"""
Local semantic search over Bible verses using sentence embeddings.
Replaces Groq LLM calls for the common case (direct quotes, close paraphrases)
with a fast local nearest-neighbor lookup — no network round-trip needed.
"""
import os
import json
import numpy as np

from paths import ROOT_DIR

_model = None
_verse_refs = []
_embeddings = None

EMBEDDINGS_DIR_DEFAULT = "embeddings"
EMBEDDINGS_FILE = "verse_embeddings.npy"
REFS_FILE = "verse_refs.json"
MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[Embeddings] Loading model '{MODEL_NAME}' (ONNX backend — low memory)...")
        try:
            _model = SentenceTransformer(MODEL_NAME, backend="onnx")
        except Exception as e:
            print(f"[Embeddings] ONNX backend unavailable ({e}), falling back to default backend")
            _model = SentenceTransformer(MODEL_NAME)
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


def semantic_search(query_text: str, top_k: int = 3) -> list:
    if _embeddings is None or not _verse_refs:
        return []

    model = _get_model()
    query_vec = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]

    scores = _embeddings @ query_vec
    top_indices = np.argpartition(scores, -top_k)[-top_k:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    return [
        {"reference": _verse_refs[i], "similarity": float(scores[i])}
        for i in top_indices
    ]


def is_index_ready() -> bool:
    return _embeddings is not None and len(_verse_refs) > 0