"""
HarisAI — Main FastAPI
========================
Point d'entrée du service ML.
Initialise et connecte tous les composants au démarrage.

DÉMARRAGE :
    uvicorn main:app --host 0.0.0.0 --port 8001

    ou en développement :
    uvicorn main:app --host 0.0.0.0 --port 8001 --reload

ORDRE D'INITIALISATION :
    1. Charge la configuration (.env)
    2. Connecte Redis
    3. Connecte PostgreSQL
    4. Charge le modèle XGBoost
    5. Initialise ShapExplainer
    6. Construit le use case avec toutes ses dépendances
    7. L'app est prête à recevoir des requêtes de .NET
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from presentation.dependencies import get_settings
from presentation.routes import router
from infrastructure.ml.explainer.shap_explainer import ShapExplainer
from infrastructure.ml.features.feature_engineering import FeatureEngineering
from application.use_cases import (
    AnalyzeTransactionUseCase,
    AnalyzeTransactionInput,
)
from infrastructure.stores import (
    RedisProfileStore, InMemoryProfileStore,
    RedisBeneficiaryStore, InMemoryBeneficiaryStore,
    PredictionCache, InMemoryPredictionCache,
    RateLimiter, InMemoryRateLimiter,
)
from infrastructure.stores.transaction_queue import (
    TransactionQueue, InMemoryTransactionQueue
)
from infrastructure.stores.postgres_store import PostgresAuditStore, InMemoryAuditStore
from application.ports import IFraudModel
from domain import ClientProfile, Transaction
from infrastructure.ml.models.xgboost_model import XGBoostModel
from infrastructure.ml.models.isolation_forest import IsolationForestModel
from infrastructure.ml.models.tft_model import TFTModel
from infrastructure.ml.models.gnn_model import GNNModel
from infrastructure.federated.model_updater import ModelUpdater

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("harisai")


# ─────────────────────────────────────────────
# LIFESPAN — démarrage et arrêt
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    logger.info("═" * 55)
    logger.info("  HarisAI — Démarrage du service ML")
    logger.info(f"  Opérateur : {settings.operator_name}")
    logger.info(f"  Port      : {settings.port}")
    logger.info("═" * 55)

    app.state.start_time = time.monotonic()

    # ── Étape 1 : Redis ───────────────────────
    logger.info("1/5 — Connexion Redis...")
    redis_store = RedisProfileStore(redis_url=settings.redis_url)
    beneficiary_store = RedisBeneficiaryStore(redis_url=settings.redis_url)
    try:
        await redis_store.connect()
        await beneficiary_store.connect()
        prediction_cache  = PredictionCache(redis_client=redis_store._client)
        transaction_queue = TransactionQueue(redis_client=redis_store._client)
        rate_limiter      = RateLimiter(redis_client=redis_store._client)
        logger.info("    ✅ Redis connecté + Cache + Queue + RateLimiter activés")
    except Exception as e:
        logger.warning(f"    ⚠ Redis indisponible : {e} — mode dégradé")
        redis_store       = InMemoryProfileStore()
        beneficiary_store = InMemoryBeneficiaryStore()
        prediction_cache  = InMemoryPredictionCache()
        transaction_queue = InMemoryTransactionQueue()
        rate_limiter      = InMemoryRateLimiter()

    app.state.prediction_cache  = prediction_cache
    app.state.rate_limiter      = rate_limiter
    app.state.transaction_queue = transaction_queue

    # ── Étape 2 : PostgreSQL ──────────────────
    logger.info("2/5 — Connexion PostgreSQL...")
    audit_store = PostgresAuditStore(database_url=settings.database_url)
    try:
        await audit_store.connect()
        logger.info("    ✅ PostgreSQL connecté")
    except Exception as e:
        logger.warning(f"    ⚠ PostgreSQL indisponible : {e} — audit en mémoire")
        audit_store = InMemoryAuditStore()

    # ── Étape 3 : Modèle XGBoost ─────────────
    logger.info("3/5 — Chargement modèle XGBoost...")
    xgboost_model = XGBoostModel(version=settings.model_version)
    try:
        await xgboost_model.load(settings.model_path)
        logger.info(f"    ✅ XGBoost v{settings.model_version} chargé")
    except Exception as e:
        logger.error(f"    ❌ Modèle XGBoost introuvable : {e}")
        logger.error(f"    → Lance d'abord : python training/train_xgboost.py")

    app.state.xgboost_model = xgboost_model

    # ── Étape 4 : Modèles complémentaires ─────
    logger.info("4/5 — Chargement modèles complémentaires...")

    # ── Placeholder pour les modèles non encore entraînés ──
    class PassThroughModel(IFraudModel):
        """Retourne 0.0 tant que le vrai modèle n'est pas entraîné."""
        def __init__(self, name: str):
            self._name = name
        @property
        def model_name(self): return self._name
        @property
        def model_version(self): return "placeholder"
        async def is_ready(self): return True
        async def load(self, path): pass
        async def predict(self, tx, profile, features): return 0.0

    # ── Isolation Forest ──────────────────────
    isolation_model = IsolationForestModel(version=settings.model_version)
    try:
        await isolation_model.load(settings.isolation_forest_path)
        logger.info("    ✅ IsolationForest chargé")
    except Exception as e:
        logger.warning(f"    ⚠ IsolationForest indisponible : {e} — retourne 0.0")
        isolation_model = PassThroughModel("isolation_forest")

    # ── TFT ───────────────────────────────────
    tft_model = TFTModel(version=settings.model_version)
    try:
        await tft_model.load(settings.tft_path)
        logger.info("    ✅ TFT chargé")
    except Exception as e:
        logger.warning(f"    ⚠ TFT indisponible : {e} — retourne 0.0")
        tft_model = PassThroughModel("tft_aml")

    # ── GNN ───────────────────────────────────
    gnn_model = GNNModel(version=settings.model_version)
    try:
        await gnn_model.load(settings.gnn_path)
        logger.info("    ✅ GNN chargé")
    except Exception as e:
        logger.warning(f"    ⚠ GNN indisponible : {e} — retourne 0.0")
        gnn_model = PassThroughModel("gnn_network")

    # ── Étape 5 : ShapExplainer + Use Case ────
    logger.info("5/5 — Construction du pipeline...")

    explainer = ShapExplainer()
    if await xgboost_model.is_ready():
        explainer.initialize(xgboost_model._model)
        logger.info("    ✅ ShapExplainer initialisé")
    else:
        logger.warning("    ⚠ ShapExplainer en mode fallback")

    use_case = AnalyzeTransactionUseCase(
        xgboost_model=xgboost_model,
        isolation_model=isolation_model,
        tft_model=tft_model,
        gnn_model=gnn_model,
        profile_store=redis_store,
        explainer=explainer,
        audit_store=audit_store,
        beneficiary_store=beneficiary_store,
    )
    app.state.use_case = use_case

    # ── ModelUpdater — hot-reload sans downtime ─
    updater = ModelUpdater(
        models_dir="models/",
        use_case=use_case,
        check_interval=60,
    )
    updater.start()
    app.state.model_updater = updater

    logger.info("═" * 55)
    logger.info("  ✅ HarisAI prêt — en attente de transactions")
    logger.info(f"  Docs API : http://localhost:{settings.port}/docs")
    logger.info("═" * 55)

    # ── Démarre le worker queue ───────────────
    async def process_queued_transaction(data: dict) -> None:
        from presentation.schemas import TransactionIn
        from presentation.routes import schema_to_transaction, score_to_schema
        try:
            tx_in       = TransactionIn(**data)
            transaction = schema_to_transaction(tx_in)
            result      = await use_case.execute(
                AnalyzeTransactionInput(transaction=transaction)
            )
            response = score_to_schema(result, tx_in.transaction_id)
            await prediction_cache.set(
                tx_in.transaction_id,
                tx_in.operator,
                response.model_dump(),
            )
        except Exception as e:
            logger.error(f"Erreur worker transaction : {e}")

    transaction_queue.start_worker(
        process_fn=process_queued_transaction,
        operators=[settings.operator_name],
    )

    # ── L'app tourne ──────────────────────────
    yield

    # ── Arrêt propre ──────────────────────────
    logger.info("Arrêt du service HarisAI...")
    await transaction_queue.stop_worker()
    if hasattr(app.state, 'model_updater'):
        await app.state.model_updater.stop()
    if hasattr(redis_store, 'disconnect'):
        await redis_store.disconnect()
    if hasattr(beneficiary_store, 'disconnect'):
        await beneficiary_store.disconnect()
    if hasattr(audit_store, 'disconnect'):
        await audit_store.disconnect()
    logger.info("✅ Service arrêté proprement")


# ─────────────────────────────────────────────
# APPLICATION FASTAPI
# ─────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title="HarisAI — Détection Fraude Mobile Money",
    description="""
## HarisAI — Système de détection de fraude et AML

Développé spécifiquement pour le mobile money mauritanien (Bankily · Sedad · Masrvi).

### Endpoints
- **POST /analyze** — Analyse une transaction et retourne un score de fraude
- **GET /health** — Vérifie que le service est opérationnel
- **GET /model** — Informations sur le modèle ML actif

### Décisions
| Score | Décision | Action |
|-------|----------|--------|
| 0–39  | APPROVE  | Transaction normale |
| 40–69 | REVIEW   | Compliance officer à vérifier |
| 70–100| BLOCK    | Fraude détectée — bloquer |

### Sécurité
Toutes les requêtes nécessitent le header `X-Api-Key`.
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────
app.include_router(router, prefix="/api/v1")


# ─────────────────────────────────────────────
# ROUTE RACINE
# ─────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({
        "service":  "HarisAI Fraud Detection",
        "version":  "1.0.0",
        "status":   "running",
        "docs":     "/docs",
        "health":   "/api/v1/health",
        "analyze":  "/api/v1/analyze",
    })


# ─────────────────────────────────────────────
# LANCEMENT DIRECT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )