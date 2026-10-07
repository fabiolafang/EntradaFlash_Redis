import time
import statistics
import redis

#Conexión a Redis en el puerto 6380
r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)

def medir_latencias():
    latencias_consulta = []
    latencias_reserva = []

    print("Iniciando mediciones de rendimiento (1,000 operaciones en bucle)...")

    for i in range(1, 1001):
        user_id = f"usr_{i:06d}"
        
        #Medir latencia de Consulta de disponibilidad (Req 1)
        inicio = time.perf_counter()
        stock = r.get("event:EVT-101:zone:VIP:stock")
        fin = time.perf_counter()
        latencias_consulta.append((fin - inicio) * 1000)  # Milisegundos

        #Medir latencia de Reserva atómica con TTL (Req 2)
        inicio = time.perf_counter()
        with r.pipeline() as pipe:
            pipe.watch("event:EVT-101:zone:VIP:stock")
            pipe.multi()
            pipe.decrby("event:EVT-101:zone:VIP:stock", 1)
            pipe.hset(f"res_test:{user_id}", mapping={"user": user_id, "qty": 1})
            pipe.expire(f"res_test:{user_id}", 10)
            pipe.execute()
        fin = time.perf_counter()
        latencias_reserva.append((fin - inicio) * 1000)  # Milisegundos

    #Imprimir resultados cuantitativos
    print("\n================ RESULTADOS DE RENDIMIENTO ================")
    print("Requerimiento 1 (Consulta Disponibilidad Key-Value O(1)):")
    print(f" - Latencia promedio: {statistics.mean(latencias_consulta):.4f} ms")
    print(f" - Latencia mínima:   {min(latencias_consulta):.4f} ms")
    print(f" - Latencia máxima:   {max(latencias_consulta):.4f} ms")
    
    print("\nRequerimiento 2 (Reserva Atómica + TTL):")
    print(f" - Latencia promedio: {statistics.mean(latencias_reserva):.4f} ms")
    print(f" - Latencia mínima:   {min(latencias_reserva):.4f} ms")
    print(f" - Latencia máxima:   {max(latencias_reserva):.4f} ms")

if __name__ == "__main__":
    medir_latencias()