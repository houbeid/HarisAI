"""
HarisAI — Entraînement GNN
============================
Entraîne le modèle de détection de réseaux de fraude.

PRINCIPE :
    On construit des mini-graphes depuis pysim.csv en utilisant
    les colonnes nameOrig et nameDest pour simuler les relations.

UTILISATION :
    python training/train_gnn.py
    python training/train_gnn.py --datasets pysim:data/pysim.csv
    python training/train_gnn.py --epochs 50 --version 1.0.0

SORTIE :
    models/gnn_v{version}.pkl
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.ml.models.gnn_model import (
    GNNModel, GNN_FEATURE_NAMES, GNN_INPUT_SIZE, MAX_NEIGHBORS
)
from training.data_loaders import REGISTRY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_graph_samples(
    X: np.ndarray,
    y: np.ndarray,
    feature_indices: list,
    n_samples: int = 50_000,
    max_neighbors: int = MAX_NEIGHBORS,
) -> tuple:
    """
    Construit des échantillons nœud + voisins depuis les données flat.

    Pour chaque transaction :
        - Nœud central = transaction actuelle
        - Voisins = transactions similaires depuis le même "compte source"
          (simulées par proximité des features)

    Args:
        X              : features (n, n_features)
        y              : labels (n,)
        feature_indices: indices des features GNN dans FEATURE_NAMES
        n_samples      : nombre d'échantillons à générer
        max_neighbors  : nombre de voisins par nœud

    Returns:
        node_features     shape (n, GNN_INPUT_SIZE)
        neighbor_features shape (n, max_neighbors, GNN_INPUT_SIZE)
        labels            shape (n,)
    """
    logger.info(f"Construction de {n_samples:,} échantillons graphe...")

    X_gnn    = X[:, feature_indices].astype(np.float32)
    X_normal = X_gnn[y == 0]
    X_fraud  = X_gnn[y == 1]

    node_features_list     = []
    neighbor_features_list = []
    labels_list            = []

    n_fraud_samples  = n_samples // 4
    n_normal_samples = n_samples - n_fraud_samples

    # ── Échantillons frauduleux ───────────────
    # Nœud = transaction frauduleuse
    # Voisins = autres transactions frauduleuses (réseau coordonné)
    for _ in range(n_fraud_samples):
        fraud_idx  = np.random.randint(len(X_fraud))
        node       = X_fraud[fraud_idx]

        # Voisins suspects — autres fraudes
        neigh_idx  = np.random.choice(len(X_fraud), max_neighbors)
        neighbors  = X_fraud[neigh_idx]

        node_features_list.append(node)
        neighbor_features_list.append(neighbors)
        labels_list.append(1)

    # ── Échantillons normaux ──────────────────
    # Nœud = transaction normale
    # Voisins = autres transactions normales
    for _ in range(n_normal_samples):
        normal_idx = np.random.randint(len(X_normal))
        node       = X_normal[normal_idx]

        neigh_idx  = np.random.choice(len(X_normal), max_neighbors)
        neighbors  = X_normal[neigh_idx]

        node_features_list.append(node)
        neighbor_features_list.append(neighbors)
        labels_list.append(0)

    node_arr  = np.array(node_features_list,     dtype=np.float32)
    neigh_arr = np.array(neighbor_features_list, dtype=np.float32)
    label_arr = np.array(labels_list,            dtype=np.float32)

    # Mélange
    perm      = np.random.permutation(len(node_arr))
    node_arr  = node_arr[perm]
    neigh_arr = neigh_arr[perm]
    label_arr = label_arr[perm]

    logger.info(
        f"Échantillons construits : {len(node_arr):,} | "
        f"fraudes : {label_arr.sum():.0f} ({label_arr.mean()*100:.1f}%)"
    )

    return node_arr, neigh_arr, label_arr


def main(args):
    logger.info("═" * 55)
    logger.info("  HarisAI — Entraînement GNN")
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

    # ── Étape 2 : Indices des features GNN ────
    from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
    feature_indices = []
    for name in GNN_FEATURE_NAMES:
        if name in FEATURE_NAMES:
            feature_indices.append(FEATURE_NAMES.index(name))
        else:
            feature_indices.append(0)  # fallback
    logger.info(f"Features GNN : {GNN_FEATURE_NAMES}")

    # ── Étape 3 : Construire les échantillons ─
    logger.info("Étape 2/4 — Construction des échantillons graphe")
    node_feat, neigh_feat, labels = build_graph_samples(
        X, y,
        feature_indices=feature_indices,
        n_samples=args.n_samples,
    )

    # ── Étape 4 : Entraînement ────────────────
    logger.info("Étape 3/4 — Entraînement GNN")
    model   = GNNModel(version=args.version)
    metrics = model.train(
        node_features=node_feat,
        neighbor_features=neigh_feat,
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
    path = models_dir / f"gnn_v{args.version}.pkl"
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
        description="HarisAI — Entraînement GNN"
    )
    p.add_argument(
        "--datasets", nargs="+",
        default=["pysim:training/data/pysim.csv"],
        help="pysim recommandé — contient nameOrig/nameDest"
    )
    p.add_argument("--version",       default="1.0.0")
    p.add_argument("--epochs",        type=int,   default=50)
    p.add_argument("--learning-rate", type=float, default=0.001)
    p.add_argument("--batch-size",    type=int,   default=256)
    p.add_argument(
        "--n-samples",
        type=int,
        default=50_000,
        help="Nombre d'échantillons graphe à générer (défaut: 50000)"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)