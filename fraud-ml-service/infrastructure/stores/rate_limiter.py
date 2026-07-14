"""
HarisAI — RateLimiter
========================
Limite le nombre de requêtes par opérateur pour protéger le service.

POURQUOI CÔTÉ FASTAPI (pas .NET) :
    fraud-ml-service expose l'API avec X-Api-Key.
    C'est ce service qui doit se protéger contre :
        - Un .NET buggé qui spam les requêtes
        - Une attaque directe si la clé API fuite
        - Un opérateur qui sature le service

FONCTIONNE DÈS MAINTENANT :
    Pas besoin que Bankily/Sedad/Masrvi soit "officiellement" intégré.
    Le rate limiting se base sur Transaction.operator qui existe déjà.
    Ajouter un nouvel opérateur = aucune modification de ce fichier.

ALGORITHME — Fenêtre glissante simplifiée (fixed window) :
    Clé Redis : harisai:ratelimit:{OPERATOR}:{minute_actuelle}
    Valeur    : compteur de requêtes
    TTL       : 60 secondes (expire automatiquement)

    Avantage  : simple, rapide, une seule commande Redis (INCR)
    Limite    : possibilité de léger dépassement aux frontières de minute
                (acceptable pour notre cas d'usage)

UTILISATION :
    limiter = RateLimiter(redis_client=redis_store._client)
    allowed = await limiter.check("BANKILY")
    if not allowed:
        raise HTTPException(429, "Rate limit dépassé")
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# LIMITES PAR OPÉRATEUR
# ─────────────────────────────────────────────
# Ajouter un nouvel opérateur = une ligne ici, rien d'autre à changer.

DEFAULT_RATE_LIMIT = 500  # requêtes/minute si opérateur non listé

RATE_LIMITS: Dict[str, int] = {
    "BANKILY": 500,
    "SEDAD":   500,
    "MASRVI":  500,
}


# ─────────────────────────────────────────────
# RATE LIMITER — Redis
# ─────────────────────────────────────────────

class RateLimiter:
    """
    Limite les requêtes par opérateur via un compteur Redis.

    Utilise INCR + EXPIRE — atomique et performant.
    Fenêtre fixe d'une minute (alignée sur l'horloge système).
    """

    def __init__(self, redis_client=None):
        """
        Args:
            redis_client : client Redis async (depuis RedisProfileStore._client)
                           Si None, le rate limiting est désactivé (mode dégradé)
        """
        self._redis = redis_client
        self._enabled = redis_client is not None

        if not self._enabled:
            logger.warning(
                "RateLimiter désactivé — pas de client Redis "
                "(mode dégradé, toutes les requêtes sont autorisées)"
            )

    async def check(self, operator: str) -> bool:
        """
        Vérifie si l'opérateur peut faire une requête supplémentaire.

        Args:
            operator : nom de l'opérateur (BANKILY, SEDAD, MASRVI...)

        Returns:
            True si la requête est autorisée, False si la limite est dépassée
        """
        if not self._enabled:
            return True

        limit = RATE_LIMITS.get(operator, DEFAULT_RATE_LIMIT)
        current_minute = int(time.time() // 60)
        key = f"harisai:ratelimit:{operator}:{current_minute}"

        try:
            count = await self._redis.incr(key)
            if count == 1:
                # Première requête de cette fenêtre — pose le TTL
                await self._redis.expire(key, 60)

            allowed = count <= limit

            if not allowed:
                logger.warning(
                    f"Rate limit dépassé pour {operator} : "
                    f"{count}/{limit} req/min"
                )

            return allowed

        except Exception as e:
            # En cas d'erreur Redis, on n'empêche pas le service de tourner
            logger.error(f"Erreur RateLimiter (Redis) : {e} — requête autorisée")
            return True

    async def get_usage(self, operator: str) -> dict:
        """
        Retourne l'usage actuel pour un opérateur.
        Utile pour un endpoint de monitoring.
        """
        if not self._enabled:
            return {"enabled": False}

        limit = RATE_LIMITS.get(operator, DEFAULT_RATE_LIMIT)
        current_minute = int(time.time() // 60)
        key = f"harisai:ratelimit:{operator}:{current_minute}"

        try:
            count = await self._redis.get(key)
            count = int(count) if count else 0
        except Exception:
            count = 0

        return {
            "enabled":         True,
            "operator":        operator,
            "current_count":   count,
            "limit_per_minute": limit,
            "remaining":       max(0, limit - count),
        }


class InMemoryRateLimiter(RateLimiter):
    """
    Version en mémoire — utilisée pour les tests et le mode dégradé
    quand Redis n'est pas disponible.
    """

    def __init__(self):
        super().__init__(redis_client=None)
        self._enabled = True  # contrairement au parent, celui-ci fonctionne
        self._counters: Dict[str, int] = {}
        self._window: Dict[str, int] = {}

    async def check(self, operator: str) -> bool:
        limit = RATE_LIMITS.get(operator, DEFAULT_RATE_LIMIT)
        current_minute = int(time.time() // 60)

        # Reset si nouvelle fenêtre
        if self._window.get(operator) != current_minute:
            self._window[operator] = current_minute
            self._counters[operator] = 0

        self._counters[operator] += 1
        count = self._counters[operator]

        allowed = count <= limit
        if not allowed:
            logger.warning(
                f"Rate limit dépassé pour {operator} : "
                f"{count}/{limit} req/min (InMemory)"
            )
        return allowed

    async def get_usage(self, operator: str) -> dict:
        limit = RATE_LIMITS.get(operator, DEFAULT_RATE_LIMIT)
        current_minute = int(time.time() // 60)
        count = (
            self._counters.get(operator, 0)
            if self._window.get(operator) == current_minute
            else 0
        )
        return {
            "enabled":          True,
            "operator":         operator,
            "current_count":    count,
            "limit_per_minute": limit,
            "remaining":        max(0, limit - count),
        }