# Odoo Studio — Configuration Immobilier Commercial

Ce guide décrit les étapes manuelles à effectuer dans Odoo Studio pour activer l'estimation des biens commerciaux.

**Prérequis :** Les modèles ML commerciaux doivent être déployés sur le VPS et le service Flask redémarré (voir `GUIDE_VPS.md`).

---

## Étape 1 — Ajouter les valeurs "Ticari-Satış" et "Ticari-Kira" au champ Type de transaction

1. Ouvrir **Odoo Studio** → modèle **Estimation** (`x_estimation`)
2. Cliquer sur le champ **"Type de transaction"** (`x_studio_x_transaction_type`)
3. Dans les propriétés du champ → **"Modifier les valeurs de sélection"**
4. Ajouter les deux nouvelles valeurs :
   - Valeur technique : `Ticari-Satış` — Libellé : `Vente commerciale`
   - Valeur technique : `Ticari-Kira` — Libellé : `Location commerciale`
5. Sauvegarder

---

## Étape 2 — Ajouter les nouveaux champs commerciaux au modèle

Dans Studio → Estimation → **"Nouveaux champs"** :

| Nom technique | Type | Libellé | Valeurs (si sélection) |
|---|---|---|---|
| `x_studio_x_commercial_type` | Sélection | Type de local | Commerce / Bureau / Entrepôt / Industrie / Horeca |
| `x_studio_x_surface_totale` | Décimal | Surface totale (m²) | — |
| `x_studio_x_hauteur_plafond` | Décimal | Hauteur sous plafond (m) | — |
| `x_studio_x_quai_chargement` | Booléen | Quai de chargement | — |
| `x_studio_x_vitrine` | Booléen | Vitrine / Façade commerciale | — |
| `x_studio_x_zone_commerciale` | Texte | Zone commerciale | — |
| `x_studio_x_floor_count` | Entier | Nombre d'étages | — |
| `x_studio_x_predicted_price_commercial` | Décimal | Prix estimé commercial (€) | — |
| `x_studio_x_predicted_rent_commercial` | Décimal | Loyer estimé commercial (€/mois) | — |

---

## Étape 3 — Ajouter une section "Commercial" au formulaire avec visibilité conditionnelle

1. Studio → Estimation → Vue **Formulaire**
2. Faire glisser un composant **"Section"** dans le formulaire
3. Nommer la section : `Bien Commercial`
4. Faire glisser dans cette section les champs créés à l'étape 2
5. Pour chaque champ commercial, définir la **condition de visibilité** :
   - Condition : `Type de transaction est dans [Ticari-Satış, Ticari-Kira]`
   - *(Dans Studio : propriété "Visible si" → sélectionner le champ transaction_type)*

6. Optionnel : masquer les champs résidentiels (chambres, pièces, jardin, etc.) quand le type est commercial via la même logique de visibilité inversée.

---

## Étape 4 — Mettre à jour l'action automatisée (webhook)

1. Odoo → **Paramètres** → **Technique** → **Actions automatisées**
2. Ouvrir l'action **"ImmoApp - Estimer le prix"**
3. Dans la section **"Champs à envoyer"**, ajouter les nouveaux champs :
   - `x_studio_x_commercial_type`
   - `x_studio_x_surface_totale`
   - `x_studio_x_hauteur_plafond`
   - `x_studio_x_quai_chargement`
   - `x_studio_x_vitrine`
   - `x_studio_x_floor_count`
   - `x_studio_x_transaction_type` *(doit déjà être présent)*
4. Sauvegarder

---

## Étape 5 — Vérification end-to-end

1. Créer une nouvelle fiche Estimation dans Odoo
2. Sélectionner **"Vente commerciale"** comme type de transaction
3. Les champs commerciaux doivent apparaître (Bureau, Surface totale, etc.)
4. Remplir : Type de local = `Bureau`, Surface = `150`, Région = `Bruxelles`
5. Sauvegarder → attendre ~3 secondes
6. Le champ **"Prix estimé commercial (€)"** doit être rempli automatiquement

Pour **"Location commerciale"**, même test → le champ **"Loyer estimé commercial (€/mois)"** doit être rempli.

---

## Référence — Mapping champs Odoo ↔ API

| Champ Odoo (technique) | Variable API | Modèle |
|---|---|---|
| `x_studio_x_commercial_type` | `commercial_type` | commercial (satış + kira) |
| `x_studio_x_surface_totale` | `surface_totale` | commercial (satış + kira) |
| `x_studio_x_region` | `region` | partagé avec résidentiel |
| `x_studio_x_postal_code` | `postal_code` | partagé avec résidentiel |
| `x_studio_x_commune` | `commune` | partagé avec résidentiel |
| `x_studio_x_state_of_building` | `state_of_building` | partagé avec résidentiel |
| `x_studio_x_construction_year` | `construction_year` | partagé avec résidentiel |
| `x_studio_x_peb` | `peb` | partagé avec résidentiel |
| `x_studio_x_hauteur_plafond` | `hauteur_plafond` | commercial uniquement |
| `x_studio_x_quai_chargement` | `quai_chargement` | commercial uniquement |
| `x_studio_x_vitrine` | `vitrine` | commercial uniquement |
| `x_studio_x_floor_count` | `floor_count` | commercial uniquement |
| `x_studio_x_predicted_price_commercial` | ← résultat vente commerciale | écrit par webhook + batch |
| `x_studio_x_predicted_rent_commercial` | ← résultat location commerciale | écrit par webhook + batch |

### Valeurs valides pour `commercial_type`

| Valeur Odoo | Description |
|---|---|
| `Commerce` | Magasin / commerce de détail |
| `Bureau` | Bureau / espace de travail |
| `Entrepôt` | Entrepôt logistique |
| `Industrie` | Surface industrielle |
| `Horeca` | Restaurant / café / hôtel |

### Multiplicateurs post-prédiction (après résultat ML)

| Ajusteur | Condition d'application | Effet |
|---|---|---|
| PEB A | Tous types | +4.5% |
| PEB G | Tous types | -4.5% |
| Hauteur plafond >6m | Entrepôt / Industrie uniquement | +10% |
| Quai de chargement | Entrepôt / Industrie uniquement | +8% |
| Vitrine | Commerce / Horeca uniquement | +5% |
| Clamp sécurité | Tous types | Limite totale ajustement à ±30% max |
