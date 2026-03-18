# ImmoApp — Estimation de prix immobilier belge

API de prédiction de prix et de loyers pour l'immobilier belge, intégrée avec Odoo SaaS via des scripts batch sur VPS OVH.

| Modèle | R² | MAE | Données |
|--------|----|-----|---------|
| Vente | 0.8203 | €66 892 | 92 544 annonces · 25 variables |
| Location | 0.8124 | €230/mois | 9 921 annonces · 24 variables |

---

## Architecture

```
Odoo SaaS (cloud)              VPS OVH
        |                          |
        |   XML-RPC API    +-------+--------------------+
        |<---------------->|  batch.py      (vente)    |
        |                  |  batch_rent.py (location) |
        |                  |  cron : toutes les 3 j.   |
        |                  |                           |
        |                  |  Flask API  :5000         |
        +------------------+  Nginx      :80           |
                           +---------------------------+
```

- **Odoo SaaS** : application Studio, champ `x_transaction_type` (vente/location), résultat écrit dans `x_predicted_price` ou `x_predicted_rent`
- **VPS OVH** : héberge l'API Flask + les scripts batch
- **Flux batch** : OVH récupère les fiches Odoo via XML-RPC → appelle `/predict` ou `/predict-rent` → réécrit le résultat

---

## Structure du projet

```
immo-prediction/
├── immo_api/
│   ├── app.py              # API Flask — /predict, /predict-rent, /health, /features
│   ├── predictor.py        # Chargement des modèles, logique de prédiction
│   ├── requirements.txt
│   └── models/
│       ├── model.pkl                  # Modèle vente (non versionné — SCP)
│       ├── model_metadata.json
│       ├── rental_model.pkl           # Modèle location (non versionné — SCP)
│       └── rental_model_metadata.json
├── odoo_batch/
│   ├── batch.py            # Batch XML-RPC vente (OVH → Odoo → /predict)
│   ├── batch_rent.py       # Batch XML-RPC location (OVH → Odoo → /predict-rent)
│   ├── .env.example        # Template des variables d'environnement
│   └── requirements.txt
├── notebooks/
│   ├── 01_eda_cleaning.ipynb      # Nettoyage des données
│   └── 03_rental_model.ipynb      # Entraînement modèle location
├── data/
│   └── fetch_statbel.py    # Téléchargement données Statbel
├── streamlit_app.py        # Interface de test (2 onglets : vente + location)
├── GUIDE_VPS.md            # Guide de mise en production (Philippe)
└── README.md
```

---

## Installation

### 1. API Flask (VPS OVH)

```bash
git clone https://github.com/dominys-be/immo-prediction.git
cd immo-prediction

python -m venv venv
source venv/bin/activate
pip install -r immo_api/requirements.txt

# Copier les modèles (depuis le PC de développement)
# scp immo_api/models/model.pkl immo@[IP_VPS]:~/immo-prediction/immo_api/models/
# scp immo_api/models/rental_model.pkl immo@[IP_VPS]:~/immo-prediction/immo_api/models/

# Lancer en production (Gunicorn)
gunicorn -w 2 -b 0.0.0.0:5000 "immo_api.app:app"
```

Tester l'API :

```bash
curl http://localhost:5000/health
curl http://localhost:5000/health-rent

curl -X POST http://localhost:5000/predict \
  -H "Content-Type: application/json" \
  -d '{"living_area": 120, "bedroom_count": 3, "room_count": 5,
       "number_of_facades": 2, "postal_code": 9000, "region": "Flanders"}'

curl -X POST http://localhost:5000/predict-rent \
  -H "Content-Type: application/json" \
  -d '{"living_area": 80, "bedroom_count": 2, "room_count": 3,
       "number_of_facades": 1, "postal_code": 1000, "region": "Brussels"}'
```

### 2. Scripts batch Odoo (VPS OVH)

```bash
cd odoo_batch
cp .env.example .env
nano .env   # Remplir les identifiants Odoo + URL de l'API

pip install -r requirements.txt

# Test manuel (sans écriture dans Odoo)
python batch.py --dry-run
python batch_rent.py --dry-run

# Exécution normale
python batch.py
python batch_rent.py
```

Configurer le cron (toutes les 3 jours) :

```bash
crontab -e
0 0 */3 * * cd /home/immo/immo-prediction && /home/immo/immo-prediction/venv/bin/python odoo_batch/batch.py >> logs/batch.log 2>&1
0 0 */3 * * cd /home/immo/immo-prediction && /home/immo/immo-prediction/venv/bin/python odoo_batch/batch_rent.py >> logs/batch_rent.log 2>&1
```

### 3. Interface Streamlit (test local)

```bash
pip install streamlit geopy
streamlit run streamlit_app.py
```

---

## Endpoint `/predict` — Vente

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

### Multiplicateurs PEB et Avis (vente uniquement)

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

## Endpoint `/predict-rent` — Location

**POST** `http://votre-vps:5000/predict-rent`

| Champ | Type | Exemple |
|-------|------|---------|
| `living_area` | float | `80` |
| `bedroom_count` | int | `2` |
| `room_count` | int | `3` |
| `number_of_facades` | int | `1` |
| `postal_code` | int | `1000` |
| `region` | string | `"Brussels"` |
| `commune` | string | `"Ixelles"` |
| `street` | string | `"Rue de la Loi"` |
| `furnished` | boolean | `true` / `false` |
| `type_of_property` | string | `"APARTMENT"` |
| `state_of_building` | string | `"GOOD"` |

Réponse :

```json
{
  "predicted_rent": 1150.00,
  "currency": "EUR",
  "unit": "per month"
}
```

> PEB et Avis ne s'appliquent **pas** aux estimations de loyer.

---

## Champs Odoo Studio

| Champ Odoo | Variable API | Modèle |
|------------|--------------|--------|
| `x_transaction_type` | — | `vente` ou `location` (routage automatique) |
| `x_living_area` | `living_area` | vente + location |
| `x_bedroom_count` | `bedroom_count` | vente + location |
| `x_room_count` | `room_count` | vente + location |
| `x_facades` | `number_of_facades` | vente + location |
| `x_street` | `street` | vente + location |
| `x_commune` | `commune` | vente + location |
| `x_postal_code` | `postal_code` | vente + location |
| `x_region` | `region` | vente + location |
| `x_state_of_building` | `state_of_building` | vente + location |
| `x_type_of_property` | `type_of_property` | vente + location |
| `x_peb` | `peb` | vente uniquement |
| `x_avis` | `avis` | vente uniquement |
| `x_furnished` | `furnished` | location uniquement |
| `x_predicted_price` | ← résultat vente | écrit par batch.py |
| `x_predicted_rent` | ← résultat location | écrit par batch_rent.py |

---

## Données Statbel

Deux variables géographiques enrichissent le modèle :

- **MedianIncome** : revenu net imposable médian par commune ([statbel.fgov.be](https://statbel.fgov.be), CC BY 4.0)
- **PopulationDensity** : densité de population par commune en hab./km² ([statbel.fgov.be](https://statbel.fgov.be), CC BY 4.0)

```bash
python data/fetch_statbel.py
# → data/statbel_features.csv (1149 codes postaux)
```

---

## Licence

Les données Statbel sont publiées sous licence **Creative Commons CC BY 4.0** — utilisation commerciale autorisée avec attribution.

Le code source est la propriété de Dominys BV.
