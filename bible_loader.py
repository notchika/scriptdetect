import json
import os
import re

TRANSLATIONS = ["kjv", "amp", "nlt", "niv", "nkjv"]

# { "kjv": {"Genesis 1:1": "In the beginning..."}, ... }
_bibles: dict = {}


def load_bibles(bible_dir: str = None):
    if bible_dir is None:
        bible_dir = os.path.join(os.path.dirname(__file__), "bibles")

    if not os.path.isdir(bible_dir):
        raise FileNotFoundError(
            f"Bible directory not found: '{bible_dir}'\n"
            f"Create a 'bibles/' folder and place your JSON files there.\n"
            f"Expected: {[t + '.json' for t in TRANSLATIONS]}"
        )

    loaded = []
    for translation in TRANSLATIONS:
        path = os.path.join(bible_dir, f"{translation}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Detect structure: flat {"Genesis 1:1": "..."} vs nested {"Genesis": {"1": {"1": "..."}}}
            sample_key = list(data.keys())[0]
            sample_val = list(data.values())[0]

            if isinstance(sample_val, str):
                # Flat format (KJV style) — normalize keys directly
                _bibles[translation] = {
                    _normalize_key(k): _extract_text(v)
                    for k, v in data.items()
                }
            elif isinstance(sample_val, dict):
                # Nested format — flatten Book > Chapter > Verse into "Book Chapter:Verse"
                _bibles[translation] = _flatten_nested(data)
            else:
                _bibles[translation] = {}

            loaded.append(translation.upper())

    if not loaded:
        raise FileNotFoundError(f"No Bible JSON files found in '{bible_dir}'.")

    print(f"[Bible Loader] Loaded: {', '.join(loaded)} — {sum(len(v) for v in _bibles.values()):,} total verses")

    # Print a sample key from each to verify correct flattening
    for t in loaded:
        verses = _bibles[t.lower()]
        if verses:
            sample_key = list(verses.keys())[0]
            sample_val = list(verses.values())[0]
            print(f"  [{t}] sample key: '{sample_key}' → '{str(sample_val)[:60]}'")

    return loaded


def _flatten_nested(data: dict) -> dict:
    """
    Flatten nested Bible JSON structure into flat {"Book Chapter:Verse": "text"} dict.

    Handles these common nested formats:
      Format A: { "Genesis": { "1": { "1": "In the beginning..." } } }
      Format B: { "Genesis": { "1": { "1": { "text": "In the beginning..." } } } }
    """
    flat = {}
    for book, chapters in data.items():
        if not isinstance(chapters, dict):
            continue
        book_title = book.strip().title()
        for chapter, verses in chapters.items():
            if not isinstance(verses, dict):
                continue
            for verse, value in verses.items():
                key = f"{book_title} {chapter}:{verse}"
                flat[key] = _extract_text(value)
    return flat


def _extract_text(value) -> str:
    """Safely extract plain string from any verse value format."""
    if isinstance(value, str):
        return value.lstrip("#").strip()
    elif isinstance(value, dict):
        for key in ("text", "verse", "value", "t", "body", "content"):
            if key in value:
                return str(value[key]).lstrip("#").strip()
        # Fallback: join all string values
        parts = [str(v) for v in value.values() if isinstance(v, str)]
        return " ".join(parts).strip()
    elif isinstance(value, list):
        return " ".join(str(i) for i in value).strip()
    return str(value).strip()


def lookup(reference: str, translation: str) -> str | None:
    t = translation.lower().strip()
    if t not in _bibles:
        return None
    key = _normalize_key(reference)
    return _bibles[t].get(key)


def get_all_verses(translation: str) -> dict:
    """Return the full {reference: text} dict for a translation."""
    return _bibles.get(translation.lower(), {})


def available_translations() -> list[str]:
    return list(_bibles.keys())


def _normalize_key(key: str) -> str:
    """Normalize a flat reference key e.g. '# genesis 1:1' -> 'Genesis 1:1'"""
    key = key.strip().lstrip("#").strip()
    match = re.match(r"^(.*?)\s+(\d+:\d+)$", key)
    if match:
        book_part = match.group(1).strip().title()
        ref_part = match.group(2)
        return f"{book_part} {ref_part}"
    return key.title()