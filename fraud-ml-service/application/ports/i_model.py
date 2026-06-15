"""
HarisAI — Port : IFraudModel
==============================
Interface abstraite que CHAQUE modèle ML doit implémenter.

Pourquoi une interface ?
→ Le use case AnalyzeTransaction ne sait pas si c'est XGBoost,
  LightGBM, ou un autre modèle. Il appelle juste predict().
→ Si demain on remplace XGBoost par LightGBM :
  - On crée LightGBMModel(IFraudModel)
  - On change l'injection de dépendance
  - ZÉRO changement dans le use case

C'est le principe de Dependency Inversion (le D de SOLID).

Hiérarchie :
    IFraudModel          ← interface générale
    ├── XGBoostModel     ← implémentation infrastructure
    ├── IsolationForest  ← implémentation infrastructure
    ├── TFTModel         ← implémentation infrastructure
    └── GNNModel         ← implémentation infrastructure
"""

from abc import ABC, abstractmethod
from typing import List

from domain import Transaction, ClientProfile


class IFraudModel(ABC):
    """
    Contrat que chaque modèle ML doit respecter.
    Toute implémentation concrète (XGBoost, IsoForest, TFT, GNN)
    doit hériter de cette classe et implémenter ses méthodes abstraites.
    """

    @abstractmethod
    async def predict(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        features: dict
    ) -> float:
        """
        Prédit le score de fraude pour une transaction.

        Args:
            transaction : la transaction à analyser
            profile     : le profil comportemental du client (depuis Redis)
            features    : dictionnaire des features calculées par feature_engineering

        Returns:
            float entre 0.0 (pas de fraude) et 1.0 (fraude certaine)

        Raises:
            ModelNotLoadedError : si le modèle n'est pas encore chargé
            PredictionError     : si la prédiction échoue
        """
        ...

    @abstractmethod
    async def load(self, model_path: str) -> None:
        """
        Charge le modèle depuis un fichier (MLflow artifact ou chemin local).

        Args:
            model_path : chemin vers le fichier modèle
                         ex: "models/xgboost_v1.2.0.pkl"
                             "mlflow://models/fraud_xgboost/1"

        Raises:
            ModelLoadError : si le fichier est introuvable ou corrompu
        """
        ...

    @abstractmethod
    async def is_ready(self) -> bool:
        """
        Vérifie si le modèle est chargé et prêt à faire des prédictions.
        Utilisé par le health check de l'API FastAPI.

        Returns:
            True si le modèle est prêt, False sinon
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """
        Nom du modèle — utilisé dans les logs et MLflow.
        Ex: "xgboost_fraud", "isolation_forest", "tft_aml", "gnn_network"
        """
        ...

    @property
    @abstractmethod
    def model_version(self) -> str:
        """
        Version du modèle actuellement chargé.
        Ex: "1.2.0", "2024-01-15"
        Inclus dans chaque FraudScore pour l'auditabilité BCM.
        """
        ...


class IExplainableModel(IFraudModel):
    """
    Extension de IFraudModel pour les modèles qui supportent SHAP.
    Seul XGBoost implémente cette interface — les autres retournent
    des explications simplifiées.
    """

    @abstractmethod
    async def explain(
        self,
        transaction: Transaction,
        profile: ClientProfile,
        features: dict
    ) -> List[dict]:
        """
        Calcule les contributions SHAP de chaque feature.

        Returns:
            Liste de dicts avec :
            [
                {
                    "feature_name": "sim_changed_72h",
                    "contribution": 0.42,
                    "feature_value": True
                },
                ...
            ]
            Trié par contribution absolue décroissante.
        """
        ...