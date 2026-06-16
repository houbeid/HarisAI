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
    """
    Gère le cycle de vie de l'application.
    Tout ce qui est dans le bloc 'yield' s'exécute au démarrage.
    Tout ce qui est après le 'yield' s'exécute à l'arrêt.
    """
    settings = get_settings()

    logger.info("═" * 55)
    logger.info("  HarisAI — Démarrage du service ML")
    logger.info(f"  Opérateur : {settings.operator_name}")
    logger.info(f"  Port      : {settings.port}")
    logger.info("═" * 55)

    app.state.start_time = time.monotonic()

    # ── Étape 1 : Redis ───────────────────────
    logger.info("1/5 — Connexion Redis...")
    from infrastructure.stores.redis_store import RedisProfileStore
    redis_store = RedisProfileStore(redis_url=settings.redis_url)
    try:
        await redis_store.connect()
        logger.info("    ✅ Redis connecté")
    except Exception as e:
        logger.warning(f"    ⚠ Redis indisponible : {e} — profils vides utilisés")
        from infrastructure.stores.redis_store import InMemoryProfileStore
        redis_store = InMemoryProfileStore()

    # ── Étape 2 : PostgreSQL ──────────────────
    logger.info("2/5 — Connexion PostgreSQL...")
    from infrastructure.stores.postgres_store import PostgresAuditStore, InMemoryAuditStore
    audit_store = PostgresAuditStore(database_url=settings.database_url)
    try:
        await audit_store.connect()
        logger.info("    ✅ PostgreSQL connecté")
    except Exception as e:
        logger.warning(f"    ⚠ PostgreSQL indisponible : {e} — audit en mémoire")
        audit_store = InMemoryAuditStore()

    # ── Étape 3 : Modèle XGBoost ─────────────
    logger.info("3/5 — Chargement modèle XGBoost...")
    from infrastructure.ml.models.xgboost_model import XGBoostModel
    xgboost_model = XGBoostModel(version=settings.model_version)
    try:
        await xgboost_model.load(settings.model_path)
        logger.info(
            f"    ✅ XGBoost v{settings.model_version} chargé"
        )
    except Exception as e:
        logger.error(f"    ❌ Modèle introuvable : {e}")
        logger.error(f"    → Lance d'abord : python training/train_xgboost.py")

    app.state.xgboost_model = xgboost_model

    # ── Étape 4 : Modèles complémentaires ─────
    logger.info("4/5 — Initialisation modèles complémentaires...")

    # Isolation Forest — mock en attendant l'implémentation
    from application.ports import IFraudModel
    from domain import ClientProfile, Transaction

    class PassThroughModel(IFraudModel):
        """
        Modèle placeholder pour IsoForest, TFT, GNN.
        Retourne 0.0 tant que les vrais modèles ne sont pas entraînés.
        Sera remplacé par les vraies implémentations en phase 2.
        """
        def __init__(self, name: str):
            self._name = name

        @property
        def model_name(self): return self._name
        @property
        def model_version(self): return "placeholder"
        async def is_ready(self): return True
        async def load(self, path): pass
        async def predict(self, tx, profile, features): return 0.0

    isolation_model = PassThroughModel("isolation_forest")
    tft_model       = PassThroughModel("tft_aml")
    gnn_model       = PassThroughModel("gnn_network")
    logger.info("    ✅ Modèles complémentaires initialisés (placeholders)")

    # ── Étape 5 : ShapExplainer + Use Case ────
    logger.info("5/5 — Construction du pipeline...")
    from infrastructure.ml.explainer.shap_explainer import ShapExplainer
    from infrastructure.ml.features.feature_engineering import FeatureEngineering
    from application.use_cases import AnalyzeTransactionUseCase

    explainer = ShapExplainer()
    if await xgboost_model.is_ready():
        explainer.initialize(xgboost_model._model)
        logger.info("    ✅ ShapExplainer initialisé")
    else:
        logger.warning("    ⚠ ShapExplainer en mode fallback")

    # Construction du use case avec toutes ses dépendances
    use_case = AnalyzeTransactionUseCase(
        xgboost_model=xgboost_model,
        isolation_model=isolation_model,
        tft_model=tft_model,
        gnn_model=gnn_model,
        profile_store=redis_store,
        explainer=explainer,
        audit_store=audit_store,
    )

    # Stocke dans l'état de l'app — accessible dans routes.py
    app.state.use_case = use_case

    logger.info("═" * 55)
    logger.info("  ✅ HarisAI prêt — en attente de transactions")
    logger.info(f"  Docs API : http://localhost:{settings.port}/docs")
    logger.info("═" * 55)

    # ── L'app tourne ──────────────────────────
    yield

    # ── Arrêt propre ──────────────────────────
    logger.info("Arrêt du service HarisAI...")
    if hasattr(redis_store, 'disconnect'):
        await redis_store.disconnect()
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

# ── CORS — autorise les requêtes de .NET ──────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production : ["http://localhost:5000"]
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