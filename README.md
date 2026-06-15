# HarisAI
# HarisAI — Datasets d'entraînement

Ces fichiers ne sont PAS sur GitHub (voir .gitignore).

## Datasets requis

### 1. creditcard.csv
- Source : https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
- Taille  : ~147 MB · 284 807 lignes · 492 fraudes
- Colonnes: Time · V1-V28 · Amount · Class

### 2. pysim.csv
- Source : https://www.kaggle.com/datasets/ealaxi/paysim1
- Taille  : ~482 MB · 6 362 620 lignes · 8 213 fraudes
- Colonnes: step · type · amount · nameOrig · oldbalanceOrg ·
            newbalanceOrig · nameDest · oldbalanceDest ·
            newbalanceDest · isFraud · isFlaggedFraud

## Téléchargement

```bash
pip install kaggle

# Creditcard
kaggle datasets download -d mlg-ulb/creditcardfraud
unzip creditcardfraud.zip -d training/data/

# PaySim
kaggle datasets download -d ealaxi/paysim1
unzip paysim1.zip -d training/data/
mv training/data/PS_*.csv training/data/pysim.csv
```

## Entraînement

```bash
python training/train_xgboost.py \
    --datasets creditcard:training/data/creditcard.csv \
               pysim:training/data/pysim.csv \
    --version 1.0.0
```