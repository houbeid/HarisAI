"""
HarisAI — PysimLoader (v2 — avec load_with_account_ids)
=========================================================
Loader pour le dataset PaySim (mobile money africain).
https://www.kaggle.com/datasets/ealaxi/paysim1

Colonnes : step · type · amount · nameOrig · oldbalanceOrg ·
           newbalanceOrig · nameDest · oldbalanceDest ·
           newbalanceDest · isFraud · isFlaggedFraud

Lignes   : 6 362 620 transactions · 8 213 fraudes (0.129%)

CORRECTIONS v2 :
─────────────────
① is_new_device     → fuite supprimée (newbalanceOrig retiré)
② is_new_account    → doublon supprimé (nameOrig starts C)
③ sim_changed_72h   → approximation plus neutre (amount > p95)
④ is_dormant_account → seuil adaptatif (p95 oldbalanceOrg)
⑤ avg_amount_7d/30d  → approximation via oldbalanceOrg documentée
⑥ load_with_account_ids() → NOUVEAU : expose nameOrig comme account_ids
                              pour que train_tft.py utilise
                              build_real_sequences() (vraies séquences
                              chronologiques par compte) au lieu de
                              build_sequences() (fuite structurelle
                              par contraste de montant)

COLONNES DÉLIBÉRÉMENT EXCLUES :
─────────────────────────────────
    newbalanceOrig  → solde APRÈS transaction = fuite directe
    newbalanceDest   → même problème côté destinataire
    isFlaggedFraud    → label dérivé trop restrictif
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .base_loader import BaseLoader

logger = logging.getLogger(__name__)


class PysimLoader(BaseLoader):

    def __init__(self):
        # Mémorisé après load() pour load_with_account_ids()
        self._last_account_ids: Optional[np.ndarray] = None

    @property
    def name(self) -> str:
        return "pysim"

    def load(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        logger.info(f"Chargement {self.name} : {path}")

        try:
            df = pd.read_csv(path)
        except MemoryError:
            logger.warning("MemoryError — chargement par chunks de 500K lignes")
            chunks = []
            for chunk in pd.read_csv(path, chunksize=500_000):
                chunks.append(chunk)
            df = pd.concat(chunks, ignore_index=True)

        n_total = len(df)
        n_fraud = df["isFraud"].sum()
        logger.info(
            f"PaySim brut → {n_total:,} transactions | "
            f"fraudes : {n_fraud:,} ({n_fraud/n_total*100:.3f}%)"
        )

        # Trie par compte puis par step pour garantir l'ordre chronologique
        # par compte — nécessaire pour build_real_sequences() qui suppose
        # que les lignes du même compte sont consécutives et ordonnées.
        # IBM AML fait ce tri dans le loader (sort_values par from_account_id
        # puis Timestamp) — on fait la même chose ici.
        df = df.sort_values(["nameOrig", "step"]).reset_index(drop=True)

        X = pd.DataFrame()

        # ── Catégorie 1 : Transaction ──────────────────────────────────
        X["amount"]      = df["amount"].astype(float)
        X["hour_of_day"] = (df["step"] % 24).astype(float)
        X["day_of_week"] = ((df["step"] // 24) % 7).astype(float)
        X["is_night"]    = (
            (X["hour_of_day"] >= 22) | (X["hour_of_day"] <= 6)
        ).astype(float)
        X["is_weekend"]  = (X["day_of_week"] >= 5).astype(float)

        # USSD — non disponible dans PaySim
        X["is_ussd"] = 0.0

        # Agent physique — CASH_OUT via agent dans le mobile money africain
        X["is_agent"] = (df["type"] == "CASH_OUT").astype(float)

        # sim_changed_72h — proxy : transaction dans le top 5% des montants
        # (approximation plus neutre que la v1 qui encodait partiellement
        # la structure de la fraude via nameDest)
        amount_p95 = float(df["amount"].quantile(0.95))
        X["sim_changed_72h"] = (df["amount"] > amount_p95).astype(float) * 0.3

        # ── Catégorie 2 : Comportement du compte ───────────────────────
        X["amount_z_score"] = self._compute_z_score(df["amount"])

        # is_new_device — solde AVANT insuffisant pour couvrir le montant
        # (fuite supprimée : newbalanceOrig retiré)
        X["is_new_device"] = (
            df["oldbalanceOrg"] < df["amount"] * 0.1
        ).astype(float)

        # Zone géographique — non disponible dans PaySim
        X["is_new_zone"] = 0.0

        # Heure inhabituelle — même logique que is_night
        X["is_unusual_hour"] = X["is_night"].copy()

        # Canal à risque — TRANSFER est le seul vecteur de fraude
        # avec CASH_OUT dans PaySim
        X["is_unusual_channel"] = (df["type"] == "TRANSFER").astype(float)

        # is_dormant_account — seuil adaptatif (p95 du dataset)
        balance_p95 = float(df["oldbalanceOrg"].quantile(0.95))
        X["is_dormant_account"] = (
            df["oldbalanceOrg"] > balance_p95
        ).astype(float)

        # is_new_account — type de compte expéditeur (C = client, M = marchand)
        # (doublon avec is_new_beneficiary supprimé)
        X["is_new_account"] = (
            df["nameOrig"].str.startswith("C")
        ).astype(float)

        # Âge du compte — normalisé sur 30 jours (durée de la simulation)
        max_step = int(df["step"].max())
        X["account_age_days"] = (
            (df["step"] / max(max_step, 1)) * 30
        ).astype(float)

        # Nombre de transactions — non disponible individuellement
        X["total_transactions"] = 50.0

        # avg_amount_7d / avg_amount_30d — proxy via oldbalanceOrg
        # (PaySim n'a pas d'historique individuel par compte avec fenêtre
        # glissante comme IBM AML — approximation documentée)
        X["avg_amount_7d"]  = (df["oldbalanceOrg"] * 0.02).astype(float)
        X["avg_amount_30d"] = (df["oldbalanceOrg"] * 0.03).astype(float)

        # ── Catégorie 3 : Bénéficiaire + ratios ───────────────────────
        # Nouveau bénéficiaire — destinataire avec solde initial = 0
        # Signal fort : 65% des fraudes ciblent des comptes vides
        X["is_new_beneficiary"] = (df["oldbalanceDest"] == 0).astype(float)

        # Marchand — destinataire dont le nom commence par M
        X["beneficiary_is_merchant"] = (
            df["nameDest"].str.startswith("M")
        ).astype(float)

        X["ratio_to_avg"] = self._compute_ratio(df["amount"])

        # is_mule_pattern — NON inclus ici volontairement.
        # Cette feature est calculée dynamiquement en production via
        # BeneficiaryProfile (analyze_transaction.py étape 2), pas depuis
        # un CSV statique. La mettre à 0.0 dans le loader faisait passer
        # X à 23 colonnes au lieu des 22 attendues par base_loader._to_numpy()
        # → AssertionError "Ordre features incorrect dans pysim".

        # ── Label ──────────────────────────────────────────────────────
        y = df["isFraud"].values.astype(np.float32)

        logger.info(
            f"PaySim prêt → {len(X):,} lignes · {X.shape[1]} features | "
            f"fraudes : {y.sum():.0f} ({y.mean()*100:.3f}%)"
        )

        # Mémorise nameOrig (déjà trié par compte) pour
        # load_with_account_ids() — même pattern qu'IBMAMLLoader
        self._last_account_ids = df["nameOrig"].values

        return self._to_numpy(X), y

    def load_with_account_ids(
        self, path: str
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Identique à load(), mais retourne EN PLUS nameOrig comme
        account_ids — permet à train_tft.py d'utiliser
        build_real_sequences() (vraies séquences chronologiques par
        compte) au lieu de build_sequences() (fuite structurelle par
        contraste de montant artificiel).

        PaySim a des comptes répétés sur 30 jours (step 1→743),
        exactement comme IBM AML a des comptes répétés — les vraies
        séquences chronologiques sont donc calculables et pertinentes.

        Returns:
            X            : numpy array (n, 22)
            y            : numpy array (n,)
            account_ids  : numpy array (n,) — nameOrig trié par compte
                           et chronologiquement, aligné avec X et y
        """
        X, y = self.load(path)
        if self._last_account_ids is None or len(self._last_account_ids) != len(y):
            raise RuntimeError(
                "account_ids indisponibles — load() doit être appelé "
                "juste avant load_with_account_ids() sur le même fichier."
            )
        return X, y, self._last_account_ids