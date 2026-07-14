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


def build_real_sequences(
    X: np.ndarray,
    y: np.ndarray,
    account_ids: np.ndarray,
    feature_indices: list,
    seq_len: int = SEQUENCE_LENGTH,
    min_history: int = None,
    max_sequences: int = None,
) -> tuple:
    """
    Construit des séquences temporelles à partir du VRAI historique
    chronologique de chaque compte — pas d'un contraste artificiel
    basé sur le montant comme dans build_sequences().

    POURQUOI CETTE FONCTION EXISTE :
        Un diagnostic a confirmé que build_sequences() créait une fuite
        structurelle : la transaction frauduleuse était toujours placée
        en dernière position d'une séquence dont le contexte (positions
        0 à 8) était délibérément choisi avec un montant plus petit
        (< 30% du montant de la fraude). Le LSTM apprenait à détecter
        ce contraste artificiel — pas un vrai pattern de fraude — ce qui
        explique un AUC-ROC=1.0 alors qu'aucune feature individuelle ni
        combinaison (testée via arbre de décision et XGBoost) n'explique
        une séparation aussi parfaite.

        Cette fonction utilise à la place les N transactions qui
        précèdent RÉELLEMENT chaque transaction dans l'historique du
        MÊME compte (account_ids), dans leur vrai ordre chronologique.
        Le label de la séquence est celui de la DERNIÈRE transaction
        réelle du compte — sans aucun contraste fabriqué.

    PLAFONNEMENT MÉMOIRE (max_sequences) :
        Sur HI-Medium (31,9M transactions, 2,01M comptes), le nombre de
        séquences éligibles est de l'ordre de 20 millions — un tableau
        (20_000_000, seq_len, n_features) en float32 pèse ~11,6 Go,
        copié tel quel sur le GPU par tft_model.py (torch.tensor(...,
        device=...)). Un Tesla T4 Kaggle n'a que 15-16 Go de VRAM au
        total — un seul tenseur de cette taille a fait planter Kaggle
        ("tried to allocate more memory than is available", session
        redémarrée) lors du premier run sur HI-Medium (v1.5.1).

        Cette fonction évite de matérialiser TOUTES les séquences
        éligibles en mémoire avant de sous-échantillonner (ce qui
        recréerait le même problème) — elle fait DEUX passes :
        1. Collecte seulement les métadonnées légères (indices de
           début/fin + label) pour chaque séquence éligible — pas
           encore les vraies valeurs de features.
        2. Garde TOUTES les séquences de fraude (rares, précieuses —
           jamais sous-échantillonnées), sous-échantillonne aléatoirement
           les séquences normales jusqu'à max_sequences au total, PUIS
           SEULEMENT matérialise les vraies valeurs pour les séquences
           retenues.

        Si max_sequences=None (défaut), aucun plafond — comportement
        identique à avant ce correctif, adapté aux datasets plus petits
        (HI-Small, 3,3M séquences, a tourné sans problème sur GPU).

    Args:
        X               : features (n_samples, n_features)
        y               : labels (n_samples,)
        account_ids     : identifiant de compte par ligne, MÊME ORDRE que
                          X et y (voir IBMAMLLoader.load_with_account_ids())
        feature_indices : indices des features TFT dans X (X peut inclure
                          is_mule_pattern comme colonne additionnelle
                          collée après les 22 FEATURE_NAMES — voir Étape 2
                          dans main())
        seq_len         : longueur des séquences
        min_history     : nombre minimum de transactions précédentes
                          requises pour qu'un compte soit utilisable
                          (défaut : seq_len, pas de remplissage artificiel)
        max_sequences   : plafond total de séquences matérialisées.
                          Toutes les fraudes sont gardées ; les séquences
                          normales sont sous-échantillonnées aléatoirement
                          pour atteindre ce total. None = pas de plafond.

    Returns:
        sequences shape (n, seq_len, n_tft_features)
        labels    shape (n,)
    """
    if min_history is None:
        min_history = seq_len

    logger.info(
        f"Construction de séquences RÉELLES (historique chronologique "
        f"par compte, min_history={min_history}"
        + (f", max_sequences={max_sequences}" if max_sequences else "")
        + ")..."
    )
    t0 = time.monotonic()

    X_tft = X[:, feature_indices].astype(np.float32)

    # ── Passe 1 : métadonnées légères uniquement (pas de copie de
    # features à ce stade) — account_ids est déjà trié par compte
    # (voir IBMAMLLoader), donc un simple parcours séquentiel suffit.
    seq_starts   = []
    seq_ends     = []
    seq_labels   = []

    n = len(account_ids)
    start = 0
    while start < n:
        end = start
        current_acc = account_ids[start]
        while end < n and account_ids[end] == current_acc:
            end += 1
        # [start, end) = toutes les lignes de ce compte, déjà triées
        # chronologiquement par construction (voir le loader)

        n_tx_compte = end - start
        if n_tx_compte >= min_history:
            # Pour chaque transaction du compte à partir de la position
            # seq_len-1, retient les BORNES d'une séquence des seq_len
            # transactions qui la précèdent RÉELLEMENT (y compris
            # elle-même en dernière position) — pas encore les features.
            for i in range(seq_len - 1, n_tx_compte):
                seq_starts.append(start + i - seq_len + 1)
                seq_ends.append(start + i + 1)
                seq_labels.append(y[start + i])

        start = end

    if not seq_starts:
        raise ValueError(
            "Aucune séquence construite — aucun compte n'a au moins "
            f"{min_history} transactions. Réduis min_history ou vérifie "
            "que account_ids est bien trié par compte."
        )

    seq_starts = np.array(seq_starts, dtype=np.int64)
    seq_ends   = np.array(seq_ends, dtype=np.int64)
    seq_labels = np.array(seq_labels, dtype=np.float32)

    n_total_eligible = len(seq_starts)

    # ── Passe 2 : sélection AVANT matérialisation ──
    if max_sequences is not None and n_total_eligible > max_sequences:
        fraud_mask = seq_labels == 1.0
        fraud_idx  = np.where(fraud_mask)[0]
        normal_idx = np.where(~fraud_mask)[0]

        n_fraud = len(fraud_idx)
        n_normal_budget = max(0, max_sequences - n_fraud)

        if n_fraud > max_sequences:
            # Cas extrême (ne devrait pas arriver en pratique — la
            # fraude est toujours très minoritaire) : même les fraudes
            # seules dépassent le plafond. Sous-échantillonne aussi les
            # fraudes plutôt que de dépasser le plafond mémoire, mais
            # log un avertissement clair — perdre des exemples de
            # fraude est plus grave que perdre des exemples normaux.
            logger.warning(
                f"n_fraud={n_fraud} dépasse déjà max_sequences="
                f"{max_sequences} — sous-échantillonnage des FRAUDES "
                f"elles-mêmes (cas inhabituel, vérifie max_sequences)."
            )
            rng = np.random.default_rng(42)
            fraud_idx = rng.choice(fraud_idx, size=max_sequences, replace=False)
            normal_idx = np.array([], dtype=np.int64)
        elif len(normal_idx) > n_normal_budget:
            rng = np.random.default_rng(42)
            normal_idx = rng.choice(normal_idx, size=n_normal_budget, replace=False)

        selected_idx = np.concatenate([fraud_idx, normal_idx])
        selected_idx.sort()  # préserve un ordre cohérent, pas obligatoire mais plus lisible en log

        logger.info(
            f"  Plafond mémoire appliqué : {n_total_eligible:,} séquences "
            f"éligibles → {len(selected_idx):,} retenues "
            f"({n_fraud:,} fraudes gardées intégralement, "
            f"{len(normal_idx):,}/{n_total_eligible - n_fraud:,} normales "
            f"sous-échantillonnées)"
        )

        seq_starts = seq_starts[selected_idx]
        seq_ends   = seq_ends[selected_idx]
        seq_labels = seq_labels[selected_idx]

    # ── Matérialisation — SEULEMENT pour les séquences retenues ──
    sequences = np.stack([
        X_tft[s:e] for s, e in zip(seq_starts, seq_ends)
    ]).astype(np.float32)
    labels = seq_labels

    # Mélange — important, car les séquences sont actuellement ordonnées
    # par compte (tous les comptes A d'abord, puis B, etc.) — et, si un
    # plafond a été appliqué ci-dessus, re-triées par selected_idx.sort()
    perm = np.random.permutation(len(sequences))
    sequences = sequences[perm]
    labels    = labels[perm]

    elapsed = time.monotonic() - t0
    logger.info(
        f"Séquences réelles construites en {elapsed:.1f}s : "
        f"{len(sequences):,} | fraudes : {labels.sum():.0f} "
        f"({labels.mean()*100:.3f}%)"
    )

    return sequences, labels


def build_sequences(
    X: np.ndarray,
    y: np.ndarray,
    feature_indices: list,
    seq_len: int = SEQUENCE_LENGTH,
    n_synthetic: int = 50_000,
) -> tuple:
    """
    Construit des séquences temporelles depuis les données flat.

    ⚠ À UTILISER UNIQUEMENT quand les comptes ne se répètent jamais dans
    les données (PaySim, Aryan) — dans ce cas il n'existe aucun vrai
    historique chronologique à exploiter, donc cette construction
    artificielle reste la moins mauvaise option disponible. Pour IBM AML
    (où les comptes se répètent authentiquement), utiliser
    build_real_sequences() à la place — voir son docstring pour les
    raisons précises (fuite structurelle confirmée dans cette fonction).

    VERSION VECTORISÉE — évite le goulot d'étranglement O(n_synthetic × n_rows)
    de la version précédente qui recalculait un masque sur TOUT le dataset
    normal à chaque itération de boucle Python.

    Stratégie :
        1. Trie X_normal_tft par montant UNE SEULE FOIS (O(n log n))
        2. Pour chaque séquence, utilise np.searchsorted pour trouver
           la plage de montants similaires en O(log n) au lieu de O(n)
        3. Échantillonne par batch avec np.random.randint (vectorisé)

    Args:
        X              : features (n_samples, n_features)
        y              : labels (n_samples,)
        feature_indices: indices des features TFT dans X (même remarque
                        que pour build_real_sequences() ci-dessus)
        seq_len        : longueur des séquences
        n_synthetic    : nombre de séquences à générer

    Returns:
        sequences shape (n, seq_len, n_tft_features)
        labels    shape (n,)
    """
    logger.info(f"Construction de {n_synthetic:,} séquences temporelles...")
    t0 = time.monotonic()

    # Sépare normaux et fraudes
    X_normal = X[y == 0]
    X_fraud  = X[y == 1]

    # Extrait uniquement les features TFT
    X_normal_tft = X_normal[:, feature_indices].astype(np.float32)
    X_fraud_tft  = X_fraud[:, feature_indices].astype(np.float32)

    amount_col = 0  # index de "amount" dans TFT_FEATURE_NAMES

    # ── Tri unique par montant — O(n log n) une seule fois ──
    # Permet ensuite des recherches O(log n) au lieu de O(n) par boucle
    sort_idx = np.argsort(X_normal_tft[:, amount_col])
    X_normal_sorted = X_normal_tft[sort_idx]
    amounts_sorted  = X_normal_sorted[:, amount_col]
    n_normal = len(X_normal_sorted)

    n_fraud_seq  = n_synthetic // 4   # 25% fraudes
    n_normal_seq = n_synthetic - n_fraud_seq

    sequences = np.empty((n_synthetic, seq_len, len(feature_indices)), dtype=np.float32)
    labels    = np.empty(n_synthetic, dtype=np.float32)

    # ── Séquences frauduleuses (vectorisé par lot) ────
    # Contexte = transactions normales avec montant < 30% du montant fraude
    # → simule l'historique habituel du client avant la fraude
    fraud_sample_idx = np.random.randint(0, len(X_fraud_tft), size=n_fraud_seq)
    fraud_txs        = X_fraud_tft[fraud_sample_idx]          # (n_fraud_seq, n_feat)
    fraud_amounts    = fraud_txs[:, amount_col] * 0.3          # seuil par séquence

    # Pour chaque seuil, trouve la position dans le tableau trié — vectorisé
    upper_bounds = np.searchsorted(amounts_sorted, fraud_amounts, side="right")
    # Évite les bornes à 0 (pas assez de candidats) → fallback sur tout le pool
    upper_bounds = np.maximum(upper_bounds, seq_len)

    for i in range(n_fraud_seq):
        bound = upper_bounds[i]
        # Échantillonne seq_len-1 indices dans la plage [0, bound) — O(seq_len)
        idx = np.random.randint(0, bound, size=seq_len - 1)
        context = X_normal_sorted[idx]
        sequences[i, :seq_len-1] = context
        sequences[i, seq_len-1]  = fraud_txs[i]
        labels[i] = 1.0

    # ── Séquences normales (vectorisé par lot) ────────
    # Montants similaires entre eux dans la même séquence
    ref_idx     = np.random.randint(0, n_normal, size=n_normal_seq)
    ref_amounts = amounts_sorted[ref_idx]

    lower_bounds = np.searchsorted(amounts_sorted, ref_amounts * 0.5,  side="left")
    upper_bounds2= np.searchsorted(amounts_sorted, ref_amounts * 1.5,  side="right")
    # Garantit une plage d'au moins seq_len
    range_sizes  = upper_bounds2 - lower_bounds
    too_small    = range_sizes < seq_len
    lower_bounds[too_small]  = 0
    upper_bounds2[too_small] = n_normal

    for j in range(n_normal_seq):
        lo, hi = lower_bounds[j], upper_bounds2[j]
        idx = np.random.randint(lo, hi, size=seq_len)
        sequences[n_fraud_seq + j] = X_normal_sorted[idx]
        labels[n_fraud_seq + j] = 0.0

    # Mélange
    perm = np.random.permutation(n_synthetic)
    sequences = sequences[perm]
    labels    = labels[perm]

    elapsed = time.monotonic() - t0
    logger.info(
        f"Séquences construites en {elapsed:.1f}s : {len(sequences):,} | "
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

    # Cas spécial — un seul dataset IBM AML : utilise le vrai historique
    # chronologique par compte (build_real_sequences), pas de fuite
    # structurelle. C'est le cas recommandé pour TFT (voir docstring de
    # build_sequences() pour le détail du problème évité ici).
    use_real_sequences = False
    account_ids = None
    aml_features = None

    # Toutes les features AML_FEATURE_NAMES demandées dans TFT_FEATURE_NAMES
    # (voir feature_engineering.py) — actuellement is_mule_pattern,
    # tx_velocity_ratio, amount_cumul_ratio, rapid_transfer_flag,
    # many_beneficiaries_flag. near_threshold_flag et round_amount_flag
    # sont volontairement absentes de TFT_FEATURE_NAMES pour l'entraînement
    # IBM AML (seuils MRU inadaptés — voir ibm_aml_loader.py).
    AML_FEATURE_NAMES_TRAINABLE = {
        "is_mule_pattern", "tx_velocity_ratio", "amount_cumul_ratio",
        "rapid_transfer_flag", "many_beneficiaries_flag",
    }
    requested_aml_features = [
        n for n in TFT_FEATURE_NAMES if n in AML_FEATURE_NAMES_TRAINABLE
    ]

    if len(args.datasets) == 1:
        name, path = args.datasets[0].split(":", 1)
        if name in ("ibm_aml", "ibm_aml_full"):
            if not Path(path).exists():
                raise FileNotFoundError(f"Fichier introuvable : {path}")
            loader = REGISTRY[name]
            if requested_aml_features and hasattr(loader, "load_with_aml_features"):
                X, y, account_ids, _beneficiary_ids, aml_features = (
                    loader.load_with_aml_features(path)
                )
                use_real_sequences = True
                logger.info(
                    "Dataset IBM AML détecté — utilisation du vrai "
                    "historique chronologique par compte (build_real_sequences) "
                    f"avec {len(requested_aml_features)} feature(s) AML "
                    f"calculée(s) : {requested_aml_features}"
                )
            elif hasattr(loader, "load_with_account_ids"):
                X, y, account_ids = loader.load_with_account_ids(path)
                use_real_sequences = True
                logger.info(
                    "Dataset IBM AML détecté — utilisation du vrai "
                    "historique chronologique par compte (build_real_sequences)"
                )

    if requested_aml_features and not use_real_sequences:
        # AVANT ce fix (2a), une feature TFT absente de FEATURE_NAMES était
        # silencieusement droppée ou (côté GNN) remplacée par "amount".
        # Ces features AML n'existent QUE via IBMAMLLoader.
        # load_with_aml_features() — PaySim/Aryan n'ont pas de comptes
        # bénéficiaires récurrents pour les calculer (même diagnostic que
        # le chapitre 6 de la doc technique pour TFT/GNN en général). Échec
        # explicite plutôt que d'entraîner silencieusement sur une colonne
        # absente ou incorrecte.
        raise ValueError(
            f"TFT_FEATURE_NAMES inclut des features AML {requested_aml_features} "
            f"qui ne sont calculables que via "
            f"IBMAMLLoader.load_with_aml_features() — entraîne avec un seul "
            f"dataset IBM AML (--datasets ibm_aml:chemin/vers/"
            f"HI-Small_Trans.csv), pas en mode mixte ni avec PaySim/Aryan seuls."
        )

    if not use_real_sequences:
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
            "Construction par contraste de montant (build_sequences) — "
            "utilisée car plusieurs datasets sont mélangés, ou parce que "
            "le dataset n'a pas de vrais comptes récurrents (PaySim/Aryan). "
            "Cette méthode a un biais structurel connu (voir docstring) — "
            "ses métriques ne doivent pas être comparées directement à "
            "celles obtenues avec build_real_sequences()."
        )

    logger.info(
        f"Dataset : {len(y):,} lignes | "
        f"fraudes : {y.sum():,} ({y.mean()*100:.3f}%)"
    )

    # ── Étape 2 : Indices des features TFT ────
    from infrastructure.ml.models.xgboost_model import FEATURE_NAMES
    # Les features AML demandées ne sont PAS dans FEATURE_NAMES (les 22
    # colonnes des loaders) — chacune est collée comme colonne
    # supplémentaire à X, DANS L'ORDRE de requested_aml_features (qui suit
    # lui-même l'ordre de TFT_FEATURE_NAMES), puis feature_indices est
    # construit dans l'ORDRE EXACT de TFT_FEATURE_NAMES — cet ordre doit
    # être identique à celui utilisé côté inférence par
    # _extract_tft_features() (tft_model.py), qui lit aussi dans l'ordre
    # de TFT_FEATURE_NAMES. Un désordre ici ferait apprendre au modèle une
    # correspondance différente de celle utilisée
    # en production, silencieusement.
    base_feature_names = [
        name for name in TFT_FEATURE_NAMES
        if name not in AML_FEATURE_NAMES_TRAINABLE
    ]
    missing_tft_features = [
        name for name in base_feature_names if name not in FEATURE_NAMES
    ]
    if missing_tft_features:
        raise ValueError(
            f"Feature(s) TFT absente(s) de FEATURE_NAMES (les 22 "
            f"colonnes produites par les loaders d'entraînement) : "
            f"{missing_tft_features}. Un loader doit d'abord être "
            f"étendu pour produire ces colonnes avant de les ajouter "
            f"à TFT_FEATURE_NAMES — voir base_loader.py."
        )

    if requested_aml_features:
        # CORRECTIF MÉMOIRE — l'ancienne version faisait
        # X = np.hstack([X, extra_columns]), construisant un tableau
        # intermédiaire à TOUTES les colonnes de X (22) + les 5 AML
        # (27 au total), pour ensuite n'en extraire QUE les 14
        # nécessaires à TFT_FEATURE_NAMES dans build_real_sequences().
        # Sur HI-Medium (31,9M lignes), ce détour coûtait un pic mémoire
        # d'environ 6,9 Go (ancien X 2,8 Go + extra_columns 0,64 Go +
        # nouveau tableau à 27 colonnes 3,44 Go, coexistant pendant le
        # hstack) — pour un résultat dont plus de la moitié des colonnes
        # n'était jamais utilisée. A contribué au plantage mémoire
        # Kaggle observé sur ce dataset.
        #
        # Construit directement le tableau final à len(TFT_FEATURE_NAMES)
        # colonnes (14, pas 27) — chaque colonne piochée une seule fois,
        # à sa bonne source (X pour les features de base, aml_features
        # pour les 5 AML). feature_indices devient un simple range()
        # puisque ce tableau a déjà exactement les bonnes colonnes, dans
        # le bon ordre — plus besoin de mapper vers des positions dans
        # un tableau étendu.
        n_rows = X.shape[0]
        X_direct = np.empty((n_rows, len(TFT_FEATURE_NAMES)), dtype=np.float32)
        for i, name in enumerate(TFT_FEATURE_NAMES):
            if name in AML_FEATURE_NAMES_TRAINABLE:
                X_direct[:, i] = aml_features[name]
            else:
                X_direct[:, i] = X[:, FEATURE_NAMES.index(name)]
        X = X_direct
        feature_indices = list(range(len(TFT_FEATURE_NAMES)))
    else:
        feature_indices = [
            FEATURE_NAMES.index(name) for name in TFT_FEATURE_NAMES
        ]
    logger.info(f"Features TFT : {TFT_FEATURE_NAMES}")

    # ── Étape 3 : Construire les séquences ────
    logger.info("Étape 2/4 — Construction des séquences temporelles")
    if use_real_sequences:
        if args.min_history is not None:
            logger.info(
                f"min_history explicitement fixé à {args.min_history} "
                f"(défaut sinon : SEQUENCE_LENGTH={SEQUENCE_LENGTH})"
            )
        sequences, labels = build_real_sequences(
            X, y, account_ids,
            feature_indices=feature_indices,
            seq_len=SEQUENCE_LENGTH,
            min_history=args.min_history,
            max_sequences=args.max_sequences,
        )
    else:
        sequences, labels = build_sequences(
            X, y,
            feature_indices=feature_indices,
            seq_len=SEQUENCE_LENGTH,
            n_synthetic=args.n_sequences,
        )

    # ── Étape 4 : Entraînement ────────────────
    logger.info("Étape 3/4 — Entraînement TFT")
    model = TFTModel(version=args.version)
    metrics, pr_curve_data = model.train(
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

    # Sauvegarde la courbe précision/rappel complète à côté du .pkl —
    # permet de choisir un seuil de décision a posteriori (ex: si 0.9
    # n'est pas le meilleur compromis pour votre cas d'usage) SANS
    # ré-entraîner, juste en rechargeant ce fichier.
    import json
    pr_curve_path = models_dir / f"tft_v{args.version}_pr_curve.json"
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
        description="HarisAI — Entraînement TFT"
    )
    p.add_argument(
        "--datasets", nargs="+",
        default=["creditcard:training/data/creditcard.csv"],
    )
    p.add_argument("--version",       default="1.0.0")
    p.add_argument("--epochs",        type=int,   default=50)
    p.add_argument("--learning-rate", type=float, default=0.005)  # augmenté 0.001→0.005
    p.add_argument("--batch-size",    type=int,   default=512)    # augmenté 256→512
    p.add_argument(
        "--n-sequences",
        type=int,
        default=50_000,
        help="Nombre de séquences synthétiques à générer (défaut: 50000)"
    )
    p.add_argument(
        "--min-history",
        type=int,
        default=None,
        help=(
            "Nombre minimum de transactions par compte pour qu'il soit "
            "éligible (build_real_sequences, dataset IBM AML uniquement). "
            "Défaut: SEQUENCE_LENGTH (10). ATTENTION — une valeur EN "
            "DESSOUS de SEQUENCE_LENGTH n'a AUCUN EFFET pour récupérer "
            "des fraudes sur compte neuf : la boucle de construction des "
            "séquences démarre toujours à la position seq_len-1, "
            "indépendamment de min_history (testé et confirmé — voir "
            "conversation du 09/07/2026). Un compte a besoin d'au moins "
            "seq_len transactions pour produire ne serait-ce qu'UNE "
            "séquence, quelle que soit la valeur de min_history. Ce "
            "paramètre n'est utile que pour exiger PLUS d'historique que "
            "seq_len (valeur > 10), pas moins — pour recréer l'effet "
            "initialement recherché (récupérer la fraude sur compte "
            "neuf), il faudrait réduire SEQUENCE_LENGTH lui-même (dans "
            "tft_model.py — impacte aussi l'inférence, changement plus "
            "structurant, non fait à ce jour)."
        ),
    )
    p.add_argument(
        "--max-sequences",
        type=int,
        default=2_000_000,
        help=(
            "Plafond du nombre de séquences réelles matérialisées "
            "(build_real_sequences, dataset IBM AML uniquement). Toutes "
            "les séquences de fraude sont gardées ; les séquences "
            "normales sont sous-échantillonnées pour atteindre ce total. "
            "Défaut: 2 000 000 (~1,1 Go en float32 pour seq_len=10 × "
            "14 features — marge de sécurité sous les 15-16 Go de VRAM "
            "d'un Tesla T4 Kaggle, en laissant de la place pour le "
            "modèle/gradients/batchs). HI-Small (3,3M séquences "
            "éligibles) passait déjà sans souci ; HI-Medium (~20M "
            "séquences éligibles estimées) a fait planter Kaggle par "
            "manque de mémoire avant ce plafond (\"tried to allocate "
            "more memory than is available\"). Mets à None (ou une "
            "valeur > nombre réel de séquences) pour désactiver le "
            "plafond si tu as confirmé assez de mémoire disponible."
        ),
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)