"""
Local semantic search over Bible verses using sentence embeddings.
Replaces Groq LLM calls for the common case (direct quotes, close paraphrases)
with a fast local nearest-neighbor lookup — no network round-trip needed.

At startup: loads a pre-computed embedding index from disk if present,
otherwise builds it once from the KJV verse text and caches it.
"""
import os
import json
import numpy as np

_model = None
_verse_refs = []       # parallel list: verse_refs[i] corresponds to _embeddings[i]
_embeddings = None      # numpy array, shape (num_verses, embedding_dim)

EMBEDDINGS_DIR_DEFAULT = "embeddings"
EMBEDDINGS_FILE = "verse_embeddings.npy"
REFS_FILE = "verse_refs.json"
MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[Embeddings] Loading model '{MODEL_NAME}'...")
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _get_paths():
    base = os.path.dirname(__file__)
    emb_dir = os.path.join(base, EMBEDDINGS_DIR_DEFAULT)
    os.makedirs(emb_dir, exist_ok=True)
    return os.path.join(emb_dir, EMBEDDINGS_FILE), os.path.join(emb_dir, REFS_FILE)


def build_or_load_index(verses: dict, force_rebuild: bool = False):
    """
    verses: {reference: text} dict, typically the KJV translation from bible_loader.
    Loads a cached index from disk if present, otherwise builds it (slow, one-time)
    and saves it for instant loading on future startups.
    """
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

    # Batch-encode for speed
    vectors = model.encode(texts, batch_size=64, show_progress_bar=True,
                            convert_to_numpy=True, normalize_embeddings=True)

    _verse_refs = refs
    _embeddings = vectors.astype(np.float32)

    np.save(emb_path, _embeddings)
    with open(refs_path, "w", encoding="utf-8") as f:
        json.dump(_verse_refs, f)

    print(f"[Embeddings] Index built and cached — {len(_verse_refs):,} verses, "
          f"dim {_embeddings.shape[1]}")


def semantic_search(query_text: str, top_k: int = 3) -> list:
    """
    Returns top_k matches as [{"reference": str, "similarity": float}, ...],
    sorted by similarity descending. similarity is cosine similarity in [-1, 1]
    (typically [0, 1] for normalized sentence embeddings on related text).
    """
    if _embeddings is None or not _verse_refs:
        return []

    model = _get_model()
    query_vec = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    # Cosine similarity via dot product (embeddings are pre-normalized)
    scores = _embeddings @ query_vec  # shape (num_verses,)

    top_indices = np.argpartition(scores, -top_k)[-top_k:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    return [
        {"reference": _verse_refs[i], "similarity": float(scores[i])}
        for i in top_indices
    ]


def is_index_ready() -> bool:
    return _embeddings is not None and len(_verse_refs) > 0