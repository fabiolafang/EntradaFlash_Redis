# Resiliencia: ¿qué pasa si Redis se cae?


## 1. El riesgo para EntradaFlash CR

Redis guarda todos los datos **en memoria RAM**; por eso responde en
fracciones de milisegundo. La contracara es que, si el proceso se detiene de
forma abrupta (corte de luz, falla del servidor, `kill -9`), lo que no se haya
escrito en disco se pierde.

Para EntradaFlash esto es grave por una razón concreta: si se pierden las
**ventas confirmadas** pero el inventario se vuelve a cargar desde los datos
originales, esas entradas **aparecen otra vez como disponibles** y se pueden
vender dos veces. Es decir, una caída sin persistencia produce justamente el
problema que el cliente quiere eliminar: **la sobreventa**.

## 2. Cómo protege Redis los datos

### 2.1 Persistencia en disco

Redis ofrece dos mecanismos que pueden usarse juntos [1]:

| Mecanismo | Cómo funciona | Qué se puede perder en una caída | Costo |
|---|---|---|---|
| **RDB** (snapshots) | Cada cierto tiempo o cantidad de cambios, Redis crea un proceso hijo (fork) que guarda una "foto" completa de los datos en un archivo `dump.rdb`. | Todo lo escrito después del último snapshot (normalmente minutos). | Bajo en operación normal; el fork consume memoria con datasets grandes. |
| **AOF** (Append Only File) | Registra cada operación de escritura en un archivo; al reiniciar, Redis la vuelve a ejecutar para reconstruir los datos. Desde Redis 7 se divide en un archivo base y archivos incrementales con un manifiesto. | Depende de `appendfsync` (ver abajo). | Mayor uso de disco; con `always`, más latencia en escrituras. |

Opciones de `appendfsync` (cada cuánto se fuerza la escritura física a disco) [1]:

| Opción | Pérdida máxima ante una caída | Comentario |
|---|---|---|
| `always` | Prácticamente nada | La más segura y la más lenta. |
| `everysec` (por defecto) | Alrededor de 1 segundo | Equilibrio recomendado por la documentación oficial. |
| `no` | Lo que el sistema operativo no haya escrito (en Linux, típicamente hasta ~30 s) | Rápida, pero poco segura. |

Si ambos mecanismos están activos, al reiniciar Redis usa el AOF porque es el
más completo [1]. La documentación recomienda usar ambos cuando se busca una
seguridad de datos comparable a la de una base relacional [1].

### 2.2 Qué pasa con las reservas temporales (TTL) después de una caída

Redis guarda el vencimiento de cada clave como una **marca de tiempo absoluta**
(Unix, en milisegundos), así que "el tiempo sigue corriendo aunque Redis esté
apagado" [2]. Si una reserva pendiente vencía durante la caída, al reiniciar
ya aparece como vencida. Además, cuando una clave vence, Redis registra un
`DEL` en el AOF y lo envía a las réplicas, para que todas las copias queden
consistentes [2].

Hay un detalle importante del diseño: **Redis borra la reserva vencida, pero
no ejecuta ninguna lógica, así que no devuelve el stock por sí solo.** Por eso
`src/reservas.py` guarda las reservas pendientes en un ZSET
(`reservations:pending`) con su hora de vencimiento y un proceso liberador
devuelve el inventario. Como ese ZSET también se persiste, después de reiniciar
el liberador encuentra las reservas vencidas y devuelve sus entradas. La
primera versión (`legado/funciones.py`) no tenía este mecanismo: en la prueba
de caída, las entradas de las reservas vencidas quedaban atrapadas.

Lo mismo aplica a las otras claves con TTL del sistema:

- **Carrito (`cart:{usuario}`, requisito 5):** con persistencia, el usuario
  recupera su carrito después de la caída con el tiempo que le quedaba; si la
  caída duró más que ese tiempo, al volver ya está vencido. Sin persistencia,
  todos los carritos se pierden.
- **Control de intentos (`rate_limit:{usuario}`, `rate_limit:ip:{ip}`,
  requisito 6):** con persistencia, los contadores siguen vigentes después del
  reinicio. Sin persistencia vuelven a cero, y un bot recupera de inmediato su
  cuota de intentos justo cuando el sistema se está recuperando.

### 2.3 Réplicas

Un servidor principal (master) puede tener una o varias réplicas que reciben
una copia de cada escritura. La replicación es **asíncrona por defecto**: el
master responde al cliente sin esperar a la réplica, lo que mantiene la baja
latencia [3]. El comando `WAIT` permite esperar a que N réplicas confirmen una
escritura, pero no garantiza consistencia fuerte: escrituras confirmadas
todavía pueden perderse durante un cambio de master [3].

Advertencia de la documentación que aplica directamente a este caso [3]: un
master **sin persistencia y con reinicio automático** es peligroso. Si se cae y
se reinicia vacío, las réplicas se sincronizan con él y **borran su propia
copia**. Por eso, si se usan réplicas, el master debe tener persistencia.

### 2.4 Alta disponibilidad: Redis Sentinel

Sentinel vigila al master y a las réplicas, avisa cuando hay fallas y, si el
master cae, **promueve automáticamente una réplica** y les indica a los clientes
la nueva dirección [4]. Se recomiendan **al menos tres instancias de Sentinel**
en máquinas independientes [4]. Como la replicación es asíncrona, Sentinel
tampoco garantiza que se conserven todas las escrituras confirmadas durante una
falla [4].

### 2.5 Escalabilidad: Redis Cluster

Redis Cluster reparte las claves en 16 384 *hash slots* entre varios masters,
cada uno con sus réplicas. Permite crecer horizontalmente, pero las
operaciones atómicas de varias claves (como nuestros scripts Lua) exigen que
todas las claves estén en el mismo slot, lo que se logra con *hash tags*
(por ejemplo `{EVT-101}`) [5]. Esto implicaría dividir por evento el registro
global `reservations:pending` de `reservas.py`. En este proyecto no se implementó Cluster; queda
como trabajo futuro.

## 3. Prueba práctica: caída abrupta del servicio

**Procedimiento.** Para cada configuración se levantó un Redis nuevo en el
puerto 6380 (Redis 7.4.7, en una MacBook Air con Apple M3, 8 núcleos y 16 GB
de RAM, macOS), se cargó el dataset del proyecto con `seed_redis.py` y se ejecutó
`prueba_caida.py`, que:

1. Crea un evento de prueba con 100 entradas.
2. Registra 10 ventas confirmadas de 2 entradas (20 vendidas) y 5 reservas
   pendientes de 2 entradas con TTL de 15 s (10 apartadas). Stock esperado: 70.
   Además deja un carrito abierto con 3 entradas (requisito 5).
3. A los 2 segundos **mata el proceso** con `kill -9` (SIGKILL, equivalente
   a un corte de luz; no se usa un apagado normal como `redis-cli shutdown`
   porque ese guarda los datos antes de salir).
4. Vuelve a levantar Redis con la misma configuración, espera a que venzan las reservas pendientes y
   compara el estado antes y después.

Comando (desde `pruebas/`): `./experimento_caida.sh`. Código medido: `src/reservas.py` y `src/sesiones.py`.

**Resultados** (detalle en `resultados/caida_*.md`):

| Configuración | Claves después del reinicio | Ventas confirmadas que sobrevivieron (de 10) | Carrito recuperado (de 3 entradas) | Stock final de la zona (correcto: 80) | Veredicto |
|---|---:|---:|---:|---:|---|
| Sin persistencia | 0 (de 72 570) | 0 | 0 | — (la zona desapareció) | Se perdió todo |
| RDB (último snapshot antes de las ventas) | 72 535 (de 72 570) | 0 | 0 | — (la zona era posterior al snapshot) | Pérdida parcial |
| AOF `everysec` | 72 570 (de 72 570) | 10 | 3 | 80 | Sin pérdida |

**Interpretación.**

- **Sin persistencia** Redis volvió completamente vacío: se perdieron el
  inventario, los 50 000 usuarios, las ventas confirmadas y el carrito. Para
  seguir operando habría que recargar el inventario desde los datos originales,
  y las entradas ya vendidas aparecerían otra vez como disponibles.
- **Con RDB** volvió el dataset del último snapshot (72 535 claves), pero todo
  lo escrito después se perdió: las 10 ventas confirmadas, las 5 reservas
  pendientes y el carrito. Es la ventana de pérdida propia de los snapshots.
- **Con AOF `everysec`** no se perdió nada: las 10 ventas, las 5 reservas y el
  carrito (3 entradas) volvieron igual. Además, las reservas pendientes
  vencieron mientras Redis estaba caído y el liberador devolvió sus 10
  entradas, por lo que el stock quedó en 80, el valor correcto.

## 4. ¿Cuánto cuesta la persistencia en rendimiento?

Comando (desde `pruebas/`): `./experimento_persistencia.sh`. Se ejecuta el mismo benchmark del
requisito 7 sobre el mismo Redis, cambiando solo la persistencia.

Resultados (detalle en `resultados/comparacion_persistencia.md`):

| Operación | Sin persistencia p50 / p99 (ms) | AOF everysec p50 / p99 (ms) | AOF always p50 / p99 (ms) |
|---|---:|---:|---:|
| consultar_disponibilidad (lectura) | 0.077 / 0.088 | 0.077 / 0.101 | 0.081 / 0.104 |
| crear_reserva_temporal | 0.102 / 0.118 | 0.112 / 0.159 | 3.999 / 4.949 |
| confirmar_reserva | 0.085 / 0.115 | 0.102 / 0.136 | 4.000 / 5.546 |
| cancelar_reserva | 0.097 / 0.132 | 0.103 / 0.141 | 4.002 / 6.222 |
| agregar_item (carrito) | 0.196 / 0.223 | 0.205 / 0.233 | 4.946 / 9.046 |
| ver_carrito (lectura) | 0.092 / 0.119 | 0.092 / 0.121 | 0.086 / 0.109 |
| verificar_intento | 0.098 / 0.125 | 0.105 / 0.133 | 4.000 / 6.005 |

**Interpretación.**

- **Las lecturas no cambian** con ninguna configuración (≈ 0.08–0.09 ms),
  porque la persistencia solo afecta a las escrituras.
- **AOF `everysec` cuesta muy poco:** las escrituras pasan de ≈ 0.09–0.10 ms a
  ≈ 0.10–0.11 ms en la mediana (entre 0 % y 20 % más), a cambio de reducir la
  pérdida máxima ante una caída a cerca de 1 segundo.
- **AOF `always` es unas 40 a 50 veces más lento en las escrituras:** cada una
  tarda ≈ 4 ms porque Redis espera a que el disco confirme antes de responder.
  Con un cliente, `crear_reserva_temporal` baja de ≈ 8 700 a ≈ 220
  operaciones por segundo, un costo demasiado alto para una preventa con miles
  de solicitudes simultáneas.

## 5. Recomendación para EntradaFlash CR

| Necesidad | Configuración recomendada | Por qué |
|---|---|---|
| No perder ventas | AOF `appendfsync everysec` + snapshots RDB | Pérdida máxima ≈ 1 s con un costo de rendimiento bajo (sección 4); el RDB da respaldos compactos y reinicios rápidos. |
| Seguir vendiendo si cae el servidor | 1 master + al menos 1 réplica + 3 Sentinel | Cambio automático a la réplica en segundos. |
| Ventas críticas (por ejemplo, la confirmación de pago) | `WAIT 1 <timeout>` después de confirmar | Asegura que la venta llegó al menos a una réplica antes de responder al cliente. |
| Crecer a muchos eventos simultáneos | Redis Cluster con *hash tags* por evento | Reparte la carga sin romper la atomicidad de los scripts Lua. |
| Inventario sin entradas atrapadas | Liberador de reservas vencidas (`src/reservas.py`) | Devuelve el stock de reservas que vencieron, incluso después de una caída. |
| Que los bots no aprovechen un reinicio | Persistencia activa (los contadores de `rate_limit` sobreviven) | Sin persistencia, todos los contadores vuelven a cero. |

**Limitaciones:** las pruebas se hicieron con un solo nodo en una sola máquina; no se probaron réplicas, Sentinel
ni Cluster en la práctica; con `everysec` sigue existiendo una ventana de
hasta ~1 s de pérdida.

## Referencias

[1] Redis Ltd., "Redis persistence," *Redis Documentation*. [En línea]. Disponible: https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/ [Accedido: 7-oct-2026].

[2] Redis Ltd., "EXPIRE," *Redis Documentation*. [En línea]. Disponible: https://redis.io/docs/latest/commands/expire/ [Accedido: 7-oct-2026].

[3] Redis Ltd., "Redis replication," *Redis Documentation*. [En línea]. Disponible: https://redis.io/docs/latest/operate/oss_and_stack/management/replication/ [Accedido: 7-oct-2026].

[4] Redis Ltd., "High availability with Redis Sentinel," *Redis Documentation*. [En línea]. Disponible: https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/ [Accedido: 7-oct-2026].

[5] Redis Ltd., "Scale with Redis Cluster," *Redis Documentation*. [En línea]. Disponible: https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/ [Accedido: 7-oct-2026].


