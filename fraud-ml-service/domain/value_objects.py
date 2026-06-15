"""
HarisAI — Domain Value Objects
================================
Les value objects sont immuables (frozen=True) et n'ont pas d'identité propre.
Deux Money(8500, MRU) sont identiques — contrairement à deux Transaction distinctes.
"""

from __future__ import annotations
from dataclasses import dataclass
from .enums import Currency


@dataclass(frozen=True)
class Money:
    """
    Représente un montant monétaire immuable.
    frozen=True → hashable, comparable, thread-safe.

    Exemple:
        montant = Money(8500.0, Currency.MRU)
        print(montant)  → 8,500.00 MRU
    """
    amount: float
    currency: Currency = Currency.MRU

    def __post_init__(self):
        if self.amount < 0:
            raise ValueError(
                f"Montant négatif interdit : {self.amount} {self.currency.value}"
            )

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(
                f"Impossible d'additionner {self.currency} et {other.currency}"
            )
        return Money(self.amount + other.amount, self.currency)

    def is_above_bcm_threshold(self, threshold: float = 10_000.0) -> bool:
        """
        Vérifie si le montant dépasse le seuil déclaratoire BCM.
        Au-dessus de ce seuil, un rapport STR peut être exigé.
        """
        return self.amount >= threshold

    def ratio_to(self, other: Money) -> float:
        """
        Calcule le ratio entre ce montant et un montant de référence.
        Utilisé pour détecter les virements qui représentent
        une grande partie du solde habituel du client.

        Exemple:
            montant_habituel = Money(8500.0)
            montant_suspect  = Money(47000.0)
            ratio = montant_suspect.ratio_to(montant_habituel)  → 5.53
        """
        if other.amount == 0:
            return 0.0
        return self.amount / other.amount

    def __repr__(self) -> str:
        return f"{self.amount:,.2f} {self.currency.value}"


@dataclass(frozen=True)
class TokenHash:
    """
    Hash SHA-256 anonymisant l'identité d'un client ou bénéficiaire.
    Les données brutes (nom, numéro de téléphone) n'entrent
    jamais dans le système ML — seulement leur hash.

    Exemple:
        token = TokenHash("a3f9b2c1d4e5f6a7b8c9d0e1f2a3b4c5...")
        print(token)  → token:a3f9b2c1...
    """
    value: str

    def __post_init__(self):
        if not self.value or len(self.value) < 8:
            raise ValueError(
                f"Token hash invalide — trop court : '{self.value}'"
            )

    def short(self) -> str:
        """Version courte pour les logs — 8 premiers caractères."""
        return self.value[:8]

    def __repr__(self) -> str:
        return f"token:{self.short()}..."


@dataclass(frozen=True)
class ShapReason:
    """
    Une raison SHAP expliquant pourquoi le modèle a donné ce score.
    Chaque feature contribue positivement ou négativement au score final.

    Exemple:
        ShapReason(
            feature_name="sim_changed_72h",
            contribution=+0.42,
            human_readable_fr="SIM changée il y a moins de 72h",
            human_readable_ar="تم تغيير الشريحة منذ أقل من 72 ساعة"
        )
    """
    feature_name: str        # Nom technique de la feature
    contribution: float      # Positif = augmente le risque · Négatif = réduit
    human_readable_fr: str   # Explication en français pour le dashboard
    human_readable_ar: str   # Explication en arabe pour le dashboard

    @property
    def increases_risk(self) -> bool:
        """True si cette feature augmente le risque de fraude."""
        return self.contribution > 0

    @property
    def is_significant(self) -> bool:
        """True si la contribution est significative (> 0.05)."""
        return abs(self.contribution) > 0.05

    def __repr__(self) -> str:
        sign = "+" if self.contribution > 0 else ""
        return f"{sign}{self.contribution:.3f} → {self.human_readable_fr}"