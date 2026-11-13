# IaModelize3d — front React + TypeScript

Un studio de conception d'objets imprimés en 3D, sur le moteur IaModelize3d. La personne décrit ce qu'elle veut
créer (ou montre une pièce en photo), l'IA lui pose les questions utiles, dessine un modèle paramétrique, et la
personne l'ajuste elle-même (réglages, versions) ou en demandant une modification dans la discussion. Ensuite elle
le télécharge en STL ou le fait imprimer par l'atelier : prix en FCFA, Mobile Money, suivi de la commande.

## Langues : français et anglais

- Le sélecteur **FR / EN** est dans l'en-tête. Au premier passage, la langue suit celle du navigateur (anglais si le
  navigateur est en anglais, français sinon) ; le choix est ensuite gardé sur l'appareil (`localStorage`,
  clé `iamodelize3d.lang`).
- `src/i18n.tsx` : la langue courante (`useLang()` donne `lang` et `tr(fr, en)`), le sélecteur `LangSwitch`.
- `src/texts.ts` : les textes partagés dans les deux langues (statuts, livraison, matières, journal de la commande,
  messages d'erreur), les montants et les dates au format de la langue.
- Les réglages d'un modèle affichent `label_en` / `group_en` en anglais quand le programme les donne.
- L'IA répond dans la langue du message, quelle que soit la langue de l'interface. La démo sans clé fait de même
  (français ou anglais).

## Pages

| Route | Pour qui | Rôle |
| --- | --- | --- |
| `/` | tous | « Que voulez-vous créer ? » : description, photos, exemples, créations précédentes |
| `/studio/:id` | créateur | le studio : discussion avec l'IA, modèle 3D, réglages, versions, commande |
| `/reparation` | client | formulaire direct pour une pièce cassée (photo sur A4), sans passer par le studio |
| `/commandes`, `/commandes/:id` | client | commandes : prix, paiement, suivi |
| `/ops` | atelier | tableau de l'atelier : vérification des paiements, impression, contrôle, expédition |

## Comment le studio marche

- **La conversation** (`src/studio/Conversation.tsx`) suit en direct le flux d'événements du projet
  (`GET /api/projects/:id/events`, SSE) : messages et questions de l'IA, étapes de travail, nouvelles versions.
  Une question se répond d'un clic ou avec ses mots.
- **Le modèle 3D** (`src/studio/Viewer.tsx`, three.js) est construit **dans le navigateur** par le noyau géométrique
  de IaModelize3d (`packages/geom`, manifold en WebAssembly) dans un worker (`src/geom/worker.ts`). Un curseur met
  à jour le modèle en direct ; « Porte-à-faux » montre les faces qui demanderaient des supports.
- **Les réglages** sont les paramètres que l'IA a exposés dans son programme (plage, unité, origine de la valeur).
  Relâcher un curseur enregistre une version (`PUT /api/projects/:id/params`).
- **Les versions** se restaurent (une version restaurée devient la plus récente).
- **Commander** envoie la version affichée au calcul de prix de l'atelier (`POST /api/shop/requests` avec
  `project_id`), puis ouvre la commande.

L'état du studio est dans `src/studio/store.ts` (adapté du studio Svelte de IaModelize3d, `web/src/lib/project.svelte.ts`).

## Lancer en local sans clé d'IA

```bash
# 1. l'API avec l'IA simulée (FCFA, vraie logique de projet et de commande)
cd server && .venv/bin/python scripts/g1_demo.py        # http://127.0.0.1:8400, données dans data-demo/

# 2. le front (Node 22+ ; le noyau géométrique est lu dans packages/geom : faire `npm install` à la racine aussi)
cd apps/repair-web && npm install && npm run dev        # http://localhost:5410
```

En démo, le concepteur est joué par `server/scripts/demo_designs.py` : il choisit l'un de cinq vrais modèles
paramétriques d'après les mots de la demande (boîte, support incliné, crochet mural, molette, pot), pose sa première
question si aucune taille n'est donnée, et comprend des demandes simples (« plus haut », « largeur 90 mm », « plus
solide », « 3 compartiments »). Le modèle, les curseurs, les versions et la commande sont réels.

Pour voir le tableau de l'atelier, ouvrez une fois `http://localhost:5410/api/demo/operator` (route de démo), puis `/ops`.

## Avec la vraie IA

```bash
# .env à la racine du dépôt
FW_LLM_PROVIDER=meta              # ou openai / custom (voir .env.example)
META_API_KEY=...                  # ou FW_LLM_API_KEY=...
FW_SHOP_TARIFF=cm                 # tarif en FCFA
FW_USD_RATE=600                   # FCFA par dollar, pour l'équivalent affiché
FW_PUBLIC_URL=http://localhost:5410

cd server && .venv/bin/python -m uvicorn iamodelize3d.app:app --port 8400
cd apps/repair-web && npm run dev
```

Le vrai concepteur (`server/iamodelize3d/agent/`) écrit n'importe quel objet, mesure les pièces sur les photos (avec
SAM, chez Meta), cherche des cotes standard, se relit sous plusieurs angles et passe une relecture indépendante.

Numéros Mobile Money affichés au client (facultatif), dans `apps/repair-web/.env` :

```
VITE_MOMO_MTN=+237 6xx xx xx xx
VITE_MOMO_ORANGE=+237 6xx xx xx xx
```

## Build

```bash
npm run build      # tsc + vite build -> dist/ (le studio et three.js sont chargés à part, à l'ouverture d'un studio)
```

En production, servez `dist/` et redirigez `/api` et `/files` vers l'API sur la même origine (le cookie de session
doit rester sur ce domaine).
