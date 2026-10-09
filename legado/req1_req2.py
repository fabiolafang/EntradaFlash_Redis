import redis

#Conexión a Redis en el puerto 6380
r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)

#req 1
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

#req 2
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