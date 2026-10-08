# Prueba de caída - rdb

Fecha: 2026-10-07 09:21  
Módulo: `reservas.py`  
Persistencia de Redis: `{'save': '300 100', 'appendonly': 'no', 'appendfsync': 'everysec'}`  

| Dato | Antes de la caída | Después de reiniciar |
|---|---:|---:|
| Claves totales en Redis | 72,570 | 72,535 |
| Dataset (usuarios de prueba presentes, de 2) | 2 | 2 |
| Stock VIP EVT-101 | 1000 | 1000 |
| Ventas confirmadas (de 10) | 10 | 0 |
| Reservas pendientes vivas (de 5) | 5 | 0 |
| Stock zona demo | 70 | None |
| Entradas en el carrito abierto (req. 5) | 3 | 0 |
| Stock zona demo tras vencer las pendientes (correcto: 80) | - | None |



**Veredicto:** PÉRDIDA PARCIAL: Redis volvió con el último snapshot (72,535 claves), pero se perdieron las 10 ventas confirmadas y las reservas hechas después de ese snapshot. Esas entradas aparecerían otra vez como disponibles (riesgo de sobreventa).
