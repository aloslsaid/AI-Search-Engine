"""Small helpers: message splitting, anti-spam, date keys."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

TELEGRAM_SAFE_LIMIT = 4000  # Telegram hard limit is 4096; keep a margin.


def split_message(text: str, limit: int = TELEGRAM_SAFE_LIMIT) -> list[str]:
    """Split text into chunks <= limit, preferring paragraph/line/word boundaries."""
    text = (text or "").strip()
    if not text:
        return ["…"]
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunk = text[:cut].rstrip()
        if chunk:
            parts.append(chunk)
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def pack_blocks(blocks: list[str], limit: int = TELEGRAM_SAFE_LIMIT, sep: str = "\n\n") -> list[str]:
    """Join text blocks into messages without ever cutting a block in half.

    Used for HTML messages where splitting in the middle would break tags.
    A single block that is itself longer than the limit is truncated.
    """
    messages: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > limit:
            block = block[: limit - 1] + "…"
        candidate = block if not current else current + sep + block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                messages.append(current)
            current = block
    if current:
        messages.append(current)
    return messages


def today_key(utc_offset_hours: int = 0, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=utc_offset_hours)).date().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SpamVerdict:
    allowed: bool
    wait: float = 0.0
    # "ok" | "too_fast" | "blocked" | "blocked_now"
    reason: str = "ok"


class AntiSpam:
    """In-memory per-user flood protection.

    * min_interval: minimum seconds between two accepted requests.
    * burst_max within burst_window: exceeding it triggers a cooldown block.
    """

    def __init__(self, min_interval: float, burst_max: int, burst_window: float,
                 cooldown: float) -> None:
        self.min_interval = min_interval
        self.burst_max = burst_max
        self.burst_window = burst_window
        self.cooldown = cooldown
        self._last: dict[int, float] = {}
        self._hits: dict[int, deque[float]] = {}
        self._blocked_until: dict[int, float] = {}

    def check(self, user_id: int, now: float | None = None) -> SpamVerdict:
        now = time.monotonic() if now is None else now

        blocked = self._blocked_until.get(user_id, 0.0)
        if blocked > now:
            return SpamVerdict(False, blocked - now, "blocked")

        last = self._last.get(user_id)
        if last is not None and (now - last) < self.min_interval:
            return SpamVerdict(False, self.min_interval - (now - last), "too_fast")

        hits = self._hits.setdefault(user_id, deque())
        while hits and now - hits[0] > self.burst_window:
            hits.popleft()
        if len(hits) >= self.burst_max:
            self._blocked_until[user_id] = now + self.cooldown
            hits.clear()
            return SpamVerdict(False, self.cooldown, "blocked_now")

        hits.append(now)
        self._last[user_id] = now
        self._cleanup(now)
        return SpamVerdict(True)

    def _cleanup(self, now: float) -> None:
        if len(self._last) < 5000:
            return
        stale = [uid for uid, ts in self._last.items() if now - ts > 3600]
        for uid in stale:
            self._last.pop(uid, None)
            self._hits.pop(uid, None)
            self._blocked_until.pop(uid, None)
