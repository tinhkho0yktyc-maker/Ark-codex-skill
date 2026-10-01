"""Incremental, read-only status reader for old and current Codex rollouts."""

import datetime
import glob
import json
import os
import time
from dataclasses import dataclass, field


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_text(part) for part in content)
    if isinstance(content, dict):
        return _text(content.get("text", content.get("message", "")))
    return ""


def _clean(text, limit=500):
    return " ".join(text.split())[:limit]


def _timestamp(value, fallback=None):
    if isinstance(value, (float, int)):
        return value / 1000 if value > 100_000_000_000 else float(value)
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


@dataclass
class SessionStatus:
    offset: int = 0
    signature: tuple = ()
    pending: bytes = b""
    task: str = ""
    model: str = ""
    progress: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    active: bool = False
    session_tokens: int | None = None
    baseline_tokens: int = 0
    turn_tokens: int | None = None
    malformed_lines: int = 0
    last_mtime: float = 0

    def consume(self, obj):
        payload = obj.get("payload") or {}
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        stamp = _timestamp(obj.get("timestamp"), time.time())
        settings = payload.get("thread_settings") or {}
        if isinstance(settings, dict) and settings.get("model"):
            self.model = str(settings["model"])
        if payload.get("model"):
            self.model = str(payload["model"])
        if kind in ("task_started", "turn_started"):
            self.active = True
            self.started_at = _timestamp(payload.get("started_at"), stamp)
            self.baseline_tokens = self.session_tokens or 0
            self.turn_tokens = 0
            self.progress = ""
        elif kind in ("task_complete", "turn_complete", "turn_aborted", "task_aborted"):
            self.active = False
            self.finished_at = _timestamp(payload.get("completed_at"), stamp)
            message = payload.get("last_agent_message")
            if isinstance(message, str):
                self.progress = _clean(message)
        elif kind == "token_count":
            info = payload.get("info") or {}
            usage = info.get("total_token_usage") or {}
            total = usage.get("total_tokens")
            if isinstance(total, (int, float)):
                self.session_tokens = int(total)
                self.turn_tokens = max(0, int(total) - self.baseline_tokens)
        item = payload.get("item") if kind == "item_completed" else payload
        if not isinstance(item, dict):
            return
        item_type = item.get("type", "")
        role = item.get("role")
        if item_type in ("UserMessage", "user_message") or (item_type == "message" and role == "user"):
            text = _text(item.get("content", item.get("message", "")))
            if text and not text.strip().startswith(("<environment_context>", "<external_codex_apps_open_page>")):
                for marker in ("## My request:", "My request for Codex:"):
                    if marker in text:
                        text = text.split(marker, 1)[1]
                self.task = _clean(text)
        elif item_type in ("AgentMessage", "agent_message"):
            text = _text(item.get("content", item.get("message", "")))
            if text and item.get("phase") in ("commentary", "final"):
                self.progress = _clean(text)

    def read_new(self, path):
        stat = os.stat(path)
        identity = (stat.st_dev, stat.st_ino)
        if self.signature != identity or stat.st_size < self.offset:
            self.__dict__.update(SessionStatus(signature=identity).__dict__)
        self.last_mtime = stat.st_mtime
        if stat.st_size == self.offset:
            return
        with open(path, "rb") as handle:
            handle.seek(self.offset)
            data = self.pending + handle.read()
            self.offset = handle.tell()
        lines = data.split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    self.consume(obj)
            except (ValueError, TypeError, AttributeError):
                self.malformed_lines += 1


@dataclass
class StatusReader:
    root: str
    sessions: dict = field(default_factory=dict)
    paths: list = field(default_factory=list)
    last_scan: float = -10

    def poll(self):
        now = time.time()
        if now - self.last_scan >= 3:
            dated = []
            for path in glob.glob(os.path.join(self.root, "**", "rollout-*.jsonl"), recursive=True):
                try:
                    dated.append((os.path.getmtime(path), path))
                except OSError:
                    continue
            self.paths = [path for _, path in sorted(dated, reverse=True)[:8]]
            self.last_scan = now
            keep = set(self.paths)
            self.sessions = {p: s for p, s in self.sessions.items() if p in keep}
        available = []
        for path in self.paths:
            session = self.sessions.setdefault(path, SessionStatus())
            try:
                session.read_new(path)
                available.append(session)
            except OSError:
                continue
        active = [s for s in available if s.active]
        candidates = active or available
        if not candidates:
            return {"active": False, "active_count": 0}
        session = max(candidates, key=lambda s: s.last_mtime)
        return {
            "active": session.active,
            "active_count": len(active),
            "task": session.task,
            "model": session.model,
            "progress": session.progress,
            "elapsed": max(0, int(now - session.started_at)) if session.active and session.started_at else None,
            "tokens": session.turn_tokens,
            "session_tokens": session.session_tokens,
            "last_finished": datetime.datetime.fromtimestamp(session.finished_at).strftime("%H:%M") if session.finished_at else None,
            "malformed_lines": session.malformed_lines,
        }


_reader = StatusReader(os.path.join(
    os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex"),
    "sessions",
))


def get_codex_status():
    return _reader.poll()
