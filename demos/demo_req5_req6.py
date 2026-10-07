"""
Demostración en vivo - Requisitos 5 y 6 (EntradaFlash CR).

Antes de ejecutar:  python seed_redis.py   (deja los datos en su estado inicial)
Ejecutar:           python demo_req5_req6.py
Modo presentación:  python demo_req5_req6.py --pausa   (espera Enter entre casos)

Usa los usuarios USR-00101 a USR-00130 y el evento EVT-102, que no se cruzan con
la demo de los requisitos 3 y 4. Al terminar deja el inventario como lo encontró.
"""

import argparse
import threading
import time

import redis

import rate_limit as rl
import reservas as rv
import sesiones as ss

EVENTO = "EVT-102"
ZONA_VIP, ZONA_PREMB = "VIP", "PREMB"
ZONA_AGOTADA = "DEMO-AGOTADA"
USUARIOS = [f"USR-{i:05d}" for i in range(101, 131)]
IP_OFICINA = "10.50.0.7"
TTL_CARRITO_DEMO = 10     # segundos que dura el carrito del Caso B (subirlo si hace falta)
VENTANA_D_NORMAL = 3      # ventana del Caso D al correr sin pausa
VENTANA_D_PAUSA = 20      # ventana del Caso D con --pausa (da tiempo de verlo en Redis)
VENTANA_E_F = 60          # ventana de los Casos E y F (segundos)

PAUSA = False


def titulo(texto):
    print("\n" + "-" * 72 + f"\n{texto}\n" + "-" * 72)
    if PAUSA:
        input("(Enter para continuar)")


def stock(zona):
    return rv.consultar_disponibilidad(EVENTO, zona)["disponibilidad_actual"]


def mostrar(etiqueta, res):
    detalle = {k: v for k, v in res.items()
               if k not in ("status", "reserva_id", "user_id")}
    print(f"  {etiqueta}: {res['status']}  {detalle}")


def limpiar():
    """Borra rastros de corridas anteriores (carritos, contadores, reservas)."""
    for u in USUARIOS:
        rv.r.delete(ss.clave_carrito(u))
        rl.reiniciar_limite(user_id=u)
        for zona in (ZONA_VIP, ZONA_PREMB, ZONA_AGOTADA):
            rid = rv.clave_reserva(u, EVENTO, zona)
            if rv.r.hget(rid, "estado") == "PENDIENTE":
                rv.cancelar_reserva(u, EVENTO, zona)
            rv.r.delete(rid)
    rl.reiniciar_limite(ip=IP_OFICINA)
    rv.r.delete(rv.clave_stock(EVENTO, ZONA_AGOTADA))


def preparar():
    if rv.r.get(rv.clave_stock(EVENTO, ZONA_VIP)) is None or \
            not rv.r.exists(rv.clave_usuario(USUARIOS[0])):
        raise SystemExit("No hay datos cargados. Ejecute primero: python seed_redis.py")
    limpiar()


def caso_a():
    titulo("Caso A - Armar el carrito y recuperarlo desde otro proceso")
    u = USUARIOS[0]
    mostrar("Agregar 2 VIP", ss.agregar_item(u, EVENTO, ZONA_VIP, 2))
    mostrar("Agregar 1 PREMB", ss.agregar_item(u, EVENTO, ZONA_PREMB, 1))
    mostrar("Agregar 1 VIP más", ss.agregar_item(u, EVENTO, ZONA_VIP, 1))
    mostrar("Agregar 5 VIP (supera el tope)", ss.agregar_item(u, EVENTO, ZONA_VIP, 5))
    print(f"  Stock VIP: {stock(ZONA_VIP)}  (el carrito no descuenta inventario)")
    print("\n  La aplicación se cae. Otro proceso, con su propia conexión, lee Redis:")
    otro = redis.Redis(host=rv.REDIS_HOST, port=rv.REDIS_PORT, db=rv.REDIS_DB,
                       decode_responses=True)
    print(f"    HGETALL {ss.clave_carrito(u)} -> {otro.hgetall(ss.clave_carrito(u))}")
    otro.close()
    print(f"  Carrito recuperado: {ss.ver_carrito(u, renovar=True)}")


def caso_b():
    titulo("Caso B - El carrito abandonado desaparece solo")
    u = USUARIOS[1]
    mostrar(f"Agregar 2 VIP con TTL {TTL_CARRITO_DEMO} s",
            ss.agregar_item(u, EVENTO, ZONA_VIP, 2, ttl_segundos=TTL_CARRITO_DEMO))
    for _ in range(TTL_CARRITO_DEMO + 1):
        carrito = ss.ver_carrito(u)
        print(f"    TTL restante: "
              f"{carrito['ttl_restante_s'] if carrito else 'carrito eliminado'}")
        time.sleep(1)
    print(f"  Carrito tras vencer: {ss.ver_carrito(u)}")
    print(f"  Finalizar el carrito vencido: {ss.finalizar_carrito(u)['status']}")


def caso_c():
    titulo("Caso C - Finalizar: el carrito se convierte en reservas")
    u = USUARIOS[2]
    rv.r.set(rv.clave_stock(EVENTO, ZONA_AGOTADA), 0)
    antes_vip, antes_premb = stock(ZONA_VIP), stock(ZONA_PREMB)
    ss.agregar_item(u, EVENTO, ZONA_VIP, 2)
    ss.agregar_item(u, EVENTO, ZONA_PREMB, 1)
    ss.agregar_item(u, EVENTO, ZONA_AGOTADA, 3)
    print(f"  Carrito: {ss.ver_carrito(u)['items']}")
    print(f"  Stock antes -> VIP {antes_vip}, PREMB {antes_premb}, {ZONA_AGOTADA} 0")
    res = ss.finalizar_carrito(u, ttl_segundos=30)
    print(f"  Finalizar: {res['status']}")
    for r in res["reservas"]:
        print(f"    reservado: {r['reserva_id']}  x{r['entradas_reservadas']}")
    for p in res["pendientes"]:
        print(f"    queda en el carrito: {p['zone_id']} x{p['cantidad']}  ({p['motivo']})")
    print(f"  Stock después -> VIP {stock(ZONA_VIP)} (esperado {antes_vip - 2}), "
          f"PREMB {stock(ZONA_PREMB)} (esperado {antes_premb - 1})")
    print(f"  Carrito restante: {ss.ver_carrito(u)['items']}")
    if PAUSA:
        input("  (Las reservas siguen vivas 30 s: este es el momento de mirarlas en "
              "Redis. Enter para limpiar y seguir)")
    for zona in (ZONA_VIP, ZONA_PREMB):
        rv.cancelar_reserva(u, EVENTO, zona)
        rv.r.delete(rv.clave_reserva(u, EVENTO, zona))
    rv.r.delete(ss.clave_carrito(u), rv.clave_stock(EVENTO, ZONA_AGOTADA))


def caso_d():
    ventana = VENTANA_D_PAUSA if PAUSA else VENTANA_D_NORMAL
    titulo(f"Caso D - Rate limiting por usuario: límite 5 intentos cada {ventana} s")
    u = USUARIOS[3]
    clave = rl.clave_limite_usuario(u)
    for n in range(1, 8):
        res = rl.verificar_intento(user_id=u, limite_usuario=5, ventana_segundos=ventana)
        extra = (f"restantes {res['intentos_restantes']['usuario']}"
                 if res["status"] == "EXITO"
                 else f"reintentar en {res['reintentar_en_segundos']} s")
        print(f"  Intento {n}: {res['status']}  ({extra})")
    print(f"  TTL del contador en Redis: {rv.r.pttl(clave) / 1000:.1f} s")
    if PAUSA:
        input(f"  (El contador {clave} vive {ventana} s: este es el momento de mirarlo "
              "en Redis. Enter para esperar a que venza)")
    restante = max(rv.r.pttl(clave), 0) / 1000
    print(f"  Esperando {restante:.1f} s a que Redis borre el contador...")
    time.sleep(restante + 0.2)
    res = rl.verificar_intento(user_id=u, limite_usuario=5, ventana_segundos=ventana)
    print(f"  Intento tras la ventana: {res['status']}  {res.get('intentos_restantes')}")


def caso_e():
    titulo("Caso E - Rate limiting por IP: 4 usuarios detrás de una misma IP")
    print(f"  Límite: 3 intentos por usuario y 4 por IP ({IP_OFICINA}), ventana de {VENTANA_E_F} s")
    plan = [USUARIOS[4], USUARIOS[5], USUARIOS[4], USUARIOS[6], USUARIOS[7]]
    for u in plan:
        res = rl.verificar_intento(user_id=u, ip=IP_OFICINA, limite_usuario=3,
                                   limite_ip=4, ventana_segundos=VENTANA_E_F)
        extra = (f"restantes {res['intentos_restantes']}" if res["status"] == "EXITO"
                 else f"bloqueado por {res['ambito']}")
        print(f"  {u}: {res['status']}  ({extra})")
    print("  Cada usuario respetó su propio límite, pero la IP ya agotó el suyo.")


def caso_f():
    titulo("Caso F - Un bot lanza 200 intentos simultáneos contra un límite de 20")
    u = USUARIOS[8]
    n, limite = 200, 20
    barrera = threading.Barrier(n)
    resultados = [None] * n

    def intento(i):
        barrera.wait()
        resultados[i] = rl.verificar_intento(user_id=u, limite_usuario=limite,
                                             ventana_segundos=VENTANA_E_F)

    inicio = time.perf_counter()
    hilos = [threading.Thread(target=intento, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    duracion = time.perf_counter() - inicio

    pasaron = sum(1 for r in resultados if r["status"] == "EXITO")
    print(f"  Intentos: {n}  |  permitidos: {pasaron}  |  rechazados: {n - pasaron}  "
          f"|  tiempo: {duracion * 1000:.0f} ms")
    print(f"  Contador final en Redis: {rv.r.get(rl.clave_limite_usuario(u))}  "
          f"(esperado {limite}: los rechazos no se cuentan)")
    if PAUSA:
        input(f"  (El contador {rl.clave_limite_usuario(u)} vive unos {VENTANA_E_F} s: "
              "este es el momento de mirarlo en Redis. Enter para terminar)")


def main():
    global PAUSA
    p = argparse.ArgumentParser()
    p.add_argument("--pausa", action="store_true", help="esperar Enter entre casos")
    PAUSA = p.parse_args().pausa

    print("=== DEMOSTRACIÓN REQUISITOS 5 Y 6 - EntradaFlash CR ===")
    preparar()
    try:
        caso_a()
        caso_b()
        caso_c()
        caso_d()
        caso_e()
        caso_f()
    finally:
        limpiar()
    print("\nDemostración terminada.")


if __name__ == "__main__":
    main()
