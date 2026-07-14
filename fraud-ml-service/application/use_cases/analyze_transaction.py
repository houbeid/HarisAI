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
    BeneficiaryProfile,
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
    IBeneficiaryStore,
    IExplainer,
    IAuditStore,
)

logger = logging.getLogger(__name__)

# Zone de structuring — juste sous le seuil de déclaration BCM (10 000 MRU).
# DUPLIQUÉ depuis infrastructure/ml/features/feature_engineering.py
# (STRUCTURING_LOWER/STRUCTURING_UPPER) plutôt qu'importé — application/
# ne doit pas dépendre de infrastructure/ (Clean Architecture, les
# dépendances pointent vers l'intérieur). Contrairement aux 4 formules
# AML dupliquées dans _aml_features_subset(), ce sont deux CONSTANTES
# NUMÉRIQUES fixes, sans risque de divergence de comportement comme
# celui documenté pour ratio_to_avg (addendum 10.6) — dupliquer un
# nombre ne peut pas diverger silencieusement de la même façon qu'une
# formule avec valeur par défaut implicite.
STRUCTURING_LOWER = 9_000.0
STRUCTURING_UPPER = 9_990.0


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

def _aml_features_subset(
    transaction: Transaction,
    profile: ClientProfile,
    is_new_beneficiary: bool,
) -> dict:
    """
    Calcule 4 des 7 AML_FEATURE_NAMES — tx_velocity_ratio,
    amount_cumul_ratio, rapid_transfer_flag, many_beneficiaries_flag.

    DUPLIQUÉE depuis FeatureEngineering._aml_features()
    (infrastructure/ml/features/feature_engineering.py) plutôt
    qu'appelée directement — voir la NOTE SUR LA DUPLICATION dans la
    docstring de _build_features() pour la raison (incohérence
    ratio_to_avg entre production et training, voir addendum 10.6 de
    la doc technique). Ces 4 formules ne dépendent PAS de ratio_to_avg,
    donc les dupliquer ici ne pose pas ce même risque.

    Si _aml_features() change un jour, ces formules doivent être
    répercutées ici manuellement — pas de garantie automatique de
    synchronisation entre les deux (c'est précisément le problème que
    l'addendum 10.6 documente et propose de résoudre plus tard).
    """
    amount = transaction.amount.amount

    # 1. Vélocité — rythme transactions vs habitude
    avg_tx_per_day = max(
        profile.total_transactions / max(profile.account_age_days, 1),
        0.1
    )
    recent_tx_estimate = min(profile.total_transactions, 10)
    tx_velocity_ratio = recent_tx_estimate / (avg_tx_per_day * 30 + 1)

    # 2. Cumul 24h — structuring sur la journée
    monthly_avg = max(profile.avg_amount_30d, 1.0)
    estimated_daily_cumul = amount * max(recent_tx_estimate / 30, 1)
    amount_cumul_ratio = estimated_daily_cumul / (monthly_avg * 3 + 1)

    # 3. Retransfert rapide — compte mule
    rapid_transfer_flag = float(
        is_new_beneficiary and
        transaction.is_night_transaction and
        amount > profile.avg_amount_30d * 2
    )

    # 4. Trop de bénéficiaires différents
    known_beneficiaries = len(profile.known_beneficiary_tokens)
    many_beneficiaries_flag = float(
        known_beneficiaries > 20 and is_new_beneficiary
    )

    return {
        "tx_velocity_ratio": float(tx_velocity_ratio),
        "amount_cumul_ratio": float(amount_cumul_ratio),
        "rapid_transfer_flag": rapid_transfer_flag,
        "many_beneficiaries_flag": many_beneficiaries_flag,
    }


def _build_features(
    transaction: Transaction,
    profile: ClientProfile,
    pre_computed: Optional[dict] = None,
    beneficiary_profile: Optional[BeneficiaryProfile] = None,
) -> dict:
    """
    Construit le dictionnaire de features pour les modèles ML.
    Combine les features calculées ici et celles pré-calculées par .NET.

    Args:
        beneficiary_profile : profil du destinataire de la transaction
            (optionnel). Permet de calculer is_mule_pattern — sans lui,
            cette feature vaut 0.0 par défaut (voir plus bas), exactement
            comme FeatureEngineering.compute() le fait déjà côté training.

    NOTE SUR LA DUPLICATION AVEC FeatureEngineering.compute() (training) :
        Cette fonction NE PEUT PAS être remplacée par un appel direct à
        FeatureEngineering.compute() — ratio_to_avg y a une valeur par
        défaut différente (1.0) de celle utilisée ici (0.0) quand le
        client n'a pas d'historique, et aucun des 5 loaders d'entraînement
        ne s'accorde non plus entre eux sur cette valeur. Remplacer 0.0
        par 1.0 changerait silencieusement le comportement de XGBoost en
        production sans certitude que ce soit plus correct. Voir addendum
        10.6 de la doc technique pour le détail complet et la marche à
        suivre avant de pouvoir unifier les deux fonctions.

        Les 4 features AML ci-dessous (tx_velocity_ratio,
        amount_cumul_ratio, rapid_transfer_flag, many_beneficiaries_flag)
        sont donc dupliquées ICI depuis _aml_features() plutôt que
        d'appeler cette dernière — aucune des 4 formules ne dépend de
        ratio_to_avg, donc pas de risque supplémentaire à les dupliquer
        ponctuellement en attendant la résolution de l'incohérence
        ci-dessus. Si _aml_features() change un jour, ces 4 formules
        doivent être répercutées ici manuellement.
    """
    is_new_benef = bool(
        transaction.beneficiary_token and
        profile.is_new_beneficiary(transaction.beneficiary_token)
    )

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
        "is_new_beneficiary": is_new_benef,
        "beneficiary_is_merchant": transaction.beneficiary_is_merchant,

        # ── Feature ratio solde ───────────────
        "ratio_to_avg": (
            transaction.amount.amount / profile.avg_amount_30d
            if profile.avg_amount_30d > 0 else 0.0
        ),

        # ── Features AML supplémentaires (TFT + GNN uniquement) ──
        # Dupliquées depuis FeatureEngineering._aml_features() — voir
        # NOTE SUR LA DUPLICATION dans la docstring de cette fonction.
        # near_threshold_flag et round_amount_flag ne sont PAS incluses
        # ici : elles ne font pas partie de TFT_FEATURE_NAMES/
        # GNN_FEATURE_NAMES (seuils MRU non entraînables sur IBM AML —
        # voir ibm_aml_loader.py::load_with_aml_features()).
        **_aml_features_subset(transaction, profile, is_new_benef),

        # ── Compte mule (AML — dépend du profil bénéficiaire) ──
        # is_mule_pattern combine fan-in élevé + non-marchand + sortie
        # rapide des fonds (voir BeneficiaryProfile.is_likely_mule()).
        # Sans beneficiary_profile (ex: nouveau bénéficiaire jamais vu,
        # ou store non disponible), vaut 0.0 par défaut — compatibilité
        # ascendante avec le comportement déjà établi dans
        # FeatureEngineering.compute() côté training.
        "is_mule_pattern": float(
            beneficiary_profile.is_likely_mule(
                is_merchant=transaction.beneficiary_is_merchant
            )
            if beneficiary_profile is not None
            else False
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
    xgboost_score: float,
    beneficiary_profile: Optional[BeneficiaryProfile] = None,
) -> FraudType:
    """
    Heuristique pour déterminer le type de fraude le plus probable.
    Utilisé pour le rapport STR BCM et le dashboard compliance.

    Règles par priorité décroissante :
    1. SIM swap + nouveau device + nuit → SIM_SWAPPING
    2. Nouveau device + nouvelle zone, SANS SIM swap → ACCOUNT_TAKEOVER
    3. USSD inhabituel + montant élevé → USSD_SCAM
    4. Agent + comportement anormal → FRAUDULENT_AGENT
    5. Marchand récent → FAKE_MERCHANT
    6. Montant proche du seuil BCM + vélocité élevée → STRUCTURING
    7. Compte mule (fan-in + non-marchand + sortie rapide) → MULE_ACCOUNT
    8. Reste → UNUSUAL_BEHAVIOR

    LAYERING (dans FraudType) N'A DÉLIBÉRÉMENT PAS de règle ici — ce
    n'est pas un oubli. Le layering est structurellement un pattern
    multi-comptes/multi-sauts (A→B→C→D) ; cette fonction n'observe
    qu'UNE transaction à la fois avec le profil agrégé du client, sans
    vue sur une chaîne de comptes. Construire une règle avec les
    données actuelles produirait un label qui a l'air rigoureux sans
    détecter quoi que ce soit de fiable — un risque pour la crédibilité
    des rapports STR BCM plutôt qu'un vrai signal. Resterait possible
    via une analyse de graphe dédiée (au-delà du score GNN agrégé
    actuel), pas via une règle locale comme celle-ci.

    beneficiary_profile : profil du destinataire, utilisé pour la règle 7.
        Si fourni, MULE_ACCOUNT utilise BeneficiaryProfile.is_likely_mule()
        (fan-in réel + exclusion marchand + vitesse de sortie) — la même
        méthode déjà utilisée pour calculer la feature is_mule_pattern
        (voir _build_features() ci-dessus), pour que le LABEL envoyé en
        STR BCM reflète enfin ce que le SCORE voit déjà (TFT/GNN, une
        fois ré-entraînés avec is_mule_pattern dans leurs features).
        Si absent (store non disponible, ou bénéficiaire jamais vu),
        retombe sur l'ancienne heuristique brute (is_new_account +
        ratio_to_avg > 5) — moins fiable (peut confondre un nouveau
        compte à gros volume avec une mule) mais évite de ne jamais
        détecter MULE_ACCOUNT quand beneficiary_profile est indisponible.
    """
    # SIM Swapping — signal le plus fort
    if (
        transaction.sim_changed_72h and
        features.get("is_new_device") and
        features.get("amount_z_score", 0) > 3
    ):
        return FraudType.SIM_SWAPPING

    # Account takeover SANS SIM swap — device + zone inhabituels par
    # un autre vecteur (identifiants volés/phishing, pas clonage SIM).
    # Le "not sim_changed_72h" est explicite plutôt qu'implicite : si le
    # SIM a changé mais que la règle SIM_SWAPPING n'a pas matché
    # (amount_z_score <= 3 par exemple), ça reste un événement lié au
    # SIM, pas un ACCOUNT_TAKEOVER par un autre vecteur — pas de flou.
    if (
        not transaction.sim_changed_72h and
        features.get("is_new_device") and
        features.get("is_new_zone") and
        features.get("amount_z_score", 0) > 3
    ):
        return FraudType.ACCOUNT_TAKEOVER

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

    # Structuring — montant juste sous le seuil de déclaration BCM,
    # combiné à une fréquence de transactions élevée (tx_velocity_ratio).
    # Un seul montant proche du seuil est un signal faible (beaucoup de
    # transactions normales tombent naturellement dans cette fourchette) —
    # combiné à une vélocité élevée, ça approxime le pattern "plusieurs
    # transactions fractionnées pour rester sous le seuil".
    #
    # SEUIL tx_velocity_ratio > 1.0 NON CALIBRÉ sur données réelles —
    # choix de départ défendable (voir _aml_features_subset() pour la
    # formule), à ajuster une fois des transactions réelles Bankily
    # disponibles pour mesurer le taux de faux positifs. Documenté
    # explicitement plutôt que présenté comme une valeur validée.
    if (
        STRUCTURING_LOWER <= transaction.amount.amount <= STRUCTURING_UPPER and
        features.get("tx_velocity_ratio", 0) > 1.0
    ):
        return FraudType.STRUCTURING

    # Compte mule — fan-in + non-marchand + sortie rapide (source de
    # vérité : BeneficiaryProfile.is_likely_mule(), même méthode que
    # celle utilisée pour is_mule_pattern). Fallback sur l'ancienne
    # heuristique brute uniquement si beneficiary_profile indisponible.
    if beneficiary_profile is not None:
        if beneficiary_profile.is_likely_mule(
            is_merchant=transaction.beneficiary_is_merchant
        ):
            return FraudType.MULE_ACCOUNT
    elif (
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
        beneficiary_store: Optional[IBeneficiaryStore] = None,
    ):
        self._xgboost = xgboost_model
        self._isolation = isolation_model
        self._tft = tft_model
        self._gnn = gnn_model
        self._profile_store = profile_store
        self._explainer = explainer
        self._audit = audit_store
        # Optionnel par compatibilité ascendante — si non fourni,
        # is_mule_pattern vaut 0.0 pour toutes les transactions (voir
        # _build_features). Permet un déploiement progressif sans casser
        # les instanciations existantes du use case qui ne le passent pas.
        self._beneficiary_store = beneficiary_store

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

        # ── Étape 1bis : Récupérer le profil bénéficiaire ──
        # Nécessaire pour is_mule_pattern (voir BeneficiaryProfile.
        # is_likely_mule()). Optionnel : si beneficiary_store n'est pas
        # injecté, ou si la transaction n'a pas de beneficiary_token
        # (ex: retrait, pas un transfert), beneficiary_profile reste None
        # et is_mule_pattern vaut 0.0 par défaut dans _build_features.
        beneficiary_profile = None
        if self._beneficiary_store is not None and tx.beneficiary_token:
            beneficiary_profile = await self._beneficiary_store.get(
                beneficiary_token=tx.beneficiary_token,
                operator=tx.operator
            )
            if beneficiary_profile is None:
                beneficiary_profile = await self._beneficiary_store.create_default(
                    beneficiary_token=tx.beneficiary_token,
                    operator=tx.operator
                )

        # ── Étape 2 : Calculer les features ───────
        features = _build_features(
            transaction=tx,
            profile=profile,
            pre_computed=input_data.pre_computed_features,
            beneficiary_profile=beneficiary_profile,
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
        fraud_type = _detect_fraud_type(
            tx, profile, features, xgboost_score,
            beneficiary_profile=beneficiary_profile,
        )

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

            # Met à jour le profil bénéficiaire (réception de fonds) —
            # c'est ce qui permet à is_mule_pattern de devenir actif sur
            # les TRANSACTIONS FUTURES vers ce même bénéficiaire : sans
            # cette mise à jour, distinct_senders_30d et last_received_at
            # ne progresseraient jamais (voir BeneficiaryProfile.
            # update_inflow() / RedisBeneficiaryStore).
            if self._beneficiary_store is not None and beneficiary_profile is not None:
                await self._beneficiary_store.update_inflow(
                    profile=beneficiary_profile,
                    transaction=tx
                )

            # Si le CLIENT expéditeur de cette transaction a lui-même
            # déjà un profil bénéficiaire (il a reçu des fonds par le
            # passé), cette transaction est pour lui une SORTIE de
            # fonds — met à jour last_outflow_at, le signal central de
            # détection mule (vélocité de transit). Sans cet appel,
            # outflow_speed_hours() resterait toujours None pour ce
            # compte, et is_likely_mule() ne pourrait jamais être vrai
            # à son sujet (voir BeneficiaryProfile.outflow_speed_hours()).
            if self._beneficiary_store is not None:
                await self._beneficiary_store.update_outflow(
                    beneficiary_token=tx.client_token,
                    operator=tx.operator,
                    outflow_at=tx.timestamp,
                )

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