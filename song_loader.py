import json
import os
import re
import uuid

_songs: dict = {}  # { song_id: {id, title, author, sections: [{label, lines}]} }

SONGS_DIR_DEFAULT = "songs"
SONGS_FILE = "songs.json"


def _get_path(songs_dir: str = None) -> str:
    if songs_dir is None:
        songs_dir = os.path.join(os.path.dirname(__file__), SONGS_DIR_DEFAULT)
    os.makedirs(songs_dir, exist_ok=True)
    return os.path.join(songs_dir, SONGS_FILE)


def load_songs(songs_dir: str = None):
    """Load songs.json into memory at startup. Creates an empty one if missing."""
    global _songs
    path = _get_path(songs_dir)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
        _songs = {}
        print("[Song Loader] No songs.json found — created empty library")
        return

    with open(path, "r", encoding="utf-8") as f:
        _songs = json.load(f)

    print(f"[Song Loader] Loaded {len(_songs)} song(s)")


def _save():
    """Persist current in-memory songs dict back to disk."""
    path = _get_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_songs, f, indent=2, ensure_ascii=False)


def list_songs() -> list:
    """Return a lightweight list of {id, title, author} for the song picker."""
    return [
        {"id": sid, "title": s.get("title", ""), "author": s.get("author", "")}
        for sid, s in _songs.items()
    ]


def search_songs(query: str) -> list:
    q = query.strip().lower()
    if not q:
        return list_songs()
    return [
        {"id": sid, "title": s.get("title", ""), "author": s.get("author", "")}
        for sid, s in _songs.items()
        if q in s.get("title", "").lower() or q in s.get("author", "").lower()
    ]


def get_song(song_id: str) -> dict | None:
    return _songs.get(song_id)


def create_song(title: str, author: str, sections: list) -> dict:
    song_id = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or str(uuid.uuid4())[:8]
    # Avoid collisions
    base_id = song_id
    counter = 1
    while song_id in _songs:
        song_id = f"{base_id}_{counter}"
        counter += 1

    song = {"id": song_id, "title": title, "author": author, "sections": sections}
    _songs[song_id] = song
    _save()
    return song


def update_song(song_id: str, title: str, author: str, sections: list) -> dict | None:
    if song_id not in _songs:
        return None
    song = {"id": song_id, "title": title, "author": author, "sections": sections}
    _songs[song_id] = song
    _save()
    return song


def delete_song(song_id: str) -> bool:
    if song_id in _songs:
        del _songs[song_id]
        _save()
        return True
    return False