param(
  [ValidateSet("windows", "macos")]
  [string]$Platform = "windows"
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venv = Join-Path $repo "python\.venv-sidecar"
$distRoot = Join-Path $repo "python\dist"
$distDir = Join-Path $distRoot "sber-whisper-sidecar"
$buildDir = Join-Path $repo "python\build"
$scriptPath = Join-Path $repo "python\asr_service.py"

if (!(Test-Path $scriptPath)) { throw "Missing sidecar source: $scriptPath" }

# Check the absolute targets before recursively clearing generated files.
$pythonRoot = [System.IO.Path]::GetFullPath((Join-Path $repo "python")) + [System.IO.Path]::DirectorySeparatorChar
foreach ($target in @($distDir, $buildDir)) {
  if (![System.IO.Path]::GetFullPath($target).StartsWith($pythonRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Build output must stay inside $pythonRoot"
  }
}

if (!(Test-Path $venv)) {
  python -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "Failed to create sidecar venv" }
}

$py = Join-Path $venv "Scripts\python.exe"
if (!(Test-Path $py)) { throw "Python executable not found in venv: $py" }

& $py -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Failed to update build tools" }
$requirementsName = if ($Platform -eq "windows") { "requirements-windows.txt" } else { "requirements.txt" }
& $py -m pip install -r (Join-Path $repo "python\$requirementsName") pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Failed to install sidecar dependencies" }

if ($Platform -eq "windows") {
  & $py -c "import torch, torchaudio; assert torch.__version__ == '2.8.0+cpu' and torchaudio.__version__ == '2.8.0+cpu' and torch.version.cuda is None, 'Windows requires CPU-only PyTorch'"
  if ($LASTEXITCODE -ne 0) { throw "CPU-only dependency verification failed" }
}

# Resolve ffmpeg before packaging: GigaAM needs it for the first dictation.
$ffmpeg = $null
if ($Platform -eq "windows") {
  $ffmpeg = & (Join-Path $PSScriptRoot "ensure-ffmpeg.ps1")
}

if (Test-Path $distDir) { Remove-Item -LiteralPath $distDir -Recurse -Force }
if (Test-Path $buildDir) { Remove-Item -LiteralPath $buildDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $distRoot | Out-Null

# A directory bundle starts without extracting torch on every process launch.
$cmd = @(
  "-m", "PyInstaller",
  "--noconfirm", "--clean", "--onedir",
  "--name", "sber-whisper-sidecar",
  "--distpath", $distRoot,
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
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$binName = if ($Platform -eq "windows") { "sber-whisper-sidecar.exe" } else { "sber-whisper-sidecar" }
$binPath = Join-Path $distDir $binName
if (!(Test-Path $binPath)) { throw "Sidecar binary was not created: $binPath" }

if ($ffmpeg) {
  Copy-Item -LiteralPath $ffmpeg -Destination (Join-Path $distDir "ffmpeg.exe") -Force
  Write-Output "Bundled ffmpeg: $ffmpeg"
}
Write-Output "Built sidecar: $binPath (CPU)"
