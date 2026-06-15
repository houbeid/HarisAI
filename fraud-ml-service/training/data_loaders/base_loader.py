"""
HarisAI — BaseLoader
======================
Classe abstraite que chaque loader de dataset doit implémenter.

Pour ajouter un nouveau dataset :
    1. Crée un fichier mon_dataset_loader.py
    2. Hérite de BaseLoader
    3. Implémente load() et name
    4. C'est tout — train_xgboost.py ne change pas

Exemple :
    class BankilyLoader(BaseLoader):
        @property
        def name(self): return "bankily"

        def load(self, path):
            df = pd.read_csv(path)
            X = self._map_features(df)
            y = df["is_fraud"].values
            return X, y
"""

from __future__ import annotations

import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from infrastructure.ml.models.xgboost_model import FEATURE_NAMES

logger = logging.getLogger(__name__)


class BaseLoader(ABC):
    """
    Contrat que chaque loader doit respecter.
    Garantit que tous les datasets produisent
    exactement les 22 features dans le bon ordre.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du dataset — utilisé dans les logs et MLflow."""
        ...

    @abstractmethod
    def load(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        """
        Charge le dataset et retourne (X, y).

        Args:
            path : chemin vers le fichier CSV

        Returns:
            X : numpy array shape (n, 22) — features dans l'ordre FEATURE_NAMES
            y : numpy array shape (n,)    — labels (0=normal · 1=fraude)
        """
        ...

    def validate(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Vérifie que X et y sont valides.
        Appelé automatiquement après load().
        """
        assert X.shape[1] == len(FEATURE_NAMES), (
            f"{self.name} : X a {X.shape[1]} features "
            f"mais {len(FEATURE_NAMES)} attendues"
        )
        assert len(X) == len(y), (
            f"{self.name} : X ({len(X)}) et y ({len(y)}) "
            f"n'ont pas la même longueur"
        )
        assert set(np.unique(y)).issubset({0, 1}), (
            f"{self.name} : y contient des valeurs autres que 0 et 1"
        )
        n_fraud = y.sum()
        logger.info(
            f"{self.name} → {len(y):,} lignes | "
            f"fraudes : {n_fraud:,} ({n_fraud/len(y)*100:.3f}%)"
        )

    def load_and_validate(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        """Charge et valide en une seule étape."""
        X, y = self.load(path)
        self.validate(X, y)
        return X, y

    # ── Méthodes utilitaires partagées ─────────

    def _build_empty_features(self) -> pd.DataFrame:
        """Retourne un DataFrame vide avec les bonnes colonnes."""
        return pd.DataFrame(columns=FEATURE_NAMES)

    def _compute_z_score(
        self,
        series: pd.Series,
    ) -> pd.Series:
        """Z-score standard."""
        mean = series.mean()
        std  = series.std()
        return (series - mean) / (std + 1e-8)

    def _compute_ratio(
        self,
        series: pd.Series,
    ) -> pd.Series:
        """Ratio par rapport à la moyenne."""
        mean = series.mean()
        return series / (mean + 1e-8)

    def _to_numpy(self, X: pd.DataFrame) -> np.ndarray:
        """
        Convertit DataFrame → numpy dans l'ordre FEATURE_NAMES.
        Vérifie l'ordre des colonnes.
        """
        assert list(X.columns) == FEATURE_NAMES, (
            f"Ordre features incorrect dans {self.name}!\n"
            f"Attendu : {FEATURE_NAMES}\n"
            f"Obtenu  : {list(X.columns)}"
        )
        return X.values.astype(np.float32)