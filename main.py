import os
import json
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv
from bible_loader import load_bibles, lookup, available_translations, get_all_verses, get_next_reference, get_prev_reference
from song_loader import load_songs, list_songs, search_songs, get_song, create_song, update_song, delete_song
from theme_loader import (load_themes, list_themes, get_theme, get_default_theme,
                           create_theme, update_theme, delete_theme, save_uploaded_image)
from fastapi import File, UploadFile, Form
from verse_embeddings import build_or_load_index, semantic_search, is_index_ready

load_dotenv()

latest_detection: dict = {}
live_slide: dict = {}  # what's currently shown on the full-screen /live output

# ── Reference call pattern ────────────────────────────────────────────────────
# Matches phrases like:
#   "let's have John 3:16"
#   "turn to Romans 8:28"
#   "John 3 verse 16"        <- spoken, no colon
#   "John 3, verse 16"       <- spoken with comma
#   "John chapter 3 verse 16"<- fully spoken
#   "1 Cor 13:4"             <- abbreviation
#   "let's go to 1 Corinthians 13:4-6"  <- verse range

CALL_TRIGGERS = r"""
    (?:
        (?:let[''']?s\s+(?:have|read|look\s+at|go\s+to|open\s+to|check\s+out))|
        (?:turn\s+to)|
        (?:open\s+to)|
        (?:read)|
        (?:go\s+to)|
        (?:look\s+at)|
        (?:check\s+out)|
        (?:see)
    )\s+
"""

# ── Book name canonicalization ────────────────────────────────────────────────
# Maps every recognized abbreviation (and the full name itself) to the exact
# canonical title used as the book name in the Bible JSON files.
BOOK_ABBREVIATIONS = {
    "Genesis":          ["Gen", "Ge", "Gn"],
    "Exodus":           ["Exod", "Exo", "Ex"],
    "Leviticus":        ["Lev", "Le", "Lv"],
    "Numbers":          ["Num", "Nu", "Nm", "Nb"],
    "Deuteronomy":      ["Deut", "De", "Dt"],
    "Joshua":           ["Josh", "Jos", "Jsh"],
    "Judges":           ["Judg", "Jdg", "Jg", "Jdgs"],
    "Ruth":             ["Rth", "Ru"],
    "1 Samuel":         ["1 Sam", "1Sa", "1S", "I Sam", "1st Samuel", "1Samuel"],
    "2 Samuel":         ["2 Sam", "2Sa", "2S", "II Sam", "2nd Samuel", "2Samuel"],
    "1 Kings":          ["1 Kgs", "1K", "I Kgs", "1st Kings", "1Kings"],
    "2 Kings":          ["2 Kgs", "2K", "II Kgs", "2nd Kings", "2Kings"],
    "1 Chronicles":     ["1 Chron", "1 Chr", "1Ch", "I Chron", "1st Chronicles", "1Chronicles"],
    "2 Chronicles":     ["2 Chron", "2 Chr", "2Ch", "II Chron", "2nd Chronicles", "2Chronicles"],
    "Ezra":             ["Ezr"],
    "Nehemiah":         ["Neh", "Ne"],
    "Esther":           ["Esth", "Est"],
    "Job":              ["Jb"],
    "Psalms":           ["Ps", "Psalm", "Pslm", "Psa", "Psm", "Pss"],
    "Proverbs":         ["Prov", "Pro", "Prv", "Pr"],
    "Ecclesiastes":     ["Eccles", "Eccle", "Ecc", "Ec", "Qoh"],
    "Song Of Solomon":  ["Song", "SOS", "Canticles", "Song Of Songs"],
    "Isaiah":           ["Isa", "Is"],
    "Jeremiah":         ["Jer", "Je", "Jr"],
    "Lamentations":     ["Lam", "La"],
    "Ezekiel":          ["Ezek", "Eze", "Ezk"],
    "Daniel":           ["Dan", "Da", "Dn"],
    "Hosea":            ["Hos", "Ho"],
    "Joel":             ["Jl"],
    "Amos":             ["Am"],
    "Obadiah":          ["Obad", "Ob"],
    "Jonah":            ["Jnh", "Jon"],
    "Micah":            ["Mic", "Mc"],
    "Nahum":            ["Nah", "Na"],
    "Habakkuk":         ["Hab", "Hb"],
    "Zephaniah":        ["Zeph", "Zep", "Zp"],
    "Haggai":           ["Hag", "Hg"],
    "Zechariah":        ["Zech", "Zec", "Zc"],
    "Malachi":          ["Mal", "Ml"],
    "Matthew":          ["Matt", "Mt"],
    "Mark":             ["Mrk", "Mk", "Mr"],
    "Luke":             ["Luk", "Lk"],
    "John":             ["Jn", "Jhn"],
    "Acts":             ["Act"],
    "Romans":           ["Rom", "Ro", "Rm"],
    "1 Corinthians":    ["1 Cor", "1Co", "I Cor", "1st Corinthians", "1Corinthians"],
    "2 Corinthians":    ["2 Cor", "2Co", "II Cor", "2nd Corinthians", "2Corinthians"],
    "Galatians":        ["Gal", "Ga"],
    "Ephesians":        ["Eph", "Ephes"],
    "Philippians":      ["Phil", "Php", "Pp"],
    "Colossians":       ["Col", "Co"],
    "1 Thessalonians":  ["1 Thess", "1 Thes", "1Th", "I Thess", "1st Thessalonians", "1Thessalonians"],
    "2 Thessalonians":  ["2 Thess", "2 Thes", "2Th", "II Thess", "2nd Thessalonians", "2Thessalonians"],
    "1 Timothy":        ["1 Tim", "1Ti", "I Tim", "1st Timothy", "1Timothy"],
    "2 Timothy":        ["2 Tim", "2Ti", "II Tim", "2nd Timothy", "2Timothy"],
    "Titus":            ["Tit", "Ti"],
    "Philemon":         ["Philem", "Phm", "Pm"],
    "Hebrews":          ["Heb"],
    "James":            ["Jas", "Jm"],
    "1 Peter":          ["1 Pet", "1Pe", "I Pet", "1st Peter", "1Peter"],
    "2 Peter":          ["2 Pet", "2Pe", "II Pet", "2nd Peter", "2Peter"],
    "1 John":           ["1 Jn", "1Jo", "I John", "1st John", "1John"],
    "2 John":           ["2 Jn", "2Jo", "II John", "2nd John", "2John"],
    "3 John":           ["3 Jn", "3Jo", "III John", "3rd John", "3John"],
    "Jude":             ["Jud", "Jd"],
    "Revelation":       ["Rev", "Re", "Revelations"],
}

# Build reverse lookup: any recognized spelling (lowercased) -> canonical name.
# Includes the canonical full names themselves so "Genesis" maps to itself.
_BOOK_LOOKUP = {}
for _canonical, _abbrevs in BOOK_ABBREVIATIONS.items():
    _BOOK_LOOKUP[_canonical.lower()] = _canonical
    for _a in _abbrevs:
        _BOOK_LOOKUP[_a.lower()] = _canonical

# Regex alternation of every recognized book term, longest first so e.g.
# "Corinthians" isn't cut short by a shorter overlapping alternative.
_ALL_BOOK_TERMS = sorted(_BOOK_LOOKUP.keys(), key=len, reverse=True)
BOOK_PATTERN = "(?:" + "|".join(re.escape(t) for t in _ALL_BOOK_TERMS) + r")\.?"


def canonicalize_book(raw: str) -> str:
    """Map any typed/spoken book spelling to its canonical JSON key name."""
    key = re.sub(r"\s+", " ", raw.strip().rstrip(".")).lower()
    return _BOOK_LOOKUP.get(key, raw.strip().title())


# Speech-to-text renders "First Corinthians" as the literal word "First",
# not the numeral "1" — but our abbreviation map only recognizes numeral
# forms (1/1st/I Corinthians). Convert spoken ordinals to numerals first
# so "First", "Second", "Third" resolve correctly before book matching.
_ORDINAL_WORDS = {
    r"\bfirst\b":  "1",
    r"\bsecond\b": "2",
    r"\bthird\b":  "3",
}


def _normalize_ordinal_words(text: str) -> str:
    for pattern, replacement in _ORDINAL_WORDS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


# Speech-to-text renders chapter/verse numbers as words ("verse one",
# "chapter thirteen") rather than digits. Convert spelled-out cardinal
# numbers (covering the full realistic range of chapters/verses, up to
# Psalm 119's 176 verses) into digits before matching.
_NUM_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_NUM_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_NUMBER_WORD_RUN = re.compile(
    r"\b(?:(?:" + "|".join(
        list(_NUM_UNITS.keys()) + list(_NUM_TENS.keys()) + ["hundred", "and"]
    ) + r")\s*)+\b",
    re.IGNORECASE
)


def _words_to_int(words: list) -> int:
    """Parse a run of number words (e.g. ['one','hundred','seventy','six']) into an int."""
    total, current, matched_any = 0, 0, False
    for w in words:
        w = w.lower()
        if w == "and":
            continue
        if w in _NUM_UNITS:
            current += _NUM_UNITS[w]
            matched_any = True
        elif w in _NUM_TENS:
            current += _NUM_TENS[w]
            matched_any = True
        elif w == "hundred":
            current = (current or 1) * 100
            matched_any = True
    return current if matched_any else None


def _normalize_spelled_numbers(text: str) -> str:
    def repl(m):
        words = m.group(0).split()
        value = _words_to_int(words)
        return str(value) if value is not None else m.group(0)
    return _NUMBER_WORD_RUN.sub(repl, text)


# Matches: Book [chapter] N [,:]? [verse(s)] N [- N]
# Handles both typed ("John 3:16") and spoken ("John 3, verse 16",
# "John chapter 3 verse 16-18") formats in one pattern.
#
# Chapter/verse digits use an atomic lookahead+backreference pattern
# (?=(\d+))\1 instead of a plain (\d+). A plain \d+ can backtrack into
# consuming FEWER digits if the rest of the pattern fails to match later
# (e.g. "13 verse one" — since "one" isn't a digit, a plain \d+ would
# backtrack "13" down to "1", then wrongly treat the leftover "3" as the
# verse number, silently producing "Chapter 1:3" instead of failing).
# The atomic form locks in the full digit run so that kind of wrong,
# confidently-incorrect split can never happen — the match just fails
# cleanly instead, which is what we want when the input isn't understood.
REFERENCE_PATTERN = re.compile(
    rf"""
    (?:{CALL_TRIGGERS})?              # optional trigger phrase
    ({BOOK_PATTERN})                  # group 1: book name / abbreviation
    \s+
    (?:chapter\s+)?                   # optional "chapter"
    (?=(\d+))\2                       # group 2: chapter number (atomic — no backtracking)
    \s*[,:]?\s*                       # optional comma or colon separator
    (?:verses?\s+)?                   # optional "verse"/"verses"
    (?=(\d+))\3                       # group 3: verse number (atomic — no backtracking)
    (?:\s*-\s*(?=(\d+))\4)?           # group 4: optional range end (atomic)
    """,
    re.IGNORECASE | re.VERBOSE
)


def extract_direct_reference(text: str):
    """
    Check if the text contains an explicit scripture reference call —
    typed ("John 3:16"), spoken ("John 3, verse 16"), spoken with ordinal
    book prefixes ("First Corinthians 13:4"), or spoken with spelled-out
    numbers ("First Corinthians thirteen, verse one").
    Returns (reference_string, detected_phrase) or (None, None).
    """
    normalized_text = _normalize_ordinal_words(text)
    normalized_text = _normalize_spelled_numbers(normalized_text)

    match = REFERENCE_PATTERN.search(normalized_text)
    if not match:
        return None, None

    book_raw = match.group(1)
    chapter = match.group(2)
    verse_start = match.group(3)
    verse_end = match.group(4)

    book = canonicalize_book(book_raw)

    if verse_end:
        ref = f"{book} {chapter}:{verse_start}-{verse_end}"
    else:
        ref = f"{book} {chapter}:{verse_start}"

    return ref, match.group(0).strip()



@asynccontextmanager
async def lifespan(app: FastAPI):
    load_bibles()
    load_songs()
    load_themes()

    # Build/load local semantic search index from KJV verses.
    # This replaces most Groq calls with an instant local lookup.
    kjv_verses = get_all_verses("kjv")
    if kjv_verses:
        build_or_load_index(kjv_verses)
    else:
        print("[Embeddings] WARNING: KJV not loaded — local semantic search disabled, "
              "falling back to Groq for all detections")
    for t in available_translations():
        verses = get_all_verses(t)
        if verses:
            sample_key = list(verses.keys())[0]
            sample_val = list(verses.values())[0]
            print(f"  [{t.upper()}] sample key: '{sample_key}' → '{str(sample_val)[:60]}'")
    yield


app = FastAPI(title="Scripture Detector", lifespan=lifespan)

# Serve style.css and app.js as static files
BASE_DIR = os.path.dirname(__file__)
os.makedirs(os.path.join(BASE_DIR, "theme_uploads"), exist_ok=True)
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")
app.mount("/theme-images", StaticFiles(directory=os.path.join(BASE_DIR, "theme_uploads")), name="theme-images")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SYSTEM_PROMPT = """You are a Bible scripture reference detector.

Analyze the given text and identify ALL Bible references — including:
1. DIRECT QUOTES: Verbatim or near-verbatim scripture
2. PARAPHRASE: Reworded scripture with the same meaning
3. SEMANTIC ALLUSION: Language or themes that echo a scripture
4. STORY REFERENCE: References to biblical stories, events, or characters

Respond ONLY with valid JSON (no markdown, no preamble, no explanation):
{
  "detections": [
    {
      "type": "direct_quote" | "paraphrase" | "semantic_allusion" | "story_reference",
      "reference": "Book Chapter:Verse",
      "detected_phrase": "The exact phrase from the input that triggered this",
      "confidence": "high" | "medium" | "low",
      "explanation": "Brief explanation of why this matches"
    }
  ],
  "summary": "1-2 sentence summary of spiritual themes detected"
}

Rules:
- "reference" must be exact format: "Book Chapter:Verse" e.g. "John 3:16", "1 Corinthians 13:4"
- Do NOT include verse text — only the reference
- If nothing found: {"detections": [], "summary": "No specific scripture references detected."}
- Return ONLY the JSON object, nothing else"""

TRANSLATIONS = ["kjv", "niv", "nkjv", "nlt", "amp"]


def build_translation_lookup(ref: str) -> dict:
    """Look up a reference across all translations."""
    result = {}
    for t in TRANSLATIONS:
        # Handle verse ranges e.g. John 3:16-17 — look up each verse
        range_match = re.match(r'^(.*?\d+):(\d+)-(\d+)$', ref)
        if range_match:
            base = range_match.group(1)
            start = int(range_match.group(2))
            end = int(range_match.group(3))
            verses = []
            for v in range(start, end + 1):
                text = lookup(f"{base}:{v}", t)
                if text:
                    verses.append(text)
            if verses:
                result[t.upper()] = ' '.join(verses)
        else:
            text = lookup(ref, t)
            if text:
                result[t.upper()] = text
    return result


def push_to_overlay(detection: dict):
    global latest_detection
    trans = detection.get("translations", {})
    display_text = trans.get("KJV") or next(iter(trans.values()), "")
    latest_detection = {
        "reference": detection.get("reference", ""),
        "type": detection.get("type", ""),
        "text": display_text,
        "translation": "KJV" if "KJV" in trans else next(iter(trans.keys()), ""),
    }


class DetectRequest(BaseModel):
    text: str
    min_confidence: str = "medium"  # "high", "medium", or "low"


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(BASE_DIR, "index.html")) as f:
        return f.read()

@app.get("/style.css")
async def styles():
    response = FileResponse(os.path.join(BASE_DIR, "style.css"), media_type="text/css")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

@app.get("/app.js")
async def scripts():
    response = FileResponse(os.path.join(BASE_DIR, "app.js"), media_type="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/overlay", response_class=HTMLResponse)
async def overlay():
    with open(os.path.join(os.path.dirname(__file__), "overlay.html")) as f:
        return f.read()


@app.get("/live", response_class=HTMLResponse)
async def live_page():
    with open(os.path.join(os.path.dirname(__file__), "live.html")) as f:
        return f.read()


@app.get("/live/current")
async def live_current():
    return live_slide


class SendLiveRequest(BaseModel):
    reference: str
    text: str
    translation: str = "KJV"
    theme_id: str = "default_black"
    kind: str = "scripture"           # 'scripture' | 'song'
    song_id: str = ""                 # populated when kind == 'song'
    section_index: int = 0            # populated when kind == 'song'


@app.post("/live/send")
async def live_send(req: SendLiveRequest):
    global live_slide
    theme = get_theme(req.theme_id) or get_default_theme()

    live_slide = {
        "reference": req.reference,
        "text": req.text,
        "translation": req.translation,
        "visible": True,
        "theme": theme,
        "kind": req.kind,
        "song_id": req.song_id,
        "section_index": req.section_index,
    }
    return {"status": "sent", "slide": live_slide}


@app.post("/live/clear")
async def live_clear():
    global live_slide
    live_slide = {}
    return {"status": "cleared"}


@app.get("/live/next-preview")
async def live_next_preview():
    """
    Compute what the NEXT slide would be, without changing live state.
    Powers the confidence monitor's "up next" panel.
    """
    if not live_slide or not live_slide.get("visible"):
        return {}

    kind = live_slide.get("kind", "scripture")

    if kind == "scripture":
        ref = live_slide.get("reference", "")
        translation = live_slide.get("translation", "KJV").lower()
        next_ref = get_next_reference(ref, translation)
        if not next_ref:
            return {}
        translations = build_translation_lookup(next_ref)
        text = translations.get(translation.upper(), next(iter(translations.values()), ""))
        return {"reference": next_ref, "text": text, "kind": "scripture"}

    elif kind == "song":
        song_id = live_slide.get("song_id", "")
        section_index = live_slide.get("section_index", 0)
        song = get_song(song_id)
        if not song:
            return {}
        next_index = section_index + 1
        if next_index >= len(song.get("sections", [])):
            return {}
        sec = song["sections"][next_index]
        return {
            "reference": f"{song['title']} — {sec['label']}",
            "text": "\n".join(sec["lines"]),
            "kind": "song"
        }

    return {}


@app.get("/search")
async def manual_search(ref: str, translation: str = "kjv"):
    """
    Direct manual lookup — operator types OR speaks a reference (same natural
    phrasing the live detector understands), gets instant result from local
    JSON with ALL 5 translations included, no Groq call needed.
    """
    normalized_ref = ref.strip()
    direct_ref, _ = extract_direct_reference(normalized_ref)
    final_ref = direct_ref if direct_ref else normalized_ref
    translations = build_translation_lookup(final_ref)
    if not translations:
        raise HTTPException(status_code=404, detail=f"Reference '{ref}' not found in any translation.")
    return {
        "reference": final_ref,
        "translations": translations
    }


@app.get("/verse-nav")
async def verse_nav(ref: str, direction: str = "next", translation: str = "kjv"):
    """
    Move to the next/previous verse from a given reference, within the same
    translation. Powers the → / ← keyboard navigation on the live output.
    """
    if direction not in ("next", "prev"):
        raise HTTPException(status_code=400, detail="direction must be 'next' or 'prev'")

    nav_fn = get_next_reference if direction == "next" else get_prev_reference
    new_ref = nav_fn(ref, translation)

    if not new_ref:
        raise HTTPException(
            status_code=404,
            detail=f"No {'next' if direction == 'next' else 'previous'} verse available."
        )

    translations = build_translation_lookup(new_ref)
    text = translations.get(translation.upper(), next(iter(translations.values()), ""))

    return {
        "reference": new_ref,
        "text": text,
        "translations": translations
    }


# ── Song Library ───────────────────────────────────────────────────────────────

class SongSection(BaseModel):
    label: str          # e.g. "Verse 1", "Chorus", "Bridge"
    lines: list[str]     # lyric lines shown together as one live slide


class SongRequest(BaseModel):
    title: str
    author: str = ""
    sections: list[SongSection]


@app.get("/songs")
async def songs_list(q: str = ""):
    """List songs, optionally filtered by search query (title/author)."""
    if q:
        return {"songs": search_songs(q)}
    return {"songs": list_songs()}


@app.get("/songs/{song_id}")
async def songs_get(song_id: str):
    song = get_song(song_id)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@app.post("/songs")
async def songs_create(req: SongRequest):
    sections = [s.dict() for s in req.sections]
    song = create_song(req.title, req.author, sections)
    return song


@app.put("/songs/{song_id}")
async def songs_update(song_id: str, req: SongRequest):
    sections = [s.dict() for s in req.sections]
    song = update_song(song_id, req.title, req.author, sections)
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@app.delete("/songs/{song_id}")
async def songs_delete(song_id: str):
    if not delete_song(song_id):
        raise HTTPException(status_code=404, detail="Song not found")
    return {"status": "deleted"}


@app.get("/overlay/latest")
async def overlay_latest():
    return latest_detection


@app.delete("/overlay/latest")
async def overlay_clear():
    global latest_detection
    latest_detection = {}
    return {"cleared": True}


@app.get("/translations")
async def get_translations():
    return {"translations": available_translations()}


@app.get("/debug/files")
async def debug_files():
    """
    Shows exactly what files Render sees in the bibles/ folder at runtime.
    Use this to diagnose missing-translation issues on deployment.
    """
    bible_dir = os.path.join(BASE_DIR, "bibles")
    if not os.path.isdir(bible_dir):
        return {"error": f"bibles/ directory not found at {bible_dir}"}

    all_files = os.listdir(bible_dir)
    json_files = [f for f in all_files if f.lower().endswith(".json")]

    return {
        "bibles_directory": bible_dir,
        "all_files_found": all_files,
        "json_files_found": json_files,
        "translations_currently_loaded": available_translations(),
        "expected_translations": ["kjv", "niv", "nkjv", "nlt", "amp"],
    }


@app.get("/debug/lookup")
async def debug_lookup(ref: str, translation: str = "kjv"):
    verses = get_all_verses(translation)
    direct_hit = lookup(ref, translation)
    close = list(verses.keys())[:20] if verses else []
    return {
        "query_ref": ref,
        "translation": translation,
        "found": direct_hit is not None,
        "verse_text": direct_hit,
        "translation_loaded": translation.lower() in available_translations(),
        "total_verses_in_translation": len(verses),
        "sample_keys_from_file": close
    }


def local_semantic_detect(text: str) -> dict | None:
    """
    Fast local nearest-neighbor search over KJV verse embeddings. Returns a
    detection dict matching Groq's output shape, or None if no match is
    confident enough (caller should fall back to Groq in that case).

    Similarity thresholds (cosine similarity, roughly calibrated for
    all-MiniLM-L6-v2 on short sermon-length phrases):
      >= 0.80  -> near-exact wording          -> direct_quote,      high
      >= 0.60  -> same meaning, reworded       -> paraphrase,        high
      >= 0.45  -> loosely related theme/echo   -> semantic_allusion, medium
      <  0.45  -> not confident -> return None, let Groq handle it
                  (covers story references like "the prodigal son",
                  which need world knowledge pure text similarity lacks)
    """
    results = semantic_search(text, top_k=1)
    if not results:
        return None

    top = results[0]
    similarity = top["similarity"]
    reference = top["reference"]

    if similarity >= 0.80:
        detection_type, confidence = "direct_quote", "high"
    elif similarity >= 0.60:
        detection_type, confidence = "paraphrase", "high"
    elif similarity >= 0.45:
        detection_type, confidence = "semantic_allusion", "medium"
    else:
        return None  # not confident — let Groq take a shot at it

    translations = build_translation_lookup(reference)
    if not translations:
        return None  # shouldn't happen since ref came from our own KJV index, but be safe

    return {
        "type": detection_type,
        "reference": reference,
        "detected_phrase": text.strip(),
        "confidence": confidence,
        "explanation": f"Matched locally via semantic similarity ({similarity:.2f}).",
        "translations": translations
    }


@app.post("/detect")
async def detect_scripture(req: DetectRequest):
    global latest_detection

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    # ── Step 1: Check for explicit reference call first (no Groq needed) ──────
    ref, phrase = extract_direct_reference(req.text)
    if ref:
        translations = build_translation_lookup(ref)
        if translations:
            detection = {
                "type": "reference_call",
                "reference": ref,
                "detected_phrase": phrase,
                "confidence": "high",
                "explanation": f"Explicit scripture reference called directly.",
                "translations": translations
            }
            push_to_overlay(detection)
            return {
                "detections": [detection],
                "summary": f"Direct reference call to {ref}.",
                "source": "local_lookup"   # tells frontend no Groq was used
            }
        # ref found but not in our JSON — fall through to local search / Groq

    # ── Step 2: Local semantic search (instant, no network call) ──────────────
    # Handles direct quotes and close paraphrases — the vast majority of real
    # sermon references — without ever touching Groq.
    if is_index_ready():
        local_result = local_semantic_detect(req.text)
        if local_result:
            push_to_overlay(local_result)
            return {
                "detections": [local_result],
                "summary": f"Detected via local semantic match: {local_result['reference']}.",
                "source": "local_embedding"   # tells frontend this was instant, no Groq
            }

    # ── Step 3: Groq fallback ──────────────────────────────────────────────────
    # Only reached when local search found no confident match — typically
    # story/allusion references that need broader world knowledge to resolve
    # (e.g. "the prodigal son" -> Luke 15), which pure text-similarity can't do.
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not configured in .env")

    client = Groq(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Detect all Bible references in this text:\n\n{req.text}"}
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"}
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq API error: {str(e)}")

    raw = response.choices[0].message.content.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Model returned invalid JSON: {raw[:200]}")

    # Filter by minimum confidence before lookup
    CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
    min_rank = CONFIDENCE_RANK.get(req.min_confidence, 2)
    result["detections"] = [
        d for d in result.get("detections", [])
        if CONFIDENCE_RANK.get(d.get("confidence", "low"), 1) >= min_rank
    ]

    # Look up verse text in ALL translations
    not_found = []
    for detection in result.get("detections", []):
        ref = detection.get("reference", "")
        detection["translations"] = build_translation_lookup(ref)
        if not detection["translations"]:
            not_found.append(ref)

    if not_found:
        result["lookup_warnings"] = f"References not found in any translation: {', '.join(not_found)}"

    # Push best detection to OBS overlay
    detections = result.get("detections", [])
    best = next(
        (d for d in detections if d.get("confidence") in ("high", "medium") and d.get("translations")),
        detections[0] if detections else None
    )
    if best:
        push_to_overlay(best)
    else:
        latest_detection = {}

    result["source"] = "groq"
    return result


# ── Themes / Backgrounds ─────────────────────────────────────────────────────

class ThemeRequest(BaseModel):
    name: str
    bg_type: str            # 'color' | 'gradient' | 'image'
    bg_value: str            # hex color, CSS gradient string, or filename
    text_color: str = "#FFFFFF"
    accent_color: str = "#C9A84C"
    overlay_opacity: float = 0.4


@app.get("/themes")
async def themes_list():
    return {"themes": list_themes()}


@app.get("/themes/{theme_id}")
async def themes_get(theme_id: str):
    theme = get_theme(theme_id)
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    return theme


@app.post("/themes")
async def themes_create(req: ThemeRequest):
    theme = create_theme(
        req.name, req.bg_type, req.bg_value,
        req.text_color, req.accent_color, req.overlay_opacity
    )
    return theme


@app.put("/themes/{theme_id}")
async def themes_update(theme_id: str, req: ThemeRequest):
    theme = update_theme(
        theme_id, name=req.name, bg_type=req.bg_type, bg_value=req.bg_value,
        text_color=req.text_color, accent_color=req.accent_color,
        overlay_opacity=req.overlay_opacity
    )
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")
    return theme


@app.delete("/themes/{theme_id}")
async def themes_delete(theme_id: str):
    if not delete_theme(theme_id):
        raise HTTPException(status_code=400, detail="Cannot delete this theme")
    return {"status": "deleted"}


@app.post("/themes/upload-image")
async def themes_upload_image(file: UploadFile = File(...)):
    """Upload a background image for use in a theme. Returns the stored filename/URL."""
    contents = await file.read()

    max_size = 8 * 1024 * 1024  # 8MB cap
    if len(contents) > max_size:
        raise HTTPException(status_code=400, detail="Image too large (max 8MB)")

    stored_name = save_uploaded_image(file.filename, contents)
    return {"filename": stored_name, "url": f"/theme-images/{stored_name}"}


# ── Confidence Monitor ────────────────────────────────────────────────────────

@app.get("/confidence", response_class=HTMLResponse)
async def confidence_page():
    with open(os.path.join(BASE_DIR, "confidence.html")) as f:
        return f.read()