"""
HarisAI — XGBoostModel
========================
Implémentation concrète du modèle XGBoost pour la détection
de fraude temps réel sur le mobile money mauritanien.

Hérite de IExplainableModel → respecte le contrat défini
dans application/ports/i_model.py.

Le use case analyze_transaction.py appelle :
    score = await model.predict(transaction, profile, features)
    shap  = await model.explain(transaction, profile, features)

Sans jamais savoir que c'est XGBoost derrière.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
from typing import Any, Dict, List, Optional

import numpy as np
import shap
import xgboost as xgb

from application.ports.i_model import IExplainableModel
from domain import ClientProfile, Transaction

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Features dans l'ordre exact attendu par XGBoost
# CET ORDRE NE DOIT JAMAIS CHANGER après l'entraînement
# ─────────────────────────────────────────────
FEATURE_NAMES = [
    # Transaction
    "amount",
    "hour_of_day",
    "day_of_week",
    "is_night",
    "is_weekend",
    "is_ussd",
    "is_agent",
    "sim_changed_72h",
    # Profil client
    "amount_z_score",
    "is_new_device",
    "is_new_zone",
    "is_unusual_hour",
    "is_unusual_channel",
    "is_dormant_account",
    "is_new_account",
    "account_age_days",
    "total_transactions",
    "avg_amount_7d",
    "avg_amount_30d",
    # Bénéficiaire
    "is_new_beneficiary",
    "beneficiary_is_merchant",
    # Ratios
    "ratio_to_avg",
]

# Textes SHAP lisibles en français et arabe
# Clé = nom de la feature · Valeur = (français, arabe)
FEATURE_LABELS: Dict[str, tuple] = {
    "amount":               ("Montant de la transaction",                    "مبلغ المعاملة"),
    "hour_of_day":          ("Heure de la transaction",                      "ساعة المعاملة"),
    "day_of_week":          ("Jour de la semaine",                           "يوم الأسبوع"),
    "is_night":             ("Transaction la nuit (22h-6h)",                 "معاملة ليلية"),
    "is_weekend":           ("Transaction le week-end",                      "معاملة في عطلة نهاية الأسبوع"),
    "is_ussd":              ("Canal USSD *888# inhabituel",                  "قناة USSD غير معتادة"),
    "is_agent":             ("Agent physique Bankily",                       "وكيل بنكيلي"),
    "sim_changed_72h":      ("SIM changée il y a moins de 72h",             "تم تغيير الشريحة منذ أقل من 72 ساعة"),
    "amount_z_score":       ("Montant anormal par rapport à l'historique",   "مبلغ غير طبيعي مقارنة بالتاريخ"),
    "is_new_device":        ("Nouvel appareil jamais utilisé",               "جهاز جديد لم يستخدم من قبل"),
    "is_new_zone":          ("Zone géographique inhabituelle",               "منطقة جغرافية غير معتادة"),
    "is_unusual_hour":      ("Heure inhabituelle pour ce client",            "ساعة غير معتادة لهذا العميل"),
    "is_unusual_channel":   ("Canal de paiement inhabituel",                 "قناة دفع غير معتادة"),
    "is_dormant_account":   ("Compte inactif réactivé soudainement",        "حساب خامل أعيد تفعيله فجأة"),
    "is_new_account":       ("Compte créé récemment (moins de 30 jours)",    "حساب تم إنشاؤه مؤخراً"),
    "account_age_days":     ("Ancienneté du compte en jours",               "عمر الحساب بالأيام"),
    "total_transactions":   ("Nombre de transactions historiques",           "عدد المعاملات التاريخية"),
    "avg_amount_7d":        ("Moyenne des montants sur 7 jours",            "متوسط المبالغ على 7 أيام"),
    "avg_amount_30d":       ("Moyenne des montants sur 30 jours",           "متوسط المبالغ على 30 يوماً"),
    "is_new_beneficiary":   ("Destinataire jamais contacté auparavant",      "مستفيد لم يتم الاتصال به من قبل"),
    "beneficiary_is_merchant": ("Paiement vers un compte marchand",         "دفع لحساب تاجر"),
    "ratio_to_avg":         ("Montant vs moyenne habituelle du client",      "المبلغ مقارنة بمتوسط العميل المعتاد"),
}


class ModelNotLoadedError(Exception):
    """Levée quand predict() est appelé avant load()."""
    pass


class XGBoostModel(IExplainableModel):
    """
    Modèle XGBoost pour la détection de fraude temps réel.

    Cycle de vie :
        1. __init__()   → configuration
        2. load()       → charge le modèle depuis fichier ou MLflow
        3. predict()    → score 0.0 → 1.0 pour chaque transaction
        4. explain()    → contributions SHAP de chaque feature

    Exemple d'utilisation :
        model = XGBoostModel()
        await model.load("models/xgboost_v1.pkl")
        score = await model.predict(tx, profile, features)
        explanations = await model.explain(tx, profile, features)
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        version: str = "1.0.0",
    ):
        self._model: Optional[xgb.XGBClassifier] = None
        self._explainer: Optional[shap.TreeExplainer] = None
        self._model_path = model_path
        self._version = version
        self._is_ready = False
        # Lock pour protéger predict_proba contre les accès concurrents
        # XGBoost n'est pas thread-safe par défaut
        self._lock = asyncio.Lock()

        logger.info("XGBoostModel initialisé", extra={"version": version})

    # ── Propriétés obligatoires (IFraudModel) ─

    @property
    def model_name(self) -> str:
        return "xgboost_fraud"

    @property
    def model_version(self) -> str:
        return self._version

    # ── Chargement ────────────────────────────

    async def load(self, model_path: str) -> None:
        """
        Charge le modèle XGBoost depuis un fichier pickle.
        Initialise aussi le TreeExplainer SHAP.

        Args:
            model_path : chemin vers le fichier .pkl ou .json
        """
        try:
            logger.info(
                "Chargement modèle XGBoost",
                extra={"path": model_path}
            )

            if model_path.endswith(".json"):
                self._model = xgb.XGBClassifier()
                self._model.load_model(model_path)
            else:
                with open(model_path, "rb") as f:
                    self._model = pickle.load(f)

            # Initialise SHAP TreeExplainer — optimisé pour XGBoost
            self._explainer = shap.TreeExplainer(self._model)
            self._is_ready = True

            logger.info(
                "Modèle XGBoost chargé",
                extra={
                    "path": model_path,
                    "n_estimators": self._model.n_estimators,
                }
            )

        except FileNotFoundError:
            logger.error(f"Fichier modèle introuvable : {model_path}")
            raise
        except Exception as e:
            logger.error(f"Erreur chargement modèle : {e}")
            raise

    def load_from_sklearn(self, model: xgb.XGBClassifier) -> None:
        """
        Charge directement depuis un objet XGBClassifier déjà entraîné.
        Utilisé après l'entraînement dans les notebooks.
        """
        self._model = model
        self._explainer = shap.TreeExplainer(self._model)
        self._is_ready = True
        logger.info("Modèle XGBoost chargé depuis objet sklearn")

    async def is_ready(self) -> bool:
        return self._is_ready

    # ── Prédiction ────────────────────────────

    async def predict(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        features: dict,
    ) -> float:
        """
        Prédit le score de fraude pour une transaction.

        Args:
            transaction : la transaction mobile money
            profile     : profil comportemental du client (Redis)
            features    : dictionnaire des features calculées

        Returns:
            float entre 0.0 (normal) et 1.0 (fraude certaine)
        """
        if not self._is_ready:
            raise ModelNotLoadedError(
                "XGBoostModel non chargé — appelez load() d'abord"
            )

        # Convertit le dict en vecteur numpy dans le bon ordre
        X = self._features_to_vector(features)

        # Lock — protège predict_proba contre accès concurrent
        # XGBoost n'est pas thread-safe · une prédiction à la fois
        async with self._lock:
            proba = self._model.predict_proba(X)[0][1]

        logger.debug(
            "Prédiction XGBoost",
            extra={
                "transaction_id": transaction.transaction_id,
                "score": round(float(proba), 4),
            }
        )

        return float(proba)

    # ── Explication SHAP ──────────────────────

    async def explain(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        features: dict,
    ) -> List[dict]:
        """
        Calcule les contributions SHAP de chaque feature.

        Returns:
            Liste triée par contribution absolue décroissante :
            [
                {
                    "feature_name"  : "sim_changed_72h",
                    "contribution"  : 0.42,
                    "feature_value" : True,
                    "readable_fr"   : "SIM changée il y a moins de 72h",
                    "readable_ar"   : "تم تغيير الشريحة..."
                },
                ...
            ]
        """
        if not self._is_ready:
            raise ModelNotLoadedError(
                "XGBoostModel non chargé — appelez load() d'abord"
            )

        X = self._features_to_vector(features)

        # Lock — même protection que predict
        async with self._lock:
            shap_values = self._explainer.shap_values(X)

        # Construit la liste des explications
        explanations = []
        for i, feature_name in enumerate(FEATURE_NAMES):
            contribution = float(shap_values[0][i])
            feature_value = features.get(feature_name, 0)
            label_fr, label_ar = FEATURE_LABELS.get(
                feature_name,
                (feature_name, feature_name)
            )

            explanations.append({
                "feature_name":  feature_name,
                "contribution":  round(contribution, 4),
                "feature_value": feature_value,
                "readable_fr":   self._build_readable(
                    label_fr, feature_name, feature_value, contribution
                ),
                "readable_ar":   label_ar,
            })

        # Trie par contribution absolue décroissante
        explanations.sort(
            key=lambda x: abs(x["contribution"]),
            reverse=True
        )

        return explanations

    # ── Entraînement (utilisé dans les notebooks) ─

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        n_estimators: int = 500,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        scale_pos_weight: float = 49.0,
    ) -> Dict[str, Any]:
        """
        Entraîne le modèle XGBoost sur les données d'entraînement.

        Args:
            X_train          : features d'entraînement (numpy array)
            y_train          : labels (0=normal, 1=fraude)
            X_val            : features de validation (optionnel)
            y_val            : labels de validation (optionnel)
            n_estimators     : nombre d'arbres (500 par défaut)
            max_depth        : profondeur max des arbres (6 par défaut)
            learning_rate    : taux d'apprentissage (0.05 par défaut)
            scale_pos_weight : poids classe positive — compense le déséquilibre
                               98% normal / 2% fraude → scale = 49

        Returns:
            Dict avec les métriques d'entraînement

        Note sur scale_pos_weight :
            Si 98% des transactions sont normales et 2% sont frauduleuses,
            le ratio est 98/2 = 49. XGBoost donne 49x plus de poids
            aux exemples de fraude pour compenser le déséquilibre.
        """
        logger.info("Début entraînement XGBoost", extra={
            "n_estimators": n_estimators,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "scale_pos_weight": scale_pos_weight,
        })

        eval_set = []
        if X_val is not None and y_val is not None:
            eval_set = [(X_val, y_val)]

        self._model = xgb.XGBClassifier(
            # Architecture
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,

            # Gestion du déséquilibre fraude/normal
            scale_pos_weight=scale_pos_weight,

            # Régularisation — évite l'overfitting
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,

            # Performance
            tree_method="hist",
            n_jobs=-1,
            random_state=42,

            # Métrique d'évaluation
            eval_metric="aucpr",  # AUC-PR mieux que AUC-ROC pour fraude
            early_stopping_rounds=50 if eval_set else None,
        )

        self._model.fit(
            X_train,
            y_train,
            eval_set=eval_set if eval_set else None,
            verbose=False,
        )

        # Initialise SHAP après entraînement
        self._explainer = shap.TreeExplainer(self._model)
        self._is_ready = True

        # Métriques finales
        metrics = {"status": "trained", "n_estimators": n_estimators}

        if eval_set:
            results = self._model.evals_result()
            if results:
                val_scores = results.get("validation_0", {}).get("aucpr", [])
                if val_scores:
                    metrics["best_aucpr"] = round(max(val_scores), 4)

        logger.info("Entraînement terminé", extra=metrics)
        return metrics

    def save(self, path: str) -> None:
        """Sauvegarde le modèle entraîné."""
        if not self._is_ready:
            raise ModelNotLoadedError("Aucun modèle à sauvegarder")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if path.endswith(".json"):
            self._model.save_model(path)
        else:
            with open(path, "wb") as f:
                pickle.dump(self._model, f)
        logger.info(f"Modèle sauvegardé → {path}")

    def get_feature_importance(self) -> Dict[str, float]:
        """
        Retourne l'importance de chaque feature selon XGBoost.
        Utile pour analyser quelles features sont les plus utiles.
        """
        if not self._is_ready:
            raise ModelNotLoadedError("Modèle non chargé")

        importances = self._model.feature_importances_
        return {
            name: round(float(imp), 4)
            for name, imp in zip(FEATURE_NAMES, importances)
        }

    # ── Méthodes privées ──────────────────────

    def _features_to_vector(self, features: dict) -> np.ndarray:
        """
        Convertit le dictionnaire de features en vecteur numpy.
        L'ordre est critique — doit correspondre à l'ordre d'entraînement.
        Les features manquantes sont remplacées par 0.
        """
        vector = [
            float(features.get(name, 0))
            for name in FEATURE_NAMES
        ]
        return np.array(vector).reshape(1, -1)

    def _build_readable(
        self,
        label: str,
        feature_name: str,
        value: Any,
        contribution: float
    ) -> str:
        """
        Construit une phrase lisible pour le compliance officer.
        Adapte le message selon la valeur et la contribution.
        """
        if feature_name == "sim_changed_72h" and value:
            return "SIM changée il y a moins de 72h — risque SIM swap"

        if feature_name == "is_new_device" and value:
            return "Nouvel appareil jamais utilisé par ce client"

        if feature_name == "amount_z_score":
            if value > 5:
                return f"Montant extrêmement anormal ({value:.1f}x l'écart-type)"
            elif value > 3:
                return f"Montant très anormal ({value:.1f}x l'écart-type)"
            elif value > 1:
                return f"Montant légèrement supérieur à la normale"
            return "Montant dans la normale"

        if feature_name == "ratio_to_avg" and value > 3:
            return f"Montant {value:.1f}x supérieur à la moyenne habituelle"

        if feature_name == "is_dormant_account" and value:
            return "Compte inactif réactivé soudainement — signal AML"

        if feature_name == "is_new_account" and value:
            return "Compte créé récemment — profil incomplet"

        if contribution > 0:
            return f"{label} — augmente le risque"
        return f"{label} — réduit le risque"