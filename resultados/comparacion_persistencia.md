| Operación | sin-persistencia p50 / p99 (ms) | aof-everysec p50 / p99 (ms) | aof-always p50 / p99 (ms) |
|---|---:|---:|---:|
| GET stock (Redis directo) | 0.081 / 0.088 | 0.077 / 0.091 | 0.077 / 0.091 |
| SET clave (Redis directo) | 0.083 / 0.091 | 0.084 / 0.108 | 3.997 / 5.032 |
| DECRBY stock (Redis directo) | 0.081 / 0.089 | 0.082 / 0.109 | 3.995 / 4.152 |
| consultar_disponibilidad | 0.077 / 0.088 | 0.077 / 0.101 | 0.081 / 0.104 |
| crear_reserva_temporal | 0.102 / 0.118 | 0.112 / 0.159 | 3.999 / 4.949 |
| confirmar_reserva | 0.085 / 0.115 | 0.102 / 0.136 | 4.000 / 5.546 |
| cancelar_reserva | 0.097 / 0.132 | 0.103 / 0.141 | 4.002 / 6.222 |
| agregar_item (carrito) | 0.196 / 0.223 | 0.205 / 0.233 | 4.946 / 9.046 |
| ver_carrito | 0.092 / 0.119 | 0.092 / 0.121 | 0.086 / 0.109 |
| verificar_intento (usuario + IP) | 0.098 / 0.125 | 0.105 / 0.133 | 4.000 / 6.005 |
