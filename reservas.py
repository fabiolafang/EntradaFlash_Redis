"""
EntradaFlash CR - Núcleo de reservas sobre Redis (requisitos 1 a 4).

Requisito 1: consultar disponibilidad por acceso directo a una clave.
Requisito 2: reserva temporal con TTL y liberación automática del inventario.
Requisito 3: confirmar o cancelar una reserva sin producir inventario negativo
             ni inventario inflado.
Requisito 4: control de concurrencia mediante scripts Lua, que Redis ejecuta
             de forma atómica (ningún otro comando se intercala).

Diseño de claves:
  event:{evento}:zone:{zona}:stock     STRING  entradas disponibles de la zona
  reservation:{usuario}:{evento}:{zona} HASH   datos y estado de la reserva
                                               (con TTL mientras está PENDIENTE)
  reservations:pending                 ZSET    reservas pendientes;
                                               score = vencimiento en ms
  reservations:pending:qty             HASH    cantidad de cada reserva pendiente
  user:{usuario}                       STRING  perfil (lo crea el generador)

Por qué existe el registro de pendientes:
  Cuando Redis borra una clave por TTL no ejecuta ninguna lógica, así que el
  stock no regresa solo. El ZSET guarda cada reserva pendiente con su hora de
  vencimiento, y un script Lua ("barrido") devuelve el stock de las vencidas.
  Confirmar o cancelar saca la reserva del registro dentro del mismo script,
  por lo que una reserva solo puede liberar su inventario una vez.

Estados de una reserva:
  PENDIENTE --confirmar--> CONFIRMADA (venta definitiva, sin TTL)
  PENDIENTE --cancelar---> CANCELADA  (stock devuelto; rastro por 10 min)
  PENDIENTE --vence------> la clave desaparece y el barrido devuelve el stock
"""

import os
import threading

import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6380"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Pool amplio: en una preventa cientos de clientes consultan al mismo tiempo.
_pool = redis.BlockingConnectionPool(host=REDIS_HOST, port=REDIS_PORT,
                                     db=REDIS_DB, decode_responses=True,
                                     max_connections=500, timeout=10)
r = redis.Redis(connection_pool=_pool)

PENDIENTES_KEY = "reservations:pending"
CANTIDADES_KEY = "reservations:pending:qty"

TTL_POR_DEFECTO = 5               # segundos que dura una reserva pendiente
MAX_ENTRADAS_POR_RESERVA = 6      # mayor cantidad presente en los intentos generados
RETENCION_CANCELADA_MS = 600_000  # rastro de una cancelación (10 minutos)


def clave_stock(event_id, zone_id):
    return f"event:{event_id}:zone:{zone_id}:stock"


def clave_reserva(user_id, event_id, zone_id):
    return f"reservation:{user_id}:{event_id}:{zone_id}"


def clave_usuario(user_id):
    return f"user:{user_id}"


# ---------------------------------------------------------------------------
# Scripts Lua. Todos comparten estas dos funciones auxiliares.
#   ahora_ms(): hora del servidor Redis en milisegundos. Se usa la hora de
#               Redis y no la de cada cliente para que todos los clientes
#               juzguen el vencimiento con el mismo reloj.
#   liberar():  devuelve al stock la cantidad de una reserva pendiente y la
#               saca del registro. Si ya no está registrada, no hace nada,
#               lo que impide devolver el mismo inventario dos veces.
# ---------------------------------------------------------------------------

_LUA_COMUN = """
local PEND = KEYS[1]
local QTY = KEYS[2]

local function ahora_ms()
    local t = redis.call('TIME')
    return tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end

local function liberar(reserva_id, stock_key)
    if redis.call('ZREM', PEND, reserva_id) == 0 then
        return 0
    end
    local cantidad = tonumber(redis.call('HGET', QTY, reserva_id)) or 0
    redis.call('HDEL', QTY, reserva_id)
    if cantidad > 0 then
        redis.call('INCRBY', stock_key, cantidad)
    end
    return cantidad
end
"""

# KEYS: PEND, QTY, stock, reserva, usuario
# ARGV: user_id, event_id, zone_id, cantidad, ttl_ms, validar_usuario
_LUA_CREAR = _LUA_COMUN + """
local stock_key = KEYS[3]
local reserva_id = KEYS[4]
local usuario_key = KEYS[5]
local cantidad = tonumber(ARGV[4])
local ttl_ms = tonumber(ARGV[5])
local ahora = ahora_ms()

if redis.call('EXISTS', stock_key) == 0 then
    return {-1}
end
if ARGV[6] == '1' and redis.call('EXISTS', usuario_key) == 0 then
    return {-2}
end

-- ¿El usuario ya tiene una reserva en esta zona?
local vence = redis.call('ZSCORE', PEND, reserva_id)
if vence then
    if tonumber(vence) > ahora then
        return {-3, tonumber(vence) - ahora}
    end
    -- Venció pero el barrido aún no pasó: se libera aquí mismo.
    liberar(reserva_id, stock_key)
    redis.call('DEL', reserva_id)
end
if redis.call('HGET', reserva_id, 'estado') == 'CONFIRMADA' then
    return {-4}
end

local stock = tonumber(redis.call('GET', stock_key))
if stock < cantidad then
    return {-5, stock}
end

local vencimiento = ahora + ttl_ms
redis.call('DECRBY', stock_key, cantidad)
redis.call('DEL', reserva_id)
redis.call('HSET', reserva_id,
    'user_id', ARGV[1], 'event_id', ARGV[2], 'zone_id', ARGV[3],
    'cantidad', cantidad, 'estado', 'PENDIENTE',
    'creada_en_ms', ahora, 'expira_en_ms', vencimiento)
redis.call('PEXPIREAT', reserva_id, vencimiento)
redis.call('ZADD', PEND, vencimiento, reserva_id)
redis.call('HSET', QTY, reserva_id, cantidad)
return {1, stock - cantidad, ttl_ms}
"""

# KEYS: PEND, QTY, stock, reserva
_LUA_CONFIRMAR = _LUA_COMUN + """
local stock_key = KEYS[3]
local reserva_id = KEYS[4]
local ahora = ahora_ms()

local vence = redis.call('ZSCORE', PEND, reserva_id)
if not vence then
    local estado = redis.call('HGET', reserva_id, 'estado')
    if estado == 'CONFIRMADA' then return -2 end
    if estado == 'CANCELADA' then return -4 end
    return -1
end
if tonumber(vence) <= ahora then
    -- Venció: se libera el inventario y la venta no procede.
    liberar(reserva_id, stock_key)
    redis.call('DEL', reserva_id)
    return -3
end

-- El stock ya se descontó al reservar; confirmar solo vuelve la venta definitiva.
redis.call('ZREM', PEND, reserva_id)
redis.call('HDEL', QTY, reserva_id)
redis.call('HSET', reserva_id, 'estado', 'CONFIRMADA', 'confirmada_en_ms', ahora)
redis.call('PERSIST', reserva_id)
return 1
"""

# KEYS: PEND, QTY, stock, reserva
# ARGV: retencion_ms
_LUA_CANCELAR = _LUA_COMUN + """
local stock_key = KEYS[3]
local reserva_id = KEYS[4]
local ahora = ahora_ms()

local vence = redis.call('ZSCORE', PEND, reserva_id)
if not vence then
    local estado = redis.call('HGET', reserva_id, 'estado')
    if estado == 'CONFIRMADA' then return {-2} end
    if estado == 'CANCELADA' then return {-4} end
    return {-1}
end
if tonumber(vence) <= ahora then
    local devueltas = liberar(reserva_id, stock_key)
    redis.call('DEL', reserva_id)
    return {-3, devueltas}
end

-- La cantidad se lee del registro, nunca del cliente.
local devueltas = liberar(reserva_id, stock_key)
redis.call('HSET', reserva_id, 'estado', 'CANCELADA', 'cancelada_en_ms', ahora)
redis.call('PEXPIRE', reserva_id, tonumber(ARGV[1]))
return {1, devueltas}
"""

# KEYS: PEND, QTY
# ARGV: tamaño máximo del lote
_LUA_BARRIDO = _LUA_COMUN + """
local ahora = ahora_ms()
local vencidas = redis.call('ZRANGEBYSCORE', PEND, '-inf', ahora,
                            'LIMIT', 0, tonumber(ARGV[1]))
local resultado = {}
for _, reserva_id in ipairs(vencidas) do
    local evento, zona = string.match(reserva_id,
        '^reservation:[^:]+:([^:]+):([^:]+)$')
    if evento then
        local stock_key = 'event:' .. evento .. ':zone:' .. zona .. ':stock'
        local devueltas = liberar(reserva_id, stock_key)
        if redis.call('HGET', reserva_id, 'estado') == 'PENDIENTE' then
            redis.call('DEL', reserva_id)
        end
        table.insert(resultado, reserva_id)
        table.insert(resultado, devueltas)
    else
        redis.call('ZREM', PEND, reserva_id)
        redis.call('HDEL', QTY, reserva_id)
    end
end
return resultado
"""

_crear = r.register_script(_LUA_CREAR)
_confirmar = r.register_script(_LUA_CONFIRMAR)
_cancelar = r.register_script(_LUA_CANCELAR)
_barrido = r.register_script(_LUA_BARRIDO)


# ---------------------------------------------------------------------------
# Requisito 1
# ---------------------------------------------------------------------------

def consultar_disponibilidad(event_id, zone_id):
    """Devuelve las entradas disponibles de una zona con un solo GET (O(1))."""
    stock = r.get(clave_stock(event_id, zone_id))
    if stock is None:
        return {"error": "El evento o zona especificada no existe."}
    return {
        "event_id": event_id,
        "zone_id": zone_id,
        "disponibilidad_actual": int(stock),
    }


# ---------------------------------------------------------------------------
# Requisito 2
# ---------------------------------------------------------------------------

_MOTIVOS_CREAR = {
    -1: "El evento o zona especificada no existe.",
    -2: "El usuario no existe.",
    -3: "El usuario ya tiene una reserva pendiente en esta zona.",
    -4: "El usuario ya tiene una compra confirmada en esta zona.",
    -5: "Stock insuficiente.",
}


def crear_reserva_temporal(user_id, event_id, zone_id, cantidad,
                           ttl_segundos=TTL_POR_DEFECTO, validar_usuario=True):
    """Descuenta inventario y crea una reserva PENDIENTE con vencimiento.

    Verificar el stock y descontarlo ocurre dentro de un mismo script Lua,
    así que dos clientes nunca pueden tomar la misma entrada.
    """
    if isinstance(cantidad, bool) or not isinstance(cantidad, int) \
            or not 1 <= cantidad <= MAX_ENTRADAS_POR_RESERVA:
        return {"status": "RECHAZADO",
                "motivo": f"La cantidad debe ser un entero entre 1 y "
                          f"{MAX_ENTRADAS_POR_RESERVA}."}
    if not isinstance(ttl_segundos, (int, float)) or ttl_segundos <= 0:
        return {"status": "RECHAZADO", "motivo": "El TTL debe ser positivo."}

    reserva_id = clave_reserva(user_id, event_id, zone_id)
    res = _crear(
        keys=[PENDIENTES_KEY, CANTIDADES_KEY, clave_stock(event_id, zone_id),
              reserva_id, clave_usuario(user_id)],
        args=[user_id, event_id, zone_id, cantidad,
              int(ttl_segundos * 1000), "1" if validar_usuario else "0"])

    if res[0] == 1:
        return {"status": "EXITO", "reserva_id": reserva_id,
                "entradas_reservadas": cantidad,
                "stock_restante": res[1],
                "expira_en_segundos": res[2] / 1000}
    respuesta = {"status": "RECHAZADO", "reserva_id": reserva_id,
                 "motivo": _MOTIVOS_CREAR.get(res[0], "Error desconocido.")}
    if res[0] == -3:
        respuesta["vence_en_segundos"] = round(res[1] / 1000, 1)
    if res[0] == -5:
        respuesta["disponibles"] = res[1]
    return respuesta


def liberar_reservas_vencidas(lote=500):
    """Devuelve al inventario el stock de todas las reservas vencidas.

    Es seguro llamarla desde varios procesos a la vez: cada reserva se
    libera una sola vez porque el script es atómico.
    """
    liberadas = []
    while True:
        res = _barrido(keys=[PENDIENTES_KEY, CANTIDADES_KEY], args=[lote])
        pares = [(res[i], int(res[i + 1])) for i in range(0, len(res), 2)]
        liberadas.extend(pares)
        if len(pares) < lote:
            return liberadas


class LiberadorAutomatico:
    """Hilo en segundo plano que ejecuta el barrido cada `intervalo` segundos."""

    def __init__(self, intervalo=0.5, al_liberar=None):
        self.intervalo = intervalo
        self.al_liberar = al_liberar
        self.total_reservas = 0
        self.total_entradas = 0
        self._detener = threading.Event()
        self._hilo = threading.Thread(target=self._ciclo, daemon=True,
                                      name="liberador-reservas")

    def _ciclo(self):
        while not self._detener.is_set():
            try:
                liberadas = liberar_reservas_vencidas()
                for reserva_id, entradas in liberadas:
                    self.total_reservas += 1
                    self.total_entradas += entradas
                    if self.al_liberar:
                        self.al_liberar(reserva_id, entradas)
            except redis.RedisError as error:
                # Si Redis no responde, las reservas siguen registradas y se
                # liberan en el siguiente ciclo exitoso: no se pierde nada.
                print(f"[liberador] Redis no disponible: {error}")
            self._detener.wait(self.intervalo)

    def iniciar(self):
        self._hilo.start()
        return self

    def detener(self):
        self._detener.set()
        self._hilo.join()


def iniciar_liberador(intervalo=0.5, al_liberar=None):
    """Inicia el liberador automático y lo devuelve (llamar .detener() al final)."""
    return LiberadorAutomatico(intervalo, al_liberar).iniciar()


# ---------------------------------------------------------------------------
# Requisito 3 (usando la operación atómica del requisito 4)
# ---------------------------------------------------------------------------

_MOTIVOS_CONFIRMAR = {
    -1: "La reserva no existe.",
    -2: "La reserva ya estaba confirmada.",
    -3: "La reserva venció antes de confirmarse; las entradas volvieron al inventario.",
    -4: "La reserva fue cancelada.",
}

_MOTIVOS_CANCELAR = {
    -1: "La reserva no existe.",
    -2: "No se puede cancelar: la reserva ya está confirmada.",
    -3: "La reserva ya había vencido; las entradas volvieron al inventario por vencimiento.",
    -4: "La reserva ya estaba cancelada.",
}


def confirmar_reserva(user_id, event_id, zone_id):
    """Convierte una reserva PENDIENTE y vigente en venta definitiva."""
    reserva_id = clave_reserva(user_id, event_id, zone_id)
    res = _confirmar(keys=[PENDIENTES_KEY, CANTIDADES_KEY,
                           clave_stock(event_id, zone_id), reserva_id])
    if res == 1:
        return {"status": "EXITO", "reserva_id": reserva_id,
                "estado": "CONFIRMADA"}
    return {"status": "RECHAZADO", "reserva_id": reserva_id,
            "motivo": _MOTIVOS_CONFIRMAR.get(res, "Error desconocido.")}


def cancelar_reserva(user_id, event_id, zone_id):
    """Cancela una reserva PENDIENTE y devuelve su cantidad al inventario.

    La cantidad devuelta se toma de la reserva registrada, no de un
    parámetro, así que el inventario no se puede inflar desde afuera.
    """
    reserva_id = clave_reserva(user_id, event_id, zone_id)
    res = _cancelar(keys=[PENDIENTES_KEY, CANTIDADES_KEY,
                          clave_stock(event_id, zone_id), reserva_id],
                    args=[RETENCION_CANCELADA_MS])
    if res[0] == 1:
        return {"status": "EXITO", "reserva_id": reserva_id,
                "estado": "CANCELADA", "entradas_devueltas": res[1]}
    return {"status": "RECHAZADO", "reserva_id": reserva_id,
            "motivo": _MOTIVOS_CANCELAR.get(res[0], "Error desconocido.")}


def ver_reserva(user_id, event_id, zone_id):
    """Estado actual de una reserva y su TTL restante (útil para la demo)."""
    reserva_id = clave_reserva(user_id, event_id, zone_id)
    datos = r.hgetall(reserva_id)
    if not datos:
        return None
    ttl_ms = r.pttl(reserva_id)
    datos["ttl_restante_s"] = None if ttl_ms < 0 else round(ttl_ms / 1000, 1)
    return datos
