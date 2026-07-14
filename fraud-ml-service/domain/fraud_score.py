"""
HarisAI — Domain FraudScore
============================
Résultat du pipeline ML pour une transaction donnée.
Contient le score final, les scores individuels des 4 modèles,
et les raisons SHAP pour le compliance officer.

Immuable après création — garantit l'auditabilité BCM.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

from .enums import RiskLevel, FraudType
from .value_objects import TokenHash, ShapReason


# Seuils de décision — ajustables selon les besoins de l'opérateur
THRESHOLD_BLOCK  = 0.70   # Score >= 70% → BLOCK
THRESHOLD_REVIEW = 0.40   # Score >= 40% → REVIEW
                           # Score <  40% → APPROVE

# Poids des modèles dans le score ensemble
WEIGHT_XGBOOST   = 0.40   # Fraude temps réel — poids principal
WEIGHT_ISOFOREST = 0.20   # Anomalie non supervisée
WEIGHT_TFT       = 0.25   # Pattern temporel — AML
WEIGHT_GNN       = 0.15   # Réseau de comptes — blanchiment

# ── Dépassement à haute confiance (override) ──────────────
# Sous la seule moyenne pondérée ci-dessus, un modèle à poids faible
# peut être noyé même à confiance maximale : GNN seul à 1.0 ne produit
# que 1.0*0.15=0.15, sous THRESHOLD_REVIEW (0.40) — un GNN certain à
# 100% d'une fraude ne déclencherait même pas une revue humaine. Ce
# mécanisme corrige ça SANS donner un pouvoir de blocage unilatéral à
# des modèles pas encore validés en production (TFT/GNN — voir
# chapitre 6 de la doc technique, val_loss encore ~0.75-1.0 au moment
# de l'écriture) :
#
#   - XGBoost seul >= XGBOOST_OVERRIDE_THRESHOLD → force BLOCK
#     (seul modèle déjà mature — AUC-PR 0.7333, testé en profondeur)
#   - IsolationForest/TFT/GNN seul >= SECONDARY_MODEL_OVERRIDE_THRESHOLD
#     → force au MINIMUM REVIEW (jamais BLOCK directement) — un signal
#     fort mais pas encore assez validé pour bloquer seul, escalade
#     vers un humain plutôt que de décider seul.
#
# Ces deux seuils NE SONT PAS calibrés sur des données réelles — points
# de départ défendables (0.90 = confiance très élevée, pas juste
# "au-dessus de la moyenne"), à ajuster une fois des transactions
# réelles Bankily disponibles pour mesurer l'impact sur le taux de
# faux positifs. Documenté explicitement plutôt que présenté comme
# une valeur validée empiriquement.
XGBOOST_OVERRIDE_THRESHOLD          = 0.90
SECONDARY_MODEL_OVERRIDE_THRESHOLD  = 0.90

# Sévérité relative des RiskLevel — RiskLevel (str, Enum) n'a pas
# d'ordre naturel, nécessaire pour ne jamais RÉTROGRADER une décision
# déjà plus sévère que ce que l'override produirait (ex: la moyenne
# pondérée a déjà donné BLOCK — un override REVIEW ne doit jamais
# redescendre à REVIEW).
_RISK_LEVEL_SEVERITY = {
    RiskLevel.APPROVE: 0,
    RiskLevel.REVIEW: 1,
    RiskLevel.BLOCK: 2,
}


@dataclass
class FraudScore:
    """
    Score de fraude calculé par le pipeline ML HarisAI.

    Le score final est une combinaison pondérée des 4 modèles :
        final = XGBoost(40%) + IsoForest(20%) + TFT(25%) + GNN(15%)

    Exemple:
        score = FraudScore(
            transaction_id="BNK-2024-001",
            client_token=TokenHash("a3f9b2c1..."),
            final_score=0.91,
            risk_level=RiskLevel.BLOCK,
            xgboost_score=0.94,
            isolation_score=0.85,
            tft_score=0.88,
            gnn_score=0.72,
            suspected_fraud_type=FraudType.SIM_SWAPPING
        )
    """

    # ── Identité ──────────────────────────────
    transaction_id: str
    client_token: TokenHash

    # ── Score final ───────────────────────────
    final_score: float        # 0.0 → 1.0
    risk_level: RiskLevel     # APPROVE / REVIEW / BLOCK

    # ── Scores individuels des 4 modèles ──────
    xgboost_score: float = 0.0     # Fraude directe temps réel
    isolation_score: float = 0.0   # Anomalie inconnue
    tft_score: float = 0.0         # Pattern temporel (structuring)
    gnn_score: float = 0.0         # Réseau de comptes (layering)

    # ── Explication SHAP ──────────────────────
    shap_reasons: List[ShapReason] = field(default_factory=list)

    # ── Type de fraude suspectée ──────────────
    suspected_fraud_type: FraudType = FraudType.UNKNOWN

    # ── Méta ──────────────────────────────────
    model_version: str = "1.0.0"
    scored_at: datetime = field(default_factory=datetime.utcnow)
    inference_time_ms: float = 0.0

    def __post_init__(self):
        if not 0.0 <= self.final_score <= 1.0:
            raise ValueError(
                f"Score invalide : {self.final_score} — doit être entre 0.0 et 1.0"
            )

    # ── Propriétés ────────────────────────────

    @property
    def score_0_100(self) -> int:
        """Score converti en 0-100 pour l'affichage dans le dashboard React."""
        return int(self.final_score * 100)

    @property
    def is_fraud(self) -> bool:
        """True si la transaction est bloquée."""
        return self.risk_level == RiskLevel.BLOCK

    @property
    def needs_review(self) -> bool:
        """True si le compliance officer doit examiner cette transaction."""
        return self.risk_level == RiskLevel.REVIEW

    @property
    def is_approved(self) -> bool:
        """True si la transaction est approuvée automatiquement."""
        return self.risk_level == RiskLevel.APPROVE

    @property
    def top_reasons(self) -> List[ShapReason]:
        """
        Les 3 raisons SHAP les plus significatives.
        Affichées dans le dashboard React pour le compliance officer.
        """
        sorted_reasons = sorted(
            self.shap_reasons,
            key=lambda r: abs(r.contribution),
            reverse=True
        )
        return sorted_reasons[:3]

    @property
    def risk_reasons_fr(self) -> List[str]:
        """Liste des raisons en français — pour les rapports STR BCM."""
        return [r.human_readable_fr for r in self.top_reasons if r.increases_risk]

    @property
    def risk_reasons_ar(self) -> List[str]:
        """Liste des raisons en arabe — pour le dashboard RTL."""
        return [r.human_readable_ar for r in self.top_reasons if r.increases_risk]

    # ── Méthode de calcul ─────────────────────

    @classmethod
    def compute(
        cls,
        transaction_id: str,
        client_token: TokenHash,
        xgboost_score: float,
        isolation_score: float,
        tft_score: float,
        gnn_score: float,
        shap_reasons: List[ShapReason],
        suspected_fraud_type: FraudType,
        model_version: str,
        inference_time_ms: float = 0.0
    ) -> FraudScore:
        """
        Calcule le score ensemble pondéré et détermine le RiskLevel.

        Cette méthode centralise la logique de combinaison des scores —
        si on veut changer les poids, on change ici seulement.

        Le RiskLevel final n'est PAS uniquement dérivé de final_score :
        un mécanisme de dépassement à haute confiance peut l'escalader
        (jamais le rétrograder) si un modèle individuel est extrêmement
        confiant, même si sa contribution à la moyenne pondérée serait
        diluée par son poids — voir XGBOOST_OVERRIDE_THRESHOLD et
        SECONDARY_MODEL_OVERRIDE_THRESHOLD ci-dessus pour le détail.
        """
        final_score = (
            xgboost_score   * WEIGHT_XGBOOST   +
            isolation_score * WEIGHT_ISOFOREST  +
            tft_score       * WEIGHT_TFT        +
            gnn_score       * WEIGHT_GNN
        )

        # Clamp entre 0 et 1 pour éviter les erreurs numériques
        final_score = max(0.0, min(1.0, final_score))

        # Décision finale — moyenne pondérée
        if final_score >= THRESHOLD_BLOCK:
            risk_level = RiskLevel.BLOCK
        elif final_score >= THRESHOLD_REVIEW:
            risk_level = RiskLevel.REVIEW
        else:
            risk_level = RiskLevel.APPROVE

        # ── Dépassement à haute confiance ──────────────────
        # Voir la docstring des constantes ci-dessus pour le
        # raisonnement complet. N'AUGMENTE jamais la sévérité au-delà
        # de ce que l'override autorise (XGBoost peut forcer BLOCK,
        # les 3 autres modèles seuls ne forcent jamais plus que REVIEW)
        # et ne RÉTROGRADE jamais une décision déjà plus sévère que
        # l'override (via _RISK_LEVEL_SEVERITY).
        override_level = None
        if xgboost_score >= XGBOOST_OVERRIDE_THRESHOLD:
            override_level = RiskLevel.BLOCK
        elif (
            isolation_score >= SECONDARY_MODEL_OVERRIDE_THRESHOLD or
            tft_score       >= SECONDARY_MODEL_OVERRIDE_THRESHOLD or
            gnn_score       >= SECONDARY_MODEL_OVERRIDE_THRESHOLD
        ):
            override_level = RiskLevel.REVIEW

        if (
            override_level is not None and
            _RISK_LEVEL_SEVERITY[override_level] > _RISK_LEVEL_SEVERITY[risk_level]
        ):
            risk_level = override_level

        return cls(
            transaction_id=transaction_id,
            client_token=client_token,
            final_score=final_score,
            risk_level=risk_level,
            xgboost_score=xgboost_score,
            isolation_score=isolation_score,
            tft_score=tft_score,
            gnn_score=gnn_score,
            shap_reasons=shap_reasons,
            suspected_fraud_type=suspected_fraud_type,
            model_version=model_version,
            inference_time_ms=inference_time_ms
        )

    def __repr__(self) -> str:
        return (
            f"FraudScore("
            f"tx={self.transaction_id}, "
            f"score={self.score_0_100}/100, "
            f"decision={self.risk_level.value}, "
            f"type={self.suspected_fraud_type.value}, "
            f"time={self.inference_time_ms:.1f}ms"
            f")"
        )