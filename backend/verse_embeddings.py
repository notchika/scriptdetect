"""
Local semantic search over Bible verses using sentence embeddings.
Replaces Groq LLM calls for the common case (direct quotes, close paraphrases)
with a fast local nearest-neighbor lookup — no network round-trip needed.
"""
import os
import re
import json
import numpy as np

from paths import ROOT_DIR
from bible_loader import lookup

_model = None
_verse_refs = []
_embeddings = None

EMBEDDINGS_DIR_DEFAULT = "embeddings"
EMBEDDINGS_FILE = "verse_embeddings.npy"
REFS_FILE = "verse_refs.json"
MODEL_NAME = "all-MiniLM-L6-v2"
HF_CACHE_REPO = "models--sentence-transformers--all-MiniLM-L6-v2"


def _resolve_model_source() -> str:
    """Prefer a local snapshot so offline containers never call huggingface.co."""
    explicit = os.environ.get("EMBEDDING_MODEL_PATH")
    if explicit and os.path.isdir(explicit):
        return explicit

    hf_home = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface"
    )
    snapshots = os.path.join(hf_home, "hub", HF_CACHE_REPO, "snapshots")
    if os.path.isdir(snapshots):
        candidates = [
            os.path.join(snapshots, name)
            for name in os.listdir(snapshots)
            if os.path.isdir(os.path.join(snapshots, name))
            and os.path.exists(os.path.join(snapshots, name, "onnx", "model.onnx"))
        ]
        if candidates:
            return sorted(candidates)[-1]
    return MODEL_NAME


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        source = _resolve_model_source()
        print(f"[Embeddings] Loading model '{source}' (ONNX backend — low memory)...")
        try:
            _model = SentenceTransformer(
                source,
                backend="onnx",
                model_kwargs={"file_name": "onnx/model.onnx"},
            )
        except Exception as e:
            if os.environ.get("HF_HUB_OFFLINE") == "1":
                raise
            print(f"[Embeddings] ONNX backend unavailable ({e}), falling back to default backend")
            _model = SentenceTransformer(source)
    return _model


def _get_paths():
    emb_dir = os.path.join(ROOT_DIR, EMBEDDINGS_DIR_DEFAULT)
    os.makedirs(emb_dir, exist_ok=True)
    return os.path.join(emb_dir, EMBEDDINGS_FILE), os.path.join(emb_dir, REFS_FILE)


def build_or_load_index(verses: dict, force_rebuild: bool = False):
    global _verse_refs, _embeddings
    emb_path, refs_path = _get_paths()

    if not force_rebuild and os.path.exists(emb_path) and os.path.exists(refs_path):
        _embeddings = np.load(emb_path)
        with open(refs_path, "r", encoding="utf-8") as f:
            _verse_refs = json.load(f)
        print(f"[Embeddings] Loaded cached index — {len(_verse_refs):,} verses, "
              f"dim {_embeddings.shape[1]}")
        return

    print(f"[Embeddings] No cached index found — building from {len(verses):,} verses "
          f"(one-time, may take a few minutes)...")

    model = _get_model()
    refs = list(verses.keys())
    texts = list(verses.values())

    vectors = model.encode(texts, batch_size=64, show_progress_bar=True,
                            convert_to_numpy=True, normalize_embeddings=True)

    _verse_refs = refs
    _embeddings = vectors.astype(np.float32)

    np.save(emb_path, _embeddings)
    with open(refs_path, "w", encoding="utf-8") as f:
        json.dump(_verse_refs, f)

    print(f"[Embeddings] Index built and cached — {len(_verse_refs):,} verses, "
          f"dim {_embeddings.shape[1]}")


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "even",
    "for", "from", "he", "her", "him", "his", "i", "if", "in", "into", "is",
    "it", "its", "me", "my", "not", "of", "on", "or", "our", "shall", "she",
    "so", "that", "the", "their", "them", "then", "there", "they", "this",
    "those", "though", "to", "unto", "was", "we", "when", "which", "who",
    "whom", "will", "with", "ye", "yea", "you", "your", "thou", "thee",
    "thy", "thine", "hath", "hast", "art", "did", "does", "do", "am",
}

_TOKEN_RE = re.compile(r"[a-z']+")


def _lexical_tokens(text: str) -> list[str]:
    return [
        tok for tok in _TOKEN_RE.findall(text.lower())
        if tok not in _STOPWORDS and len(tok) > 2
    ]


def _overlap_score(query_tokens: list[str], verse_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0
    qset, vset = set(query_tokens), set(verse_tokens)
    return len(qset & vset) / len(qset)


def _order_score(query_tokens: list[str], verse_tokens: list[str]) -> float:
    if len(query_tokens) < 2 or len(verse_tokens) < 2:
        return 0.0
    verse_bigrams = set(zip(verse_tokens, verse_tokens[1:]))
    query_bigrams = list(zip(query_tokens, query_tokens[1:]))
    if not query_bigrams:
        return 0.0
    hits = sum(1 for bg in query_bigrams if bg in verse_bigrams)
    return hits / len(query_bigrams)


def _rerank(query_text: str, candidates: list[dict]) -> list[dict]:
    """Blend cosine similarity with lexical overlap so paraphrases land on the
    verse that actually shares distinctive words (Psalm 23 vs Job 23)."""
    query_tokens = _lexical_tokens(query_text)
    scored = []
    for cand in candidates:
        verse_text = lookup(cand["reference"], "kjv") or ""
        verse_tokens = _lexical_tokens(verse_text)
        overlap = _overlap_score(query_tokens, verse_tokens)
        order = _order_score(query_tokens, verse_tokens)
        combined = (
            0.55 * cand["similarity"]
            + 0.35 * overlap
            + 0.10 * order
        )
        scored.append({
            **cand,
            "overlap": overlap,
            "order": order,
            "combined": combined,
            "text": verse_text,
        })
    scored.sort(key=lambda row: (row["combined"], row["similarity"]), reverse=True)
    return scored


def semantic_search(query_text: str, top_k: int = 3, pool_size: int = 12) -> list:
    if _embeddings is None or not _verse_refs:
        return []

    model = _get_model()
    query_vec = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    pool = max(top_k, pool_size)
    pool = min(pool, len(_verse_refs))
    scores = _embeddings @ query_vec
    top_indices = np.argpartition(scores, -pool)[-pool:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    candidates = [
        {"reference": _verse_refs[i], "similarity": float(scores[i])}
        for i in top_indices
    ]
    return _rerank(query_text, candidates)[:top_k]


def is_index_ready() -> bool:
    return _embeddings is not None and len(_verse_refs) > 0