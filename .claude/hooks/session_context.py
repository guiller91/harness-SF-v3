#!/usr/bin/env python3
"""SessionStart (startup | resume | clear | compact).

Reinyecta el estado del harness desde disco. Es lo que hace que una sesión nueva
—o una que acaba de compactar su contexto— retome exactamente donde se quedó.
"""
from __future__ import annotations

import io
import os
import contextlib
import sys

import _hx
from _hx import core


def _export_bin_on_path() -> None:
    """bin/sf (shim) al principio del PATH de la sesión: `sf` funciona igual en gates y agentes."""
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    shim = _hx.PROJECT / "bin" / "sf"
    if not env_file or not shim.exists():
        return
    try:
        posix = str(shim.parent).replace("\\", "/")
        with open(env_file, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f'export PATH="{posix}:$PATH"\n')
    except OSError:
        pass


def main() -> None:
    _hx.read_event()
    sys.path.insert(0, str(_hx.PROJECT / "harness"))
    import cli  # noqa: WPS433

    _export_bin_on_path()
    cfg = core.load_config(_hx.PROJECT)
    features = core.load_features(_hx.PROJECT)
    feat = core.active_feature(features)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(["status"])
    lines = ["<harness-state>", buf.getvalue().rstrip()]
    if feat:
        notes = _hx.PROJECT / "progress" / feat["id"] / "notes.md"
        if notes.exists():
            tail = notes.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]
            lines += ["", f"Últimas notas (progress/{feat['id']}/notes.md):"] + tail
    lines += [
        "",
        "Recordatorio operativo: el estado solo cambia con `./hx`; los implementers van EN SERIE y los",
        "revisores EN PARALELO; nada está hecho sin evidencia del árbol actual; las puertas humanas",
        "(`./hx approve`, `./hx close`) las confirma el humano, no tú.",
        "</harness-state>",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    _hx.safe_main(main)
