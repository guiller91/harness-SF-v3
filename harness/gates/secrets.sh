#!/usr/bin/env bash
# Gate: ningún secreto (contraseñas, tokens, claves) en los ficheros que cambia la feature.
# Usa Named/External Credentials. Una excepción la aprueba solo el humano en secrets-allowlist.txt.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

"$HX_PY" "$HX_LIB/secrets_scan.py" "$HX_CHANGED_FILES" "$HX_ROOT/secrets-allowlist.txt"
rc=$?
if [ "$rc" -eq 0 ]; then
  summary "sin secretos en los ficheros cambiados"
else
  echo "Mueve el secreto a una Named/External Credential. Si es un falso positivo, el HUMANO añade"
  echo "'<ruta> <huella>' a secrets-allowlist.txt."
  summary "secretos en el código (ver log)"; rc=1
fi
exit "$rc"
