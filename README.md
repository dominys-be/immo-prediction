# ImmoApp — Estimation de prix immobilier belge

API de prédiction de prix et de loyers pour l'immobilier belge, intégrée avec Odoo SaaS 19.2 via webhook et scripts batch sur VPS OVH Windows Server.

| Modèle | R² | MAE | Données |
|--------|----|-----|---------|
| Vente résidentielle | 0.8203 | €66 892 | 92 544 annonces · 25 variables |
| Location résidentielle | 0.8124 | €230/mois | 9 921 annonces · 24 variables |
| Vente commerciale | Après entraînement | Après entraînement | Annonces Immoweb commercial · 18 variables |
| Location commerciale | Après entraînement | Après entraînement | Annonces Immoweb commercial · 18 variables |

---

## Architecture

```
Odoo SaaS (cloud)                    VPS OVH — Windows Server
        |                                        |
        |   Webhook (création fiche)    +--------+---------------------+
        |-----------------------------→ | Flask API  :8080             |
        |   XML-RPC (écriture résultat) |  /predict                    |
        |←------------------------------ |  /predict-rent               |
        |                               |  /odoo-webhook               |
        |   XML-RPC (batch)             |  /health                     |
        |←-----------------------------→|                              |
        |                               |  batch.py      (vente)       |
        |                               |  batch_rent.py (location)    |
        |                               |  Planificateur : tous les 3j |
        |                               |  NSSM service (Waitress)     |
        +                               +------------------------------+
```

**Flux webhook (instantané) :**
1. Nouvelle fiche Odoo créée → automated action envoie un POST au VPS
2. Flask prédit le prix → écrit le résultat via XML-RPC dans Odoo

**Flux batch (toutes les 3 jours) :**
- `batch.py` et `batch_rent.py` récupèrent toutes les fiches Odoo → recalculent les estimations

---

## Structure du projet

```
immo-prediction/
├── immo_api/
│   ├── app.py              # API Flask — /predict, /predict-rent, /odoo-webhook, /health
│   ├── predictor.py        # Chargement des modèles, logique de prédiction
│   ├── requirements.txt
│   ├── .env                # Credentials Odoo (non versionné)
│   └── models/
│       ├── model.pkl                  # Modèle vente (~1 Go, non versionné)
│       ├── model_metadata.json
│       ├── rental_model.pkl           # Modèle location (non versionné)
│       └── rental_model_metadata.json
├── odoo_batch/
│   ├── batch.py            # Batch XML-RPC vente
│   ├── batch_rent.py       # Batch XML-RPC location
│   ├── .env                # Credentials Odoo (non versionné)
│   ├── .env.example        # Template des variables d'environnement
│   └── requirements.txt
├── notebooks/
│   ├── 01_eda_cleaning.ipynb
│   ├── 03_rental_model.ipynb
│   └── 04_commercial_model.ipynb  # Entraînement modèles commerciaux
├── data/
│   ├── fetch_statbel.py
│   └── scrape_commercial.py       # Collecte données Immoweb commercial
├── streamlit_app.py
├── GUIDE_VPS.md                   # Guide de mise en production Windows Server
├── ODOO_COMMERCIAL_SETUP.md       # Guide Studio — configuration biens commerciaux
└── README.md
```

---

## Déploiement — VPS OVH Windows Server

### Prérequis
- Python 3.11+
- NSSM (Non-Sucking Service Manager)
- Modèles `.pkl` transférés via Google Drive + gdown

### 1. Installation

```powershell
git clone https://github.com/dominys-be/immo-prediction.git
cd immo-prediction

python -m venv venv
venv\Scripts\activate
pip install -r immo_api\requirements.txt
pip install pip-system-certs   # Fix SSL sur Windows Server
```

### 2. Variables d'environnement

Créer `immo_api\.env` :
```
ODOO_URL=https://votre-societe.odoo.com
ODOO_DB=nom-de-la-base
ODOO_USER=email@exemple.com
ODOO_APIKEY=cle-api-odoo
ODOO_MODEL=x_estimation
```

Créer `odoo_batch\.env` (même contenu + URL API) :
```
ODOO_URL=https://votre-societe.odoo.com
ODOO_DB=nom-de-la-base
ODOO_USER=email@exemple.com
ODOO_APIKEY=cle-api-odoo
ODOO_MODEL=x_estimation
API_URL=http://localhost:8080/predict
```

### 3. Service Windows (NSSM)

```powershell
nssm install ImmoApp "C:\...\venv\Scripts\python.exe"
nssm set ImmoApp AppParameters "-m waitress --host=0.0.0.0 --port=8080 app:app"
nssm set ImmoApp AppDirectory "C:\...\immo_api"
nssm set ImmoApp AppStdout "C:\...\logs\access.log"
nssm set ImmoApp AppStderr "C:\...\logs\error.log"
nssm start ImmoApp
```

### 4. Firewall Windows

```powershell
New-NetFirewallRule -DisplayName "Flask API 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
```

### 5. Planificateur de tâches (batch — tous les 3 jours)

Via Planificateur de tâches Windows :
- Programme : `C:\...\venv\Scripts\python.exe`
- Arguments : `C:\...\odoo_batch\batch.py`
- Déclencheur : tous les 3 jours à 02h00

---

## Configuration Odoo Studio

### Modèle : `x_estimation`

**Action automatisée — Webhook instantané :**
- Déclencheur : **À la création**
- Type : Envoyer une notification webhook
- URL : `http://[IP_VPS]:8080/odoo-webhook`
- Champs : tous les champs `x_studio_x_*` + `id`

### Champs Odoo Studio

| Champ Odoo (technique) | Variable API | Modèle |
|------------------------|--------------|--------|
| `x_studio_x_transaction_type` | — | routage vente / location |
| `x_studio_x_living_area` | `living_area` | vente + location |
| `x_studio_x_bedroom_count` | `bedroom_count` | vente + location |
| `x_studio_x_room_count` | `room_count` | vente + location |
| `x_studio_x_facades` | `number_of_facades` | vente + location |
| `x_studio_x_street` | `street` | vente + location |
| `x_studio_x_commune` | `commune` | vente + location |
| `x_studio_x_postal_code` | `postal_code` | vente + location |
| `x_studio_x_region` | `region` | vente + location |
| `x_studio_x_state_of_building` | `state_of_building` | vente + location |
| `x_studio_x_type_of_property` | `type_of_property` | vente + location |
| `x_studio_x_construction_year` | `construction_year` | vente + location |
| `x_studio_x_heating_type` | `heating_type` | vente + location |
| `x_studio_x_garage` | `garage` | vente + location |
| `x_studio_x_garden` | `garden` | vente + location |
| `x_studio_x_garden_area` | `garden_area` | vente + location |
| `x_studio_x_swimming_pool` | `swimming_pool` | vente + location |
| `x_studio_x_terrace` | `terrace` | vente + location |
| `x_studio_x_fireplace` | `fireplace` | vente + location |
| `x_studio_x_lift` | `lift` | vente + location |
| `x_studio_x_solar_panels` | `has_solar_panels` | vente + location |
| `x_studio_x_peb` | `peb` | vente uniquement |
| `x_studio_x_avis` | `avis` | vente uniquement |
| `x_studio_x_predicted_price` | ← résultat vente | écrit par webhook + batch |
| `x_studio_x_predicted_rent` | ← résultat location | écrit par webhook + batch |

> **Note :** Odoo Studio ajoute automatiquement le préfixe `x_studio_` à tous les champs personnalisés, d'où le double préfixe `x_studio_x_`.

---

## Endpoints API

### `GET /health`
```json
{
  "status": "ok",
  "model_name": "RandomForest",
  "r2": 0.8203,
  "mae": 66891.73,
  "feature_count": 25,
  "version": "2.0"
}
```

### `POST /predict` — Vente

Champs obligatoires : `room_count`, `living_area`, `number_of_facades`, `bedroom_count`

Champs optionnels : `postal_code`, `region`, `commune`, `street`, `type_of_property`, `state_of_building`, `peb`, `avis`, `construction_year`, `heating_type`, `garage`, `garden`, `swimming_pool`, `terrace`, `fireplace`, `lift`, `has_solar_panels`

```json
{ "predicted_price": 285000.00, "currency": "EUR" }
```

### `POST /predict-rent` — Location

Champs : mêmes que `/predict` (sans `peb` ni `avis`)

```json
{ "predicted_rent": 1150.00, "currency": "EUR", "unit": "per month" }
```

### `POST /predict-commercial` — Vente ou Location commerciale

Champs obligatoires : `commercial_type`, `surface_totale`, `transaction_type`

`commercial_type` : `Commerce` / `Bureau` / `Entrepôt` / `Industrie` / `Horeca`

`transaction_type` : `Ticari-Satış` (vente) ou `Ticari-Kira` (location)

Champs optionnels : `region`, `postal_code`, `commune`, `construction_year`, `state_of_building`, `peb`, `heating_type`, `has_parking`, `has_lift`, `floor_count`, `hauteur_plafond`, `quai_chargement`, `vitrine`

```json
// Vente
{ "predicted_price_commercial": 450000.00, "currency": "EUR" }
// Location
{ "predicted_rent_commercial": 2800.00, "currency": "EUR", "unit": "per month" }
```

### `GET /health-commercial`
```json
{ "status": "ok", "sale_model": {"r2": 0.xx, "mae": xx}, "rental_model": {...} }
```

### `POST /odoo-webhook`

Reçoit le payload Odoo → prédit → écrit le résultat via XML-RPC dans Odoo.

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

## Données Statbel

- **MedianIncome** : revenu net imposable médian par commune ([statbel.fgov.be](https://statbel.fgov.be), CC BY 4.0)
- **PopulationDensity** : densité de population par commune en hab./km²

```bash
python data/fetch_statbel.py
# → data/statbel_features.csv (1149 codes postaux)
```

---

## Licence

Les données Statbel sont publiées sous licence **Creative Commons CC BY 4.0**.

Le code source est la propriété de Dominys BV.
