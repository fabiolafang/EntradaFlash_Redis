import time
import redis

#Conexión a Redis en el puerto 6380
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

if __name__ == "__main__":
    print("=== DEMOSTRACIÓN REQUERIMIENTOS 1 Y 2 ===\n")
    
    EVENTO = "EVT-101"
    ZONA = "VIP"
    USUARIO = "usr_000001"

    print("1. Consultando disponibilidad inicial...")
    info_inicial = consultar_disponibilidad(EVENTO, ZONA)
    print(f"   Stock inicial en {EVENTO} ({ZONA}): {info_inicial['disponibilidad_actual']} entradas.")

    print("\n2. Creando reserva temporal de 4 entradas con TTL de 20 segundos...")
    reserva = crear_reserva_temporal(USUARIO, EVENTO, ZONA, cantidad=4, ttl_segundos=20)
    print(f"   Resultado: {reserva}")

    info_post_reserva = consultar_disponibilidad(EVENTO, ZONA)
    print(f"   Stock tras la reserva: {info_post_reserva['disponibilidad_actual']} entradas.")

    print("\n3. Esperando 20 segundos a que venza el TTL de la reserva...")
    time.sleep(20)

    simular_expiracion_y_devolucion(USUARIO, EVENTO, ZONA, cantidad=4)

    info_final = consultar_disponibilidad(EVENTO, ZONA)
    print(f"   Stock tras la expiración: {info_final['disponibilidad_actual']} entradas.")