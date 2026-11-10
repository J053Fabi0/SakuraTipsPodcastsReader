"""Generacion del sitio estatico dentro de ``dist/``."""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import WEB_TEMPLATE_DIR


def ensure_site(dist_dir: str | Path) -> None:
    """Crea el arbol de ``dist`` y refresca los assets del frontend.

    No toca ``database.json`` ni ``audio/``. Los archivos del frontend se
    copian desde ``sakuratips_reader/web`` para que una actualizacion del
    programa se refleje al arrancar o al agregar un podcast.
    """

    dist = Path(dist_dir)
    (dist / "assets" / "css").mkdir(parents=True, exist_ok=True)
    (dist / "assets" / "js").mkdir(parents=True, exist_ok=True)
    (dist / "audio").mkdir(parents=True, exist_ok=True)

    if not WEB_TEMPLATE_DIR.exists():
        return

    for source in WEB_TEMPLATE_DIR.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(WEB_TEMPLATE_DIR)
        target = dist / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
