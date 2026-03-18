# ImmoApp — Plan de déploiement (Windows Server OVH)

> Fichier local uniquement — ne pas envoyer sur GitHub.

---

## Situation

```
PC personnel ──Bureau à distance (RDP)──> VPS OVH (Windows Server)
```

Connexion via **Bureau à distance** (mstsc) directement sur le VPS Windows.
Tous les déploiements se font depuis le bureau du VPS (pas de terminal SSH nécessaire).

---

## PHASE 1 — Préparer le VPS Windows

### Étape 1 — Se connecter au VPS

Sur le PC entreprise → ouvrir **Bureau à distance (mstsc)** → entrer l'IP du VPS → connexion.

### Étape 2 — Installer Python

Sur le VPS, ouvrir un navigateur → télécharger Python 3.11 :
```
https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
```

Installation :
- Cocher **"Add Python to PATH"** ✅
- Cliquer **Install Now**

Vérifier dans PowerShell (sur le VPS) :
```powershell
python --version
# Python 3.11.x
```

### Étape 3 — Installer Git

Télécharger Git for Windows :
```
https://git-scm.com/download/win
```

Installation par défaut → Finish.

### Étape 4 — Ouvrir les ports (Pare-feu Windows)

Dans PowerShell (en tant qu'Administrateur) sur le VPS :

```powershell
# Port 5000 — test API (temporaire)
New-NetFirewallRule -DisplayName "ImmoApp API Test" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow

# Port 80 — HTTP production
New-NetFirewallRule -DisplayName "ImmoApp HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

> Port 5000 sera supprimé après la mise en production (Phase 4).

---

## PHASE 2 — Déployer le code

### Étape 5 — Cloner le dépôt GitHub

Dans PowerShell sur le VPS :

```powershell
cd C:\
mkdir immo
cd C:\immo
git clone https://github.com/dominys-be/immo-prediction.git
cd immo-prediction
```

### Étape 6 — Créer l'environnement virtuel

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r immo_api\requirements.txt
pip install -r odoo_batch\requirements.txt
pip install waitress   # Serveur WSGI pour Windows (remplace Gunicorn)
```

### Étape 7 — Créer les dossiers nécessaires

```powershell
mkdir C:\immo\immo-prediction\logs
mkdir C:\immo\immo-prediction\immo_api\models
```

---

## PHASE 3 — Transférer les fichiers .pkl

Les modèles sont sur le PC personnel. Voici les options :

### Option A — Via Google Drive + gdown (recommandé)

**Sur le PC personnel :**
1. Uploader ces 4 fichiers sur Google Drive :
   - `immo_api\models\model.pkl`
   - `immo_api\models\model_metadata.json`
   - `immo_api\models\rental_model.pkl`
   - `immo_api\models\rental_model_metadata.json`
2. Clic droit sur chaque fichier → **"Obtenir le lien"** → **"Tout le monde avec le lien"** → Copier
3. Le lien ressemble à : `https://drive.google.com/file/d/XXXXX/view?usp=sharing`
   → noter le **XXXXX** (ID du fichier) pour chaque fichier

**Sur le VPS (PowerShell) :**

```powershell
# Installer gdown (nécessaire pour les grands fichiers Google Drive)
pip install gdown

cd C:\immo\immo-prediction\immo_api\models

# Remplacer XXXXX par les vrais IDs Google Drive
gdown "https://drive.google.com/uc?id=XXXXX" -O model.pkl
gdown "https://drive.google.com/uc?id=XXXXX" -O rental_model.pkl
gdown "https://drive.google.com/uc?id=XXXXX" -O model_metadata.json
gdown "https://drive.google.com/uc?id=XXXXX" -O rental_model_metadata.json
```

> **Pourquoi gdown ?** model.pkl fait ~1 GB — Google Drive affiche une page de confirmation pour les grands fichiers, `Invoke-WebRequest` ne fonctionne pas. `gdown` contourne ce problème automatiquement.

### Option B — Via clé USB (accès physique requis)

1. Copier les 4 fichiers sur une clé USB depuis le PC personnel
2. Brancher la clé sur le PC du VPS (accès physique) ou partager via Bureau à distance :
   **Bureau à distance → Ressources locales → Lecteurs → cocher la clé USB**
3. Copier vers `C:\immo\immo-prediction\immo_api\models\`

---

## PHASE 4 — Lancer l'API Flask

### Étape 8 — Test rapide

```powershell
cd C:\immo\immo-prediction\immo_api
..\venv\Scripts\Activate.ps1
python app.py
```

Ouvrir un 2e PowerShell et tester :
```powershell
Invoke-WebRequest http://localhost:5000/health | Select-Object -Expand Content
Invoke-WebRequest http://localhost:5000/health-rent | Select-Object -Expand Content
```

`Ctrl+C` pour arrêter.

### Étape 9 — Installer NSSM (gestionnaire de services Windows)

Télécharger NSSM :
```
https://nssm.cc/download
```

Extraire → copier `nssm.exe` dans `C:\Windows\System32\`

### Étape 10 — Créer un service Windows avec NSSM

Dans PowerShell (Administrateur) :

```powershell
nssm install ImmoApp
```

Une fenêtre s'ouvre → remplir :

| Champ | Valeur |
|-------|--------|
| **Path** | `C:\immo\immo-prediction\venv\Scripts\python.exe` |
| **Startup directory** | `C:\immo\immo-prediction\immo_api` |
| **Arguments** | `-m waitress --host=127.0.0.1 --port=5000 app:app` |

Onglet **I/O** :
- Output : `C:\immo\immo-prediction\logs\access.log`
- Error  : `C:\immo\immo-prediction\logs\error.log`

Cliquer **Install service** → puis :

```powershell
nssm start ImmoApp
nssm status ImmoApp   # doit afficher : SERVICE_RUNNING
```

---

## PHASE 5 — IIS comme reverse proxy (port 80)

### Étape 11 — Activer IIS

PowerShell (Administrateur) :

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServer, IIS-WebServerManagement -All
```

Ou via : **Panneau de configuration → Programmes → Activer ou désactiver des fonctionnalités Windows → Internet Information Services**

### Étape 12 — Installer ARR + URL Rewrite pour IIS

Télécharger et installer :
- **URL Rewrite** : `https://www.iis.net/downloads/microsoft/url-rewrite`
- **Application Request Routing (ARR)** : `https://www.iis.net/downloads/microsoft/application-request-routing`

### Étape 13 — Configurer le proxy IIS

Ouvrir **Gestionnaire IIS** → Site par défaut → **URL Rewrite** → Ajouter une règle :

```
Type        : Reverse Proxy
URL serveur : 127.0.0.1:5000
```

### Étape 14 — Fermer le port 5000

```powershell
Remove-NetFirewallRule -DisplayName "ImmoApp API Test"
```

Tester depuis le navigateur : `http://51.68.231.173/health`

---

## PHASE 6 — Scripts batch Odoo

### Étape 15 — Configurer le .env

```powershell
cd C:\immo\immo-prediction\odoo_batch
copy .env.example .env
notepad .env
```

Remplir :
```
ODOO_URL=https://dominys.odoo.com
ODOO_DB=dominys
ODOO_USER=gkridvan@icloud.com
ODOO_APIKEY=VOTRE_CLE_API_ODOO
ODOO_MODEL=x_estimation
API_URL=http://localhost:5000/predict
```

### Étape 16 — Tester les scripts batch

```powershell
cd C:\immo\immo-prediction
.\venv\Scripts\Activate.ps1
python odoo_batch\batch.py --dry-run
python odoo_batch\batch_rent.py --dry-run
```

### Étape 17 — Planificateur de tâches Windows (toutes les 3 jours)

PowerShell (Administrateur) :

```powershell
# Batch vente
$action1 = New-ScheduledTaskAction `
    -Execute "C:\immo\immo-prediction\venv\Scripts\python.exe" `
    -Argument "C:\immo\immo-prediction\odoo_batch\batch.py" `
    -WorkingDirectory "C:\immo\immo-prediction"

$trigger1 = New-ScheduledTaskTrigger -Daily -DaysInterval 3 -At 00:00

Register-ScheduledTask -TaskName "ImmoApp Batch Vente" `
    -Action $action1 -Trigger $trigger1 `
    -RunLevel Highest -Force

# Batch location
$action2 = New-ScheduledTaskAction `
    -Execute "C:\immo\immo-prediction\venv\Scripts\python.exe" `
    -Argument "C:\immo\immo-prediction\odoo_batch\batch_rent.py" `
    -WorkingDirectory "C:\immo\immo-prediction"

Register-ScheduledTask -TaskName "ImmoApp Batch Location" `
    -Action $action2 -Trigger $trigger1 `
    -RunLevel Highest -Force
```

Vérifier : **Planificateur de tâches** → `ImmoApp Batch Vente` et `ImmoApp Batch Location` présents.

---

## Vérification finale

```powershell
nssm status ImmoApp                          # SERVICE_RUNNING ?
Invoke-WebRequest http://localhost:5000/health | Select-Object -Expand Content
Invoke-WebRequest http://localhost/health    # Via IIS port 80
Get-ScheduledTask -TaskName "ImmoApp*"       # Tâches planifiées ?
```

---

## Mise à jour du code (après git push)

```powershell
cd C:\immo\immo-prediction
git pull origin main
.\venv\Scripts\Activate.ps1
pip install -r immo_api\requirements.txt
nssm restart ImmoApp
```
