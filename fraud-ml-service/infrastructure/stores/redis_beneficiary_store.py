"""
HarisAI — RedisBeneficiaryStore
==================================
Implémentation concrète de IBeneficiaryStore.
Stocke et récupère les profils comportementaux des BÉNÉFICIAIRES dans
Redis — symétrique à RedisProfileStore (redis_store.py), mais côté
destinataire.

RÔLE :
    Sans ce store, is_mule_pattern (BeneficiaryProfile.is_likely_mule())
    ne peut jamais devenir vrai sur les transactions futures : sans
    persistance, distinct_senders_30d et last_received_at/last_outflow_at
    ne progressent jamais d'une transaction à l'autre.

STRUCTURE DE CLÉ REDIS :
    harisai:{operator}:beneficiary:{beneficiary_token}   → profil JSON
    harisai:{operator}:beneficiary:{beneficiary_token}:senders
        → ZSET (member=sender_token, score=timestamp Unix de la dernière
          transaction de ce sender vers ce bénéficiaire) — permet un
          calcul EXACT de distinct_senders_30d (ZCARD après purge des
          entrées hors fenêtre via ZREMRANGEBYSCORE), pas une
          approximation. Choix différent de RedisProfileStore, dont les
          moyennes glissantes SONT approximées (formule de Welford) car
          il n'existe pas de structure Redis native pour une moyenne
          glissante exacte — mais un COMPTE DISTINCT dans une fenêtre a
          un support natif idéal (ZSET), donc pas de raison d'approximer
          ici.

    IMPORTANT — la fenêtre de 30 jours est calculée relativement au
    timestamp DE LA TRANSACTION (transaction.timestamp), jamais à
    l'horloge murale (datetime.now()). Sinon, toute transaction passée
    (tests, rejeu de données historiques) verrait sa fenêtre de 30 jours
    calculée par rapport à "maintenant" au lieu de son propre contexte
    temporel — incohérent avec la donnée elle-même.

TTL :
    90 jours — même durée que RedisProfileStore, pas de raison de
    diverger (cohérence des deux profils d'une même transaction).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis

from application.ports.i_beneficiary_store import IBeneficiaryStore
from domain import BeneficiaryProfile, TokenHash, Transaction

logger = logging.getLogger(__name__)

# TTL du profil en secondes — 90 jours, même valeur que RedisProfileStore
BENEFICIARY_TTL_SECONDS = 90 * 24 * 3600

# Préfixe de toutes les clés HarisAI dans Redis
KEY_PREFIX = "harisai"

# Nombre maximum d'expéditeurs connus stockés dans known_sender_tokens
# (liste all-time, bornée — distincte de distinct_senders_30d qui est
# une fenêtre glissante exacte via le ZSET, voir docstring du module)
MAX_SENDERS = 50

# Fenêtre glissante pour le fan-in — doit rester synchronisée avec
# BeneficiaryProfile.has_high_fan_in() (domain/transaction.py), qui
# documente lui-même "distinct_senders_30d" comme une fenêtre de 30j
FAN_IN_WINDOW_DAYS = 30


class RedisBeneficiaryStore(IBeneficiaryStore):
    """
    Stockage des profils comportementaux des bénéficiaires dans Redis.

    Hérite de IBeneficiaryStore — respecte le contrat défini dans
    application/ports/i_beneficiary_store.py.

    Exemple d'utilisation :
        store = RedisBeneficiaryStore(redis_url="redis://localhost:6379")
        await store.connect()

        profile = await store.get(TokenHash("b3f9..."), "BANKILY")
        if profile is None:
            profile = await store.create_default(token, "BANKILY")
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Établit la connexion Redis."""
        self._client = await aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info(
            "Connexion Redis établie (beneficiary store)",
            extra={"url": self._redis_url}
        )

    async def disconnect(self) -> None:
        """Ferme la connexion Redis."""
        if self._client:
            await self._client.aclose()
            logger.info("Connexion Redis fermée (beneficiary store)")

    # ─────────────────────────────────────────
    # INTERFACE IBeneficiaryStore
    # ─────────────────────────────────────────

    async def get(
        self,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> Optional[BeneficiaryProfile]:
        """
        Récupère le profil d'un bénéficiaire depuis Redis.

        distinct_senders_30d retourné ici est la valeur CACHÉE lors du
        dernier update_inflow() — pas recalculée à la lecture (même
        philosophie que avg_amount_30d dans RedisProfileStore : une
        stat approximée/mise à jour en écriture, pas garantie
        parfaitement à jour si aucune transaction récente n'a eu lieu
        depuis — voir docstring du module pour le détail).

        Returns:
            BeneficiaryProfile si ce compte a déjà reçu des fonds
            None si c'est la première fois qu'il reçoit de l'argent
        """
        key = self._build_key(beneficiary_token, operator)

        try:
            data = await self._client.get(key)

            if data is None:
                logger.debug(
                    "Profil bénéficiaire introuvable — nouveau compte",
                    extra={"token": beneficiary_token.short(), "operator": operator}
                )
                return None

            profile = self._deserialize(data, beneficiary_token, operator)

            logger.debug(
                "Profil bénéficiaire récupéré",
                extra={
                    "token": beneficiary_token.short(),
                    "operator": operator,
                    "distinct_senders_30d": profile.distinct_senders_30d,
                }
            )
            return profile

        except Exception as e:
            logger.error(
                "Erreur lecture Redis (beneficiary)",
                extra={"token": beneficiary_token.short(), "error": str(e)}
            )
            # En cas d'erreur Redis — retourne None, comme RedisProfileStore.
            # Le use case traite ça comme "premier bénéficiaire", pas
            # comme une erreur bloquante.
            return None

    async def update_inflow(
        self,
        profile: BeneficiaryProfile,
        transaction: Transaction,
    ) -> None:
        """
        Met à jour le profil après une RÉCEPTION de fonds légitime
        confirmée. Voir IBeneficiaryStore.update_inflow() pour le détail
        de ce qui est mis à jour.

        Utilise transaction.timestamp (pas l'horloge murale) comme
        référence pour la fenêtre de 30 jours — voir docstring du module.
        """
        key = self._build_key(profile.beneficiary_token, profile.operator)
        senders_key = self._senders_key(profile.beneficiary_token, profile.operator)
        amount = transaction.amount.amount
        sender_value = transaction.client_token.value
        now = transaction.timestamp
        now_score = now.timestamp()
        cutoff_score = (now - timedelta(days=FAN_IN_WINDOW_DAYS)).timestamp()

        try:
            # ── Fan-in exact via ZSET (voir docstring du module) ──
            await self._client.zadd(senders_key, {sender_value: now_score})
            await self._client.zremrangebyscore(senders_key, "-inf", cutoff_score)
            distinct_senders_30d = await self._client.zcard(senders_key)
            await self._client.expire(senders_key, BENEFICIARY_TTL_SECONDS)

            # ── known_sender_tokens — liste all-time bornée ──
            known_senders = self._add_unique(
                profile.known_sender_tokens, sender_value, MAX_SENDERS
            )

            # ── Moyenne glissante du montant reçu (même formule que
            # RedisProfileStore._rolling_average — approximation O(1),
            # cohérente avec le reste du système) ──
            n = profile.total_transactions_received + 1
            new_avg_received_30d = self._rolling_average(
                profile.avg_amount_received_30d, amount, min(n, 30 * 10)
            )
            # total_received_30d — cumul APPROXIMATIF, pas une somme
            # strictement fenêtrée sur 30 jours (aurait besoin de la
            # même mécanique ZSET que le fan-in, jugé disproportionné
            # pour une stat secondaire non utilisée par is_likely_mule()).
            new_total_received_30d = profile.total_received_30d + amount

            updated_data = {
                "known_sender_tokens":        known_senders,
                "distinct_senders_30d":       int(distinct_senders_30d),
                "avg_amount_received_30d":    new_avg_received_30d,
                "total_received_30d":         new_total_received_30d,
                "last_received_at":           now.isoformat(),
                "last_outflow_at":            (
                    profile.last_outflow_at.isoformat()
                    if profile.last_outflow_at else None
                ),
                "total_transactions_received": n,
                "account_age_days":           profile.account_age_days,
                "last_updated":               datetime.now(timezone.utc).isoformat(),
            }

            await self._client.setex(
                key, BENEFICIARY_TTL_SECONDS, json.dumps(updated_data)
            )

            logger.debug(
                "Profil bénéficiaire mis à jour (inflow)",
                extra={
                    "token": profile.beneficiary_token.short(),
                    "distinct_senders_30d": distinct_senders_30d,
                    "total_tx_received": n,
                }
            )

        except Exception as e:
            logger.error(
                "Erreur mise à jour Redis (beneficiary inflow)",
                extra={"token": profile.beneficiary_token.short(), "error": str(e)}
            )
            # Ne pas lever l'exception — même philosophie que
            # RedisProfileStore.update() : la transaction a déjà été
            # décidée, l'échec de mise à jour du profil ne doit pas
            # faire planter la réponse déjà envoyée.

    async def update_outflow(
        self,
        beneficiary_token: TokenHash,
        operator: str,
        outflow_at: datetime,
    ) -> None:
        """
        Met à jour last_outflow_at quand ce compte envoie lui-même de
        l'argent. Appelé pour CHAQUE transaction approuvée (voir
        analyze_transaction.py, étape 9) — pas seulement pour les
        comptes ayant déjà un profil bénéficiaire.

        NO-OP si aucun profil n'existe encore pour ce compte (jamais
        reçu d'argent comme bénéficiaire) : rien de significatif à
        mettre à jour, et créer un profil ici polluerait le store avec
        des entrées pour des comptes purement expéditeurs qui ne sont
        jamais candidats mule (is_likely_mule() a besoin de
        last_received_at, qui resterait None de toute façon).
        """
        key = self._build_key(beneficiary_token, operator)

        try:
            data = await self._client.get(key)
            if data is None:
                logger.debug(
                    "update_outflow ignoré — aucun profil bénéficiaire "
                    "existant (jamais reçu d'argent)",
                    extra={"token": beneficiary_token.short()}
                )
                return

            d = json.loads(data)
            d["last_outflow_at"] = outflow_at.isoformat()
            d["last_updated"] = datetime.now(timezone.utc).isoformat()

            await self._client.setex(
                key, BENEFICIARY_TTL_SECONDS, json.dumps(d)
            )

            logger.debug(
                "Profil bénéficiaire mis à jour (outflow)",
                extra={"token": beneficiary_token.short(), "outflow_at": outflow_at.isoformat()}
            )

        except Exception as e:
            logger.error(
                "Erreur mise à jour Redis (beneficiary outflow)",
                extra={"token": beneficiary_token.short(), "error": str(e)}
            )

    async def create_default(
        self,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> BeneficiaryProfile:
        """
        Crée un profil bénéficiaire vide pour un compte qui reçoit de
        l'argent pour la première fois. Sauvegarde immédiatement dans
        Redis.
        """
        key = self._build_key(beneficiary_token, operator)

        default_data = {
            "known_sender_tokens":         [],
            "distinct_senders_30d":        0,
            "avg_amount_received_30d":     0.0,
            "total_received_30d":          0.0,
            "last_received_at":            None,
            "last_outflow_at":             None,
            "total_transactions_received": 0,
            "account_age_days":            0,
            "last_updated":                datetime.now(timezone.utc).isoformat(),
        }

        try:
            await self._client.setex(
                key, BENEFICIARY_TTL_SECONDS, json.dumps(default_data)
            )
            logger.info(
                "Profil bénéficiaire vide créé",
                extra={"token": beneficiary_token.short(), "operator": operator}
            )
        except Exception as e:
            logger.error(
                "Erreur création profil bénéficiaire Redis",
                extra={"error": str(e)}
            )

        return BeneficiaryProfile(
            beneficiary_token=beneficiary_token,
            operator=operator,
        )

    async def delete(
        self,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> None:
        """Supprime le profil d'un bénéficiaire (blob + ZSET fan-in)."""
        key = self._build_key(beneficiary_token, operator)
        senders_key = self._senders_key(beneficiary_token, operator)
        try:
            await self._client.delete(key, senders_key)
            logger.info(
                "Profil bénéficiaire supprimé",
                extra={"token": beneficiary_token.short(), "operator": operator}
            )
        except Exception as e:
            logger.error(
                "Erreur suppression Redis (beneficiary)",
                extra={"error": str(e)}
            )

    # ─────────────────────────────────────────
    # MÉTHODES PRIVÉES
    # ─────────────────────────────────────────

    def _build_key(self, beneficiary_token: TokenHash, operator: str) -> str:
        """
        Format : harisai:{operator}:beneficiary:{token}
        Distinct de harisai:{operator}:profile:{token} (RedisProfileStore)
        — un même TokenHash peut avoir les deux profils simultanément.
        """
        return f"{KEY_PREFIX}:{operator.upper()}:beneficiary:{beneficiary_token.value}"

    def _senders_key(self, beneficiary_token: TokenHash, operator: str) -> str:
        """Clé du ZSET fan-in — voir docstring du module."""
        return f"{self._build_key(beneficiary_token, operator)}:senders"

    def _deserialize(
        self,
        data: str,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> BeneficiaryProfile:
        """Désérialise le JSON Redis en objet BeneficiaryProfile."""
        d = json.loads(data)

        def _parse_dt(value):
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except (ValueError, TypeError):
                return None

        return BeneficiaryProfile(
            beneficiary_token=beneficiary_token,
            operator=operator,
            known_sender_tokens=list(d.get("known_sender_tokens", [])),
            distinct_senders_30d=int(d.get("distinct_senders_30d", 0)),
            avg_amount_received_30d=float(d.get("avg_amount_received_30d", 0.0)),
            total_received_30d=float(d.get("total_received_30d", 0.0)),
            last_received_at=_parse_dt(d.get("last_received_at")),
            last_outflow_at=_parse_dt(d.get("last_outflow_at")),
            total_transactions_received=int(d.get("total_transactions_received", 0)),
            account_age_days=int(d.get("account_age_days", 0)),
        )

    @staticmethod
    def _rolling_average(old_avg: float, new_value: float, n: int) -> float:
        """Identique à RedisProfileStore._rolling_average — voir redis_store.py."""
        if n <= 1:
            return new_value
        return old_avg + (new_value - old_avg) / n

    @staticmethod
    def _add_unique(existing: list, new_value, max_size: int) -> list:
        """Identique à RedisProfileStore._add_unique — voir redis_store.py."""
        result = list(existing)
        if new_value not in result:
            result.append(new_value)
        if len(result) > max_size:
            result = result[-max_size:]
        return result


# ─────────────────────────────────────────────
# VERSION IN-MEMORY — pour les tests unitaires
# ─────────────────────────────────────────────

class InMemoryBeneficiaryStore(IBeneficiaryStore):
    """
    Implémentation en mémoire de IBeneficiaryStore.
    Utilisée dans les tests unitaires — pas besoin d'une vraie Redis.

    Contrairement à InMemoryProfileStore (qui n'implémente PAS de vraies
    moyennes glissantes, juste des compteurs simples), le fan-in DOIT
    être correctement fenêtré ici : les tests existants
    (test_mule_pattern_detecte_apres_fan_in_et_sortie_rapide,
    test_marchand_avec_fan_in_eleve_jamais_flagge) vérifient des valeurs
    précises de distinct_senders_30d. La fenêtre est calculée par
    rapport à transaction.timestamp, jamais l'horloge murale — mêmes
    raisons que RedisBeneficiaryStore (voir docstring du module).

    Exemple dans les tests :
        store = InMemoryBeneficiaryStore()
        store.seed(token, operator, profile)  # pré-charge un profil
        profile = await store.get(token, operator)
    """

    def __init__(self):
        self._store: dict = {}
        # Historique (sender_token, timestamp) par clé bénéficiaire —
        # nécessaire pour calculer distinct_senders_30d correctement
        # sur une fenêtre glissante, pas juste un total cumulé.
        self._sender_history: dict = {}

    @staticmethod
    def _key(beneficiary_token: TokenHash, operator: str) -> str:
        return f"{operator}:{beneficiary_token.value}"

    def seed(
        self,
        beneficiary_token: TokenHash,
        operator: str,
        profile: BeneficiaryProfile,
    ) -> None:
        """Pré-charge un profil pour les tests."""
        self._store[self._key(beneficiary_token, operator)] = profile

    async def get(
        self,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> Optional[BeneficiaryProfile]:
        return self._store.get(self._key(beneficiary_token, operator))

    async def update_inflow(
        self,
        profile: BeneficiaryProfile,
        transaction: Transaction,
    ) -> None:
        key = self._key(profile.beneficiary_token, profile.operator)
        sender_value = transaction.client_token.value
        now = transaction.timestamp

        history = self._sender_history.setdefault(key, [])
        history.append((sender_value, now))
        cutoff = now - timedelta(days=FAN_IN_WINDOW_DAYS)
        history[:] = [(s, t) for (s, t) in history if t > cutoff]
        self._sender_history[key] = history

        profile.distinct_senders_30d = len({s for s, _ in history})

        if sender_value not in profile.known_sender_tokens:
            profile.known_sender_tokens.append(sender_value)
            if len(profile.known_sender_tokens) > MAX_SENDERS:
                profile.known_sender_tokens = profile.known_sender_tokens[-MAX_SENDERS:]

        amount = transaction.amount.amount
        n = profile.total_transactions_received + 1
        if n <= 1:
            profile.avg_amount_received_30d = amount
        else:
            profile.avg_amount_received_30d += (
                amount - profile.avg_amount_received_30d
            ) / min(n, 30 * 10)
        profile.total_received_30d += amount
        profile.last_received_at = now
        profile.total_transactions_received = n

        self._store[key] = profile

    async def update_outflow(
        self,
        beneficiary_token: TokenHash,
        operator: str,
        outflow_at: datetime,
    ) -> None:
        key = self._key(beneficiary_token, operator)
        profile = self._store.get(key)
        if profile is None:
            # Même comportement que RedisBeneficiaryStore — no-op si
            # aucun profil n'existe (jamais reçu d'argent).
            return
        profile.last_outflow_at = outflow_at
        self._store[key] = profile

    async def create_default(
        self,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> BeneficiaryProfile:
        profile = BeneficiaryProfile(
            beneficiary_token=beneficiary_token,
            operator=operator,
        )
        self._store[self._key(beneficiary_token, operator)] = profile
        return profile

    async def delete(
        self,
        beneficiary_token: TokenHash,
        operator: str,
    ) -> None:
        key = self._key(beneficiary_token, operator)
        self._store.pop(key, None)
        self._sender_history.pop(key, None)