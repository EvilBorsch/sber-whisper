param(
  [string]$Name = "sber-whisper-gpu-portable-win-x64"
)

$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$exe = Join-Path $repo "src-tauri\target\release\sber-whisper.exe"
$sidecar = Join-Path $repo "python\dist\sber-whisper-sidecar"
$outRoot = Join-Path $repo "artifacts\releases"
$outDir = Join-Path $outRoot $Name
$zip = "$outDir.zip"

foreach ($required in @($exe, (Join-Path $sidecar "sber-whisper-sidecar.exe"), (Join-Path $sidecar "ffmpeg.exe"))) {
  if (!(Test-Path $required)) { throw "Missing build output: $required" }
}

New-Item -ItemType Directory -Force -Path $outRoot | Out-Null
if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
if (Test-Path $zip) { Remove-Item -Force $zip }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Copy-Item $exe $outDir
# Same resource set the NSIS installer ships (bundle.resources in tauri.conf.json).
New-Item -ItemType Directory -Force -Path (Join-Path $outDir "_up_\python") | Out-Null
Copy-Item (Join-Path $repo "python\asr_service.py") (Join-Path $outDir "_up_\python")
Copy-Item (Join-Path $repo "python\requirements.txt") (Join-Path $outDir "_up_\python")
# The app looks for <exe dir>\sber-whisper-sidecar\sber-whisper-sidecar.exe (find_sidecar_binary in lib.rs).
# robocopy: 4+ GB of small files, Copy-Item -Recurse is noticeably slower at this size.
& robocopy $sidecar (Join-Path $outDir "sber-whisper-sidecar") /E /NFL /NDL /NJH /NJS /NP /MT:8 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

$sizeGb = [math]::Round(((Get-ChildItem $outDir -Recurse -File | Measure-Object Length -Sum).Sum / 1GB), 2)
Write-Output "Portable folder: $outDir ($sizeGb GB)"

if ($env:SKIP_ZIP -eq "1") {
  Write-Output "SKIP_ZIP=1, zip not created"
  exit 0
}

# bsdtar ships with Windows 10+ and writes zip64; Compress-Archive from PowerShell 5.1 breaks on archives above 2 GB.
Push-Location $outRoot
try {
  & tar -a -cf $zip $Name
  if ($LASTEXITCODE -ne 0) { throw "tar failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}
Write-Output "Portable zip: $zip"
