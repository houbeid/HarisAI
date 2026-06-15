"""
HarisAI — Entraînement XGBoost
================================
Script principal — ne change JAMAIS.
Tout le mapping des datasets est dans data_loaders/.

Pour ajouter un nouveau dataset :
    1. Crée training/data_loaders/mon_loader.py
    2. Ajoute-le dans data_loaders/__init__.py REGISTRY
    3. Lance : python training/train_xgboost.py --datasets mon_loader:mon_fichier.csv

UTILISATION :
    # Un seul dataset
    python training/train_xgboost.py --datasets creditcard:data/creditcard.csv

    # Deux datasets combinés
    python training/train_xgboost.py \
        --datasets creditcard:data/creditcard.csv pysim:data/pysim.csv

    # Fine tuning avec données Bankily réelles
    python training/train_xgboost.py \
        --datasets creditcard:data/creditcard.csv bankily:data/bankily_export.csv \
        --version 1.1.0

DATASETS DISPONIBLES :
    creditcard  → creditcard.csv (Kaggle Credit Card Fraud)
    pysim       → pysim.csv (PaySim mobile money africain)
    bankily     → export PostgreSQL données réelles Bankily
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import mlflow
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.ml.models.xgboost_model import XGBoostModel
from training.data_loaders import REGISTRY

# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CHARGEMENT
# ─────────────────────────────────────────────

def load_datasets(dataset_args: list) -> tuple:
    """
    Charge et combine tous les datasets spécifiés.

    Args:
        dataset_args : liste de "nom:chemin"
                       ex: ["creditcard:data/creditcard.csv",
                            "pysim:data/pysim.csv"]

    Returns:
        X, y combinés
    """
    X_list, y_list = [], []

    for item in dataset_args:
        # Parse "nom:chemin"
        parts = item.split(":", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Format invalide : '{item}' — attendu 'nom:chemin'\n"
                f"Exemple : creditcard:training/data/creditcard.csv"
            )
        name, path = parts

        # Vérifie que le loader existe
        if name not in REGISTRY:
            available = list(REGISTRY.keys())
            raise ValueError(
                f"Loader '{name}' inconnu.\n"
                f"Disponibles : {available}"
            )

        # Vérifie que le fichier existe
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Fichier introuvable : {path}"
            )

        # Charge et valide
        loader = REGISTRY[name]
        logger.info(f"Chargement [{name}] depuis {path}")
        X, y = loader.load_and_validate(path)
        X_list.append(X)
        y_list.append(y)

    if not X_list:
        raise ValueError("Aucun dataset chargé")

    # Combine tous les datasets
    X_combined = np.vstack(X_list)
    y_combined  = np.concatenate(y_list)

    n_fraud = y_combined.sum()
    logger.info(
        f"Dataset combiné → {len(y_combined):,} lignes | "
        f"fraudes : {n_fraud:,} ({n_fraud/len(y_combined)*100:.3f}%)"
    )

    return X_combined, y_combined


# ─────────────────────────────────────────────
# ÉVALUATION
# ─────────────────────────────────────────────

def find_best_threshold(model, X_val, y_val) -> float:
    """Trouve le seuil F1 optimal."""
    y_proba = model._model.predict_proba(X_val)[:, 1]
    best_t, best_f1 = 0.5, 0.0
    for t in np.arange(0.1, 0.9, 0.05):
        f1 = f1_score(y_val, (y_proba >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    logger.info(f"Meilleur seuil : {best_t:.2f} (F1={best_f1:.4f})")
    return float(best_t)


def evaluate(model, X_test, y_test, threshold) -> dict:
    """Évalue le modèle sur le jeu de test."""
    y_proba = model._model.predict_proba(X_test)[:, 1]
    y_pred  = (y_proba >= threshold).astype(int)
    cm = confusion_matrix(y_test, y_pred)
    return {
        "auc_pr":    round(average_precision_score(y_test, y_proba), 4),
        "auc_roc":   round(roc_auc_score(y_test, y_proba), 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall":    round(recall_score(y_test, y_pred, zero_division=0), 4),
        "f1":        round(f1_score(y_test, y_pred, zero_division=0), 4),
        "threshold": threshold,
        "tn": int(cm[0][0]), "fp": int(cm[0][1]),
        "fn": int(cm[1][0]), "tp": int(cm[1][1]),
    }


def print_results(metrics: dict) -> None:
    fraud_pct = (metrics["tp"] / (metrics["tp"] + metrics["fn"]) * 100
                 if metrics["tp"] + metrics["fn"] > 0 else 0)
    false_pct = (metrics["fp"] / (metrics["fp"] + metrics["tn"]) * 100
                 if metrics["fp"] + metrics["tn"] > 0 else 0)
    print()
    print("═" * 55)
    print("  RÉSULTATS — HarisAI XGBoost")
    print("═" * 55)
    print(f"  AUC-PR    : {metrics['auc_pr']:.4f}  ← métrique principale")
    print(f"  AUC-ROC   : {metrics['auc_roc']:.4f}")
    print(f"  Précision : {metrics['precision']:.4f}")
    print(f"  Rappel    : {metrics['recall']:.4f}")
    print(f"  F1        : {metrics['f1']:.4f}")
    print(f"  Seuil     : {metrics['threshold']:.2f}")
    print()
    print("  Matrice de confusion :")
    print(f"    TN (normaux corrects)  : {metrics['tn']:>8,}")
    print(f"    FP (fausses alertes)   : {metrics['fp']:>8,}")
    print(f"    FN (fraudes manquées)  : {metrics['fn']:>8,}")
    print(f"    TP (fraudes détectées) : {metrics['tp']:>8,}")
    print()
    print(f"  Fraudes détectées : {fraud_pct:.1f}%")
    print(f"  Fausses alertes   : {false_pct:.3f}%")
    print("═" * 55)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main(args):
    logger.info("═" * 55)
    logger.info("  HarisAI — Entraînement XGBoost")
    logger.info(f"  Datasets : {args.datasets}")
    logger.info("═" * 55)
    start = time.time()

    # ── Étape 1 : Charger ─────────────────────
    logger.info("Étape 1/6 — Chargement des datasets")
    X, y = load_datasets(args.datasets)

    # ── Étape 2 : Split ───────────────────────
    logger.info("Étape 2/6 — Split 70/15/15")
    X_tmp, X_test, y_tmp, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_tmp, y_tmp, test_size=0.176, random_state=42, stratify=y_tmp
    )
    logger.info(
        f"train:{len(X_train):,} | val:{len(X_val):,} | test:{len(X_test):,}"
    )

    # ── Étape 3 : scale_pos_weight ────────────
    n_normal = (y_train == 0).sum()
    n_fraud  = (y_train == 1).sum()
    spw = float(n_normal / n_fraud)
    logger.info(f"scale_pos_weight = {n_normal:,}/{n_fraud} = {spw:.1f}")

    # ── Étape 4 : Entraînement ────────────────
    logger.info("Étape 4/6 — Entraînement XGBoost")
    mlflow.set_experiment("harisai-xgboost-fraud")

    with mlflow.start_run(run_name=f"xgboost-v{args.version}"):

        mlflow.log_params({
            "n_estimators":     args.n_estimators,
            "max_depth":        args.max_depth,
            "learning_rate":    args.learning_rate,
            "scale_pos_weight": round(spw, 1),
            "datasets":         " + ".join(
                d.split(":")[0] for d in args.datasets
            ),
            "n_train":          len(X_train),
            "n_fraud_train":    int(n_fraud),
        })

        t0 = time.time()
        model = XGBoostModel(version=args.version)
        model.train(
            X_train, y_train, X_val, y_val,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            scale_pos_weight=spw,
        )
        train_time = time.time() - t0
        logger.info(f"Entraîné en {train_time:.1f}s")

        # ── Étape 5 : Évaluation ──────────────
        logger.info("Étape 5/6 — Évaluation")
        best_t  = find_best_threshold(model, X_val, y_val)
        metrics = evaluate(model, X_test, y_test, best_t)
        print_results(metrics)

        mlflow.log_metrics({
            "test_auc_pr":    metrics["auc_pr"],
            "test_auc_roc":   metrics["auc_roc"],
            "test_precision": metrics["precision"],
            "test_recall":    metrics["recall"],
            "test_f1":        metrics["f1"],
            "test_tp":        metrics["tp"],
            "test_fp":        metrics["fp"],
            "train_time_s":   round(train_time, 1),
        })
        mlflow.log_param("best_threshold", best_t)

        importance = model.get_feature_importance()
        top5 = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
        logger.info("Top 5 features :")
        for name, imp in top5:
            logger.info(f"  {imp:.4f} | {name}")

        # ── Étape 6 : Sauvegarde ──────────────
        logger.info("Étape 6/6 — Sauvegarde")
        models_dir = Path(__file__).parent.parent / "models"
        models_dir.mkdir(exist_ok=True)
        path = models_dir / f"xgboost_v{args.version}.pkl"
        model.save(str(path))
        mlflow.log_artifact(str(path))
        mlflow.log_dict(importance, "feature_importance.json")

        total = time.time() - start
        print()
        print("═" * 55)
        print(f"  ✅ Modèle → {path.name}")
        print(f"  ✅ AUC-PR : {metrics['auc_pr']:.4f}")
        print(f"  ✅ Durée  : {total:.0f}s ({total/60:.1f} min)")
        print("═" * 55)

    return metrics


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="HarisAI — Entraînement XGBoost",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Loaders disponibles : {list(REGISTRY.keys())}

Exemples :
  python training/train_xgboost.py \\
      --datasets creditcard:training/data/creditcard.csv

  python training/train_xgboost.py \\
      --datasets creditcard:training/data/creditcard.csv \\
                 pysim:training/data/pysim.csv

  python training/train_xgboost.py \\
      --datasets bankily:training/data/bankily_export.csv \\
      --version 1.1.0
        """
    )
    p.add_argument(
        "--datasets",
        nargs="+",
        required=True,
        help="Liste de 'nom:chemin' — ex: creditcard:data/creditcard.csv"
    )
    p.add_argument("--version",       default="1.0.0")
    p.add_argument("--n-estimators",  type=int,   default=500)
    p.add_argument("--max-depth",     type=int,   default=6)
    p.add_argument("--learning-rate", type=float, default=0.05)
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)