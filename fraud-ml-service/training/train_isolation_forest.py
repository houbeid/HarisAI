"""
HarisAI — Entraînement Isolation Forest
==========================================
Entraîne le modèle de détection d'anomalies.

DIFFÉRENCE AVEC XGBOOST :
    XGBoost s'entraîne sur TOUTES les transactions (normales + fraudes)
    IsoForest s'entraîne UNIQUEMENT sur les transactions normales (Class=0)
    Il apprend le "territoire normal" et détecte tout ce qui en sort.

UTILISATION :
    python training/train_isolation_forest.py
    python training/train_isolation_forest.py --datasets creditcard:data/creditcard.csv
    python training/train_isolation_forest.py --contamination 0.005

SORTIE :
    models/isolation_forest_v{version}.pkl
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.ml.models.isolation_forest import IsolationForestModel
from training.data_loaders import REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(args):
    logger.info("═" * 55)
    logger.info("  HarisAI — Entraînement Isolation Forest")
    logger.info("═" * 55)
    start = time.time()

    # ── Étape 1 : Charger les données ─────────
    logger.info("Étape 1/4 — Chargement des datasets")
    X_list, y_list = [], []

    for item in args.datasets:
        name, path = item.split(":", 1)
        if name not in REGISTRY:
            raise ValueError(f"Loader '{name}' inconnu")
        if not Path(path).exists():
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        loader = REGISTRY[name]
        X, y = loader.load_and_validate(path)
        X_list.append(X)
        y_list.append(y)

    X = np.vstack(X_list)
    y = np.concatenate(y_list)

    logger.info(
        f"Dataset combiné → {len(y):,} lignes | "
        f"fraudes : {y.sum():,} ({y.mean()*100:.3f}%)"
    )

    # ── Étape 2 : Filtrer — normaux seulement ─
    logger.info("Étape 2/4 — Filtrage transactions normales")
    X_normal = X[y == 0]
    logger.info(f"Transactions normales : {len(X_normal):,}")

    # Split pour évaluation
    X_train_normal, X_val_normal = train_test_split(
        X_normal, test_size=0.2, random_state=42
    )

    # ── Étape 3 : Entraînement ────────────────
    logger.info("Étape 3/4 — Entraînement IsolationForest")
    model = IsolationForestModel(version=args.version)
    metrics = model.train(
        X_train=X_train_normal,
        n_estimators=args.n_estimators,
        contamination=args.contamination,
    )
    logger.info(f"Métriques : {metrics}")

    # ── Étape 4 : Évaluation ──────────────────
    logger.info("Étape 4/4 — Évaluation")

    # Test sur données mixtes (normales + fraudes)
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )

    # Prédit les anomalies
    raw_scores = model._model.decision_function(X_test)
    # Convertit en prédiction binaire (0=normal, 1=anomalie)
    y_pred = (model._model.predict(X_test) == -1).astype(int)
    # Convertit en scores normalisés pour AUC
    y_scores = np.array([
        model._normalize_score(s) for s in raw_scores
    ])

    cm = confusion_matrix(y_test, y_pred)
    tn, fp, fn, tp = cm.ravel()

    try:
        auc = roc_auc_score(y_test, y_scores)
    except Exception:
        auc = 0.0

    print()
    print("═" * 55)
    print("  RÉSULTATS — HarisAI Isolation Forest")
    print("═" * 55)
    print(f"  AUC-ROC   : {auc:.4f}")
    print(f"  Rappel    : {tp/(tp+fn):.4f}  ← fraudes détectées")
    print(f"  Précision : {tp/(tp+fp):.4f}" if (tp+fp) > 0 else "  Précision : N/A")
    print()
    print("  Matrice de confusion :")
    print(f"    TN : {tn:>8,}  ← normaux corrects")
    print(f"    FP : {fp:>8,}  ← fausses alertes")
    print(f"    FN : {fn:>8,}  ← fraudes manquées")
    print(f"    TP : {tp:>8,}  ← fraudes détectées")
    print("═" * 55)

    # ── Sauvegarde ────────────────────────────
    models_dir = Path(__file__).parent.parent / "models"
    models_dir.mkdir(exist_ok=True)
    path = models_dir / f"isolation_forest_v{args.version}.pkl"
    model.save(str(path))

    total = time.time() - start
    print()
    print("═" * 55)
    print(f"  ✅ Modèle → {path.name}")
    print(f"  ✅ AUC-ROC : {auc:.4f}")
    print(f"  ✅ Durée   : {total:.0f}s")
    print("═" * 55)


def parse_args():
    p = argparse.ArgumentParser(
        description="HarisAI — Entraînement Isolation Forest"
    )
    p.add_argument(
        "--datasets", nargs="+",
        default=["creditcard:training/data/creditcard.csv"],
        help="Liste de 'nom:chemin'"
    )
    p.add_argument("--version",       default="1.0.0")
    p.add_argument("--n-estimators",  type=int,   default=200)
    p.add_argument(
        "--contamination",
        type=float,
        default=0.01,
        help="Proportion d'anomalies attendue (défaut: 0.01 = 1%%)"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)