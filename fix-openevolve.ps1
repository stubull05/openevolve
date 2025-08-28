<#
.SYNOPSIS
  Fix OpenEvolve TemplateManager constructor mismatch and ensure Python loads your workspace (sitecustomize) reliably.

.KEY CHANGES vs v1
  - Fixed PowerShell quoting bug when composing export line.
  - Added robust fallback: write a .pth file into the venv's site-packages so Python always adds your workspace to sys.path (Windows & Linux).
  - The entrypoint.sh injection now uses a Linux-safe check and never interpolates PowerShell variables into bash syntax.

.PARAMETERS
  See below. Typical Windows usage:
    pwsh -File .\fix-openevolve.ps1 `
      -Workspace "C:\Source\GIT\openevolve" `
      -Venv "C:\Source\GIT\openevolve\.venv" `
      -LocalOpenevolve "C:\Source\GIT\openevolve\openevolve" `
      -PatchSitePackages `
      -EditableInstall:$false
#>

param(
  [string]$Workspace = "/workspace",
  [string]$Venv = "/workspace/.venv",
  [string]$LocalOpenevolve = "/workspace/openevolve",
  [switch]$EditableInstall,
  [switch]$PatchSitePackages = $true,
  [string]$EntryPointSh = "/workspace/entrypoint.sh",
  [string]$Run = "",
  [switch]$NoVerify
)

function Write-Info($msg){ Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg){ Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg){ Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Get-PythonExe {
  $linuxPath = Join-Path $Venv "bin/python"
  $winPath   = Join-Path $Venv "Scripts/python.exe"
  if (Test-Path $linuxPath) { return $linuxPath }
  if (Test-Path $winPath)   { return $winPath }
  Write-Warn "Could not find venv python in '$Venv'. Falling back to 'python' on PATH."
  return "python"
}

function Invoke-Py([string]$Code) {
  $py = Get-PythonExe
  $tmp = [System.IO.Path]::GetTempFileName() + ".py"
  Set-Content -Path $tmp -Encoding UTF8 -NoNewline -Value $Code
  try {
    & $py $tmp
    return $LASTEXITCODE
  } finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $tmp
  }
}

# 1) Create / update sitecustomize.py shim in $Workspace
$siteCustomizePath = Join-Path $Workspace "sitecustomize.py"
$shim = @'
# Auto-loaded if its directory is on sys.path.
# Accept both 'custom_template_dir' and 'template_dir' for TemplateManager.__init__.
import importlib, inspect

def _patch(mod_name):
    try:
        m = importlib.import_module(mod_name)
        TM = m.TemplateManager
        sig = inspect.signature(TM.__init__)
        if "custom_template_dir" not in sig.parameters:
            orig = TM.__init__
            def __init__(self, *args, **kwargs):
                if "custom_template_dir" in kwargs and "template_dir" not in kwargs and not args:
                    kwargs["template_dir"] = kwargs.pop("custom_template_dir")
                return orig(self, *args, **kwargs)
            TM.__init__ = __init__
    except Exception:
        pass

for name in ("openevolve.prompt.templates", "openevolve.prompt.template_manager"):
    _patch(name)
'@

Write-Info "Writing shim: $siteCustomizePath"
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
Set-Content -Path $siteCustomizePath -Encoding UTF8 -Value $shim

# 2) Ensure the workspace is on sys.path via a .pth file in site-packages
Write-Info "Ensuring site-packages contains a .pth pointing to your workspace..."
$pthLocator = @'
import sys, site
from sysconfig import get_paths
paths = get_paths()
sp = paths.get("purelib", None)
if not sp:
    # Fallbacks
    sps = site.getsitepackages()
    sp = sps[0] if sps else None
print(sp or "")
'@
$tmpOut = New-TemporaryFile
$null = Invoke-Py $pthLocator 2>&1 | Tee-Object -Variable pyOut
$sitePackages = ($pyOut | Where-Object { $_ -match "^([A-Za-z]:)?/.+" -or $_ -match "^[A-Za-z]:\\.*" } | Select-Object -First 1)
if (-not $sitePackages) {
  Write-Warn "Could not resolve site-packages. Output:`n$($pyOut -join "`n")"
} else {
  Write-Info "site-packages: $sitePackages"
  $pthFile = Join-Path $sitePackages "workspace_path.pth"
  # Write the raw workspace path so Python adds it to sys.path
  Set-Content -Path $pthFile -Encoding UTF8 -NoNewline -Value $Workspace
  Write-Info "Wrote .pth: $pthFile"
}

# 3) Optionally, inject a safe bash line into entrypoint.sh (Linux containers)
if (Test-Path $EntryPointSh) {
  Write-Info "Checking $EntryPointSh for PYTHONPATH export..."
  $content = Get-Content -Path $EntryPointSh -Raw
  if ($content -notmatch 'export\s+PYTHONPATH=.*?\$PYTHONPATH') {
    # Avoid PowerShell interpolation by using single-quoted string
    $line = 'if [ -d "/workspace" ]; then export PYTHONPATH="/workspace:${PYTHONPATH}"; fi'
    if ($content -match '^#!.*') {
      $content = $content -replace "^(#!.*\r?\n)", "`$1$line`n"
    } else {
      $content = "$line`n$content"
    }
    Set-Content -Path $EntryPointSh -Encoding UTF8 -Value $content
    Write-Info "Inserted Linux-safe PYTHONPATH export."
  } else {
    Write-Info "PYTHONPATH export already present."
  }
} else {
  Write-Warn "EntryPointSh not found at $EntryPointSh (skipping entrypoint injection)."
}

# 4) Optionally patch the live site-packages sampler.py
if ($PatchSitePackages) {
  Write-Info "Locating live openevolve.prompt.sampler in site-packages..."
  $pyCode = @'
import importlib
sm = importlib.import_module("openevolve.prompt.sampler")
print(sm.__file__)
'@
  $null = Invoke-Py $pyCode 2>&1 | Tee-Object -Variable pyOut2
  $samplerPath = ($pyOut2 | Where-Object {$_ -match "^/|^[A-Za-z]:\\"} | Select-Object -First 1)
  if (-not $samplerPath) {
    Write-Warn "Could not resolve sampler.py path. Output:`n$($pyOut2 -join "`n")"
  } else {
    Write-Info "Found sampler.py at: $samplerPath"
    if (Test-Path $samplerPath) {
      $orig = Get-Content -Path $samplerPath -Raw
      $backupPath = "$samplerPath.bak_{0:yyyyMMdd_HHmmss}" -f (Get-Date)
      Copy-Item -Path $samplerPath -Destination $backupPath -Force
      $patched = $orig -replace 'custom_template_dir\s*=\s*config\.template_dir','template_dir=config.template_dir'
      $patched = $patched -replace 'TemplateManager\(\s*custom_template_dir\s*=\s*','TemplateManager(template_dir='
      if ($patched -ne $orig) {
        Set-Content -Path $samplerPath -Encoding UTF8 -Value $patched
        Write-Info "Patched sampler.py. Backup at $backupPath"
      } else {
        Write-Info "No matching text to patch in sampler.py (maybe already patched)."
      }
    } else {
      Write-Warn "sampler.py path not found on disk: $samplerPath"
    }
  }
}

# 5) Optionally reinstall local openevolve from $LocalOpenevolve
if (Test-Path $LocalOpenevolve) {
  Write-Info "Local openevolve detected at: $LocalOpenevolve"
  $py = Get-PythonExe
  Write-Info "Uninstalling installed openevolve wheel (if any)..."
  & $py -m pip uninstall -y openevolve | Out-Null
  if ($EditableInstall) {
    Write-Info "Installing local openevolve in editable mode..."
    & $py -m pip install -e $LocalOpenevolve --no-cache-dir
  } else {
    Write-Info "Installing local openevolve (non-editable)..."
    & $py -m pip install $LocalOpenevolve --no-cache-dir
  }
} else {
  Write-Warn "LocalOpenevolve not found at $LocalOpenevolve (skipping local reinstall)."
}

# 6) Verification
if (-not $NoVerify) {
  Write-Info "Verification: import locations and TemplateManager signature"
  $verify = @'
import importlib, inspect, sys
def show(mod):
    m = importlib.import_module(mod)
    print(f"{mod} -> {getattr(m, '__file__', 'n/a')}")

show("openevolve.prompt.sampler")
for mod in ("openevolve.prompt.templates","openevolve.prompt.template_manager"):
    try:
        m = importlib.import_module(mod)
        print(f"{mod} -> {getattr(m, '__file__', 'n/a')}")
        print("TemplateManager.__init__:", inspect.signature(m.TemplateManager.__init__))
    except Exception as e:
        print(f"{mod} import failed:", e)
'@
  Invoke-Py $verify | Out-Null
}

# 7) Optional run (Linux containers only)
if ($Run) {
  Write-Info "Running: $Run"
  try {
    & /bin/sh -lc "$Run"
  } catch {
    Write-Warn "Could not invoke /bin/sh. If you're on Windows host, run your app manually after this script."
  }
}

Write-Info "Done."
