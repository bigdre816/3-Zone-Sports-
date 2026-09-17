"""Parse public YouTube URLs into a video id. No API key; embed is watch-only."""

from __future__ import annotations

import re

_ID = r"(?P<id>[A-Za-z0-9_-]{11})"
_PATTERNS = (
    re.compile(rf"(?:https?://)?(?:www\.)?youtube\.com/watch\?(?:[^#]*&)?v={_ID}", re.I),
    re.compile(rf"(?:https?://)?(?:www\.)?youtube\.com/embed/{_ID}", re.I),
    re.compile(rf"(?:https?://)?(?:www\.)?youtube\.com/shorts/{_ID}", re.I),
    re.compile(rf"(?:https?://)?(?:www\.)?youtube\.com/live/{_ID}", re.I),
    re.compile(rf"(?:https?://)?youtu\.be/{_ID}", re.I),
    re.compile(rf"^{_ID}$"),
)


def parse_youtube_id(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("id")
    return None


def youtube_embed_url(video_id: str) -> str:
    return f"https://www.youtube-nocookie.com/embed/{video_id}?rel=0&modestbranding=1"


def youtube_poster_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
