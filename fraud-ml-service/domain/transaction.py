"""
HarisAI — Domain Transaction & ClientProfile
=============================================
Transaction  : représente une transaction mobile money reçue via webhook.
ClientProfile: profil comportemental du client stocké dans Redis.
               Mis à jour après chaque transaction légitime confirmée.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .enums import Channel, Currency
from .value_objects import Money, TokenHash


@dataclass
class Transaction:
    """
    Entité principale — une transaction mobile money.
    Reçue depuis Bankily / Sedad / Masrvi via webhook .NET 8.
    Toutes les données personnelles sont anonymisées avant d'arriver ici.

    Exemple:
        tx = Transaction(
            transaction_id="BNK-2024-001",
            client_token=TokenHash("a3f9b2c1..."),
            amount=Money(8500.0),
            timestamp=datetime.utcnow(),
            channel=Channel.MOBILE_APP,
            zone="TEVRAGH_ZEINA",
            operator="BANKILY",
            device_id="device_hash_xyz"
        )
    """

    # ── Identité ──────────────────────────────
    transaction_id: str
    client_token: TokenHash
    amount: Money
    timestamp: datetime

    # ── Canal et localisation ─────────────────
    channel: Channel
    zone: str              # ex: "TEVRAGH_ZEINA", "KSAR", "ROSSO"
    operator: str          # ex: "BANKILY", "SEDAD", "MASRVI"

    # ── Device et SIM — détection SIM swapping ─
    device_id: str
    sim_changed_72h: bool = False
    sim_changed_at: Optional[datetime] = None

    # ── Bénéficiaire (anonymisé) ──────────────
    beneficiary_token: Optional[TokenHash] = None
    beneficiary_is_merchant: bool = False

    # ── Agent physique (canal AGENT) ──────────
    agent_id: Optional[str] = None

    # ── Contexte USSD ─────────────────────────
    ussd_session: bool = False

    # ── Méta ──────────────────────────────────
    received_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.transaction_id:
            raise ValueError("transaction_id est obligatoire")
        if not self.operator:
            raise ValueError("operator est obligatoire (BANKILY, SEDAD, MASRVI)")

    # ── Propriétés calculées ───────────────────

    @property
    def hour_of_day(self) -> int:
        """Heure de la transaction — utilisée comme feature XGBoost."""
        return self.timestamp.hour

    @property
    def day_of_week(self) -> int:
        """Jour de la semaine — 0=lundi, 6=dimanche."""
        return self.timestamp.weekday()

    @property
    def is_night_transaction(self) -> bool:
        """
        Transaction entre 22h et 6h — signal de risque.
        La majorité des fraudes SIM swap se passent la nuit.
        """
        return self.hour_of_day >= 22 or self.hour_of_day <= 6

    @property
    def is_ussd_channel(self) -> bool:
        """True si la transaction vient du menu USSD *888#."""
        return self.channel == Channel.USSD

    @property
    def is_agent_channel(self) -> bool:
        """True si la transaction passe par un agent physique."""
        return self.channel == Channel.AGENT

    @property
    def is_weekend(self) -> bool:
        """Samedi ou dimanche."""
        return self.day_of_week >= 5

    def __repr__(self) -> str:
        return (
            f"Transaction("
            f"id={self.transaction_id}, "
            f"amount={self.amount}, "
            f"channel={self.channel.value}, "
            f"zone={self.zone}, "
            f"operator={self.operator}"
            f")"
        )


@dataclass
class ClientProfile:
    """
    Profil comportemental d'un client — stocké dans Redis avec TTL 90 jours.
    C'est la mémoire du système — il sait comment le client se comporte
    normalement pour détecter les déviations suspectes.

    Mis à jour après chaque transaction confirmée comme légitime.
    """

    client_token: TokenHash
    operator: str  # BANKILY, SEDAD, MASRVI

    # ── Statistiques montants ─────────────────
    avg_amount_7d: float = 0.0    # Moyenne sur 7 jours
    avg_amount_30d: float = 0.0   # Moyenne sur 30 jours
    std_amount_7d: float = 0.0    # Écart-type 7 jours
    max_amount_ever: float = 0.0  # Maximum historique absolu

    # ── Zones habituelles ─────────────────────
    usual_zones: list = field(default_factory=list)
    # ex: ["TEVRAGH_ZEINA", "KSAR"]

    # ── Canaux habituels ──────────────────────
    usual_channels: list = field(default_factory=list)
    # ex: ["MOBILE_APP"]

    # ── Devices connus ────────────────────────
    known_device_ids: list = field(default_factory=list)

    # ── Bénéficiaires habituels ───────────────
    known_beneficiary_tokens: list = field(default_factory=list)

    # ── Horaires habituels ────────────────────
    usual_hours: list = field(default_factory=list)
    # ex: [8, 9, 10, 17, 18]

    # ── Méta compte ───────────────────────────
    total_transactions: int = 0
    account_age_days: int = 0
    last_transaction_at: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)

    # ── Méthodes de détection ─────────────────

    def is_new_device(self, device_id: str) -> bool:
        """True si ce device n'a jamais été vu pour ce client — signal SIM swap."""
        return device_id not in self.known_device_ids

    def is_new_zone(self, zone: str) -> bool:
        """True si le client n'a jamais transacté depuis cette zone."""
        return zone not in self.usual_zones

    def is_new_beneficiary(self, token: TokenHash) -> bool:
        """True si le client n'a jamais envoyé d'argent à ce bénéficiaire."""
        return token.value not in self.known_beneficiary_tokens

    def is_unusual_hour(self, hour: int) -> bool:
        """True si le client ne transacte jamais à cette heure normalement."""
        if not self.usual_hours:
            return False
        return hour not in self.usual_hours

    def is_unusual_channel(self, channel: Channel) -> bool:
        """
        True si le canal est inhabituel pour ce client.
        Ex: client qui utilise toujours l'app mobile → soudainement USSD.
        """
        if not self.usual_channels:
            return False
        return channel.value not in self.usual_channels

    def amount_z_score(self, amount: float) -> float:
        """
        Z-score du montant par rapport à l'historique du client.
        Z > 3  = très anormal (3 écarts-types au-dessus de la moyenne)
        Z > 5  = extrêmement suspect
        Z = 0  = parfaitement dans la moyenne

        Exemple:
            Client moyen = 8500 MRU, std = 2000 MRU
            Transaction  = 47000 MRU
            Z-score      = (47000 - 8500) / 2000 = 19.25 → TRÈS SUSPECT
        """
        if self.std_amount_7d == 0:
            return 0.0
        return (amount - self.avg_amount_7d) / self.std_amount_7d

    def is_dormant_account(self, days_threshold: int = 90) -> bool:
        if not self.last_transaction_at:
            return True
        now = datetime.utcnow()
        last = self.last_transaction_at
        if hasattr(last, 'tzinfo') and last.tzinfo is not None:
            from datetime import timezone
            now = datetime.now(timezone.utc)
        delta = now - last
        return delta.days >= days_threshold

    def is_new_account(self, days_threshold: int = 30) -> bool:
        """
        True si le compte a moins de X jours d'existence.
        Les comptes mules sont souvent créés récemment.
        """
        return self.account_age_days < days_threshold

    def __repr__(self) -> str:
        return (
            f"ClientProfile("
            f"token={self.client_token}, "
            f"operator={self.operator}, "
            f"avg_30d={self.avg_amount_30d:.0f} MRU, "
            f"tx_count={self.total_transactions}"
            f")"
        )