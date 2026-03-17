# ImmoApp — Estimation de prix immobilier belge

API de prédiction de prix pour l'immobilier belge, intégrée avec Odoo SaaS via un script batch sur VPS OVH.

**Métriques du modèle :** R² = 0.8203 · MAE = €66 892 · 92 544 annonces · 25 variables

---

## Architecture

```
Odoo SaaS (cloud)              VPS OVH
        |                          |
        |   XML-RPC API    +-------+--------------------+
        |<---------------->|  batch.py (cron toutes    |
        |                  |  les 5 min)               |
        |                  |                           |
        |                  |  Flask API  :5000         |
        +------------------+  Nginx      :80           |
                           +---------------------------+
```

- **Odoo SaaS** : application Studio, champ `x_predicted_price` mis à jour automatiquement
- **VPS OVH** : héberge l'API Flask + le script batch
- **Flux batch** : OVH récupère les fiches Odoo via XML-RPC → appelle `/predict` → réécrit le prix estimé

---

## Structure du projet

```
immo-prediction/
├── immo_api/
│   ├── app.py              # API Flask (endpoints /predict /health /features)
│   ├── predictor.py        # Chargement du modèle, logique de prédiction
│   ├── requirements.txt    # Dépendances Python de l'API
│   └── models/
│       ├── model.pkl       # Modèle entraîné (RandomForest)
│       └── model_metadata.json
├── odoo_batch/
│   ├── batch.py            # Script batch XML-RPC (OVH → Odoo)
│   ├── .env.example        # Template des variables d'environnement
│   └── requirements.txt    # Dépendances du script batch
├── notebooks/
│   └── 01_eda_cleaning.ipynb  # Nettoyage des données + entraînement
├── data/
│   └── fetch_statbel.py    # Téléchargement données Statbel (revenus, densité)
├── streamlit_app.py        # Interface de test interactive (Streamlit)
└── README.md
```

---

## Installation

### 1. API Flask (VPS OVH)

```bash
git clone https://github.com/dominys-be/immo-prediction.git
cd immo-prediction

python -m venv venv
source venv/bin/activate      # Windows : venv\Scripts\activate
pip install -r immo_api/requirements.txt

# Lancer en développement
python immo_api/app.py

# Lancer en production (Gunicorn)
gunicorn -w 2 -b 0.0.0.0:5000 "immo_api.app:app"
```

Tester l'API :

```bash
curl http://localhost:5000/health

curl -X POST http://localhost:5000/predict \
  -H "Content-Type: application/json" \
  -d '{"living_area": 120, "bedroom_count": 3, "room_count": 5,
       "number_of_facades": 2, "postal_code": 9000, "region": "Flanders"}'
```

### 2. Script batch Odoo (VPS OVH)

```bash
cd odoo_batch
cp .env.example .env
nano .env          # Remplir les identifiants Odoo

pip install -r requirements.txt

# Test manuel (sans écriture)
python batch.py --dry-run

# Exécution normale
python batch.py
```

Configurer le cron (toutes les 5 minutes) :

```bash
crontab -e
*/5 * * * * cd /home/immo/immo-prediction && python odoo_batch/batch.py >> logs/batch.log 2>&1
```

### 3. Interface Streamlit (optionnel, test local)

```bash
pip install streamlit geopy
streamlit run streamlit_app.py
```

---

## Endpoint `/predict`

**POST** `http://votre-vps:5000/predict`

Champs obligatoires :

| Champ | Type | Description |
|-------|------|-------------|
| `room_count` | int | Nombre de pièces total |
| `living_area` | float | Surface habitable (m²) |
| `number_of_facades` | int | Nombre de façades (1–4) |
| `bedroom_count` | int | Nombre de chambres |

Champs optionnels (améliorent la précision) :

| Champ | Type | Exemple |
|-------|------|---------|
| `postal_code` | int | `9000` |
| `region` | string | `"Flanders"`, `"Wallonia"`, `"Brussels"` |
| `commune` | string | `"Gent"`, `"Liège"` |
| `street` | string | `"Kortrijksesteenweg"` (géocodage OpenStreetMap) |
| `house_number` | string | `"48"` |
| `type_of_property` | string | `"HOUSE"`, `"APARTMENT"`, `"VILLA"`, `"STUDIO"` |
| `state_of_building` | string | `"GOOD"`, `"NEW"`, `"FAIR"`, `"POOR"`, `"NEEDS_RENOVATION"` |
| `peb` | string | `"A"` à `"G"` (multiplicateur post-prédiction) |
| `avis` | string | `"A"` à `"G"` (multiplicateur post-prédiction) |

Réponse :

```json
{
  "predicted_price": 285000.00,
  "currency": "EUR"
}
```

### Multiplicateurs PEB et Avis

Ces scores sont appliqués **après** la prédiction du modèle :

| Classe | PEB | Avis |
|--------|-----|------|
| A | +4.5% | +7.5% |
| B | +3.5% | +5.0% |
| C | +1.75% | +2.5% |
| D | 0% | 0% |
| E | -1.75% | -2.5% |
| F | -3.5% | -5.0% |
| G | -4.5% | -7.5% |

---

## Champs Odoo Studio

Le script batch lit et écrit ces champs techniques :

| Champ Odoo | Variable `/predict` |
|------------|---------------------|
| `x_living_area` | `living_area` |
| `x_bedroom_count` | `bedroom_count` |
| `x_room_count` | `room_count` |
| `x_facades` | `number_of_facades` |
| `x_peb` | `peb` |
| `x_avis` | `avis` |
| `x_commune` | `commune` |
| `x_state_of_building` | `state_of_building` |
| `x_type_of_property` | `type_of_property` |
| `x_predicted_price` | ← résultat écrit ici |

> **Vérifier le nom du modèle Odoo :** Paramètres → Technique → Modèles → rechercher "immobilier" → copier le nom technique dans `ODOO_MODEL` du fichier `.env`.

---

## Données Statbel

Deux variables géographiques enrichissent le modèle :

- **MedianIncome** : revenu net imposable médian par commune (source : [statbel.fgov.be](https://statbel.fgov.be), CC BY 4.0)
- **PopulationDensity** : densité de population par commune en hab./km² (source : [statbel.fgov.be](https://statbel.fgov.be), CC BY 4.0)

Pour régénérer ces données :

```bash
python data/fetch_statbel.py
# → data/statbel_features.csv (1149 codes postaux)
```

---

## Licence des données

Les données Statbel utilisées pour l'entraînement sont publiées sous licence **Creative Commons CC BY 4.0** — utilisation commerciale autorisée avec attribution.

Le code source de ce dépôt est la propriété de Dominys BV.
