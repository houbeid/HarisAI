"""
HarisAI — Infrastructure Stores
==================================
CONTENU :
    redis_store.py            → profils comportementaux clients (Redis)
    redis_beneficiary_store.py → profils comportementaux bénéficiaires (Redis)
    postgres_store.py         → audit trail BCM immuable (PostgreSQL)
    prediction_cache.py       → cache des prédictions ML (Redis · TTL 5min)
    transaction_queue.py      → queue messages (Redis Streams · zéro 503)
    rate_limiter.py            → limite requêtes par opérateur (Redis)

UTILISATION :
    from infrastructure.stores import (
        RedisProfileStore, InMemoryProfileStore,
        RedisBeneficiaryStore, InMemoryBeneficiaryStore,
        PostgresAuditStore, InMemoryAuditStore,
        PredictionCache, InMemoryPredictionCache,
        TransactionQueue, InMemoryTransactionQueue,
        RateLimiter, InMemoryRateLimiter,
    )
"""

from .redis_store              import RedisProfileStore, InMemoryProfileStore
from .redis_beneficiary_store  import RedisBeneficiaryStore, InMemoryBeneficiaryStore
from .postgres_store           import PostgresAuditStore, InMemoryAuditStore
from .prediction_cache         import PredictionCache, InMemoryPredictionCache
from .transaction_queue        import TransactionQueue, InMemoryTransactionQueue
from .rate_limiter             import RateLimiter, InMemoryRateLimiter

__all__ = [
    "RedisProfileStore",
    "InMemoryProfileStore",
    "RedisBeneficiaryStore",
    "InMemoryBeneficiaryStore",
    "PostgresAuditStore",
    "InMemoryAuditStore",
    "PredictionCache",
    "InMemoryPredictionCache",
    "TransactionQueue",
    "InMemoryTransactionQueue",
    "RateLimiter",
    "InMemoryRateLimiter",
]