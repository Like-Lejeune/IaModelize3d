# Réparation (G1) — front React + TypeScript

Le front de la verticale **G1 Réparation** : un client photographie sa pièce cassée sur une feuille A4, reçoit un prix
en FCFA, paie par Mobile Money et suit sa commande ; l'atelier vérifie les paiements, imprime, contrôle et expédie.
Il parle à l'API boutique de Formwright (`server/formwright/shop/routes.py`, `/api/shop`).

## Pages

| Route | Pour qui | Rôle |
| --- | --- | --- |
| `/` | client | nouvelle demande : photos sur A4, plaque signalétique, description, quantité, matière, réception, contact |
| `/commandes` | client | ses commandes (liées au cookie de session de ce navigateur) |
| `/commandes/:id` | client | suivi : question de l'atelier, prix, changement de matière/quantité/réception, paiement, réception |
| `/ops` | atelier | tableau : demandes à examiner, paiements à vérifier, impression, contrôle qualité, expédition, imprimantes |

## Lancer en local sans clé d'IA

```bash
# 1. l'API avec des étapes IA simulées (prix FCFA, vraie logique de commande)
cd server && .venv/bin/python scripts/g1_demo.py        # http://127.0.0.1:8400, données dans data-demo/

# 2. le front
cd apps/repair-web && npm install && npm run dev        # http://localhost:5410
```

Pour voir le tableau de l'atelier, ouvrez une fois `http://localhost:5410/api/demo/operator` dans le navigateur
(route de démo uniquement), puis `/ops`.

## Avec la vraie API

```bash
# .env à la racine du dépôt
FW_SHOP_TARIFF=cm                 # tarif en FCFA
FW_USD_RATE=600                   # FCFA par dollar, pour l'équivalent affiché
FW_LLM_PROVIDER=meta              # ou openai / custom (voir .env.example)
META_API_KEY=...                  # ou FW_LLM_API_KEY=...
FW_PUBLIC_URL=http://localhost:5410

cd server && .venv/bin/python -m uvicorn formwright.app:app --port 8400
cd apps/repair-web && npm run dev
```

Un opérateur d'atelier se crée avec `server/scripts/shop_operator.py` ; son lien de connexion mène à `/ops`.

Numéros Mobile Money affichés au client (facultatif), dans `apps/repair-web/.env` :

```
VITE_MOMO_MTN=+237 6xx xx xx xx
VITE_MOMO_ORANGE=+237 6xx xx xx xx
```

`FW_API_URL` change l'adresse de l'API vers laquelle Vite redirige `/api` et `/files` (par défaut `http://127.0.0.1:8400`).

## Build

```bash
npm run build      # tsc + vite build -> dist/
```

En production, servez `dist/` et redirigez `/api` et `/files` vers l'API sur la même origine (le cookie de session
doit rester sur ce domaine).
