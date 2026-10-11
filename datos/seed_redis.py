import json
from pathlib import Path

import redis

#Conexión a Redis local en el puerto 6380
r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)

# El archivo de datos esta junto a este script: asi funciona desde cualquier carpeta.
ARCHIVO_DATOS = Path(__file__).resolve().parent / "dataset_kv_initial.json"

def cargar_datos_a_redis():
    print("Limpiando Redis...")
    r.flushdb()

    print(f"Cargando '{ARCHIVO_DATOS.name}'...")
    with open(ARCHIVO_DATOS, "r", encoding="utf-8") as f:
        data = json.load(f)

    for key, value in data.items():
        if isinstance(value, dict):
            r.hset(key, mapping=value)
        else:
            r.set(key, value)

    print("¡Datos cargados con éxito en Redis!")

if __name__ == "__main__":
    cargar_datos_a_redis()