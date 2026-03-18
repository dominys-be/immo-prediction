# ImmoApp — Guide de mise en production

---

## Ce que fait le système

ImmoApp est un système d'intelligence artificielle qui prédit automatiquement **les prix de vente et les loyers** des biens immobiliers belges, directement depuis Odoo.

**Fonctionnement :**
1. Vous encodez un bien dans Odoo (surface, chambres, localisation, PEB…)
2. Vous cliquez sur **"Estimer le prix"**
3. Le champ **Prix estimé (€)** ou **Loyer estimé (€/mois)** se remplit automatiquement

Le tout en moins de 3 secondes.

---

## Architecture

```
┌─────────────────────────┐              ┌──────────────────────────────┐
│     Odoo SaaS (cloud)   │              │       Serveur VPS         │
│                         │              │                              │
│  Formulaire immobilier  │──── HTTP ───▶│  API d'estimation (IA)      │
│  Bouton "Estimer" →     │              │  Modèle vente  : R²=0.82     │
│  <- Prix estimé (€)     │◀────────────│  Modèle location: R²=0.81   │
│                         │              │                              │
│                         │              │  Script automatique (cron)  │
│  Nouveaux biens sans    │◀────────────│  toutes les 5 minutes        │
│  estimation -> remplis  │              │  traite les biens en cours   │
└─────────────────────────┘              └──────────────────────────────┘
```

- **Odoo** : votre abonnement SaaS existant — aucune modification, aucun coût supplémentaire
- **VPS ** : le serveur que vous avez acheté — héberge l'IA et le script automatique
- **GitHub** : le code source est versionné à `github.com/dominys-be/immo-prediction`

---

## Modèles IA

| Modèle | Données d'entraînement | Précision |
|--------|----------------------|-----------|
| Vente | 92.544 annonces Immoweb | MAE ±67.000 EUR |
| Location | 9.921 annonces Immoweb | MAE ±230 EUR/mois |

Les estimations tiennent compte de : surface, localisation, PEB, année de construction, état du bâtiment, équipements, et plus de 20 autres critères.

---

## Une seule action requise de Philippe

> **L'environnement de développement est prêt.** Les credentials Odoo, la clé API, et la configuration sont déjà en place. Une fois l'accès SSH accordé, le développeur installe et configure tout le reste de manière autonome.

### Ajouter la clé SSH du développeur au VPS

Le développeur fournira une clé SSH (longue chaîne commençant par `ssh-ed25519`).
Il faut l'ajouter au serveur via **l'une des deux méthodes suivantes** :

---

#### Méthode A — Via OVH Manager (recommandée, sans terminal)

1. Aller sur **[manager.ovhcloud.com](https://manager.ovhcloud.com)** → Se connecter
2. Menu gauche : **Bare Metal Cloud → VPS** → sélectionner le VPS
3. Onglet **"Accueil"** → bouton **"Réinstaller le VPS"**
4. Choisir l'OS (Ubuntu 22.04 recommandé)
5. À l'étape **"Clé SSH"** → coller la clé fournie par le développeur
6. Confirmer → le VPS redémarre (~5 minutes)

> **Attention :** La réinstallation efface le contenu du serveur. Si le VPS est vierge (nouveau), c'est la bonne méthode.

---

#### Méthode B — Via terminal (si le VPS est déjà configuré)

OVH envoie le mot de passe root par e-mail à la création du VPS. Utiliser ce mot de passe :

```bash
ssh root@51.68.231.173
```

Puis coller exactement :

```bash
mkdir -p /root/.ssh
echo "COLLER_ICI_LA_CLE_SSH_DU_DEVELOPPEUR" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

---

**C'est tout. Le développeur prend le relais à partir de là.**

---

## Ce que le développeur fait ensuite (pour information)

Une fois l'accès SSH accordé, le développeur effectue les opérations suivantes de manière autonome :

1. Connexion au VPS et installation de l'environnement Python
2. Clonage du code depuis GitHub
3. Transfert des modèles IA (fichiers volumineux non stockés sur GitHub)
4. Configuration du service (démarrage automatique au reboot)
5. Mise en place des scripts batch (synchronisation Odoo toutes les 5 minutes)
6. Tests de validation (vérification que les estimations sont correctes)

---

## Après la mise en production — Aucune maintenance requise

Le système est entièrement autonome :

| Action | Fréquence | Automatique ? |
|--------|-----------|---------------|
| Estimation des nouveaux biens | Toutes les 5 min | Oui |
| Redémarrage après coupure serveur | Au reboot | Oui |
| Mise à jour du code | Sur demande | Manuel (développeur) |

---

## En cas de problème

**Vérification rapide depuis le navigateur :**
```
http://51.68.231.173/health
```
Si la page affiche `{"status": "ok"}`, le système fonctionne correctement.

**Redémarrer le service si nécessaire :**
```bash
ssh immo@51.68.231.173
sudo systemctl restart immo-api
```

---


