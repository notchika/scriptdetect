import json
import os
import re
import uuid
import shutil

_themes: dict = {}

THEMES_DIR_DEFAULT = "themes"
THEMES_FILE = "themes.json"
UPLOADS_DIR_DEFAULT = "theme_uploads"

DEFAULT_THEME = {
    "id": "default_black",
    "name": "Default (Black)",
    "bg_type": "color",       # 'color' | 'gradient' | 'image'
    "bg_value": "#000000",    # hex color, CSS gradient string, or image filename
    "text_color": "#FFFFFF",
    "accent_color": "#C9A84C",
    "overlay_opacity": 0.4,   # dark overlay over images so text stays readable
}


def _get_paths():
    base = os.path.dirname(__file__)
    themes_dir = os.path.join(base, THEMES_DIR_DEFAULT)
    uploads_dir = os.path.join(base, UPLOADS_DIR_DEFAULT)
    os.makedirs(themes_dir, exist_ok=True)
    os.makedirs(uploads_dir, exist_ok=True)
    return os.path.join(themes_dir, THEMES_FILE), uploads_dir


def load_themes():
    global _themes
    path, _ = _get_paths()

    if not os.path.exists(path):
        _themes = {DEFAULT_THEME["id"]: DEFAULT_THEME}
        _save()
        print("[Theme Loader] No themes.json found — created with default theme")
        return

    with open(path, "r", encoding="utf-8") as f:
        _themes = json.load(f)

    # Ensure default theme always exists as a fallback
    if DEFAULT_THEME["id"] not in _themes:
        _themes[DEFAULT_THEME["id"]] = DEFAULT_THEME
        _save()

    print(f"[Theme Loader] Loaded {len(_themes)} theme(s)")


def _save():
    path, _ = _get_paths()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_themes, f, indent=2, ensure_ascii=False)


def list_themes() -> list:
    return list(_themes.values())


def get_theme(theme_id: str) -> dict | None:
    return _themes.get(theme_id)


def get_default_theme() -> dict:
    return _themes.get(DEFAULT_THEME["id"], DEFAULT_THEME)


def create_theme(name: str, bg_type: str, bg_value: str, text_color: str,
                  accent_color: str, overlay_opacity: float) -> dict:
    theme_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or str(uuid.uuid4())[:8]
    base_id = theme_id
    counter = 1
    while theme_id in _themes:
        theme_id = f"{base_id}_{counter}"
        counter += 1

    theme = {
        "id": theme_id, "name": name, "bg_type": bg_type, "bg_value": bg_value,
        "text_color": text_color, "accent_color": accent_color,
        "overlay_opacity": overlay_opacity,
    }
    _themes[theme_id] = theme
    _save()
    return theme


def update_theme(theme_id: str, **fields) -> dict | None:
    if theme_id not in _themes:
        return None
    _themes[theme_id].update({k: v for k, v in fields.items() if v is not None})
    _save()
    return _themes[theme_id]


def delete_theme(theme_id: str) -> bool:
    if theme_id == DEFAULT_THEME["id"]:
        return False  # never allow deleting the fallback default
    if theme_id in _themes:
        del _themes[theme_id]
        _save()
        return True
    return False


def save_uploaded_image(filename: str, file_bytes: bytes) -> str:
    """Save an uploaded background image, return its stored filename."""
    _, uploads_dir = _get_paths()
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(uploads_dir, stored_name)
    with open(path, "wb") as f:
        f.write(file_bytes)
    return stored_name


def get_all_themes() -> dict:
    """Return the full {theme_id: theme} dict — used for backup export."""
    return _themes


def import_themes(data: dict) -> int:
    """Merge themes from a backup file into the library, overwriting by id. Returns count imported."""
    count = 0
    for theme_id, theme in data.items():
        if not isinstance(theme, dict):
            continue
        _themes[theme_id] = theme
        count += 1
    if count:
        _save()
    return count


def get_uploaded_image_bytes(filename: str) -> bytes | None:
    """Read a stored background image's raw bytes — used for backup export."""
    _, uploads_dir = _get_paths()
    path = os.path.join(uploads_dir, os.path.basename(filename))
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def restore_uploaded_image(filename: str, file_bytes: bytes):
    """Write image bytes back to their original stored filename — used by backup import
    so a restored theme's bg_value keeps pointing at a file that actually exists."""
    _, uploads_dir = _get_paths()
    path = os.path.join(uploads_dir, os.path.basename(filename))
    with open(path, "wb") as f:
        f.write(file_bytes)