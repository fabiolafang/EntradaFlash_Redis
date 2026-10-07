"""
Pruebas automáticas de los requisitos 3 y 4 (y su integración con 1 y 2).

Ejecutar:  python -m pytest test_reservas.py -v

Las pruebas usan un evento propio (EVT-TEST) y usuarios propios, y borran
todo al terminar, así que no alteran los datos cargados por el seed.
"""

import threading
import time

import pytest

import reservas as rv

EVENTO = "EVT-TEST"
ZONA = "PRUEBA"


@pytest.fixture
def zona():
    """Crea una zona de prueba y sus usuarios; limpia todo al final."""
    creadas = []

    def preparar(stock, usuarios=5):
        rv.r.set(rv.clave_stock(EVENTO, ZONA), stock)
        ids = [f"TEST-{i:04d}" for i in range(usuarios)]
        for uid in ids:
            rv.r.set(rv.clave_usuario(uid), "{}")
        creadas.extend(ids)
        return ids

    yield preparar

    rv.r.delete(rv.clave_stock(EVENTO, ZONA))
    for uid in creadas:
        rid = rv.clave_reserva(uid, EVENTO, ZONA)
        rv.r.delete(rv.clave_usuario(uid), rid)
        rv.r.zrem(rv.PENDIENTES_KEY, rid)
        rv.r.hdel(rv.CANTIDADES_KEY, rid)


def stock():
    return rv.consultar_disponibilidad(EVENTO, ZONA)["disponibilidad_actual"]


# --- Requisito 3: confirmar ---------------------------------------------

def test_confirmar_no_devuelve_stock_al_pasar_el_ttl(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 3, ttl_segundos=1)
    assert rv.confirmar_reserva(u, EVENTO, ZONA)["status"] == "EXITO"
    time.sleep(1.3)
    rv.liberar_reservas_vencidas()
    assert stock() == 7
    assert rv.ver_reserva(u, EVENTO, ZONA)["estado"] == "CONFIRMADA"
    assert rv.ver_reserva(u, EVENTO, ZONA)["ttl_restante_s"] is None


def test_confirmar_dos_veces(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 2)
    rv.confirmar_reserva(u, EVENTO, ZONA)
    res = rv.confirmar_reserva(u, EVENTO, ZONA)
    assert res["status"] == "RECHAZADO" and "confirmada" in res["motivo"]
    assert stock() == 8


def test_confirmar_reserva_vencida_la_libera(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 4, ttl_segundos=0.5)
    time.sleep(0.7)
    # Sin barrido previo: la propia confirmación detecta el vencimiento.
    res = rv.confirmar_reserva(u, EVENTO, ZONA)
    assert res["status"] == "RECHAZADO" and "venció" in res["motivo"]
    assert stock() == 10


def test_confirmar_reserva_inexistente(zona):
    u, = zona(10, 1)
    assert rv.confirmar_reserva(u, EVENTO, ZONA)["status"] == "RECHAZADO"
    assert stock() == 10


# --- Requisito 3: cancelar ----------------------------------------------

def test_cancelar_devuelve_la_cantidad_registrada(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 3)
    res = rv.cancelar_reserva(u, EVENTO, ZONA)
    assert res["entradas_devueltas"] == 3
    assert stock() == 10


def test_cancelar_dos_veces_no_infla(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 3)
    rv.cancelar_reserva(u, EVENTO, ZONA)
    res = rv.cancelar_reserva(u, EVENTO, ZONA)
    assert res["status"] == "RECHAZADO" and "cancelada" in res["motivo"]
    rv.liberar_reservas_vencidas()
    assert stock() == 10


def test_cancelar_confirmada(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 2)
    rv.confirmar_reserva(u, EVENTO, ZONA)
    assert rv.cancelar_reserva(u, EVENTO, ZONA)["status"] == "RECHAZADO"
    assert stock() == 8


def test_cancelar_tras_vencer_no_devuelve_dos_veces(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 5, ttl_segundos=0.5)
    time.sleep(0.7)
    rv.liberar_reservas_vencidas()
    assert stock() == 10
    assert rv.cancelar_reserva(u, EVENTO, ZONA)["status"] == "RECHAZADO"
    assert stock() == 10


def test_confirmar_cancelada(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 2)
    rv.cancelar_reserva(u, EVENTO, ZONA)
    res = rv.confirmar_reserva(u, EVENTO, ZONA)
    assert res["status"] == "RECHAZADO" and "cancelada" in res["motivo"]
    assert stock() == 10


def test_reservar_de_nuevo_tras_cancelar(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 2)
    rv.cancelar_reserva(u, EVENTO, ZONA)
    assert rv.crear_reserva_temporal(u, EVENTO, ZONA, 1)["status"] == "EXITO"
    assert stock() == 9


# --- Requisito 2 integrado: vencimiento automático ----------------------

def test_liberador_automatico_devuelve_stock(zona):
    u, = zona(10, 1)
    liberador = rv.iniciar_liberador(intervalo=0.1)
    try:
        rv.crear_reserva_temporal(u, EVENTO, ZONA, 4, ttl_segundos=0.5)
        assert stock() == 6
        time.sleep(1.0)
        assert stock() == 10
        assert rv.ver_reserva(u, EVENTO, ZONA) is None
    finally:
        liberador.detener()


def test_barrido_repetido_no_duplica(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 4, ttl_segundos=0.3)
    time.sleep(0.5)
    for _ in range(5):
        rv.liberar_reservas_vencidas()
    assert stock() == 10


def test_doble_reserva_misma_zona(zona):
    u, = zona(10, 1)
    rv.crear_reserva_temporal(u, EVENTO, ZONA, 2)
    res = rv.crear_reserva_temporal(u, EVENTO, ZONA, 2)
    assert res["status"] == "RECHAZADO" and "pendiente" in res["motivo"]
    assert stock() == 8


def test_validaciones_de_entrada(zona):
    u, = zona(10, 1)
    for cantidad in (0, -1, 7, 2.5, True, "2"):
        assert rv.crear_reserva_temporal(u, EVENTO, ZONA, cantidad)["status"] == "RECHAZADO"
    assert rv.crear_reserva_temporal("NO-EXISTE", EVENTO, ZONA, 1)["status"] == "RECHAZADO"
    assert rv.crear_reserva_temporal(u, EVENTO, "NO-ZONA", 1)["status"] == "RECHAZADO"
    assert stock() == 10


# --- Requisito 4: concurrencia ------------------------------------------

def _en_paralelo(funcion, argumentos):
    barrera = threading.Barrier(len(argumentos))
    resultados = [None] * len(argumentos)

    def tarea(i, args):
        barrera.wait()  # todos arrancan exactamente al mismo tiempo
        resultados[i] = funcion(*args)

    hilos = [threading.Thread(target=tarea, args=(i, a))
             for i, a in enumerate(argumentos)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return resultados


def test_dos_clientes_por_la_ultima_entrada(zona):
    a, b = zona(1, 2)
    res = _en_paralelo(rv.crear_reserva_temporal,
                       [(a, EVENTO, ZONA, 1), (b, EVENTO, ZONA, 1)])
    assert sorted(x["status"] for x in res) == ["EXITO", "RECHAZADO"]
    assert stock() == 0


def test_doscientos_clientes_cincuenta_entradas(zona):
    usuarios = zona(50, 200)
    res = _en_paralelo(rv.crear_reserva_temporal,
                       [(u, EVENTO, ZONA, 1 + i % 3) for i, u in enumerate(usuarios)])
    reservadas = sum(x["entradas_reservadas"] for x in res if x["status"] == "EXITO")
    assert stock() >= 0
    assert reservadas + stock() == 50


def test_confirmar_y_cancelar_a_la_vez(zona):
    """Solo una de las dos operaciones puede ganar, nunca ambas."""
    for _ in range(30):
        u, = zona(10, 1)
        rv.crear_reserva_temporal(u, EVENTO, ZONA, 3)
        conf, canc = _en_paralelo(lambda f: f(u, EVENTO, ZONA),
                                  [(rv.confirmar_reserva,), (rv.cancelar_reserva,)])
        exitos = [x for x in (conf, canc) if x["status"] == "EXITO"]
        assert len(exitos) == 1
        assert stock() == (7 if conf["status"] == "EXITO" else 10)
        rv.r.delete(rv.clave_reserva(u, EVENTO, ZONA))
