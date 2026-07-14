"""
HarisAI — Métriques Prometheus
=================================
Centralise toutes les métriques exposées via GET /metrics.

POURQUOI CE FICHIER EST SÉPARÉ :
    Toutes les métriques sont définies UNE SEULE FOIS ici.
    routes.py et analyze_transaction.py importent ces objets
    et les incrémentent — pas de duplication de définitions Prometheus
    (qui provoquerait une erreur "Duplicated timeseries").

TYPES DE MÉTRIQUES PROMETHEUS :
    Counter   → ne fait qu'augmenter (nombre total de transactions)
    Histogram → distribue les valeurs en buckets (latence)
    Gauge     → valeur qui monte et descend (taille de la queue)

UTILISATION :
    from infrastructure.monitoring.metrics import (
        transactions_total, inference_duration_seconds,
        decisions_total, model_ready_gauge, queue_size_gauge,
        rate_limit_rejections_total, cache_hits_total,
    )

    # Dans le code métier
    transactions_total.labels(operator="BANKILY").inc()
    with inference_duration_seconds.time():
        result = await use_case.execute(...)
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, REGISTRY


# ─────────────────────────────────────────────
# COUNTERS — valeurs qui n'augmentent que dans un sens
# ─────────────────────────────────────────────

transactions_total = Counter(
    "harisai_transactions_total",
    "Nombre total de transactions analysées",
    ["operator"],
)

decisions_total = Counter(
    "harisai_decisions_total",
    "Nombre de décisions par type (APPROVE, REVIEW, BLOCK)",
    ["operator", "decision"],
)

cache_hits_total = Counter(
    "harisai_cache_hits_total",
    "Nombre de hits du cache de prédictions",
    ["operator"],
)

cache_misses_total = Counter(
    "harisai_cache_misses_total",
    "Nombre de misses du cache de prédictions",
    ["operator"],
)

rate_limit_rejections_total = Counter(
    "harisai_rate_limit_rejections_total",
    "Nombre de requêtes rejetées par le rate limiting",
    ["operator"],
)

errors_total = Counter(
    "harisai_errors_total",
    "Nombre d'erreurs dans le pipeline d'analyse",
    ["operator", "error_type"],
)

fraud_type_total = Counter(
    "harisai_fraud_type_total",
    "Nombre de fraudes détectées par type",
    ["operator", "fraud_type"],
)


# ─────────────────────────────────────────────
# HISTOGRAMS — distribution des valeurs (latence)
# ─────────────────────────────────────────────

inference_duration_seconds = Histogram(
    "harisai_inference_duration_seconds",
    "Durée du pipeline d'analyse ML complet (secondes)",
    ["operator"],
    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

fraud_score_distribution = Histogram(
    "harisai_fraud_score_distribution",
    "Distribution des scores de fraude calculés (0-100)",
    ["operator"],
    buckets=(10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)


# ─────────────────────────────────────────────
# GAUGES — valeurs qui montent et descendent
# ─────────────────────────────────────────────

queue_size_gauge = Gauge(
    "harisai_queue_size",
    "Nombre de transactions en attente dans la queue Redis",
    ["operator"],
)

model_ready_gauge = Gauge(
    "harisai_model_ready",
    "Statut de disponibilité des modèles ML (1=prêt, 0=indisponible)",
    ["model_name"],
)

rate_limit_usage_gauge = Gauge(
    "harisai_rate_limit_usage",
    "Nombre de requêtes utilisées dans la fenêtre actuelle",
    ["operator"],
)

service_uptime_seconds = Gauge(
    "harisai_service_uptime_seconds",
    "Durée depuis le démarrage du service (secondes)",
)


def reset_registry_for_tests() -> None:
    """
    Utilitaire pour les tests — évite l'erreur 'Duplicated timeseries'
    quand pytest réimporte le module plusieurs fois.
    Ne PAS appeler en production.
    """
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except KeyError:
            pass