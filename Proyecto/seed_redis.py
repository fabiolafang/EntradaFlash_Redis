import json
import redis

#Conexión a Redis local en el puerto 6380
r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)

def cargar_datos_a_redis():
    print("Limpiando Redis...")
    r.flushdb()

    print("Cargando 'dataset_kv_initial.json'...")
    with open("dataset_kv_initial.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    for key, value in data.items():
        if isinstance(value, dict):
            r.hset(key, mapping=value)
        else:
            r.set(key, value)

    print("¡Datos cargados con éxito en Redis!")

if __name__ == "__main__":
    cargar_datos_a_redis()