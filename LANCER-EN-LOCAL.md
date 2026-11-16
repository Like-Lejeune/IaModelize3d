# Lancer IaModelize3d sur son poste (Windows, sans Docker)

## Ce qu'il faut sur le poste

- **Node.js 22 ou plus récent** (https://nodejs.org)
- **Python 3.12 ou plus récent**, le plus simple étant **uv** (https://docs.astral.sh/uv/) qui installe Python tout seul
- Une connexion Internet au premier lancement (installation des dépendances)

## Lancer

1. Décompressez le zip, par exemple dans `D:\yves\travaux\IaModelize3d`.
2. Double-cliquez sur **`lancer-local.cmd`**.
   Le premier lancement installe tout (quelques minutes), les suivants démarrent tout de suite.
3. Ouvrez **http://localhost:5410**.

Deux fenêtres s'ouvrent : le site (celle du script) et l'API. Fermez les deux pour tout arrêter.

Par défaut, c'est la **démo** : l'IA est simulée, aucune clé n'est nécessaire, les données vont dans `data-demo\`.
Tableau de l'atelier en démo : ouvrez une fois http://localhost:5410/api/demo/operator, puis `/ops`.

## Avec la vraie IA

1. Copiez `.env.example` en `.env` (à la racine) et réglez le fournisseur ; exemple OpenAI :

   ```ini
   FW_LLM_PROVIDER=openai
   FW_LLM_API_KEY=sk-...
   FW_LLM_MODEL=gpt-5-mini
   FW_LLM_PRICE_IN_PER_M=0.25
   FW_LLM_PRICE_OUT_PER_M=2.00
   FW_DAILY_BUDGET_USD=2
   FW_SHOP_TARIFF=cm
   ```

2. Dans un terminal à la racine : `lancer-local.cmd -Ia`
   Le script vérifie d'abord le fournisseur (cinq petits appels) et ne lance le serveur que si tout est OK.

## Options

| Commande | Effet |
| --- | --- |
| `lancer-local.cmd` | Démo, IA simulée |
| `lancer-local.cmd -Ia` | Vraie IA (fichier `.env`) |
| `lancer-local.cmd -Installer` | Réinstalle les dépendances Python et Node, puis lance |

Depuis PowerShell, `.\lancer-local.ps1` accepte les mêmes options. Si Windows refuse de lancer le script
(« l'exécution de scripts est désactivée »), passez par `lancer-local.cmd`, ou tapez une fois
`Unblock-File .\lancer-local.ps1`.

## En cas de problème

- **« Aucun Python 3.12+ trouvé »** : installez uv (`winget install astral-sh.uv`), puis relancez.
- **Port déjà pris (8400 ou 5410)** : fermez l'ancienne fenêtre de l'API ou du site, puis relancez.
- **Page blanche ou erreur 403** : rechargez la page une fois que la fenêtre de l'API affiche « Application startup complete ».
