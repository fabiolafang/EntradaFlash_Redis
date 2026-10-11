import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "legado"))

from req1_req2 import (
    consultar_disponibilidad,
    crear_reserva_temporal,
    simular_expiracion_y_devolucion,
)

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