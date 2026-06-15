"""
HarisAI — ShapExplainer
=========================
Implémentation concrète de IExplainer.
Explique pourquoi XGBoost a donné un score élevé à une transaction.

RÔLE :
    Sans SHAP, le système dit "score = 0.94 → BLOCK" sans explication.
    Avec SHAP, il dit :
        +0.42 → SIM changée il y a moins de 72h
        +0.31 → Nouveau appareil jamais utilisé
        +0.28 → Montant 9x supérieur à la moyenne
        -0.08 → Zone habituelle du client (rassure)

    Ces explications sont obligatoires pour :
        1. Le compliance officer — il sait quoi vérifier
        2. Les rapports STR BCM — justifie la décision
        3. La réglementation GAFI — chaque blocage doit être justifiable

SHAP = SHapley Additive exPlanations
    Méthode mathématique issue de la théorie des jeux.
    Garantit que la somme des contributions = score final.
    Chaque feature reçoit exactement sa part de responsabilité.

FONCTIONNEMENT :
    XGBoost prédit score = 0.94
    SHAP décompose ce score feature par feature :
        base_value       = 0.02  (score moyen sans info)
        + sim_changed    = +0.42
        + new_device     = +0.31
        + amount_z       = +0.28
        + is_night       = +0.18
        - usual_zone     = -0.08
        ─────────────────────────
        score final      = 0.94  ✓ (somme = score XGBoost)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import shap
import xgboost as xgb

from application.ports.i_explainer_audit import IExplainer
from domain import ClientProfile, Transaction
from infrastructure.ml.models.xgboost_model import FEATURE_NAMES, FEATURE_LABELS

logger = logging.getLogger(__name__)


class ShapExplainer(IExplainer):
    """
    Génère les explications SHAP pour les décisions XGBoost.

    Hérite de IExplainer — respecte le contrat défini
    dans application/ports/i_explainer_audit.py.

    Doit être initialisé avec le même modèle XGBoost
    que celui utilisé pour la prédiction.

    Exemple d'utilisation :
        explainer = ShapExplainer()
        explainer.initialize(xgboost_model._model)

        explanations = await explainer.explain(
            transaction=tx,
            profile=profile,
            features=features,
            raw_score=0.94
        )
    """

    def __init__(self):
        self._explainer: Optional[shap.TreeExplainer] = None
        self._base_value: float = 0.0
        self._ready: bool = False

    def initialize(self, xgb_model: xgb.XGBClassifier) -> None:
        """
        Initialise l'explainer SHAP avec le modèle XGBoost entraîné.
        Doit être appelé après le chargement du modèle XGBoost.

        Args:
            xgb_model : modèle XGBClassifier déjà entraîné
        """
        self._explainer = shap.TreeExplainer(xgb_model)

        # Calcule la valeur de base (score moyen sans aucune feature)
        # C'est le point de départ avant d'ajouter les contributions
        try:
            self._base_value = float(
                self._explainer.expected_value
                if not hasattr(self._explainer.expected_value, '__len__')
                else self._explainer.expected_value[1]
            )
        except Exception:
            self._base_value = 0.02  # valeur par défaut si erreur

        self._ready = True
        logger.info(
            "ShapExplainer initialisé",
            extra={"base_value": round(self._base_value, 4)}
        )

    async def is_ready(self) -> bool:
        return self._ready

    # ─────────────────────────────────────────
    # INTERFACE IExplainer
    # ─────────────────────────────────────────

    async def explain(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        features: dict,
        raw_score: float,
    ) -> List[dict]:
        """
        Calcule les contributions SHAP de chaque feature.

        Args:
            transaction : la transaction analysée
            profile     : le profil comportemental du client
            features    : dictionnaire des 22 features calculées
            raw_score   : score brut retourné par XGBoost (0.0 → 1.0)

        Returns:
            Liste triée par contribution absolue décroissante :
            [
                {
                    "feature_name"  : "sim_changed_72h",
                    "contribution"  : 0.42,
                    "feature_value" : 1.0,
                    "readable_fr"   : "SIM changée il y a moins de 72h",
                    "readable_ar"   : "تم تغيير الشريحة منذ أقل من 72 ساعة"
                },
                ...
            ]
        """
        if not self._ready:
            logger.warning(
                "ShapExplainer non initialisé — retourne explications vides"
            )
            return self._fallback_explanations(features, raw_score)

        # Construit le vecteur numpy dans le bon ordre
        vector = self._features_to_vector(features)

        # ── Calcul SHAP ───────────────────────────────────────
        # shap_values shape = (1, n_features)
        # Chaque valeur = contribution de cette feature au score
        try:
            shap_values = self._explainer.shap_values(vector)
            contributions = shap_values[0]  # première (et seule) ligne
        except Exception as e:
            logger.error(
                "Erreur calcul SHAP",
                extra={
                    "transaction_id": transaction.transaction_id,
                    "error": str(e)
                }
            )
            return self._fallback_explanations(features, raw_score)

        # ── Construit les explications ────────────────────────
        explanations = []
        for i, feature_name in enumerate(FEATURE_NAMES):
            contribution   = float(contributions[i])
            feature_value  = features.get(feature_name, 0.0)
            label_fr, label_ar = FEATURE_LABELS.get(
                feature_name,
                (feature_name, feature_name)
            )

            # Construit le texte lisible adapté à la valeur
            readable_fr = self._build_readable_fr(
                feature_name, feature_value, contribution, label_fr
            )
            readable_ar = self._build_readable_ar(
                feature_name, feature_value, contribution, label_ar
            )

            explanations.append({
                "feature_name":  feature_name,
                "contribution":  round(contribution, 4),
                "feature_value": feature_value,
                "readable_fr":   readable_fr,
                "readable_ar":   readable_ar,
            })

        # ── Trie par contribution absolue décroissante ────────
        explanations.sort(
            key=lambda x: abs(x["contribution"]),
            reverse=True
        )

        logger.debug(
            "Explications SHAP calculées",
            extra={
                "transaction_id": transaction.transaction_id,
                "top_feature":    explanations[0]["feature_name"],
                "top_contrib":    explanations[0]["contribution"],
                "n_features":     len(explanations),
            }
        )

        return explanations

    # ─────────────────────────────────────────
    # MÉTHODES PRIVÉES
    # ─────────────────────────────────────────

    def _features_to_vector(self, features: dict) -> np.ndarray:
        """Convertit le dict de features en vecteur numpy ordonné."""
        vector = [
            float(features.get(name, 0.0))
            for name in FEATURE_NAMES
        ]
        return np.array(vector, dtype=np.float32).reshape(1, -1)

    def _build_readable_fr(
        self,
        feature_name: str,
        value: Any,
        contribution: float,
        label: str,
    ) -> str:
        """
        Construit une phrase en français lisible par le compliance officer.
        Adapte le message selon la valeur et la contribution.
        """
        risk = contribution > 0  # True = augmente le risque

        # ── SIM swapping ──────────────────────────────────────
        if feature_name == "sim_changed_72h":
            if value:
                return "⚠ SIM changée il y a moins de 72h — risque SIM swap élevé"
            return "✓ Pas de changement SIM récent"

        # ── Nouveau device ────────────────────────────────────
        if feature_name == "is_new_device":
            if value:
                return "⚠ Appareil jamais utilisé par ce client — possible SIM swap"
            return "✓ Appareil habituel reconnu"

        # ── Z-score montant ───────────────────────────────────
        if feature_name == "amount_z_score":
            if value > 10:
                return f"⚠ Montant extrêmement anormal ({value:.1f}σ au-dessus de la moyenne)"
            if value > 5:
                return f"⚠ Montant très anormal ({value:.1f}σ au-dessus de la moyenne)"
            if value > 3:
                return f"⚠ Montant anormal ({value:.1f}σ au-dessus de la moyenne)"
            if value < -1:
                return f"✓ Montant inférieur à la normale ({abs(value):.1f}σ en dessous)"
            return "✓ Montant dans la plage normale"

        # ── Ratio montant / moyenne ───────────────────────────
        if feature_name == "ratio_to_avg":
            if value > 5:
                return f"⚠ Montant {value:.1f}x supérieur à la moyenne habituelle"
            if value > 3:
                return f"⚠ Montant {value:.1f}x la moyenne — inhabituel"
            if value > 1.5:
                return f"Montant {value:.1f}x la moyenne — légèrement élevé"
            return f"✓ Montant dans la normale ({value:.1f}x la moyenne)"

        # ── Transaction de nuit ───────────────────────────────
        if feature_name == "is_night":
            if value:
                return "⚠ Transaction effectuée la nuit (22h-6h)"
            return "✓ Transaction en heures normales"

        # ── Canal USSD ────────────────────────────────────────
        if feature_name == "is_ussd":
            if value:
                return "⚠ Transaction via USSD *888# — canal inhabituel"
            return "✓ Canal mobile app habituel"

        # ── Nouveau bénéficiaire ──────────────────────────────
        if feature_name == "is_new_beneficiary":
            if value:
                return "⚠ Virement vers un destinataire jamais contacté"
            return "✓ Destinataire connu du client"

        # ── Nouvelle zone ─────────────────────────────────────
        if feature_name == "is_new_zone":
            if value:
                return "⚠ Transaction depuis une zone géographique inhabituelle"
            return "✓ Zone habituelle du client"

        # ── Heure inhabituelle ────────────────────────────────
        if feature_name == "is_unusual_hour":
            if value:
                return "⚠ Transaction à une heure inhabituelle pour ce client"
            return "✓ Heure habituelle du client"

        # ── Compte dormant ────────────────────────────────────
        if feature_name == "is_dormant_account":
            if value:
                return "⚠ Compte inactif réactivé soudainement — signal AML"
            return "✓ Compte actif régulièrement"

        # ── Nouveau compte ────────────────────────────────────
        if feature_name == "is_new_account":
            if value:
                return "⚠ Compte créé récemment (moins de 30 jours)"
            return "✓ Compte établi depuis longtemps"

        # ── Ancienneté compte ─────────────────────────────────
        if feature_name == "account_age_days":
            if value < 30:
                return f"⚠ Compte très récent ({int(value)} jours)"
            if value < 90:
                return f"Compte récent ({int(value)} jours)"
            return f"✓ Compte établi ({int(value)} jours)"

        # ── Historique transactions ───────────────────────────
        if feature_name == "total_transactions":
            if value < 10:
                return f"⚠ Peu de transactions historiques ({int(value)})"
            return f"✓ Historique solide ({int(value)} transactions)"

        # ── Agent physique ────────────────────────────────────
        if feature_name == "is_agent":
            if value and risk:
                return "⚠ Transaction via agent physique — comportement inhabituel"
            return "✓ Transaction via agent physique"

        # ── Marchand ─────────────────────────────────────────
        if feature_name == "beneficiary_is_merchant":
            if value and risk:
                return "⚠ Paiement vers compte marchand — à vérifier"
            return "✓ Paiement marchand habituel"

        # ── Default ───────────────────────────────────────────
        prefix = "⚠" if risk else "✓"
        return f"{prefix} {label}"

    def _build_readable_ar(
        self,
        feature_name: str,
        value: Any,
        contribution: float,
        label: str,
    ) -> str:
        """
        Construit une phrase en arabe pour le dashboard RTL.
        """
        risk = contribution > 0

        ar_labels = {
            "sim_changed_72h":      ("⚠ تم تغيير الشريحة منذ أقل من 72 ساعة — خطر مرتفع",
                                     "✓ لا تغيير حديث في الشريحة"),
            "is_new_device":        ("⚠ جهاز جديد لم يستخدم من قبل",
                                     "✓ الجهاز المعتاد معروف"),
            "is_night":             ("⚠ معاملة ليلية (22:00 - 06:00)",
                                     "✓ معاملة في ساعات عمل عادية"),
            "is_ussd":              ("⚠ معاملة عبر USSD *888# — قناة غير معتادة",
                                     "✓ قناة التطبيق المعتادة"),
            "is_new_beneficiary":   ("⚠ تحويل إلى مستفيد لم يتم الاتصال به من قبل",
                                     "✓ المستفيد معروف للعميل"),
            "is_new_zone":          ("⚠ معاملة من منطقة جغرافية غير معتادة",
                                     "✓ المنطقة المعتادة للعميل"),
            "is_unusual_hour":      ("⚠ معاملة في ساعة غير معتادة للعميل",
                                     "✓ الساعة المعتادة للعميل"),
            "is_dormant_account":   ("⚠ حساب خامل أعيد تفعيله فجأة — إشارة غسيل أموال",
                                     "✓ حساب نشط بانتظام"),
            "is_new_account":       ("⚠ حساب تم إنشاؤه مؤخراً (أقل من 30 يوماً)",
                                     "✓ حساب راسخ منذ فترة طويلة"),
        }

        if feature_name in ar_labels:
            positive_label, negative_label = ar_labels[feature_name]
            if feature_name in ["sim_changed_72h", "is_new_device",
                                  "is_night", "is_ussd", "is_new_beneficiary",
                                  "is_new_zone", "is_unusual_hour",
                                  "is_dormant_account", "is_new_account"]:
                return positive_label if value else negative_label

        if feature_name == "amount_z_score":
            if value > 5:
                return f"⚠ المبلغ غير طبيعي جداً ({value:.1f}σ فوق المتوسط)"
            if value > 3:
                return f"⚠ المبلغ غير طبيعي ({value:.1f}σ فوق المتوسط)"
            return "✓ المبلغ ضمن النطاق الطبيعي"

        if feature_name == "ratio_to_avg":
            if value > 5:
                return f"⚠ المبلغ أعلى {value:.1f} أضعاف من المتوسط المعتاد"
            if value > 3:
                return f"⚠ المبلغ {value:.1f} أضعاف المتوسط — غير عادي"
            return f"✓ المبلغ طبيعي ({value:.1f} مرة المتوسط)"

        prefix = "⚠" if risk else "✓"
        return f"{prefix} {label}"

    def _fallback_explanations(
        self,
        features: dict,
        raw_score: float,
    ) -> List[dict]:
        """
        Explications de secours quand SHAP n'est pas disponible.
        Basées sur des règles simples — moins précises mais toujours utiles.
        Utilisé quand le modèle n'est pas encore chargé ou en cas d'erreur.
        """
        explanations = []
        score_portion = raw_score / max(len(FEATURE_NAMES), 1)

        priority_features = [
            ("sim_changed_72h",   0.40),
            ("is_new_device",     0.30),
            ("amount_z_score",    0.20),
            ("is_night",          0.15),
            ("is_new_zone",       0.12),
            ("is_new_beneficiary",0.10),
            ("is_dormant_account",0.08),
            ("ratio_to_avg",      0.05),
        ]

        for feature_name, weight in priority_features:
            value = features.get(feature_name, 0.0)
            if value:
                contribution = weight * raw_score
                label_fr, label_ar = FEATURE_LABELS.get(
                    feature_name, (feature_name, feature_name)
                )
                explanations.append({
                    "feature_name":  feature_name,
                    "contribution":  round(contribution, 4),
                    "feature_value": value,
                    "readable_fr":   self._build_readable_fr(
                        feature_name, value, contribution, label_fr
                    ),
                    "readable_ar":   self._build_readable_ar(
                        feature_name, value, contribution, label_ar
                    ),
                })

        explanations.sort(
            key=lambda x: abs(x["contribution"]),
            reverse=True
        )
        return explanations