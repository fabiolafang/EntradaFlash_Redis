"""
EntradaFlash CR - Carrito (sesión temporal) por usuario sobre Redis (requisito 5).

Un usuario arma su compra antes de reservar: elige zonas y cantidades y puede
cambiar de opinión. Si cierra la aplicación o esta se cae, al volver encuentra
su carrito intacto. Si no vuelve, el carrito desaparece solo.

Diseño de claves (mismo estilo que reservas.py):
  cart:{usuario}   HASH   una línea del carrito por campo:
                          "{evento}:{zona}" -> cantidad de entradas
                          Tiene TTL deslizante: cada acción lo renueva.

Por qué un HASH y no un JSON dentro de un STRING:
  agregar o quitar una línea es una sola operación sobre un campo. Con un JSON
  habría que leer el carrito completo, modificarlo y reescribirlo, y si el mismo
  usuario tiene dos pestañas abiertas una de las dos pisaría los cambios de la
  otra.

Recuperación:
  El carrito vive en Redis y no en la memoria de la aplicación, así que
  cualquier proceso (otro servidor, otra pestaña, la aplicación reiniciada) lo
  lee con ver_carrito(usuario). Con renovar=True la lectura también extiende su
  vida, que es lo que ocurre cuando el usuario vuelve a iniciar sesión.

El carrito NO descuenta inventario: solo guarda la intención de compra. El
inventario se descuenta en finalizar_carrito(), que convierte cada línea en una
reserva temporal con crear_reserva_temporal() del núcleo (requisito 2). Así el
stock solo se bloquea cuando el usuario decide pagar, y no por carritos
abandonados.

Atomicidad:
  Agregar, quitar y leer-con-renovación son scripts Lua. Redis los ejecuta sin
  intercalar otros comandos, así que dos pestañas del mismo usuario nunca
  pueden dejar el carrito por encima del tope de entradas por zona.
"""

import reservas as rv

CARRITO_TTL_POR_DEFECTO = 900   # segundos de inactividad antes de vencer (15 min)


def clave_carrito(user_id):
    return f"cart:{user_id}"


def _campo(event_id, zone_id):
    return f"{event_id}:{zone_id}"


# ---------------------------------------------------------------------------
# Scripts Lua
# ---------------------------------------------------------------------------

# KEYS: carrito
# ARGV: campo, cantidad a sumar, tope por zona, ttl_ms
_LUA_AGREGAR = """
local actual = tonumber(redis.call('HGET', KEYS[1], ARGV[1])) or 0
local nuevo = actual + tonumber(ARGV[2])
if nuevo > tonumber(ARGV[3]) then
    return {-1, actual}
end
redis.call('HSET', KEYS[1], ARGV[1], nuevo)
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[4]))
return {1, nuevo}
"""

# KEYS: carrito
# ARGV: campo, cantidad a quitar (0 = toda la línea), ttl_ms
_LUA_QUITAR = """
local actual = tonumber(redis.call('HGET', KEYS[1], ARGV[1]))
if not actual then
    return {-1, 0}
end
local quitar = tonumber(ARGV[2])
local nuevo = actual - quitar
if quitar <= 0 or nuevo <= 0 then
    redis.call('HDEL', KEYS[1], ARGV[1])
    return {1, 0}
end
redis.call('HSET', KEYS[1], ARGV[1], nuevo)
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]))
return {1, nuevo}
"""

# KEYS: carrito
# ARGV: ttl_ms para renovar (0 = solo leer, sin tocar el TTL)
# Devuelve {} si no existe; si existe, {ttl_restante_ms, campo, valor, ...}.
_LUA_LEER = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return {}
end
if tonumber(ARGV[1]) > 0 then
    redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local datos = redis.call('HGETALL', KEYS[1])
table.insert(datos, 1, redis.call('PTTL', KEYS[1]))
return datos
"""

_agregar = rv.r.register_script(_LUA_AGREGAR)
_quitar = rv.r.register_script(_LUA_QUITAR)
_leer = rv.r.register_script(_LUA_LEER)


# ---------------------------------------------------------------------------
# Validaciones
# ---------------------------------------------------------------------------

def _cantidad_valida(cantidad):
    return (isinstance(cantidad, int) and not isinstance(cantidad, bool)
            and 1 <= cantidad <= rv.MAX_ENTRADAS_POR_RESERVA)


def _ttl_valido(ttl_segundos):
    return (isinstance(ttl_segundos, (int, float))
            and not isinstance(ttl_segundos, bool) and ttl_segundos > 0)


def _rechazo(motivo, **extra):
    return {"status": "RECHAZADO", "motivo": motivo, **extra}


# ---------------------------------------------------------------------------
# Operaciones del carrito
# ---------------------------------------------------------------------------

def agregar_item(user_id, event_id, zone_id, cantidad,
                 ttl_segundos=CARRITO_TTL_POR_DEFECTO):
    """Suma `cantidad` entradas de una zona al carrito y renueva su vida.

    Si la zona ya estaba en el carrito, las cantidades se acumulan. El total
    por zona no puede superar MAX_ENTRADAS_POR_RESERVA, porque es lo máximo
    que luego aceptará la reserva.
    """
    if not _cantidad_valida(cantidad):
        return _rechazo(f"La cantidad debe ser un entero entre 1 y "
                        f"{rv.MAX_ENTRADAS_POR_RESERVA}.")
    if not _ttl_valido(ttl_segundos):
        return _rechazo("El TTL debe ser positivo.")

    with rv.r.pipeline() as pipe:
        pipe.exists(rv.clave_stock(event_id, zone_id))
        pipe.exists(rv.clave_usuario(user_id))
        zona_existe, usuario_existe = pipe.execute()
    if not zona_existe:
        return _rechazo("El evento o zona especificada no existe.")
    if not usuario_existe:
        return _rechazo("El usuario no existe.")

    codigo, total = _agregar(
        keys=[clave_carrito(user_id)],
        args=[_campo(event_id, zone_id), cantidad,
              rv.MAX_ENTRADAS_POR_RESERVA, int(ttl_segundos * 1000)])
    if codigo == 1:
        return {"status": "EXITO", "user_id": user_id, "event_id": event_id,
                "zone_id": zone_id, "cantidad_en_carrito": total,
                "expira_en_segundos": ttl_segundos}
    return _rechazo(f"Máximo {rv.MAX_ENTRADAS_POR_RESERVA} entradas por zona "
                    f"en el carrito.", cantidad_en_carrito=total)


def quitar_item(user_id, event_id, zone_id, cantidad=None,
                ttl_segundos=CARRITO_TTL_POR_DEFECTO):
    """Quita `cantidad` entradas de una zona (o toda la línea si es None)."""
    if cantidad is not None and (isinstance(cantidad, bool)
                                 or not isinstance(cantidad, int) or cantidad < 1):
        return _rechazo("La cantidad a quitar debe ser un entero positivo.")
    if not _ttl_valido(ttl_segundos):
        return _rechazo("El TTL debe ser positivo.")

    codigo, restante = _quitar(
        keys=[clave_carrito(user_id)],
        args=[_campo(event_id, zone_id), cantidad or 0, int(ttl_segundos * 1000)])
    if codigo == 1:
        return {"status": "EXITO", "user_id": user_id, "event_id": event_id,
                "zone_id": zone_id, "cantidad_en_carrito": restante}
    return _rechazo("El carrito no tiene esa zona.")


def ver_carrito(user_id, renovar=False, ttl_segundos=CARRITO_TTL_POR_DEFECTO):
    """Devuelve el carrito del usuario, o None si no existe o ya venció.

    Con renovar=True la lectura reinicia el TTL (el usuario volvió); con
    renovar=False es una lectura pura que no altera su vida.
    """
    ttl_ms = int(ttl_segundos * 1000) if renovar else 0
    res = _leer(keys=[clave_carrito(user_id)], args=[ttl_ms])
    if not res:
        return None
    ttl_restante_ms = res[0]
    items = []
    for i in range(1, len(res), 2):
        evento, zona = res[i].split(":", 1)
        items.append({"event_id": evento, "zone_id": zona,
                      "cantidad": int(res[i + 1])})
    items.sort(key=lambda it: (it["event_id"], it["zone_id"]))
    return {"user_id": user_id,
            "items": items,
            "total_entradas": sum(it["cantidad"] for it in items),
            "ttl_restante_s": None if ttl_restante_ms < 0
            else round(ttl_restante_ms / 1000, 1)}


def vaciar_carrito(user_id):
    """Elimina el carrito completo."""
    borrado = rv.r.delete(clave_carrito(user_id))
    return {"status": "EXITO", "vaciado": bool(borrado)}


def finalizar_carrito(user_id, ttl_segundos=rv.TTL_POR_DEFECTO):
    """Convierte cada línea del carrito en una reserva temporal.

    Cada línea pasa por crear_reserva_temporal() del núcleo, que es quien
    decide si hay stock. Las líneas reservadas salen del carrito; las que el
    núcleo rechaza (por ejemplo, stock insuficiente) se quedan para que el
    usuario las corrija.

    Estado devuelto: EXITO (todo reservado), PARCIAL (algunas líneas
    rechazadas) o RECHAZADO (ninguna se pudo reservar).
    """
    carrito = ver_carrito(user_id)
    if carrito is None:
        return _rechazo("El carrito está vacío o venció.")

    reservas, pendientes = [], []
    for it in carrito["items"]:
        res = rv.crear_reserva_temporal(user_id, it["event_id"], it["zone_id"],
                                        it["cantidad"], ttl_segundos=ttl_segundos)
        if res["status"] == "EXITO":
            # Se quita exactamente lo reservado: si el usuario agregó más en
            # otra pestaña mientras tanto, eso se conserva en el carrito.
            quitar_item(user_id, it["event_id"], it["zone_id"],
                        cantidad=it["cantidad"])
            reservas.append(res)
        else:
            pendientes.append({**it, "motivo": res["motivo"]})

    if not pendientes:
        estado = "EXITO"
    else:
        estado = "PARCIAL" if reservas else "RECHAZADO"
    return {"status": estado, "reservas": reservas, "pendientes": pendientes}
