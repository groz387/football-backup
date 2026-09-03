"""FastAPI operator console — HTTP skin over ``recap.studio_api``."""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from recap import studio_api

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Recap Studio", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": "studio"}


@app.get("/api/bootstrap")
def bootstrap() -> dict:
    return studio_api.bootstrap()


@app.get("/api/settings")
def get_settings() -> dict:
    return studio_api.load_settings()


@app.post("/api/settings")
def post_settings(payload: dict = Body(default_factory=dict)) -> dict:
    return studio_api.save_settings(payload)


@app.get("/api/matches")
def matches() -> dict:
    return {"matches": studio_api.list_matches()}


@app.get("/api/languages")
def languages() -> dict:
    return {"languages": studio_api.list_languages()}


@app.post("/api/resolve")
def resolve(payload: dict = Body(default_factory=dict)) -> dict:
    return studio_api.resolve_source(
        url=str(payload.get("url") or ""),
        match_dir=str(payload.get("match_dir") or ""),
    )


@app.post("/api/preview-colors")
def colors(payload: dict = Body(default_factory=dict)) -> dict:
    match_dir = payload.get("match_dir") or ""
    if not match_dir:
        raise HTTPException(400, "match_dir is required")
    try:
        return studio_api.preview_colors(
            match_dir,
            team=str(payload.get("team") or "club"),
            colors=list(payload.get("colors") or []),
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/draft")
def draft(payload: dict = Body(default_factory=dict)) -> dict:
    try:
        return studio_api.draft_scripts(payload)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    try:
        return studio_api.get_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/jobs/{job_id}/scripts/{language}")
def script_action(job_id: str, language: str, payload: dict = Body(default_factory=dict)) -> dict:
    action = str(payload.get("action") or "").lower()
    try:
        if action == "edit":
            return studio_api.edit_script(job_id, language, list(payload.get("scenes") or []))
        if action == "approve":
            if payload.get("scenes"):
                studio_api.edit_script(job_id, language, list(payload.get("scenes") or []))
            return studio_api.approve_script(job_id, language)
        raise HTTPException(400, "action must be approve or edit")
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/jobs/{job_id}/voice/{language}")
def voice_action(job_id: str, language: str, payload: dict = Body(default_factory=dict)) -> dict:
    action = str(payload.get("action") or "regenerate").lower()
    try:
        if action == "regenerate":
            return studio_api.regenerate_voice(job_id, language, payload.get("voice_id"))
        if action == "approve":
            return studio_api.approve_voice(job_id, language)
        raise HTTPException(400, "action must be regenerate or approve")
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/jobs/{job_id}/audio/{language}")
def voice_audio(job_id: str, language: str) -> FileResponse:
    try:
        path = studio_api.voice_file(job_id, language)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.post("/api/jobs/{job_id}/produce")
def produce(job_id: str, payload: dict = Body(default_factory=dict)) -> dict:
    mode = str(payload.get("mode") or "full")
    try:
        return studio_api.start_produce(job_id, mode=mode)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def parse_launch_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m studio", description="Local recap operator console")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (localhost default)")
    parser.add_argument("--port", type=int, default=8765, help="Port")
    parser.add_argument("--reload", action="store_true", help="Uvicorn reload (dev)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_launch_args(argv)
    studio_api.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    import uvicorn

    uvicorn.run(
        "studio.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0
