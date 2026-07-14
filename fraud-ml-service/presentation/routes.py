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
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

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
from infrastructure.monitoring import (
    transactions_total,
    decisions_total,
    cache_hits_total,
    cache_misses_total,
    rate_limit_rejections_total,
    errors_total,
    fraud_type_total,
    inference_duration_seconds,
    fraud_score_distribution,
    service_uptime_seconds,
    model_ready_gauge,
    queue_size_gauge,
    rate_limit_usage_gauge,
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

    # ── Métrique : transaction reçue ──────────────
    transactions_total.labels(operator=data.operator).inc()

    # ── Étape 0 : Rate limiting par opérateur ─────
    rate_limiter = request.app.state.rate_limiter
    if not await rate_limiter.check(data.operator):
        rate_limit_rejections_total.labels(operator=data.operator).inc()
        usage = await rate_limiter.get_usage(data.operator)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limite de requêtes dépassée pour {data.operator} : "
                f"{usage.get('current_count', 0)}/{usage.get('limit_per_minute', 0)} "
                f"req/min. Réessayez dans quelques secondes."
            )
        )

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
        cache_hits_total.labels(operator=data.operator).inc()
        logger.info(
            "Cache HIT — retour immédiat",
            extra={"transaction_id": data.transaction_id}
        )
        return ScoreOut(**{k: v for k, v in cached.items() if k != "from_cache"})

    cache_misses_total.labels(operator=data.operator).inc()

    # ── Étape 2 : Vérifie que le modèle est prêt ──
    if not await request.app.state.xgboost_model.is_ready():
        errors_total.labels(operator=data.operator, error_type="model_not_ready").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Modèle ML non chargé — réessayez dans quelques secondes"
        )

    # ── Étape 3 : Convertit schema → domain ───────
    transaction = schema_to_transaction(data)

    # ── Étape 4 : Pipeline ML (chronométré) ───────
    use_case: AnalyzeTransactionUseCase = request.app.state.use_case
    try:
        with inference_duration_seconds.labels(operator=data.operator).time():
            result = await use_case.execute(
                AnalyzeTransactionInput(
                    transaction=transaction,
                    pre_computed_features=data.pre_computed_features,
                )
            )
    except Exception as e:
        errors_total.labels(operator=data.operator, error_type="pipeline_error").inc()
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

    # ── Étape 5 : Convertit domain → schema ──────
    response = score_to_schema(result, data.transaction_id)

    # ── Métriques : décision + score + type de fraude ─
    decisions_total.labels(
        operator=data.operator,
        decision=response.decision,
    ).inc()
    fraud_score_distribution.labels(operator=data.operator).observe(response.score)
    if result.fraud_score.is_fraud:
        fraud_type_total.labels(
            operator=data.operator,
            fraud_type=result.fraud_score.suspected_fraud_type.value,
        ).inc()

    # ── Étape 6 : Stocke dans le cache Redis ──────
    # Les prochains retries de .NET retourneront le cache
    await cache.set(
        data.transaction_id,
        data.operator,
        response.model_dump(),
    )

    total_ms = (time.monotonic() - start) * 1000
    logger.info(
        "Analyse terminée",
        extra={
            "transaction_id": data.transaction_id,
            "score":          response.score,
            "decision":       response.decision,
            "time_ms":        round(total_ms, 1),
            "cached":         True,
        }
    )

    return response


@router.post(
    "/analyze-async",
    status_code=202,
    summary="Analyser une transaction (mode asynchrone)",
    description="""
    Mode asynchrone — retourne immédiatement 202 Accepted.
    Utiliser quand le serveur est sous forte charge.

    **Flux :**
    1. POST /analyze-async → 202 Accepted (< 1ms)
    2. Transaction mise en queue Redis
    3. Worker traite en arrière-plan
    4. GET /result/{transaction_id} → récupère le résultat
    """,
)
async def analyze_transaction_async(
    data: TransactionIn,
    request: Request,
    _: str = Depends(verify_api_key),
) -> dict:
    """
    Pousse la transaction dans la queue Redis et retourne immédiatement.
    Le résultat sera disponible via GET /result/{transaction_id}.
    """
    queue = request.app.state.transaction_queue

    # ── Rate limiting par opérateur ───────────────
    rate_limiter = request.app.state.rate_limiter
    if not await rate_limiter.check(data.operator):
        usage = await rate_limiter.get_usage(data.operator)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limite de requêtes dépassée pour {data.operator} : "
                f"{usage.get('current_count', 0)}/{usage.get('limit_per_minute', 0)} "
                f"req/min. Réessayez dans quelques secondes."
            )
        )

    msg_id = await queue.push(
        transaction_data=data.model_dump(mode="json"),
        operator=data.operator,
    )

    logger.info(
        "Transaction mise en queue",
        extra={
            "transaction_id": data.transaction_id,
            "operator":       data.operator,
            "message_id":     msg_id,
        }
    )

    return {
        "status":          "accepted",
        "transaction_id":  data.transaction_id,
        "message_id":      msg_id,
        "result_url":      f"/api/v1/result/{data.transaction_id}",
    }


@router.get(
    "/result/{transaction_id}",
    response_model=ScoreOut,
    summary="Récupère le résultat d'une analyse async",
    description="Récupère le score depuis le cache Redis après une analyse asynchrone.",
)
async def get_result(
    transaction_id: str,
    request: Request,
    _: str = Depends(verify_api_key),
) -> ScoreOut:
    """
    Récupère le résultat d'une analyse lancée via /analyze-async.
    Retourne 404 si le résultat n'est pas encore disponible.
    """
    # Cherche dans le cache Redis
    cache    = request.app.state.prediction_cache
    operator = request.query_params.get("operator", "BANKILY")
    cached   = await cache.get(transaction_id, operator)

    if not cached:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Résultat non disponible pour {transaction_id} — réessayez dans quelques secondes"
        )

    return ScoreOut(**{k: v for k, v in cached.items() if k != "from_cache"})


@router.get(
    "/queue/stats",
    summary="Statistiques de la queue",
    description="Nombre de transactions en attente dans la queue Redis.",
)
async def queue_stats(
    request: Request,
    _: str = Depends(verify_api_key),
) -> dict:
    """Statistiques de la queue pour monitoring Grafana."""
    queue    = request.app.state.transaction_queue
    cache    = request.app.state.prediction_cache

    operators = ["BANKILY", "SEDAD", "MASRVI"]
    stats = {}
    for op in operators:
        stats[op] = {
            "queue_size":    await queue.queue_size(op),
        }

    cache_stats = await cache.get_stats()

    return {
        "queues":        stats,
        "cache":         cache_stats,
        "worker_running": getattr(queue, '_running', False),
    }


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

    # ── Métriques : santé des modèles + uptime ────
    model_ready_gauge.labels(model_name="xgboost").set(1 if model_ready else 0)
    service_uptime_seconds.set(uptime)

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


@router.get(
    "/rate-limit/{operator}",
    summary="Usage du rate limiting pour un opérateur",
    description="Retourne le nombre de requêtes utilisées dans la minute en cours."
)
async def rate_limit_status(
    operator: str,
    request: Request,
    _: str = Depends(verify_api_key),
) -> dict:
    """Monitoring du rate limiting — utile pour Grafana ou debug."""
    rate_limiter = request.app.state.rate_limiter
    return await rate_limiter.get_usage(operator.upper())


@router.get(
    "/metrics",
    summary="Métriques Prometheus",
    description=(
        "Expose les métriques au format Prometheus pour scraping. "
        "Pas d'authentification — appelé automatiquement par Prometheus."
    ),
    include_in_schema=False,
)
async def metrics(request: Request) -> Response:
    """
    Endpoint scrapé par Prometheus toutes les 15s (voir prometheus.yml).
    Pas de X-Api-Key requis — Prometheus tourne dans le réseau interne Docker.

    Met aussi à jour les gauges en temps réel (queue, rate limit)
    juste avant de générer la réponse, pour des données fraîches.
    """
    # Rafraîchit les gauges de queue pour les opérateurs connus
    queue = getattr(request.app.state, "transaction_queue", None)
    if queue:
        from infrastructure.stores.rate_limiter import RATE_LIMITS
        for operator in RATE_LIMITS.keys():
            try:
                size = await queue.queue_size(operator)
                queue_size_gauge.labels(operator=operator).set(size)
            except Exception:
                pass  # ne bloque jamais /metrics pour un souci de queue

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )