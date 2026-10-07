"""
EntradaFlash CR - Control de intentos (rate limiting) por usuario e IP sobre
Redis (requisito 6).

Cuando abre la preventa, un bot puede lanzar miles de intentos por segundo para
acaparar entradas. Este módulo limita cuántos intentos puede hacer un mismo
usuario, y una misma IP, dentro de una ventana de tiempo.

Diseño de claves (mismo estilo que reservas.py):
  rate_limit:{usuario}   STRING  contador de intentos del usuario en la ventana
  rate_limit:ip:{ip}     STRING  contador de intentos de la IP en la ventana
                                 (ambos con TTL = duración de la ventana)

Algoritmo: ventana fija con INCR + TTL.
  El primer intento crea el contador y le pone el TTL de la ventana. Los
  siguientes lo incrementan. Cuando el contador llega al límite se rechaza hasta
  que Redis borra la clave al vencer el TTL, y el contador vuelve a empezar.
  Es O(1) y no necesita ningún proceso en segundo plano: el vencimiento lo hace
  Redis solo.

Atomicidad:
  Revisar el límite e incrementar ocurre dentro de un mismo script Lua. Sin eso,
  100 hilos podrían leer "quedan intentos" al mismo tiempo y colarse todos. Con
  el script, en una ventana pasan exactamente `limite` intentos.

Decisiones de diseño:
  - Un intento rechazado NO se cuenta. Así un bot que insiste no alarga su
    propio bloqueo: la ventana termina a la hora fijada desde el primer intento.
  - Si se controla usuario e IP a la vez y uno de los dos ya llegó al límite,
    ningún contador se incrementa. Un usuario bloqueado no consume el cupo de
    su IP.
  - Una IP puede agrupar a varios usuarios reales (una oficina, una universidad),
    por eso su límite por defecto es mayor que el del usuario.

Limitación conocida de la ventana fija:
  un cliente puede hacer `limite` intentos al final de una ventana y otros
  `limite` al inicio de la siguiente, o sea hasta el doble en un instante. Para
  este caso es aceptable; una ventana deslizante (ZSET) lo evitaría a cambio de
  más memoria y más trabajo por intento.
"""

import json

import reservas as rv

LIMITE_USUARIO_POR_DEFECTO = 10    # intentos por usuario en cada ventana
LIMITE_IP_POR_DEFECTO = 30         # intentos por IP en cada ventana
VENTANA_POR_DEFECTO = 60           # segundos


def clave_limite_usuario(user_id):
    return f"rate_limit:{user_id}"


def clave_limite_ip(ip):
    return f"rate_limit:ip:{ip}"


# KEYS: un contador por ámbito (usuario, ip), en ese orden
# ARGV: ventana_ms, y luego el límite de cada contador (mismo orden que KEYS)
# Devuelve {0, posicion_del_ambito_bloqueado, ttl_restante_ms}
#       o {1, intentos_restantes_ambito_1, intentos_restantes_ambito_2, ...}
_LUA_INTENTO = """
local ventana = tonumber(ARGV[1])

-- Primero se revisan todos los límites, sin modificar nada.
for i, clave in ipairs(KEYS) do
    local actual = tonumber(redis.call('GET', clave) or '0')
    if actual >= tonumber(ARGV[i + 1]) then
        local ttl = redis.call('PTTL', clave)
        if ttl < 0 then
            redis.call('PEXPIRE', clave, ventana)
            ttl = ventana
        end
        return {0, i, ttl}
    end
end

-- Todos tienen cupo: se cuenta el intento en cada ámbito.
local resultado = {1}
for i, clave in ipairs(KEYS) do
    local n = redis.call('INCR', clave)
    if n == 1 or redis.call('PTTL', clave) < 0 then
        redis.call('PEXPIRE', clave, ventana)
    end
    table.insert(resultado, tonumber(ARGV[i + 1]) - n)
end
return resultado
"""

_intento = rv.r.register_script(_LUA_INTENTO)


def _limite_valido(valor):
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= 1


def verificar_intento(user_id=None, ip=None,
                      limite_usuario=LIMITE_USUARIO_POR_DEFECTO,
                      limite_ip=LIMITE_IP_POR_DEFECTO,
                      ventana_segundos=VENTANA_POR_DEFECTO):
    """Registra un intento y dice si se permite o se rechaza por exceso.

    Se puede controlar solo el usuario, solo la IP, o ambos a la vez.

    Devuelve:
      EXITO      con "intentos_restantes" por ámbito ({"usuario": n, "ip": m}).
      RECHAZADO  con "ambito" (usuario o ip) y "reintentar_en_segundos".
    """
    ambitos, claves, limites = [], [], []
    if user_id is not None:
        ambitos.append("usuario")
        claves.append(clave_limite_usuario(user_id))
        limites.append(limite_usuario)
    if ip is not None:
        ambitos.append("ip")
        claves.append(clave_limite_ip(ip))
        limites.append(limite_ip)

    if not claves:
        return {"status": "RECHAZADO", "motivo": "Debe indicar usuario o IP."}
    if not all(_limite_valido(x) for x in limites):
        return {"status": "RECHAZADO",
                "motivo": "El límite debe ser un entero positivo."}
    if (not isinstance(ventana_segundos, (int, float))
            or isinstance(ventana_segundos, bool) or ventana_segundos <= 0):
        return {"status": "RECHAZADO", "motivo": "La ventana debe ser positiva."}

    res = _intento(keys=claves, args=[int(ventana_segundos * 1000), *limites])
    if res[0] == 1:
        return {"status": "EXITO",
                "intentos_restantes": dict(zip(ambitos, res[1:]))}

    ambito = ambitos[res[1] - 1]
    return {"status": "RECHAZADO",
            "motivo": f"Demasiados intentos para este {ambito}.",
            "ambito": ambito,
            "reintentar_en_segundos": round(res[2] / 1000, 1)}


def ip_de_usuario(user_id):
    """IP registrada en el perfil del usuario (la crea el generador de datos)."""
    crudo = rv.r.get(rv.clave_usuario(user_id))
    try:
        return json.loads(crudo).get("ip")
    except (TypeError, ValueError, AttributeError):
        return None


def reservar_con_limite(user_id, event_id, zone_id, cantidad, ip=None,
                        ttl_segundos=rv.TTL_POR_DEFECTO,
                        limite_usuario=LIMITE_USUARIO_POR_DEFECTO,
                        limite_ip=LIMITE_IP_POR_DEFECTO,
                        ventana_segundos=VENTANA_POR_DEFECTO):
    """Reserva con control de intentos por delante.

    Si el usuario o su IP excedieron el límite, se rechaza antes de tocar el
    inventario. Si no se indica la IP, se toma la del perfil del usuario.
    """
    ip = ip or ip_de_usuario(user_id)
    control = verificar_intento(user_id, ip, limite_usuario, limite_ip,
                                ventana_segundos)
    if control["status"] != "EXITO":
        return control
    res = rv.crear_reserva_temporal(user_id, event_id, zone_id, cantidad,
                                    ttl_segundos=ttl_segundos)
    res["intentos_restantes"] = control["intentos_restantes"]
    return res


def reiniciar_limite(user_id=None, ip=None):
    """Borra los contadores (útil para pruebas y para la demo)."""
    claves = []
    if user_id is not None:
        claves.append(clave_limite_usuario(user_id))
    if ip is not None:
        claves.append(clave_limite_ip(ip))
    if claves:
        rv.r.delete(*claves)
