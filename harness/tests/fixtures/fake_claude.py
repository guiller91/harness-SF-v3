#!/usr/bin/env python3
"""`claude` de mentira para los tests del centro de control: imita el stream-json de `claude -p`."""
import json
import sys

msg = sys.stdin.read()
argv = sys.argv[1:]
sid = argv[argv.index("--resume") + 1] if "--resume" in argv else None
new = sid or "11111111-2222-3333-4444-555555555555"


def emit(obj):
    print(json.dumps(obj), flush=True)


emit({"type": "system", "subtype": "init", "session_id": new})
emit({"type": "assistant", "session_id": new, "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": "./hx status"}},
    {"type": "text", "text": f"Recibido: {msg} | resume={sid} | prompt={'--append-system-prompt' in argv}"}]}})
emit({"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "denegado"}]}})
emit({"type": "result", "subtype": "success", "duration_ms": 1200, "session_id": new})
