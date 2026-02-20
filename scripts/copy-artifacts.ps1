param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("windows", "macos")]
  [string]$Platform
)

$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$outDir = Join-Path $repo "dist\releases"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

if ($Platform -eq "windows") {
  $src = Join-Path $repo "src-tauri\target\release\bundle\nsis"
  Get-ChildItem -Path $src -Filter *.exe -File | ForEach-Object {
    Copy-Item -Force $_.FullName (Join-Path $outDir $_.Name)
  }
}

if ($Platform -eq "macos") {
  $src = Join-Path $repo "src-tauri/target/release/bundle/dmg"
  Get-ChildItem -Path $src -Filter *.dmg -File | ForEach-Object {
    Copy-Item -Force $_.FullName (Join-Path $outDir $_.Name)
  }
}

Write-Output "Artifacts copied to $outDir"
