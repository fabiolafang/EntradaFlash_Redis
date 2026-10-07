"""
Pruebas automáticas del requisito 5 (carrito o sesión temporal por usuario).

Ejecutar:  python -m pytest test_sesiones.py -v

Las pruebas usan un evento propio (EVT-TESTCART) y usuarios propios, y borran
todo al terminar, así que no alteran los datos cargados por el seed.
"""

import threading
import time

import pytest
import redis

import reservas as rv
import sesiones as ss

EVENTO = "EVT-TESTCART"
ZONA = "PRUEBA"
ZONA_2 = "PRUEBA2"
TOPE = rv.MAX_ENTRADAS_POR_RESERVA


@pytest.fixture
def entorno():
    """Crea zonas y usuarios de prueba; limpia todo al final."""
    usuarios = []

    def preparar(stock=10, cantidad_usuarios=3):
        for zona in (ZONA, ZONA_2):
            rv.r.set(rv.clave_stock(EVENTO, zona), stock)
        ids = [f"CART-{i:04d}" for i in range(cantidad_usuarios)]
        for uid in ids:
            rv.r.set(rv.clave_usuario(uid), "{}")
        usuarios.extend(ids)
        return ids

    yield preparar

    for zona in (ZONA, ZONA_2):
        rv.r.delete(rv.clave_stock(EVENTO, zona))
    for uid in usuarios:
        rv.r.delete(ss.clave_carrito(uid), rv.clave_usuario(uid))
        for zona in (ZONA, ZONA_2):
            rid = rv.clave_reserva(uid, EVENTO, zona)
            rv.r.delete(rid)
            rv.r.zrem(rv.PENDIENTES_KEY, rid)
            rv.r.hdel(rv.CANTIDADES_KEY, rid)


def stock(zona=ZONA):
    return rv.consultar_disponibilidad(EVENTO, zona)["disponibilidad_actual"]


# --- Armar el carrito ---------------------------------------------------------

def test_agregar_y_ver_carrito(entorno):
    u, = entorno(10, 1)
    res = ss.agregar_item(u, EVENTO, ZONA, 2)
    assert res["status"] == "EXITO" and res["cantidad_en_carrito"] == 2
    ss.agregar_item(u, EVENTO, ZONA_2, 1)
    carrito = ss.ver_carrito(u)
    assert carrito["items"] == [
        {"event_id": EVENTO, "zone_id": ZONA, "cantidad": 2},
        {"event_id": EVENTO, "zone_id": ZONA_2, "cantidad": 1}]
    assert carrito["total_entradas"] == 3
    assert 0 < carrito["ttl_restante_s"] <= ss.CARRITO_TTL_POR_DEFECTO


def test_agregar_acumula_la_misma_zona(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    res = ss.agregar_item(u, EVENTO, ZONA, 3)
    assert res["cantidad_en_carrito"] == 5
    assert len(ss.ver_carrito(u)["items"]) == 1


def test_el_tope_por_zona_se_respeta(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, TOPE - 2)
    res = ss.agregar_item(u, EVENTO, ZONA, 3)
    assert res["status"] == "RECHAZADO"
    assert res["cantidad_en_carrito"] == TOPE - 2
    assert ss.ver_carrito(u)["items"][0]["cantidad"] == TOPE - 2


def test_agregar_no_toca_el_inventario(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 4)
    assert stock() == 10


def test_validaciones_de_entrada(entorno):
    u, = entorno(10, 1)
    for cantidad in (0, -1, TOPE + 1, 2.5, True, "2", None):
        assert ss.agregar_item(u, EVENTO, ZONA, cantidad)["status"] == "RECHAZADO"
    assert ss.agregar_item(u, EVENTO, "NO-ZONA", 1)["status"] == "RECHAZADO"
    assert ss.agregar_item("NO-EXISTE", EVENTO, ZONA, 1)["status"] == "RECHAZADO"
    assert ss.agregar_item(u, EVENTO, ZONA, 1, ttl_segundos=0)["status"] == "RECHAZADO"
    assert ss.ver_carrito(u) is None


def test_carritos_de_usuarios_distintos_son_independientes(entorno):
    a, b, _ = entorno(10, 3)
    ss.agregar_item(a, EVENTO, ZONA, 2)
    ss.agregar_item(b, EVENTO, ZONA, 5)
    assert ss.ver_carrito(a)["total_entradas"] == 2
    assert ss.ver_carrito(b)["total_entradas"] == 5


# --- Quitar y vaciar ------------------------------------------------------------

def test_quitar_parcial_y_total(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 4)
    assert ss.quitar_item(u, EVENTO, ZONA, cantidad=1)["cantidad_en_carrito"] == 3
    assert ss.quitar_item(u, EVENTO, ZONA)["cantidad_en_carrito"] == 0
    assert ss.ver_carrito(u) is None      # sin líneas, la clave desaparece


def test_quitar_mas_de_lo_que_hay_elimina_la_linea(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    ss.agregar_item(u, EVENTO, ZONA_2, 1)
    ss.quitar_item(u, EVENTO, ZONA, cantidad=5)
    assert [i["zone_id"] for i in ss.ver_carrito(u)["items"]] == [ZONA_2]


def test_quitar_zona_inexistente(entorno):
    u, = entorno(10, 1)
    assert ss.quitar_item(u, EVENTO, ZONA)["status"] == "RECHAZADO"
    ss.agregar_item(u, EVENTO, ZONA, 1)
    assert ss.quitar_item(u, EVENTO, ZONA_2)["status"] == "RECHAZADO"
    for cantidad in (0, -1, 1.5, True):
        assert ss.quitar_item(u, EVENTO, ZONA, cantidad=cantidad)["status"] == "RECHAZADO"
    assert ss.ver_carrito(u)["total_entradas"] == 1


def test_vaciar_carrito(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    assert ss.vaciar_carrito(u)["vaciado"] is True
    assert ss.ver_carrito(u) is None
    assert ss.vaciar_carrito(u)["vaciado"] is False


# --- Vencimiento y recuperación -------------------------------------------------

def test_el_carrito_vence_solo(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2, ttl_segundos=0.5)
    assert ss.ver_carrito(u) is not None
    time.sleep(0.8)
    assert ss.ver_carrito(u) is None


def test_la_actividad_renueva_la_vida_del_carrito(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 1, ttl_segundos=1.0)
    time.sleep(0.6)
    ss.agregar_item(u, EVENTO, ZONA_2, 1, ttl_segundos=1.0)   # renueva
    time.sleep(0.6)                      # ya pasó el 1.0 s original
    assert ss.ver_carrito(u)["total_entradas"] == 2


def test_ver_sin_renovar_no_extiende_la_vida(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 1, ttl_segundos=1.0)
    time.sleep(0.6)
    ss.ver_carrito(u)                    # lectura pura
    time.sleep(0.6)
    assert ss.ver_carrito(u) is None


def test_ver_renovando_extiende_la_vida(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 1, ttl_segundos=1.0)
    time.sleep(0.6)
    ss.ver_carrito(u, renovar=True, ttl_segundos=1.0)   # el usuario volvió
    time.sleep(0.6)
    assert ss.ver_carrito(u)["total_entradas"] == 1


def test_recuperacion_desde_otra_conexion(entorno):
    """El carrito vive en Redis, no en la memoria del proceso que lo creó."""
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    ss.agregar_item(u, EVENTO, ZONA_2, 3)

    otro_proceso = redis.Redis(host=rv.REDIS_HOST, port=rv.REDIS_PORT,
                               db=rv.REDIS_DB, decode_responses=True)
    assert otro_proceso.hgetall(ss.clave_carrito(u)) == {
        f"{EVENTO}:{ZONA}": "2", f"{EVENTO}:{ZONA_2}": "3"}
    otro_proceso.close()


def test_el_carrito_siempre_tiene_ttl(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    ss.agregar_item(u, EVENTO, ZONA, 1)
    ss.quitar_item(u, EVENTO, ZONA, cantidad=1)
    assert rv.r.pttl(ss.clave_carrito(u)) > 0    # nunca queda sin vencimiento


# --- Finalizar: del carrito a la reserva ------------------------------------------

def test_finalizar_convierte_el_carrito_en_reservas(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    ss.agregar_item(u, EVENTO, ZONA_2, 3)
    res = ss.finalizar_carrito(u, ttl_segundos=30)
    assert res["status"] == "EXITO" and len(res["reservas"]) == 2
    assert res["pendientes"] == []
    assert stock(ZONA) == 8 and stock(ZONA_2) == 7
    assert ss.ver_carrito(u) is None
    assert rv.ver_reserva(u, EVENTO, ZONA)["estado"] == "PENDIENTE"


def test_finalizar_parcial_deja_en_el_carrito_lo_que_fallo(entorno):
    u, = entorno(10, 1)
    rv.r.set(rv.clave_stock(EVENTO, ZONA_2), 1)        # solo queda 1 entrada
    ss.agregar_item(u, EVENTO, ZONA, 2)
    ss.agregar_item(u, EVENTO, ZONA_2, 3)
    res = ss.finalizar_carrito(u, ttl_segundos=30)
    assert res["status"] == "PARCIAL"
    assert [p["zone_id"] for p in res["pendientes"]] == [ZONA_2]
    assert stock(ZONA) == 8 and stock(ZONA_2) == 1     # lo rechazado no descuenta
    assert ss.ver_carrito(u)["items"] == [
        {"event_id": EVENTO, "zone_id": ZONA_2, "cantidad": 3}]


def test_finalizar_sin_stock_en_ninguna_linea(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 3)
    rv.r.set(rv.clave_stock(EVENTO, ZONA), 0)
    res = ss.finalizar_carrito(u, ttl_segundos=30)
    assert res["status"] == "RECHAZADO" and res["reservas"] == []
    assert ss.ver_carrito(u)["total_entradas"] == 3


def test_finalizar_carrito_vacio_o_vencido(entorno):
    u, = entorno(10, 1)
    assert ss.finalizar_carrito(u)["status"] == "RECHAZADO"
    ss.agregar_item(u, EVENTO, ZONA, 2, ttl_segundos=0.4)
    time.sleep(0.6)
    assert ss.finalizar_carrito(u)["status"] == "RECHAZADO"
    assert stock() == 10


def test_finalizar_dos_veces_no_duplica_la_reserva(entorno):
    u, = entorno(10, 1)
    ss.agregar_item(u, EVENTO, ZONA, 2)
    ss.finalizar_carrito(u, ttl_segundos=30)
    assert ss.finalizar_carrito(u)["status"] == "RECHAZADO"
    assert stock() == 8


# --- Concurrencia -----------------------------------------------------------------

def test_dos_pestanas_no_superan_el_tope(entorno):
    """50 pestañas del mismo usuario agregan a la vez: el tope se respeta."""
    u, = entorno(10, 1)
    hilos_n = 50
    barrera = threading.Barrier(hilos_n)
    resultados = [None] * hilos_n

    def pestana(i):
        barrera.wait()
        resultados[i] = ss.agregar_item(u, EVENTO, ZONA, 1)

    hilos = [threading.Thread(target=pestana, args=(i,)) for i in range(hilos_n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    aceptados = sum(1 for r in resultados if r["status"] == "EXITO")
    assert aceptados == TOPE
    assert ss.ver_carrito(u)["total_entradas"] == TOPE
