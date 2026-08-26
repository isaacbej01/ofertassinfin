"""Estado persistente: qué se publicó, cuándo, y con qué resultado.

Se guarda como JSON en data/state.json y se commitea al repo por el
workflow de GitHub Actions. Así el historial sobrevive entre corridas
sin necesidad de base de datos.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .config import DATA_DIR, get

STATE_FILE = DATA_DIR / "state.json"

_EMPTY = {
    "version": 1,
    "published": {},   # key -> {"published_at": iso, "source": str, "title": str, "price": float}
    "runs": [],        # historial corto de corridas
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class State:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return json.loads(json.dumps(_EMPTY))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------------------------------------------------------------- dedupe
    def was_published(self, key: str) -> bool:
        entry = self.data["published"].get(key)
        if not entry:
            return False
        dias = get("cadencia.dias_bloqueo_reposteo", 45)
        try:
            when = datetime.fromisoformat(entry["published_at"])
        except (ValueError, KeyError):
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return _now() - when < timedelta(days=dias)

    def filter_new(self, deals: Iterable) -> list:
        return [d for d in deals if not self.was_published(d.key)]

    def mark_published(self, deal, scheduled_at: str = ""):
        self.data["published"][deal.key] = {
            "published_at": _now().isoformat(),
            "scheduled_at": scheduled_at,
            "source": deal.source,
            "title": deal.title[:120],
            "price": deal.price,
            "discount_pct": deal.discount_pct,
            "category_id": deal.category_id,
        }

    # ------------------------------------------------------------- cadencia
    def published_today(self, source: str | None = None) -> int:
        hoy = _now().date()
        n = 0
        for e in self.data["published"].values():
            try:
                when = datetime.fromisoformat(e["published_at"]).date()
            except (ValueError, KeyError):
                continue
            if when == hoy and (source is None or e.get("source") == source):
                n += 1
        return n

    # ------------------------------------------------------------ mantenimiento
    def prune(self, dias: int = 180):
        corte = _now() - timedelta(days=dias)
        keep = {}
        for k, e in self.data["published"].items():
            try:
                when = datetime.fromisoformat(e["published_at"])
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when >= corte:
                    keep[k] = e
            except (ValueError, KeyError):
                continue
        self.data["published"] = keep

    def log_run(self, resumen: dict):
        self.data["runs"].append({"at": _now().isoformat(), **resumen})
        self.data["runs"] = self.data["runs"][-60:]
