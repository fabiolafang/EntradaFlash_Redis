"""
Pruebas automáticas del requisito 6 (control de intentos por usuario e IP).

Ejecutar:  python -m pytest test_rate_limit.py -v

Las pruebas usan usuarios (RL-xxxx), IPs (10.99.x.x) y un evento (EVT-TESTRL)
propios, y borran todo al terminar, así que no alteran los datos del seed.
"""

import json
import threading
import time

import pytest

import rate_limit as rl
import reservas as rv

EVENTO = "EVT-TESTRL"
ZONA = "PRUEBA"
VENTANA = 30          # ventana larga para que ningún test dependa de la hora


@pytest.fixture
def entorno():
    """Reparte usuarios e IPs de prueba y limpia sus contadores al final."""
    usuarios, ips = [], []

    def preparar(cantidad_usuarios=1, cantidad_ips=1, stock=10, ip_en_perfil=None):
        rv.r.set(rv.clave_stock(EVENTO, ZONA), stock)
        ids = [f"RL-{i:04d}" for i in range(cantidad_usuarios)]
        for uid in ids:
            perfil = {"user_id": uid}
            if ip_en_perfil:
                perfil["ip"] = ip_en_perfil
            rv.r.set(rv.clave_usuario(uid), json.dumps(perfil))
        direcciones = [f"10.99.0.{i + 1}" for i in range(cantidad_ips)]
        usuarios.extend(ids)
        ips.extend(direcciones + ([ip_en_perfil] if ip_en_perfil else []))
        return ids, direcciones

    yield preparar

    rv.r.delete(rv.clave_stock(EVENTO, ZONA))
    for uid in usuarios:
        rl.reiniciar_limite(user_id=uid)
        rid = rv.clave_reserva(uid, EVENTO, ZONA)
        rv.r.delete(rv.clave_usuario(uid), rid)
        rv.r.zrem(rv.PENDIENTES_KEY, rid)
        rv.r.hdel(rv.CANTIDADES_KEY, rid)
    for ip in ips:
        rl.reiniciar_limite(ip=ip)


# --- Control por usuario -------------------------------------------------------------

def test_permite_hasta_el_limite_y_rechaza_el_siguiente(entorno):
    (u,), _ = entorno()
    for restantes in (2, 1, 0):
        res = rl.verificar_intento(user_id=u, limite_usuario=3,
                                   ventana_segundos=VENTANA)
        assert res["status"] == "EXITO"
        assert res["intentos_restantes"] == {"usuario": restantes}
    res = rl.verificar_intento(user_id=u, limite_usuario=3, ventana_segundos=VENTANA)
    assert res["status"] == "RECHAZADO" and res["ambito"] == "usuario"
    assert 0 < res["reintentar_en_segundos"] <= VENTANA


def test_la_ventana_vence_y_el_contador_vuelve_a_cero(entorno):
    (u,), _ = entorno()
    for _ in range(2):
        rl.verificar_intento(user_id=u, limite_usuario=2, ventana_segundos=0.5)
    assert rl.verificar_intento(user_id=u, limite_usuario=2,
                                ventana_segundos=0.5)["status"] == "RECHAZADO"
    time.sleep(0.7)
    res = rl.verificar_intento(user_id=u, limite_usuario=2, ventana_segundos=0.5)
    assert res["status"] == "EXITO"
    assert res["intentos_restantes"] == {"usuario": 1}


def test_los_rechazos_no_extienden_la_ventana(entorno):
    (u,), _ = entorno()
    for _ in range(2):
        rl.verificar_intento(user_id=u, limite_usuario=2, ventana_segundos=1.0)
    time.sleep(0.5)
    # Un bot insiste a mitad de la ventana: se rechaza pero no se le suma castigo.
    assert rl.verificar_intento(user_id=u, limite_usuario=2,
                                ventana_segundos=1.0)["status"] == "RECHAZADO"
    time.sleep(0.6)           # 1.1 s desde el primer intento
    assert rl.verificar_intento(user_id=u, limite_usuario=2,
                                ventana_segundos=1.0)["status"] == "EXITO"


def test_usuarios_distintos_son_independientes(entorno):
    (a, b), _ = entorno(2)
    for _ in range(3):
        rl.verificar_intento(user_id=a, limite_usuario=3, ventana_segundos=VENTANA)
    assert rl.verificar_intento(user_id=a, limite_usuario=3,
                                ventana_segundos=VENTANA)["status"] == "RECHAZADO"
    assert rl.verificar_intento(user_id=b, limite_usuario=3,
                                ventana_segundos=VENTANA)["status"] == "EXITO"


def test_los_contadores_siempre_tienen_ttl(entorno):
    (u,), (ip,) = entorno()
    rl.verificar_intento(user_id=u, ip=ip, ventana_segundos=VENTANA)
    rl.verificar_intento(user_id=u, ip=ip, ventana_segundos=VENTANA)
    for clave in (rl.clave_limite_usuario(u), rl.clave_limite_ip(ip)):
        assert 0 < rv.r.pttl(clave) <= VENTANA * 1000   # nunca queda bloqueo eterno


# --- Control por IP --------------------------------------------------------------------

def test_varios_usuarios_comparten_el_limite_de_su_ip(entorno):
    usuarios, (ip,) = entorno(4)
    for u in usuarios[:3]:
        res = rl.verificar_intento(user_id=u, ip=ip, limite_usuario=10,
                                   limite_ip=3, ventana_segundos=VENTANA)
        assert res["status"] == "EXITO"
    res = rl.verificar_intento(user_id=usuarios[3], ip=ip, limite_usuario=10,
                               limite_ip=3, ventana_segundos=VENTANA)
    assert res["status"] == "RECHAZADO" and res["ambito"] == "ip"


def test_controlar_solo_por_ip(entorno):
    _, (ip,) = entorno()
    for _ in range(2):
        assert rl.verificar_intento(ip=ip, limite_ip=2,
                                    ventana_segundos=VENTANA)["status"] == "EXITO"
    res = rl.verificar_intento(ip=ip, limite_ip=2, ventana_segundos=VENTANA)
    assert res["status"] == "RECHAZADO" and res["ambito"] == "ip"


def test_un_usuario_bloqueado_no_consume_el_cupo_de_su_ip(entorno):
    (u,), (ip,) = entorno()
    rl.verificar_intento(user_id=u, ip=ip, limite_usuario=1, limite_ip=50,
                         ventana_segundos=VENTANA)
    for _ in range(5):
        res = rl.verificar_intento(user_id=u, ip=ip, limite_usuario=1,
                                   limite_ip=50, ventana_segundos=VENTANA)
        assert res["status"] == "RECHAZADO" and res["ambito"] == "usuario"
    assert rv.r.get(rl.clave_limite_ip(ip)) == "1"


# --- Validaciones ------------------------------------------------------------------------

def test_validaciones_de_entrada(entorno):
    (u,), _ = entorno()
    assert rl.verificar_intento()["status"] == "RECHAZADO"
    for limite in (0, -1, 2.5, True, "3", None):
        assert rl.verificar_intento(user_id=u, limite_usuario=limite,
                                    ventana_segundos=VENTANA)["status"] == "RECHAZADO"
    for ventana in (0, -5, True, "60"):
        assert rl.verificar_intento(user_id=u, ventana_segundos=ventana)["status"] == "RECHAZADO"
    assert rv.r.exists(rl.clave_limite_usuario(u)) == 0   # nada se contó


# --- Concurrencia ------------------------------------------------------------------------

def test_cien_hilos_a_la_vez_solo_pasa_el_limite(entorno):
    """Revisar e incrementar es atómico: pasan exactamente `limite` intentos."""
    (u,), _ = entorno()
    hilos_n, limite = 100, 10
    barrera = threading.Barrier(hilos_n)
    resultados = [None] * hilos_n

    def intento(i):
        barrera.wait()
        resultados[i] = rl.verificar_intento(user_id=u, limite_usuario=limite,
                                             ventana_segundos=VENTANA)

    hilos = [threading.Thread(target=intento, args=(i,)) for i in range(hilos_n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert sum(1 for r in resultados if r["status"] == "EXITO") == limite
    assert rv.r.get(rl.clave_limite_usuario(u)) == str(limite)


def test_concurrencia_con_usuario_e_ip_a_la_vez(entorno):
    """Con 100 usuarios en una IP de límite 15, pasan exactamente 15."""
    usuarios, (ip,) = entorno(100)
    barrera = threading.Barrier(len(usuarios))
    resultados = [None] * len(usuarios)

    def intento(i):
        barrera.wait()
        resultados[i] = rl.verificar_intento(user_id=usuarios[i], ip=ip,
                                             limite_usuario=5, limite_ip=15,
                                             ventana_segundos=VENTANA)

    hilos = [threading.Thread(target=intento, args=(i,)) for i in range(len(usuarios))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert sum(1 for r in resultados if r["status"] == "EXITO") == 15
    assert rv.r.get(rl.clave_limite_ip(ip)) == "15"


# --- Integración con la reserva -------------------------------------------------------------

def test_reservar_con_limite_bloquea_antes_de_tocar_el_inventario(entorno):
    usuarios, (ip,) = entorno(3)
    for u in usuarios[:2]:
        res = rl.reservar_con_limite(u, EVENTO, ZONA, 1, ip=ip, ttl_segundos=30,
                                     limite_usuario=5, limite_ip=2,
                                     ventana_segundos=VENTANA)
        assert res["status"] == "EXITO"
    res = rl.reservar_con_limite(usuarios[2], EVENTO, ZONA, 1, ip=ip,
                                 ttl_segundos=30, limite_usuario=5, limite_ip=2,
                                 ventana_segundos=VENTANA)
    assert res["status"] == "RECHAZADO" and res["ambito"] == "ip"
    assert rv.consultar_disponibilidad(EVENTO, ZONA)["disponibilidad_actual"] == 8
    assert rv.ver_reserva(usuarios[2], EVENTO, ZONA) is None


def test_reservar_con_limite_toma_la_ip_del_perfil(entorno):
    (u,), _ = entorno(1, 0, ip_en_perfil="10.99.9.9")
    assert rl.ip_de_usuario(u) == "10.99.9.9"
    res = rl.reservar_con_limite(u, EVENTO, ZONA, 1, ttl_segundos=30,
                                 ventana_segundos=VENTANA)
    assert res["status"] == "EXITO"
    assert "ip" in res["intentos_restantes"]
    assert rv.r.get(rl.clave_limite_ip("10.99.9.9")) == "1"


def test_ip_de_usuario_sin_perfil_o_sin_ip(entorno):
    (u,), _ = entorno()
    assert rl.ip_de_usuario(u) is None             # perfil sin campo ip
    assert rl.ip_de_usuario("RL-NO-EXISTE") is None
