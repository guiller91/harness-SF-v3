#!/usr/bin/env bash
# hx - punto de entrada del harness. Uso: ./hx <comando>   (./hx --help)
set -euo pipefail
HX_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HX_ROOT

# Busca un Python que realmente funcione (descarta el stub de Microsoft Store).
# 1. Candidatos del PATH (order de preferencia: python3, python).
# 2. Candidatos de respaldo: rutas típicas de Windows con Python real.
# 3. Verifica ejecutabilidad (no solo existencia) para cada candidato.
find_working_python() {
    local candidates=()
    local py

    # Candidatos desde command -v
    py=$(command -v python3 2>/dev/null || true)
    [ -n "$py" ] && candidates+=("$py")
    py=$(command -v python 2>/dev/null || true)
    [ -n "$py" ] && candidates+=("$py")

    # Candidatos de respaldo: Python real en rutas típicas de Windows
    local user_name
    user_name=$(whoami) || user_name=""

    # Busca en AppData\Local\Programs\Python\Python3*
    if [ -d "/c/Users/$user_name/AppData/Local/Programs/Python" ]; then
        for pydir in /c/Users/"$user_name"/AppData/Local/Programs/Python/Python3*/python.exe; do
            [ -f "$pydir" ] && candidates+=("$pydir")
        done
    fi

    # Busca en Program Files\Python3*
    for pydir in /c/Program\ Files/Python3*/python.exe /c/Program\ Files\ \(x86\)/Python3*/python.exe; do
        [ -f "$pydir" ] && candidates+=("$pydir")
    done

    # Busca en Program Files\Python3*
    for pydir in /c/Program\ Files/Python3*/python.exe /c/Program\ Files\ \(x86\)/Python3*/python.exe; do
        [ -f "$pydir" ] && candidates+=("$pydir")
    done

    # Prueba cada candidato: verifica que ejecute sin error
    for c in "${candidates[@]}"; do
        if "$c" -c "import sys" 2>/dev/null; then
            echo "$c"
            return 0
        fi
    done

    # Ninguno funcionó
    return 1
}

PY=$(find_working_python || true)
[ -n "$PY" ] || { echo "hx: hace falta Python 3.8+ en el PATH (o instalado en C:\Program Files\Python)" >&2; exit 127; }
exec "$PY" "$HX_ROOT/harness/cli.py" "$@"
