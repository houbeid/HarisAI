"""
HarisAI — Infrastructure Monitoring
======================================
CONTENU :
    metrics.py → 13 métriques Prometheus (compteurs, histogrammes, jauges)

Ce fichier était vide (0 ligne) alors que presentation/routes.py importe
directement depuis infrastructure.monitoring — sans réexport ici, cet
import échoue et fait planter le chargement de toute l'app FastAPI
(main.py), bloquant de fait tous les tests qui montent l'app complète
(TestAPIEndpoints, TestRateLimiting dans tests/test_integration.py).

UTILISATION :
    from infrastructure.monitoring import (
        transactions_total, decisions_total,
        cache_hits_total, cache_misses_total,
        rate_limit_rejections_total, errors_total, fraud_type_total,
        inference_duration_seconds, fraud_score_distribution,
        service_uptime_seconds,
        model_ready_gauge, queue_size_gauge, rate_limit_usage_gauge,
    )
"""

from .metrics import (
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

__all__ = [
    "transactions_total",
    "decisions_total",
    "cache_hits_total",
    "cache_misses_total",
    "rate_limit_rejections_total",
    "errors_total",
    "fraud_type_total",
    "inference_duration_seconds",
    "fraud_score_distribution",
    "service_uptime_seconds",
    "model_ready_gauge",
    "queue_size_gauge",
    "rate_limit_usage_gauge",
]