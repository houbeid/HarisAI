"""
HarisAI — PysimLoader
=======================
Loader pour le dataset PaySim (mobile money africain).
https://www.kaggle.com/datasets/ealaxi/paysim1

Colonnes : step · type · amount · nameOrig · oldbalanceOrg ·
           newbalanceOrig · nameDest · oldbalanceDest ·
           newbalanceDest · isFraud · isFlaggedFraud

Lignes   : 6 362 620 transactions · 8 213 fraudes (0.129%)

Insights clés :
    - Seuls TRANSFER et CASH_OUT peuvent être frauduleux
    - 65% des fraudes ont oldbalanceDest = 0 (compte mule vide)
    - Montant moyen fraude : 1 467 967 vs 178 197 normal
"""

from __future__ import annotations

import logging
from typing import Tuple

import numpy as np
import pandas as pd

from .base_loader import BaseLoader

logger = logging.getLogger(__name__)


class PysimLoader(BaseLoader):

    @property
    def name(self) -> str:
        return "pysim"

    def load(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        logger.info(f"Chargement {self.name} : {path}")

        # Charge par chunks si le fichier est trop grand
        try:
            df = pd.read_csv(path)
        except MemoryError:
            logger.warning("MemoryError — chargement par chunks de 500K lignes")
            chunks = []
            for chunk in pd.read_csv(path, chunksize=500_000):
                chunks.append(chunk)
            df = pd.concat(chunks, ignore_index=True)

        X = pd.DataFrame()

        # ── Catégorie 1 : Transaction ──────────
        X["amount"]      = df["amount"]
        X["hour_of_day"] = (df["step"] % 24).astype(float)
        X["day_of_week"] = ((df["step"] // 24) % 7).astype(float)
        X["is_night"]    = ((X["hour_of_day"] >= 22) |
                            (X["hour_of_day"] <= 6)).astype(float)
        X["is_weekend"]  = (X["day_of_week"] >= 5).astype(float)

        # USSD — pas disponible dans PaySim
        X["is_ussd"]  = 0.0

        # Agent — CASH_OUT via agent physique
        X["is_agent"] = (df["type"] == "CASH_OUT").astype(float)

        # SIM swap — signal : nameDest commence par M (marchand)
        # Les fraudes envoient souvent vers des marchands fictifs
        X["sim_changed_72h"] = (
            df["nameDest"].str.startswith("M") &
            (df["type"] == "TRANSFER")
        ).astype(float) * 0.5

        # ── Catégorie 2 : Comportement ─────────
        X["amount_z_score"] = self._compute_z_score(df["amount"])

        # Écart entre solde attendu et solde réel = manipulation
        balance_diff = (df["oldbalanceOrg"] - df["newbalanceOrig"]).abs()
        X["is_new_device"] = (
            balance_diff > df["amount"] * 1.1
        ).astype(float)

        # Zone — pas disponible
        X["is_new_zone"] = 0.0

        # Heure inhabituelle
        X["is_unusual_hour"] = X["is_night"].copy()

        # TRANSFER = canal risqué pour fraude
        X["is_unusual_channel"] = (df["type"] == "TRANSFER").astype(float)

        # Compte dormant — solde origine très élevé
        X["is_dormant_account"] = (
            df["oldbalanceOrg"] > 1_000_000
        ).astype(float)

        # Nouveau compte — solde dest = 0 avant réception
        # Signal fort : 65% des fraudes ont oldbalanceDest = 0
        X["is_new_account"] = (df["oldbalanceDest"] == 0).astype(float)

        max_step = df["step"].max()
        X["account_age_days"] = (df["step"] / (max_step + 1) * 365)

        X["total_transactions"] = 50.0

        # Solde origine = approximation de l'historique client
        X["avg_amount_7d"]  = df["oldbalanceOrg"] * 0.02
        X["avg_amount_30d"] = df["oldbalanceOrg"] * 0.03

        # ── Catégorie 3 : Bénéficiaire + ratios
        # Nouveau bénéficiaire — solde dest = 0 avant réception
        X["is_new_beneficiary"] = (df["oldbalanceDest"] == 0).astype(float)

        # Marchand — nameDest commence par M
        X["beneficiary_is_merchant"] = (
            df["nameDest"].str.startswith("M")
        ).astype(float)

        X["ratio_to_avg"] = self._compute_ratio(df["amount"])

        y = df["isFraud"].values
        return self._to_numpy(X), y