from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlsplit, urlunsplit


@dataclass(frozen=True)
class CameraSource:
    id: str
    name: str
    transport: str
    endpoint: str
    username: str | None = None
    password: str | None = None


class CameraAdapter(Protocol):
    def verify(self) -> None: ...

    def capture_command(self, output_path: str) -> list[str]: ...


class RtspCameraAdapter:
    def __init__(self, camera: CameraSource):
        self.camera = camera

    def verify(self) -> None:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "json",
                self._authenticated_url(),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"camera connection failed: {stderr or 'ffprobe returned non-zero exit status'}")

    def capture_command(self, output_path: str) -> list[str]:
        return [
            "ffmpeg",
            "-nostdin",
            "-rtsp_transport",
            "tcp",
            "-i",
            self._authenticated_url(),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            "10",
            "-reset_timestamps",
            "1",
            output_path,
        ]

    def _authenticated_url(self) -> str:
        if not self.camera.username:
            return self.camera.endpoint
        parsed = urlsplit(self.camera.endpoint)
        username = quote(self.camera.username, safe="")
        password = quote(self.camera.password or "", safe="")
        userinfo = f"{username}:{password}@"
        return urlunsplit((parsed.scheme, userinfo + parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def adapter_for(camera: CameraSource) -> CameraAdapter:
    if camera.transport == "rtsp":
        return RtspCameraAdapter(camera)
    raise ValueError(f"unsupported camera transport: {camera.transport}")
