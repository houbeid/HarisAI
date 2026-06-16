"""
HarisAI — Routes FastAPI
==========================
Pont entre le monde HTTP de .NET et le domain Python.

ENDPOINTS :
    POST /analyze   → analyse une transaction · retourne score + décision
    GET  /health    → vérifie que le service ML est opérationnel
    GET  /model     → infos sur le modèle chargé

FLUX :
    .NET envoie JSON
        ↓
    TransactionIn (Pydantic valide)
        ↓
    Transaction (objet domain)
        ↓
    AnalyzeTransactionUseCase.execute()
        ↓
    ScoreOut (JSON retourné à .NET)
        ↓
    .NET décide APPROVE / REVIEW / BLOCK

SÉCURITÉ :
    - Token API dans le header X-API-Key
    - Rate limiting par opérateur
    - Toutes les requêtes loggées avec transaction_id
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from application.use_cases import (
    AnalyzeTransactionInput,
    AnalyzeTransactionUseCase,
)
from domain import (
    Channel,
    ClientProfile,
    Money,
    ShapReason,
    TokenHash,
    Transaction,
)
from presentation.schemas import (
    ErrorOut,
    HealthOut,
    ScoreOut,
    ShapReasonOut,
    TransactionIn,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────
# AUTHENTIFICATION
# ─────────────────────────────────────────────

async def verify_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
    request: Request = None,
) -> str:
    """
    Vérifie le token API dans le header X-Api-Key.
    .NET envoie ce token à chaque requête.
    """
    from presentation.dependencies import get_settings
    settings = get_settings()

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Api-Key manquant"
        )

    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token API invalide"
        )

    return x_api_key


# ─────────────────────────────────────────────
# CONVERTISSEURS domain ↔ schemas
# ─────────────────────────────────────────────

def schema_to_transaction(data: TransactionIn) -> Transaction:
    """
    Convertit TransactionIn (Pydantic) → Transaction (domain).
    C'est la traduction du monde HTTP vers le monde métier.
    """
    beneficiary_token = None
    if data.beneficiary_token:
        beneficiary_token = TokenHash(data.beneficiary_token)

    return Transaction(
        transaction_id=data.transaction_id,
        client_token=TokenHash(data.client_token),
        amount=Money(data.amount),
        timestamp=data.timestamp,
        channel=Channel(data.channel),
        zone=data.zone,
        operator=data.operator,
        device_id=data.device_id,
        sim_changed_72h=data.sim_changed_72h,
        sim_changed_at=data.sim_changed_at,
        beneficiary_token=beneficiary_token,
        beneficiary_is_merchant=data.beneficiary_is_merchant,
        agent_id=data.agent_id,
        ussd_session=data.ussd_session,
    )


def score_to_schema(result, transaction_id: str) -> ScoreOut:
    """
    Convertit AnalyzeTransactionOutput → ScoreOut (Pydantic).
    C'est la traduction du monde métier vers le monde HTTP.
    """
    score = result.fraud_score

    # Convertit les ShapReason domain → ShapReasonOut schema
    reasons = [
        ShapReasonOut(
            feature_name=r.feature_name,
            contribution=r.contribution,
            feature_value=0.0,  # valeur par défaut
            readable_fr=r.human_readable_fr,
            readable_ar=r.human_readable_ar,
        )
        for r in score.top_reasons
    ]

    return ScoreOut(
        transaction_id=transaction_id,
        score=score.score_0_100,
        decision=score.risk_level.value,
        fraud_type=score.suspected_fraud_type.value,
        alert_id=result.alert.alert_id if result.alert else None,
        xgboost_score=score.xgboost_score,
        isolation_score=score.isolation_score,
        tft_score=score.tft_score,
        gnn_score=score.gnn_score,
        reasons=reasons,
        inference_time_ms=result.total_time_ms,
        model_version=score.model_version,
    )


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@router.post(
    "/analyze",
    response_model=ScoreOut,
    summary="Analyser une transaction",
    description="""
    Reçoit une transaction depuis .NET et retourne le score de fraude.

    **Décisions possibles :**
    - `APPROVE` (score < 40) → transaction normale
    - `REVIEW`  (40 ≤ score < 70) → compliance officer à vérifier
    - `BLOCK`   (score ≥ 70) → fraude détectée → bloquer

    **Temps de réponse cible : < 200ms**
    """,
    responses={
        200: {"description": "Score calculé avec succès"},
        401: {"model": ErrorOut, "description": "Token API manquant"},
        403: {"model": ErrorOut, "description": "Token API invalide"},
        422: {"model": ErrorOut, "description": "Données invalides"},
        503: {"model": ErrorOut, "description": "Modèle ML non disponible"},
    }
)
async def analyze_transaction(
    data: TransactionIn,
    request: Request,
    _: str = Depends(verify_api_key),
) -> ScoreOut:
    """
    Pipeline complet d'analyse de fraude.

    1. Vérifie le cache Redis (cache hit → retour immédiat)
    2. Valide la transaction (Pydantic)
    3. Convertit en objet domain Transaction
    4. Appelle AnalyzeTransactionUseCase
    5. Stocke dans le cache Redis
    6. Retourne le score et la décision
    """
    start = time.monotonic()

    logger.info(
        "Requête /analyze reçue",
        extra={
            "transaction_id": data.transaction_id,
            "operator":       data.operator,
            "amount":         data.amount,
            "channel":        data.channel,
            "sim_changed":    data.sim_changed_72h,
        }
    )

    # ── Étape 1 : Vérifie le cache Redis ──────────
    # Si la transaction a déjà été analysée dans les 5 minutes
    # → retourne le résultat immédiatement sans toucher XGBoost
    cache = request.app.state.prediction_cache
    cached = await cache.get(data.transaction_id, data.operator)
    if cached:
        logger.info(
            "Cache HIT — retour immédiat",
            extra={"transaction_id": data.transaction_id}
        )
        return ScoreOut(**{k: v for k, v in cached.items() if k != "from_cache"})

    # ── Étape 2 : Vérifie que le modèle est prêt ──
    if not await request.app.state.xgboost_model.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Modèle ML non chargé — réessayez dans quelques secondes"
        )

    # ── Étape 3 : Convertit schema → domain ───────
    transaction = schema_to_transaction(data)

    # ── Étape 4 : Pipeline ML ─────────────────────
    use_case: AnalyzeTransactionUseCase = request.app.state.use_case
    try:
        result = await use_case.execute(
            AnalyzeTransactionInput(
                transaction=transaction,
                pre_computed_features=data.pre_computed_features,
            )
        )
    except Exception as e:
        logger.error(
            "Erreur pipeline ML",
            extra={
                "transaction_id": data.transaction_id,
                "error": str(e)
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur analyse : {str(e)}"
        )

    # Convertit domain → schema
    response = score_to_schema(result, data.transaction_id)

    total_ms = (time.monotonic() - start) * 1000
    logger.info(
        "Analyse terminée",
        extra={
            "transaction_id": data.transaction_id,
            "score":          response.score,
            "decision":       response.decision,
            "time_ms":        round(total_ms, 1),
        }
    )

    return response


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Health check",
    description="Vérifie que le service ML est opérationnel. Utilisé par le circuit breaker .NET."
)
async def health_check(request: Request) -> HealthOut:
    """
    Health check appelé régulièrement par .NET.
    Si ce endpoint retourne une erreur → .NET active le circuit breaker
    et laisse passer les transactions sans analyse ML.
    """
    model = request.app.state.xgboost_model
    model_ready = await model.is_ready()

    uptime = time.monotonic() - request.app.state.start_time

    return HealthOut(
        status="ok" if model_ready else "degraded",
        model_ready=model_ready,
        model_version=model.model_version if model_ready else "N/A",
        uptime_seconds=round(uptime, 1),
    )


@router.get(
    "/model",
    summary="Informations sur le modèle",
    description="Retourne les informations sur le modèle XGBoost actuellement chargé."
)
async def model_info(
    request: Request,
    _: str = Depends(verify_api_key),
) -> dict:
    """Informations sur le modèle ML actif."""
    model = request.app.state.xgboost_model

    if not await model.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Modèle non chargé"
        )

    importance = model.get_feature_importance()
    top5 = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "model_name":    model.model_name,
        "model_version": model.model_version,
        "status":        "ready",
        "top_features":  [
            {"feature": name, "importance": imp}
            for name, imp in top5
        ],
    }