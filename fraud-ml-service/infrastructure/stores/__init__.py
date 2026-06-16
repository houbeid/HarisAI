"""
HarisAI — Infrastructure Stores
==================================
CONTENU :
    redis_store.py        → profils comportementaux clients (Redis)
    postgres_store.py     → audit trail BCM immuable (PostgreSQL)
    prediction_cache.py   → cache des prédictions ML (Redis · TTL 5min)
    transaction_queue.py  → queue messages (Redis Streams · zéro 503)

UTILISATION :
    from infrastructure.stores import (
        RedisProfileStore, InMemoryProfileStore,
        PostgresAuditStore, InMemoryAuditStore,
        PredictionCache, InMemoryPredictionCache,
        TransactionQueue, InMemoryTransactionQueue,
    )
"""

from .redis_store       import RedisProfileStore, InMemoryProfileStore
from .postgres_store    import PostgresAuditStore, InMemoryAuditStore
from .prediction_cache  import PredictionCache, InMemoryPredictionCache
from .transaction_queue import TransactionQueue, InMemoryTransactionQueue

__all__ = [
    "RedisProfileStore",
    "InMemoryProfileStore",
    "PostgresAuditStore",
    "InMemoryAuditStore",
    "PredictionCache",
    "InMemoryPredictionCache",
    "TransactionQueue",
    "InMemoryTransactionQueue",
]