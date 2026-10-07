#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PUERTO=6380
CONTENEDOR="${CONTENEDOR:-entradaflash-redis}"
IMAGEN="${IMAGEN:-redis:7.4}"
if [ "$(basename "$PWD")" = "pruebas" ]; then REPO_DEF="$(cd .. && pwd)"
else REPO_DEF="$HOME/Documents/GitHub/EntradaFlash_Redis"; fi
REPO="${REPO:-$REPO_DEF}"
export PROYECTO_DIR="${PROYECTO_DIR:-$REPO/src}"
ARG_MODULO=()
[ -n "${MODULO:-}" ] && ARG_MODULO=(--modulo "$MODULO")
PY="${PYTHON:-python3}"

if [ -z "${MODO:-}" ]; then
  if command -v redis-server >/dev/null; then MODO=local
  elif command -v docker >/dev/null; then MODO=docker
  else echo "Necesita redis-server (brew install redis) o Docker." >&2; exit 1; fi
fi
DATOS_LOCAL="$(mktemp -d "${TMPDIR:-/tmp}/entradaflash-caida.XXXX")"
PARAMS=()

cli() {
  if [ "$MODO" = docker ]; then docker exec "$CONTENEDOR" redis-cli "$@"
  else redis-cli -p "$PUERTO" "$@"; fi
}

esperar() { until cli ping 2>/dev/null | grep -q PONG; do sleep 0.5; done; }

iniciar_proceso() {
  if [ "$MODO" = docker ]; then docker start "$CONTENEDOR" >/dev/null
  else redis-server --port "$PUERTO" --dir "$DATOS_LOCAL" --daemonize yes "${PARAMS[@]}" >/dev/null; fi
  esperar
}

levantar() {   # $@ = parámetros de redis-server
  PARAMS=("$@")
  if [ "$MODO" = docker ]; then
    docker rm -f "$CONTENEDOR" >/dev/null 2>&1 || true
    docker run -d --name "$CONTENEDOR" -p "$PUERTO:6379" "$IMAGEN" redis-server "$@" >/dev/null
    esperar
  else
    redis-cli -p "$PUERTO" shutdown nosave >/dev/null 2>&1 || true
    sleep 0.5
    rm -rf "${DATOS_LOCAL:?}"/*
    iniciar_proceso
  fi
}

matar() {      # caída abrupta: SIGKILL, sin guardar nada
  if [ "$MODO" = docker ]; then docker kill "$CONTENEDOR" >/dev/null
  else
    pid="$(cli INFO server | grep '^process_id:' | cut -d: -f2 | tr -d '\r')"
    kill -9 "$pid"
  fi
  sleep 1
}

cargar_datos() {
  echo "  Cargando datos del proyecto (datos/seed_redis.py)..."
  (cd "$REPO/datos" && "$PY" seed_redis.py >/dev/null)
}

probar() {     # $1 = etiqueta, resto = parámetros de redis-server
  local etiqueta="$1"; shift
  echo
  echo "=================================================================="
  echo " Configuración: $etiqueta   (redis-server $*)   [modo $MODO]"
  echo "=================================================================="
  levantar "$@"
  cargar_datos
  if [ "$etiqueta" = "rdb" ]; then
    echo "  Tomando snapshot RDB (SAVE) con los datos recién cargados..."
    cli SAVE >/dev/null
  fi
  "$PY" prueba_caida.py preparar --etiqueta "$etiqueta" ${ARG_MODULO[@]+${ARG_MODULO[@]+${ARG_MODULO[@]+"${ARG_MODULO[@]}"}}} | grep -v "Ahora simule\|docker kill\|y luego\|prueba_caida.py verificar"
  sleep 2
  echo "  >>> Caída abrupta (kill -9) a los 2 s; reiniciando Redis..."
  matar
  iniciar_proceso
  "$PY" prueba_caida.py verificar --etiqueta "$etiqueta" ${ARG_MODULO[@]+${ARG_MODULO[@]+${ARG_MODULO[@]+"${ARG_MODULO[@]}"}}}
}

probar sin-persistencia --save "" --appendonly no
probar rdb              --save "300 100" --appendonly no
probar aof-everysec     --save "" --appendonly yes --appendfsync everysec

echo
echo "Dejando Redis con la configuración recomendada (AOF everysec + RDB)..."
levantar --appendonly yes --appendfsync everysec --save "300 100"
cargar_datos
echo "Listo. Resultados en resultados/caida_*.md"
[ "$MODO" = local ] && echo "(Los archivos de Redis de esta sesión quedaron en $DATOS_LOCAL)"
true
