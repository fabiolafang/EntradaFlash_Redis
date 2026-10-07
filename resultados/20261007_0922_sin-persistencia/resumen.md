# Resultados requisito 7 - sin-persistencia

Fecha: 2026-10-07T09:22:15  
Equipo: Apple M3, 8 núcleos, 16.0 GB RAM, macOS-27.0.1-arm64-arm-64bit-Mach-O  
Redis 7.4.7 (standalone) en localhost:6380; Python 3.13.5, redis-py 8.1.0  
Persistencia: {'save': '', 'appendonly': 'no', 'appendfsync': 'everysec'}  
Módulo del proyecto medido: `reservas.py`; claves en Redis: 72,535  
Parámetros: {'n': 5000, 'calentamiento': 500, 'repeticiones': 3, 'hilos': [1, 8, 32, 64], 'ops_concurrencia': 10000}

## Latencia (1 cliente, mediana de las repeticiones)

| Operación | Tipo | Req. | Promedio (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/s | Éxito |
|---|---|---|---:|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | lectura | base | 0.081 | 0.081 | 0.085 | 0.088 | 12,347 | 100 % |
| SET clave (Redis directo) | escritura | base | 0.084 | 0.083 | 0.088 | 0.091 | 11,908 | 100 % |
| DECRBY stock (Redis directo) | atómica | base | 0.081 | 0.081 | 0.086 | 0.089 | 12,317 | 100 % |
| consultar_disponibilidad | lectura | R1 | 0.079 | 0.077 | 0.085 | 0.088 | 12,620 | 100 % |
| crear_reserva_temporal | escritura + atómica | R2/R4 | 0.102 | 0.102 | 0.111 | 0.118 | 9,793 | 100 % |
| confirmar_reserva | atómica | R3/R4 | 0.087 | 0.085 | 0.098 | 0.115 | 11,492 | 100 % |
| cancelar_reserva | atómica | R3/R4 | 0.097 | 0.097 | 0.102 | 0.132 | 10,335 | 100 % |
| agregar_item (carrito) | escritura + atómica | R5 | 0.196 | 0.196 | 0.206 | 0.223 | 5,093 | 100 % |
| ver_carrito | lectura | R5 | 0.092 | 0.092 | 0.096 | 0.119 | 10,825 | 100 % |
| verificar_intento (usuario + IP) | atómica | R6 | 0.098 | 0.098 | 0.104 | 0.125 | 10,193 | 100 % |

## Rendimiento con clientes concurrentes

| Operación | Hilos | ops/s | p50 (ms) | p99 (ms) | Éxito |
|---|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | 1 | 10,373 | 0.091 | 0.101 | 100.0 % |
| GET stock (Redis directo) | 8 | 25,003 | 0.276 | 0.673 | 100.0 % |
| GET stock (Redis directo) | 32 | 24,926 | 1.038 | 3.577 | 100.0 % |
| GET stock (Redis directo) | 64 | 24,454 | 2.043 | 7.967 | 100.0 % |
| consultar_disponibilidad | 1 | 10,567 | 0.090 | 0.103 | 100.0 % |
| consultar_disponibilidad | 8 | 24,392 | 0.280 | 0.698 | 100.0 % |
| consultar_disponibilidad | 32 | 25,193 | 1.052 | 3.648 | 100.0 % |
| consultar_disponibilidad | 64 | 24,732 | 2.044 | 7.685 | 100.0 % |
| crear_reserva_temporal | 1 | 8,809 | 0.107 | 0.154 | 100.0 % |
| crear_reserva_temporal | 8 | 21,521 | 0.321 | 0.764 | 100.0 % |
| crear_reserva_temporal | 32 | 22,059 | 1.159 | 4.606 | 100.0 % |
| crear_reserva_temporal | 64 | 21,492 | 2.271 | 10.254 | 100.0 % |
| confirmar_reserva | 1 | 9,522 | 0.099 | 0.134 | 100.0 % |
| confirmar_reserva | 8 | 23,655 | 0.295 | 0.706 | 100.0 % |
| confirmar_reserva | 32 | 23,964 | 1.071 | 4.045 | 100.0 % |
| confirmar_reserva | 64 | 23,080 | 2.156 | 9.391 | 100.0 % |
| agregar_item (carrito) | 1 | 4,807 | 0.202 | 0.231 | 100.0 % |
| agregar_item (carrito) | 8 | 10,763 | 0.683 | 1.404 | 100.0 % |
| agregar_item (carrito) | 32 | 11,063 | 2.587 | 7.442 | 100.0 % |
| agregar_item (carrito) | 64 | 10,851 | 5.198 | 15.667 | 100.0 % |
| verificar_intento (usuario + IP) | 1 | 9,082 | 0.104 | 0.132 | 100.0 % |
| verificar_intento (usuario + IP) | 8 | 21,769 | 0.317 | 0.834 | 100.0 % |
| verificar_intento (usuario + IP) | 32 | 22,077 | 1.150 | 4.783 | 100.0 % |
| verificar_intento (usuario + IP) | 64 | 22,077 | 2.237 | 9.145 | 100.0 % |
