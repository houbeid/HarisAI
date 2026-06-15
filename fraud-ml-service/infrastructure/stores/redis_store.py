"""
HarisAI — RedisProfileStore
=============================
Implémentation concrète de IProfileStore.
Stocke et récupère les profils comportementaux clients dans Redis.

RÔLE :
    C'est la mémoire du système. Sans Redis, le système ne peut pas
    détecter les déviations comportementales — tout sera "nouveau"
    pour chaque client à chaque transaction.

STRUCTURE DE CLÉ REDIS :
    harisai:{operator}:profile:{client_token}
    ex: harisai:BANKILY:profile:a3f9b2c1...

TTL :
    90 jours — si un client n'est pas actif pendant 90 jours,
    son profil expire et sera recréé à la prochaine transaction.

CE QUE REDIS STOCKE PAR CLIENT :
    - Moyennes des montants (7j, 30j)
    - Écart-type des montants (7j)
    - Zones habituelles
    - Canaux habituels
    - Devices connus
    - Bénéficiaires connus
    - Heures habituelles
    - Méta (age compte, total transactions, dernière tx)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

import redis.asyncio as aioredis

from application.ports.i_profile_store import IProfileStore
from domain import Channel, ClientProfile, TokenHash, Transaction

logger = logging.getLogger(__name__)

# TTL du profil en secondes — 90 jours
PROFILE_TTL_SECONDS = 90 * 24 * 3600

# Préfixe de toutes les clés HarisAI dans Redis
KEY_PREFIX = "harisai"

# Nombre maximum de zones / devices / bénéficiaires stockés
# Évite que le profil grossisse indéfiniment
MAX_ZONES       = 10
MAX_DEVICES     = 5
MAX_BENEFICIARIES = 50
MAX_HOURS       = 24


class RedisProfileStore(IProfileStore):
    """
    Stockage des profils comportementaux dans Redis.

    Hérite de IProfileStore — respecte le contrat défini
    dans application/ports/i_profile_store.py.

    Le use case analyze_transaction.py appelle :
        profile = await store.get(client_token, operator)
        await store.update(profile, transaction)

    Sans jamais savoir que c'est Redis derrière.

    Exemple d'utilisation :
        store = RedisProfileStore(redis_url="redis://localhost:6379")
        await store.connect()

        profile = await store.get(TokenHash("a3f9b2c1..."), "BANKILY")
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
            "Connexion Redis établie",
            extra={"url": self._redis_url}
        )

    async def disconnect(self) -> None:
        """Ferme la connexion Redis."""
        if self._client:
            await self._client.aclose()
            logger.info("Connexion Redis fermée")

    # ─────────────────────────────────────────
    # INTERFACE IProfileStore
    # ─────────────────────────────────────────

    async def get(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> Optional[ClientProfile]:
        """
        Récupère le profil d'un client depuis Redis.

        Returns:
            ClientProfile si le client est connu
            None si c'est sa première transaction
        """
        key = self._build_key(client_token, operator)

        try:
            data = await self._client.get(key)

            if data is None:
                logger.debug(
                    "Profil introuvable — nouveau client",
                    extra={"token": client_token.short(), "operator": operator}
                )
                return None

            profile = self._deserialize(data, client_token, operator)

            logger.debug(
                "Profil récupéré",
                extra={
                    "token": client_token.short(),
                    "operator": operator,
                    "total_tx": profile.total_transactions,
                    "avg_30d": round(profile.avg_amount_30d, 0),
                }
            )
            return profile

        except Exception as e:
            logger.error(
                "Erreur lecture Redis",
                extra={"token": client_token.short(), "error": str(e)}
            )
            # En cas d'erreur Redis — retourne None
            # Le use case créera un profil vide
            # La transaction continuera sans profil complet
            return None

    async def update(
        self,
        profile: ClientProfile,
        transaction: Transaction,
    ) -> None:
        """
        Met à jour le profil après une transaction légitime.
        Appelé seulement pour les transactions APPROVE
        ou les faux positifs confirmés par le compliance officer.

        Met à jour :
        - Moyennes des montants (fenêtre glissante)
        - Devices connus
        - Zones habituelles
        - Heures habituelles
        - Bénéficiaires connus
        - Méta (total_tx, last_transaction_at)
        """
        key = self._build_key(transaction.client_token, transaction.operator)
        amount = transaction.amount.amount

        try:
            # ── Mise à jour des moyennes (fenêtre glissante) ──
            # Formule moyenne glissante :
            # new_avg = old_avg + (new_value - old_avg) / n
            # Plus simple et plus efficace qu'un recalcul complet
            n = profile.total_transactions + 1

            new_avg_7d  = self._rolling_average(
                profile.avg_amount_7d, amount, min(n, 7 * 10)
            )
            new_avg_30d = self._rolling_average(
                profile.avg_amount_30d, amount, min(n, 30 * 10)
            )

            # Écart-type glissant (approximation de Welford)
            new_std_7d = self._rolling_std(
                profile.std_amount_7d,
                profile.avg_amount_7d,
                new_avg_7d,
                amount,
                min(n, 7 * 10)
            )

            # ── Mise à jour des listes ─────────────────────
            known_devices = self._add_unique(
                profile.known_device_ids,
                transaction.device_id,
                MAX_DEVICES
            )
            usual_zones = self._add_unique(
                profile.usual_zones,
                transaction.zone,
                MAX_ZONES
            )
            usual_hours = self._add_unique(
                profile.usual_hours,
                transaction.hour_of_day,
                MAX_HOURS
            )
            usual_channels = self._add_unique(
                profile.usual_channels,
                transaction.channel.value,
                len(list(Channel))
            )

            # Bénéficiaire connu
            known_beneficiaries = list(profile.known_beneficiary_tokens)
            if (
                transaction.beneficiary_token and
                transaction.beneficiary_token.value not in known_beneficiaries
            ):
                known_beneficiaries.append(
                    transaction.beneficiary_token.value
                )
                # Garde seulement les N derniers bénéficiaires
                if len(known_beneficiaries) > MAX_BENEFICIARIES:
                    known_beneficiaries = known_beneficiaries[-MAX_BENEFICIARIES:]

            # ── Construit le profil mis à jour ─────────────
            updated_data = {
                "avg_amount_7d":              new_avg_7d,
                "avg_amount_30d":             new_avg_30d,
                "std_amount_7d":              new_std_7d,
                "max_amount_ever":            max(
                    profile.max_amount_ever, amount
                ),
                "usual_zones":                usual_zones,
                "usual_channels":             usual_channels,
                "known_device_ids":           known_devices,
                "known_beneficiary_tokens":   known_beneficiaries,
                "usual_hours":                usual_hours,
                "total_transactions":         n,
                "account_age_days":           profile.account_age_days,
                "last_transaction_at":        datetime.now(
                    timezone.utc
                ).isoformat(),
                "last_updated":               datetime.now(
                    timezone.utc
                ).isoformat(),
            }

            # ── Sauvegarde dans Redis avec TTL ─────────────
            await self._client.setex(
                key,
                PROFILE_TTL_SECONDS,
                json.dumps(updated_data)
            )

            logger.debug(
                "Profil mis à jour",
                extra={
                    "token": transaction.client_token.short(),
                    "operator": transaction.operator,
                    "total_tx": n,
                    "new_avg_30d": round(new_avg_30d, 0),
                }
            )

        except Exception as e:
            logger.error(
                "Erreur mise à jour Redis",
                extra={
                    "token": transaction.client_token.short(),
                    "error": str(e)
                }
            )
            # Ne pas lever l'exception — la transaction a déjà été
            # analysée et décidée. L'échec de mise à jour du profil
            # est loggé mais ne bloque pas le système.

    async def create_default(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> ClientProfile:
        """
        Crée un profil vide pour un nouveau client.
        Sauvegarde immédiatement dans Redis.
        """
        key = self._build_key(client_token, operator)

        default_data = {
            "avg_amount_7d":            0.0,
            "avg_amount_30d":           0.0,
            "std_amount_7d":            0.0,
            "max_amount_ever":          0.0,
            "usual_zones":              [],
            "usual_channels":           [],
            "known_device_ids":         [],
            "known_beneficiary_tokens": [],
            "usual_hours":              [],
            "total_transactions":       0,
            "account_age_days":         0,
            "last_transaction_at":      None,
            "last_updated":             datetime.now(timezone.utc).isoformat(),
        }

        try:
            await self._client.setex(
                key,
                PROFILE_TTL_SECONDS,
                json.dumps(default_data)
            )
            logger.info(
                "Profil vide créé",
                extra={
                    "token": client_token.short(),
                    "operator": operator
                }
            )
        except Exception as e:
            logger.error(
                "Erreur création profil Redis",
                extra={"error": str(e)}
            )

        return ClientProfile(
            client_token=client_token,
            operator=operator,
        )

    async def delete(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> None:
        """Supprime le profil d'un client."""
        key = self._build_key(client_token, operator)
        try:
            await self._client.delete(key)
            logger.info(
                "Profil supprimé",
                extra={
                    "token": client_token.short(),
                    "operator": operator
                }
            )
        except Exception as e:
            logger.error(
                "Erreur suppression Redis",
                extra={"error": str(e)}
            )

    # ─────────────────────────────────────────
    # MÉTHODES PRIVÉES
    # ─────────────────────────────────────────

    def _build_key(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> str:
        """
        Construit la clé Redis pour un profil client.

        Format : harisai:{operator}:profile:{token}
        Exemple : harisai:BANKILY:profile:a3f9b2c1d4e5f6a7
        """
        return f"{KEY_PREFIX}:{operator.upper()}:profile:{client_token.value}"

    def _deserialize(
        self,
        data: str,
        client_token: TokenHash,
        operator: str,
    ) -> ClientProfile:
        """Désérialise le JSON Redis en objet ClientProfile."""
        d = json.loads(data)

        last_tx = None
        if d.get("last_transaction_at"):
            try:
                last_tx = datetime.fromisoformat(d["last_transaction_at"])
            except (ValueError, TypeError):
                last_tx = None

        return ClientProfile(
            client_token=client_token,
            operator=operator,
            avg_amount_7d=float(d.get("avg_amount_7d", 0.0)),
            avg_amount_30d=float(d.get("avg_amount_30d", 0.0)),
            std_amount_7d=float(d.get("std_amount_7d", 0.0)),
            max_amount_ever=float(d.get("max_amount_ever", 0.0)),
            usual_zones=list(d.get("usual_zones", [])),
            usual_channels=list(d.get("usual_channels", [])),
            known_device_ids=list(d.get("known_device_ids", [])),
            known_beneficiary_tokens=list(
                d.get("known_beneficiary_tokens", [])
            ),
            usual_hours=list(d.get("usual_hours", [])),
            total_transactions=int(d.get("total_transactions", 0)),
            account_age_days=int(d.get("account_age_days", 0)),
            last_transaction_at=last_tx,
        )

    @staticmethod
    def _rolling_average(
        old_avg: float,
        new_value: float,
        n: int,
    ) -> float:
        """
        Calcule la moyenne glissante sans stocker tout l'historique.

        Formule : new_avg = old_avg + (new_value - old_avg) / n

        Avantage : O(1) en mémoire — pas besoin de stocker
        toutes les transactions passées dans Redis.
        """
        if n <= 1:
            return new_value
        return old_avg + (new_value - old_avg) / n

    @staticmethod
    def _rolling_std(
        old_std: float,
        old_avg: float,
        new_avg: float,
        new_value: float,
        n: int,
    ) -> float:
        """
        Approximation de l'écart-type glissant (algorithme de Welford).
        Utilisé pour calculer le z-score dans feature_engineering.py.
        """
        if n <= 1:
            return 0.0
        # Variance glissante
        old_var = old_std ** 2
        new_var = old_var + (
            (new_value - old_avg) * (new_value - new_avg) - old_var
        ) / n
        return max(0.0, new_var) ** 0.5

    @staticmethod
    def _add_unique(
        existing: list,
        new_value,
        max_size: int,
    ) -> list:
        """
        Ajoute une valeur à une liste si elle n'existe pas déjà.
        Respecte la taille maximale définie.
        """
        result = list(existing)
        if new_value not in result:
            result.append(new_value)
        # Garde seulement les N derniers éléments
        if len(result) > max_size:
            result = result[-max_size:]
        return result


# ─────────────────────────────────────────────
# VERSION IN-MEMORY — pour les tests unitaires
# ─────────────────────────────────────────────

class InMemoryProfileStore(IProfileStore):
    """
    Implémentation en mémoire de IProfileStore.
    Utilisée dans les tests unitaires — pas besoin d'une vraie Redis.

    Exemple dans les tests :
        store = InMemoryProfileStore()
        store.seed(token, operator, profile)  # pré-charge un profil
        profile = await store.get(token, operator)
    """

    def __init__(self):
        self._store: dict = {}

    def seed(
        self,
        client_token: TokenHash,
        operator: str,
        profile: ClientProfile,
    ) -> None:
        """Pré-charge un profil pour les tests."""
        key = f"{operator}:{client_token.value}"
        self._store[key] = profile

    async def get(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> Optional[ClientProfile]:
        key = f"{operator}:{client_token.value}"
        return self._store.get(key)

    async def update(
        self,
        profile: ClientProfile,
        transaction: Transaction,
    ) -> None:
        """Met à jour simplement en mémoire."""
        key = f"{transaction.operator}:{transaction.client_token.value}"

        # Ajoute le device si nouveau
        if transaction.device_id not in profile.known_device_ids:
            profile.known_device_ids.append(transaction.device_id)

        # Ajoute la zone si nouvelle
        if transaction.zone not in profile.usual_zones:
            profile.usual_zones.append(transaction.zone)

        # Met à jour les méta
        profile.total_transactions += 1
        profile.last_transaction_at = datetime.now(timezone.utc)

        self._store[key] = profile

    async def create_default(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> ClientProfile:
        profile = ClientProfile(
            client_token=client_token,
            operator=operator,
        )
        key = f"{operator}:{client_token.value}"
        self._store[key] = profile
        return profile

    async def delete(
        self,
        client_token: TokenHash,
        operator: str,
    ) -> None:
        key = f"{operator}:{client_token.value}"
        self._store.pop(key, None)