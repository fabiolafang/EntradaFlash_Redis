# Prueba de caída - sin-persistencia

Fecha: 2026-10-07 09:20  
Módulo: `reservas.py`  
Persistencia de Redis: `{'save': '', 'appendonly': 'no', 'appendfsync': 'everysec'}`  

| Dato | Antes de la caída | Después de reiniciar |
|---|---:|---:|
| Claves totales en Redis | 72,570 | 0 |
| Dataset (usuarios de prueba presentes, de 2) | 2 | 0 |
| Stock VIP EVT-101 | 1000 | None |
| Ventas confirmadas (de 10) | 10 | 0 |
| Reservas pendientes vivas (de 5) | 5 | 0 |
| Stock zona demo | 70 | None |
| Entradas en el carrito abierto (req. 5) | 3 | 0 |
| Stock zona demo tras vencer las pendientes (correcto: 80) | - | None |



**Veredicto:** SE PERDIÓ TODO: Redis reinició vacío. Habría que recargar el inventario desde otra fuente y las ventas confirmadas desaparecieron (riesgo directo de sobreventa).
