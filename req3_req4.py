import time
import redis

r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)

def consultar_disponibilidad(event_id, zone_id):
    stock_key = f"event:{event_id}:zone:{zone_id}:stock"
    stock = r.get(stock_key)

    if stock is None:
        return {"error": "El evento o zona especificada no existe."}

    return {
        "event_id": event_id,
        "zone_id": zone_id,
        "disponibilidad_actual": int(stock)
    }


def crear_reserva_temporal(user_id, event_id, zone_id, cantidad, ttl_segundos=20):
    stock_key = f"event:{event_id}:zone:{zone_id}:stock"
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"

    with r.pipeline() as pipe:
        try:
            pipe.watch(stock_key)
            stock_actual = int(pipe.get(stock_key) or 0)

            if stock_actual < cantidad:
                pipe.reset()
                return {"status": "RECHAZADO", "motivo": "Stock insuficiente"}

            pipe.multi()
            pipe.decrby(stock_key, cantidad)

            datos_reserva = {
                "user_id": user_id,
                "event_id": event_id,
                "zone_id": zone_id,
                "cantidad": cantidad,
                "estado": "PENDIENTE"
            }
            pipe.hset(reserva_id, mapping=datos_reserva)
            pipe.expire(reserva_id, ttl_segundos)

            pipe.execute()
            return {
                "status": "EXITO",
                "reserva_id": reserva_id,
                "entradas_reservadas": cantidad,
                "expira_en_segundos": ttl_segundos
            }

        except redis.WatchError:
            return {"status": "RECHAZADO", "motivo": "Conflicto de concurrencia."}

# Operación atómica (Lua) para controlar concurrencia

_LUA_CONFIRMAR = """
local reserva_id = KEYS[1]

local existe = redis.call('EXISTS', reserva_id)
if existe == 0 then
    return -1  -- La reserva no existe o ya expiró
end

local estado = redis.call('HGET', reserva_id, 'estado')
if estado ~= 'PENDIENTE' then
    return -2  -- Ya estaba confirmada o cancelada
end

redis.call('HSET', reserva_id, 'estado', 'CONFIRMADA')
redis.call('PERSIST', reserva_id)  -- Una reserva confirmada ya no debe expirar

return 1
"""

_LUA_CANCELAR = """
local reserva_id = KEYS[1]
local stock_key = KEYS[2]
local cantidad = tonumber(ARGV[1])

local existe = redis.call('EXISTS', reserva_id)
if existe == 0 then
    return -1  -- La reserva no existe o ya expiró (el stock ya se devolvió)
end

local estado = redis.call('HGET', reserva_id, 'estado')
if estado == 'CONFIRMADA' then
    return -2  -- No se puede cancelar una reserva ya confirmada
end
if estado == 'CANCELADA' then
    return -3  -- Ya estaba cancelada, no se devuelve el stock dos veces
end

redis.call('DEL', reserva_id)
redis.call('INCRBY', stock_key, cantidad)

return 1
"""

confirmar_script = r.register_script(_LUA_CONFIRMAR)
cancelar_script = r.register_script(_LUA_CANCELAR)

_CODIGOS_CONFIRMAR = {
    1: "CONFIRMADA",
    -1: "La reserva no existe (pudo haber expirado).",
    -2: "La reserva ya estaba confirmada o cancelada.",
}

_CODIGOS_CANCELAR = {
    1: "CANCELADA",
    -1: "La reserva no existe (pudo haber expirado).",
    -2: "No se puede cancelar: ya está confirmada.",
    -3: "La reserva ya estaba cancelada.",
}


def confirmar_reserva(user_id, event_id, zone_id):
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"
    resultado = confirmar_script(keys=[reserva_id])

    if resultado == 1:
        return {"status": "EXITO", "reserva_id": reserva_id, "estado": "CONFIRMADA"}
    return {"status": "RECHAZADO", "reserva_id": reserva_id,
            "motivo": _CODIGOS_CONFIRMAR.get(resultado, "Error desconocido")}


def cancelar_reserva(user_id, event_id, zone_id, cantidad):
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"
    stock_key = f"event:{event_id}:zone:{zone_id}:stock"
    resultado = cancelar_script(keys=[reserva_id, stock_key], args=[cantidad])

    if resultado == 1:
        return {"status": "EXITO", "reserva_id": reserva_id,
                "entradas_devueltas": cantidad}
    return {"status": "RECHAZADO", "reserva_id": reserva_id,
            "motivo": _CODIGOS_CANCELAR.get(resultado, "Error desconocido")}

# Demostración

if __name__ == "__main__":
    print("=== DEMOSTRACIÓN REQUERIMIENTOS 3 Y 4 ===\n")

    EVENTO = "EVT-101"
    ZONA = "VIP"

    # Caso A: confirmar una reserva válida
    USUARIO_A = "usr_000002"
    print("--- Caso A: Crear y CONFIRMAR una reserva ---")
    info_inicial = consultar_disponibilidad(EVENTO, ZONA)
    print(f"Stock inicial: {info_inicial['disponibilidad_actual']}")

    reserva_a = crear_reserva_temporal(USUARIO_A, EVENTO, ZONA, cantidad=2, ttl_segundos=15)
    print(f"Reserva creada: {reserva_a}")

    resultado_confirmar = confirmar_reserva(USUARIO_A, EVENTO, ZONA)
    print(f"Resultado de confirmar: {resultado_confirmar}")

    print("Esperando 15s (el TTL original) para comprobar que la reserva")
    print("confirmada YA NO expira ni devuelve el stock...")
    time.sleep(15)

    reserva_key_a = f"reservation:{USUARIO_A}:{EVENTO}:{ZONA}"
    existe_tras_ttl = r.exists(reserva_key_a)
    stock_tras_confirmar = consultar_disponibilidad(EVENTO, ZONA)
    print(f"¿La reserva confirmada sigue existiendo? {'Sí' if existe_tras_ttl else 'No'}")
    print(f"Stock tras confirmar y esperar: {stock_tras_confirmar['disponibilidad_actual']} "
          f"(debe seguir reflejando las 2 entradas ya vendidas, NO debe devolverse)\n")

    # Caso B: cancelar una reserva válida
    USUARIO_B = "usr_000003"
    print("--- Caso B: Crear y CANCELAR una reserva ---")
    stock_antes_b = consultar_disponibilidad(EVENTO, ZONA)
    print(f"Stock antes: {stock_antes_b['disponibilidad_actual']}")

    reserva_b = crear_reserva_temporal(USUARIO_B, EVENTO, ZONA, cantidad=3, ttl_segundos=30)
    print(f"Reserva creada: {reserva_b}")

    stock_tras_reservar_b = consultar_disponibilidad(EVENTO, ZONA)
    print(f"Stock tras reservar: {stock_tras_reservar_b['disponibilidad_actual']}")

    resultado_cancelar = cancelar_reserva(USUARIO_B, EVENTO, ZONA, cantidad=3)
    print(f"Resultado de cancelar: {resultado_cancelar}")

    stock_tras_cancelar = consultar_disponibilidad(EVENTO, ZONA)
    print(f"Stock tras cancelar: {stock_tras_cancelar['disponibilidad_actual']} "
          f"(debe volver al valor de antes de reservar)\n")

    # Caso C: evitar inventario negativo / doble devolución
    print("--- Caso C: Intentar cancelar la MISMA reserva dos veces ---")
    resultado_doble = cancelar_reserva(USUARIO_B, EVENTO, ZONA, cantidad=3)
    print(f"Resultado del segundo intento de cancelar: {resultado_doble}")
    print("(debe ser RECHAZADO porque la reserva ya no existe; así se evita",
          "devolver el stock dos veces y generar inventario inflado)\n")

    # Caso D: intentar confirmar una reserva que ya no existe (expiró)
    print("--- Caso D: Intentar confirmar una reserva ya vencida ---")
    USUARIO_D = "usr_000004"
    reserva_d = crear_reserva_temporal(USUARIO_D, EVENTO, ZONA, cantidad=1, ttl_segundos=3)
    print(f"Reserva creada con TTL de 3s: {reserva_d}")
    print("Esperando 4 segundos a que expire...")
    time.sleep(4)

    resultado_confirmar_expirada = confirmar_reserva(USUARIO_D, EVENTO, ZONA)
    print(f"Resultado de confirmar reserva expirada: {resultado_confirmar_expirada}")
    print("(debe ser RECHAZADO: la reserva ya no existe, Redis la borró solo)")
