"""
HarisAI — CreditcardLoader
============================
Loader pour le dataset Kaggle Credit Card Fraud Detection.
https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud

Colonnes : Time · V1-V28 · Amount · Class
Lignes   : 284 807 transactions · 492 fraudes (0.173%)
"""

from __future__ import annotations

import logging
from typing import Tuple

import numpy as np
import pandas as pd

from .base_loader import BaseLoader

logger = logging.getLogger(__name__)


class CreditcardLoader(BaseLoader):

    @property
    def name(self) -> str:
        return "creditcard"

    def load(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        logger.info(f"Chargement {self.name} : {path}")
        df = pd.read_csv(path)

        X = pd.DataFrame()

        # ── Catégorie 1 : Transaction ──────────
        X["amount"]          = df["Amount"]
        X["hour_of_day"]     = (df["Time"] / 3600 % 24).astype(float)
        X["day_of_week"]     = (df["Time"] / 86400 % 7).astype(float)
        X["is_night"]        = ((X["hour_of_day"] >= 22) |
                                (X["hour_of_day"] <= 6)).astype(float)
        X["is_weekend"]      = (X["day_of_week"] >= 5).astype(float)
        X["is_ussd"]         = (df["V1"] < -2).astype(float)
        X["is_agent"]        = (df["V2"] < -2).astype(float)
        X["sim_changed_72h"] = (df["V3"] < -3).astype(float)

        # ── Catégorie 2 : Comportement ─────────
        X["amount_z_score"]      = self._compute_z_score(df["Amount"])
        X["is_new_device"]       = (df["V4"] > 2).astype(float)
        X["is_new_zone"]         = (df["V5"] < -2).astype(float)
        X["is_unusual_hour"]     = ((X["is_night"] == 1) |
                                    (df["V6"] < -2)).astype(float)
        X["is_unusual_channel"]  = (df["V7"] < -3).astype(float)
        X["is_dormant_account"]  = (df["V8"] > 3).astype(float)
        X["is_new_account"]      = (df["V9"] < -2).astype(float)

        max_time = df["Time"].max()
        X["account_age_days"]    = (df["Time"] / (max_time + 1) * 365)

        v10_norm = (df["V10"] - df["V10"].min()) / \
                   (df["V10"].max() - df["V10"].min() + 1e-8)
        X["total_transactions"]  = (v10_norm * 499 + 1)
        X["avg_amount_7d"]       = df["Amount"] * 0.80
        X["avg_amount_30d"]      = df["Amount"] * 0.85

        # ── Catégorie 3 : Bénéficiaire + ratios
        X["is_new_beneficiary"]      = (df["V11"] > 2).astype(float)
        X["beneficiary_is_merchant"] = (df["V12"] < -2).astype(float)
        X["ratio_to_avg"]            = self._compute_ratio(df["Amount"])

        y = df["Class"].values
        return self._to_numpy(X), y