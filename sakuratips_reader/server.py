"""Servidor HTTP local para el sitio y la API de progreso."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server

from .config import SERVER_HOST
from .database import DatabaseError, DatabaseStore
from .site import ensure_site


def _json_error(message: str, status: int) -> tuple[Response, int]:
    response = jsonify({"error": message})
    response.status_code = status
    return response, status


def create_app(dist_dir: str | Path) -> Flask:
    dist = Path(dist_dir)
    ensure_site(dist)
    store = DatabaseStore(dist)
    try:
        store.ensure_initialized()
    except DatabaseError:
        # La base corrupta no se sobrescribe; la API informara el error.
        pass

    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False

    @app.after_request
    def set_cache_headers(response: Response) -> Response:
        path = request.path
        if (
            path == "/"
            or path.startswith("/api/")
            or path.endswith(".html")
            or path.endswith("database.json")
        ):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    def index() -> Response:
        return send_from_directory(dist, "index.html")

    @app.get("/api/database")
    def api_database():
        try:
            data = store.load()
        except DatabaseError as exc:
            return _json_error(str(exc), 500)
        return jsonify(data)

    @app.route("/api/progress/<youtube_id>", methods=["PUT", "POST"])
    def api_progress(youtube_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or "progress" not in payload:
            return _json_error(
                "El cuerpo debe ser un objeto JSON con el campo progress.", 400
            )

        try:
            entry = store.update_progress(youtube_id, payload["progress"])
        except KeyError:
            return _json_error(
                f"No existe el podcast con YouTube ID {youtube_id!r}.", 404
            )
        except ValueError as exc:
            return _json_error(str(exc), 400)
        except DatabaseError as exc:
            return _json_error(str(exc), 500)

        return jsonify(
            {"youtubeId": entry["youtubeId"], "progress": entry["progress"]}
        )

    @app.route("/api/focus/<youtube_id>", methods=["PUT", "POST"])
    def api_focus(youtube_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or "focusIndex" not in payload:
            return _json_error(
                "El cuerpo debe ser un objeto JSON con el campo focusIndex.",
                400,
            )

        try:
            entry = store.update_focus(youtube_id, payload["focusIndex"])
        except KeyError:
            return _json_error(
                f"No existe el podcast con YouTube ID {youtube_id!r}.", 404
            )
        except ValueError as exc:
            return _json_error(str(exc), 400)
        except DatabaseError as exc:
            return _json_error(str(exc), 500)

        return jsonify(
            {
                "youtubeId": entry["youtubeId"],
                "focusIndex": entry["focusIndex"],
            }
        )

    @app.get("/<path:filename>")
    def static_files(filename: str) -> Response:
        return send_from_directory(dist, filename)

    return app


def _browser_disabled() -> bool:
    return os.environ.get("SAKURATIPS_NO_BROWSER", "").lower() in (
        "1",
        "true",
        "yes",
    )


def open_local_browser(url: str) -> bool:
    """Abre la URL en el navegador local de Linux, macOS o Termux."""

    if _browser_disabled():
        return False

    commands: list[list[str]] = []
    if os.environ.get("TERMUX_VERSION") or shutil.which("termux-open-url"):
        commands.append(["termux-open-url", url])
    if sys.platform == "darwin":
        commands.append(["open", url])
    elif os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError:
            pass
    else:
        commands.append(["xdg-open", url])

    for command in commands:
        executable = shutil.which(command[0])
        if executable is None:
            continue
        try:
            subprocess.Popen(
                [executable, *command[1:]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue

    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def _open_browser_and_warn(url: str) -> None:
    if not open_local_browser(url):
        print(
            "No se pudo abrir el navegador automaticamente. "
            f"Abre manualmente {url}",
            file=sys.stderr,
        )


def serve(dist_dir: str | Path, port: int) -> None:
    app = create_app(dist_dir)
    http_server = make_server(SERVER_HOST, port, app, threaded=True)
    url = f"http://{SERVER_HOST}:{port}/"
    print(
        f"Servidor local en {url} "
        f"(sirviendo {Path(dist_dir).resolve()})",
        flush=True,
    )
    if not _browser_disabled():
        threading.Timer(
            0.4, _open_browser_and_warn, args=(url,)
        ).start()
    http_server.serve_forever()
