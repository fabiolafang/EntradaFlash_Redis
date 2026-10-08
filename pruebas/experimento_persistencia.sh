#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

CONTENEDOR="${CONTENEDOR:-entradaflash-redis}"
if [ "$(basename "$PWD")" = "pruebas" ]; then REPO_DEF="$(cd .. && pwd)"
else REPO_DEF="$HOME/Documents/GitHub/EntradaFlash_Redis"; fi
REPO="${REPO:-$REPO_DEF}"
export PROYECTO_DIR="${PROYECTO_DIR:-$REPO/src}"
RESULTADOS="resultados"; [ "$(basename "$PWD")" = "pruebas" ] && RESULTADOS="../resultados"
PY="${PYTHON:-python3}"
EXTRA=()
[ -n "${RAPIDO:-}" ] && EXTRA+=(--rapido)
[ -n "${MODULO:-}" ] && EXTRA+=(--modulo "$MODULO")

if [ -z "${MODO:-}" ]; then
  if command -v redis-cli >/dev/null; then MODO=local; else MODO=docker; fi
fi
cli() {
  if [ "$MODO" = docker ]; then docker exec "$CONTENEDOR" redis-cli "$@"
  else redis-cli -p 6380 "$@"; fi
}

esperar_aof() {   # activar AOF dispara una reescritura en segundo plano
  sleep 1
  until cli INFO persistence | grep -q "aof_rewrite_in_progress:0"; do sleep 0.5; done
}

INICIO=$(date +%Y%m%d_%H%M)
for config in sin-persistencia aof-everysec aof-always; do
  echo
  echo "=== $config ==="
  cli CONFIG SET save "" >/dev/null
  case "$config" in
    sin-persistencia) cli CONFIG SET appendonly no >/dev/null ;;
    aof-everysec)     cli CONFIG SET appendfsync everysec >/dev/null
                      cli CONFIG SET appendonly yes >/dev/null; esperar_aof ;;
    aof-always)       cli CONFIG SET appendfsync always >/dev/null
                      cli CONFIG SET appendonly yes >/dev/null; esperar_aof ;;
  esac
  "$PY" benchmark_req7.py --etiqueta "$config" ${EXTRA[@]+${EXTRA[@]+"${EXTRA[@]}"}}
done

# Volver a la configuración recomendada
cli CONFIG SET appendfsync everysec >/dev/null
cli CONFIG SET appendonly yes >/dev/null

echo
echo "Tabla comparativa (p50 / p99 en ms):"
CARPETAS=()
for d in "$RESULTADOS"/*_{sin-persistencia,aof-everysec,aof-always}; do
  [ -d "$d" ] && [[ "$(basename "$d")" > "$INICIO" || "$(basename "$d")" == "$INICIO"* ]] && CARPETAS+=("$d")
done
"$PY" benchmark_req7.py --comparar "${CARPETAS[@]}" | tee "$RESULTADOS/comparacion_persistencia.md"
