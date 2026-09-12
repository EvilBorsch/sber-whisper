param(
  [ValidateSet("windows", "macos")]
  [string]$Platform = "windows",
  [ValidateSet("cpu", "gpu")]
  [string]$Variant = "cpu"
)

$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$venv = Join-Path $repo "python\.venv-sidecar"
$distRoot = Join-Path $repo "python\dist"
$distDir = Join-Path $distRoot "sber-whisper-sidecar"
$buildDir = Join-Path $repo "python\build"
$scriptPath = Join-Path $repo "python\asr_service.py"
$torchIndex = "https://download.pytorch.org/whl/cu128"
$torchGpuVersion = "2.8.0+cu128"

if (!(Test-Path $scriptPath)) {
  throw "Missing sidecar source: $scriptPath"
}

if (!(Test-Path $venv)) {
  python -m venv $venv
}

$py = Join-Path $venv "Scripts\python.exe"
if (!(Test-Path $py)) {
  throw "Python executable not found in venv: $py"
}

& $py -m pip install --upgrade pip wheel setuptools

$requirements = Join-Path $repo "python\requirements.txt"
if ($Variant -eq "gpu") {
  # requirements.txt pins CPU torch 2.5.1. Installing it only to replace it with cu128 right away costs
  # an extra 3.5 GB per run, so install CUDA torch first (skipped when already present), then the rest
  # without the torch pins. gigaam itself does not pin torch (only in extras), so the order is safe.
  $installed = & $py -c "import importlib.util as u; print(__import__('torch').__version__ if u.find_spec('torch') else 'none')"
  if ($installed -eq $torchGpuVersion) {
    Write-Output "torch $torchGpuVersion already installed, skipping"
  } else {
    & $py -m pip install --index-url $torchIndex "torch==$torchGpuVersion" "torchaudio==$torchGpuVersion"
  }
  $requirements = [System.IO.Path]::GetTempFileName()
  Get-Content (Join-Path $repo "python\requirements.txt") | Where-Object { $_ -notmatch '^torch(audio)?\s*==' } | Set-Content $requirements
}
& $py -m pip install -r $requirements pyinstaller
if ($Variant -eq "gpu") {
  Remove-Item -Force $requirements
}

# gigaam decodes audio with an external ffmpeg; without it the packaged sidecar fails on the first dictation.
# Resolve it before packaging so a missing ffmpeg/network surfaces before the long PyInstaller run.
$ffmpeg = $null
if ($Platform -eq "windows") {
  $ffmpeg = & (Join-Path $PSScriptRoot "ensure-ffmpeg.ps1")
}

Get-Process sber-whisper-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force

if (Test-Path $distDir) {
  Remove-Item -Recurse -Force $distDir
}
if (Test-Path $buildDir) {
  Remove-Item -Recurse -Force $buildDir
}
New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

$packMode = if ($Variant -eq "gpu") { "--onedir" } else { "--onefile" }
$distPath = if ($Variant -eq "gpu") { $distRoot } else { $distDir }

$cmd = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  $packMode,
  "--name", "sber-whisper-sidecar",
  "--distpath", $distPath,
  "--workpath", $buildDir,
  "--specpath", $buildDir,
  "--collect-all", "gigaam",
  "--collect-data", "sounddevice",
  "--collect-binaries", "sounddevice",
  "--collect-data", "soundfile",
  "--collect-binaries", "soundfile",
  $scriptPath
)

& $py @cmd

$binName = if ($Platform -eq "windows") { "sber-whisper-sidecar.exe" } else { "sber-whisper-sidecar" }
$binPath = if ($Variant -eq "gpu") {
  Join-Path $distDir $binName
} else {
  Join-Path $distDir $binName
}
if (!(Test-Path $binPath)) {
  throw "Sidecar binary was not created: $binPath"
}

if ($ffmpeg) {
  # Next to the exe: CreateProcess searches the calling exe's directory first, so PATH is not needed.
  Copy-Item $ffmpeg (Join-Path $distDir "ffmpeg.exe") -Force
  Write-Output "Bundled ffmpeg: $ffmpeg"
}

Write-Output "Built sidecar: $binPath"
Write-Output "Build variant: $Variant"
