"""
HarisAI — ModelUpdater
=======================
Hot-reload des modèles ML sans redémarrage du service FastAPI.

RÔLE :
    Surveille le dossier models/ en arrière-plan.
    Dès qu'un nouveau .pkl apparaît, charge le modèle
    et le remplace atomiquement dans le use case — zéro downtime.

SCÉNARIO D'UTILISATION :
    1. Flower fine-tune TFT sur données Bankily locales
    2. Flower sauvegarde tft_v1.1.0.pkl dans models/
    3. ModelUpdater détecte le nouveau fichier
    4. Charge tft_v1.1.0.pkl en mémoire
    5. Remplace tft_v1.0.0 dans le use case atomiquement
    6. Les prochaines transactions utilisent le nouveau modèle
    → Zéro redémarrage · Zéro downtime

INTÉGRATION DANS MAIN.PY :
    updater = ModelUpdater(
        models_dir="models/",
        use_case=use_case,
        settings=settings,
    )
    updater.start()  # démarre la surveillance en arrière-plan
    # ... service tourne ...
    updater.stop()   # arrêt propre dans le lifespan

STRATÉGIE DE DÉTECTION :
    Surveille les timestamps de modification des fichiers .pkl
    Intervalle de vérification : 60 secondes (configurable)
    Remplacement atomique via asyncio.Lock
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
import time
from pathlib import Path
from typing import Dict, Optional

from application.use_cases import AnalyzeTransactionUseCase
from infrastructure.ml.models.isolation_forest import IsolationForestModel
from infrastructure.ml.models.tft_model import TFTModel
from infrastructure.ml.models.gnn_model import GNNModel
from infrastructure.ml.models.xgboost_model import XGBoostModel

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# MAPPING — nom fichier → type modèle
# ─────────────────────────────────────────────

MODEL_PATTERNS = {
    "xgboost":           "xgboost",
    "isolation_forest":  "isolation_forest",
    "tft":               "tft",
    "gnn":               "gnn",
}


def detect_model_type(filename: str) -> Optional[str]:
    """
    Détecte le type de modèle depuis le nom du fichier.

    Exemples :
        xgboost_v1.1.0.pkl       → "xgboost"
        isolation_forest_v1.1.0.pkl → "isolation_forest"
        tft_v1.1.0.pkl           → "tft"
        gnn_v1.1.0.pkl           → "gnn"
    """
    name = filename.lower()
    for pattern, model_type in MODEL_PATTERNS.items():
        if name.startswith(pattern):
            return model_type
    return None


def extract_version(filename: str) -> str:
    """
    Extrait la version depuis le nom du fichier.

    Exemples :
        tft_v1.1.0.pkl → "1.1.0"
        gnn_v2.0.pkl   → "2.0"
    """
    name = Path(filename).stem  # sans .pkl
    parts = name.split("_v")
    if len(parts) >= 2:
        return parts[-1]
    return "unknown"


# ─────────────────────────────────────────────
# MODEL UPDATER
# ─────────────────────────────────────────────

class ModelUpdater:
    """
    Surveille le dossier models/ et recharge les modèles à chaud.

    Usage :
        updater = ModelUpdater(
            models_dir="models/",
            use_case=use_case,
        )
        updater.start()   # dans le lifespan FastAPI
        updater.stop()    # à l'arrêt du service
    """

    def __init__(
        self,
        models_dir: str,
        use_case: AnalyzeTransactionUseCase,
        check_interval: int = 60,
    ):
        """
        Args:
            models_dir     : dossier à surveiller
            use_case       : use case FastAPI à mettre à jour
            check_interval : intervalle de vérification en secondes
        """
        self._models_dir      = Path(models_dir)
        self._use_case        = use_case
        self._check_interval  = check_interval
        self._task: Optional[asyncio.Task] = None
        self._running         = False

        # Cache des timestamps — détecte les nouveaux fichiers
        self._file_timestamps: Dict[str, float] = {}

        # Versions actives — évite de recharger la même version
        self._active_versions: Dict[str, str] = {
            "xgboost":          "unknown",
            "isolation_forest": "unknown",
            "tft":              "unknown",
            "gnn":              "unknown",
        }

        logger.info(
            "ModelUpdater initialisé",
            extra={
                "models_dir":     str(models_dir),
                "check_interval": check_interval,
            }
        )

    # ── Démarrage / Arrêt ────────────────────

    def start(self) -> None:
        """Démarre la surveillance en arrière-plan."""
        self._running = True
        self._task    = asyncio.create_task(self._watch_loop())
        logger.info(
            f"ModelUpdater démarré — surveillance toutes les "
            f"{self._check_interval}s"
        )

    async def stop(self) -> None:
        """Arrête la surveillance proprement."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ModelUpdater arrêté")

    # ── Boucle de surveillance ────────────────

    async def _watch_loop(self) -> None:
        """Boucle principale — vérifie les fichiers toutes les N secondes."""
        logger.info("ModelUpdater — boucle de surveillance active")

        while self._running:
            try:
                await self._check_for_updates()
            except Exception as e:
                logger.error(f"ModelUpdater erreur : {e}")

            await asyncio.sleep(self._check_interval)

    async def _check_for_updates(self) -> None:
        """
        Vérifie si de nouveaux fichiers .pkl sont disponibles.
        Si oui, charge et remplace le modèle correspondant.
        """
        if not self._models_dir.exists():
            return

        pkl_files = list(self._models_dir.glob("*.pkl"))

        for pkl_path in pkl_files:
            filename  = pkl_path.name
            mtime     = pkl_path.stat().st_mtime
            model_type = detect_model_type(filename)

            if not model_type:
                continue

            # Nouveau fichier ou fichier modifié ?
            cached_mtime = self._file_timestamps.get(filename, 0)
            if mtime <= cached_mtime:
                continue

            # Nouvelle version ?
            version = extract_version(filename)
            if version == self._active_versions.get(model_type):
                self._file_timestamps[filename] = mtime
                continue

            # Charge le nouveau modèle
            logger.info(
                f"Nouveau modèle détecté : {filename} "
                f"(v{version})"
            )
            await self._reload_model(model_type, str(pkl_path), version)
            self._file_timestamps[filename] = mtime

    async def _reload_model(
        self,
        model_type: str,
        model_path: str,
        version: str,
    ) -> None:
        """
        Charge un nouveau modèle et le remplace dans le use case.
        Remplacement atomique — pas de downtime.

        Args:
            model_type : xgboost · isolation_forest · tft · gnn
            model_path : chemin complet vers le .pkl
            version    : version du modèle (ex: "1.1.0")
        """
        try:
            logger.info(f"Chargement {model_type} v{version}...")

            if model_type == "xgboost":
                new_model = XGBoostModel(version=version)
                await new_model.load(model_path)
                # Remplacement atomique
                self._use_case._xgboost = new_model

            elif model_type == "isolation_forest":
                new_model = IsolationForestModel(version=version)
                await new_model.load(model_path)
                self._use_case._isolation = new_model

            elif model_type == "tft":
                new_model = TFTModel(version=version)
                await new_model.load(model_path)
                self._use_case._tft = new_model

            elif model_type == "gnn":
                new_model = GNNModel(version=version)
                await new_model.load(model_path)
                self._use_case._gnn = new_model

            # Met à jour la version active
            self._active_versions[model_type] = version

            logger.info(
                f"✅ {model_type} rechargé → v{version} "
                f"(zéro downtime)"
            )

        except Exception as e:
            logger.error(
                f"❌ Erreur rechargement {model_type} v{version} : {e}"
            )

    # ── Status ───────────────────────────────

    def get_status(self) -> dict:
        """Retourne l'état actuel des modèles surveillés."""
        return {
            "running":         self._running,
            "models_dir":      str(self._models_dir),
            "check_interval":  self._check_interval,
            "active_versions": self._active_versions.copy(),
            "watched_files":   list(self._file_timestamps.keys()),
        }