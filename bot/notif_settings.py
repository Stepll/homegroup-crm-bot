import json
from pathlib import Path

_FILE = Path("data/notif_settings.json")

KEYS = ["event_7days", "event_day", "conflict", "conflict_resolved", "attendance_ask"]
DEFAULTS: dict[str, bool] = {k: True for k in KEYS}


def _load_all() -> dict:
    try:
        return json.loads(_FILE.read_text())
    except Exception:
        return {}


def get(group_id: int) -> dict[str, bool]:
    stored = _load_all().get(str(group_id), {})
    return {**DEFAULTS, **{k: bool(v) for k, v in stored.items() if k in DEFAULTS}}


def toggle(group_id: int, key: str) -> dict[str, bool]:
    settings = get(group_id)
    if key in settings:
        settings[key] = not settings[key]
    data = _load_all()
    data[str(group_id)] = settings
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2))
    return settings
