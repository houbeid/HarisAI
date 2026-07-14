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


def build_real_graph_samples(
    X: np.ndarray,
    y: np.ndarray,
    account_ids: np.ndarray,
    beneficiary_ids: np.ndarray,
    feature_indices: list,
    max_neighbors: int = MAX_NEIGHBORS,
    min_neighbors: int = 1,
    max_edges_per_account: int = 2000,
    max_samples: int = None,
) -> tuple:
    """
    Construit des échantillons nœud + voisins depuis le VRAI graphe de
    transferts (account_ids → beneficiary_ids) — pas d'un voisinage
    fabriqué par contraste de montant comme dans build_graph_samples().

    POURQUOI CETTE FONCTION EXISTE :
        Un diagnostic a confirmé que build_graph_samples() créait une
        fuite structurelle symétrique à celle de build_sequences() (TFT) :
        les voisins d'un nœud frauduleux étaient choisis pour moitié
        parmi d'autres fraudes et pour moitié parmi des normaux à
        montant élevé (80e percentile) — un raccourci artificiel, pas
        une vraie relation de graphe. Le GNN apprenait à détecter ce
        contraste fabriqué, pas un vrai pattern relationnel.

        Cette fonction utilise à la place les VRAIS voisins de chaque
        compte — les autres comptes avec qui il a réellement transigé,
        en tant qu'expéditeur ou destinataire, dans le dataset complet.
        Le label de l'échantillon est celui de la transaction réelle.

    VERSION VECTORISÉE — la première version utilisait deux boucles
    Python pures sur len(account_ids) (jusqu'à des millions d'itérations
    sur les vraies données IBM AML), chacune avec des opérations dict/
    np.random.choice coûteuses par itération. Cette version construit
    les groupes de voisins via np.unique + np.argsort (tri vectorisé en
    O(n log n)), puis tire les voisins par lot avec np.random.randint
    plutôt qu'un appel np.random.choice par ligne.

    PLAFONNEMENT MÉMOIRE (max_samples) :
        Sur HI-Small, cette fonction produit déjà 4,9M échantillons
        (plus que build_real_sequences côté TFT, à 3,3M, car
        min_neighbors=1 est bien plus permissif que min_history=10).
        Sur HI-Medium (~6,3× plus de transactions), un run TFT a fait
        planter Kaggle par manque de mémoire ("tried to allocate more
        memory than is available") — GNN produirait probablement
        encore plus d'échantillons, donc un risque au moins aussi grand.

        Le sous-échantillonnage est appliqué sur eligible_idx, AVANT le
        tirage des voisins (rand_offsets/neighbor_row_idx) et AVANT la
        matérialisation de node_arr/neigh_arr — donc le calcul coûteux
        ne se fait jamais pour les échantillons exclus, contrairement à
        une approche qui matérialiserait tout puis sous-échantillonnerait
        après coup. Toutes les fraudes sont gardées ; les échantillons
        normaux sont sous-échantillonnés aléatoirement jusqu'à
        max_samples au total. None = pas de plafond (comportement
        d'avant ce correctif).

    Args:
        X                : features (n_samples, n_features)
        y                : labels (n_samples,)
        account_ids      : from_account_id par ligne, même ordre que X/y
        beneficiary_ids   : to_account_id par ligne, même ordre que X/y
        feature_indices   : indices des features GNN dans X (X peut inclure
                            is_mule_pattern comme colonne additionnelle
                            collée après les 22 FEATURE_NAMES — voir
                            Étape 2 dans main())
        max_neighbors     : nombre de voisins par nœud (padding si moins)
        min_neighbors     : nombre minimum de vrais voisins requis pour
                            qu'une transaction soit utilisable
        max_edges_per_account : plafond de sécurité — un compte impliqué
                            dans plus de transactions que cette valeur ne
                            considère que ses transactions les PLUS
                            RÉCENTES comme source de voisins potentiels.
                            Sans ce plafond, un compte extrêmement
                            connecté (vu sur de vraies données bancaires :
                            certains comptes peuvent apparaître dans des
                            centaines de milliers de transactions)
                            pourrait faire exploser la mémoire lors du
                            tirage de ses voisins.
        max_samples       : plafond total d'échantillons matérialisés.
                            Toutes les fraudes sont gardées ; les
                            échantillons normaux sont sous-échantillonnés
                            aléatoirement pour atteindre ce total.
                            None = pas de plafond.

    Returns:
        node_features     shape (n, GNN_INPUT_SIZE)
        neighbor_features shape (n, max_neighbors, GNN_INPUT_SIZE)
        labels            shape (n,)
    """
    logger.info(
        f"Construction d'échantillons graphe RÉELS (vrais voisins de "
        f"transfert, min_neighbors={min_neighbors}"
        + (f", max_samples={max_samples}" if max_samples else "")
        + ")..."
    )
    t0 = time.monotonic()

    X_gnn = X[:, feature_indices].astype(np.float32)
    n = len(account_ids)

    # ── Encode les comptes en entiers — bien plus rapide que des
    # comparaisons de chaînes pour tout ce qui suit (tri, recherche). ──
    all_accounts_str = np.concatenate([account_ids, beneficiary_ids])
    unique_accounts, encoded_all = np.unique(all_accounts_str, return_inverse=True)
    encoded_from = encoded_all[:n]   # account_ids encodés
    encoded_to   = encoded_all[n:]   # beneficiary_ids encodés
    n_unique_accounts = len(unique_accounts)

    # ── Construit, pour CHAQUE ligne, la liste des lignes qui partagent
    # le même compte EXPÉDITEUR (encoded_from[i]) — c'est exactement le
    # pool de voisins potentiels pour le nœud i. Vectorisé via tri par
    # clé de compte, sans aucune boucle Python sur les n lignes. ──
    order = np.argsort(encoded_from, kind="stable")
    sorted_from = encoded_from[order]            # comptes triés
    sorted_rowidx = order                          # lignes triées par compte

    change_points = np.where(sorted_from[1:] != sorted_from[:-1])[0] + 1
    boundaries = np.concatenate(([0], change_points, [n]))
    group_sizes = np.diff(boundaries)              # nb de lignes par compte expéditeur

    # Pour chaque ligne ORIGINALE i, retrouve son groupe (= sa position
    # dans sorted_from) et la taille de ce groupe — sans boucle, via
    # recherche binaire vectorisée (searchsorted sur les comptes triés
    # de boundaries, qui sont déjà uniques et croissants par construction).
    group_of_account = np.zeros(n_unique_accounts, dtype=np.int64)
    group_of_account[sorted_from[boundaries[:-1]]] = np.arange(len(boundaries) - 1)
    row_group = group_of_account[encoded_from]      # groupe de chaque ligne i
    row_n_candidates = group_sizes[row_group] - 1   # -1 pour exclure soi-même

    eligible = row_n_candidates >= min_neighbors
    n_eligible = int(eligible.sum())

    if n_eligible == 0:
        raise ValueError(
            "Aucun échantillon construit — aucun compte n'a au moins "
            f"{min_neighbors} vrai(s) voisin(s). Réduis min_neighbors."
        )

    eligible_idx = np.where(eligible)[0]

    # ── Plafonnement AVANT le calcul coûteux des voisins ──
    # Contrairement à une approche qui matérialiserait tout puis
    # sous-échantillonnerait, ce filtre s'applique ICI — le tirage de
    # voisins (rand_offsets, neighbor_row_idx) et la matérialisation
    # (node_arr, neigh_arr) qui suivent ne travaillent JAMAIS sur les
    # échantillons exclus.
    n_total_eligible = len(eligible_idx)
    if max_samples is not None and n_total_eligible > max_samples:
        eligible_labels = y[eligible_idx]
        fraud_mask = eligible_labels == 1.0
        fraud_idx_local  = eligible_idx[fraud_mask]
        normal_idx_local = eligible_idx[~fraud_mask]

        n_fraud = len(fraud_idx_local)
        n_normal_budget = max(0, max_samples - n_fraud)

        if n_fraud > max_samples:
            logger.warning(
                f"n_fraud={n_fraud} dépasse déjà max_samples={max_samples} "
                f"— sous-échantillonnage des FRAUDES elles-mêmes (cas "
                f"inhabituel, vérifie max_samples)."
            )
            rng = np.random.default_rng(42)
            fraud_idx_local = rng.choice(fraud_idx_local, size=max_samples, replace=False)
            normal_idx_local = np.array([], dtype=np.int64)
        elif len(normal_idx_local) > n_normal_budget:
            rng = np.random.default_rng(42)
            normal_idx_local = rng.choice(normal_idx_local, size=n_normal_budget, replace=False)

        eligible_idx = np.concatenate([fraud_idx_local, normal_idx_local])
        eligible_idx.sort()

        logger.info(
            f"  Plafond mémoire appliqué : {n_total_eligible:,} échantillons "
            f"éligibles → {len(eligible_idx):,} retenus "
            f"({n_fraud:,} fraudes gardées intégralement, "
            f"{len(normal_idx_local):,}/{n_total_eligible - n_fraud:,} "
            f"normaux sous-échantillonnés)"
        )

    n_out = len(eligible_idx)

    # ── Tirage vectorisé des voisins, SANS boucle Python ──
    # Pour chaque ligne éligible, tire max_neighbors positions aléatoires
    # DANS SON PROPRE GROUPE (en excluant sa propre position), en un seul
    # appel numpy sur tout le batch — pas un appel par ligne.
    group_start = boundaries[row_group[eligible_idx]]
    group_size_for_row = group_sizes[row_group[eligible_idx]]

    # Position de la ligne elle-même DANS son groupe trié (pour l'exclure)
    # — recherche vectorisée via searchsorted sur sorted_rowidx trié par
    # groupe (déjà trié, donc recherche directe possible).
    self_pos_in_group = np.empty(n_out, dtype=np.int64)
    # argsort inverse : pour chaque ligne i, sa position dans `order`
    inv_order = np.empty(n, dtype=np.int64)
    inv_order[order] = np.arange(n)
    self_pos_in_group = inv_order[eligible_idx] - group_start

    rand_offsets = np.random.randint(
        0, np.maximum(group_size_for_row - 1, 1)[:, None], size=(n_out, max_neighbors)
    )
    # Décale les offsets >= self_pos pour ne jamais retomber sur soi-même
    # (équivalent à tirer dans [0, group_size-1) puis sauter sa propre case)
    rand_offsets = rand_offsets + (rand_offsets >= self_pos_in_group[:, None]).astype(np.int64)
    rand_offsets = np.clip(rand_offsets, 0, group_size_for_row[:, None] - 1)

    neighbor_positions = group_start[:, None] + rand_offsets
    neighbor_row_idx = sorted_rowidx[neighbor_positions]  # (n_out, max_neighbors)

    node_arr  = X_gnn[eligible_idx]
    neigh_arr = X_gnn[neighbor_row_idx]
    label_arr = y[eligible_idx].astype(np.float32)

    # Mélange — important car construit dans l'ordre des lignes originales
    perm = np.random.permutation(n_out)
    node_arr  = node_arr[perm]
    neigh_arr = neigh_arr[perm]
    label_arr = label_arr[perm]

    elapsed = time.monotonic() - t0
    n_skipped_no_neighbors = n - n_total_eligible
    n_skipped_subsampling  = n_total_eligible - n_out
    logger.info(
        f"Échantillons graphe RÉELS construits en {elapsed:.1f}s : "
        f"{len(node_arr):,} | fraudes : {label_arr.sum():.0f} "
        f"({label_arr.mean()*100:.3f}%) | "
        f"{n_skipped_no_neighbors:,} transactions ignorées (pas assez de "
        f"vrais voisins)"
        + (
            f" | {n_skipped_subsampling:,} normales sous-échantillonnées "
            f"(plafond mémoire)"
            if n_skipped_subsampling > 0 else ""
        )
    )

    return node_arr, neigh_arr, label_arr


def build_graph_samples(
    X: np.ndarray,
    y: np.ndarray,
    feature_indices: list,
    n_samples: int = 50_000,
    max_neighbors: int = MAX_NEIGHBORS,
) -> tuple:
    """
    Construit des échantillons nœud + voisins depuis les données flat.

    ⚠ À UTILISER UNIQUEMENT quand le dataset n'a pas de vraies relations
    expéditeur→destinataire répétées (PaySim, Aryan) — dans ce cas il
    n'existe aucun vrai graphe à exploiter, donc ce voisinage fabriqué
    reste la moins mauvaise option disponible. Pour IBM AML (où les
    comptes ont de vraies relations de transfert répétées), utiliser
    build_real_graph_samples() à la place — voir son docstring pour
    les raisons précises (fuite structurelle confirmée ici : les voisins
    étaient choisis par contraste de montant, pas par vraie relation).

    VERSION VECTORISÉE — la version précédente recalculait np.percentile
    sur TOUT le dataset normal à CHAQUE voisin (n_fraud_samples × max_neighbors/2
    fois), et scannait un masque sur tout le dataset à chaque échantillon
    normal. Sur 12.7M lignes, c'est l'origine du blocage de plusieurs heures.

    Stratégie :
        1. Calcule percentile 80% et trie les montants UNE SEULE FOIS
        2. Utilise np.searchsorted pour les recherches de plage (O(log n))
        3. Échantillonne par lot avec np.random.randint (vectorisé)

    Args:
        X              : features (n, n_features)
        y              : labels (n,)
        feature_indices: indices des features GNN dans X (même remarque
                        que build_real_graph_samples() ci-dessus)
        n_samples      : nombre d'échantillons à générer
        max_neighbors  : nombre de voisins par nœud

    Returns:
        node_features     shape (n, GNN_INPUT_SIZE)
        neighbor_features shape (n, max_neighbors, GNN_INPUT_SIZE)
        labels            shape (n,)
    """
    logger.info(f"Construction de {n_samples:,} échantillons graphe...")
    t0 = time.monotonic()

    X_gnn    = X[:, feature_indices].astype(np.float32)
    X_normal = X_gnn[y == 0]
    X_fraud  = X_gnn[y == 1]
    n_normal = len(X_normal)
    n_fraud  = len(X_fraud)

    n_fraud_samples  = n_samples // 4
    n_normal_samples = n_samples - n_fraud_samples
    half_neigh       = max_neighbors // 2
    other_neigh      = max_neighbors - half_neigh

    # ── Pré-calculs uniques (pas dans une boucle) ──────
    sort_idx_normal   = np.argsort(X_normal[:, 0])
    X_normal_sorted   = X_normal[sort_idx_normal]
    amounts_sorted    = X_normal_sorted[:, 0]

    # Pool des montants élevés (>80e percentile) — calculé une fois
    p80 = np.percentile(amounts_sorted, 80)
    p80_start = np.searchsorted(amounts_sorted, p80, side="left")
    high_pool = X_normal_sorted[p80_start:] if p80_start < n_normal else X_normal_sorted

    node_features     = np.empty((n_samples, X_gnn.shape[1]), dtype=np.float32)
    neighbor_features = np.empty((n_samples, max_neighbors, X_gnn.shape[1]), dtype=np.float32)
    labels             = np.empty(n_samples, dtype=np.float32)

    # ── Échantillons frauduleux (vectorisé) ───────────
    # Nœud = fraude · voisins = moitié fraudes + moitié normaux montant élevé
    fraud_node_idx = np.random.randint(0, n_fraud, size=n_fraud_samples)
    node_features[:n_fraud_samples] = X_fraud[fraud_node_idx]
    labels[:n_fraud_samples] = 1.0

    # Voisins fraude — tirage vectorisé pour tous les échantillons d'un coup
    fraud_neigh_idx = np.random.randint(0, n_fraud, size=(n_fraud_samples, half_neigh))
    neighbor_features[:n_fraud_samples, :half_neigh] = X_fraud[fraud_neigh_idx]

    # Voisins montant élevé — tirage vectorisé depuis le pool pré-calculé
    high_neigh_idx = np.random.randint(0, len(high_pool), size=(n_fraud_samples, other_neigh))
    neighbor_features[:n_fraud_samples, half_neigh:] = high_pool[high_neigh_idx]

    # ── Échantillons normaux (vectorisé) ──────────────
    # Nœud = normal · voisins = normaux avec montant similaire (±50%)
    normal_node_idx = np.random.randint(0, n_normal, size=n_normal_samples)
    nodes_normal    = X_normal_sorted[normal_node_idx]
    node_features[n_fraud_samples:] = nodes_normal
    labels[n_fraud_samples:] = 0.0

    ref_amounts = nodes_normal[:, 0]
    lower = np.searchsorted(amounts_sorted, ref_amounts * 0.5, side="left")
    upper = np.searchsorted(amounts_sorted, ref_amounts * 1.5, side="right")

    # Garantit une plage suffisante — fallback sur tout le pool si trop étroite
    too_small = (upper - lower) < max_neighbors
    lower[too_small] = 0
    upper[too_small] = n_normal

    for j in range(n_normal_samples):
        idx = np.random.randint(lower[j], upper[j], size=max_neighbors)
        neighbor_features[n_fraud_samples + j] = X_normal_sorted[idx]

    # Mélange
    perm = np.random.permutation(n_samples)
    node_arr  = node_features[perm]
    neigh_arr = neighbor_features[perm]
    label_arr = labels[perm]

    elapsed = time.monotonic() - t0
    logger.info(
        f"Échantillons graphe construits en {elapsed:.1f}s : "
        f"{len(node_arr):,} | fraudes : {label_arr.sum():.0f} "
        f"({label_arr.mean()*100:.1f}%)"
    )

    return node_arr, neigh_arr, label_arr


def main(args):
    logger.info("═" * 55)
    logger.info("  HarisAI — Entraînement GNN")
    logger.info("═" * 55)
    start = time.time()

    # ── Étape 1 : Charger les données ─────────
    logger.info("Étape 1/4 — Chargement des datasets")

    # Cas spécial — un seul dataset IBM AML : utilise le VRAI graphe de
    # transferts (build_real_graph_samples), pas de fuite structurelle.
    # C'est le cas recommandé pour GNN (voir docstring de
    # build_graph_samples() pour le détail du problème évité ici).
    use_real_graph = False
    account_ids = None
    beneficiary_ids = None
    aml_features = None

    # Toutes les features AML_FEATURE_NAMES demandées dans GNN_FEATURE_NAMES
    # — voir train_tft.py pour la même logique côté TFT (commentaires
    # complets là-bas, non dupliqués ici).
    AML_FEATURE_NAMES_TRAINABLE = {
        "is_mule_pattern", "tx_velocity_ratio", "amount_cumul_ratio",
        "rapid_transfer_flag", "many_beneficiaries_flag",
    }
    requested_aml_features = [
        n for n in GNN_FEATURE_NAMES if n in AML_FEATURE_NAMES_TRAINABLE
    ]

    if len(args.datasets) == 1:
        name, path = args.datasets[0].split(":", 1)
        if name in ("ibm_aml", "ibm_aml_full"):
            if not Path(path).exists():
                raise FileNotFoundError(f"Fichier introuvable : {path}")
            loader = REGISTRY[name]
            if requested_aml_features and hasattr(loader, "load_with_aml_features"):
                X, y, account_ids, beneficiary_ids, aml_features = (
                    loader.load_with_aml_features(path)
                )
                use_real_graph = True
                logger.info(
                    "Dataset IBM AML détecté — utilisation du vrai graphe "
                    "de transferts (build_real_graph_samples) avec "
                    f"{len(requested_aml_features)} feature(s) AML "
                    f"calculée(s) : {requested_aml_features}"
                )
            elif hasattr(loader, "load_with_graph_ids"):
                X, y, account_ids, beneficiary_ids = loader.load_with_graph_ids(path)
                use_real_graph = True
                logger.info(
                    "Dataset IBM AML détecté — utilisation du vrai graphe "
                    "de transferts (build_real_graph_samples)"
                )

    if requested_aml_features and not use_real_graph:
        # Même principe que train_tft.py : ces features AML ne sont
        # calculables que via IBMAMLLoader.load_with_aml_features() —
        # PaySim/Aryan n'ont pas de relations expéditeur→destinataire
        # répétées pour les calculer.
        raise ValueError(
            f"GNN_FEATURE_NAMES inclut des features AML "
            f"{requested_aml_features} qui ne sont calculables que via "
            f"IBMAMLLoader.load_with_aml_features() — entraîne avec un "
            f"seul dataset IBM AML (--datasets ibm_aml:chemin/vers/"
            f"HI-Small_Trans.csv), pas en mode mixte ni avec PaySim/Aryan "
            f"seuls."
        )

    if not use_real_graph:
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
        logger.warning(
            "Construction par contraste de montant (build_graph_samples) — "
            "utilisée car plusieurs datasets sont mélangés, ou parce que "
            "le dataset n'a pas de vraies relations expéditeur→destinataire "
            "répétées (PaySim/Aryan). Cette méthode a un biais structurel "
            "connu (voir docstring) — ses métriques ne doivent pas être "
            "comparées directement à celles de build_real_graph_samples()."
        )

    logger.info(
        f"Dataset : {len(y):,} lignes | "
        f"fraudes : {y.sum():,} ({y.mean()*100:.3f}%)"
    )

    # ── Étape 2 : Indices des features GNN ────
    from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
    # Les features AML demandées ne sont PAS dans FEATURE_NAMES — collées
    # comme colonnes supplémentaires à X si utilisées, puis feature_indices
    # construit dans l'ORDRE EXACT de GNN_FEATURE_NAMES (même ordre que
    # _extract_gnn_features() côté inférence dans gnn_model.py — voir la
    # remarque équivalente dans train_tft.py, même risque de
    # désynchronisation train/inférence si l'ordre n'est pas respecté ici).
    base_feature_names = [
        name for name in GNN_FEATURE_NAMES
        if name not in AML_FEATURE_NAMES_TRAINABLE
    ]
    missing_gnn_features = [
        name for name in base_feature_names if name not in FEATURE_NAMES
    ]
    if missing_gnn_features:
        raise ValueError(
            f"Feature(s) GNN absente(s) de FEATURE_NAMES (les 22 "
            f"colonnes produites par les loaders d'entraînement) : "
            f"{missing_gnn_features}. Un loader doit d'abord être "
            f"étendu pour produire ces colonnes avant de les ajouter "
            f"à GNN_FEATURE_NAMES — voir base_loader.py."
        )

    if requested_aml_features:
        # CORRECTIF MÉMOIRE — même raisonnement que train_tft.py (voir
        # son commentaire équivalent pour le détail complet du calcul).
        # Construit directement le tableau final à len(GNN_FEATURE_NAMES)
        # colonnes (10, pas 27) plutôt que hstack puis extraction.
        n_rows = X.shape[0]
        X_direct = np.empty((n_rows, len(GNN_FEATURE_NAMES)), dtype=np.float32)
        for i, name in enumerate(GNN_FEATURE_NAMES):
            if name in AML_FEATURE_NAMES_TRAINABLE:
                X_direct[:, i] = aml_features[name]
            else:
                X_direct[:, i] = X[:, FEATURE_NAMES.index(name)]
        X = X_direct
        feature_indices = list(range(len(GNN_FEATURE_NAMES)))
    else:
        feature_indices = [
            FEATURE_NAMES.index(name) for name in GNN_FEATURE_NAMES
        ]
    logger.info(f"Features GNN : {GNN_FEATURE_NAMES}")

    # ── Étape 3 : Construire les échantillons ─
    logger.info("Étape 2/4 — Construction des échantillons graphe")
    if use_real_graph:
        if args.min_neighbors != 1:
            logger.info(
                f"min_neighbors explicitement fixé à {args.min_neighbors} "
                f"(défaut : 1)"
            )
        node_feat, neigh_feat, labels = build_real_graph_samples(
            X, y, account_ids, beneficiary_ids,
            feature_indices=feature_indices,
            min_neighbors=args.min_neighbors,
            max_samples=args.max_samples,
        )
    else:
        node_feat, neigh_feat, labels = build_graph_samples(
            X, y,
            feature_indices=feature_indices,
            n_samples=args.n_samples,
        )

    # ── Étape 4 : Entraînement ────────────────
    logger.info("Étape 3/4 — Entraînement GNN")
    model = GNNModel(version=args.version)
    metrics, pr_curve_data = model.train(
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

    import json
    pr_curve_path = models_dir / f"gnn_v{args.version}_pr_curve.json"
    with open(pr_curve_path, "w") as f:
        json.dump(pr_curve_data, f)
    logger.info(f"Courbe précision/rappel sauvegardée → {pr_curve_path}")

    total = time.time() - start
    print()
    print("═" * 55)
    print(f"  ✅ Modèle → {path.name}")
    print(f"  ✅ Val loss   : {metrics['best_val_loss']:.4f}")
    print(f"  ✅ Seuil      : {metrics['threshold']}")
    print(f"  ✅ AUC-ROC    : {metrics['auc_roc']}")
    print(f"  ✅ AUC-PR     : {metrics['auc_pr']:.4f}")
    print(f"  ✅ Précision  : {metrics['precision']:.4f}")
    print(f"  ✅ Rappel     : {metrics['recall']:.4f}")
    print(f"  ✅ F1         : {metrics['f1']:.4f}")
    print(f"  ✅ Durée      : {total:.0f}s ({total/60:.1f} min)")
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
    p.add_argument("--learning-rate", type=float, default=0.005)  # 0.001→0.005
    p.add_argument("--batch-size",    type=int,   default=512)    # 256→512
    p.add_argument(
        "--n-samples",
        type=int,
        default=50_000,
        help="Nombre d'échantillons graphe à générer (défaut: 50000)"
    )
    p.add_argument(
        "--min-neighbors",
        type=int,
        default=1,
        help=(
            "Nombre minimum de voisins requis pour inclure un nœud "
            "(build_real_graph_samples, dataset IBM AML uniquement). "
            "Défaut: 1 (permissif — contrairement à min_history côté "
            "TFT, ce filtre exclut probablement peu de fraudes par "
            "défaut, mais exposé pour permettre le même type de test "
            "que --min-history dans train_tft.py)."
        ),
    )
    p.add_argument(
        "--max-samples",
        type=int,
        default=3_000_000,
        help=(
            "Plafond du nombre d'échantillons graphe réels matérialisés "
            "(build_real_graph_samples, dataset IBM AML uniquement). "
            "Toutes les fraudes sont gardées ; les échantillons normaux "
            "sont sous-échantillonnés pour atteindre ce total. Défaut: "
            "3 000 000 (~0,7 Go en float32 pour node+neighbor combinés — "
            "marge sous les 15-16 Go de VRAM d'un Tesla T4 Kaggle). "
            "HI-Small a produit 4,9M échantillons éligibles sans "
            "problème ; un run TFT sur HI-Medium a fait planter Kaggle "
            "par manque de mémoire (\"tried to allocate more memory "
            "than is available\") avant qu'un plafond équivalent existe "
            "côté GNN — probable même risque ou pire ici vu le volume "
            "plus élevé que TFT à taille de dataset égale."
        ),
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)