"""Состояние карты: какие регионы и какая угроза активна."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MSK = timezone(timedelta(hours=3))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ThreatState:
    def __init__(self, path: Path, ttl_minutes: int = 180):
        self.path = Path(path)
        self.ttl = timedelta(minutes=ttl_minutes)
        self.regions: dict[str, dict[str, str]] = {}
        self.last_post_id: int = 0
        self.updated_at: str = ""
        self.last_summary: str = ""            # подпись последней отправленной сводки
        self.pending_summary: list[dict] = []  # сводки, которые ещё не ушли в канал
        self._load()

    # ---------- персистентность ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.regions = data.get("regions", {})
        self.last_post_id = int(data.get("last_post_id", 0))
        self.updated_at = data.get("updated_at", "")
        self.last_summary = data.get("last_summary", "")
        raw_pending = data.get("pending_summary") or []
        self.pending_summary = raw_pending if isinstance(raw_pending, list) else [raw_pending]
        self.expire()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "regions": self.regions,
            "last_post_id": self.last_post_id,
            "updated_at": self.updated_at,
            "last_summary": self.last_summary,
            "pending_summary": self.pending_summary,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- логика ----------
    def expire(self) -> bool:
        """Снимает угрозы, которые висят дольше TTL без подтверждения."""
        changed = False
        limit = datetime.now(timezone.utc) - self.ttl
        for region in list(self.regions):
            types = self.regions[region]
            for t in list(types):
                try:
                    if parse_iso(types[t]) < limit:
                        del types[t]
                        changed = True
                except Exception:
                    del types[t]
                    changed = True
            if not types:
                del self.regions[region]
                changed = True
        return changed

    def status(self, region: str) -> str | None:
        types = self.regions.get(region, {})
        if "rocket" in types:
            return "rocket"
        if "bpla" in types:
            return "bpla"
        return None

    def apply(self, parsed) -> bool:
        changed = False
        stamp = now_iso()
        if parsed.kind == "clear_all":
            # «Отбой ракетной опасности по всем регионам» снимает только ракеты,
            # тревоги по БПЛА остаются.
            types_to_clear = parsed.types or ["rocket", "bpla"]
            for region in list(self.regions):
                types = self.regions[region]
                for t in types_to_clear:
                    if t in types:
                        del types[t]
                        changed = True
                if not types:
                    self.regions.pop(region, None)
        elif parsed.kind == "alert":
            for region in parsed.regions:
                types = self.regions.setdefault(region, {})
                for t in parsed.types:
                    if t not in types:
                        changed = True
                    types[t] = stamp
        elif parsed.kind == "clear":
            for region in parsed.regions:
                types = self.regions.get(region)
                if not types:
                    continue
                for t in parsed.types:
                    if t in types:
                        del types[t]
                        changed = True
                if not types:
                    self.regions.pop(region, None)
        if changed:
            self.updated_at = stamp
        return changed

    def summary(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"rocket": [], "bpla": []}
        for region in sorted(self.regions):
            st = self.status(region)
            if st:
                out[st].append(region)
        return out
