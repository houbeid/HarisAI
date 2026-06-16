"""
HarisAI — PredictionCache
==========================
Cache Redis pour les résultats de prédiction ML.

PROBLÈME RÉSOLU :
    .NET retente automatiquement une requête si elle échoue (retry policy).
    Sans cache, la même transaction peut être analysée 2 ou 3 fois
    par XGBoost — inutile et coûteux en temps CPU.

SOLUTION :
    Avant d'appeler XGBoost, on vérifie si la transaction a déjà
    été analysée dans les 5 dernières minutes. Si oui → cache hit.

CLÉ REDIS :
    harisai:cache:{operator}:{transaction_id}

TTL :
    5 minutes — suffisant pour absorber les retries de .NET
    (retry policy standard : 3 tentatives en 30 secondes)

GAIN :
    Cache hit  → < 1ms  (lecture Redis)
    Cache miss → ~50ms  (pipeline ML complet)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# TTL du cache en secondes — 5 minutes
CACHE_TTL_SECONDS = 5 * 60

# Préfixe des clés de cache
CACHE_PREFIX = "harisai:cache"


class PredictionCache:
    """
    Cache Redis pour les résultats du pipeline ML.

    S'intègre dans routes.py :
        # Avant le pipeline ML
        cached = await cache.get(transaction_id, operator)
        if cached:
            return cached  # ← retour immédiat sans toucher XGBoost

        # Pipeline ML complet
        result = await use_case.execute(...)

        # Stocke le résultat
        await cache.set(transaction_id, operator, result)
        return result
    """

    def __init__(self, redis_client=None):
        """
        Args:
            redis_client : client Redis asyncio (depuis RedisProfileStore)
                           None → cache désactivé (mode dégradé)
        """
        self._redis = redis_client
        self._enabled = redis_client is not None

        if self._enabled:
            logger.info("PredictionCache initialisé — TTL 5 minutes")
        else:
            logger.warning("PredictionCache désactivé — pas de client Redis")

    # ─────────────────────────────────────────
    # LECTURE
    # ─────────────────────────────────────────

    async def get(
        self,
        transaction_id: str,
        operator: str,
    ) -> Optional[dict]:
        """
        Récupère un résultat en cache.

        Returns:
            dict avec les résultats si cache hit
            None si cache miss ou cache désactivé
        """
        if not self._enabled:
            return None

        key = self._build_key(transaction_id, operator)

        try:
            data = await self._redis.get(key)
            if data is None:
                logger.debug(
                    "Cache MISS",
                    extra={"transaction_id": transaction_id}
                )
                return None

            result = json.loads(data)
            logger.info(
                "Cache HIT — prédiction depuis cache Redis",
                extra={
                    "transaction_id": transaction_id,
                    "score":          result.get("score"),
                    "decision":       result.get("decision"),
                }
            )
            # Ajoute un indicateur que c'est un cache hit
            result["from_cache"] = True
            return result

        except Exception as e:
            logger.error(
                "Erreur lecture cache Redis",
                extra={
                    "transaction_id": transaction_id,
                    "error": str(e)
                }
            )
            # En cas d'erreur — on continue sans cache
            return None

    # ─────────────────────────────────────────
    # ÉCRITURE
    # ─────────────────────────────────────────

    async def set(
        self,
        transaction_id: str,
        operator: str,
        score_data: dict,
    ) -> None:
        """
        Stocke un résultat dans le cache.

        Args:
            transaction_id : ID unique de la transaction
            operator       : BANKILY · SEDAD · MASRVI
            score_data     : dict avec score · decision · fraud_type · etc.
        """
        if not self._enabled:
            return

        key = self._build_key(transaction_id, operator)

        try:
            # On ne cache pas les indicateurs de cache
            data = {k: v for k, v in score_data.items() if k != "from_cache"}

            await self._redis.setex(
                key,
                CACHE_TTL_SECONDS,
                json.dumps(data)
            )

            logger.debug(
                "Résultat mis en cache",
                extra={
                    "transaction_id": transaction_id,
                    "ttl_seconds":    CACHE_TTL_SECONDS,
                }
            )

        except Exception as e:
            logger.error(
                "Erreur écriture cache Redis",
                extra={
                    "transaction_id": transaction_id,
                    "error": str(e)
                }
            )
            # Erreur non bloquante — le résultat est retourné quand même

    # ─────────────────────────────────────────
    # INVALIDATION
    # ─────────────────────────────────────────

    async def invalidate(
        self,
        transaction_id: str,
        operator: str,
    ) -> None:
        """
        Supprime une entrée du cache.
        Appelé si le compliance officer modifie manuellement
        le statut d'une transaction.
        """
        if not self._enabled:
            return

        key = self._build_key(transaction_id, operator)

        try:
            await self._redis.delete(key)
            logger.info(
                "Cache invalidé",
                extra={"transaction_id": transaction_id}
            )
        except Exception as e:
            logger.error(
                "Erreur invalidation cache",
                extra={"error": str(e)}
            )

    async def get_stats(self) -> dict:
        """
        Statistiques du cache — pour Grafana.
        Retourne le nombre d'entrées actives.
        """
        if not self._enabled:
            return {"enabled": False}

        try:
            keys = await self._redis.keys(f"{CACHE_PREFIX}:*")
            return {
                "enabled":     True,
                "active_entries": len(keys),
                "ttl_seconds": CACHE_TTL_SECONDS,
            }
        except Exception:
            return {"enabled": True, "active_entries": -1}

    # ─────────────────────────────────────────
    # UTILITAIRES
    # ─────────────────────────────────────────

    def _build_key(self, transaction_id: str, operator: str) -> str:
        """
        Clé Redis unique par transaction.
        Format : harisai:cache:{OPERATOR}:{transaction_id}
        Exemple : harisai:cache:BANKILY:BNK-2024-001
        """
        return f"{CACHE_PREFIX}:{operator.upper()}:{transaction_id}"


# ─────────────────────────────────────────────
# VERSION IN-MEMORY — pour les tests
# ─────────────────────────────────────────────

class InMemoryPredictionCache(PredictionCache):
    """
    Cache en mémoire pour les tests unitaires.
    Même interface que PredictionCache mais sans Redis.
    """

    def __init__(self):
        super().__init__(redis_client=None)
        self._store: dict = {}
        self._hits: int = 0
        self._misses: int = 0

    async def get(
        self,
        transaction_id: str,
        operator: str,
    ) -> Optional[dict]:
        key = self._build_key(transaction_id, operator)
        result = self._store.get(key)
        if result:
            self._hits += 1
            result["from_cache"] = True
            return result
        self._misses += 1
        return None

    async def set(
        self,
        transaction_id: str,
        operator: str,
        score_data: dict,
    ) -> None:
        key = self._build_key(transaction_id, operator)
        self._store[key] = {
            k: v for k, v in score_data.items()
            if k != "from_cache"
        }

    async def invalidate(
        self,
        transaction_id: str,
        operator: str,
    ) -> None:
        key = self._build_key(transaction_id, operator)
        self._store.pop(key, None)

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0