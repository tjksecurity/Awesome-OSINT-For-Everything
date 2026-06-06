"""EVA HTTP server — drives the same agent from a phone (PWA, Shortcuts, bot)."""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import platform
import queue
import secrets
import threading
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .agent import Agent
from .auth import Authorizer
from .config import Config, load_config
from .memory import MemoryStore


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

# ---- module-level state --------------------------------------------------

_config: Config | None = None
_memory: MemoryStore | None = None
_authorizer: Authorizer | None = None
_agent: Agent | None = None
_auth_token: str = ""

_agent_lock = threading.Lock()  # serialize turns — one EVA, one conversation


# ---- security ------------------------------------------------------------

bearer_scheme = HTTPBearer(auto_error=False)


def _check_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    # Allow token in Authorization: Bearer ... OR ?token=... (for EventSource).
    sent = ""
    if creds is not None:
        sent = creds.credentials or ""
    if not sent:
        sent = request.query_params.get("token", "")
    if not sent or not secrets.compare_digest(sent, _auth_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


# ---- API models / helpers ------------------------------------------------

def _state_snapshot() -> dict:
    assert _agent is not None and _authorizer is not None
    auth_state = _authorizer.state
    return {
        "model": _config.model if _config else "",
        "effort": _config.effort if _config else "",
        "user_name": _config.user_name if _config else "Commander",
        "workspace": str(_config.workspace) if _config else "",
        "host": platform.node(),
        "authorizer": {
            "mode": auth_state.mode,
            "expires_at": auth_state.expires_at,
        },
        "turns": sum(1 for m in _agent.messages if m["role"] == "user"),
        "memory_entries": len(_memory.entries) if _memory else 0,
        "tool_count": len(_agent._tool_schemas),
    }


def _sse(event: str, data) -> bytes:
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    # SSE: each event = "event: name\ndata: payload\n\n"
    # Make sure no newlines in payload break framing.
    payload = payload.replace("\r\n", "\n").replace("\n", "\\n")
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


# ---- app -----------------------------------------------------------------

app = FastAPI(title="EVA", docs_url=None, redoc_url=None)

# CORS: PWA may be served from a different origin during dev. In production
# the PWA is served by the same FastAPI app, so this is mostly defensive.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/state")
async def state(_: None = Depends(_check_token)) -> dict:
    return _state_snapshot()


@app.post("/api/reset")
async def reset(_: None = Depends(_check_token)) -> dict:
    assert _agent is not None
    with _agent_lock:
        _agent.reset()
    return {"ok": True, "message": "Tactical buffer cleared. Memory retained."}


@app.post("/api/authorize")
async def authorize(
    request: Request, _: None = Depends(_check_token)
) -> dict:
    """Toggle the authorization gate. Body: {mode, ttl_seconds?}."""
    assert _authorizer is not None
    body = await request.json() if request.headers.get("content-length") else {}
    mode = body.get("mode", "one_shot")
    ttl = int(body.get("ttl_seconds", 0))
    try:
        st = _authorizer.set_mode(mode, ttl_seconds=ttl)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "ok": True,
        "mode": st.mode,
        "expires_at": st.expires_at,
        "message": _mode_message(st.mode, ttl),
    }


def _mode_message(mode: str, ttl: int) -> str:
    if mode == "deny":
        return "Authorization revoked. Destructive operations locked."
    if mode == "one_shot":
        return "Authorization granted. One destructive operation permitted."
    if mode == "session":
        if ttl > 0:
            return f"Session authorization granted for {ttl}s."
        return "Session authorization granted. Standing by."
    return ""


@app.get("/api/memory")
async def get_memory(_: None = Depends(_check_token)) -> dict:
    assert _memory is not None
    return {
        "entries": [
            {
                "key": e.key,
                "value": e.value,
                "tags": e.tags,
                "updated_at": e.updated_at,
            }
            for e in sorted(_memory.entries.values(), key=lambda x: x.updated_at, reverse=True)
        ]
    }


@app.delete("/api/memory/{key}")
async def del_memory(key: str, _: None = Depends(_check_token)) -> dict:
    assert _memory is not None
    ok = _memory.forget(key)
    return {"ok": ok}


@app.post("/api/chat")
async def chat(request: Request, _: None = Depends(_check_token)) -> StreamingResponse:
    """Streaming chat endpoint. Body: {message: str}. Returns SSE stream."""
    body = await request.json()
    user_message = (body.get("message") or "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message is required")

    async def stream() -> AsyncIterator[bytes]:
        assert _agent is not None
        # Run the sync generator in a thread, pipe events through an asyncio.Queue.
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def producer() -> None:
            try:
                with _agent_lock:
                    for ev in _agent.turn(user_message):
                        loop.call_soon_threadsafe(q.put_nowait, ev)
            except Exception as exc:  # noqa: BLE001
                err = {"kind": "error", "text": f"server error: {exc}", "is_error": True}
                loop.call_soon_threadsafe(q.put_nowait, err)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, sentinel)

        threading.Thread(target=producer, daemon=True).start()

        # Initial state echo so the client can update its UI.
        yield _sse("state", _state_snapshot())

        try:
            while True:
                item = await q.get()
                if item is sentinel:
                    break
                if isinstance(item, dict):
                    yield _sse("event", item)
                else:
                    yield _sse(
                        "event",
                        {
                            "kind": item.kind,
                            "text": item.text,
                            "tool_name": item.tool_name,
                            "is_error": item.is_error,
                        },
                    )
        except asyncio.CancelledError:
            # Client disconnected — let the producer finish in the background.
            raise

        # Final state echo so the client can refresh memory count, etc.
        yield _sse("state", _state_snapshot())
        yield _sse("done", {"ok": True})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # for nginx; harmless elsewhere
            "Connection": "keep-alive",
        },
    )


# ---- static PWA ----------------------------------------------------------

if WEB_ROOT.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT)), name="static")

    @app.get("/")
    async def root_index() -> FileResponse:
        return FileResponse(str(WEB_ROOT / "index.html"))

    @app.get("/manifest.webmanifest")
    async def manifest() -> FileResponse:
        return FileResponse(
            str(WEB_ROOT / "manifest.webmanifest"),
            media_type="application/manifest+json",
        )

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        return FileResponse(
            str(WEB_ROOT / "sw.js"),
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.get("/icon-{size}.svg")
    async def icon(size: int) -> FileResponse:
        return FileResponse(str(WEB_ROOT / "icon.svg"), media_type="image/svg+xml")


# ---- entry point ---------------------------------------------------------

def _init_state(cfg: Config) -> None:
    global _config, _memory, _authorizer, _agent
    cfg.ensure_home()
    _config = cfg
    _memory = MemoryStore(cfg.memory_file)
    _authorizer = Authorizer()
    _agent = Agent(
        config=cfg,
        memory=_memory,
        confirm_destructive=_authorizer.confirm,
        exclude_tool_tags=(),  # destructive tools present; gated by authorizer
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis-server", description="EVA HTTP server.")
    p.add_argument("--host", default=os.environ.get("JARVIS_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_PORT", "8765")))
    p.add_argument("--model", help="override model ID")
    p.add_argument("--effort", help="override effort level")
    p.add_argument("--cwd", help="EVA working directory on this host")
    p.add_argument(
        "--read-only",
        action="store_true",
        help="strip destructive tools entirely (write_file, shell_exec)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    global _auth_token
    args = build_parser().parse_args(argv)

    cfg = load_config()
    if args.model:
        cfg.model = args.model
    if args.effort:
        cfg.effort = args.effort
    if args.cwd:
        p = Path(args.cwd).expanduser().resolve()
        if not p.is_dir():
            raise SystemExit(f"not a directory: {p}")
        cfg.workspace = p

    _auth_token = os.environ.get("JARVIS_AUTH_TOKEN", "").strip()
    if not _auth_token:
        # Generate one and print it on first run so the operator can pair the phone.
        _auth_token = secrets.token_urlsafe(24)
        cfg.ensure_home()
        token_file = cfg.home_dir / "server_token"
        token_file.write_text(_auth_token + "\n")
        token_file.chmod(0o600)
        print(f"[EVA] Generated auth token. Pair your phone with this value:")
        print(f"[EVA]   {_auth_token}")
        print(f"[EVA] Stored at {token_file} (chmod 600).")
        print(f"[EVA] Set JARVIS_AUTH_TOKEN to override.")

    _init_state(cfg)

    if args.read_only:
        # Rebuild agent without destructive tools
        global _agent
        assert _memory is not None and _authorizer is not None
        _agent = Agent(
            config=cfg,
            memory=_memory,
            confirm_destructive=lambda *_: False,
            exclude_tool_tags=("destructive", "shell"),
        )
        print("[EVA] Read-only mode: shell_exec and write_file disabled.")

    print(f"[EVA] Listening on http://{args.host}:{args.port}")
    print(f"[EVA] PWA: http://{args.host}:{args.port}/")
    print(f"[EVA] Workspace: {cfg.workspace}")

    import uvicorn  # local import so the CLI startup doesn't pay this cost
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    main()
