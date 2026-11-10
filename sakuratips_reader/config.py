"""Constantes y rutas de la aplicacion."""

from __future__ import annotations

import os
from pathlib import Path

SCHEMA_VERSION = 1

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
WEB_TEMPLATE_DIR = PACKAGE_DIR / "web"

SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8000


def get_dist_dir() -> Path:
    """Devuelve el directorio ``dist`` configurado.

    ``SAKURATIPS_DIST`` permite usar un directorio alternativo (util en tests).
    La ruta es absoluta y se resuelve respecto al directorio actual cuando la
    variable de entorno es relativa.
    """

    raw = os.environ.get("SAKURATIPS_DIST")
    if raw:
        return Path(raw).expanduser().resolve()
    return PROJECT_ROOT / "dist"


def get_server_port() -> int:
    """Puerto local del servidor, configurable por entorno."""

    raw = os.environ.get("SAKURATIPS_PORT", str(DEFAULT_SERVER_PORT))
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"SAKURATIPS_PORT debe ser un numero entero, se recibio: {raw!r}"
        ) from exc
    if not 1 <= port <= 65535:
        raise ValueError("SAKURATIPS_PORT debe estar entre 1 y 65535")
    return port
