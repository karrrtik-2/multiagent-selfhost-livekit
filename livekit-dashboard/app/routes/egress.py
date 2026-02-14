from fastapi import APIRouter, Depends, Request, Form, HTTPException, status, Header
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from typing import Optional, Tuple, BinaryIO, Any
from datetime import datetime
from pathlib import Path
import os
import mimetypes

from app.services.livekit import LiveKitClient, get_livekit_client
from app.security.basic_auth import requires_admin, get_current_user
from app.security.csrf import get_csrf_token, verify_csrf_token

# LiveKit webhook verification (python sdk)
from livekit.api import TokenVerifier
from livekit.api.webhook import WebhookReceiver


router = APIRouter()

# Change this to where your egress service writes files (mp4/webm/ogg)
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", "/recordings")).resolve()
VIDEO_EXTS = {".mp4", ".webm"}
AUDIO_EXTS = {".ogg", ".opus", ".mp3", ".wav", ".m4a"}

# Webhook auth
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

# Auto-record settings
AUTO_RECORD_ON_SIP_JOIN = os.getenv("AUTO_RECORD_ON_SIP_JOIN", "true").lower() in ("1", "true", "yes", "on")
AUTO_RECORD_AUDIO_ONLY = os.getenv("AUTO_RECORD_AUDIO_ONLY", "true").lower() in ("1", "true", "yes", "on")
AUTO_RECORD_LAYOUT = os.getenv("AUTO_RECORD_LAYOUT", "grid")  # used only when not audio_only
AUTO_RECORD_FILENAME_TMPL = os.getenv(
    "AUTO_RECORD_FILENAME_TMPL",
    "{room}-{sip_call_id}-{time}.mp4",
)


def _webhook_receiver() -> WebhookReceiver:
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise RuntimeError("LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set")
    verifier = TokenVerifier(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    return WebhookReceiver(verifier)


def list_recordings(limit: int = 200):
    items = []
    if not RECORDINGS_DIR.exists():
        return items

    for p in RECORDINGS_DIR.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in AUDIO_EXTS:
            continue

        st = p.stat()
        items.append(
            {
                "filename": p.name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime),
            }
        )

    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def parse_range_header(range_header: str, file_size: int) -> Tuple[int, int]:
    # Example: "bytes=0-1023"
    try:
        units, rng = range_header.split("=", 1)
        if units.strip().lower() != "bytes":
            raise ValueError("Only bytes ranges supported")
        start_s, end_s = rng.split("-", 1)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except Exception:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    if start < 0 or end < start or end > file_size - 1:
        raise HTTPException(status_code=416, detail="Invalid Range header")
    return start, end


def iter_file_range(file_obj: BinaryIO, start: int, end: int, chunk_size: int = 1024 * 1024):
    with file_obj as f:
        f.seek(start)
        while (pos := f.tell()) <= end:
            to_read = min(chunk_size, end + 1 - pos)
            data = f.read(to_read)
            if not data:
                break
            yield data


@router.get("/recordings/{filename}", dependencies=[Depends(requires_admin)])
async def serve_recording(filename: str, request: Request):
    """
    Serves a recording file with Range support so the browser can seek.
    """
    # Path traversal protection
    file_path = (RECORDINGS_DIR / filename).resolve()
    if RECORDINGS_DIR not in file_path.parents:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    file_size = file_path.stat().st_size
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

    range_header = request.headers.get("range")
    start, end = 0, file_size - 1
    status_code = status.HTTP_200_OK

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
    }

    if range_header:
        start, end = parse_range_header(range_header, file_size)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)
        status_code = status.HTTP_206_PARTIAL_CONTENT
    else:
        headers["Content-Length"] = str(file_size)

    return StreamingResponse(
        iter_file_range(open(file_path, "rb"), start, end),
        status_code=status_code,
        headers=headers,
    )


@router.get("/egress", response_class=HTMLResponse, dependencies=[Depends(requires_admin)])
async def egress_index(request: Request, partial: Optional[str] = None, lk: LiveKitClient = Depends(get_livekit_client)):
    egress_jobs = await lk.list_egress(active=True)  # active jobs only
    current_user = get_current_user(request)

    recordings = list_recordings(limit=200)

    template_data = {
        "request": request,
        "egress_jobs": egress_jobs,
        "recordings": recordings,
        "recordings_count": len(recordings),
        "current_user": current_user,
        "sip_enabled": lk.sip_enabled,
        "csrf_token": get_csrf_token(request),
    }

    return request.app.state.templates.TemplateResponse("egress/index.html.j2", template_data)


@router.post("/egress/start", dependencies=[Depends(requires_admin)])
async def start_egress(
    request: Request,
    csrf_token: str = Form(...),
    room_name: str = Form(...),
    output_filename: str = Form(...),
    layout: str = Form("grid"),
    audio_only: Optional[str] = Form(None),
    video_only: Optional[str] = Form(None),
    lk: LiveKitClient = Depends(get_livekit_client),
):
    await verify_csrf_token(request)

    # Replace placeholders in filename
    filename = output_filename.replace("{room}", room_name)
    filename = filename.replace("{time}", datetime.now().strftime("%Y%m%d_%H%M%S"))

    # Optional: enforce extension for video recordings
    if not Path(filename).suffix:
        filename = f"{filename}.mp4"

    try:
        await lk.start_room_composite_egress(
            room_name=room_name,
            output_filename=filename,
            layout=layout,
            audio_only=(audio_only == "on"),
            video_only=(video_only == "on"),
        )
    except Exception as e:
        print(f"Error starting egress: {e}")

    return RedirectResponse(url="/egress", status_code=303)


@router.post("/egress/{egress_id}/stop", dependencies=[Depends(requires_admin)])
async def stop_egress(
    request: Request,
    egress_id: str,
    csrf_token: str = Form(...),
    lk: LiveKitClient = Depends(get_livekit_client),
):
    await verify_csrf_token(request)

    try:
        await lk.stop_egress(egress_id)
    except Exception as e:
        print(f"Error stopping egress: {e}")

    return RedirectResponse(url="/egress", status_code=303)


def _safe_get(obj: Any, path: str, default=None):
    cur = obj
    for key in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur if cur is not None else default


def _is_sip_participant(event) -> bool:
    # Prefer "kind == SIP", but also accept the presence of SIP attributes as a fallback.
    kind = _safe_get(event, "participant.kind")
    kind_s = str(kind).upper() if kind is not None else ""
    attrs = _safe_get(event, "participant.attributes", {}) or {}
    if not isinstance(attrs, dict):
        try:
            attrs = dict(attrs)
        except Exception:
            attrs = {}

    return ("SIP" in kind_s) or ("sip.callID" in attrs) or ("sip.callIDFull" in attrs)


async def _already_recording_room(lk: LiveKitClient, room_name: str) -> bool:
    try:
        active = await lk.list_egress(active=True)
    except Exception:
        return False

    for j in active or []:
        rn = None
        if isinstance(j, dict):
            rn = j.get("room_name") or _safe_get(j, "room_name")
        else:
            rn = getattr(j, "room_name", None)
        if rn == room_name:
            return True
    return False


@router.post("/livekit/webhook")
async def livekit_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
    lk: LiveKitClient = Depends(get_livekit_client),
):
    """
    LiveKit webhook endpoint to auto-start recording when a SIP participant joins.
    Configure this URL in LiveKit webhook settings.
    """
    if not AUTO_RECORD_ON_SIP_JOIN:
        return {"ok": True, "auto_record": "disabled"}

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    raw_body = (await request.body()).decode("utf-8")

    try:
        event = _webhook_receiver().receive(raw_body, authorization)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid webhook")

    if getattr(event, "event", None) != "participant_joined":
        return {"ok": True}

    if not _is_sip_participant(event):
        return {"ok": True, "ignored": "not-sip"}

    room_name = _safe_get(event, "room.name")
    if not room_name:
        return {"ok": True, "ignored": "no-room-name"}

    # Idempotency: avoid starting multiple recordings for same room.
    if await _already_recording_room(lk, room_name):
        return {"ok": True, "recording": "already-running"}

    attrs = _safe_get(event, "participant.attributes", {}) or {}
    sip_call_id = None
    if isinstance(attrs, dict):
        sip_call_id = attrs.get("sip.callID") or attrs.get("sip.callIDFull")

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = (
        AUTO_RECORD_FILENAME_TMPL
        .replace("{room}", room_name)
        .replace("{room_name}", room_name)
        .replace("{time}", now)
        .replace("{sip_call_id}", sip_call_id or "sip")
    )
    if not Path(filename).suffix:
        filename = f"{filename}.mp4"

    try:
        await lk.start_room_composite_egress(
            room_name=room_name,
            output_filename=filename,
            layout=AUTO_RECORD_LAYOUT,
            audio_only=AUTO_RECORD_AUDIO_ONLY,
            video_only=False,
        )
    except Exception as e:
        # If webhook retries happen, idempotency above should prevent duplicates in most cases.
        raise HTTPException(status_code=500, detail=f"Failed to start egress: {e}")

    return {"ok": True, "recording": "started", "room": room_name, "file": filename}
