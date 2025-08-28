
Param(
    [string]$OpenEvolveRoot = "C:\Source\GIT\openevolve",
    [string]$TargetRepoHostPath = "C:\Source\GIT\Rysky",
    [string]$OpenEvolveSourceHostPath = "C:\Source\GIT\OpenEvolve",
    [string]$OllamaBaseUrl = "http://host.docker.internal:11434/v1",
    [string]$OllamaModel = "codellama:7b"
)

$ErrorActionPreference = "Stop"

function Ensure-Folder($path) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

Write-Host "==> Preparing folders..."
Ensure-Folder -path (Split-Path $OpenEvolveRoot -Parent)
Ensure-Folder -path $OpenEvolveRoot
Ensure-Folder -path (Split-Path $TargetRepoHostPath -Parent)
Ensure-Folder -path (Split-Path $OpenEvolveSourceHostPath -Parent)

# Validate/maybe clone target repo if missing
if (-not (Test-Path $TargetRepoHostPath)) {
    Write-Host "Target repo not found at $TargetRepoHostPath. Attempting to clone stubull05/Rysky..."
    try {
        git --version | Out-Null
        Push-Location (Split-Path $TargetRepoHostPath -Parent)
        git clone https://github.com/stubull05/Rysky (Split-Path $TargetRepoHostPath -Leaf)
        Pop-Location
    } catch {
        Write-Warning "Clone failed. Ensure the repo path exists or update -TargetRepoHostPath."
    }
}

# Warn if OpenEvolve source path is missing
if (-not (Test-Path $OpenEvolveSourceHostPath)) {
    Write-Warning "OpenEvolve source not found at $OpenEvolveSourceHostPath. The container will try to use any openevolve-run available via pip; otherwise install it or update -OpenEvolveSourceHostPath."
}

# Copy bundle files into OpenEvolveRoot
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "==> Copying bundle from $ScriptDir to $OpenEvolveRoot ..."
robocopy "$ScriptDir" "$OpenEvolveRoot" /E /NFL /NDL /NJH /NJS /NC /NS /XD ".git" "node_modules" | Out-Null

# Write .env for docker compose variables
$envFile = Join-Path $OpenEvolveRoot ".env"
@"
TARGET_REPO_HOST_PATH=$TargetRepoHostPath
OPENEVOLVE_SRC_HOST_PATH=$OpenEvolveSourceHostPath
OLLAMA_BASE_URL=$OllamaBaseUrl
OLLAMA_MODEL=$OllamaModel
"@ | Set-Content -Path $envFile -Encoding UTF8

# Kick off Docker
Write-Host "==> Building and running Docker Compose..."
Push-Location $OpenEvolveRoot
docker compose down --remove-orphans | Out-Null
docker compose build
docker compose up --abort-on-container-exit
$exitCode = $LASTEXITCODE
Pop-Location

if ($exitCode -ne 0) {
    throw "Docker compose exited with code $exitCode"
} else {
    Write-Host "✅ OpenEvolve container finished (stop occurred). To run again, re-execute this script."
}
