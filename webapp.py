from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import time
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from image_pipeline import ImageValidationError, image_bytes_to_rgb565_lines
from projector import DeviceNotFoundError, ProjectorClient

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 5

CACHE_FILE = os.path.join(os.path.dirname(__file__), "device_cache.json")
CACHE_TTL_SECONDS = 24 * 60 * 60


def _load_cached_address() -> str | None:
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("saved_at", 0) < CACHE_TTL_SECONDS:
            return data.get("address")
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None


def _save_cached_address(address: str) -> None:
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump({"address": address, "saved_at": time.time()}, f)
    except OSError:
        pass


class SendUrlRequest(BaseModel):
    url: str
    address: str | None = None
    fit_mode: Literal["contain", "stretch"] = "contain"


@dataclass
class TransferStatus:
    state: str = "idle"
    message: str = "Ready"
    sent_lines: int = 0
    total_lines: int = 128
    address: str | None = None


app = FastAPI(title="Smart Sketcher Web")
projector = ProjectorClient(line_delay_seconds=0.05)
transfer_lock = asyncio.Lock()
status = TransferStatus()

static_dir = "web"
app.mount("/web", StaticFiles(directory=static_dir), name="web")


def _set_status(**kwargs: object) -> None:
    global status
    updated = asdict(status)
    updated.update(kwargs)
    status = TransferStatus(**updated)


def _is_ip_forbidden(ip: str) -> bool:
    ip_obj = ipaddress.ip_address(ip)
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def _validate_remote_url(raw_url: str) -> None:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http and https URLs are allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL must include a hostname")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="URLs with credentials are not allowed")

    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise HTTPException(status_code=400, detail="Localhost addresses are not allowed")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Could not resolve URL hostname") from exc

    for info in addrinfo:
        ip = info[4][0]
        if _is_ip_forbidden(ip):
            raise HTTPException(status_code=400, detail="Private or local network URLs are not allowed")


async def fetch_image_bytes_from_url(url: str) -> bytes:
    current_url = url

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _validate_remote_url(current_url)
            response = await client.get(current_url, follow_redirects=False)

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise HTTPException(status_code=400, detail="Redirect response missing location header")
                current_url = urljoin(str(response.url), location)
                continue

            if response.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Image URL returned HTTP {response.status_code}")

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="URL does not point to an image")

            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=400, detail="Image is too large")

            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise HTTPException(status_code=400, detail="Image is too large")

            if not data:
                raise HTTPException(status_code=400, detail="No image data received")

            return bytes(data)

    raise HTTPException(status_code=400, detail="Too many redirects")


async def _send_image_bytes(image_bytes: bytes, address: str | None, fit_mode: str) -> dict[str, str]:
    try:
        lines = image_bytes_to_rgb565_lines(image_bytes, fit_mode=fit_mode)
    except ImageValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if address is None:
        address = _load_cached_address()

    if transfer_lock.locked():
        raise HTTPException(status_code=409, detail="Another transfer is already running")

    async with transfer_lock:
        _set_status(state="connecting", message="Connecting to projector", sent_lines=0, total_lines=128, address=address)

        async def on_progress(sent: int, total: int) -> None:
            _set_status(state="sending", message="Sending image", sent_lines=sent, total_lines=total)

        try:
            used_address = await projector.send_image_lines(lines, address=address, progress_callback=on_progress)
        except DeviceNotFoundError as exc:
            _set_status(state="error", message=str(exc))
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            _set_status(state="error", message=f"Transfer failed: {exc}")
            raise HTTPException(status_code=500, detail=f"Transfer failed: {exc}") from exc

        _set_status(state="done", message="Transfer complete", sent_lines=128, total_lines=128, address=used_address)
        _save_cached_address(used_address)
        return {"message": "Image sent", "address": used_address}


@app.get("/")
async def root() -> FileResponse:
    return FileResponse("web/index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def transfer_status() -> dict[str, object]:
    return asdict(status)


@app.get("/api/cached-device")
async def cached_device() -> dict[str, str | None]:
    return {"address": _load_cached_address()}


@app.get("/api/discover")
async def discover() -> dict[str, str]:
    try:
        address = await projector.discover_address()
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"address": address}


@app.post("/api/send-url")
async def send_url(payload: SendUrlRequest) -> dict[str, str]:
    image_bytes = await fetch_image_bytes_from_url(payload.url)
    return await _send_image_bytes(image_bytes, payload.address, payload.fit_mode)


@app.post("/api/send-upload")
async def send_upload(
    file: UploadFile = File(...),
    address: str | None = Form(default=None),
    fit_mode: Literal["contain", "stretch"] = Form(default="contain"),
) -> dict[str, str]:
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Uploaded image is too large")

    return await _send_image_bytes(image_bytes, address, fit_mode)


if __name__ == "__main__":
    uvicorn.run("webapp:app", host="0.0.0.0", port=8000, reload=False)
