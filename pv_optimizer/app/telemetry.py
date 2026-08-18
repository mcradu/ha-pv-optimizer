from __future__ import annotations

import json
from collections import deque
from pathlib import Path


class TelemetryStore:
    def __init__(self, path: Path, recent_limit: int = 500, maximum_bytes: int = 5_000_000) -> None:
        self.path = path
        self.maximum_bytes = maximum_bytes
        self.recent = deque(maxlen=recent_limit)
        try:
            for line in self.path.read_text().splitlines()[-recent_limit:]:
                self.recent.append(json.loads(line))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size >= self.maximum_bytes:
            rotated = self.path.with_suffix(".previous.jsonl")
            if rotated.exists():
                rotated.unlink()
            self.path.replace(rotated)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.recent.append(record)

    def latest(self, limit: int = 100) -> list[dict]:
        return list(self.recent)[-max(1, min(limit, self.recent.maxlen or 500)):]
