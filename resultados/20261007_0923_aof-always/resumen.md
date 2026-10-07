# Resultados requisito 7 - aof-always

Fecha: 2026-10-07T09:23:53  
Equipo: Apple M3, 8 núcleos, 16.0 GB RAM, macOS-27.0.1-arm64-arm-64bit-Mach-O  
Redis 7.4.7 (standalone) en localhost:6380; Python 3.13.5, redis-py 8.1.0  
Persistencia: {'save': '', 'appendonly': 'yes', 'appendfsync': 'always'}  
Módulo del proyecto medido: `reservas.py`; claves en Redis: 72,535  
Parámetros: {'n': 5000, 'calentamiento': 500, 'repeticiones': 3, 'hilos': [1, 8, 32, 64], 'ops_concurrencia': 10000}

## Latencia (1 cliente, mediana de las repeticiones)

| Operación | Tipo | Req. | Promedio (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/s | Éxito |
|---|---|---|---:|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | lectura | base | 0.078 | 0.077 | 0.085 | 0.091 | 12,864 | 100 % |
| SET clave (Redis directo) | escritura | base | 3.997 | 3.997 | 4.136 | 5.032 | 250 | 100 % |
| DECRBY stock (Redis directo) | atómica | base | 3.967 | 3.995 | 4.073 | 4.152 | 252 | 100 % |
| consultar_disponibilidad | lectura | R1 | 0.082 | 0.081 | 0.086 | 0.104 | 12,231 | 100 % |
| crear_reserva_temporal | escritura + atómica | R2/R4 | 4.014 | 3.999 | 4.261 | 4.949 | 249 | 100 % |
| confirmar_reserva | atómica | R3/R4 | 4.071 | 4.000 | 4.872 | 5.546 | 246 | 100 % |
| cancelar_reserva | atómica | R3/R4 | 4.182 | 4.002 | 5.189 | 6.222 | 239 | 100 % |
| agregar_item (carrito) | escritura + atómica | R5 | 4.800 | 4.946 | 6.690 | 9.046 | 208 | 100 % |
| ver_carrito | lectura | R5 | 0.088 | 0.086 | 0.099 | 0.109 | 11,399 | 100 % |
| verificar_intento (usuario + IP) | atómica | R6 | 4.025 | 4.000 | 5.005 | 6.005 | 248 | 100 % |

## Rendimiento con clientes concurrentes

| Operación | Hilos | ops/s | p50 (ms) | p99 (ms) | Éxito |
|---|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | 1 | 10,024 | 0.090 | 0.133 | 100.0 % |
| GET stock (Redis directo) | 8 | 24,474 | 0.278 | 0.704 | 100.0 % |
| GET stock (Redis directo) | 32 | 24,714 | 1.039 | 3.944 | 100.0 % |
| GET stock (Redis directo) | 64 | 24,323 | 2.052 | 8.425 | 100.0 % |
| consultar_disponibilidad | 1 | 10,318 | 0.090 | 0.101 | 100.0 % |
| consultar_disponibilidad | 8 | 23,932 | 0.280 | 0.740 | 100.0 % |
| consultar_disponibilidad | 32 | 25,257 | 1.044 | 3.684 | 100.0 % |
| consultar_disponibilidad | 64 | 24,432 | 2.042 | 7.574 | 100.0 % |
| crear_reserva_temporal | 1 | 223 | 4.013 | 9.018 | 100.0 % |
| crear_reserva_temporal | 8 | 941 | 8.436 | 12.195 | 100.0 % |
| crear_reserva_temporal | 32 | 2,772 | 11.637 | 17.129 | 100.0 % |
| crear_reserva_temporal | 64 | 6,118 | 9.961 | 21.006 | 100.0 % |
| confirmar_reserva | 1 | 255 | 3.959 | 7.995 | 100.0 % |
| confirmar_reserva | 8 | 775 | 10.103 | 17.043 | 100.0 % |
| confirmar_reserva | 32 | 3,110 | 9.869 | 25.670 | 100.0 % |
| confirmar_reserva | 64 | 6,085 | 10.131 | 18.814 | 100.0 % |
| agregar_item (carrito) | 1 | 158 | 5.964 | 13.090 | 100.0 % |
| agregar_item (carrito) | 8 | 496 | 16.048 | 20.114 | 100.0 % |
| agregar_item (carrito) | 32 | 2,080 | 15.528 | 19.503 | 100.0 % |
| agregar_item (carrito) | 64 | 5,111 | 12.068 | 19.810 | 100.0 % |
| verificar_intento (usuario + IP) | 1 | 246 | 3.975 | 8.004 | 100.0 % |
| verificar_intento (usuario + IP) | 8 | 1,011 | 7.987 | 10.022 | 100.0 % |
| verificar_intento (usuario + IP) | 32 | 3,491 | 9.046 | 16.732 | 100.0 % |
| verificar_intento (usuario + IP) | 64 | 8,044 | 7.888 | 14.780 | 100.0 % |
