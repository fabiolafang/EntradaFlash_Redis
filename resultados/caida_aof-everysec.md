# Prueba de caída - aof-everysec

Fecha: 2026-10-07 09:21  
Módulo: `reservas.py`  
Persistencia de Redis: `{'save': '', 'appendonly': 'yes', 'appendfsync': 'everysec'}`  

| Dato | Antes de la caída | Después de reiniciar |
|---|---:|---:|
| Claves totales en Redis | 72,570 | 72,570 |
| Dataset (usuarios de prueba presentes, de 2) | 2 | 2 |
| Stock VIP EVT-101 | 1000 | 1000 |
| Ventas confirmadas (de 10) | 10 | 10 |
| Reservas pendientes vivas (de 5) | 5 | 5 |
| Stock zona demo | 70 | 70 |
| Entradas en el carrito abierto (req. 5) | 3 | 3 |
| Stock zona demo tras vencer las pendientes (correcto: 80) | - | 80 |

El liberador devolvió 10 entradas de 5 reservas vencidas.

**Veredicto:** SIN PÉRDIDA: sobrevivieron todas las ventas y el inventario quedó correcto después de liberar las reservas vencidas.
