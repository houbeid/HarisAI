"""
HarisAI — Ports : IExplainer + IAuditStore
============================================
IExplainer  : interface pour générer les explications SHAP
IAuditStore : interface pour persister l'audit trail BCM
"""

from abc import ABC, abstractmethod
from typing import List

from domain import Transaction, ClientProfile, FraudScore, Alert


class IExplainer(ABC):
    """
    Interface pour les explications SHAP des décisions du modèle.
    Implémentée par ShapExplainer dans infrastructure/ml/explainer/.

    Pourquoi une interface ?
    Si SHAP devient trop lent en production, on peut le remplacer
    par LIME ou une autre méthode sans toucher aux use cases.
    """

    @abstractmethod
    async def explain(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        features: dict,
        raw_score: float
    ) -> List[dict]:
        """
        Génère les explications pour une prédiction.

        Args:
            transaction : la transaction analysée
            profile     : le profil du client
            features    : dictionnaire des features calculées
            raw_score   : score brut retourné par XGBoost

        Returns:
            Liste triée par contribution absolue décroissante :
            [
                {
                    "feature_name"    : "sim_changed_72h",
                    "contribution"    : 0.42,
                    "feature_value"   : True,
                    "readable_fr"     : "SIM changée il y a moins de 72h",
                    "readable_ar"     : "تم تغيير الشريحة منذ أقل من 72 ساعة"
                },
                ...
            ]
        """
        ...

    @abstractmethod
    async def is_ready(self) -> bool:
        """True si l'explainer est initialisé et prêt."""
        ...


class IAuditStore(ABC):
    """
    Interface pour l'audit trail immuable — obligatoire BCM/GAFI.
    Chaque décision du système doit être tracée et non modifiable.

    Implémentations :
        IAuditStore
        ├── PostgresAuditStore  ← production
        └── InMemoryAuditStore  ← tests
    """

    @abstractmethod
    async def log_score(
        self,
        transaction: Transaction,
        score: FraudScore
    ) -> None:
        """
        Enregistre le score d'une transaction dans l'audit trail.
        Cette entrée est immuable — jamais modifiable après création.

        Appelé pour CHAQUE transaction analysée — APPROVE, REVIEW ou BLOCK.

        Args:
            transaction : la transaction analysée
            score       : le FraudScore calculé par le pipeline ML
        """
        ...

    @abstractmethod
    async def log_alert(
        self,
        alert: Alert
    ) -> None:
        """
        Enregistre une alerte et son traitement par le compliance officer.
        Utilisé pour les rapports BCM et la traçabilité réglementaire.

        Args:
            alert : l'alerte avec son statut de traitement
        """
        ...

    @abstractmethod
    async def log_model_prediction(
        self,
        transaction_id: str,
        model_name: str,
        model_version: str,
        score: float,
        features_used: List[str],
        inference_time_ms: float
    ) -> None:
        """
        Enregistre les détails techniques de chaque prédiction ML.
        Permet de tracer quelle version du modèle a pris quelle décision.

        Utilisé pour :
        - Détecter le model drift
        - Audit BCM si une décision est contestée
        - Comparer les performances des versions de modèle

        Args:
            transaction_id   : ID de la transaction
            model_name       : "xgboost_fraud", "isolation_forest", etc.
            model_version    : "1.2.0"
            score            : score retourné par ce modèle
            features_used    : liste des features utilisées
            inference_time_ms: temps d'inférence en millisecondes
        """
        ...