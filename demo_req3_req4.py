"""
Demostración en vivo - Requisitos 3 y 4 (EntradaFlash CR).

Antes de ejecutar:  python seed_redis.py   (deja el inventario en su estado inicial)
Ejecutar:           python demo_req3_req4.py
Modo presentación:  python demo_req3_req4.py --pausa   (espera Enter entre casos)
"""

import argparse
import threading
import time

import reservas as rv

EVENTO = "EVT-101"
ZONA = "VIP"
USUARIOS = {c: f"USR-0000{i}" for i, c in enumerate("ABCDEF", start=1)}

PAUSA = False


def titulo(texto):
    print("\n" + "-" * 72 + f"\n{texto}\n" + "-" * 72)
    if PAUSA:
        input("(Enter para continuar)")


def stock(evento=EVENTO, zona=ZONA):
    return rv.consultar_disponibilidad(evento, zona)["disponibilidad_actual"]


def mostrar(etiqueta, res):
    estado = res["status"]
    detalle = {k: v for k, v in res.items() if k not in ("status", "reserva_id")}
    print(f"  {etiqueta}: {estado}  {detalle}")


def preparar():
    """Verifica que los datos estén cargados y limpia corridas anteriores de la demo."""
    if rv.r.get(rv.clave_stock(EVENTO, ZONA)) is None or \
            not rv.r.exists(rv.clave_usuario(USUARIOS["A"])):
        raise SystemExit("No hay datos cargados. Ejecute primero: python seed_redis.py")
    for u in USUARIOS.values():
        rid = rv.clave_reserva(u, EVENTO, ZONA)
        if rv.r.hget(rid, "estado") == "PENDIENTE":
            rv.cancelar_reserva(u, EVENTO, ZONA)
        rv.r.delete(rid)


def caso_a():
    titulo("Caso A - Confirmar: la venta queda firme y el TTL ya no aplica")
    u = USUARIOS["A"]
    antes = stock()
    print(f"  Stock {EVENTO}/{ZONA}: {antes}")
    mostrar("Reservar 2", rv.crear_reserva_temporal(u, EVENTO, ZONA, 2, ttl_segundos=3))
    mostrar("Confirmar", rv.confirmar_reserva(u, EVENTO, ZONA))
    print("  Esperando 4 s (más que el TTL de 3 s)...")
    time.sleep(4)
    print(f"  Reserva en Redis: {rv.ver_reserva(u, EVENTO, ZONA)}")
    print(f"  Stock: {stock()}  (esperado {antes - 2}: la venta no se revierte)")
    mostrar("Confirmar otra vez", rv.confirmar_reserva(u, EVENTO, ZONA))
    mostrar("Cancelar una confirmada", rv.cancelar_reserva(u, EVENTO, ZONA))


def caso_b():
    titulo("Caso B - Cancelar: se devuelve exactamente lo reservado, una sola vez")
    u = USUARIOS["B"]
    antes = stock()
    print(f"  Stock antes: {antes}")
    mostrar("Reservar 3", rv.crear_reserva_temporal(u, EVENTO, ZONA, 3, ttl_segundos=30))
    print(f"  Stock tras reservar: {stock()}")
    mostrar("Cancelar", rv.cancelar_reserva(u, EVENTO, ZONA))
    print(f"  Stock tras cancelar: {stock()}  (esperado {antes})")
    mostrar("Cancelar otra vez", rv.cancelar_reserva(u, EVENTO, ZONA))
    print(f"  Stock: {stock()}  (no cambia: no se devuelve dos veces)")
    mostrar("Confirmar la cancelada", rv.confirmar_reserva(u, EVENTO, ZONA))


def caso_c(liberador):
    titulo("Caso C - Vencimiento automático y devolución del inventario")
    u = USUARIOS["C"]
    antes = stock()
    print(f"  Stock antes: {antes}")
    mostrar("Reservar 4 con TTL 3 s", rv.crear_reserva_temporal(u, EVENTO, ZONA, 4, ttl_segundos=3))
    for _ in range(4):
        reserva = rv.ver_reserva(u, EVENTO, ZONA)
        ttl = reserva["ttl_restante_s"] if reserva else "clave eliminada"
        print(f"    TTL restante: {ttl}  |  stock: {stock()}")
        time.sleep(1)
    time.sleep(0.5)
    print(f"  Stock tras vencer: {stock()}  (esperado {antes}; nadie llamó a ninguna función)")
    mostrar("Confirmar la vencida", rv.confirmar_reserva(u, EVENTO, ZONA))
    mostrar("Cancelar la vencida", rv.cancelar_reserva(u, EVENTO, ZONA))
    print(f"  Stock: {stock()}  (sin doble devolución)")


def caso_d():
    titulo("Caso D - Dos clientes compiten por la última entrada")
    evento, zona = "EVT-101", "DEMO-ULTIMA"
    rv.r.set(rv.clave_stock(evento, zona), 1)
    clientes = [USUARIOS["D"], USUARIOS["E"]]
    barrera = threading.Barrier(2)
    resultados = {}

    def cliente(u):
        barrera.wait()  # ambos disparan exactamente al mismo tiempo
        resultados[u] = rv.crear_reserva_temporal(u, evento, zona, 1, ttl_segundos=30)

    hilos = [threading.Thread(target=cliente, args=(u,)) for u in clientes]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    print(f"  Zona de prueba con 1 entrada disponible")
    for u in clientes:
        mostrar(u, resultados[u])
    print(f"  Stock final: {stock(evento, zona)}  (nunca negativo; un solo ganador)")
    for u in clientes:
        rv.cancelar_reserva(u, evento, zona)
        rv.r.delete(rv.clave_reserva(u, evento, zona))
    rv.r.delete(rv.clave_stock(evento, zona))


def caso_e():
    titulo("Caso E - Validaciones: el inventario no se puede manipular desde afuera")
    u = USUARIOS["F"]
    antes = stock()
    mostrar("Reservar 0", rv.crear_reserva_temporal(u, EVENTO, ZONA, 0))
    mostrar("Reservar -5", rv.crear_reserva_temporal(u, EVENTO, ZONA, -5))
    mostrar("Usuario inexistente", rv.crear_reserva_temporal("USR-99999", EVENTO, ZONA, 1))
    mostrar("Reservar 1", rv.crear_reserva_temporal(u, EVENTO, ZONA, 1, ttl_segundos=30))
    mostrar("Reservar de nuevo", rv.crear_reserva_temporal(u, EVENTO, ZONA, 1))
    rv.cancelar_reserva(u, EVENTO, ZONA)
    print(f"  Stock: {stock()}  (esperado {antes})")


def main():
    global PAUSA
    p = argparse.ArgumentParser()
    p.add_argument("--pausa", action="store_true", help="esperar Enter entre casos")
    PAUSA = p.parse_args().pausa

    print("=== DEMOSTRACIÓN REQUISITOS 3 Y 4 - EntradaFlash CR ===")
    preparar()

    def aviso(reserva_id, entradas):
        print(f"    [liberador] {reserva_id} venció: {entradas} entradas devueltas")

    liberador = rv.iniciar_liberador(intervalo=0.2, al_liberar=aviso)
    try:
        caso_a()
        caso_b()
        caso_c(liberador)
        caso_d()
        caso_e()
    finally:
        liberador.detener()
    print("\nDemostración terminada.")


if __name__ == "__main__":
    main()
