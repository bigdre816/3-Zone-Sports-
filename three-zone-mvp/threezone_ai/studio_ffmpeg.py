"""Studio FFmpeg clip cutting (no Remotion — see docs/STUDIO.md)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class StudioError(RuntimeError):
    """Raised for invalid clip bounds or missing ffmpeg."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def cut_clip(
    source_path: str | Path,
    start_s: float,
    end_s: float,
    out_path: str | Path,
    min_s: float = 5.0,
    max_s: float = 60.0,
) -> Path:
    """
    Cut a clip from source_path using ffmpeg.

    Validates duration is within [min_s, max_s] and start/end are sensible.
    Raises StudioError with a clear message if ffmpeg is missing or bounds fail.
    """
    src = Path(source_path)
    out = Path(out_path)

    if not src.is_file():
        raise StudioError(f"Source media not found: {src}")

    if start_s < 0:
        raise StudioError(f"start_s must be >= 0, got {start_s}")
    if end_s <= start_s:
        raise StudioError(
            f"end_s ({end_s}) must be greater than start_s ({start_s})"
        )

    duration = float(end_s) - float(start_s)
    if duration < min_s:
        raise StudioError(
            f"Clip duration {duration:.2f}s is below minimum {min_s}s"
        )
    if duration > max_s:
        raise StudioError(
            f"Clip duration {duration:.2f}s exceeds maximum {max_s}s"
        )

    if not ffmpeg_available():
        raise StudioError(
            "ffmpeg not found on PATH. Install ffmpeg to use studio clips."
        )

    out.parent.mkdir(parents=True, exist_ok=True)

    # Re-encode for accurate cuts; keep audio when present
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_s),
        "-to",
        str(end_s),
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise StudioError(
            "ffmpeg not found on PATH. Install ffmpeg to use studio clips."
        ) from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise StudioError(
            f"ffmpeg failed (exit {proc.returncode}): {err[:500]}"
        )

    if not out.is_file():
        raise StudioError(f"ffmpeg reported success but output missing: {out}")

    return out
