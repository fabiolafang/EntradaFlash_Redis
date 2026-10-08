"""
EntradaFlash CR - Prueba de caída del servicio (resiliencia, Persona 4).
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import redis

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA))
from benchmark_req7 import Proyecto, RESULTADOS  # noqa: E402  (mismo adaptador del benchmark)

EVENTO, ZONA = "EVT-CAIDA", "DEMO"
STOCK_INICIAL = 100
VENTAS, PENDIENTES, CANTIDAD = 10, 5, 2
TTL_PENDIENTE = 15


def stock_key():
    return f"event:{EVENTO}:zone:{ZONA}:stock"


def usuario(i):
    return f"CAIDA-{i:03d}"


def ruta_estado(etiqueta):
    return RESULTADOS / f"caida_{etiqueta}.json"


def limpiar(app):
    r = app.r
    claves = list(r.scan_iter(match="*CAIDA*", count=1000)) + [stock_key(), "caida:marcador"]
    if claves:
        r.delete(*claves)
    for m in r.zrange("reservations:pending", 0, -1):
        if "CAIDA-" in m:
            r.zrem("reservations:pending", m)
            r.hdel("reservations:pending:qty", m)


def config_persistencia(r):
    try:
        cfg = {}
        for c in ("save", "appendonly", "appendfsync"):
            cfg.update(r.config_get(c))
        return cfg
    except redis.ResponseError:
        return {}


def preparar(app, etiqueta):
    r = app.r
    limpiar(app)
    r.set(stock_key(), STOCK_INICIAL)
    for i in range(VENTAS + PENDIENTES):
        r.set(f"user:{usuario(i)}", "{}")
    for i in range(VENTAS):
        res = app.mod.crear_reserva_temporal(usuario(i), EVENTO, ZONA, CANTIDAD, ttl_segundos=60)
        assert res.get("status") == "EXITO", res
        assert app.confirmar(usuario(i), EVENTO, ZONA).get("status") == "EXITO"
    for i in range(VENTAS, VENTAS + PENDIENTES):
        res = app.mod.crear_reserva_temporal(usuario(i), EVENTO, ZONA, CANTIDAD,
                                             ttl_segundos=TTL_PENDIENTE)
        assert res.get("status") == "EXITO", res
  
    carrito_antes = None
    if app.sesiones is not None:
        app.sesiones.agregar_item(usuario(0), EVENTO, ZONA, 3)
        carrito_antes = app.sesiones.ver_carrito(usuario(0))["total_entradas"]
    ahora = time.time()
    r.set("caida:marcador", dt.datetime.now().isoformat(timespec="seconds"))

    estado = {
        "etiqueta": etiqueta,
        "modulo": app.nombre + ".py",
        "preparado_en": ahora,
        "persistencia": config_persistencia(r),
        "antes": {
            "claves_totales": r.dbsize(),
            "stock_demo": int(r.get(stock_key())),
            "stock_vip_evt101": r.get("event:EVT-101:zone:VIP:stock"),
            "usuarios_dataset": r.exists("user:USR-00001", "user:USR-50000"),
            "confirmadas": VENTAS,
            "pendientes": PENDIENTES,
            "carrito_entradas": carrito_antes,
        },
    }
    ruta_estado(etiqueta).parent.mkdir(exist_ok=True)
    ruta_estado(etiqueta).write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Persistencia actual de Redis: {estado['persistencia']}")
    print(f"Escenario listo: stock {estado['antes']['stock_demo']} "
          f"(inicial {STOCK_INICIAL}, {VENTAS * CANTIDAD} vendidas, "
          f"{PENDIENTES * CANTIDAD} apartadas en reservas pendientes de {TTL_PENDIENTE} s)")
    print(f"Claves totales en Redis: {estado['antes']['claves_totales']:,}")
    return estado


def esperar_redis(r, segundos=60):
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            r.ping()
            return True
        except (redis.ConnectionError, redis.BusyLoadingError, redis.TimeoutError):
            time.sleep(0.5)
    return False


def verificar(app, etiqueta, segundos_caido=None):
    r = app.r
    estado = json.loads(ruta_estado(etiqueta).read_text(encoding="utf-8"))
    if not esperar_redis(r):
        raise SystemExit("Redis no respondió después de reiniciar.")

    confirmadas = sum(1 for i in range(VENTAS)
                      if r.hget(f"reservation:{usuario(i)}:{EVENTO}:{ZONA}", "estado") == "CONFIRMADA")
    pendientes_vivas = sum(1 for i in range(VENTAS, VENTAS + PENDIENTES)
                           if r.exists(f"reservation:{usuario(i)}:{EVENTO}:{ZONA}"))
    stock_tras = r.get(stock_key())
    despues = {
        "claves_totales": r.dbsize(),
        "stock_demo": None if stock_tras is None else int(stock_tras),
        "stock_vip_evt101": r.get("event:EVT-101:zone:VIP:stock"),
        "usuarios_dataset": r.exists("user:USR-00001", "user:USR-50000"),
        "confirmadas": confirmadas,
        "pendientes": pendientes_vivas,
        "marcador": r.get("caida:marcador"),
        "carrito_entradas": None,
    }
    if app.sesiones is not None and estado["antes"].get("carrito_entradas") is not None:
        carrito = app.sesiones.ver_carrito(usuario(0))
        despues["carrito_entradas"] = carrito["total_entradas"] if carrito else 0

    
    stock_final = None
    nota_liberacion = ""
    if despues["stock_demo"] is not None:
        falta = estado["preparado_en"] + TTL_PENDIENTE + 1 - time.time()
        if falta > 0:
            print(f"Esperando {falta:.0f} s a que venzan las reservas pendientes...")
            time.sleep(falta)
        if hasattr(app.mod, "liberar_reservas_vencidas"):
            liberadas = app.mod.liberar_reservas_vencidas()
            nota_liberacion = (f"El liberador devolvió {sum(c for _, c in liberadas)} entradas "
                               f"de {len(liberadas)} reservas vencidas.")
        else:
            nota_liberacion = ("Este módulo no tiene liberador automático: al vencer el TTL "
                               "Redis borra la reserva pero el stock NO se devuelve.")
        stock_final = int(r.get(stock_key()))

    a = estado["antes"]
    esperado_final = STOCK_INICIAL - VENTAS * CANTIDAD
    filas = [
        ("Claves totales en Redis", f"{a['claves_totales']:,}", f"{despues['claves_totales']:,}"),
        ("Dataset (usuarios de prueba presentes, de 2)", a["usuarios_dataset"], despues["usuarios_dataset"]),
        ("Stock VIP EVT-101", a["stock_vip_evt101"], despues["stock_vip_evt101"]),
        ("Ventas confirmadas (de 10)", a["confirmadas"], despues["confirmadas"]),
        ("Reservas pendientes vivas (de 5)", a["pendientes"], despues["pendientes"]),
        ("Stock zona demo", a["stock_demo"], despues["stock_demo"]),
        ("Entradas en el carrito abierto (req. 5)", a.get("carrito_entradas", "-"),
         despues["carrito_entradas"] if a.get("carrito_entradas") is not None else "-"),
        (f"Stock zona demo tras vencer las pendientes (correcto: {esperado_final})", "-", stock_final),
    ]

    if despues["claves_totales"] == 0:
        veredicto = ("SE PERDIÓ TODO: Redis reinició vacío. Habría que recargar el inventario "
                     "desde otra fuente y las ventas confirmadas desaparecieron "
                     "(riesgo directo de sobreventa).")
    elif despues["stock_demo"] is None:
        veredicto = (f"PÉRDIDA PARCIAL: Redis volvió con el último snapshot "
                     f"({despues['claves_totales']:,} claves), pero se perdieron las {VENTAS} ventas "
                     "confirmadas y las reservas hechas después de ese snapshot. Esas entradas "
                     "aparecerían otra vez como disponibles (riesgo de sobreventa).")
    elif confirmadas < VENTAS:
        veredicto = (f"PÉRDIDA PARCIAL: sobrevivieron {confirmadas} de {VENTAS} ventas confirmadas "
                     "(se perdió lo escrito después del último guardado).")
    elif stock_final != esperado_final:
        veredicto = (f"Los datos sobrevivieron, pero el inventario quedó en {stock_final} en vez de "
                     f"{esperado_final}: {esperado_final - stock_final} entradas quedaron atrapadas "
                     "en reservas que vencieron sin devolver su stock.")
    else:
        veredicto = ("SIN PÉRDIDA: sobrevivieron todas las ventas y el inventario quedó correcto "
                     "después de liberar las reservas vencidas.")

    print("\n| Dato | Antes de la caída | Después de reiniciar |\n|---|---:|---:|")
    for nombre, antes, desp in filas:
        print(f"| {nombre} | {antes} | {desp} |")
    print(f"\n{nota_liberacion}\nVEREDICTO: {veredicto}")

    md = [f"# Prueba de caída - {etiqueta}", "",
          f"Fecha: {dt.datetime.now():%Y-%m-%d %H:%M}  ",
          f"Módulo: `{estado['modulo']}`  ",
          f"Persistencia de Redis: `{estado['persistencia']}`  "]
    if segundos_caido is not None:
        md.append(f"Tiempo desde preparar hasta la caída: {segundos_caido:.1f} s  ")
    md += ["", "| Dato | Antes de la caída | Después de reiniciar |", "|---|---:|---:|"]
    md += [f"| {n} | {x} | {y} |" for n, x, y in filas]
    md += ["", nota_liberacion, "", f"**Veredicto:** {veredicto}", ""]
    salida = RESULTADOS / f"caida_{etiqueta}.md"
    salida.write_text("\n".join(md), encoding="utf-8")
    print(f"\nResultado guardado en {salida.relative_to(RESULTADOS.parent)}")
    limpiar(app)


def docker(*args):
    print("$ docker " + " ".join(args))
    subprocess.run(["docker", *args], check=True, capture_output=True)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=["preparar", "verificar", "completo"])
    p.add_argument("--etiqueta", required=True,
                   help="nombre de la configuración probada, p. ej. sin-persistencia, rdb, aof-everysec")
    p.add_argument("--contenedor", default="entradaflash-redis", help="contenedor Docker de Redis")
    p.add_argument("--espera", type=float, default=2.0,
                   help="segundos entre preparar y la caída (completo)")
    p.add_argument("--modulo", choices=["funciones", "reservas"])
    args = p.parse_args()

    app = Proyecto(args.modulo)
    if args.accion in ("preparar", "completo"):
        if not esperar_redis(app.r, 5):
            raise SystemExit("No se pudo conectar a Redis.")
        preparar(app, args.etiqueta)
    if args.accion == "preparar":
        print("\nAhora simule la caída:\n"
              f"  kill -9 <pid de redis>  (o docker kill {args.contenedor}) y volver a levantarlo\n"
              f"y luego ejecute:\n  python prueba_caida.py verificar --etiqueta {args.etiqueta}")
    elif args.accion == "completo":
        time.sleep(args.espera)
        print(f"\nSimulando caída abrupta tras {args.espera:.1f} s...")
        docker("kill", args.contenedor)
        docker("start", args.contenedor)
        app.r.connection_pool.disconnect()
        verificar(app, args.etiqueta, segundos_caido=args.espera)
    else:
        verificar(app, args.etiqueta)


if __name__ == "__main__":
    main()
