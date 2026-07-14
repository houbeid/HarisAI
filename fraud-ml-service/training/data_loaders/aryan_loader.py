"""
HarisAI — AryanLoader
======================
Loader pour le dataset "Financial Transactions Dataset for Fraud Detection"
(Aryan208 — Kaggle)

DEUX MODES :
    Mode local  (low_memory=True)  → sampling 20% pour machines < 16GB RAM
    Mode Kaggle (low_memory=False) → charge tout — 30GB RAM disponible

STRUCTURE DU DATASET :
    transactions.csv              → montant · type · soldes
    fraud_scenario_labels.csv     → labels enrichis (8 scénarios de fraude)
    balance_features.csv          → features de solde et erreurs
    network_features.csv          → features réseau pour GNN
    risk_features.csv             → score de risque rule-based
    sender_behavior_features.csv  → comportement expéditeur pour TFT
    sender_receiver_features.csv  → relation expéditeur/destinataire
    temporal_features.csv         → features temporelles

AVANTAGE VS PYSIM :
    - 8 scénarios de fraude enrichis (pas seulement isFraud binaire)
    - Features réseau réelles (sender_out_degree, receiver_in_degree)
    - Features comportementales précises (tx_count_24h, unique_receivers)
    - Features temporelles (day, hour, period_of_day)

UTILISATION :
    # Local (économise la RAM)
    python training/train_xgboost.py ^
        --datasets aryan:training/data/aryan

    # Kaggle (charge tout)
    loader = AryanLoader(low_memory=False)
    X, y = loader.load("training/data/aryan")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

from .base_loader import BaseLoader

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# COLONNES À CHARGER PAR FICHIER
# Uniquement ce dont on a besoin pour FEATURE_NAMES
# ─────────────────────────────────────────────

COLS = {
    "transactions.csv": [
        "transaction_id",
        "step",           # → hour_of_day · day_of_week
        "type",           # → is_agent · is_unusual_channel · sim_changed_72h
        "amount",         # → amount · amount_z_score · ratio_to_avg
        "is_merchant_dest",# → beneficiary_is_merchant
    ],
    "fraud_scenario_labels.csv": [
        "transaction_id",
        "is_original_fraud_label",  # → label (0/1)
        "fraud_scenario",           # info bonus sur le type de fraude
    ],
    "balance_features.csv": [
        "transaction_id",
        "is_dest_balance_zero_before",   # → signal compte mule
        "is_sender_balance_zero_after",  # → signal vidage de compte
        "orig_balance_error",            # → signal manipulation
    ],
    "network_features.csv": [
        "transaction_id",
        "sender_out_degree_so_far",      # → nb envois du sender
        "receiver_in_degree_so_far",     # → nb receptions du receiver
        "receiver_tx_count_so_far",      # → historique receiver
        "sender_receiver_network_count_so_far", # → relation sender/receiver
    ],
    "risk_features.csv": [
        "transaction_id",
        "risk_score_rule_based",      # → score règles métier
        "new_receiver_flag",          # → is_new_beneficiary
        "many_to_one_receiver_flag",  # → signal compte mule
        "suspicious_cashout_flag",    # → signal layering
        "high_amount_flag",           # → signal montant élevé
    ],
    "sender_behavior_features.csv": [
        "transaction_id",
        "sender_tx_count_total_so_far",  # → total_transactions
        "sender_tx_count_24h",           # → activité récente
        "sender_avg_amount_24h",         # → avg_amount_7d · avg_amount_30d
        "amount_to_sender_avg_ratio",    # → ratio_to_avg
        "sender_unique_receivers_24h",   # → diversité des envois
    ],
    "sender_receiver_features.csv": [
        "transaction_id",
        "is_new_receiver_for_sender",    # → is_new_beneficiary
        "same_receiver_count_24h",       # → fréquence vers même receiver
    ],
    "temporal_features.csv": [
        "transaction_id",
        "day",            # → day_of_week
        "hour",           # → hour_of_day
        "is_night",       # → is_night · is_unusual_hour
        "period_of_day",  # → contexte temporel
    ],
}


class AryanLoader(BaseLoader):
    """
    Loader pour le dataset Aryan — 8 fichiers mergés sur transaction_id.

    Args:
        low_memory : True  → sampling 20% pour machines avec peu de RAM
                     False → charge tout (recommandé sur Kaggle 30GB)
    """

    def __init__(self, low_memory: bool = True):
        self._low_memory = low_memory

    @property
    def name(self) -> str:
        return "aryan"

    def load(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        """
        Charge et merge les 8 fichiers du dataset Aryan.

        Args:
            path : chemin vers le DOSSIER contenant les 8 CSV
        """
        folder = Path(path)
        if not folder.exists():
            raise FileNotFoundError(f"Dossier introuvable : {folder}")

        mode = "low_memory" if self._low_memory else "full"
        logger.info(f"Chargement Aryan [{mode}] depuis : {folder}")

        # ── Étape 1 : Charge chaque fichier ───────
        dfs = {}
        for filename, cols in COLS.items():
            filepath = folder / filename
            if not filepath.exists():
                raise FileNotFoundError(
                    f"Fichier manquant : {filepath}\n"
                    f"Place les 8 fichiers CSV dans : {folder}"
                )
            logger.info(f"  {filename} → {len(cols)-1} features")
            dfs[filename] = pd.read_csv(filepath, usecols=cols)

        # ── Étape 2 : Merge sur transaction_id ────
        logger.info("Merge des 8 fichiers...")
        df = dfs["transactions.csv"]
        for filename in list(COLS.keys())[1:]:
            df = df.merge(dfs[filename], on="transaction_id", how="left")
            del dfs[filename]  # libère immédiatement après merge
        del dfs

        logger.info(
            f"Mergé → {len(df):,} transactions | "
            f"fraudes : {df['is_original_fraud_label'].sum():,} "
            f"({df['is_original_fraud_label'].mean()*100:.3f}%)"
        )

        # ── Étape 3 : Sampling si low_memory ──────
        if self._low_memory:
            df_fraud  = df[df["is_original_fraud_label"] == 1].copy()
            df_normal = df[df["is_original_fraud_label"] == 0].sample(
                frac=0.20, random_state=42
            )
            df = pd.concat([df_fraud, df_normal], ignore_index=True)
            df = df.sample(frac=1, random_state=42).reset_index(drop=True)
            del df_fraud, df_normal
            logger.info(
                f"Après sampling 20% → {len(df):,} lignes | "
                f"fraudes : {df['is_original_fraud_label'].sum():,}"
            )

        # ── Étape 4 : Construire FEATURE_NAMES ────
        X = pd.DataFrame()

        # ── Catégorie 1 : Transaction ──────────────

        # amount — montant direct
        X["amount"] = df["amount"]

        # hour_of_day — depuis temporal_features
        X["hour_of_day"] = df["hour"].astype(float)

        # day_of_week — depuis step ou temporal
        X["day_of_week"] = (df["day"] % 7).astype(float)

        # is_night — depuis temporal_features
        X["is_night"] = df["is_night"].astype(float)

        # is_weekend
        X["is_weekend"] = (X["day_of_week"] >= 5).astype(float)

        # is_ussd — pas disponible dans ce dataset
        X["is_ussd"] = 0.0

        # is_agent — CASH_OUT = agent physique
        X["is_agent"] = (df["type"] == "CASH_OUT").astype(float)

        # sim_changed_72h — signal composite :
        # TRANSFER vers non-marchand + solde dest = 0 + premier contact
        X["sim_changed_72h"] = (
            (df["is_merchant_dest"] == 0) &
            (df["type"] == "TRANSFER") &
            (df["is_dest_balance_zero_before"] == 1) &
            (df["is_new_receiver_for_sender"] == 1)
        ).astype(float)

        # ── Catégorie 2 : Comportement ─────────────

        # amount_z_score
        amt_mean = df["amount"].mean()
        amt_std  = df["amount"].std()
        X["amount_z_score"] = (df["amount"] - amt_mean) / (amt_std + 1e-8)

        # is_new_device — sender avec très peu de transactions historiques
        X["is_new_device"] = (
            df["sender_tx_count_total_so_far"] < 3
        ).astype(float)

        # is_new_zone — pas disponible
        X["is_new_zone"] = 0.0

        # is_unusual_hour
        X["is_unusual_hour"] = df["is_night"].astype(float)

        # is_unusual_channel — TRANSFER et CASH_OUT = canaux risqués
        X["is_unusual_channel"] = (
            df["type"].isin(["TRANSFER", "CASH_OUT"])
        ).astype(float)

        # is_dormant_account — actif historiquement mais pas récemment
        X["is_dormant_account"] = (
            (df["sender_tx_count_24h"] == 0) &
            (df["sender_tx_count_total_so_far"] > 10)
        ).astype(float)

        # is_new_account — sender très récent (< 3 tx)
        X["is_new_account"] = (
            df["sender_tx_count_total_so_far"] < 2
        ).astype(float)

        # account_age_days — approximation depuis l'historique
        max_count = df["sender_tx_count_total_so_far"].max()
        X["account_age_days"] = (
            df["sender_tx_count_total_so_far"] / (max_count + 1) * 365
        ).astype(float)

        # total_transactions
        X["total_transactions"] = df["sender_tx_count_total_so_far"].astype(float)

        # avg_amount_7d et 30d — depuis sender_behavior
        X["avg_amount_7d"]  = df["sender_avg_amount_24h"].astype(float)
        X["avg_amount_30d"] = df["sender_avg_amount_24h"].astype(float)

        # ── Catégorie 3 : Bénéficiaire + ratios ────

        # is_new_beneficiary — premier contact sender→receiver
        X["is_new_beneficiary"] = df["is_new_receiver_for_sender"].astype(float)

        # beneficiary_is_merchant
        X["beneficiary_is_merchant"] = df["is_merchant_dest"].astype(float)

        # ratio_to_avg — depuis sender_behavior
        X["ratio_to_avg"] = df["amount_to_sender_avg_ratio"].fillna(1.0).astype(float)

        # ── Label ──────────────────────────────────
        y = df["is_original_fraud_label"].values

        logger.info(
            f"Aryan prêt → {X.shape[0]:,} lignes · {X.shape[1]} features | "
            f"fraudes : {y.sum():,} ({y.mean()*100:.3f}%)"
        )

        return self._to_numpy(X), y