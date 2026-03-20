# ImmoApp — Estimation de prix immobilier belge

API de prédiction de prix et de loyers pour l'immobilier belge (résidentiel et commercial), intégrée avec Odoo SaaS 19.2 via webhook et scripts batch sur VPS OVH Windows Server.

| Modèle | R² | MAE | Données |
|--------|----|-----|---------|
| Vente résidentielle | 0.8203 | €66 892 | 92 544 annonces · 25 variables |
| Location résidentielle | 0.8124 | €230/mois | 9 921 annonces · 24 variables |
| Vente commerciale | 0.69 | €165 207 | 1 302 annonces · 18 variables |
| Location commerciale | 0.54 | €1 320/mois | 429 annonces · 18 variables |

---

## Architecture

```
Odoo SaaS (cloud)                    VPS OVH — Windows Server
        |                                        |
        |   Webhook (création fiche)    +--------+------------------------------+
        |-----------------------------→ | Flask API  :8080                     |
        |   XML-RPC (écriture résultat) |  /predict              (rés. vente)  |
        |←------------------------------ |  /predict-rent         (rés. loc.)   |
        |                               |  /predict-commercial   (com. vente/loc.) |
        |   XML-RPC (batch)             |  /odoo-webhook                       |
        |←-----------------------------→|  /health  /health-rent  /health-commercial |
        |                               |                                      |
        |                               |  batch.py              (rés. vente)  |
        |                               |  batch_rent.py         (rés. loc.)   |
        |                               |  batch_commercial.py   (com.)        |
        |                               |  Planificateur : tous les 3j à 02-03h |
        |                               |  NSSM service (Waitress)             |
        +                               +--------------------------------------+
```

**Flux webhook (instantané) :**
1. Nouvelle fiche Odoo créée → automated action envoie un POST au VPS
2. Flask détecte le type de bien (`bien_type`) et le type de transaction → route vers le bon modèle
3. Résultat écrit via XML-RPC dans le champ Odoo correspondant

**Flux batch (toutes les 3 jours) :**
- `batch.py`, `batch_rent.py`, `batch_commercial.py` récupèrent les fiches sans estimation → recalculent

---

## Structure du projet

```
immo-prediction/
├── immo_api/
│   ├── app.py              # API Flask — tous les endpoints
│   ├── predictor.py        # Chargement des modèles, logique de prédiction
│   ├── requirements.txt
│   ├── .env                # Credentials Odoo (non versionné)
│   ├── models/
│   │   ├── model.pkl                        # Modèle rés. vente (~1 Go, non versionné)
│   │   ├── model_metadata.json
│   │   ├── rental_model.pkl                 # Modèle rés. location (non versionné)
│   │   ├── rental_model_metadata.json
│   │   ├── commercial_sale_model.pkl        # Modèle com. vente (non versionné)
│   │   ├── commercial_sale_metadata.json
│   │   ├── commercial_rent_model.pkl        # Modèle com. location (non versionné)
│   │   └── commercial_rent_metadata.json
│   └── report/
│       └── estimation_report.xml            # Template QWeb — rapport PDF (4 combinaisons)
├── odoo_batch/
│   ├── batch.py                # Batch XML-RPC rés. vente
│   ├── batch_rent.py           # Batch XML-RPC rés. location
│   ├── batch_commercial.py     # Batch XML-RPC com. vente + location
│   ├── .env                    # Credentials Odoo (non versionné)
│   ├── .env.example            # Template des variables d'environnement
│   └── requirements.txt
├── notebooks/
│   ├── 01_eda_cleaning.ipynb
│   ├── 03_rental_model.ipynb
│   └── 04_commercial_model.ipynb   # Entraînement modèles commerciaux
├── data/
│   ├── fetch_statbel.py
│   └── scrape_commercial.py        # Collecte données Immoweb commercial
├── streamlit_app.py
├── GUIDE_VPS.md                    # Guide de mise en production Windows Server
├── ODOO_COMMERCIAL_SETUP.md        # Guide Studio — configuration biens commerciaux
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

```powershell
# Résidentiel vente — 02h00
$t1 = New-ScheduledTaskTrigger -Daily -At "02:00"
$a1 = New-ScheduledTaskAction -Execute "C:\...\venv\Scripts\python.exe" -Argument "C:\...\odoo_batch\batch.py"
Register-ScheduledTask -TaskName "ImmoApp_Batch_Vente" -Trigger $t1 -Action $a1 -RunLevel Highest

# Résidentiel location — 02h30
$t2 = New-ScheduledTaskTrigger -Daily -At "02:30"
$a2 = New-ScheduledTaskAction -Execute "C:\...\venv\Scripts\python.exe" -Argument "C:\...\odoo_batch\batch_rent.py"
Register-ScheduledTask -TaskName "ImmoApp_Batch_Location" -Trigger $t2 -Action $a2 -RunLevel Highest

# Commercial — 03h00
$t3 = New-ScheduledTaskTrigger -Daily -At "03:00"
$a3 = New-ScheduledTaskAction -Execute "C:\...\venv\Scripts\python.exe" -Argument "C:\...\odoo_batch\batch_commercial.py"
Register-ScheduledTask -TaskName "ImmoApp_Batch_Commercial" -Trigger $t3 -Action $a3 -RunLevel Highest
```

Pour limiter à tous les 3 jours, configurer la répétition via l'interface graphique du Planificateur de tâches (onglet Déclencheurs → Répéter toutes les 3 jours).

---

## Configuration Odoo Studio

### Modèle : `x_estimation`

**Action automatisée — Webhook instantané :**
- Déclencheur : **À la création**
- Type : Envoyer une notification webhook
- URL : `http://[IP_VPS]:8080/odoo-webhook`
- Champs : tous les champs `x_studio_x_*` + `x_studio_x_bien_type` + champs commerciaux + `id`

### Routing — 4 combinaisons

| `x_studio_x_bien_type` | `x_studio_x_transaction_type` | Modèle appelé | Champ résultat |
|---|---|---|---|
| `Résidentiel` | `À vendre` | `predict()` | `x_studio_x_predicted_price` |
| `Résidentiel` | `À louer` | `predict_rent()` | `x_studio_x_predicted_rent` |
| `Commercial` | `À vendre` | `predict_commercial_sale()` | `x_studio_prix_estime_commercial_` |
| `Commercial` | `À louer` | `predict_commercial_rent()` | `x_studio_loyer_estime_commercial_mois` |

### Champs Odoo Studio — Résidentiel

| Champ Odoo (technique) | Variable API | Notes |
|------------------------|--------------|-------|
| `x_studio_x_bien_type` | `bien_type` | `Résidentiel` / `Commercial` |
| `x_studio_x_transaction_type` | `transaction_type` | `À vendre` / `À louer` |
| `x_studio_x_living_area` | `living_area` | — |
| `x_studio_x_bedroom_count` | `bedroom_count` | — |
| `x_studio_x_room_count` | `room_count` | — |
| `x_studio_x_facades` | `number_of_facades` | — |
| `x_studio_x_street` | `street` | Géocodage niveau rue |
| `x_studio_x_commune` | `commune` | — |
| `x_studio_x_postal_code` | `postal_code` | — |
| `x_studio_x_region` | `region` | — |
| `x_studio_x_state_of_building` | `state_of_building` | — |
| `x_studio_x_type_of_property` | `type_of_property` | — |
| `x_studio_x_construction_year` | `construction_year` | — |
| `x_studio_x_heating_type` | `heating_type` | — |
| `x_studio_x_garage` | `garage` | — |
| `x_studio_x_garden` | `garden` | — |
| `x_studio_x_garden_area` | `garden_area` | — |
| `x_studio_x_swimming_pool` | `swimming_pool` | — |
| `x_studio_x_terrace` | `terrace` | — |
| `x_studio_x_fireplace` | `fireplace` | — |
| `x_studio_x_lift` | `lift` | — |
| `x_studio_x_solar_panels` | `has_solar_panels` | — |
| `x_studio_x_peb` | `peb` | Multiplicateur post-prédiction |
| `x_studio_x_avis` | `avis` | Multiplicateur post-prédiction |
| `x_studio_x_predicted_price` | ← résultat vente | Écrit par webhook + batch |
| `x_studio_x_predicted_rent` | ← résultat location | Écrit par webhook + batch |

### Champs Odoo Studio — Commercial

| Champ Odoo (technique) | Variable API | Notes |
|------------------------|--------------|-------|
| `x_studio_type_de_local` | `commercial_type` | `Bureau` / `Commerce` / `Entrepôt` / `Industrie` / `Horeca` |
| `x_studio_x_surface_totale` | `surface_totale` | m² |
| `x_studio_hauteur_sous_plafond_m` | `hauteur_plafond` | Multiplicateur +10% si >6m (entrepôt/industrie) |
| `x_studio_quai_de_chargement` | `quai_chargement` | Booléen — +8% (entrepôt/industrie) |
| `x_studio_x_vitrine` | `vitrine` | Booléen — +5% (commerce/horeca) |
| `x_studio_prix_estime_commercial_` | ← résultat vente com. | Écrit par webhook + batch |
| `x_studio_loyer_estime_commercial_mois` | ← résultat location com. | Écrit par webhook + batch |

> **Note :** Odoo Studio ajoute automatiquement le préfixe `x_studio_` à tous les champs personnalisés, d'où le double préfixe `x_studio_x_`.

---

## Endpoints API

### `GET /health` — `GET /health-rent`
```json
{ "status": "ok", "model_name": "RandomForest", "r2": 0.8203, "mae": 66891.73, "feature_count": 25 }
```

### `POST /predict` — Vente résidentielle

Champs obligatoires : `room_count`, `living_area`, `number_of_facades`, `bedroom_count`

Champs optionnels : `postal_code`, `region`, `commune`, `street`, `type_of_property`, `state_of_building`, `peb`, `avis`, `construction_year`, `heating_type`, `garage`, `garden`, `swimming_pool`, `terrace`, `fireplace`, `lift`, `has_solar_panels`

```json
{ "predicted_price": 285000.00, "currency": "EUR" }
```

### `POST /predict-rent` — Location résidentielle

Champs : mêmes que `/predict`

```json
{ "predicted_rent": 1150.00, "currency": "EUR", "unit": "per month" }
```

### `POST /predict-commercial` — Vente ou Location commerciale

Champs obligatoires : `commercial_type`, `surface_totale`, `transaction_type`

- `commercial_type` : `Commerce` / `Bureau` / `Entrepôt` / `Industrie` / `Horeca`
- `transaction_type` : `À vendre` (vente) ou `À louer` (location)

Champs optionnels : `region`, `postal_code`, `commune`, `state_of_building`, `peb`, `heating_type`, `hauteur_plafond`, `quai_chargement`, `vitrine`

```json
// Vente
{ "predicted_price_commercial": 450000.00, "currency": "EUR" }
// Location
{ "predicted_rent_commercial": 2800.00, "currency": "EUR", "unit": "per month" }
```

### `GET /health-commercial`
```json
{
  "status": "ok",
  "sale_model":   { "r2": 0.69, "mae": 165207, "feature_count": 18 },
  "rental_model": { "r2": 0.54, "mae": 1320,   "feature_count": 18 }
}
```

### `POST /odoo-webhook`

Reçoit le payload Odoo → détecte `bien_type` + `transaction_type` → route vers le bon modèle → écrit le résultat via XML-RPC dans Odoo.

### Multiplicateurs post-prédiction

| Classe | PEB (résidentiel + commercial) | Avis (résidentiel) | Commercial spécifique |
|--------|-------------------------------|--------------------|-----------------------|
| A | +4.5% | +7.5% | — |
| B | +3.5% | +5.0% | — |
| C | +1.75% | +2.5% | — |
| D | 0% | 0% | — |
| E | -1.75% | -2.5% | — |
| F | -3.5% | -5.0% | — |
| G | -4.5% | -7.5% | — |
| Hauteur >6m | — | — | +10% (entrepôt/industrie) |
| Quai chargement | — | — | +8% (entrepôt/industrie) |
| Vitrine | — | — | +5% (commerce/horeca) |

Ajustement total plafonné à ±30% maximum.

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
