import json
import os
import re

TRANSLATIONS = ["kjv", "amp", "nlt", "niv", "nkjv", "cjb"]

# { "kjv": {"Genesis 1:1": "In the beginning..."}, ... }
_bibles: dict = {}

# Navigation index: { translation: { book: { chapter_int: sorted [verse_int, ...] } } }
# Built once at load time so → / ← verse navigation is instant.
_verse_index: dict = {}


def load_bibles(bible_dir: str = None):
    if bible_dir is None:
        bible_dir = os.path.join(os.path.dirname(__file__), "bibles")

    if not os.path.isdir(bible_dir):
        raise FileNotFoundError(
            f"Bible directory not found: '{bible_dir}'\n"
            f"Create a 'bibles/' folder and place your JSON files there.\n"
            f"Expected: {[t + '.json' for t in TRANSLATIONS]}"
        )

    # Build a case-insensitive map of actual files in the bibles directory.
    # This matters because Windows filesystems are case-insensitive but Linux
    # (which Render runs on) is case-sensitive — a file named "KJV.json" locally
    # would silently fail to load on deployment if we only check "kjv.json".
    actual_files = {f.lower(): f for f in os.listdir(bible_dir) if f.lower().endswith(".json")}

    loaded = []
    skipped = []
    for translation in TRANSLATIONS:
        expected_name = f"{translation}.json"
        actual_name = actual_files.get(expected_name.lower())

        if not actual_name:
            skipped.append(translation.upper())
            continue

        path = os.path.join(bible_dir, actual_name)
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
    if skipped:
        print(f"[Bible Loader] WARNING — file not found for: {', '.join(skipped)} "
              f"(check filename spelling/case in bibles/ folder)")

    # Build navigation index for every loaded translation
    for t in loaded:
        _build_verse_index(t.lower())
    print(f"[Bible Loader] Navigation index built for {len(_verse_index)} translation(s)")

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


# Common book name variants across different Bible JSON sources.
# Maps a canonical form to alternate spellings — checked in order until one hits.
BOOK_VARIANTS = {
    "Psalm": ["Psalms"],
    "Psalms": ["Psalm"],
    "Song Of Solomon": ["Song Of Songs", "Songs Of Solomon"],
    "Song Of Songs": ["Song Of Solomon", "Songs Of Solomon"],
    "Revelation": ["Revelations"],
    "Revelations": ["Revelation"],
    "1 Corinthians": ["I Corinthians"],
    "2 Corinthians": ["II Corinthians"],
    "1 Kings": ["I Kings"],
    "2 Kings": ["II Kings"],
    "1 Samuel": ["I Samuel"],
    "2 Samuel": ["II Samuel"],
    "1 Chronicles": ["I Chronicles"],
    "2 Chronicles": ["II Chronicles"],
    "1 Thessalonians": ["I Thessalonians"],
    "2 Thessalonians": ["II Thessalonians"],
    "1 Timothy": ["I Timothy"],
    "2 Timothy": ["II Timothy"],
    "1 Peter": ["I Peter"],
    "2 Peter": ["II Peter"],
    "1 John": ["I John"],
    "2 John": ["II John"],
    "3 John": ["III John"],
}


def lookup(reference: str, translation: str) -> str | None:
    t = translation.lower().strip()
    if t not in _bibles:
        return None

    key = _normalize_key(reference)
    result = _bibles[t].get(key)
    if result:
        return result

    # Fallback — try alternate book name spellings (e.g. Psalm vs Psalms)
    match = re.match(r'^(.*?)\s+(\d+:\d+)$', key)
    if match:
        book, cv = match.group(1), match.group(2)
        for alt_book in BOOK_VARIANTS.get(book, []):
            alt_key = f"{alt_book} {cv}"
            result = _bibles[t].get(alt_key)
            if result:
                return result

    return None


def _build_verse_index(translation: str):
    """
    Parse every key in a translation's verse dict once and build a lookup
    structure for fast next/previous verse navigation:
        { book: { chapter_int: sorted [verse_int, ...] } }
    """
    verses = _bibles.get(translation, {})
    index = {}

    ref_pattern = re.compile(r'^(.*?)\s+(\d+):(\d+)$')

    for key in verses.keys():
        match = ref_pattern.match(key)
        if not match:
            continue
        book, chapter_str, verse_str = match.groups()
        chapter, verse = int(chapter_str), int(verse_str)

        index.setdefault(book, {}).setdefault(chapter, []).append(verse)

    # Sort verse lists for predictable next/prev traversal
    for book in index:
        for chapter in index[book]:
            index[book][chapter].sort()

    _verse_index[translation] = index


def get_next_reference(reference: str, translation: str) -> str | None:
    """
    Given 'Book Chapter:Verse', return the next verse reference in the same
    translation, crossing chapter boundaries when needed. Returns None if
    there is no next verse (end of book, or reference/translation unknown).
    """
    return _navigate(reference, translation, direction=1)


def get_prev_reference(reference: str, translation: str) -> str | None:
    """Same as get_next_reference but moves backward."""
    return _navigate(reference, translation, direction=-1)


def _navigate(reference: str, translation: str, direction: int) -> str | None:
    t = translation.lower().strip()
    index = _verse_index.get(t)
    if not index:
        return None

    key = _normalize_key(reference)
    match = re.match(r'^(.*?)\s+(\d+):(\d+)$', key)
    if not match:
        return None

    book, chapter_str, verse_str = match.groups()
    chapter, verse = int(chapter_str), int(verse_str)

    book_chapters = index.get(book)
    if not book_chapters:
        return None

    verses_in_chapter = book_chapters.get(chapter, [])

    if direction == 1:
        # Try next verse in the same chapter
        later = [v for v in verses_in_chapter if v > verse]
        if later:
            return f"{book} {chapter}:{min(later)}"
        # Cross into the next chapter that exists for this book
        later_chapters = sorted(c for c in book_chapters if c > chapter)
        if later_chapters:
            next_chapter = later_chapters[0]
            first_verse = min(book_chapters[next_chapter])
            return f"{book} {next_chapter}:{first_verse}"
        return None  # end of book

    else:
        # Try previous verse in the same chapter
        earlier = [v for v in verses_in_chapter if v < verse]
        if earlier:
            return f"{book} {chapter}:{max(earlier)}"
        # Cross into the previous chapter that exists for this book
        earlier_chapters = sorted((c for c in book_chapters if c < chapter), reverse=True)
        if earlier_chapters:
            prev_chapter = earlier_chapters[0]
            last_verse = max(book_chapters[prev_chapter])
            return f"{book} {prev_chapter}:{last_verse}"
        return None  # start of book


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