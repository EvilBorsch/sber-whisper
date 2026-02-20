param(
  [ValidateSet("windows", "macos")]
  [string]$Platform = "windows"
)

$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$venv = Join-Path $repo "python\.venv-sidecar"
$distRoot = Join-Path $repo "python\dist"
$distDir = Join-Path $distRoot "sber-whisper-sidecar"
$buildDir = Join-Path $repo "python\build"
$scriptPath = Join-Path $repo "python\asr_service.py"
$gigaamRef = "gigaam @ git+https://github.com/salute-developers/GigaAM.git@94082238aa5cabbd4bdc28e755100a1922a90d43"

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
& $py -m pip install -r (Join-Path $repo "python\requirements.txt") pyinstaller
& $py -m pip install --force-reinstall --no-deps --no-cache-dir $gigaamRef

Get-Process sber-whisper-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force

if (Test-Path $distDir) {
  Remove-Item -Recurse -Force $distDir
}
if (Test-Path $buildDir) {
  Remove-Item -Recurse -Force $buildDir
}
New-Item -ItemType Directory -Force -Path $distRoot | Out-Null

$cmd = @(
  "-m", "PyInstaller",
  "--noconfirm",
  "--clean",
  "--onedir",
  "--name", "sber-whisper-sidecar",
  "--distpath", $distRoot,
  "--workpath", $buildDir,
  "--specpath", $buildDir,
  "--collect-all", "gigaam",
  "--collect-all", "torch",
  "--collect-all", "torchaudio",
  "--collect-data", "sounddevice",
  "--collect-binaries", "sounddevice",
  "--collect-data", "soundfile",
  "--collect-binaries", "soundfile",
  $scriptPath
)

& $py @cmd

$binName = if ($Platform -eq "windows") { "sber-whisper-sidecar.exe" } else { "sber-whisper-sidecar" }
$binPath = Join-Path $distDir $binName
if (!(Test-Path $binPath)) {
  throw "Sidecar binary was not created: $binPath"
}

Write-Output "Built sidecar: $binPath"
