"""
HarisAI — Flower Client (Federated Learning)
=============================================
Client Federated Learning qui tourne chez chaque opérateur mobile money.

RÔLE :
    Améliore les modèles TFT et GNN localement sur les données de l'opérateur
    sans jamais envoyer ces données au serveur central.
    Envoie uniquement les poids du réseau (pas les données).

ARCHITECTURE FEDERATED :
    Serveur central (fraud-infrastructure/central-server/)
        ↓ envoie poids globaux
    Client Bankily (ce fichier)
        → fine-tune sur données Bankily locales
        → envoie poids mis à jour
    Client Sedad
        → fine-tune sur données Sedad locales
        → envoie poids mis à jour
    Serveur
        → FedAvg : moyenne pondérée de tous les poids
        → modèle global amélioré

MODÈLES SUPPORTÉS :
    TFT (LSTM + Attention)  → fine-tune sur historique séquentiel
    GNN (GraphSAGE)         → fine-tune sur graphes de transactions

POURQUOI PAS XGBOOST / ISOLATION FOREST :
    Ces modèles ne sont pas des réseaux de neurones → pas de gradients
    → pas de transfert de poids possible via Flower
    → stratégie alternative : réentraînement complet avec les données combinées

LANCEMENT :
    # Côté opérateur (Bankily)
    python infrastructure/federated/flower_client.py \
        --server-address 192.168.1.100:8080 \
        --operator BANKILY \
        --model tft \
        --data-path /data/bankily_transactions.csv

    # Pour le serveur central (séparé)
    → voir fraud-infrastructure/central-server/flower_server.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import flwr as fl
from flwr.common import (
    NDArrays,
    Parameters,
    Scalar,
    ndarrays_to_parameters,
    parameters_to_ndarrays,
)

# Ajoute le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.ml.models.tft_model import TFTModel, TFT_FEATURE_NAMES, SEQUENCE_LENGTH
from infrastructure.ml.models.gnn_model import GNNModel, GNN_FEATURE_NAMES, GNN_INPUT_SIZE, MAX_NEIGHBORS

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


# ─────────────────────────────────────────────
# UTILITAIRES POIDS
# ─────────────────────────────────────────────

def get_tft_weights(model: TFTModel) -> NDArrays:
    """Extrait les poids du réseau TFT comme liste de numpy arrays."""
    if not model._network:
        raise RuntimeError("TFT non initialisé")
    return [
        p.detach().cpu().numpy()
        for p in model._network.parameters()
    ]


def set_tft_weights(model: TFTModel, weights: NDArrays) -> None:
    """Charge les poids dans le réseau TFT."""
    params = [
        torch.tensor(w)
        for w in weights
    ]
    for p, w in zip(model._network.parameters(), params):
        p.data = w


def get_gnn_weights(model: GNNModel) -> NDArrays:
    """Extrait les poids du réseau GNN comme liste de numpy arrays."""
    if not model._network:
        raise RuntimeError("GNN non initialisé")
    return [
        p.detach().cpu().numpy()
        for p in model._network.parameters()
    ]


def set_gnn_weights(model: GNNModel, weights: NDArrays) -> None:
    """Charge les poids dans le réseau GNN."""
    params = [torch.tensor(w) for w in weights]
    for p, w in zip(model._network.parameters(), params):
        p.data = w


# ─────────────────────────────────────────────
# CLIENT TFT
# ─────────────────────────────────────────────

class TFTFlowerClient(fl.client.NumPyClient):
    """
    Client Flower pour le fine-tuning du TFT.

    Protocole Flower :
        get_parameters() → retourne les poids actuels au serveur
        set_parameters() → reçoit les poids globaux du serveur
        fit()            → fine-tune localement + retourne poids améliorés
        evaluate()       → évalue le modèle global sur données locales
    """

    def __init__(
        self,
        model: TFTModel,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        operator: str,
    ):
        self.model    = model
        self.X_train  = X_train
        self.y_train  = y_train
        self.X_val    = X_val
        self.y_val    = y_val
        self.operator = operator

    def get_parameters(self, config: Dict) -> NDArrays:
        """Retourne les poids TFT actuels au serveur."""
        logger.info(f"[{self.operator}] TFT → envoi poids au serveur")
        return get_tft_weights(self.model)

    def set_parameters(self, parameters: NDArrays) -> None:
        """Charge les poids globaux reçus du serveur."""
        set_tft_weights(self.model, parameters)

    def fit(
        self,
        parameters: NDArrays,
        config: Dict,
    ) -> Tuple[NDArrays, int, Dict]:
        """
        Fine-tune le TFT sur les données locales de l'opérateur.

        Returns:
            poids mis à jour, nombre d'exemples, métriques
        """
        # Charge les poids globaux
        self.set_parameters(parameters)

        epochs     = int(config.get("local_epochs", 5))
        batch_size = int(config.get("batch_size", 256))

        logger.info(
            f"[{self.operator}] TFT fine-tuning — "
            f"{epochs} epochs · {len(self.X_train):,} séquences"
        )

        # Fine-tune localement
        metrics = self.model.train(
            sequences=self.X_train,
            labels=self.y_train,
            epochs=epochs,
            batch_size=batch_size,
        )

        logger.info(
            f"[{self.operator}] TFT fine-tuning terminé — "
            f"val_loss={metrics['best_val_loss']:.4f}"
        )

        return (
            get_tft_weights(self.model),
            len(self.X_train),
            {"val_loss": metrics["best_val_loss"], "operator": self.operator},
        )

    def evaluate(
        self,
        parameters: NDArrays,
        config: Dict,
    ) -> Tuple[float, int, Dict]:
        """
        Évalue le modèle global sur les données locales de l'opérateur.

        Returns:
            loss, nombre d'exemples, métriques
        """
        self.set_parameters(parameters)

        import torch
        import torch.nn as nn

        self.model._network.eval()
        X_tensor = torch.tensor(self.X_val, dtype=torch.float32)
        y_tensor = torch.tensor(self.y_val, dtype=torch.float32).unsqueeze(1)

        criterion = nn.BCEWithLogitsLoss()
        with torch.no_grad():
            out  = self.model._network(X_tensor)
            loss = criterion(out, y_tensor).item()

        # Calcule l'accuracy
        preds    = (torch.sigmoid(out) > 0.5).float()
        accuracy = (preds == y_tensor).float().mean().item()

        logger.info(
            f"[{self.operator}] TFT évaluation — "
            f"loss={loss:.4f} accuracy={accuracy:.4f}"
        )

        return (
            loss,
            len(self.X_val),
            {"accuracy": accuracy, "operator": self.operator},
        )


# ─────────────────────────────────────────────
# CLIENT GNN
# ─────────────────────────────────────────────

class GNNFlowerClient(fl.client.NumPyClient):
    """
    Client Flower pour le fine-tuning du GNN.
    Même protocole que TFTFlowerClient.
    """

    def __init__(
        self,
        model: GNNModel,
        node_features: np.ndarray,
        neighbor_features: np.ndarray,
        labels: np.ndarray,
        node_val: np.ndarray,
        neighbor_val: np.ndarray,
        labels_val: np.ndarray,
        operator: str,
    ):
        self.model         = model
        self.node_features = node_features
        self.neigh_features= neighbor_features
        self.labels        = labels
        self.node_val      = node_val
        self.neigh_val     = neighbor_val
        self.labels_val    = labels_val
        self.operator      = operator

    def get_parameters(self, config: Dict) -> NDArrays:
        logger.info(f"[{self.operator}] GNN → envoi poids au serveur")
        return get_gnn_weights(self.model)

    def set_parameters(self, parameters: NDArrays) -> None:
        set_gnn_weights(self.model, parameters)

    def fit(
        self,
        parameters: NDArrays,
        config: Dict,
    ) -> Tuple[NDArrays, int, Dict]:
        self.set_parameters(parameters)

        epochs     = int(config.get("local_epochs", 5))
        batch_size = int(config.get("batch_size", 256))

        logger.info(
            f"[{self.operator}] GNN fine-tuning — "
            f"{epochs} epochs · {len(self.node_features):,} échantillons"
        )

        metrics = self.model.train(
            node_features=self.node_features,
            neighbor_features=self.neigh_features,
            labels=self.labels,
            epochs=epochs,
            batch_size=batch_size,
        )

        logger.info(
            f"[{self.operator}] GNN fine-tuning terminé — "
            f"val_loss={metrics['best_val_loss']:.4f}"
        )

        return (
            get_gnn_weights(self.model),
            len(self.node_features),
            {"val_loss": metrics["best_val_loss"], "operator": self.operator},
        )

    def evaluate(
        self,
        parameters: NDArrays,
        config: Dict,
    ) -> Tuple[float, int, Dict]:
        self.set_parameters(parameters)

        import torch
        import torch.nn as nn

        self.model._network.eval()
        Xn = torch.tensor(self.node_val,  dtype=torch.float32)
        Xe = torch.tensor(self.neigh_val, dtype=torch.float32)
        y  = torch.tensor(self.labels_val, dtype=torch.float32).unsqueeze(1)

        criterion = nn.BCEWithLogitsLoss()
        with torch.no_grad():
            out  = self.model._network(Xn, Xe)
            loss = criterion(out, y).item()

        preds    = (torch.sigmoid(out) > 0.5).float()
        accuracy = (preds == y).float().mean().item()

        logger.info(
            f"[{self.operator}] GNN évaluation — "
            f"loss={loss:.4f} accuracy={accuracy:.4f}"
        )

        return (
            loss,
            len(self.node_val),
            {"accuracy": accuracy, "operator": self.operator},
        )


# ─────────────────────────────────────────────
# FACTORY — construit le bon client
# ─────────────────────────────────────────────

def build_tft_client(
    model_path: str,
    data_path: str,
    operator: str,
) -> TFTFlowerClient:
    """
    Construit un client TFT Flower depuis un fichier de données local.

    Args:
        model_path : chemin vers le .pkl du TFT entraîné
        data_path  : chemin vers le CSV de transactions local
        operator   : nom de l'opérateur (BANKILY, SEDAD, MASRVI)
    """
    from sklearn.model_selection import train_test_split

    # Charge le modèle
    model = TFTModel()
    import asyncio
    asyncio.get_event_loop().run_until_complete(model.load(model_path))

    # Charge les données locales
    sequences, labels = _load_tft_data(data_path, operator)

    X_train, X_val, y_train, y_val = train_test_split(
        sequences, labels, test_size=0.2, random_state=42
    )

    return TFTFlowerClient(
        model=model,
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        operator=operator,
    )


def build_gnn_client(
    model_path: str,
    data_path: str,
    operator: str,
) -> GNNFlowerClient:
    """
    Construit un client GNN Flower depuis un fichier de données local.
    """
    from sklearn.model_selection import train_test_split

    model = GNNModel()
    import asyncio
    asyncio.get_event_loop().run_until_complete(model.load(model_path))

    node_feat, neigh_feat, labels = _load_gnn_data(data_path, operator)

    n_val = int(len(node_feat) * 0.2)
    return GNNFlowerClient(
        model=model,
        node_features=node_feat[:-n_val],
        neighbor_features=neigh_feat[:-n_val],
        labels=labels[:-n_val],
        node_val=node_feat[-n_val:],
        neighbor_val=neigh_feat[-n_val:],
        labels_val=labels[-n_val:],
        operator=operator,
    )


# ─────────────────────────────────────────────
# CHARGEMENT DONNÉES LOCALES
# ─────────────────────────────────────────────

def _load_tft_data(
    data_path: str,
    operator: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Charge les données locales de l'opérateur pour le TFT.
    Retourne des séquences de SEQUENCE_LENGTH transactions.

    En production : remplacé par un export PostgreSQL local.
    """
    import pandas as pd
    from training.data_loaders import REGISTRY

    logger.info(f"Chargement données TFT depuis : {data_path}")

    # Détecte le format (CSV ou dossier aryan)
    path = Path(data_path)
    if path.is_dir():
        loader = REGISTRY["aryan"]
    elif "pysim" in data_path.lower():
        loader = REGISTRY["pysim"]
    elif "creditcard" in data_path.lower():
        loader = REGISTRY["creditcard"]
    else:
        loader = REGISTRY["bankily"]

    X, y = loader.load_and_validate(data_path)

    # Construit des séquences TFT
    from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
    feature_indices = [
        FEATURE_NAMES.index(name)
        for name in TFT_FEATURE_NAMES
        if name in FEATURE_NAMES
    ]
    X_tft = X[:, feature_indices].astype(np.float32)

    # Génère des séquences
    sequences = _build_sequences(X_tft, y, n_sequences=10_000)
    labels    = _build_sequence_labels(y, n_sequences=10_000)

    logger.info(
        f"Données TFT prêtes → {len(sequences):,} séquences | "
        f"fraudes : {labels.sum():,}"
    )
    return sequences, labels


def _load_gnn_data(
    data_path: str,
    operator: str,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Charge les données locales de l'opérateur pour le GNN.
    """
    import pandas as pd
    from training.data_loaders import REGISTRY

    logger.info(f"Chargement données GNN depuis : {data_path}")

    path = Path(data_path)
    if path.is_dir():
        loader = REGISTRY["aryan"]
    elif "pysim" in data_path.lower():
        loader = REGISTRY["pysim"]
    else:
        loader = REGISTRY["bankily"]

    X, y = loader.load_and_validate(data_path)

    from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
    feature_indices = [
        FEATURE_NAMES.index(name)
        for name in GNN_FEATURE_NAMES
        if name in FEATURE_NAMES
    ]
    X_gnn = X[:, feature_indices].astype(np.float32)

    # Génère des échantillons graphe
    n = min(10_000, len(X_gnn))
    X_normal = X_gnn[y == 0]
    X_fraud  = X_gnn[y == 1]

    node_list, neigh_list, label_list = [], [], []

    for _ in range(n // 4):
        idx = np.random.randint(len(X_fraud))
        node_list.append(X_fraud[idx])
        neigh_idx = np.random.choice(len(X_fraud), MAX_NEIGHBORS)
        neigh_list.append(X_fraud[neigh_idx])
        label_list.append(1)

    for _ in range(n - n // 4):
        idx = np.random.randint(len(X_normal))
        node_list.append(X_normal[idx])
        neigh_idx = np.random.choice(len(X_normal), MAX_NEIGHBORS)
        neigh_list.append(X_normal[neigh_idx])
        label_list.append(0)

    return (
        np.array(node_list,  dtype=np.float32),
        np.array(neigh_list, dtype=np.float32),
        np.array(label_list, dtype=np.float32),
    )


def _build_sequences(
    X: np.ndarray,
    y: np.ndarray,
    n_sequences: int = 10_000,
) -> np.ndarray:
    """Construit des séquences TFT depuis les données flat."""
    X_normal = X[y == 0]
    X_fraud  = X[y == 1]
    sequences = []

    for _ in range(n_sequences // 4):
        idx      = np.random.randint(len(X_fraud))
        fraud_tx = X_fraud[idx]
        ctx_idx  = np.random.choice(len(X_normal), SEQUENCE_LENGTH - 1)
        context  = X_normal[ctx_idx]
        sequences.append(np.vstack([context, fraud_tx]))

    for _ in range(n_sequences - n_sequences // 4):
        idx = np.random.choice(len(X_normal), SEQUENCE_LENGTH)
        sequences.append(X_normal[idx])

    return np.array(sequences, dtype=np.float32)


def _build_sequence_labels(
    y: np.ndarray,
    n_sequences: int = 10_000,
) -> np.ndarray:
    """Construit les labels correspondant aux séquences."""
    n_fraud  = n_sequences // 4
    n_normal = n_sequences - n_fraud
    labels   = np.array([1] * n_fraud + [0] * n_normal, dtype=np.float32)
    np.random.shuffle(labels)
    return labels


# ─────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="HarisAI — Flower Client Federated Learning"
    )
    parser.add_argument(
        "--server-address",
        default="localhost:8080",
        help="Adresse du serveur Flower central (défaut: localhost:8080)"
    )
    parser.add_argument(
        "--operator",
        default="BANKILY",
        choices=["BANKILY", "SEDAD", "MASRVI"],
        help="Nom de l'opérateur"
    )
    parser.add_argument(
        "--model",
        default="tft",
        choices=["tft", "gnn"],
        help="Modèle à fine-tuner"
    )
    parser.add_argument(
        "--model-path",
        required=True,
        help="Chemin vers le .pkl du modèle entraîné"
    )
    parser.add_argument(
        "--data-path",
        required=True,
        help="Chemin vers les données locales de l'opérateur"
    )
    args = parser.parse_args()

    logger.info("═" * 55)
    logger.info("  HarisAI — Flower Client Federated Learning")
    logger.info(f"  Opérateur : {args.operator}")
    logger.info(f"  Modèle    : {args.model.upper()}")
    logger.info(f"  Serveur   : {args.server_address}")
    logger.info("═" * 55)

    # Construit le client
    if args.model == "tft":
        client = build_tft_client(
            model_path=args.model_path,
            data_path=args.data_path,
            operator=args.operator,
        )
    else:
        client = build_gnn_client(
            model_path=args.model_path,
            data_path=args.data_path,
            operator=args.operator,
        )

    # Démarre le client Flower
    logger.info(f"Connexion au serveur Flower : {args.server_address}")
    fl.client.start_client(
        server_address=args.server_address,
        client=client.to_client(),
    )


if __name__ == "__main__":
    main()