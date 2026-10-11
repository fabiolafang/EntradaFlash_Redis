# EntradaFlash CR con Redis

Investigación Grupal 1 (Desafío NoSQL) del curso XS0131, UCR. Nos tocó el caso
EntradaFlash CR con el modelo clave-valor, y usamos Redis.

La idea es simular la preventa de un evento grande: mucha gente consulta
entradas, las reserva por un rato y después las confirma o las cancela, sin que
se venda dos veces la misma entrada ni quede el inventario en negativo.

## Qué hay en cada carpeta

- `src/`: el código oficial del sistema.
  - `reservas.py`: consultar disponibilidad, reservar con vencimiento,
    confirmar, cancelar y devolver el stock cuando una reserva vence (con un
    hilo liberador automático). Usa scripts Lua para que dos personas no se
    lleven la misma entrada.
  - `sesiones.py`: el carrito de cada usuario, que se borra solo si lo
    abandonan.
  - `rate_limit.py`: límite de intentos por usuario y por IP, para frenar bots.
- `pruebas/`: todo lo que verifica y mide el sistema.
  - `test_reservas.py`, `test_sesiones.py` y `test_rate_limit.py`: pruebas
    automáticas (53 en total).
  - `prueba_concurrencia.py`: reproduce los 100,000 intentos de reserva con
    muchos hilos y comprueba que el inventario cuadre, sin sobreventa.
  - `benchmark_req7.py`: mide latencia y rendimiento (requisito 7).
  - `prueba_caida.py`, `experimento_caida.sh` y `experimento_persistencia.sh`:
    resiliencia ante la caída de Redis (requisito 7).
  - `medir_rendimiento_req1_req2.py`: medición sencilla y anterior de los
    requisitos 1 y 2, de las primeras versiones.
- `demos/`: las demostraciones que usamos en la presentación, una por pareja de
  requisitos.
- `datos/`: generación y carga de los datos de prueba. `Datos_generados.py`
  crea 5 eventos con 3 zonas cada uno, 50,000 usuarios y 100,000 intentos de
  reserva (con semilla fija, así que sale siempre lo mismo); `seed_redis.py` los
  carga a Redis desde `dataset_kv_initial.json`.
- `resultados/`: lo que dieron las mediciones del requisito 7, ya guardado
  (ver más abajo).
- `docs/`: el paper en formato IEEE (`IEEE.pdf` y su borrador `IEEE (borrador).docx`)
  y `RESILIENCIA.md`, que explica qué pasa si Redis se cae y cómo se protege
  (RDB y AOF).
- `legado/`: las primeras versiones del código (`funciones.py`, `req1_req2.py`
  y `req3_req4.py`). No devuelven el stock de las reservas vencidas
  automáticamente. Las dejamos por el historial, y `demos/demo_req1_req2.py` y
  la opción `--modulo funciones` del benchmark todavía las usan, pero el
  sistema oficial es `src/`.

## Claves en Redis

- `event:{evento}:zone:{zona}:stock`: entradas disponibles de cada zona.
- `reservation:{usuario}:{evento}:{zona}`: la reserva de un usuario, con su
  estado (pendiente, confirmada o cancelada).
- `cart:{usuario}`: el carrito del usuario (un hash, con vencimiento que se
  renueva al usarlo).
- `rate_limit:{usuario}` y `rate_limit:ip:{ip}`: contadores de intentos
  (ventana fija de 60 segundos).
- `user:{usuario}`: el perfil del usuario, que incluye su IP.

## Para correrlo

Hace falta Python 3 y Redis. En Windows, Redis se puede usar con Docker o con
WSL. Las librerías de Python se instalan con:

```
pip install -r requirements.txt
```

Todo el código se conecta a Redis en el puerto 6380, así que se puede levantar
una instancia aparte sin tocar la normal:

```
redis-server --port 6380 --daemonize yes
```

Los comandos se ejecutan desde la carpeta principal del repositorio. Primero se
cargan los datos (esto se puede correr desde cualquier carpeta):

```
python datos/seed_redis.py
```

Ojo con este paso: `seed_redis.py` borra todo lo que haya en esa base antes de
cargar, así que no hay que apuntarlo a una base con datos que importen.

Las pruebas automáticas se corren con:

```
python -m pytest -v
```

Las demos y las pruebas de concurrencia son scripts sueltos, y necesitan saber
dónde está `src`. Se le indica con `PYTHONPATH`.

En Linux o Mac:

```
export PYTHONPATH=src
```

En Windows (PowerShell):

```
$env:PYTHONPATH = "src"
```

## Demos

| Script | Qué muestra |
|---|---|
| `demos/demo_req1_req2.py` | Disponibilidad y reserva temporal con su vencimiento, con la versión de `legado/`. |
| `demos/demo_req3_req4.py` | Confirmar, cancelar, vencimiento automático, dos clientes compitiendo por la última entrada y validaciones (casos A a E). |
| `demos/demo_req5_req6.py` | Carrito: armarlo, que se borre solo y finalizarlo en reservas (casos A a C). Límite de intentos por usuario y por IP (casos D y E). Un bot con 200 intentos simultáneos contra un límite de 20 (caso F). |

```
python demos/demo_req1_req2.py
python demos/demo_req3_req4.py
python demos/demo_req5_req6.py
```

Con `--pausa` las demos esperan un Enter entre caso y caso, que sirve para la
presentación. En `demo_req5_req6.py` también se pueden elegir casos con
`--casos`, por ejemplo `python demos/demo_req5_req6.py --pausa --casos ABCF`.

Las demos modifican el stock, así que conviene correr `seed_redis.py` antes de
cada una. `demo_req1_req2.py` no hay que interrumpirla a la mitad: si se corta,
quedan entradas descontadas que su versión no devuelve sola, y por eso el stock
puede mostrar 996 en vez de 1000. Con volver a correr `seed_redis.py` se
arregla.

## Prueba de concurrencia

```
python datos/seed_redis.py
python pruebas/prueba_concurrencia.py
```

Reproduce los intentos de `datos/reservation_attempts.json` con 64 hilos y
revisa, zona por zona, que lo vendido cuadre con el stock inicial, que el stock
nunca baje de 0 y que no queden reservas sin liberar. Termina con un veredicto.
La prueba vende entradas reales del dataset, por lo que hay que volver a correr
`seed_redis.py` antes de cada corrida (si no, da un falso "inconsistencia" por
reservas sobrantes de la corrida anterior) y después, para dejar el inventario
original.

## Requisito 7: rendimiento y resiliencia

Resultados guardados en `resultados/`. Las mediciones se hicieron en un MacBook
con Apple M3 y 16 GB de RAM, con Redis 7.4.7 en el puerto 6380.

- `resultados/20261007_0919_final/`: latencia con un cliente y rendimiento con
  1, 8, 32 y 64 hilos (`resumen.md`, `latencia.csv`, `rendimiento.csv` y
  `entorno.json`).
- `resultados/..._sin-persistencia/`, `..._aof-everysec/` y `..._aof-always/`:
  la misma medición con cada configuración de persistencia.
- `resultados/comparacion_persistencia.md`: tabla comparativa de las tres.
- `resultados/caida_*.md` y `caida_*.json`: qué sobrevivió a una caída
  abrupta (`kill -9`) con sin persistencia, RDB y AOF everysec.

Para repetirlo (con Redis en el puerto 6380, y `redis-server` o Docker
instalado):

```
python datos/seed_redis.py
python pruebas/benchmark_req7.py --etiqueta final
bash pruebas/experimento_persistencia.sh
bash pruebas/experimento_caida.sh
```

`benchmark_req7.py` acepta `--rapido` para una corrida corta de verificación y
`--modulo funciones` para medir la versión de `legado/`. Los dos `.sh` son para
Linux o Mac (en Windows, desde WSL), y el de caída reinicia Redis a la fuerza.

## Integrantes

- Angelina: disponibilidad y reserva temporal (requisitos 1 y 2)
- Ana Paula: confirmación, cancelación y concurrencia (requisitos 3 y 4)
- Sebastián: carrito y control de intentos (requisitos 5 y 6)
- Luis: rendimiento y resiliencia (requisito 7)
- Abigail: paper en formato IEEE
- Fabiola: repositorio, presentación y entrega
