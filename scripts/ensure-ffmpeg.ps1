<#
Locates ffmpeg.exe to bundle next to the sidecar and prints its path.
gigaam decodes audio by running an external ffmpeg; without it every dictation fails with
"Transcription failed: [WinError 2]".
Lookup order: $env:FFMPEG_EXE -> ffmpeg on PATH -> python/.ffmpeg-cache -> download the gyan.dev essentials build.
#>
param(
  [string]$CacheDir = (Join-Path $PSScriptRoot "..\python\.ffmpeg-cache")
)

$ErrorActionPreference = "Stop"

if ($env:FFMPEG_EXE) {
  if (!(Test-Path $env:FFMPEG_EXE)) { throw "FFMPEG_EXE points to a missing file: $env:FFMPEG_EXE" }
  return (Resolve-Path $env:FFMPEG_EXE).Path
}

$onPath = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
if ($onPath) { return $onPath.Source }

$cached = Get-ChildItem $CacheDir -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cached) { return $cached.FullName }

# gyan.dev sits behind Cloudflare and drops connections now and then, so retry and fall back to the BtbN GitHub build.
$urls = @(
  "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
  "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"
)
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$zip = Join-Path $CacheDir "ffmpeg.zip"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"   # the Invoke-WebRequest progress bar slows the download down a lot
$downloaded = $false
foreach ($url in $urls) {
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    Write-Host "ffmpeg not found on PATH, downloading $url (attempt $attempt)"
    try {
      Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -UserAgent "sber-whisper-build"
      $downloaded = $true
      break
    } catch {
      Write-Host "  download failed: $($_.Exception.Message)"
      Start-Sleep -Seconds (5 * $attempt)
    }
  }
  if ($downloaded) { break }
}
if (!$downloaded) { throw "Could not download ffmpeg from any source. Install ffmpeg or set FFMPEG_EXE." }
Expand-Archive -Path $zip -DestinationPath $CacheDir -Force
Remove-Item -Force $zip

$downloaded = Get-ChildItem $CacheDir -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if (!$downloaded) { throw "ffmpeg.exe not found in the downloaded archive" }
return $downloaded.FullName
