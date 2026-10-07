# FUNCIONES

import time
import redis

# Conexión a Redis en el puerto 6380
r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)

# Requisito 1

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

# Requisto 2

def crear_reserva_temporal(user_id, event_id, zone_id, cantidad, ttl_segundos=5):
    stock_key = f"event:{event_id}:zone:{zone_id}:stock"
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"

    with r.pipeline() as pipe:
        try:
            pipe.watch(stock_key)
            stock_actual = int(pipe.get(stock_key) or 0)

            if stock_actual < cantidad:
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

def simular_expiracion_y_devolucion(user_id, event_id, zone_id, cantidad):
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"
    stock_key = f"event:{event_id}:zone:{zone_id}:stock"

    if not r.exists(reserva_id):
        r.incrby(stock_key, cantidad)
        print(f" [TTL Expirado]: Reserva {reserva_id} vencida. Se devolvieron {cantidad} entradas al inventario.")

# Operación atómica

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

# Requisito 3

def confirmar_reserva(user_id, event_id, zone_id):
    """Confirma una reserva PENDIENTE (venta definitiva) de forma atómica."""
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"
    resultado = confirmar_script(keys=[reserva_id])

    if resultado == 1:
        return {"status": "EXITO", "reserva_id": reserva_id, "estado": "CONFIRMADA"}
    return {"status": "RECHAZADO", "reserva_id": reserva_id,
            "motivo": _CODIGOS_CONFIRMAR.get(resultado, "Error desconocido")}

# Requisito 4

def cancelar_reserva(user_id, event_id, zone_id, cantidad):
    """Cancela una reserva PENDIENTE y devuelve el stock de forma atómica."""
    reserva_id = f"reservation:{user_id}:{event_id}:{zone_id}"
    stock_key = f"event:{event_id}:zone:{zone_id}:stock"
    resultado = cancelar_script(keys=[reserva_id, stock_key], args=[cantidad])

    if resultado == 1:
        return {"status": "EXITO", "reserva_id": reserva_id,
                "entradas_devueltas": cantidad}
    return {"status": "RECHAZADO", "reserva_id": reserva_id,
            "motivo": _CODIGOS_CANCELAR.get(resultado, "Error desconocido")}