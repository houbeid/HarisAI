"""
HarisAI — Use Case : AnalyzeTransaction
=========================================
Le use case principal du système HarisAI.
Il orchestre tout le pipeline ML pour une transaction donnée :

    1. Récupérer le profil client (Redis)
    2. Calculer les features (feature engineering)
    3. Scores des 4 modèles ML (XGBoost, IsoForest, TFT, GNN)
    4. Score ensemble final (0-100)
    5. Explication SHAP
    6. Créer l'alerte si REVIEW ou BLOCK
    7. Logger dans l'audit trail (BCM)
    8. Mettre à jour le profil si APPROVE

Ce use case ne connaît PAS :
    - Redis (il utilise IProfileStore)
    - XGBoost (il utilise IFraudModel)
    - SHAP (il utilise IExplainer)
    - PostgreSQL (il utilise IAuditStore)

Il ne connaît QUE les interfaces — c'est la Clean Architecture.
"""

from __future__ import annotations
import asyncio
import time
import uuid
import logging
from dataclasses import dataclass
from typing import List, Optional

from domain import (
    Transaction,
    ClientProfile,
    FraudScore,
    Alert,
    ShapReason,
    RiskLevel,
    FraudType,
)

from application.ports import (
    IFraudModel,
    IExplainableModel,
    IProfileStore,
    IExplainer,
    IAuditStore,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# INPUT / OUTPUT — contrats du use case
# ─────────────────────────────────────────────

@dataclass
class AnalyzeTransactionInput:
    """
    Input du use case — reçu depuis la couche Presentation (FastAPI).
    Contient la transaction et les features pré-calculées par .NET.
    """
    transaction: Transaction
    # Features déjà calculées par .NET avant d'envoyer à FastAPI
    # (évite de recalculer des choses que .NET connaît déjà)
    pre_computed_features: Optional[dict] = None


@dataclass
class AnalyzeTransactionOutput:
    """
    Output du use case — retourné à la couche Presentation.
    Contient tout ce dont le .NET a besoin pour prendre une décision.
    """
    fraud_score: FraudScore
    alert: Optional[Alert]       # None si APPROVE
    profile_updated: bool        # True si le profil client a été mis à jour
    total_time_ms: float         # Temps total d'exécution


# ─────────────────────────────────────────────
# FEATURE ENGINEERING — mapping simple ici
# (la vraie logique est dans infrastructure/ml/features/)
# ─────────────────────────────────────────────

def _build_features(
    transaction: Transaction,
    profile: ClientProfile,
    pre_computed: Optional[dict] = None
) -> dict:
    """
    Construit le dictionnaire de features pour les modèles ML.
    Combine les features calculées ici et celles pré-calculées par .NET.
    """
    features = {
        # ── Features transaction ─────────────
        "amount":              transaction.amount.amount,
        "hour_of_day":         transaction.hour_of_day,
        "day_of_week":         transaction.day_of_week,
        "is_night":            transaction.is_night_transaction,
        "is_weekend":          transaction.is_weekend,
        "is_ussd":             transaction.is_ussd_channel,
        "is_agent":            transaction.is_agent_channel,
        "sim_changed_72h":     transaction.sim_changed_72h,

        # ── Features profil client ────────────
        "amount_z_score":      profile.amount_z_score(transaction.amount.amount),
        "is_new_device":       profile.is_new_device(transaction.device_id),
        "is_new_zone":         profile.is_new_zone(transaction.zone),
        "is_unusual_hour":     profile.is_unusual_hour(transaction.hour_of_day),
        "is_unusual_channel":  profile.is_unusual_channel(transaction.channel),
        "is_dormant_account":  profile.is_dormant_account(),
        "is_new_account":      profile.is_new_account(),
        "account_age_days":    profile.account_age_days,
        "total_transactions":  profile.total_transactions,
        "avg_amount_7d":       profile.avg_amount_7d,
        "avg_amount_30d":      profile.avg_amount_30d,

        # ── Features bénéficiaire ─────────────
        "is_new_beneficiary": (
            profile.is_new_beneficiary(transaction.beneficiary_token)
            if transaction.beneficiary_token else False
        ),
        "beneficiary_is_merchant": transaction.beneficiary_is_merchant,

        # ── Feature ratio solde ───────────────
        "ratio_to_avg": (
            transaction.amount.amount / profile.avg_amount_30d
            if profile.avg_amount_30d > 0 else 0.0
        ),
    }

    # Merge avec les features pré-calculées par .NET
    if pre_computed:
        features.update(pre_computed)

    return features


def _detect_fraud_type(
    transaction: Transaction,
    profile: ClientProfile,
    features: dict,
    xgboost_score: float
) -> FraudType:
    """
    Heuristique pour déterminer le type de fraude le plus probable.
    Utilisé pour le rapport STR BCM et le dashboard compliance.

    Règles par priorité décroissante :
    1. SIM swap + nouveau device + nuit → SIM_SWAPPING
    2. USSD inhabituel + montant élevé → USSD_SCAM
    3. Montants répétitifs sous seuil → STRUCTURING
    4. Agent + comportement anormal → FRAUDULENT_AGENT
    5. Compte mule (reçoit + transfère immédiat) → MULE_ACCOUNT
    6. Marchand récent → FAKE_MERCHANT
    7. Reste → UNUSUAL_BEHAVIOR
    """
    # SIM Swapping — signal le plus fort
    if (
        transaction.sim_changed_72h and
        features.get("is_new_device") and
        features.get("amount_z_score", 0) > 3
    ):
        return FraudType.SIM_SWAPPING

    # Arnaque USSD — canal inhabituel + montant élevé
    if (
        transaction.is_ussd_channel and
        features.get("is_unusual_channel") and
        features.get("amount_z_score", 0) > 2
    ):
        return FraudType.USSD_SCAM

    # Agent frauduleux
    if (
        transaction.is_agent_channel and
        features.get("is_unusual_channel") and
        xgboost_score > 0.7
    ):
        return FraudType.FRAUDULENT_AGENT

    # Faux marchand — nouveau marchand avec gros volume
    if (
        transaction.beneficiary_is_merchant and
        features.get("is_new_beneficiary") and
        features.get("amount_z_score", 0) > 2
    ):
        return FraudType.FAKE_MERCHANT

    # Compte mule — compte nouveau qui reçoit et transfère
    if (
        features.get("is_new_account") and
        features.get("ratio_to_avg", 0) > 5
    ):
        return FraudType.MULE_ACCOUNT

    return FraudType.UNUSUAL_BEHAVIOR


def _build_shap_reasons(raw_explanations: List[dict]) -> List[ShapReason]:
    """
    Convertit les explications brutes de l'explainer en ShapReason.
    Filtre les contributions non significatives (< 0.05).
    """
    reasons = []
    for exp in raw_explanations:
        reason = ShapReason(
            feature_name=exp["feature_name"],
            contribution=exp["contribution"],
            human_readable_fr=exp.get("readable_fr", exp["feature_name"]),
            human_readable_ar=exp.get("readable_ar", exp["feature_name"]),
        )
        if reason.is_significant:
            reasons.append(reason)
    return reasons


# ─────────────────────────────────────────────
# USE CASE PRINCIPAL
# ─────────────────────────────────────────────

class AnalyzeTransactionUseCase:
    """
    Orchestrateur principal du pipeline ML HarisAI.

    Injection de dépendances dans le constructeur — jamais d'instanciation
    directe des dépendances ici. Tout vient de l'extérieur (DI container).

    Exemple d'utilisation :
        use_case = AnalyzeTransactionUseCase(
            xgboost_model=xgboost,
            isolation_model=isoforest,
            tft_model=tft,
            gnn_model=gnn,
            profile_store=redis_store,
            explainer=shap_explainer,
            audit_store=postgres_audit,
        )
        result = await use_case.execute(input_data)
    """

    def __init__(
        self,
        xgboost_model: IExplainableModel,
        isolation_model: IFraudModel,
        tft_model: IFraudModel,
        gnn_model: IFraudModel,
        profile_store: IProfileStore,
        explainer: IExplainer,
        audit_store: IAuditStore,
    ):
        self._xgboost = xgboost_model
        self._isolation = isolation_model
        self._tft = tft_model
        self._gnn = gnn_model
        self._profile_store = profile_store
        self._explainer = explainer
        self._audit = audit_store

    async def execute(
        self,
        input_data: AnalyzeTransactionInput
    ) -> AnalyzeTransactionOutput:
        """
        Pipeline complet d'analyse d'une transaction.
        Cible : < 200ms de bout en bout.
        """
        start_time = time.monotonic()
        tx = input_data.transaction

        logger.info(
            "Analyse transaction",
            extra={
                "transaction_id": tx.transaction_id,
                "operator": tx.operator,
                "amount": tx.amount.amount,
                "channel": tx.channel.value,
            }
        )

        # ── Étape 1 : Récupérer le profil client ──
        profile = await self._profile_store.get(
            client_token=tx.client_token,
            operator=tx.operator
        )

        if profile is None:
            # Nouveau client — créer un profil vide
            logger.info(
                "Nouveau client — profil vide créé",
                extra={"client_token": tx.client_token.short()}
            )
            profile = await self._profile_store.create_default(
                client_token=tx.client_token,
                operator=tx.operator
            )

        # ── Étape 2 : Calculer les features ───────
        features = _build_features(
            transaction=tx,
            profile=profile,
            pre_computed=input_data.pre_computed_features
        )

        # ── Étape 3 : Scores des 4 modèles ────────
        # asyncio.gather() lance les 4 prédictions EN PARALLÈLE
        # Gain de temps : 4 × 10ms séquentiel → ~10ms parallèle
        (
            xgboost_score,
            isolation_score,
            tft_score,
            gnn_score,
        ) = await asyncio.gather(
            self._xgboost.predict(tx, profile, features),
            self._isolation.predict(tx, profile, features),
            self._tft.predict(tx, profile, features),
            self._gnn.predict(tx, profile, features),
        )

        # ── Étape 4 : Explication SHAP ────────────
        raw_explanations = await self._explainer.explain(
            transaction=tx,
            profile=profile,
            features=features,
            raw_score=xgboost_score
        )
        shap_reasons = _build_shap_reasons(raw_explanations)

        # ── Étape 5 : Type de fraude ───────────────
        fraud_type = _detect_fraud_type(tx, profile, features, xgboost_score)

        # ── Étape 6 : Score ensemble final ────────
        inference_time_ms = (time.monotonic() - start_time) * 1000

        fraud_score = FraudScore.compute(
            transaction_id=tx.transaction_id,
            client_token=tx.client_token,
            xgboost_score=xgboost_score,
            isolation_score=isolation_score,
            tft_score=tft_score,
            gnn_score=gnn_score,
            shap_reasons=shap_reasons,
            suspected_fraud_type=fraud_type,
            model_version=self._xgboost.model_version,
            inference_time_ms=inference_time_ms,
        )

        logger.info(
            "Score calculé",
            extra={
                "transaction_id": tx.transaction_id,
                "score": fraud_score.score_0_100,
                "decision": fraud_score.risk_level.value,
                "fraud_type": fraud_type.value,
                "time_ms": round(inference_time_ms, 1),
            }
        )

        # ── Étape 7 : Créer l'alerte si nécessaire ─
        alert = None
        if fraud_score.risk_level in (RiskLevel.REVIEW, RiskLevel.BLOCK):
            alert = Alert(
                alert_id=f"ALT-{uuid.uuid4().hex[:12].upper()}",
                transaction=tx,
                fraud_score=fraud_score,
            )
            logger.warning(
                "Alerte créée",
                extra={
                    "alert_id": alert.alert_id,
                    "priority": alert.priority.value,
                    "decision": fraud_score.risk_level.value,
                }
            )

        # ── Étape 8 : Audit trail BCM ─────────────
        await self._audit.log_score(
            transaction=tx,
            score=fraud_score
        )
        if alert:
            await self._audit.log_alert(alert)

        # ── Étape 9 : Mettre à jour le profil ─────
        # Seulement pour les transactions approuvées
        # (on n'apprend pas le comportement des fraudeurs)
        profile_updated = False
        if fraud_score.risk_level == RiskLevel.APPROVE:
            await self._profile_store.update(
                profile=profile,
                transaction=tx
            )
            profile_updated = True

        total_time_ms = (time.monotonic() - start_time) * 1000

        logger.info(
            "Analyse terminée",
            extra={
                "transaction_id": tx.transaction_id,
                "total_time_ms": round(total_time_ms, 1),
            }
        )

        return AnalyzeTransactionOutput(
            fraud_score=fraud_score,
            alert=alert,
            profile_updated=profile_updated,
            total_time_ms=total_time_ms,
        )