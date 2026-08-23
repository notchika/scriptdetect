import json
import os
import uuid

_schedules: dict = {}  # { schedule_id: {id, name, date, items: [ {id, kind, ...} ]} }

SCHEDULES_DIR_DEFAULT = "schedules"
SCHEDULES_FILE = "schedules.json"

# Recognized item kinds:
#   scripture     — {id, kind, reference, translation}
#   song          — {id, kind, song_id, title}
#   announcement  — {id, kind, title, text}
ITEM_KINDS = ("scripture", "song", "announcement")


def _get_path(schedules_dir: str = None) -> str:
    if schedules_dir is None:
        schedules_dir = os.path.join(os.path.dirname(__file__), SCHEDULES_DIR_DEFAULT)
    os.makedirs(schedules_dir, exist_ok=True)
    return os.path.join(schedules_dir, SCHEDULES_FILE)


def load_schedules(schedules_dir: str = None):
    """Load schedules.json into memory at startup. Creates an empty one if missing."""
    global _schedules
    path = _get_path(schedules_dir)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
        _schedules = {}
        print("[Schedule Loader] No schedules.json found — created empty library")
        return

    with open(path, "r", encoding="utf-8") as f:
        _schedules = json.load(f)

    print(f"[Schedule Loader] Loaded {len(_schedules)} schedule(s)")


def _save():
    path = _get_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_schedules, f, indent=2, ensure_ascii=False)


def list_schedules() -> list:
    """Lightweight list for the schedule picker: id, name, date, item_count."""
    return [
        {
            "id": sid,
            "name": s.get("name", ""),
            "date": s.get("date", ""),
            "item_count": len(s.get("items", [])),
        }
        for sid, s in _schedules.items()
    ]


def get_schedule(schedule_id: str) -> dict | None:
    return _schedules.get(schedule_id)


def get_all_schedules() -> dict:
    """Return the full {schedule_id: schedule} dict — used for backup export."""
    return _schedules


def create_schedule(name: str, date: str = "") -> dict:
    schedule_id = str(uuid.uuid4())[:8]
    while schedule_id in _schedules:
        schedule_id = str(uuid.uuid4())[:8]

    schedule = {"id": schedule_id, "name": name, "date": date, "items": []}
    _schedules[schedule_id] = schedule
    _save()
    return schedule


def update_schedule(schedule_id: str, name: str = None, date: str = None) -> dict | None:
    schedule = _schedules.get(schedule_id)
    if not schedule:
        return None
    if name is not None:
        schedule["name"] = name
    if date is not None:
        schedule["date"] = date
    _save()
    return schedule


def delete_schedule(schedule_id: str) -> bool:
    if schedule_id in _schedules:
        del _schedules[schedule_id]
        _save()
        return True
    return False


def add_item(schedule_id: str, item: dict) -> dict | None:
    """Append a new item to a schedule's item list. Returns the updated schedule, or None if not found."""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        return None

    item_id = str(uuid.uuid4())[:8]
    new_item = {"id": item_id, **item}
    schedule.setdefault("items", []).append(new_item)
    _save()
    return schedule


def update_item(schedule_id: str, item_id: str, fields: dict) -> dict | None:
    """Update fields on an existing item. Returns the updated schedule, or None if schedule/item not found."""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        return None

    for item in schedule.get("items", []):
        if item.get("id") == item_id:
            item.update({k: v for k, v in fields.items() if v is not None})
            _save()
            return schedule

    return None


def delete_item(schedule_id: str, item_id: str) -> dict | None:
    schedule = _schedules.get(schedule_id)
    if not schedule:
        return None

    items = schedule.get("items", [])
    filtered = [i for i in items if i.get("id") != item_id]
    if len(filtered) == len(items):
        return None  # item not found

    schedule["items"] = filtered
    _save()
    return schedule


def reorder_items(schedule_id: str, item_ids: list) -> dict | None:
    """Reorder a schedule's items to match the given list of item ids.
    Any existing items whose id isn't in item_ids are dropped; unknown ids are ignored."""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        return None

    by_id = {i.get("id"): i for i in schedule.get("items", [])}
    reordered = [by_id[iid] for iid in item_ids if iid in by_id]
    schedule["items"] = reordered
    _save()
    return schedule


def import_schedules(data: dict) -> int:
    """Merge schedules from a backup file into the library, overwriting by id. Returns count imported."""
    count = 0
    for schedule_id, schedule in data.items():
        if not isinstance(schedule, dict):
            continue
        _schedules[schedule_id] = schedule
        count += 1
    if count:
        _save()
    return count
