"""Local managed-media adapter.

This is the *replacement seam*. It only creates a small local test asset so the
browser has something to play. In production this module is replaced by a
managed SRT contribution + transcoder + packager + object store + CDN, and the
CDN edge calls ``ControlPlane.validate_lease`` (or ``/api/leases/validate``)
before serving or packaging any segment.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# A tiny but structurally valid MP4 (ftyp + minimal moov). Used only when
# FFmpeg is unavailable so the endpoint still serves bytes and lease-gating
# stays testable. It is not guaranteed to render video.
_FALLBACK_MP4 = bytes.fromhex(
    "0000001c667479706d70343200000000"
    "6d70343269736f6d0000000869736f6d"
    "0000000f6d6461740000000000000000"
)


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def ensure_media(media_dir: str, event_id: str, seconds: int = 6) -> str:
    """Return a path to a playable-ish MP4 for ``event_id``, creating it once."""
    os.makedirs(media_dir, exist_ok=True)
    path = os.path.join(media_dir, f"{event_id}.mp4")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    ffmpeg = _ffmpeg()
    if ffmpeg:
        tmp = path + ".tmp.mp4"
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=15:duration={seconds}",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-shortest", "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "baseline",
            "-c:a", "aac", "-movflags", "+faststart", tmp,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.replace(tmp, path)
            return path
        except (subprocess.SubprocessError, OSError):
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            # fall through to fallback bytes

    with open(path, "wb") as handle:
        handle.write(_FALLBACK_MP4)
    return path


def read_range(path: str, range_header: str | None):
    """Return ``(status, headers, body)`` for a media response, honoring a
    single-range ``Range`` request so browsers can seek."""
    size = os.path.getsize(path)
    base_headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
    }
    start, end = 0, size - 1
    is_range = False
    if range_header and range_header.startswith("bytes="):
        is_range = True
        spec = range_header[len("bytes="):].split(",")[0].strip()
        lo, _, hi = spec.partition("-")
        try:
            if lo == "":
                # suffix range: last N bytes
                length = int(hi)
                start = max(0, size - length)
                end = size - 1
            else:
                start = int(lo)
                end = int(hi) if hi else size - 1
        except ValueError:
            is_range = False
            start, end = 0, size - 1
        if is_range and (start > end or start >= size):
            headers = dict(base_headers)
            headers["Content-Range"] = f"bytes */{size}"
            return 416, headers, b""
        end = min(end, size - 1)

    with open(path, "rb") as handle:
        handle.seek(start)
        body = handle.read(end - start + 1)

    headers = dict(base_headers)
    headers["Content-Length"] = str(len(body))
    if is_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return 206, headers, body
    return 200, headers, body
