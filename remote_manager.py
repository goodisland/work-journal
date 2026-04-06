from __future__ import annotations

import uuid
from datetime import datetime

from storage import ACTIVE_REMOTE_SESSION_PATH, read_json, write_json


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class RemoteSessionService:
    def get_active_session(self) -> dict | None:
        session = read_json(ACTIVE_REMOTE_SESSION_PATH, None)
        return session if isinstance(session, dict) and session.get("remote_tool") else None

    def start_session(self, remote_tool: str, remote_host: str = "", remote_note: str = "") -> dict:
        tool = remote_tool.strip()
        if not tool:
            raise ValueError("Remote tool is required.")

        active = self.get_active_session()
        if active and active.get("remote_tool") == tool and active.get("remote_host", "") == remote_host.strip():
            return active

        session = {
            "remote_session_id": uuid.uuid4().hex,
            "remote_tool": tool,
            "remote_host": remote_host.strip(),
            "remote_note": remote_note.strip(),
            "started_at": _now_iso(),
            "work_mode": "remote",
        }
        write_json(ACTIVE_REMOTE_SESSION_PATH, session)
        return session

    def stop_session(self) -> dict | None:
        active = self.get_active_session()
        if not active:
            return None
        finished = dict(active)
        finished["ended_at"] = _now_iso()
        write_json(ACTIVE_REMOTE_SESSION_PATH, {})
        return finished

    def get_context(self) -> dict:
        active = self.get_active_session()
        if not active:
            return {"work_mode": "local"}
        return {
            "work_mode": "remote",
            "remote_session_id": active.get("remote_session_id", ""),
            "remote_tool": active.get("remote_tool", ""),
            "remote_host": active.get("remote_host", ""),
            "remote_note": active.get("remote_note", ""),
            "remote_started_at": active.get("started_at", ""),
        }
