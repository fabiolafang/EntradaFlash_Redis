# Resultados requisito 7 - final

Fecha: 2026-10-07T09:19:34  
Equipo: Apple M3, 8 núcleos, 16.0 GB RAM, macOS-27.0.1-arm64-arm-64bit-Mach-O  
Redis 7.4.7 (standalone) en localhost:6380; Python 3.13.5, redis-py 8.1.0  
Persistencia: {'save': '3600 1 300 100 60 10000', 'appendonly': 'no', 'appendfsync': 'everysec'}  
Módulo del proyecto medido: `reservas.py`; claves en Redis: 72,535  
Parámetros: {'n': 5000, 'calentamiento': 500, 'repeticiones': 3, 'hilos': [1, 8, 32, 64], 'ops_concurrencia': 10000}

## Latencia (1 cliente, mediana de las repeticiones)

| Operación | Tipo | Req. | Promedio (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/s | Éxito |
|---|---|---|---:|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | lectura | base | 0.082 | 0.081 | 0.092 | 0.102 | 12,140 | 100 % |
| SET clave (Redis directo) | escritura | base | 0.086 | 0.085 | 0.092 | 0.102 | 11,692 | 100 % |
| DECRBY stock (Redis directo) | atómica | base | 0.082 | 0.082 | 0.088 | 0.092 | 12,196 | 100 % |
| consultar_disponibilidad | lectura | R1 | 0.080 | 0.080 | 0.085 | 0.088 | 12,536 | 100 % |
| crear_reserva_temporal | escritura + atómica | R2/R4 | 0.098 | 0.098 | 0.105 | 0.140 | 10,192 | 100 % |
| confirmar_reserva | atómica | R3/R4 | 0.087 | 0.086 | 0.096 | 0.111 | 11,560 | 100 % |
| cancelar_reserva | atómica | R3/R4 | 0.095 | 0.095 | 0.100 | 0.126 | 10,577 | 100 % |
| agregar_item (carrito) | escritura + atómica | R5 | 0.188 | 0.189 | 0.201 | 0.214 | 5,308 | 100 % |
| ver_carrito | lectura | R5 | 0.090 | 0.090 | 0.094 | 0.117 | 11,111 | 100 % |
| verificar_intento (usuario + IP) | atómica | R6 | 0.095 | 0.095 | 0.101 | 0.121 | 10,490 | 100 % |

## Rendimiento con clientes concurrentes

| Operación | Hilos | ops/s | p50 (ms) | p99 (ms) | Éxito |
|---|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | 1 | 10,795 | 0.086 | 0.100 | 100.0 % |
| GET stock (Redis directo) | 8 | 24,888 | 0.275 | 0.700 | 100.0 % |
| GET stock (Redis directo) | 32 | 24,907 | 1.032 | 3.692 | 100.0 % |
| GET stock (Redis directo) | 64 | 24,493 | 2.042 | 7.429 | 100.0 % |
| consultar_disponibilidad | 1 | 10,481 | 0.091 | 0.105 | 100.0 % |
| consultar_disponibilidad | 8 | 24,139 | 0.282 | 0.713 | 100.0 % |
| consultar_disponibilidad | 32 | 25,543 | 1.045 | 3.579 | 100.0 % |
| consultar_disponibilidad | 64 | 24,624 | 2.048 | 8.208 | 100.0 % |
| crear_reserva_temporal | 1 | 8,710 | 0.107 | 0.154 | 100.0 % |
| crear_reserva_temporal | 8 | 21,147 | 0.323 | 0.809 | 100.0 % |
| crear_reserva_temporal | 32 | 21,949 | 1.169 | 5.092 | 100.0 % |
| crear_reserva_temporal | 64 | 21,378 | 2.265 | 10.356 | 100.0 % |
| confirmar_reserva | 1 | 9,405 | 0.100 | 0.135 | 100.0 % |
| confirmar_reserva | 8 | 23,321 | 0.298 | 0.734 | 100.0 % |
| confirmar_reserva | 32 | 23,809 | 1.077 | 4.194 | 100.0 % |
| confirmar_reserva | 64 | 22,939 | 2.136 | 9.855 | 100.0 % |
| agregar_item (carrito) | 1 | 4,859 | 0.200 | 0.229 | 100.0 % |
| agregar_item (carrito) | 8 | 10,787 | 0.680 | 1.419 | 100.0 % |
| agregar_item (carrito) | 32 | 11,093 | 2.580 | 7.207 | 100.0 % |
| agregar_item (carrito) | 64 | 10,869 | 5.129 | 15.015 | 100.0 % |
| verificar_intento (usuario + IP) | 1 | 9,220 | 0.102 | 0.130 | 100.0 % |
| verificar_intento (usuario + IP) | 8 | 22,033 | 0.314 | 0.809 | 100.0 % |
| verificar_intento (usuario + IP) | 32 | 22,127 | 1.152 | 4.513 | 100.0 % |
| verificar_intento (usuario + IP) | 64 | 22,208 | 2.260 | 10.470 | 100.0 % |
