FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=UTF-8 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache

WORKDIR /app

# Large wheels are fetched on the host into docker-cache/ because pip inside
# Docker has been truncating them on this network. Torch must use the CPU
# wheel; `pip install torch` on Linux otherwise pulls CUDA (~2.5 GB).
COPY docker-cache/*.whl /tmp/wheels/
COPY requirements.txt ./
RUN mv /tmp/wheels/torch-cpu.whl \
        /tmp/wheels/torch-2.14.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl \
 && pip install --no-cache-dir \
        /tmp/wheels/torch-2.14.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl \
 && pip install --no-cache-dir --find-links /tmp/wheels \
        --default-timeout=1000 --retries 20 -r requirements.txt \
 && rm -rf /tmp/wheels

# Bake the embedding model in, so startup never depends on huggingface.co being
# reachable. Exporting it here also means the ONNX backend is genuinely used at
# runtime rather than silently falling back to torch, which costs ~250 MB more RAM.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2', backend='onnx')"

COPY bibles/ ./bibles/
COPY songs/ ./songs/
COPY themes/ ./themes/
COPY schedules/ ./schedules/
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Precompute the KJV semantic index. Without this the first boot after every
# deploy blocks for several minutes while it encodes 31k verses.
RUN python -c "import sys; sys.path.insert(0, 'backend'); \
from bible_loader import load_bibles, get_all_verses; \
from verse_embeddings import build_or_load_index; \
load_bibles(); build_or_load_index(get_all_verses('kjv'))"

# The model and index are already present; refuse to reach out to the network so a
# cache miss fails loudly instead of hanging on a download.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd --create-home --uid 10001 app \
 && mkdir -p history theme_uploads \
 && chown -R app:app /app /opt/hf-cache
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/translations\", timeout=4)"

CMD ["sh", "-c", "uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
