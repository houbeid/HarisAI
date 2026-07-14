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
        """
        True si le compte est inactif depuis plus de X jours.
        Un compte dormant réactivé soudainement = signal AML classique.
        """
        if not self.last_transaction_at:
            return True
        # Gère les deux cas : datetime avec et sans timezone
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


@dataclass
class BeneficiaryProfile:
    """
    Profil comportemental d'un BÉNÉFICIAIRE — stocké dans Redis avec TTL 90 jours.

    Symétrique à ClientProfile, mais du point de vue inverse : ClientProfile
    répond à "à qui ce client envoie-t-il habituellement de l'argent ?",
    BeneficiaryProfile répond à "qui envoie habituellement de l'argent à
    ce compte, et que devient cet argent une fois reçu ?".

    Cette distinction est nécessaire pour détecter les comptes mules sans
    confondre avec un marchand légitime. Un supermarché, une boutique ou un
    restaurant affilié à Bankily reçoit lui aussi de très nombreux clients
    différents chaque jour — ce qui est entièrement normal pour son activité.
    Ce qui distingue une mule n'est pas le nombre d'expéditeurs différents
    seul, mais la combinaison de ce nombre avec l'absence de statut marchand
    ET la vitesse à laquelle l'argent reçu est reversé ou retiré.

    Mis à jour après chaque transaction reçue et confirmée comme légitime.
    """

    beneficiary_token: TokenHash
    operator: str  # BANKILY, SEDAD, MASRVI

    # ── Expéditeurs ────────────────────────────
    known_sender_tokens: list = field(default_factory=list)
    distinct_senders_30d: int = 0
    # Nombre d'expéditeurs DIFFÉRENTS dans les 30 derniers jours.
    # Glissant — remis à jour à chaque transaction reçue, pas juste
    # accumulé indéfiniment, pour ne pas pénaliser un vieux marchand
    # actif depuis des années avec un total historique énorme.

    # ── Statistiques montants reçus ───────────
    avg_amount_received_30d: float = 0.0
    total_received_30d: float = 0.0

    # ── Vélocité de sortie — coeur du signal mule ─
    last_received_at: Optional[datetime] = None
    last_outflow_at: Optional[datetime] = None
    # last_outflow_at : dernière fois que CE compte a lui-même envoyé
    # de l'argent (devient expéditeur dans une autre transaction).
    # Un grand écart entre last_received_at et last_outflow_at suivant
    # immédiatement = argent qui transite vite, signal mule classique.

    # ── Méta compte ─────────────────────────────
    total_transactions_received: int = 0
    account_age_days: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    # ── Méthodes de détection ───────────────────

    def is_new_sender(self, token: TokenHash) -> bool:
        """True si ce compte n'a jamais reçu d'argent de cet expéditeur."""
        return token.value not in self.known_sender_tokens

    def fan_in_ratio(self) -> float:
        """
        Ratio expéditeurs distincts / transactions reçues.

        Proche de 1.0 → presque chaque transaction vient d'un expéditeur
        différent (profil mule typique : beaucoup de petites sources
        distinctes, rarement les mêmes clients qui reviennent).

        Proche de 0.0 → les mêmes expéditeurs reviennent régulièrement
        (profil marchand typique : clients fidèles, achats répétés).
        """
        if self.total_transactions_received == 0:
            return 0.0
        return self.distinct_senders_30d / self.total_transactions_received

    def has_high_fan_in(self, threshold: int = 15) -> bool:
        """
        True si ce compte a reçu de beaucoup d'expéditeurs différents
        récemment. Seuil volontairement plus permissif que many_beneficiaries
        côté expéditeur, car un compte peut légitimement recevoir de
        plusieurs sources (famille, remboursements) sans être un marchand
        ni une mule — le seuil seul ne suffit jamais, voir is_likely_mule().
        """
        return self.distinct_senders_30d > threshold

    def outflow_speed_hours(self) -> Optional[float]:
        """
        Délai en heures entre la dernière réception et la dernière sortie
        de fonds qui la suit. None si aucune sortie n'a encore eu lieu
        après la dernière réception (l'argent est resté sur le compte).

        Un délai court et répété est le signal le plus fort de compte mule :
        l'argent ne fait que transiter, il ne s'accumule jamais réellement.
        """
        if not self.last_received_at or not self.last_outflow_at:
            return None
        if self.last_outflow_at < self.last_received_at:
            # La dernière sortie a eu lieu AVANT la dernière réception
            # → pas de sortie consécutive à mesurer pour l'instant
            return None
        delta = self.last_outflow_at - self.last_received_at
        return delta.total_seconds() / 3600

    def is_likely_mule(
        self,
        is_merchant: bool,
        fan_in_threshold: int = 15,
        outflow_hours_threshold: float = 24.0,
    ) -> bool:
        """
        Combine les trois signaux nécessaires pour suspecter un compte mule,
        plutôt que de se fier à un seul critère qui confondrait un marchand
        légitime avec une mule.

        Conditions réunies :
            1. Fan-in élevé      — reçoit de nombreuses sources différentes
            2. PAS marchand      — un vrai marchand déclaré est exclu d'office
            3. Sortie rapide     — l'argent reçu repart vite, ne s'accumule pas

        Un supermarché avec un fan-in élevé mais beneficiary_is_merchant=True
        et qui garde ses fonds (pas de sortie rapide) ne sera jamais flaggé
        par cette méthode, même avec des centaines de clients par jour.
        """
        if is_merchant:
            return False
        if not self.has_high_fan_in(fan_in_threshold):
            return False
        outflow = self.outflow_speed_hours()
        if outflow is None:
            return False
        return outflow <= outflow_hours_threshold

    def __repr__(self) -> str:
        return (
            f"BeneficiaryProfile("
            f"token={self.beneficiary_token}, "
            f"operator={self.operator}, "
            f"distinct_senders_30d={self.distinct_senders_30d}, "
            f"tx_received={self.total_transactions_received}"
            f")"
        )