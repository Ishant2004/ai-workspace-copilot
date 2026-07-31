# Backend container (Phase 17).
# A small, reproducible image for the FastAPI app, deployable on Render/Koyeb's
# free tier. We use a stable Python (3.12) rather than the dev machine's 3.14,
# since all our pinned deps ship 3.12 wheels — no compiler needed.
FROM python:3.12-slim

WORKDIR /app

# onnxruntime (via FlashRank) needs libgomp at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install deps first so this layer is cached when only source changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render/Koyeb inject the port to listen on via $PORT.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
