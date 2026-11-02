"""WebSocket broadcaster: pushes live events + snapshots to dashboard clients."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from typing import Any

log = logging.getLogger("broadcaster")


class Broadcaster:
    def __init__(self, history_size: int = 300) -> None:
        self._clients: dict[int, asyncio.Queue] = {}
        self._next_id = 0
        self._history: deque[str] = deque(maxlen=history_size)

    async def connect(self) -> tuple[int, asyncio.Queue]:
        self._next_id += 1
        cid = self._next_id
        self._clients[cid] = asyncio.Queue(maxsize=500)
        # replay recent history so a fresh page is instantly full
        for line in list(self._history)[-120:]:
            await self._clients[cid].put(line)
        return cid, self._clients[cid]

    def disconnect(self, cid: int) -> None:
        self._clients.pop(cid, None)

    async def send(self, payload: dict[str, Any]) -> None:
        try:
            line = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            return
        kind = payload.get("type")
        if kind == "event":
            self._history.append(line)
        dead: list[int] = []
        for cid, q in self._clients.items():
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    def send_nowait(self, payload: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.send(payload))
