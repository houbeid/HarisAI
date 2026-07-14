"""
HarisAI — IBMAMLLoader
=========================
Loader pour le dataset "IBM Transactions for Anti Money Laundering (AML)"
(ealtman2019 — Kaggle)

POURQUOI CE DATASET POUR TFT/GNN :
    pysim et aryan génèrent des comptes UNIQUES par transaction
    → impossible de construire un vrai historique séquentiel (TFT)
    → impossible de construire un vrai graphe de relations (GNN)

    IBM AML a des comptes RÉELS qui réapparaissent dans des milliers
    de transactions, avec un vrai Timestamp ordonné :
        From Bank + Account → identifiant unique d'un compte émetteur
        To Bank + Account   → identifiant unique d'un compte destinataire
    → on peut trier par Timestamp et obtenir le VRAI historique d'un compte
    → on peut construire le VRAI graphe expéditeur→destinataire

FORMAT BRUT DU CSV (confirmé via format_kaggle_files.py officiel IBM) :
    Timestamp           — '%Y/%m/%d %H:%M'
    From Bank            — identifiant banque émettrice
    Account              — compte émetteur (colonne brute)
    To Bank               — identifiant banque destinataire
    Account.1             — compte destinataire (colonne brute, pandas renomme
                             automatiquement la 2e colonne "Account" en "Account.1")
    Amount Received        — montant reçu (devise destinataire)
    Receiving Currency      — devise de réception
    Amount Paid             — montant payé (devise émetteur)
    Payment Currency        — devise de paiement
    Payment Format           — méthode (Wire, ACH, Credit Card, Cheque, etc.)
    Is Laundering             — label (0=normal, 1=blanchiment)

FICHIERS DISPONIBLES (choisir un seul à la fois) :
    HI-Small_Trans.csv   — High Illicit ratio, recommandé pour démarrer
    HI-Medium_Trans.csv
    HI-Large_Trans.csv
    LI-Small_Trans.csv   — Low Illicit ratio (~0.05%), plus réaliste
    LI-Medium_Trans.csv
    LI-Large_Trans.csv

MAPPING VERS LES 22 FEATURE_NAMES :
    Certaines features mobile money n'existent pas dans ce dataset bancaire
    (pas de zone géographique, pas de device_id, pas d'USSD) → mises à 0.
    Les features comportementales (is_new_account, total_transactions,
    avg_amount_30d...) sont calculées RÉELLEMENT depuis l'historique
    du compte trié par Timestamp — contrairement aux autres loaders,
    ici cet historique est authentique, pas approximé.

UTILISATION :
    python training/train_tft.py \
        --datasets ibm_aml:training/data/HI-Small_Trans.csv

    python training/train_gnn.py \
        --datasets ibm_aml:training/data/HI-Small_Trans.csv
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .base_loader import BaseLoader

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────

# Payment Format considérés comme "canal inhabituel" — virements/crypto
# plus utilisés dans le layering que les paiements classiques
UNUSUAL_PAYMENT_FORMATS = {"Wire", "Cheque", "ACH"}

# Un compte est "nouveau" s'il a moins de N transactions dans son historique
NEW_ACCOUNT_THRESHOLD = 3

# Un compte est "dormant" s'il a un historique mais rien depuis longtemps
# (approximé ici via un grand nombre de tx totales mais peu récentes)
DORMANT_GAP_HOURS = 720  # 30 jours

# Seuils pour is_mule_pattern — DOIVENT rester synchronisés avec les
# valeurs par défaut de BeneficiaryProfile.is_likely_mule() dans
# domain/transaction.py (fan_in_threshold=15, outflow_hours_threshold=24.0).
# Dupliqués ici plutôt qu'importés car ce module ne doit pas dépendre du
# domaine (voir Clean Architecture — training/ est hors des couches
# domain/application/infrastructure) ; si l'un des deux change, l'autre
# doit être mis à jour manuellement.
MULE_FAN_IN_THRESHOLD = 15
MULE_OUTFLOW_HOURS_THRESHOLD = 24.0


def _distinct_senders_trailing_window(
    df: pd.DataFrame,
    receiver_col: str,
    sender_col: str,
    ts_col: str,
    window_days: int = 30,
) -> np.ndarray:
    """
    Pour chaque ligne, compte le nombre d'expéditeurs DISTINCTS ayant
    envoyé de l'argent à df[receiver_col] dans les `window_days` jours
    PRÉCÉDANT STRICTEMENT cette transaction (n'inclut jamais la
    transaction courante — évite la fuite, même principe que le
    shift(1) utilisé ailleurs dans ce loader).

    Approche : two-pointer par groupe de destinataire — O(n) au total
    (chaque ligne entre et sort de la fenêtre glissante une seule fois),
    pas O(n²). Pas de solution pandas native vectorisée pour un "compte
    de valeurs distinctes dans une fenêtre glissante" — contrairement à
    une somme ou une moyenne glissante, donc implémenté explicitement.

    ATTENTION PERFORMANCE : contrairement à build_sequences() (chapitre 6
    de la doc technique), cette fonction n'a PAS été mesurée sur un vrai
    fichier IBM AML à plusieurs millions de lignes (aucun CSV disponible
    dans cet environnement). Le two-pointer est O(n) en théorie, mais
    l'implémentation ci-dessous boucle en Python pur à l'intérieur de
    chaque groupe — à benchmarker sur un échantillon avant de lancer sur
    le fichier complet. Si trop lent, envisager Numba ou Cython sur cette
    fonction spécifiquement (le reste du loader restera inchangé).

    Returns:
        numpy array shape (n,) — aligné ligne à ligne avec df (PAS avec
        l'ordre trié interne), même contrat que les autres colonnes X.
    """
    sorted_df = df[[receiver_col, sender_col, ts_col]].sort_values(
        [receiver_col, ts_col]
    )
    order_index = sorted_df.index.to_numpy()
    result = np.zeros(len(df), dtype=np.int32)
    window = pd.Timedelta(days=window_days)

    for _, group in sorted_df.groupby(receiver_col, sort=False):
        ts = group[ts_col].to_numpy()
        senders = group[sender_col].to_numpy()
        idx = group.index.to_numpy()

        left = 0
        counts: dict = {}
        distinct = 0
        for right in range(len(group)):
            # Retire de la fenêtre tout ce qui est trop vieux par
            # rapport à CETTE transaction (ts[right])
            while left < right and ts[left] <= ts[right] - window:
                s_left = senders[left]
                counts[s_left] -= 1
                if counts[s_left] == 0:
                    distinct -= 1
                left += 1

            # Résultat pour cette ligne = distinct AVANT d'ajouter sa
            # propre transaction à la fenêtre (exclut la transaction
            # courante — c'est la garantie anti-fuite)
            result[idx[right]] = distinct

            # Ajoute la transaction courante pour les lignes suivantes
            s_right = senders[right]
            counts[s_right] = counts.get(s_right, 0) + 1
            if counts[s_right] == 1:
                distinct += 1

    return result


def _outflow_speed_hours(
    df: pd.DataFrame,
    account_col_as_receiver: str,
    account_col_as_sender: str,
    ts_col: str,
) -> np.ndarray:
    """
    Pour chaque ligne (une réception par account_col_as_receiver au
    temps ts_col), calcule le délai en heures entre :
        - la dernière réception STRICTEMENT ANTÉRIEURE reçue par ce
          même compte (état "avant" cette transaction — la transaction
          courante elle-même n'est jamais comptée comme sa propre
          "dernière réception", même logique anti-fuite que partout
          ailleurs dans ce loader)
        - la dernière sortie de fonds STRICTEMENT ANTÉRIEURE de ce même
          compte (ce compte agissant comme account_col_as_sender dans
          une AUTRE transaction, avant ts_col)

    Réplique BeneficiaryProfile.outflow_speed_hours() : NaN si aucune
    réception antérieure, ou si aucune sortie antérieure, ou si la
    dernière sortie a eu lieu avant la dernière réception (pas de
    sortie consécutive à mesurer).

    Implémentation : pd.merge_asof (backward, exact matches exclus) —
    vectorisé, pas de boucle Python, adapté à plusieurs millions de
    lignes (contrairement à _distinct_senders_trailing_window ci-dessus).

    Returns:
        numpy array shape (n,) de float — NaN si non calculable.
    """
    # Flux des réceptions : à quel moment chaque compte a-t-il reçu ?
    # merge_asof exige un tri GLOBAL par la clé temporelle (pas juste
    # par groupe) — le paramètre `by` gère le groupement séparément.
    receipts = (
        df[[account_col_as_receiver, ts_col]]
        .rename(columns={account_col_as_receiver: "account"})
        .sort_values(ts_col)
    )
    # Flux des sorties : à quel moment chaque compte a-t-il envoyé ?
    sends = (
        df[[account_col_as_sender, ts_col]]
        .rename(columns={account_col_as_sender: "account"})
        .sort_values(ts_col)
    )

    main = df[[account_col_as_receiver, ts_col]].rename(
        columns={account_col_as_receiver: "account"}
    )
    main = main.reset_index().rename(columns={"index": "_orig_idx"})
    main_sorted = main.sort_values(ts_col)

    # Dernière réception STRICTEMENT antérieure pour ce compte
    receipts_renamed = receipts.rename(columns={ts_col: "last_received_at"})
    last_receipt = pd.merge_asof(
        main_sorted, receipts_renamed,
        left_on=ts_col, right_on="last_received_at", by="account",
        direction="backward", allow_exact_matches=False,
    )

    sends_renamed = sends.rename(columns={ts_col: "last_outflow_at"})
    last_outflow = pd.merge_asof(
        main_sorted, sends_renamed,
        left_on=ts_col, right_on="last_outflow_at", by="account",
        direction="backward", allow_exact_matches=False,
    )

    last_received_at = last_receipt["last_received_at"].to_numpy()
    last_outflow_at = last_outflow["last_outflow_at"].to_numpy()

    delta_hours = (
        (last_outflow_at - last_received_at) / np.timedelta64(1, "h")
    )
    # NaN si pas de réception antérieure, pas de sortie antérieure,
    # ou sortie avant la réception (pas de sortie consécutive)
    valid = (
        ~pd.isna(last_received_at)
        & ~pd.isna(last_outflow_at)
        & (last_outflow_at >= last_received_at)
    )
    delta_hours = np.where(valid, delta_hours, np.nan)

    # Remet dans l'ordre original de df (main_sorted a été trié pour
    # le merge_asof — _orig_idx permet de revenir à l'ordre d'entrée)
    result = np.full(len(df), np.nan)
    result[main_sorted["_orig_idx"].to_numpy()] = delta_hours
    return result


class IBMAMLLoader(BaseLoader):
    """
    Loader pour le dataset IBM AML — comptes réels, vraies séquences
    temporelles, vrai graphe de transferts.

    Args:
        low_memory : True  → échantillonne 30% des transactions normales
                              (garde toutes les fraudes) pour machines < 16GB
                     False → charge tout (recommandé sur Kaggle 30GB)
    """

    def __init__(self, low_memory: bool = True):
        self._low_memory = low_memory
        self._last_account_ids: Optional[np.ndarray] = None
        self._last_beneficiary_ids: Optional[np.ndarray] = None
        self._last_is_mule_pattern: Optional[np.ndarray] = None
        self._last_tx_velocity_ratio: Optional[np.ndarray] = None
        self._last_amount_cumul_ratio: Optional[np.ndarray] = None
        self._last_rapid_transfer_flag: Optional[np.ndarray] = None
        self._last_many_beneficiaries_flag: Optional[np.ndarray] = None

    @property
    def name(self) -> str:
        return "ibm_aml"

    def load(self, path: str) -> Tuple[np.ndarray, np.ndarray]:
        """
        Args:
            path : chemin vers un fichier *_Trans.csv
                   ex: training/data/HI-Small_Trans.csv
        """
        filepath = Path(path)
        if not filepath.exists():
            raise FileNotFoundError(f"Fichier introuvable : {filepath}")

        mode = "low_memory" if self._low_memory else "full"
        logger.info(f"Chargement IBM AML [{mode}] depuis : {filepath}")

        # ── Étape 1 : Charge le CSV brut ───────────
        df = pd.read_csv(
            filepath,
            usecols=[
                "Timestamp", "From Bank", "Account",
                "To Bank", "Account.1",
                "Amount Received", "Receiving Currency",
                "Amount Paid", "Payment Currency",
                "Payment Format", "Is Laundering",
            ],
        )
        logger.info(f"  CSV brut → {len(df):,} transactions")

        # ── Étape 2 : Parse le Timestamp ───────────
        df["Timestamp"] = pd.to_datetime(
            df["Timestamp"], format="%Y/%m/%d %H:%M"
        )

        # ── Étape 3 : Construit les identifiants de compte ──
        # From Bank + Account = identifiant UNIQUE du compte émetteur
        # (un même numéro de compte peut exister dans plusieurs banques)
        from_account_str = (
            df["From Bank"].astype(str) + "_" + df["Account"].astype(str)
        )
        to_account_str = (
            df["To Bank"].astype(str) + "_" + df["Account.1"].astype(str)
        )

        # ── Encodage en entiers — CRITIQUE pour la mémoire à grande
        # échelle. Une colonne de chaînes Python sur des millions de
        # lignes coûte cher (~60-80 octets par chaîne, contre 8 octets
        # pour un int64) — sur HI-Medium (31,9M lignes), garder
        # from_account_id/to_account_id/pair_id en chaînes tout du long
        # a contribué à un plantage mémoire Kaggle ("tried to allocate
        # more memory than is available"). Même technique que
        # build_real_graph_samples() (train_gnn.py) utilise déjà pour
        # encoder ses propres comptes — np.unique(..., return_inverse=
        # True) sur l'ensemble combiné expéditeur+destinataire, pour que
        # la même chaîne obtienne TOUJOURS le même entier des deux côtés.
        # Toutes les opérations suivantes (tri, groupby, égalité) sont
        # identiques sur des entiers — aucune perte de fonctionnalité,
        # seulement un gain mémoire et souvent de vitesse.
        all_accounts_combined = pd.concat(
            [from_account_str, to_account_str], ignore_index=True
        )
        unique_accounts_arr, encoded_all = np.unique(
            all_accounts_combined, return_inverse=True
        )
        n_unique_accounts_total = len(unique_accounts_arr)
        n_rows = len(df)
        df["from_account_id"] = encoded_all[:n_rows].astype(np.int64)
        df["to_account_id"]   = encoded_all[n_rows:].astype(np.int64)
        del from_account_str, to_account_str, all_accounts_combined
        del unique_accounts_arr, encoded_all

        # ── Étape 4 : Trie par compte puis par temps ─
        # ESSENTIEL — permet de calculer un vrai historique séquentiel
        df = df.sort_values(["from_account_id", "Timestamp"]).reset_index(drop=True)

        # ── Étape 5 : Sampling si low_memory ────────
        if self._low_memory:
            df_fraud  = df[df["Is Laundering"] == 1].copy()
            df_normal = df[df["Is Laundering"] == 0].sample(
                frac=0.30, random_state=42
            )
            df = pd.concat([df_fraud, df_normal]).sort_values(
                ["from_account_id", "Timestamp"]
            ).reset_index(drop=True)
            del df_fraud, df_normal
            logger.info(
                f"  Après sampling 30% → {len(df):,} lignes | "
                f"fraudes : {df['Is Laundering'].sum():,}"
            )

        # ── Étape 6 : Historique RÉEL par compte ────
        # Contrairement aux autres loaders, ceci est un vrai historique
        # car from_account_id réapparaît authentiquement dans le dataset
        logger.info("  Calcul de l'historique réel par compte...")

        df["account_tx_index"] = df.groupby("from_account_id").cumcount()
        df["total_transactions"] = df.groupby("from_account_id").cumcount() + 1

        # Montant moyen glissant des transactions PRÉCÉDENTES du compte
        # (shift(1) pour ne pas inclure la transaction actuelle — évite la fuite)
        df["avg_amount_30d"] = (
            df.groupby("from_account_id")["Amount Paid"]
            .transform(lambda s: s.shift(1).expanding().mean())
            .fillna(df["Amount Paid"])
        )
        df["avg_amount_7d"] = df["avg_amount_30d"]  # même approximation faute de fenêtre 7j fiable

        # Premier timestamp vu pour ce compte → âge du compte en jours
        first_seen = df.groupby("from_account_id")["Timestamp"].transform("min")
        df["account_age_days"] = (
            (df["Timestamp"] - first_seen).dt.total_seconds() / 86400
        )

        # Écart depuis la transaction précédente du même compte (en heures)
        df["gap_hours"] = (
            df.groupby("from_account_id")["Timestamp"]
            .diff()
            .dt.total_seconds() / 3600
        ).fillna(0)

        # ── Étape 7 : Construit les features ────────
        X = pd.DataFrame()

        # Catégorie 1 — Transaction
        X["amount"]      = df["Amount Paid"]
        X["hour_of_day"] = df["Timestamp"].dt.hour.astype(float)
        X["day_of_week"] = df["Timestamp"].dt.dayofweek.astype(float)
        X["is_night"]    = ((X["hour_of_day"] < 6) | (X["hour_of_day"] >= 22)).astype(float)
        X["is_weekend"]  = (X["day_of_week"] >= 5).astype(float)
        X["is_ussd"]     = 0.0  # absent — dataset bancaire, pas mobile money
        X["is_agent"]    = 0.0  # absent — pas de notion d'agent physique ici

        # sim_changed_72h — approximé via "premier transfert vers ce
        # destinataire après un long gap" (signal de compte compromis)
        X["sim_changed_72h"] = (
            (df["gap_hours"] > 72) & (df["account_tx_index"] > 0)
        ).astype(float)

        # Catégorie 2 — Comportement (calculé sur historique RÉEL)
        amt_mean = df["Amount Paid"].mean()
        amt_std  = df["Amount Paid"].std()
        X["amount_z_score"]     = (df["Amount Paid"] - amt_mean) / (amt_std + 1e-8)
        X["is_new_device"]      = 0.0  # absent — pas de device_id dans ce dataset
        X["is_new_zone"]        = 0.0  # absent — pas de zone géographique

        # is_unusual_hour — réutilise is_night comme proxy raisonnable
        X["is_unusual_hour"]    = X["is_night"]

        # is_unusual_channel — Wire/Cheque/ACH = canaux plus utilisés en layering
        X["is_unusual_channel"] = df["Payment Format"].isin(
            UNUSUAL_PAYMENT_FORMATS
        ).astype(float)

        # is_dormant_account — beaucoup de tx historiques mais gros gap récent
        X["is_dormant_account"] = (
            (df["account_tx_index"] > 10) & (df["gap_hours"] > DORMANT_GAP_HOURS)
        ).astype(float)

        # is_new_account — vraiment nouveau dans CE dataset (premières tx)
        X["is_new_account"] = (
            df["account_tx_index"] < NEW_ACCOUNT_THRESHOLD
        ).astype(float)

        X["account_age_days"]   = df["account_age_days"].astype(float)
        X["total_transactions"] = df["total_transactions"].astype(float)
        X["avg_amount_7d"]      = df["avg_amount_7d"].astype(float)
        X["avg_amount_30d"]     = df["avg_amount_30d"].astype(float)

        # Catégorie 3 — Bénéficiaire + ratios
        # is_new_beneficiary — première fois que ce compte envoie à ce destinataire
        # pair_id — clé entière combinée (from*n_unique + to) plutôt qu'une
        # concaténation de chaînes ("from->to") — même raison mémoire que
        # l'encodage de from_account_id/to_account_id ci-dessus. Unique par
        # construction : deux comptes distincts ne peuvent jamais produire
        # la même clé combinée tant que to_account_id < n_unique_accounts_total
        # (garanti, puisque les deux colonnes sont encodées depuis le même
        # espace de valeurs uniques combiné).
        df["pair_id"] = (
            df["from_account_id"] * n_unique_accounts_total + df["to_account_id"]
        )
        df["pair_seen_before"] = df.groupby("pair_id").cumcount()
        X["is_new_beneficiary"] = (df["pair_seen_before"] == 0).astype(float)

        # beneficiary_is_merchant — absent dans ce dataset (pas de flag marchand)
        X["beneficiary_is_merchant"] = 0.0

        X["ratio_to_avg"] = (
            df["Amount Paid"] / (df["avg_amount_30d"] + 1e-8)
        ).clip(0, 1000).astype(float)

        # ── Label ───────────────────────────────────
        y = df["Is Laundering"].values.astype(np.float32)

        # ── is_mule_pattern (voir load_with_mule_pattern()) ──────────
        # Calculé ici, sur le même df déjà trié/enrichi, pour éviter de
        # reparser et retrier le CSV une seconde fois. Réplique fidèlement
        # BeneficiaryProfile.is_likely_mule() (domain/transaction.py) :
        # fan-in élevé (>15, fenêtre 30j) ET non-marchand ET sortie
        # rapide (<=24h). beneficiary_is_merchant est toujours 0.0 sur ce
        # dataset (voir plus haut) — la condition "non-marchand" est donc
        # TOUJOURS vraie ici, ce qui signifie que cet entraînement ne
        # valide QUE le fan-in et la vitesse de sortie, jamais le filet
        # de sécurité anti-faux-positif marchand (voir docstring de
        # load_with_mule_pattern() pour le détail de cette limite).
        distinct_senders_30d = _distinct_senders_trailing_window(
            df,
            receiver_col="to_account_id",
            sender_col="from_account_id",
            ts_col="Timestamp",
            window_days=30,
        )
        outflow_speed_hours = _outflow_speed_hours(
            df,
            account_col_as_receiver="to_account_id",
            account_col_as_sender="from_account_id",
            ts_col="Timestamp",
        )
        has_high_fan_in = distinct_senders_30d > MULE_FAN_IN_THRESHOLD
        has_rapid_outflow = (
            ~np.isnan(outflow_speed_hours)
            & (outflow_speed_hours <= MULE_OUTFLOW_HOURS_THRESHOLD)
        )
        # is_merchant toujours False ici (voir ci-dessus) — condition
        # "non-marchand" omise du ET car toujours vraie sur ce dataset.
        self._last_is_mule_pattern = (
            has_high_fan_in & has_rapid_outflow
        ).astype(np.float32)

        logger.info(
            f"  is_mule_pattern calculé → "
            f"{int(self._last_is_mule_pattern.sum()):,} lignes positives "
            f"({self._last_is_mule_pattern.mean()*100:.3f}%) | "
            f"ATTENTION : beneficiary_is_merchant toujours à 0 sur ce "
            f"dataset — le filet anti-faux-positif marchand n'est pas "
            f"exercé par cet entraînement (voir load_with_aml_features())"
        )

        # ── 4 features AML supplémentaires (voir load_with_aml_features()) ──
        # Répliquent EXACTEMENT les formules de FeatureEngineering._aml_features()
        # (infrastructure/ml/features/feature_engineering.py) — même variables
        # d'entrée (total_transactions, account_age_days, avg_amount_30d,
        # is_new_beneficiary, is_night) que celles DÉJÀ calculées ci-dessus
        # pour les 22 features XGBoost. Réutiliser ces mêmes colonnes garantit
        # zéro écart train/production sur ces variables d'entrée — seul le
        # calcul dérivé (ratio, flag) est nouveau ici.
        #
        # EXCLUES DE CE CALCUL (voir load_with_aml_features()) :
        # near_threshold_flag et round_amount_flag utilisent des seuils
        # absolus en MRU (9000-9990 MRU, multiples de 5000 MRU) — IBM AML
        # est un dataset bancaire en USD/multi-devises, sans conversion de
        # change fournie. Appliquer ces seuils MRU tels quels à des montants
        # en devises différentes n'aurait aucun sens (entraînerait sur du
        # bruit plutôt que sur un vrai signal de structuring).
        total_tx = X["total_transactions"].to_numpy()
        account_age = X["account_age_days"].to_numpy()
        avg_30d = X["avg_amount_30d"].to_numpy()
        amount_arr = X["amount"].to_numpy()
        is_new_benef_arr = X["is_new_beneficiary"].to_numpy().astype(bool)
        is_night_arr = X["is_night"].to_numpy().astype(bool)

        avg_tx_per_day = np.maximum(total_tx / np.maximum(account_age, 1), 0.1)
        recent_tx_estimate = np.minimum(total_tx, 10)
        self._last_tx_velocity_ratio = (
            recent_tx_estimate / (avg_tx_per_day * 30 + 1)
        ).astype(np.float32)

        monthly_avg = np.maximum(avg_30d, 1.0)
        estimated_daily_cumul = amount_arr * np.maximum(recent_tx_estimate / 30, 1)
        self._last_amount_cumul_ratio = (
            estimated_daily_cumul / (monthly_avg * 3 + 1)
        ).astype(np.float32)

        self._last_rapid_transfer_flag = (
            is_new_benef_arr & is_night_arr & (amount_arr > avg_30d * 2)
        ).astype(np.float32)

        # many_beneficiaries_flag — nécessite le nombre de bénéficiaires
        # DISTINCTS déjà connus par cet expéditeur AVANT cette transaction
        # (comptage cumulatif ALL-TIME, pas de fenêtre — même sémantique
        # que ClientProfile.known_beneficiary_tokens, une liste qui ne
        # s'expire jamais). Réutilise is_new_beneficiary (pair_seen_before
        # == 0, déjà calculé au-dessus) : chaque nouveau bénéficiaire
        # contribue exactement +1 au compte cumulatif la première fois
        # qu'il apparaît — pas besoin d'un two-pointer comme pour le
        # fan-in (fenêtre glissante 30j côté BÉNÉFICIAIRE, alors qu'ici
        # c'est un cumul ALL-TIME côté EXPÉDITEUR, structurellement plus
        # simple).
        df["is_new_beneficiary_flag"] = is_new_benef_arr.astype(int)
        known_beneficiaries_before = (
            df.groupby("from_account_id")["is_new_beneficiary_flag"]
            .transform(lambda s: s.shift(1).fillna(0).cumsum())
            .to_numpy()
        )
        self._last_many_beneficiaries_flag = (
            (known_beneficiaries_before > 20) & is_new_benef_arr
        ).astype(np.float32)

        logger.info(
            f"  4 features AML supplémentaires calculées : "
            f"tx_velocity_ratio (moy={self._last_tx_velocity_ratio.mean():.3f}), "
            f"amount_cumul_ratio (moy={self._last_amount_cumul_ratio.mean():.3f}), "
            f"rapid_transfer_flag ({int(self._last_rapid_transfer_flag.sum()):,} "
            f"positifs), many_beneficiaries_flag "
            f"({int(self._last_many_beneficiaries_flag.sum()):,} positifs)"
        )

        logger.info(
            f"IBM AML prêt → {X.shape[0]:,} lignes · {X.shape[1]} features | "
            f"fraudes : {y.sum():,.0f} ({y.mean()*100:.3f}%) | "
            f"comptes uniques : {df['from_account_id'].nunique():,}"
        )

        # Mémorise account_ids pour load_with_account_ids() — évite de
        # recharger et re-trier tout le CSV une seconde fois si l'appelant
        # a besoin du vrai historique chronologique par compte (TFT/GNN).
        self._last_account_ids = df["from_account_id"].values
        self._last_beneficiary_ids = df["to_account_id"].values

        return self._to_numpy(X), y

    def load_with_account_ids(
        self, path: str
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Identique à load(), mais retourne EN PLUS l'identifiant de compte
        (from_account_id) aligné ligne à ligne avec X et y, déjà trié
        chronologiquement par compte (même tri que dans load()).

        POURQUOI CETTE MÉTHODE EXISTE :
            build_sequences() (TFT) et build_graph_samples() (GNN)
            recevaient seulement X et y — sans savoir quel compte est
            quel, elles devaient FABRIQUER un contexte artificiel basé
            sur le montant (ex: "contexte = transactions avec montant
            < 30% de la fraude"). Cette construction crée un raccourci
            structurel que le modèle apprend à la place d'un vrai signal
            de fraude — confirmé par un diagnostic Cohen's d (aucune
            feature individuelle ni combinaison via XGBoost n'explique
            un AUC-ROC de 1.0 obtenu par le LSTM, alors que la structure
            de construction des séquences, elle, l'explique entièrement).

            Avec account_ids, on peut désormais construire de VRAIES
            séquences chronologiques par compte — l'historique réel
            précédant chaque transaction, sans contraste artificiel.

        Returns:
            X            : numpy array shape (n, 22) — comme load()
            y            : numpy array shape (n,) — comme load()
            account_ids  : numpy array shape (n,) — identifiant de compte
                           (string), aligné ligne à ligne avec X et y,
                           dans le même ordre trié chronologiquement
        """
        X, y = self.load(path)
        if self._last_account_ids is None or len(self._last_account_ids) != len(y):
            raise RuntimeError(
                "account_ids indisponibles ou désynchronisés — load() doit "
                "être appelé juste avant load_with_account_ids() sur le "
                "même fichier, sans appel intermédiaire à un autre loader."
            )
        return X, y, self._last_account_ids

    def load_with_graph_ids(
        self, path: str
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Identique à load_with_account_ids(), mais retourne EN PLUS
        beneficiary_ids (to_account_id) — nécessaire pour construire un
        VRAI graphe de transferts (qui envoie à qui), pas seulement un
        historique chronologique par compte expéditeur.

        POURQUOI CETTE MÉTHODE EXISTE :
            build_graph_samples() (GNN) avait le même type de fuite
            structurelle que build_sequences() (TFT) : les "voisins"
            d'un nœud frauduleux étaient choisis avec un contraste de
            montant artificiel (50% autres fraudes + 50% normaux à
            montant élevé), pas en suivant les VRAIES relations
            expéditeur→destinataire du dataset. Avec beneficiary_ids,
            on peut construire le graphe réel : pour un compte donné,
            quels sont ses VRAIS voisins (comptes avec qui il a
            effectivement transigé), sans biais de montant fabriqué.

        Returns:
            X              : numpy array shape (n, 22) — comme load()
            y              : numpy array shape (n,) — comme load()
            account_ids     : numpy array shape (n,) — from_account_id,
                              trié chronologiquement par compte
            beneficiary_ids  : numpy array shape (n,) — to_account_id,
                              même ordre que account_ids et X/y
        """
        X, y, account_ids = self.load_with_account_ids(path)
        if (
            self._last_beneficiary_ids is None
            or len(self._last_beneficiary_ids) != len(y)
        ):
            raise RuntimeError(
                "beneficiary_ids indisponibles ou désynchronisés — load() "
                "doit être appelé juste avant load_with_graph_ids() sur le "
                "même fichier, sans appel intermédiaire à un autre loader."
            )
        return X, y, account_ids, self._last_beneficiary_ids

    def load_with_aml_features(
        self, path: str
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
        """
        Méthode complète pour TFT/GNN : retourne TOUT ce dont
        build_real_sequences() (TFT) et build_real_graph_samples() (GNN)
        ont besoin en un seul appel — account_ids, beneficiary_ids, ET
        un dict de features AML calculées à partir du vrai historique
        par compte (pas d'un profil Redis vivant, mais son équivalent
        reconstruit rétrospectivement depuis IBM AML).

        aml_features contient 5 des 7 AML_FEATURE_NAMES
        (infrastructure/ml/features/feature_engineering.py) :
            - is_mule_pattern       : fan-in glissant 30j + vitesse de
                                      sortie — réplique BeneficiaryProfile.
                                      is_likely_mule() (domain/transaction.py)
            - tx_velocity_ratio     : réplique FeatureEngineering.
            - amount_cumul_ratio      _aml_features() EXACTEMENT, à partir
            - rapid_transfer_flag     des colonnes déjà présentes dans X
            - many_beneficiaries_flag (total_transactions, account_age_days,
                                      avg_amount_30d, is_new_beneficiary,
                                      is_night) — zéro écart train/production
                                      sur ces variables d'entrée.

        EXCLUES (voir load() pour le détail) — near_threshold_flag et
        round_amount_flag NE SONT PAS dans ce dict : leurs seuils absolus
        sont en MRU, inadaptés aux montants multi-devises d'IBM AML sans
        conversion de change (non fournie dans ce dataset). Toute
        extension future de TFT_FEATURE_NAMES/GNN_FEATURE_NAMES avec ces
        deux features nécessitera soit un dataset en MRU (données réelles
        Bankily), soit une conversion de change explicite et documentée.

        LIMITE CONNUE sur is_mule_pattern — à documenter dans toute
        présentation des métriques obtenues avec cette feature :
            beneficiary_is_merchant vaut TOUJOURS 0.0 sur ce dataset
            (pas de flag marchand dans les données bancaires IBM AML —
            voir load()). La condition "non-marchand" de is_likely_mule()
            est donc TOUJOURS vraie ici : cet entraînement valide le
            fan-in et la vitesse de sortie, mais NE VALIDE JAMAIS le
            filet de sécurité anti-faux-positif marchand décrit dans
            HarisAI_Documentation_Technique.docx section 3.5 (le cas du
            supermarché à fort volume qui ne doit jamais être flaggé).
            Ce filet reste donc non testé empiriquement tant que des
            données réelles Bankily avec statut marchand ne sont pas
            disponibles.

        ATTENTION PERFORMANCE — is_mule_pattern (fan-in glissant) n'est
        pas mesuré sur un vrai fichier IBM AML à plusieurs millions de
        lignes dans cet environnement (aucun CSV disponible ici). Voir
        la docstring de _distinct_senders_trailing_window() : benchmarker
        sur un échantillon avant de lancer sur le fichier complet. Les
        4 autres features AML sont de l'arithmétique vectorisée sur des
        colonnes déjà calculées — pas de risque de performance équivalent.

        Returns:
            X                : numpy array shape (n, 22) — comme load()
            y                : numpy array shape (n,) — comme load()
            account_ids      : numpy array shape (n,) — from_account_id,
                               trié chronologiquement par compte
            beneficiary_ids  : numpy array shape (n,) — to_account_id,
                               même ordre que account_ids et X/y
            aml_features     : dict[str, np.ndarray] — 5 clés listées
                               ci-dessus, chaque array shape (n,), même
                               ordre que X, y, account_ids
        """
        X, y, account_ids, beneficiary_ids = self.load_with_graph_ids(path)
        arrays = {
            "is_mule_pattern": self._last_is_mule_pattern,
            "tx_velocity_ratio": self._last_tx_velocity_ratio,
            "amount_cumul_ratio": self._last_amount_cumul_ratio,
            "rapid_transfer_flag": self._last_rapid_transfer_flag,
            "many_beneficiaries_flag": self._last_many_beneficiaries_flag,
        }
        for feature_name, arr in arrays.items():
            if arr is None or len(arr) != len(y):
                raise RuntimeError(
                    f"{feature_name} indisponible ou désynchronisé — "
                    f"load() doit être appelé juste avant "
                    f"load_with_aml_features() sur le même fichier, sans "
                    f"appel intermédiaire à un autre loader."
                )
        return X, y, account_ids, beneficiary_ids, arrays