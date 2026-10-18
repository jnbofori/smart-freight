"""Serve the Vite-built UI from STATIC_DIR (Fly / Docker Option A).

API and SPA share some paths (/optimize, /trucks, …). Browser navigations
send Accept: text/html; axios sends application/json. Mirror the Vite
dev proxy: HTML → index.html, otherwise let API routes handle the request.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_HTML_SKIP_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not static_dir.is_dir() or not index.is_file():
        return

    root = static_dir.resolve()
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.middleware("http")
    async def spa_html_navigation(request: Request, call_next):
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path
        if path.startswith(_HTML_SKIP_PREFIXES):
            return await call_next(request)

        # Vite public/ files at dist root (favicon, logos, …)
        if path not in ("/", "") and not path.startswith("/assets"):
            rel = path.lstrip("/")
            candidate = (static_dir / rel).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return await call_next(request)
            if candidate.is_file():
                return FileResponse(candidate)

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return FileResponse(index)

        return await call_next(request)
