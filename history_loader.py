import json
import os
import time
import uuid

_history: list = []  # newest first

HISTORY_DIR_DEFAULT = "history"
HISTORY_FILE = "history.json"
MAX_ENTRIES = 200  # cap growth — oldest entries drop off past this


def _get_path():
    base = os.path.dirname(__file__)
    hist_dir = os.path.join(base, HISTORY_DIR_DEFAULT)
    os.makedirs(hist_dir, exist_ok=True)
    return os.path.join(hist_dir, HISTORY_FILE)


def load_history():
    global _history
    path = _get_path()

    if not os.path.exists(path):
        _history = []
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
        print("[History] No history.json found — created empty log")
        return

    with open(path, "r", encoding="utf-8") as f:
        _history = json.load(f)

    print(f"[History] Loaded {len(_history)} entries")


def _save():
    path = _get_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_history, f, indent=2, ensure_ascii=False)


def add_entry(reference: str, source: str, detection_type: str = None,
              confidence: str = None, query: str = None):
    """
    source: 'detection' (came from live listening/typing auto-detect)
          | 'search'    (manually searched by the operator)
    """
    entry = {
        "id": uuid.uuid4().hex[:10],
        "timestamp": time.time(),
        "reference": reference,
        "source": source,
        "type": detection_type,
        "confidence": confidence,
        "query": query,   # original spoken/typed phrase or search text
    }
    _history.insert(0, entry)
    del _history[MAX_ENTRIES:]  # trim oldest beyond cap
    _save()
    return entry


def get_history(limit: int = 50) -> list:
    return _history[:limit]


def clear_history():
    global _history
    _history = []
    _save()