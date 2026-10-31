"""Open the local frontend on a phone through a Cloudflare quick tunnel (demo tools, DEMO_TOOLS_ENABLED).

One tunnel to the frontend is enough: the Next.js proxy forwards both REST and WebSocket traffic to this backend.
Anyone with the tunnel URL reaches the demo while it is open, so it is started and stopped only from the laptop.
"""

import asyncio
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request

URL = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
READY = "Registered tunnel connection"
START_SECONDS = 45
INSTALL_HINT = "cloudflared is not installed. Install it with: winget install Cloudflare.cloudflared"


class Tunnel:
    """One cloudflared quick tunnel process and the public URL it printed."""

    def __init__(self, command: str = "cloudflared"):
        self.command = command
        self.process: subprocess.Popen | None = None
        self.url: str | None = None
        self.ready = threading.Event()
        self.lines: deque[str] = deque(maxlen=20)
        self.lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def status(self) -> dict:
        """Whether the tunnel is up and its public URL."""
        running = self.running
        return {"running": running, "url": self.url if running else None}

    def start(self, port: int, timeout: float = START_SECONDS) -> dict:
        """Start a tunnel to localhost:<port>, or return the one already running. Raises RuntimeError on failure."""
        with self.lock:
            if self.running and self.ready.is_set():
                return self.status()
            self._stop()
            exe = shutil.which(self.command)
            if exe is None:
                raise RuntimeError(INSTALL_HINT)
            self.ready.clear()
            self.process = subprocess.Popen(
                [exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            threading.Thread(target=self._read, args=(self.process,), daemon=True).start()
            deadline = time.monotonic() + timeout
            while not self.ready.wait(0.2):
                if not self.running or time.monotonic() > deadline:
                    detail = " | ".join(list(self.lines)[-3:]) or "no output"
                    self._stop()
                    raise RuntimeError(f"The tunnel did not start: {detail}")
            return self.status()

    def stop(self) -> dict:
        """Close the tunnel if it is open."""
        with self.lock:
            self._stop()
            return self.status()

    def _stop(self) -> None:
        process, self.process, self.url = self.process, None, None
        self.ready.clear()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def _read(self, process: subprocess.Popen) -> None:
        # Keep draining stderr for the process's whole life, or cloudflared blocks on a full pipe.
        for line in process.stderr:
            self.lines.append(line.strip())
            if process is not self.process:
                continue
            if self.url is None and (match := URL.search(line)):
                self.url = match.group(0)
            if self.url and READY in line:
                self.ready.set()


tunnel = Tunnel()
router = APIRouter(prefix="/api/phone-link", tags=["demo"])


def frontend_port() -> int:
    """The local frontend port the tunnel exposes (PHONE_LINK_PORT, default 3000)."""
    return int(os.getenv("PHONE_LINK_PORT", "3000"))


def require_laptop(request: Request) -> None:
    """Refuse requests that arrived through the tunnel, so only the laptop opens or closes it."""
    if request.headers.get("cf-connecting-ip") or request.headers.get("cf-ray"):
        raise HTTPException(status_code=403, detail="Open or close the phone link from the laptop.")


@router.get("")
async def phone_link_status() -> dict:
    """Whether the phone link is open, and its public URL."""
    return tunnel.status()


@router.post("/start")
async def start_phone_link(request: Request) -> dict:
    """Open the tunnel to the local frontend and return its public URL."""
    require_laptop(request)
    try:
        return await asyncio.to_thread(tunnel.start, frontend_port())
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/stop")
async def stop_phone_link(request: Request) -> dict:
    """Close the tunnel."""
    require_laptop(request)
    return await asyncio.to_thread(tunnel.stop)
