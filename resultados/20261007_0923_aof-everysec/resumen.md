# Resultados requisito 7 - aof-everysec

Fecha: 2026-10-07T09:23:03  
Equipo: Apple M3, 8 núcleos, 16.0 GB RAM, macOS-27.0.1-arm64-arm-64bit-Mach-O  
Redis 7.4.7 (standalone) en localhost:6380; Python 3.13.5, redis-py 8.1.0  
Persistencia: {'save': '', 'appendonly': 'yes', 'appendfsync': 'everysec'}  
Módulo del proyecto medido: `reservas.py`; claves en Redis: 72,535  
Parámetros: {'n': 5000, 'calentamiento': 500, 'repeticiones': 3, 'hilos': [1, 8, 32, 64], 'ops_concurrencia': 10000}

## Latencia (1 cliente, mediana de las repeticiones)

| Operación | Tipo | Req. | Promedio (ms) | p50 (ms) | p95 (ms) | p99 (ms) | ops/s | Éxito |
|---|---|---|---:|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | lectura | base | 0.078 | 0.077 | 0.085 | 0.091 | 12,794 | 100 % |
| SET clave (Redis directo) | escritura | base | 0.086 | 0.084 | 0.094 | 0.108 | 11,563 | 100 % |
| DECRBY stock (Redis directo) | atómica | base | 0.083 | 0.082 | 0.089 | 0.109 | 12,035 | 100 % |
| consultar_disponibilidad | lectura | R1 | 0.079 | 0.077 | 0.086 | 0.101 | 12,718 | 100 % |
| crear_reserva_temporal | escritura + atómica | R2/R4 | 0.114 | 0.112 | 0.121 | 0.159 | 8,785 | 100 % |
| confirmar_reserva | atómica | R3/R4 | 0.107 | 0.102 | 0.129 | 0.136 | 9,380 | 100 % |
| cancelar_reserva | atómica | R3/R4 | 0.105 | 0.103 | 0.113 | 0.141 | 9,481 | 100 % |
| agregar_item (carrito) | escritura + atómica | R5 | 0.206 | 0.205 | 0.216 | 0.233 | 4,854 | 100 % |
| ver_carrito | lectura | R5 | 0.094 | 0.092 | 0.100 | 0.121 | 10,624 | 100 % |
| verificar_intento (usuario + IP) | atómica | R6 | 0.106 | 0.105 | 0.110 | 0.133 | 9,445 | 100 % |

## Rendimiento con clientes concurrentes

| Operación | Hilos | ops/s | p50 (ms) | p99 (ms) | Éxito |
|---|---:|---:|---:|---:|---:|
| GET stock (Redis directo) | 1 | 10,036 | 0.092 | 0.118 | 100.0 % |
| GET stock (Redis directo) | 8 | 24,948 | 0.275 | 0.661 | 100.0 % |
| GET stock (Redis directo) | 32 | 24,849 | 1.038 | 3.511 | 100.0 % |
| GET stock (Redis directo) | 64 | 24,585 | 2.051 | 7.914 | 100.0 % |
| consultar_disponibilidad | 1 | 10,532 | 0.090 | 0.119 | 100.0 % |
| consultar_disponibilidad | 8 | 24,444 | 0.280 | 0.686 | 100.0 % |
| consultar_disponibilidad | 32 | 24,685 | 1.074 | 3.902 | 100.0 % |
| consultar_disponibilidad | 64 | 24,541 | 2.066 | 9.416 | 100.0 % |
| crear_reserva_temporal | 1 | 7,920 | 0.120 | 0.167 | 100.0 % |
| crear_reserva_temporal | 8 | 21,573 | 0.336 | 0.642 | 100.0 % |
| crear_reserva_temporal | 32 | 22,145 | 1.170 | 4.982 | 100.0 % |
| crear_reserva_temporal | 64 | 21,530 | 2.237 | 11.278 | 100.0 % |
| confirmar_reserva | 1 | 8,288 | 0.109 | 0.145 | 100.0 % |
| confirmar_reserva | 8 | 23,197 | 0.296 | 0.661 | 100.0 % |
| confirmar_reserva | 32 | 24,123 | 1.067 | 4.341 | 100.0 % |
| confirmar_reserva | 64 | 23,173 | 2.142 | 11.892 | 100.0 % |
| agregar_item (carrito) | 1 | 4,613 | 0.208 | 0.243 | 100.0 % |
| agregar_item (carrito) | 8 | 10,926 | 0.676 | 1.325 | 100.0 % |
| agregar_item (carrito) | 32 | 11,161 | 2.565 | 7.039 | 100.0 % |
| agregar_item (carrito) | 64 | 10,971 | 5.118 | 15.049 | 100.0 % |
| verificar_intento (usuario + IP) | 1 | 8,290 | 0.110 | 0.146 | 100.0 % |
| verificar_intento (usuario + IP) | 8 | 22,191 | 0.319 | 0.740 | 100.0 % |
| verificar_intento (usuario + IP) | 32 | 22,324 | 1.142 | 4.826 | 100.0 % |
| verificar_intento (usuario + IP) | 64 | 20,576 | 2.398 | 12.242 | 100.0 % |
