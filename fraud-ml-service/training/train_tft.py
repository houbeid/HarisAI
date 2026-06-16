"""
HarisAI — Entraînement TFT
============================
Entraîne le modèle de détection de patterns temporels.

PRINCIPE :
    On groupe les transactions par client simulé et on construit
    des séquences temporelles de 10 transactions pour entraîner le LSTM.

UTILISATION :
    python training/train_tft.py
    python training/train_tft.py --datasets pysim:data/pysim.csv
    python training/train_tft.py --epochs 100 --version 1.0.0

SORTIE :
    models/tft_v{version}.pkl
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.ml.models.tft_model import (
    TFTModel, TFT_FEATURE_NAMES, SEQUENCE_LENGTH
)
from training.data_loaders import REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_sequences(
    X: np.ndarray,
    y: np.ndarray,
    feature_indices: list,
    seq_len: int = SEQUENCE_LENGTH,
    n_synthetic: int = 50_000,
) -> tuple:
    """
    Construit des séquences temporelles depuis les données flat.

    Stratégie :
        1. Pour les transactions frauduleuses — séquence avec la fraude
           en dernière position précédée de transactions normales
        2. Pour les normales — séquences de transactions similaires

    Args:
        X              : features (n_samples, n_features)
        y              : labels (n_samples,)
        feature_indices: indices des features TFT dans FEATURE_NAMES
        seq_len        : longueur des séquences
        n_synthetic    : nombre de séquences à générer

    Returns:
        sequences shape (n, seq_len, n_tft_features)
        labels    shape (n,)
    """
    logger.info(f"Construction de {n_synthetic:,} séquences temporelles...")

    # Sépare normaux et fraudes
    X_normal = X[y == 0]
    X_fraud  = X[y == 1]

    # Extrait uniquement les features TFT
    X_normal_tft = X_normal[:, feature_indices]
    X_fraud_tft  = X_fraud[:, feature_indices]

    sequences = []
    labels    = []

    n_fraud_seq  = n_synthetic // 4   # 25% fraudes
    n_normal_seq = n_synthetic - n_fraud_seq

    # ── Séquences frauduleuses ────────────────
    # La dernière transaction est une fraude
    # Les précédentes sont des transactions normales du même "client"
    for _ in range(n_fraud_seq):
        fraud_idx  = np.random.randint(len(X_fraud_tft))
        fraud_tx   = X_fraud_tft[fraud_idx]

        # Contexte : seq_len-1 transactions normales
        normal_indices = np.random.choice(len(X_normal_tft), seq_len - 1)
        context = X_normal_tft[normal_indices]

        seq = np.vstack([context, fraud_tx.reshape(1, -1)])
        sequences.append(seq)
        labels.append(1)

    # ── Séquences normales ────────────────────
    for _ in range(n_normal_seq):
        normal_indices = np.random.choice(len(X_normal_tft), seq_len)
        seq = X_normal_tft[normal_indices]
        sequences.append(seq)
        labels.append(0)

    sequences = np.array(sequences, dtype=np.float32)
    labels    = np.array(labels, dtype=np.float32)

    # Mélange
    perm = np.random.permutation(len(sequences))
    sequences = sequences[perm]
    labels    = labels[perm]

    logger.info(
        f"Séquences construites : {len(sequences):,} | "
        f"fraudes : {labels.sum():.0f} ({labels.mean()*100:.1f}%)"
    )

    return sequences, labels


def main(args):
    logger.info("═" * 55)
    logger.info("  HarisAI — Entraînement TFT")
    logger.info("═" * 55)
    start = time.time()

    # ── Étape 1 : Charger les données ─────────
    logger.info("Étape 1/4 — Chargement des datasets")
    X_list, y_list = [], []

    for item in args.datasets:
        name, path = item.split(":", 1)
        if not Path(path).exists():
            raise FileNotFoundError(f"Fichier introuvable : {path}")
        loader = REGISTRY[name]
        X, y = loader.load_and_validate(path)
        X_list.append(X)
        y_list.append(y)

    X = np.vstack(X_list)
    y = np.concatenate(y_list)

    logger.info(
        f"Dataset : {len(y):,} lignes | "
        f"fraudes : {y.sum():,} ({y.mean()*100:.3f}%)"
    )

    # ── Étape 2 : Indices des features TFT ────
    from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
    feature_indices = [
        FEATURE_NAMES.index(name)
        for name in TFT_FEATURE_NAMES
        if name in FEATURE_NAMES
    ]
    logger.info(f"Features TFT : {TFT_FEATURE_NAMES}")

    # ── Étape 3 : Construire les séquences ────
    logger.info("Étape 2/4 — Construction des séquences temporelles")
    sequences, labels = build_sequences(
        X, y,
        feature_indices=feature_indices,
        seq_len=SEQUENCE_LENGTH,
        n_synthetic=args.n_sequences,
    )

    # ── Étape 4 : Entraînement ────────────────
    logger.info("Étape 3/4 — Entraînement TFT")
    model   = TFTModel(version=args.version)
    metrics = model.train(
        sequences=sequences,
        labels=labels,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
    )
    logger.info(f"Métriques : {metrics}")

    # ── Étape 5 : Sauvegarde ──────────────────
    logger.info("Étape 4/4 — Sauvegarde")
    models_dir = Path(__file__).parent.parent / "models"
    models_dir.mkdir(exist_ok=True)
    path = models_dir / f"tft_v{args.version}.pkl"
    model.save(str(path))

    total = time.time() - start
    print()
    print("═" * 55)
    print(f"  ✅ Modèle → {path.name}")
    print(f"  ✅ Val loss : {metrics['best_val_loss']:.4f}")
    print(f"  ✅ Durée    : {total:.0f}s ({total/60:.1f} min)")
    print("═" * 55)


def parse_args():
    p = argparse.ArgumentParser(
        description="HarisAI — Entraînement TFT"
    )
    p.add_argument(
        "--datasets", nargs="+",
        default=["creditcard:training/data/creditcard.csv"],
    )
    p.add_argument("--version",       default="1.0.0")
    p.add_argument("--epochs",        type=int,   default=50)
    p.add_argument("--learning-rate", type=float, default=0.001)
    p.add_argument("--batch-size",    type=int,   default=256)
    p.add_argument(
        "--n-sequences",
        type=int,
        default=50_000,
        help="Nombre de séquences synthétiques à générer (défaut: 50000)"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)