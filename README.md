# EntradaFlash CR con Redis

Investigación Grupal 1 (Desafío NoSQL) del curso XS0131, UCR. Nos tocó el caso
EntradaFlash CR con el modelo clave-valor, y usamos Redis.

La idea es simular la preventa de un evento grande: mucha gente consulta
entradas, las reserva por un rato y después las confirma o las cancela, sin que
se venda dos veces la misma entrada ni quede el inventario en negativo.

## Qué hay en cada carpeta

- `src/`: el código del sistema y todo lo que se ejecuta con él.
  - `reservas.py`: consultar disponibilidad, reservar con vencimiento,
    confirmar, cancelar y devolver el stock cuando una reserva vence. Usa
    scripts Lua para que dos personas no se lleven la misma entrada.
  - `sesiones.py`: el carrito de cada usuario, que se borra solo si lo
    abandonan.
  - `rate_limit.py`: límite de intentos por usuario y por IP, para frenar bots.
  - `test_*.py`: las pruebas de cada módulo.
  - `demo_req3_req4.py` y `demo_req5_req6.py`: demos para la presentación.
  - `prueba_concurrencia.py` y `medir_rendimiento_req1_req2.py`: pruebas de
    concurrencia y mediciones de latencia.
- `datos/`: generación y carga de los datos de prueba. `Datos_generados.py`
  crea 5 eventos con 3 zonas cada uno, 50,000 usuarios y 100,000 intentos de
  reserva; `seed_redis.py` los carga a Redis desde `dataset_kv_initial.json`.
  `reservation_attempts.json` son los intentos que usa la prueba de
  concurrencia.
- `legado/`: las primeras versiones de reservas (`funciones.py` y
  `req3_req4.py`). Las dejamos por el historial, pero la que usamos es
  `src/reservas.py`.

## Claves en Redis

- `event:{evento}:zone:{zona}:stock`: entradas disponibles de cada zona.
- `reservation:{usuario}:{evento}:{zona}`: la reserva de un usuario, con su
  estado (pendiente, confirmada o cancelada).
- `cart:{usuario}`: el carrito del usuario.
- `rate_limit:{usuario}` y `rate_limit:ip:{ip}`: contadores de intentos.
- `user:{usuario}`: el perfil del usuario, que incluye su IP.

## Para correrlo

Hace falta Python 3 y Redis. Las librerías de Python se instalan con:

```
pip install -r requirements.txt
```

Todo el código se conecta a Redis en el puerto 6380, así que se puede levantar
una instancia aparte sin tocar la normal:

```
redis-server --port 6380 --daemonize yes
```

Después se cargan los datos desde la carpeta `datos/`:

```
cd datos
python seed_redis.py
```

Ojo con este paso: `seed_redis.py` borra todo lo que haya en esa base antes de
cargar, así que no hay que apuntarlo a una base con datos que importen.

Las pruebas y las demos se corren desde `src/`:

```
cd src
python -m pytest -v
python demo_req3_req4.py
python demo_req5_req6.py
```

Con `--pausa` las demos esperan un Enter entre caso y caso, que sirve para la
presentación. Como `reservation_attempts.json` está en `datos/`, la prueba de
concurrencia se corre indicando dónde está:

```
python prueba_concurrencia.py --archivo ../datos/reservation_attempts.json
```

Algunas demos y `prueba_concurrencia.py` modifican el stock, así que después de
usarlas conviene volver a correr `seed_redis.py`.

## Integrantes

- Angelina: disponibilidad y reserva temporal (requisitos 1 y 2)
- Ana Paula: confirmación, cancelación y concurrencia (requisitos 3 y 4)
- Sebastián: carrito y control de intentos (requisitos 5 y 6)
- Luis: rendimiento y resiliencia (requisito 7)
- Abigail: paper en formato IEEE
- Fabiola: repositorio, presentación y entrega
