import json
import random
import time

#Configuración de Semilla para Garantizar Reproducibilidad
SEED = 42
random.seed(SEED)

def generate_events_data():
    """
    Genera 5 eventos con varias zonas y un inventario total >= 20,000 entradas.
    Estructura Clave-Valor explícita:
      - event:{event_id} -> Metadata del evento
      - event:{event_id}:zone:{zone_id}:stock -> Cantidad de entradas disponibles
      - ticket:{event_id}:{zone_id}:{seat_id} -> Estado del asiento individual
    """
    events = [
        {"id": "EVT-101", "name": "Coldplay Music of the Spheres", "venue": "Estadio Nacional", "date": "2026-11-15"},
        {"id": "EVT-102", "name": "Bad Bunny World Tour", "venue": "Estadio Ricardo Saprissa", "date": "2026-12-01"},
        {"id": "EVT-103", "name": "Clásico San José vs Alajuela", "venue": "Estadio Nacional", "date": "2026-10-20"},
        {"id": "EVT-104", "name": "Festival Imperial 2026", "venue": "Parque Viva", "date": "2026-12-18"},
        {"id": "EVT-105", "name": "Keane 20th Anniversary", "venue": "Anfiteatro Coca-Cola", "date": "2026-11-05"}
    ]

    zones_template = [
        {"zone_id": "VIP", "price": 120, "capacity": 1000},
        {"zone_id": "PREMB", "price": 85, "capacity": 1500},
        {"zone_id": "GENERAL", "price": 45, "capacity": 2000}
    ]

    kv_data = {}
    total_inventory = 0

    for event in events:
        evt_id = event["id"]
        # Clave metadata del evento
        kv_data[f"event:{evt_id}"] = json.dumps(event)

        for zone in zones_template:
            z_id = zone["zone_id"]
            capacity = zone["capacity"]
            total_inventory += capacity

            # Clave de stock por zona
            kv_data[f"event:{evt_id}:zone:{z_id}:stock"] = str(capacity)
            # Clave de precio por zona
            kv_data[f"event:{evt_id}:zone:{z_id}:price"] = str(zone["price"])

            # Estructura individual de tiquetes (0 = Disponible, 1 = Reservado, 2 = Vendido)
            for seat_num in range(1, capacity + 1):
                ticket_key = f"ticket:{evt_id}:{z_id}:{seat_num}"
                kv_data[ticket_key] = json.dumps({"status": "AVAILABLE", "price": zone["price"]})

    print(f"[+] Eventos y zonas generados. Inventario total de entradas: {total_inventory}")
    return kv_data, events, zones_template

def generate_users(total_users=50000):
    """
    Genera 50,000 usuarios simulados.
    Estructura Clave-Valor:
      - user:{user_id} -> Datos del perfil de usuario
      - rate_limit:{user_id} -> Contador de solicitudes
    """
    kv_users = {}
    user_ids = []

    for i in range(1, total_users + 1):
        uid = f"USR-{i:05d}"
        user_ids.append(uid)
        user_data = {
            "user_id": uid,
            "email": f"user_{i}@ejemplo.cr",
            "ip": f"190.113.{random.randint(1, 254)}.{random.randint(1, 254)}"
        }
        kv_users[f"user:{uid}"] = json.dumps(user_data)

    print(f"[+] {total_users} usuarios simulados generados.")
    return kv_users, user_ids

def generate_reservation_attempts(user_ids, events, zones, total_attempts=100000):
    """
    Genera 100,000 intentos de reserva con distribución realista para concurrencia.
    """
    attempts = []
    base_timestamp = int(time.time())

    for i in range(1, total_attempts + 1):
        uid = random.choice(user_ids)
        event = random.choice(events)
        zone = random.choice(zones)
        quantity = random.choices([1, 2, 4, 6], weights=[0.4, 0.4, 0.15, 0.05])[0]

        attempts.append({
            "attempt_id": f"ATT-{i:06d}",
            "user_id": uid,
            "event_id": event["id"],
            "zone_id": zone["zone_id"],
            "quantity": quantity,
            "timestamp": base_timestamp + random.randint(0, 3600)  # Ventana de 1 hora
        })

    print(f"[+] {total_attempts} intentos de reserva generados.")
    return attempts

def main():
    print("=== Generador de Datos y Carga Inicial - EntradaFlash CR ===")
    
    # 1. Generar estructuras
    kv_events_data, events, zones = generate_events_data()
    kv_users_data, user_ids = generate_users(50000)
    attempts = generate_reservation_attempts(user_ids, events, zones, 100000)

    # 2. Consolidar dataset de Claves y Valores explícitos
    full_kv_dataset = {**kv_events_data, **kv_users_data}

    # 3. Exportar a archivos JSON para inspección o carga
    print("\n[+] Guardando dataset en disco...")
    
    with open("dataset_kv_initial.json", "w") as f:
        json.dump(full_kv_dataset, f, indent=2)
        
    with open("reservation_attempts.json", "w") as f:
        json.dump(attempts, f, indent=2)

    print("\n¡Generación completada con éxito!")
    print(f"- Muestra de Claves generadas: {list(full_kv_dataset.keys())[:5]}")
    print(f"- Archivos de salida: 'dataset_kv_initial.json' y 'reservation_attempts.json'")

if __name__ == "__main__":
    main()
