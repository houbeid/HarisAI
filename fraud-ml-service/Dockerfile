# ═══════════════════════════════════════════════════
# HarisAI — Dockerfile
# Service ML FastAPI + XGBoost
# ═══════════════════════════════════════════════════

# ─── Stage 1 : Builder ──────────────────────────────
# Compile les dépendances Python avec les outils C/C++
# asyncpg et shap nécessitent une compilation
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─── Stage 2 : Production ───────────────────────────
# Image finale légère sans les outils de compilation
FROM python:3.11-slim

WORKDIR /app

# Copie les packages compilés depuis le builder
COPY --from=builder /install /usr/local

# Seule dépendance runtime nécessaire pour asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ─── Code source ────────────────────────────────────
# Uniquement le code — jamais les données ni les modèles
COPY domain/           ./domain/
COPY application/      ./application/
COPY infrastructure/   ./infrastructure/
COPY presentation/     ./presentation/
COPY main.py           ./main.py

# ─── Dossiers runtime ───────────────────────────────
# models/ est monté en volume depuis le host au démarrage
RUN mkdir -p models logs

# ─── Sécurité — utilisateur non-root ────────────────
RUN useradd -m -u 1000 harisai \
    && chown -R harisai:harisai /app
USER harisai

# ─── Variables d'environnement ──────────────────────
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8001 \
    MODEL_PATH=models/xgboost_v1.0.0.pkl \
    MODEL_VERSION=1.0.0 \
    REDIS_URL=redis://redis:6379 \
    DATABASE_URL=postgresql+asyncpg://harisai:harisai@postgres/harisai \
    OPERATOR_NAME=BANKILY

# ─── Port exposé ────────────────────────────────────
EXPOSE 8001

# ─── Health check ───────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/v1/health')" \
    || exit 1

# ─── Démarrage ──────────────────────────────────────
# 4 workers = (2 × 2 CPU) + 0 — adapte selon le serveur
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4", "--log-level", "info"]