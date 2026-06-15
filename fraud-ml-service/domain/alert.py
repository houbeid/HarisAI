"""
HarisAI — Domain Alert
========================
Alerte générée quand FraudScore indique REVIEW ou BLOCK.
Envoyée au compliance officer via le dashboard React.
Utilisée pour générer les rapports STR pour la BCM.

Le workflow :
    Transaction analysée → Score REVIEW/BLOCK
    → Alert créée → Compliance officer notifié
    → Compliance officer confirme (fraude) ou rejette (faux positif)
    → Si confirmée → Rapport STR généré et envoyé à la BCM
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .enums import AlertPriority, AlertStatus, FraudType
from .transaction import Transaction
from .fraud_score import FraudScore


@dataclass
class Alert:
    """
    Alerte de fraude ou de blanchiment à traiter par le compliance officer.

    Exemple:
        alert = Alert(
            alert_id="ALT-2024-001",
            transaction=tx,
            fraud_score=score
        )
        print(alert.priority)   → CRITICAL
        print(alert.is_pending) → True

        # Compliance officer confirme
        alert.confirm_fraud(reviewed_by="officer_123", notes="SIM swap confirmé")
        print(alert.status)     → CONFIRMED
    """

    # ── Identité ──────────────────────────────
    alert_id: str
    transaction: Transaction
    fraud_score: FraudScore

    # ── Workflow compliance ────────────────────
    status: AlertStatus = AlertStatus.PENDING
    reviewed_by: Optional[str] = None       # ID du compliance officer
    reviewed_at: Optional[datetime] = None
    compliance_notes: Optional[str] = None

    # ── Rapport STR BCM ───────────────────────
    str_report_generated: bool = False
    str_report_path: Optional[str] = None   # Chemin du PDF généré
    str_submitted_at: Optional[datetime] = None

    # ── Méta ──────────────────────────────────
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if not self.alert_id:
            raise ValueError("alert_id est obligatoire")

    # ── Propriétés ────────────────────────────

    @property
    def is_pending(self) -> bool:
        """True si l'alerte n'a pas encore été traitée."""
        return self.status == AlertStatus.PENDING

    @property
    def is_confirmed_fraud(self) -> bool:
        """True si le compliance officer a confirmé la fraude."""
        return self.status == AlertStatus.CONFIRMED

    @property
    def is_false_positive(self) -> bool:
        """True si le compliance officer a indiqué un faux positif."""
        return self.status == AlertStatus.FALSE_POSITIVE

    @property
    def priority(self) -> AlertPriority:
        """
        Priorité calculée depuis le score — pour le tri dans le dashboard.
        CRITICAL → traiter immédiatement
        HIGH     → traiter dans l'heure
        MEDIUM   → traiter dans la journée
        LOW      → traiter en fin de journée
        """
        score = self.fraud_score.score_0_100
        if score >= 85:
            return AlertPriority.CRITICAL
        elif score >= 70:
            return AlertPriority.HIGH
        elif score >= 50:
            return AlertPriority.MEDIUM
        return AlertPriority.LOW

    @property
    def fraud_type(self) -> FraudType:
        """Type de fraude suspectée — délégué au FraudScore."""
        return self.fraud_score.suspected_fraud_type

    @property
    def requires_str_report(self) -> bool:
        """
        True si un rapport STR doit être généré pour la BCM.
        Obligatoire pour les fraudes AML confirmées.
        """
        aml_types = {
            FraudType.STRUCTURING,
            FraudType.LAYERING,
            FraudType.MULE_ACCOUNT,
        }
        return (
            self.is_confirmed_fraud and
            self.fraud_type in aml_types and
            not self.str_report_generated
        )

    @property
    def response_time_minutes(self) -> Optional[float]:
        """Temps de réponse du compliance officer en minutes."""
        if not self.reviewed_at:
            return None
        delta = self.reviewed_at - self.created_at
        return delta.total_seconds() / 60

    # ── Actions workflow ──────────────────────

    def confirm_fraud(
        self,
        reviewed_by: str,
        notes: str = ""
    ) -> None:
        """
        Le compliance officer confirme que c'est une vraie fraude.
        Déclenche la génération du rapport STR si applicable.
        """
        if not self.is_pending:
            raise ValueError(
                f"Impossible de confirmer — alerte déjà traitée : {self.status}"
            )
        self.status = AlertStatus.CONFIRMED
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.utcnow()
        self.compliance_notes = notes

    def mark_false_positive(
        self,
        reviewed_by: str,
        notes: str = ""
    ) -> None:
        """
        Le compliance officer indique que c'est un faux positif.
        Ces données servent à améliorer le modèle ML.
        """
        if not self.is_pending:
            raise ValueError(
                f"Impossible de marquer — alerte déjà traitée : {self.status}"
            )
        self.status = AlertStatus.FALSE_POSITIVE
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.utcnow()
        self.compliance_notes = notes

    def mark_str_generated(self, report_path: str) -> None:
        """Marque le rapport STR comme généré et enregistre son chemin."""
        self.str_report_generated = True
        self.str_report_path = report_path
        self.str_submitted_at = datetime.utcnow()

    def __repr__(self) -> str:
        return (
            f"Alert("
            f"id={self.alert_id}, "
            f"score={self.fraud_score.score_0_100}/100, "
            f"priority={self.priority.value}, "
            f"status={self.status.value}, "
            f"type={self.fraud_type.value}"
            f")"
        )