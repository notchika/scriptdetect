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

load_dotenv()

latest_detection: dict = {}
live_slide: dict = {}  # what's currently shown on the full-screen /live output

# ── Reference call pattern ────────────────────────────────────────────────────
# Matches phrases like:
#   "let's have John 3:16"
#   "turn to Romans 8:28"
#   "open to Psalm 23:1"
#   "read Genesis 1:1"
#   "let's go to 1 Corinthians 13:4"
#   "John 3:16" (bare reference anywhere in text)

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

# Bible book names (full + common abbreviations)
BOOK_PATTERN = r"""
    (?:
        # Numbered books
        (?:[123]\s*(?:
            Kings?|Chronicles?|Samuel|Corinthians?|Thessalonians?|Timothy|Peter|John|
            Maccabees?|Esdras?
        ))|
        # Song of Solomon / Song of Songs
        (?:Song\s+of\s+(?:Solomon|Songs?))|
        # Regular books
        (?:
            Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|
            Nehemiah|Esther|Job|Psalms?|Proverbs?|Ecclesiastes|Isaiah|Jeremiah|
            Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|
            Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|
            Matthew|Mark|Luke|John|Acts|Romans|Galatians|Ephesians|Philippians|
            Colossians|Philemon|Hebrews|James|Jude|Revelation|Revelations|
            # Common abbreviations
            Gen|Ex|Lev|Num|Deut|Josh|Judg|Ps|Prov|Eccl|Isa|Jer|Lam|Ezek|Dan|
            Hos|Zech|Mal|Matt|Mk|Lk|Jn|Rom|Gal|Eph|Phil|Col|Thess|Tim|Heb|Jas|Rev
        )
    )
"""

REFERENCE_PATTERN = re.compile(
    rf"""
    (?:{CALL_TRIGGERS})?          # optional trigger phrase
    ({BOOK_PATTERN}\s+\d+:\d+(?:-\d+)?)  # Book Chapter:Verse or range
    """,
    re.IGNORECASE | re.VERBOSE
)


def extract_direct_reference(text: str):
    """
    Check if the text contains an explicit scripture reference call.
    Returns (reference_string, detected_phrase) or (None, None).
    """
    match = REFERENCE_PATTERN.search(text)
    if match:
        raw_ref = match.group(1).strip()
        # Normalize: title-case book, keep chapter:verse
        ref_match = re.match(r'^(.*?)\s+(\d+:\d+(?:-\d+)?)$', raw_ref.strip())
        if ref_match:
            book = ref_match.group(1).strip().title()
            cv = ref_match.group(2)
            return f"{book} {cv}", match.group(0).strip()
    return None, None


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_bibles()
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
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

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


@app.post("/live/send")
async def live_send(req: SendLiveRequest):
    global live_slide
    live_slide = {
        "reference": req.reference,
        "text": req.text,
        "translation": req.translation,
        "visible": True,
    }
    return {"status": "sent", "slide": live_slide}


@app.post("/live/clear")
async def live_clear():
    global live_slide
    live_slide = {}
    return {"status": "cleared"}


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
        # ref found but not in our JSON — fall through to Groq

    # ── Step 2: Semantic/paraphrase detection via Groq ────────────────────────
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