"""
EntradaFlash CR - Requisito 7: medición de latencia y rendimiento.

"""

import argparse
import csv
import datetime as dt
import glob
import importlib
import inspect
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import redis

CARPETA = Path(__file__).resolve().parent
# Si el script está en pruebas/ del repo, los resultados van a resultados/ en la raíz.
RESULTADOS = (CARPETA.parent if CARPETA.name == "pruebas" else CARPETA) / "resultados"


def _buscar_proyecto():

    candidatas = [os.environ.get("PROYECTO_DIR"), CARPETA.parent / "src", CARPETA,
                  Path.home() / "Documents" / "GitHub" / "EntradaFlash_Redis" / "src"]
    for c in candidatas:
        if c and (Path(c) / "reservas.py").exists():
            return Path(c).resolve()
    raise SystemExit("No encontré src/reservas.py. Indique la carpeta con:\n"
                     "  export PROYECTO_DIR=/ruta/a/EntradaFlash_Redis/src")


PROYECTO = None

EVENTO = "EVT-BENCH"
STOCK_GRANDE = 10 ** 9          # el benchmark nunca se queda sin entradas
TTL_RESERVA = 300               # las reservas de prueba no vencen durante la medición



class Proyecto:
    def __init__(self, nombre_modulo=None):
        global PROYECTO
        PROYECTO = _buscar_proyecto()
        legado = PROYECTO.parent / "legado"
        for ruta in (PROYECTO, legado):
            if str(ruta) not in sys.path:
                sys.path.insert(0, str(ruta))
        self.nombre = nombre_modulo or "reservas"
        self.mod = importlib.import_module(self.nombre)
        self.r = self.mod.r
        params = inspect.signature(self.mod.cancelar_reserva).parameters
        self._cancelar_pide_cantidad = "cantidad" in params
        # Requisitos 5 y 6 (Persona 3). Solo existen junto a reservas.py.
        self.sesiones = self.rate_limit = None
        if self.nombre == "reservas":
            for nombre in ("sesiones", "rate_limit"):
                try:
                    setattr(self, nombre, importlib.import_module(nombre))
                except ImportError:
                    pass

    def consultar(self, evento, zona):
        return self.mod.consultar_disponibilidad(evento, zona)

    def crear(self, usuario, evento, zona, cantidad=1):
        return self.mod.crear_reserva_temporal(usuario, evento, zona, cantidad,
                                               ttl_segundos=TTL_RESERVA)

    def confirmar(self, usuario, evento, zona):
        return self.mod.confirmar_reserva(usuario, evento, zona)

    def cancelar(self, usuario, evento, zona, cantidad=1):
        if self._cancelar_pide_cantidad:
            return self.mod.cancelar_reserva(usuario, evento, zona, cantidad)
        return self.mod.cancelar_reserva(usuario, evento, zona)


def exito(res):
    if isinstance(res, dict):
        return res.get("status", "EXITO") == "EXITO" and "error" not in res
    return res is not None



class Contador:
    """Genera usuarios de prueba únicos (cada reserva necesita un usuario nuevo,
    porque un usuario solo puede tener una reserva por zona)."""

    def __init__(self):
        self.n = 0
        self._candado = threading.Lock()

    def nuevos(self, cantidad):
        with self._candado:
            inicio = self.n
            self.n += cantidad
        return [f"BENCH-{i:07d}" for i in range(inicio, inicio + cantidad)]


def crear_usuarios(app, usuarios):
    with app.r.pipeline(transaction=False) as p:
        for u in usuarios:
            p.set(f"user:{u}", "{}")
        p.execute()


def preparar_zona(app, zona):
    app.r.set(f"event:{EVENTO}:zone:{zona}:stock", STOCK_GRANDE)


def limpiar(app):
    patrones = [f"event:{EVENTO}:*", "user:BENCH-*", "reservation:BENCH-*", "bench:*",
                "cart:BENCH-*", "rate_limit:BENCH-*", "rate_limit:ip:10.255.*"]
    for patron in patrones:
        lote = []
        for clave in app.r.scan_iter(match=patron, count=5000):
            lote.append(clave)
            if len(lote) >= 5000:
                app.r.unlink(*lote)
                lote = []
        if lote:
            app.r.unlink(*lote)
    # Registro de pendientes de reservas.py (si existe)
    for zset, hset in (("reservations:pending", "reservations:pending:qty"),):
        miembros = [m for m in app.r.zrange(zset, 0, -1) if "BENCH-" in m]
        for i in range(0, len(miembros), 5000):
            app.r.zrem(zset, *miembros[i:i + 5000])
            app.r.hdel(hset, *miembros[i:i + 5000])


def operaciones(app, contador):
    r = app.r
    ops = []

    preparar_zona(app, "BASE")
    clave_base = f"event:{EVENTO}:zone:BASE:stock"
    ops.append(dict(
        nombre="GET stock (Redis directo)", tipo="lectura", req="base",
        preparar=lambda k: [None] * k,
        ejecutar=lambda _: r.get(clave_base)))
    ops.append(dict(
        nombre="SET clave (Redis directo)", tipo="escritura", req="base",
        preparar=lambda k: list(range(k)),
        ejecutar=lambda i: r.set(f"bench:set:{i % 1000}", "x")))
    ops.append(dict(
        nombre="DECRBY stock (Redis directo)", tipo="atómica", req="base",
        preparar=lambda k: [None] * k,
        ejecutar=lambda _: r.decrby(clave_base, 1)))

   
    preparar_zona(app, "R1")
    ops.append(dict(
        nombre="consultar_disponibilidad", tipo="lectura", req="R1",
        preparar=lambda k: [None] * k,
        ejecutar=lambda _: app.consultar(EVENTO, "R1")))

    preparar_zona(app, "R2")

    def prep_crear(k):
        usuarios = contador.nuevos(k)
        crear_usuarios(app, usuarios)
        return usuarios
    ops.append(dict(
        nombre="crear_reserva_temporal", tipo="escritura + atómica", req="R2/R4",
        preparar=prep_crear,
        ejecutar=lambda u: app.crear(u, EVENTO, "R2")))

    for zona, nombre, accion in (("R3C", "confirmar_reserva", app.confirmar),
                                 ("R3X", "cancelar_reserva", app.cancelar)):
        preparar_zona(app, zona)

        def prep_con_reserva(k, zona=zona):
            usuarios = contador.nuevos(k)
            crear_usuarios(app, usuarios)
            for u in usuarios:
                app.crear(u, EVENTO, zona)
            return usuarios
        ops.append(dict(
            nombre=nombre, tipo="atómica", req="R3/R4",
            preparar=prep_con_reserva,
            ejecutar=lambda u, zona=zona, accion=accion: accion(u, EVENTO, zona)))

    ops.extend(operaciones_persona_3(app, contador))
    return ops


def ip_bench(usuario):
    """IP única por usuario de prueba (10.255.x.y) para no chocar con el límite por IP."""
    n = int(usuario.split("-")[1])
    return f"10.255.{n // 250 % 250}.{n % 250 + 1}"


def operaciones_persona_3(app, contador):
    """
    Claves que usan: cart:{usuario}, rate_limit:{usuario}, rate_limit:ip:{ip}.
    Cada operación usa un usuario de prueba nuevo, para que no choque con el
    tope de 6 entradas por zona del carrito ni con el límite de intentos.
    """
    ops = []
    ses, rl = app.sesiones, app.rate_limit

    if ses is not None:
        preparar_zona(app, "R5")

        def prep_usuarios(k):
            usuarios = contador.nuevos(k)
            crear_usuarios(app, usuarios)
            return usuarios

        def prep_con_carrito(k):
            usuarios = prep_usuarios(k)
            for u in usuarios:
                ses.agregar_item(u, EVENTO, "R5", 2)
            return usuarios

        ops.append(dict(
            nombre="agregar_item (carrito)", tipo="escritura + atómica", req="R5",
            preparar=prep_usuarios,
            ejecutar=lambda u: ses.agregar_item(u, EVENTO, "R5", 1)))
        ops.append(dict(
            nombre="ver_carrito", tipo="lectura", req="R5",
            preparar=prep_con_carrito,
            ejecutar=lambda u: ses.ver_carrito(u)))

    if rl is not None:
        def prep_intentos(k):
            return contador.nuevos(k)

        ops.append(dict(
            nombre="verificar_intento (usuario + IP)", tipo="atómica", req="R6",
            preparar=prep_intentos,
            ejecutar=lambda u: rl.verificar_intento(u, ip_bench(u))))

    return ops


def percentil(datos_ordenados, p):
    if not datos_ordenados:
        return float("nan")
    idx = min(len(datos_ordenados) - 1, max(0, round(p / 100 * len(datos_ordenados)) - 1))
    return datos_ordenados[idx]


def resumir(latencias_ms):
    s = sorted(latencias_ms)
    return {
        "promedio_ms": statistics.fmean(s),
        "p50_ms": percentil(s, 50),
        "p95_ms": percentil(s, 95),
        "p99_ms": percentil(s, 99),
        "max_ms": s[-1],
        "ops_por_s": len(s) / (sum(s) / 1000),
    }



def fase_latencia(ops, n, calentamiento, repeticiones):
    filas = []
    for op in ops:
        por_rep = []
        exitosas = total = 0
        for rep in range(repeticiones):
            args = op["preparar"](calentamiento + n)
            for a in args[:calentamiento]:
                op["ejecutar"](a)
            lat = []
            for a in args[calentamiento:]:
                t0 = time.perf_counter()
                res = op["ejecutar"](a)
                lat.append((time.perf_counter() - t0) * 1000)
                total += 1
                exitosas += exito(res) if op["req"] != "base" else 1
            por_rep.append(resumir(lat))
        fila = {"operacion": op["nombre"], "tipo": op["tipo"], "requisito": op["req"],
                "n": n, "repeticiones": repeticiones}
        for campo in por_rep[0]:
            fila[campo] = statistics.median(r[campo] for r in por_rep)
        fila["exitosas_pct"] = 100 * exitosas / total
        filas.append(fila)
        print(f"  {op['nombre']:<30} p50 {fila['p50_ms']:.3f} ms   "
              f"p99 {fila['p99_ms']:.3f} ms   {fila['ops_por_s']:,.0f} ops/s")
    return filas

def fase_concurrencia(ops, niveles, total_ops):
    elegidas = [op for op in ops if op["nombre"] in (
        "GET stock (Redis directo)", "consultar_disponibilidad",
        "crear_reserva_temporal", "confirmar_reserva",
        "agregar_item (carrito)", "verificar_intento (usuario + IP)")]
    filas = []
    for op in elegidas:
        for hilos in niveles:
            args = op["preparar"](total_ops)
            lat = [0.0] * total_ops
            oks = [False] * total_ops

            def tarea(i):
                t0 = time.perf_counter()
                res = op["ejecutar"](args[i])
                lat[i] = (time.perf_counter() - t0) * 1000
                oks[i] = exito(res) if op["req"] != "base" else True

            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=hilos) as ex:
                list(ex.map(tarea, range(total_ops)))
            duracion = time.perf_counter() - t0
            s = sorted(lat)
            fila = {"operacion": op["nombre"], "hilos": hilos, "operaciones": total_ops,
                    "duracion_s": duracion, "ops_por_s": total_ops / duracion,
                    "p50_ms": percentil(s, 50), "p99_ms": percentil(s, 99),
                    "exitosas_pct": 100 * sum(oks) / total_ops}
            filas.append(fila)
            print(f"  {op['nombre']:<30} {hilos:>3} hilos  {fila['ops_por_s']:>9,.0f} ops/s   "
                  f"p99 {fila['p99_ms']:.2f} ms   éxito {fila['exitosas_pct']:.1f} %")
    return filas



def _cmd(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def entorno(app, args):
    info = app.r.info("server")
    persist = app.r.info("persistence")
    try:
        config = {k: v for c in ("save", "appendonly", "appendfsync")
                  for k, v in app.r.config_get(c).items()}
    except redis.ResponseError:
        config = {}
    cpu = (_cmd("sysctl", "-n", "machdep.cpu.brand_string")
           or _cmd("sh", "-c", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2")
           or platform.processor())
    ram = _cmd("sysctl", "-n", "hw.memsize")
    if not ram:
        try:
            ram = str(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (ValueError, OSError, AttributeError):
            ram = ""
    return {
        "fecha": dt.datetime.now().isoformat(timespec="seconds"),
        "etiqueta": args.etiqueta,
        "sistema": platform.platform(),
        "cpu": cpu.strip(),
        "nucleos": os.cpu_count(),
        "ram_gb": round(int(ram) / 1024 ** 3, 1) if ram.isdigit() else None,
        "python": platform.python_version(),
        "redis_py": redis.__version__,
        "redis_version": info.get("redis_version"),
        "redis_modo": info.get("redis_mode"),
        "redis_os": info.get("os"),
        "conexion": app.r.connection_pool.connection_kwargs.get("host", "?") + ":" +
                    str(app.r.connection_pool.connection_kwargs.get("port", "?")),
        "persistencia_config": config,
        "aof_activo": persist.get("aof_enabled"),
        "claves_en_redis": app.r.dbsize(),
        "modulo_proyecto": app.nombre + ".py",
        "carpeta_proyecto": str(PROYECTO),
        "parametros": {"n": args.n, "calentamiento": args.calentamiento,
                       "repeticiones": args.repeticiones, "hilos": args.hilos,
                       "ops_concurrencia": args.ops_concurrencia},
    }



def guardar_csv(ruta, filas):
    if not filas:
        return
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        for fila in filas:
            w.writerow({k: round(v, 4) if isinstance(v, float) else v for k, v in fila.items()})


def guardar_resumen(ruta, env, lat, conc):
    L = [f"# Resultados requisito 7 - {env['etiqueta']}", "",
         f"Fecha: {env['fecha']}  ",
         f"Equipo: {env['cpu']}, {env['nucleos']} núcleos, {env['ram_gb']} GB RAM, {env['sistema']}  ",
         f"Redis {env['redis_version']} ({env['redis_modo']}) en {env['conexion']}; "
         f"Python {env['python']}, redis-py {env['redis_py']}  ",
         f"Persistencia: {env['persistencia_config']}  ",
         f"Módulo del proyecto medido: `{env['modulo_proyecto']}`; claves en Redis: {env['claves_en_redis']:,}  ",
         f"Parámetros: {env['parametros']}", "",
         "## Latencia (1 cliente, mediana de las repeticiones)", "",
         "| Operación | Tipo | Req. | Promedio (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/s | Éxito |",
         "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for f in lat:
        L.append(f"| {f['operacion']} | {f['tipo']} | {f['requisito']} | {f['promedio_ms']:.3f} | "
                 f"{f['p50_ms']:.3f} | {f['p95_ms']:.3f} | {f['p99_ms']:.3f} | "
                 f"{f['ops_por_s']:,.0f} | {f['exitosas_pct']:.0f} % |")
    if conc:
        L += ["", "## Rendimiento con clientes concurrentes", "",
              "| Operación | Hilos | ops/s | p50 (ms) | p99 (ms) | Éxito |",
              "|---|---:|---:|---:|---:|---:|"]
        for f in conc:
            L.append(f"| {f['operacion']} | {f['hilos']} | {f['ops_por_s']:,.0f} | "
                     f"{f['p50_ms']:.3f} | {f['p99_ms']:.3f} | {f['exitosas_pct']:.1f} % |")
    Path(ruta).write_text("\n".join(L) + "\n", encoding="utf-8")


def comparar(carpetas):
    """Tabla p50 / p99 por operación entre varias corridas (p. ej. sin AOF vs AOF)."""
    corridas = []
    for c in sorted(carpetas):
        c = Path(c)
        if not (c / "latencia.csv").exists():
            continue
        env = json.loads((c / "entorno.json").read_text(encoding="utf-8"))
        with open(c / "latencia.csv", encoding="utf-8") as f:
            corridas.append((env.get("etiqueta") or c.name, list(csv.DictReader(f))))
    if not corridas:
        print("No se encontraron corridas con latencia.csv")
        return
    orden = ["sin-persistencia", "rdb", "aof-everysec", "aof-always"]
    corridas.sort(key=lambda c: orden.index(c[0]) if c[0] in orden else len(orden))
    nombres = [n for n, _ in corridas]
    print("| Operación | " + " | ".join(f"{n} p50 / p99 (ms)" for n in nombres) + " |")
    print("|---|" + "---:|" * len(nombres))
    for i, fila in enumerate(corridas[0][1]):
        celdas = []
        for _, filas in corridas:
            f = next((x for x in filas if x["operacion"] == fila["operacion"]), None)
            celdas.append(f"{float(f['p50_ms']):.3f} / {float(f['p99_ms']):.3f}" if f else "-")
        print(f"| {fila['operacion']} | " + " | ".join(celdas) + " |")




def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--modulo", choices=["reservas", "funciones"],
                   help="reservas = versión oficial (src/); funciones = versión anterior (legado/)")
    p.add_argument("--etiqueta", default="base", help="nombre de la corrida (p. ej. sin-persistencia)")
    p.add_argument("-n", type=int, default=5000)
    p.add_argument("--calentamiento", type=int, default=500)
    p.add_argument("--repeticiones", type=int, default=3)
    p.add_argument("--hilos", type=int, nargs="+", default=[1, 8, 32, 64])
    p.add_argument("--ops-concurrencia", type=int, default=10000)
    p.add_argument("--sin-concurrencia", action="store_true")
    p.add_argument("--rapido", action="store_true", help="corrida corta para verificar")
    p.add_argument("--comparar", nargs="+", metavar="CARPETA")
    args = p.parse_args()

    if args.comparar:
        comparar([c for patron in args.comparar for c in glob.glob(patron)])
        return
    if args.rapido:
        args.n, args.calentamiento, args.repeticiones = 300, 50, 1
        args.hilos, args.ops_concurrencia = [1, 16], 1000

    app = Proyecto(args.modulo)
    try:
        app.r.ping()
    except redis.ConnectionError as e:
        raise SystemExit(f"No se pudo conectar a Redis: {e}\n¿Está corriendo Redis en el puerto del proyecto?")
    if app.r.get("event:EVT-101:zone:VIP:stock") is None:
        print("AVISO: no se encontraron los datos del proyecto. Ejecute primero: cd datos && python3 seed_redis.py")

    destino = RESULTADOS / f"{dt.datetime.now():%Y%m%d_%H%M}_{args.etiqueta}"
    destino.mkdir(parents=True, exist_ok=True)
    env = entorno(app, args)
    print(f"Módulo: {app.nombre}.py | Redis {env['redis_version']} en {env['conexion']} | "
          f"persistencia {env['persistencia_config']}")

    limpiar(app)
    contador = Contador()
    try:
        ops = operaciones(app, contador)
        print(f"\nFase 1 - Latencia ({args.n} ops x {args.repeticiones} repeticiones, 1 cliente)")
        lat = fase_latencia(ops, args.n, args.calentamiento, args.repeticiones)
        conc = []
        if not args.sin_concurrencia:
            print(f"\nFase 2 - Concurrencia ({args.ops_concurrencia} ops por nivel)")
            conc = fase_concurrencia(ops, args.hilos, args.ops_concurrencia)
    finally:
        limpiar(app)

    (destino / "entorno.json").write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")
    guardar_csv(destino / "latencia.csv", lat)
    guardar_csv(destino / "rendimiento.csv", conc)
    guardar_resumen(destino / "resumen.md", env, lat, conc)
    print(f"\nResultados guardados en {destino.relative_to(RESULTADOS.parent)}/")


if __name__ == "__main__":
    main()
