<#
.SYNOPSIS
  Runs IaModelize3d for development: the API (uvicorn) and the web app (vite) in one console.

.DESCRIPTION
  Both logs go to this window with [api] and [web] prefixes; Ctrl+C stops both.
  The first run installs dependencies (node_modules, server\.venv) and builds the PCB worker (packages\pcb\dist);
  -Setup reinstalls them and rebuilds the PCB worker when its sources are newer.
  Open http://localhost:5400: vite serves the UI and proxies /api and /files to the API.
  Edits apply on their own: vite updates the page as web files change, and the API restarts once
  server\iamodelize3d or packages\geom\src change. Pages opened on the API port go to vite as well.

.EXAMPLE
  .\dev.ps1
.EXAMPLE
  .\dev.ps1 -NoReload      # keep the API running through server edits (agent jobs are not cut short)
.EXAMPLE
  .\dev.ps1 -Lan           # open the web app from a phone on the same network
.EXAMPLE
  .\dev.ps1 -Only api      # just the API (it serves web\build if that was built)
#>
[CmdletBinding()]
param(
    # Which part to run.
    [ValidateSet('all', 'api', 'web')] [string]$Only = 'all',
    # not vite's and uvicorn's usual 5173 and 8000, which other local projects take
    [int]$ApiPort = 8400,
    [int]$WebPort = 5400,
    # Do not restart the API when server\iamodelize3d or packages\geom\src change; by default it restarts,
    # cutting a running agent job short.
    [switch]$NoReload,
    # Make the web app reachable from other devices on the network.
    [switch]$Lan,
    # Open the browser once everything is up.
    [switch]$Open,
    # Reinstall npm and Python dependencies before starting (and rebuild the PCB worker if it is out of date).
    [switch]$Setup
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$serverDir = Join-Path $root 'server'
$webDir = Join-Path $root 'web'
$pcbDir = Join-Path $root 'packages\pcb'
$python = Join-Path $serverDir '.venv\Scripts\python.exe'
$vite = Join-Path $root 'node_modules\vite\bin\vite.js'
$watched = (Join-Path $serverDir 'iamodelize3d'), (Join-Path $root 'packages\geom\src')
$runApi = $Only -ne 'web'
$runWeb = $Only -ne 'api'
$utf8 = New-Object Text.UTF8Encoding $false

function Say([string]$text, [ConsoleColor]$color = 'Cyan') { Write-Host $text -ForegroundColor $color }

function Invoke-Step([string]$what, [string]$dir, [scriptblock]$command) {
    Say "==> $what"
    Push-Location $dir
    try { & $command } finally { Pop-Location }
    if ($LASTEXITCODE) { throw "$what failed (exit code $LASTEXITCODE)" }
}

function Assert-PortFree([int]$port, [string]$flag) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $listener) { return }
    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $who = if ($owner) { "$($owner.ProcessName) (pid $($owner.Id))" } else { "pid $($listener.OwningProcess)" }
    throw "Port $port is already taken by $who. Stop it or pick another port with $flag."
}

function Start-Child([string]$name, [ConsoleColor]$color, [string]$readyPattern, [string]$exe, [object[]]$arguments,
                     [string]$dir, [hashtable]$environment) {
    $psi = New-Object Diagnostics.ProcessStartInfo $exe
    $psi.Arguments = ($arguments | ForEach-Object { if ("$_" -match '\s') { "`"$_`"" } else { "$_" } }) -join ' '
    $psi.WorkingDirectory = $dir
    $psi.UseShellExecute = $false  # stays on this console, so Ctrl+C reaches it too
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    foreach ($key in $environment.Keys) { $psi.EnvironmentVariables[$key] = $environment[$key] }
    $process = [Diagnostics.Process]::Start($psi)
    [pscustomobject]@{
        Name = $name; Color = $color; ReadyPattern = $readyPattern; Ready = $false; Process = $process; ExitedAt = $null
        Readers = @($process.StandardOutput, $process.StandardError)
        Pending = @($process.StandardOutput.ReadLineAsync(), $process.StandardError.ReadLineAsync())
    }
}

function Stop-Child($child) {
    if (-not $child.Process.HasExited) { cmd.exe /c "taskkill /PID $($child.Process.Id) /T /F >nul 2>&1" }
    $null = $child.Process.WaitForExit(5000)
}

# uvicorn's own --reload restarts its worker with a console-wide Ctrl+C on Windows, which would stop
# everything here as well, so this script watches the sources itself and restarts the whole process.
function Start-Api {
    $environment = @{ PYTHONUNBUFFERED = '1'; PYTHONIOENCODING = 'utf-8' }
    # with vite running, a page opened on the API port is sent to it instead of an outdated web\build
    if ($runWeb) { $environment.FW_WEB_DEV_PORT = "$WebPort" }
    # vite passes the visitor's address in X-Forwarded-For; it is trusted from vite (local) only
    $arguments = @('-m', 'uvicorn', 'iamodelize3d.app:app', '--port', $ApiPort, '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1')
    Start-Child 'api' Magenta 'Application startup complete' $python $arguments $serverDir $environment
}

function Test-PythonDeps {
    # Windows PowerShell turns a native command's stderr into error records, which 'Stop' would throw
    $ErrorActionPreference = 'Continue'  # for this function only
    & $python -c 'import fastapi' 2>&1 | Out-Null
    $LASTEXITCODE -eq 0
}

# 'missing', 'stale' (a source is newer than the bundle) or $null. The bundle also inlines the geometry package's boards.json.
function Get-PcbBundleState {
    $bundle = Join-Path $pcbDir 'dist\pcb-worker.mjs'
    if (-not (Test-Path $bundle)) { return 'missing' }
    $built = (Get-Item $bundle).LastWriteTimeUtc
    $sources = @(Get-ChildItem (Join-Path $pcbDir 'src'), (Join-Path $pcbDir 'scripts') -Recurse -File -ErrorAction SilentlyContinue) +
               @(Get-Item (Join-Path $pcbDir 'package-lock.json'), (Join-Path $root 'packages\geom\src\boards.json') -ErrorAction SilentlyContinue)
    if ($sources | Where-Object { $_.LastWriteTimeUtc -gt $built } | Select-Object -First 1) { return 'stale' }
    $null
}

function Get-SourceStamp {
    $files = @(Get-ChildItem $watched -Recurse -File -Include *.py, *.ts, *.json -ErrorAction SilentlyContinue)
    $newest = $files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    [pscustomobject]@{ Key = "$($files.Count)|$($newest.LastWriteTimeUtc.Ticks)"; Newest = $newest.FullName.Substring($root.Length + 1) }
}

# ------------------------------------------------------------------ dependencies
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is not on PATH (Node 24 is needed).' }
if ($Setup -or -not (Test-Path $vite)) {
    Invoke-Step 'npm install' $root { npm.cmd install }
}
if ($runApi -and -not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { Invoke-Step 'create server\.venv' $serverDir { py -3 -m venv .venv } }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { Invoke-Step 'create server\.venv' $serverDir { python -m venv .venv } }
    else { throw 'Python 3.12+ is not on PATH.' }
}
# a venv whose first install failed has python.exe but no packages, so look for them, not for the venv
if ($runApi -and ($Setup -or -not (Test-PythonDeps))) {
    Invoke-Step 'pip install server' $serverDir { & $python -m pip install -e '.[dev]' }
}
# The PCB worker is its own npm package; the API runs only its bundle (packages\pcb\dist). Built on the first run and by
# -Setup when out of date; without it the API still runs, with the PCB tools and the PCB example off.
if ($runApi) {
    $pcbState = Get-PcbBundleState
    if ($pcbState -eq 'missing' -or ($Setup -and $pcbState)) {
        try {
            if ($Setup -or -not (Test-Path (Join-Path $pcbDir 'node_modules'))) { Invoke-Step 'npm ci packages\pcb' $pcbDir { npm.cmd ci --ignore-scripts } }
            Invoke-Step 'bundle the PCB worker' $pcbDir { npm.cmd run bundle }
        }
        catch { Say "The PCB worker was not built ($($_.Exception.Message)); the PCB tools and the PCB example stay off." Yellow }
    }
    elseif ($pcbState -eq 'stale') {
        Say 'packages\pcb\dist is older than its sources: .\dev.ps1 -Setup rebuilds it.' Yellow
    }
}

# ------------------------------------------------------------------ checks
if ($runApi) {
    Assert-PortFree $ApiPort '-ApiPort'
    $envFiles = (Join-Path $root '.env'), (Join-Path (Split-Path $root) '.env')
    if (-not ($env:META_API_KEY -or $env:META_KEY -or ($envFiles | Where-Object { Test-Path $_ }))) {
        Say 'No .env found: copy .env.example to .env and set META_API_KEY, otherwise the agent cannot call models.' Yellow
    }
    if (-not $runWeb -and -not (Test-Path (Join-Path $webDir 'build'))) {
        Say "web\build is missing, so :$ApiPort serves only the API. Build it with: npm run build" Yellow
    }
}
if ($runWeb) { Assert-PortFree $WebPort '-WebPort' }

# ------------------------------------------------------------------ run
try { $consoleEncoding = [Console]::OutputEncoding; [Console]::OutputEncoding = $utf8 } catch { $consoleEncoding = $null }
$children = @()
$failed = $null
try {
    if ($runApi) { $children += Start-Api }
    if ($runWeb) {
        $webArgs = @($vite, 'dev', '--port', $WebPort, '--strictPort')
        if ($Lan) { $webArgs += '--host' }
        $children += Start-Child 'web' Green 'Local:' 'node' $webArgs $webDir @{ FW_API = "http://127.0.0.1:$ApiPort" }
    }

    $reloading = $runApi -and -not $NoReload
    if ($reloading) { $sources = (Get-SourceStamp).Key; $nextScan = Get-Date; $restartAt = $null }
    $announced = $false
    :watch while ($true) {
        $busy = $false
        foreach ($child in $children) {
            for ($i = 0; $i -lt 2; $i++) {
                while ($child.Pending[$i] -and $child.Pending[$i].IsCompleted) {
                    $line = $child.Pending[$i].Result
                    if ($null -eq $line) { $child.Pending[$i] = $null; break }  # stream closed
                    Write-Host ('{0,-6}' -f "[$($child.Name)]") -ForegroundColor $child.Color -NoNewline
                    Write-Host $line
                    # vite colours its output even into a pipe; match on the plain text
                    if (-not $child.Ready -and ($line -replace '\x1b\[[\d;]*m') -match $child.ReadyPattern) { $child.Ready = $true }
                    $child.Pending[$i] = $child.Readers[$i].ReadLineAsync()
                    $busy = $true
                }
            }
            if ($child.Process.HasExited) {
                # let the last lines (a traceback, say) come through first
                if (-not $child.ExitedAt) { $child.ExitedAt = Get-Date }
                if (($child.Pending | Where-Object { $_ }) -and ((Get-Date) - $child.ExitedAt).TotalSeconds -lt 1) { continue }
                if ($reloading -and $child.Name -eq 'api') {
                    Say "api exited with code $($child.Process.ExitCode); it restarts on the next change." Yellow
                    $children = @($children | Where-Object { $_ -ne $child })
                    continue
                }
                $failed = $child
                break watch
            }
        }

        # restart once the sources have stopped changing for a moment (an editor may save several files)
        if ($reloading -and (Get-Date) -ge $nextScan) {
            $nextScan = (Get-Date).AddMilliseconds(700)
            $stamp = Get-SourceStamp
            if ($stamp.Key -ne $sources) {
                $sources = $stamp.Key
                $changed = $stamp.Newest
                $restartAt = (Get-Date).AddMilliseconds(700)
            }
            elseif ($restartAt -and (Get-Date) -ge $restartAt) {
                $restartAt = $null
                Say "restarting the API: $changed changed" Yellow
                $children | Where-Object { $_.Name -eq 'api' } | ForEach-Object { Stop-Child $_ }
                $children = @($children | Where-Object { $_.Name -ne 'api' }) + (Start-Api)
            }
        }

        if (-not $announced -and -not ($children | Where-Object { -not $_.Ready })) {
            $announced = $true
            $url = if ($runWeb) { "http://localhost:$WebPort" } else { "http://localhost:$ApiPort" }
            Say "`nIaModelize3d is up: $url   (Ctrl+C stops it)"
            if ($reloading) { Say "Edits apply on their own; the API restarts after server or geometry changes (-NoReload turns that off).`n" DarkGray }
            else { Write-Host '' }
            if ($Open) { Start-Process $url }
        }
        if (-not $busy) { Start-Sleep -Milliseconds 50 }
    }
}
finally {
    # Ctrl+C reached the children as well; give them a moment to shut down cleanly, then end what is left.
    $deadline = (Get-Date).AddSeconds($(if ($failed) { 0 } else { 3 }))
    foreach ($child in $children) {
        $left = [int][Math]::Max(0, ($deadline - (Get-Date)).TotalMilliseconds)
        if (-not $child.Process.WaitForExit($left)) { Stop-Child $child }
    }
    if ($consoleEncoding) { [Console]::OutputEncoding = $consoleEncoding }
}
if ($failed) {
    Say "$($failed.Name) exited with code $($failed.Process.ExitCode); stopped the rest." Red
    exit 1
}
