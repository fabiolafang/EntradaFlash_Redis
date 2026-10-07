"""
Prueba de concurrencia del requisito 4 (evidencia cuantitativa).

Parte 1 - Duelo controlado: muchos clientes compiten por pocas entradas.
          Se compara una versión ingenua (leer y luego descontar, sin
          atomicidad) contra la versión con script Lua.
Parte 2 - Reproducción de los intentos de reserva del dataset del grupo
          (reservation_attempts.json) en paralelo, con confirmaciones,
          cancelaciones y vencimientos mezclados. Al final se verifica que
          ninguna zona quedó negativa y que el inventario cuadra.

Ejecutar (con Redis arriba y los datos cargados con seed_redis.py):
    python prueba_concurrencia.py
    python prueba_concurrencia.py --intentos 20000 --hilos 32

La parte 2 modifica el stock real (vende entradas). Para restaurar los
datos originales, volver a ejecutar seed_redis.py.
"""

import argparse
import json
import random
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import reservas as rv

SEMILLA = 42


# ---------------------------------------------------------------------------
# Parte 1: duelo ingenuo vs. atómico
# ---------------------------------------------------------------------------

def reservar_ingenuo(stock_key, retraso):
    """Versión SIN atomicidad: lee, la aplicación decide, luego descuenta.

    El retraso simula el tiempo que la aplicación tarda entre leer y
    escribir (validaciones, red, etc.). Es exactamente la ventana en la
    que dos clientes pueden ver la misma entrada como disponible.
    """
    disponible = int(rv.r.get(stock_key))
    time.sleep(retraso)
    if disponible >= 1:
        rv.r.decrby(stock_key, 1)
        return True
    return False


def duelo(clientes, entradas, retraso):
    evento, zona = "EVT-DUELO", "DEMO"
    stock_key = rv.clave_stock(evento, zona)
    usuarios = [f"DUELO-{i:05d}" for i in range(clientes)]
    resultados = {}

    for nombre in ("Ingenua (GET + DECRBY)", "Atómica (script Lua)"):
        rv.r.set(stock_key, entradas)
        for u in usuarios:
            rv.r.set(rv.clave_usuario(u), "{}")
        barrera = threading.Barrier(clientes)

        def tarea(u):
            barrera.wait()
            if nombre.startswith("Ingenua"):
                return reservar_ingenuo(stock_key, retraso)
            return rv.crear_reserva_temporal(u, evento, zona, 1,
                                             ttl_segundos=60)["status"] == "EXITO"

        with ThreadPoolExecutor(max_workers=clientes) as ex:
            exitos = sum(ex.map(tarea, usuarios))
        resultados[nombre] = (exitos, int(rv.r.get(stock_key)))

        for u in usuarios:
            rid = rv.clave_reserva(u, evento, zona)
            rv.r.delete(rv.clave_usuario(u), rid)
            rv.r.zrem(rv.PENDIENTES_KEY, rid)
            rv.r.hdel(rv.CANTIDADES_KEY, rid)
    rv.r.delete(stock_key)

    print(f"\n{clientes} clientes simultáneos compiten por {entradas} entradas "
          f"(retraso de aplicación simulado: {retraso * 1000:.0f} ms)\n")
    print(f"{'Versión':<26}{'Reservas OK':>13}{'Stock final':>13}{'Sobreventa':>12}")
    for nombre, (exitos, final) in resultados.items():
        print(f"{nombre:<26}{exitos:>13}{final:>13}{max(0, exitos - entradas):>12}")
    return resultados


# ---------------------------------------------------------------------------
# Parte 2: reproducción del dataset
# ---------------------------------------------------------------------------

def reproducir(ruta, limite, hilos, ttl, p_confirmar, p_cancelar):
    with open(ruta, encoding="utf-8") as f:
        intentos = json.load(f)
    if limite:
        intentos = intentos[:limite]

    # Decisión de cada cliente (confirmar / cancelar / abandonar) fijada con
    # semilla para que la prueba sea reproducible.
    azar = random.Random(SEMILLA)
    acciones = []
    for _ in intentos:
        x = azar.random()
        acciones.append("confirmar" if x < p_confirmar
                        else "cancelar" if x < p_confirmar + p_cancelar
                        else "abandonar")

    zonas = sorted({(a["event_id"], a["zone_id"]) for a in intentos})
    claves = [rv.clave_stock(e, z) for e, z in zonas]
    inicial = dict(zip(zonas, map(int, rv.r.mget(claves))))

    # Monitor: observa el stock de todas las zonas durante la prueba.
    minimo = {"valor": min(inicial.values())}
    terminar = threading.Event()

    def monitor():
        while not terminar.is_set():
            valores = [int(v) for v in rv.r.mget(claves)]
            minimo["valor"] = min(minimo["valor"], *valores)
            time.sleep(0.005)

    resultados = Counter()
    motivos = Counter()
    vendidas = defaultdict(int)
    candado = threading.Lock()
    latencias = []

    def ejecutar(i):
        a = intentos[i]
        t0 = time.perf_counter()
        res = rv.crear_reserva_temporal(a["user_id"], a["event_id"], a["zone_id"],
                                        a["quantity"], ttl_segundos=ttl)
        lat = (time.perf_counter() - t0) * 1000
        local = []
        if res["status"] == "EXITO":
            accion = acciones[i]
            if accion == "confirmar":
                c = rv.confirmar_reserva(a["user_id"], a["event_id"], a["zone_id"])
                local.append(("confirmada" if c["status"] == "EXITO"
                              else "confirmación rechazada", c))
            elif accion == "cancelar":
                c = rv.cancelar_reserva(a["user_id"], a["event_id"], a["zone_id"])
                local.append(("cancelada" if c["status"] == "EXITO"
                              else "cancelación rechazada", c))
            else:
                local.append(("abandonada (vence sola)", None))
        else:
            local.append(("reserva rechazada", res))
        with candado:
            latencias.append(lat)
            for etiqueta, detalle in local:
                resultados[etiqueta] += 1
                if etiqueta == "reserva rechazada":
                    motivos[detalle["motivo"]] += 1
                if etiqueta == "confirmada":
                    vendidas[(a["event_id"], a["zone_id"])] += a["quantity"]

    hilo_monitor = threading.Thread(target=monitor, daemon=True)
    hilo_monitor.start()
    liberador = rv.iniciar_liberador(intervalo=0.2)

    print(f"\nReproduciendo {len(intentos):,} intentos con {hilos} hilos "
          f"(TTL {ttl}s; confirma {p_confirmar:.0%}, cancela {p_cancelar:.0%}, "
          f"abandona {1 - p_confirmar - p_cancelar:.0%})...")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        list(ex.map(ejecutar, range(len(intentos))))
    duracion = time.perf_counter() - t0

    # Esperar a que venzan las reservas abandonadas y se liberen.
    time.sleep(ttl + 0.5)
    liberador.detener()
    rv.liberar_reservas_vencidas()
    terminar.set()
    hilo_monitor.join()

    final = dict(zip(zonas, map(int, rv.r.mget(claves))))

    # Verificación independiente: vendidas según Redis (no según el cliente).
    vendidas_redis = defaultdict(int)
    for clave in rv.r.scan_iter(match="reservation:*", count=1000):
        datos = rv.r.hgetall(clave)
        if datos.get("estado") == "CONFIRMADA":
            vendidas_redis[(datos["event_id"], datos["zone_id"])] += int(datos["cantidad"])

    latencias.sort()
    print(f"\nTiempo total: {duracion:.2f} s  |  "
          f"Rendimiento: {len(intentos) / duracion:,.0f} intentos/s")
    print(f"Latencia de crear_reserva_temporal: p50 {latencias[len(latencias) // 2]:.2f} ms, "
          f"p95 {latencias[int(len(latencias) * .95)]:.2f} ms, "
          f"p99 {latencias[int(len(latencias) * .99)]:.2f} ms")

    print("\nResultado de los intentos:")
    for etiqueta, n in resultados.most_common():
        print(f"  {etiqueta:<28}{n:>9,}")
    print("Motivos de rechazo al reservar:")
    for motivo, n in motivos.most_common():
        print(f"  {motivo:<58}{n:>9,}")

    print(f"\n{'Zona':<20}{'Inicial':>9}{'Vendidas':>10}{'Final':>8}"
          f"{'Inicial-Vendidas':>18}{'Cuadra':>8}")
    todo_cuadra = True
    for zona in zonas:
        esperado = inicial[zona] - vendidas[zona]
        cuadra = (final[zona] == esperado and vendidas[zona] == vendidas_redis[zona]
                  and final[zona] >= 0)
        todo_cuadra &= cuadra
        print(f"{zona[0] + ' ' + zona[1]:<20}{inicial[zona]:>9}{vendidas[zona]:>10}"
              f"{final[zona]:>8}{esperado:>18}{'sí' if cuadra else 'NO':>8}")

    pendientes = rv.r.zcard(rv.PENDIENTES_KEY)
    print(f"\nStock mínimo observado durante la prueba: {minimo['valor']}")
    print(f"Reservas pendientes sin liberar al final: {pendientes}")
    print(f"Total vendido: {sum(vendidas.values()):,} entradas "
          f"(según Redis: {sum(vendidas_redis.values()):,})")
    print("\nVEREDICTO:", "inventario consistente, sin sobreventa ni stock negativo"
          if todo_cuadra and minimo["valor"] >= 0 and pendientes == 0
          else "SE DETECTÓ UNA INCONSISTENCIA")
    print("\nNota: esta prueba vendió entradas reales del dataset. "
          "Ejecute seed_redis.py para restaurar el inventario original.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--archivo", default="reservation_attempts.json")
    p.add_argument("--intentos", type=int, default=0,
                   help="cuántos intentos reproducir (0 = todos)")
    p.add_argument("--hilos", type=int, default=64)
    p.add_argument("--ttl", type=float, default=2.0)
    p.add_argument("--confirmar", type=float, default=0.5)
    p.add_argument("--cancelar", type=float, default=0.2)
    p.add_argument("--solo-duelo", action="store_true")
    args = p.parse_args()

    rv.r.ping()
    print("=" * 72)
    print("PARTE 1 - Duelo: versión ingenua vs. versión atómica")
    print("=" * 72)
    duelo(clientes=300, entradas=50, retraso=0.002)

    if not args.solo_duelo:
        print("\n" + "=" * 72)
        print("PARTE 2 - Reproducción de reservation_attempts.json")
        print("=" * 72)
        reproducir(args.archivo, args.intentos, args.hilos, args.ttl,
                   args.confirmar, args.cancelar)


if __name__ == "__main__":
    main()
