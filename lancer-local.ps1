<#
.SYNOPSIS
  Lance IaModelize3d sur ce poste, sans Docker : l'API (port 8400) et le site React (port 5410).

.DESCRIPTION
  Au premier lancement, le script installe ce qu'il faut : l'environnement Python du serveur (server\.venv)
  et les modules Node (node_modules à la racine et dans apps\repair-web). Les lancements suivants démarrent tout de suite.
  L'API s'ouvre dans une seconde fenêtre PowerShell ; fermez les deux fenêtres (ou Ctrl+C) pour tout arrêter.
  Puis ouvrez http://localhost:5410

  Sans option : la démo, avec une IA simulée (aucune clé nécessaire, données dans data-demo\).
  -Ia : la vraie IA, réglée dans le fichier .env à la racine (voir README, « Brancher une vraie IA »).

.EXAMPLE
  .\lancer-local.ps1              # démo, IA simulée
.EXAMPLE
  .\lancer-local.ps1 -Ia          # vraie IA (.env), vérification du fournisseur avant le lancement
.EXAMPLE
  .\lancer-local.ps1 -Installer   # réinstalle les dépendances Python et Node, puis lance
#>
[CmdletBinding()]
param(
    [switch]$Ia,
    [switch]$Installer
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$server = Join-Path $root 'server'
$web = Join-Path $root 'apps\repair-web'
$python = Join-Path $server '.venv\Scripts\python.exe'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n$text" -ForegroundColor Red; exit 1 }
# runs a native command quietly and says whether it succeeded (Windows PowerShell 5.1 turns a redirected stderr into
# errors that would stop the script under 'Stop')
function Test-Ok([scriptblock]$run) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $run 2>&1 | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false } finally { $ErrorActionPreference = $old }
}

# --- outils nécessaires
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js est introuvable. Installez Node 22 ou plus récent (https://nodejs.org), puis relancez." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "npm est introuvable (il est livré avec Node.js)." }

# --- Python : server\.venv (Python 3.12 ou plus récent)
if ($Installer -and (Test-Path (Join-Path $server '.venv'))) {
    Step "Suppression de l'ancien server\.venv"
    Remove-Item -Recurse -Force (Join-Path $server '.venv')
}
if (-not (Test-Path $python)) {
    Step "Création de server\.venv"
    Push-Location $server
    try {
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            if (-not (Test-Ok { uv venv --python 3.12 .venv })) { uv python install 3.12; uv venv --python 3.12 .venv }
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            # le premier Python 3.12+ connu du lanceur py
            $found = $null
            foreach ($v in @('3.14', '3.13', '3.12')) {
                if (Test-Ok { py "-$v" -c "import sys" }) { $found = $v; break }
            }
            if (-not $found) { Fail "Aucun Python 3.12+ trouvé par py. Installez uv (https://docs.astral.sh/uv/) ou Python 3.12+, puis relancez." }
            py -$found -m venv .venv
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            python -m venv .venv
        } else {
            Fail "Python est introuvable. Installez uv (https://docs.astral.sh/uv/) ou Python 3.12+, puis relancez."
        }
    } finally { Pop-Location }
    if (-not (Test-Path $python)) { Fail "server\.venv n'a pas pu être créé." }
}

# un venv dont la première installation a échoué a python.exe mais pas les paquets : on regarde les paquets
if ($Installer -or -not (Test-Ok { & $python -c "import fastapi, iamodelize3d" })) {
    Step "Installation du serveur (paquets Python)"
    Push-Location $server
    try {
        if (Get-Command uv -ErrorAction SilentlyContinue) { uv pip install --python .venv -e ".[dev]" }
        else { & $python -m pip install --upgrade pip; & $python -m pip install -e ".[dev]" }
        if ($LASTEXITCODE -ne 0) { Fail "L'installation des paquets Python a échoué (voir les messages au-dessus)." }
    } finally { Pop-Location }
}

# --- Node : le noyau géométrique (workspace racine) et le site React
if ($Installer -or -not (Test-Path (Join-Path $root 'node_modules'))) {
    Step "Installation des modules Node (racine : noyau géométrique)"
    Push-Location $root; try { npm install; if ($LASTEXITCODE -ne 0) { Fail "npm install a échoué à la racine." } } finally { Pop-Location }
}
if ($Installer -or -not (Test-Path (Join-Path $web 'node_modules'))) {
    Step "Installation des modules Node (apps\repair-web)"
    Push-Location $web; try { npm install; if ($LASTEXITCODE -ne 0) { Fail "npm install a échoué dans apps\repair-web." } } finally { Pop-Location }
}

# --- l'API
if ($Ia) {
    if (-not (Test-Path (Join-Path $root '.env'))) { Fail "Pas de fichier .env à la racine. Copiez .env.example en .env et réglez le fournisseur d'IA (README, « Brancher une vraie IA »)." }
    Step "Vérification du fournisseur d'IA"
    Push-Location $server
    try { & $python scripts\check_llm.py } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Fail "La vérification a échoué : corrigez .env (voir les essais en ÉCHEC), puis relancez." }
    $apiArgs = "-m uvicorn iamodelize3d.app:app --port 8400"
    $mode = "vraie IA"
} else {
    $apiArgs = "scripts\g1_demo.py"
    $mode = "démo, IA simulée"
}

Step "Démarrage de l'API ($mode) dans une seconde fenêtre : http://127.0.0.1:8400"
$command = "Set-Location '$server'; `$Host.UI.RawUI.WindowTitle = 'IaModelize3d API ($mode)'; & '$python' $apiArgs"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $command | Out-Null

Step "Démarrage du site : ouvrez http://localhost:5410"
if (-not $Ia) { Write-Host "Tableau de l'atelier (démo) : ouvrez une fois http://localhost:5410/api/demo/operator puis /ops" -ForegroundColor DarkGray }
Push-Location $web
try { npm run dev } finally { Pop-Location }
