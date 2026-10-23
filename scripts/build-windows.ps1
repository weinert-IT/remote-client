<#
.SYNOPSIS
  Baut wIT-Remote lokal unter Windows (x64): exe-Installer und MSI.

.DESCRIPTION
  Gleiche Schritte und Versionen wie .github/workflows/build.yml (Job "windows"),
  nur ohne GitHub Actions. Einmalig: -Setup installiert die Werkzeuge.

    # PowerShell als Administrator, im Repo-Verzeichnis:
    Set-ExecutionPolicy -Scope Process Bypass
    .\scripts\build-windows.ps1 -Setup                 # Werkzeuge (einmalig, ~30 min)
    .\scripts\build-windows.ps1 -ServerKey "<id_ed25519.pub>" -Build 1

  -RustDeskDir zeigt auf einen schon vorbereiteten Quellbaum (prepare.py lief,
  Bridge-Dateien vorhanden); ohne wird RustDesk geklont und vorbereitet, die
  Bridge-Dateien müssen dann aus -BridgeDir kommen (siehe README.md).

  Ergebnis: out\wIT-Remote-<version>-b<build>-x86_64.{exe,msi}
#>
param(
  [switch]$Setup,
  [string]$ServerKey = "",
  [int]$Build = 1,
  [string]$RustDeskDir = "",
  [string]$BridgeDir = "",
  [string]$WorkDir = "C:\rd-build"
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

# Versionen wie in build.yml / RustDesks flutter-build.yml (1.5.0)
$RustDeskRef   = "1.5.0"
$Version       = "1.5.0"
$RustVersion   = "1.75"
$FlutterVer    = "3.24.5"
$LlvmVersion   = "15.0.6"
$VcpkgCommit   = "9e593bb18ea69cc5095e012465dcd675a822ed0d"
$FlutterDir    = "C:\flutter"
$VcpkgDir      = "C:\vcpkg"
$TopMostCommit = "ecd8d6a139eee76845ea66423fb739af450fda90"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Run($exe, [string[]]$argv) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') -> Exitcode $LASTEXITCODE" }
}
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

if ($Setup) {
  Step "Werkzeuge per winget"
  $pkgs = @(
    @("Git.Git", $null),
    @("Python.Python.3.11", $null),
    @("Rustlang.Rustup", $null),
    @("LLVM.LLVM", $LlvmVersion),
    @("Microsoft.NuGet", $null),
    @("Microsoft.VisualStudio.2022.BuildTools", $null)
  )
  foreach ($p in $pkgs) {
    $a = @("install", "-e", "--id", $p[0], "--accept-package-agreements", "--accept-source-agreements", "--silent")
    if ($p[1]) { $a += @("--version", $p[1]) }
    if ($p[0] -eq "Microsoft.VisualStudio.2022.BuildTools") {
      # C++-Werkzeuge, Windows-SDK, ATL (für die MSI-CustomActions)
      $a += @("--override", "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.ATL --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended")
    }
    & winget @a
  }
  RefreshPath
  [Environment]::SetEnvironmentVariable("LIBCLANG_PATH", "C:\Program Files\LLVM\bin", "Machine")

  Step "Rust $RustVersion"
  Run rustup @("toolchain", "install", $RustVersion, "--profile", "minimal", "-c", "rustfmt")
  Run rustup @("default", $RustVersion)
  Run rustup @("target", "add", "x86_64-pc-windows-msvc")

  Step "Flutter $FlutterVer nach $FlutterDir"
  if (-not (Test-Path "$FlutterDir\bin\flutter.bat")) {
    Run git @("clone", "-q", "--depth", "1", "--branch", $FlutterVer, "https://github.com/flutter/flutter.git", $FlutterDir)
  }
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if ($userPath -notlike "*$FlutterDir\bin*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$FlutterDir\bin", "User")
  }
  RefreshPath
  Run "$FlutterDir\bin\flutter.bat" @("config", "--no-analytics", "--enable-windows-desktop")
  Run "$FlutterDir\bin\flutter.bat" @("precache", "--windows")

  # https://github.com/flutter/flutter/issues/155685: RustDesks eigene Windows-Engine
  Step "RustDesk-Flutter-Engine einsetzen"
  $zip = Join-Path $env:TEMP "windows-x64-release.zip"
  Invoke-WebRequest -Uri https://github.com/rustdesk/engine/releases/download/main/windows-x64-release.zip -OutFile $zip
  $tmp = Join-Path $env:TEMP "windows-x64-release"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  Expand-Archive -Path $zip -DestinationPath $tmp
  Copy-Item -Force -Recurse "$tmp\*" "$FlutterDir\bin\cache\artifacts\engine\windows-x64-release\"

  Step "vcpkg $VcpkgCommit nach $VcpkgDir"
  if (-not (Test-Path "$VcpkgDir\vcpkg.exe")) {
    Run git @("clone", "-q", "https://github.com/microsoft/vcpkg", $VcpkgDir)
    Push-Location $VcpkgDir
    Run git @("checkout", "-q", $VcpkgCommit)
    Run ".\bootstrap-vcpkg.bat" @("-disableMetrics")
    Pop-Location
  }
  [Environment]::SetEnvironmentVariable("VCPKG_ROOT", $VcpkgDir, "Machine")
  Run py @("-3.11", "-m", "pip", "install", "--upgrade", "pillow", "requests")
  Write-Host "`nSetup fertig. Neue PowerShell öffnen, dann ohne -Setup bauen." -ForegroundColor Green
  exit 0
}

RefreshPath
$env:VCPKG_ROOT = $VcpkgDir
$env:LIBCLANG_PATH = "C:\Program Files\LLVM\bin"
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$brand = Get-Content -Raw "$Repo\brand\brand.json" | ConvertFrom-Json
$App = $brand.app_name
$Company = $brand.company

# ---- Quellbaum ----
if (-not $RustDeskDir) {
  if (-not $ServerKey) { throw "-ServerKey fehlt (Inhalt von id_ed25519.pub des ID-Servers)" }
  $RustDeskDir = Join-Path $WorkDir "rustdesk"
  if (Test-Path $RustDeskDir) { Remove-Item -Recurse -Force $RustDeskDir }
  Step "RustDesk $RustDeskRef klonen"
  Run git @("clone", "-q", "--depth", "1", "--branch", $RustDeskRef, "--recurse-submodules", "--shallow-submodules", "https://github.com/rustdesk/rustdesk.git", $RustDeskDir)
  Step "Patches und Branding (prepare.py)"
  $env:SERVER_KEY = $ServerKey
  # prepare.py braucht rsvg-convert für die Icons; unter Windows fehlt es meist.
  # Dann die Icons aus einem unter Linux vorbereiteten Baum übernehmen (README.md).
  Run py @("-3.11", "$Repo\scripts\prepare.py", $RustDeskDir)
}
$RustDeskDir = (Resolve-Path $RustDeskDir).Path
if ($BridgeDir) {
  Step "Bridge-Dateien aus $BridgeDir"
  foreach ($f in @("src\bridge_generated.rs", "src\bridge_generated.io.rs", "flutter\lib\generated_bridge.dart", "flutter\lib\generated_bridge.freezed.dart")) {
    Copy-Item -Force (Join-Path $BridgeDir $f) (Join-Path $RustDeskDir $f)
  }
}
if (-not (Test-Path "$RustDeskDir\src\bridge_generated.rs")) { throw "Bridge-Dateien fehlen (src\bridge_generated.rs), siehe README.md" }
if ($ServerKey) {
  # Schlüssel nachtragen, falls der Baum mit einem Platzhalter vorbereitet wurde.
  $cfgPath = "$RustDeskDir\res\brand\custom.json"
  $cfg = Get-Content -Raw $cfgPath | ConvertFrom-Json
  $cfg."override-settings".key = $ServerKey
  [IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
}
$key = ((Get-Content -Raw "$RustDeskDir\res\brand\custom.json" | ConvertFrom-Json)."override-settings").key
if (-not $key -or $key -eq "placeholder") { throw "res\brand\custom.json hat keinen echten Server-Schlüssel: -ServerKey angeben" }

Push-Location $RustDeskDir
try {
  Step "Flutter patchen (Dropdown-Filter, wie RustDesk-CI)"
  Push-Location $FlutterDir
  & git apply --check "$RustDeskDir\.github\patches\flutter_3.24.4_dropdown_menu_enableFilter.diff" 2>$null
  if ($LASTEXITCODE -eq 0) { Run git @("apply", "$RustDeskDir\.github\patches\flutter_3.24.4_dropdown_menu_enableFilter.diff") }
  Pop-Location

  Step "vcpkg-Abhängigkeiten (x64-windows-static; beim ersten Mal ~1 h wegen ffmpeg)"
  $env:VCPKG_DEFAULT_HOST_TRIPLET = "x64-windows-static"
  Run "$VcpkgDir\vcpkg.exe" @("install", "--triplet", "x64-windows-static", "--x-install-root=$VcpkgDir\installed")

  Step "Client bauen (build.py --flutter --hwcodec --vram)"
  $env:BRAND_BUILD = "$Build"
  Run py @("-3.11", ".\build.py", "--portable", "--flutter", "--skip-portable-pack", "--hwcodec", "--vram")

  Step "dist zusammenstellen"
  $dist = Join-Path $RustDeskDir "dist"
  if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
  Copy-Item -Recurse ".\flutter\build\windows\x64\runner\Release" $dist
  # Dienst, taskkill und Verknüpfungen erwarten <App-Name>.exe.
  Move-Item "$dist\rustdesk.exe" "$dist\$App.exe"

  Invoke-WebRequest -Uri https://github.com/rustdesk-org/rdev/releases/download/usbmmidd_v2/usbmmidd_v2.zip -OutFile usbmmidd_v2.zip
  if (Test-Path usbmmidd_v2) { Remove-Item -Recurse -Force usbmmidd_v2 }
  Expand-Archive usbmmidd_v2.zip -DestinationPath .
  Remove-Item -Recurse usbmmidd_v2\Win32
  Remove-Item "usbmmidd_v2\deviceinstaller64.exe", "usbmmidd_v2\deviceinstaller.exe", "usbmmidd_v2\usbmmidd.bat"
  Move-Item usbmmidd_v2 "$dist\usbmmidd_v2"

  try {
    Invoke-WebRequest -Uri https://github.com/rustdesk/hbb_common/releases/download/driver/rustdesk_printer_driver_v4-1.4.zip -OutFile drv.zip
    Invoke-WebRequest -Uri https://github.com/rustdesk/hbb_common/releases/download/driver/printer_driver_adapter.zip -OutFile adapter.zip
    Invoke-WebRequest -Uri https://github.com/rustdesk/hbb_common/releases/download/driver/sha256sums -OutFile sha256sums
    $want1 = (Select-String -Path .\sha256sums -Pattern '^([a-fA-F0-9]{64}) \*rustdesk_printer_driver_v4-1.4\.zip$').Matches.Groups[1].Value
    $want2 = (Select-String -Path .\sha256sums -Pattern '^([a-fA-F0-9]{64}) \*printer_driver_adapter\.zip$').Matches.Groups[1].Value
    if ($want1 -eq (Get-FileHash drv.zip).Hash -and $want2 -eq (Get-FileHash adapter.zip).Hash) {
      Expand-Archive -Force drv.zip -DestinationPath .
      New-Item -ItemType Directory -Force "$dist\drivers" | Out-Null
      Move-Item -Force .\rustdesk_printer_driver_v4-1.4 "$dist\drivers\RustDeskPrinterDriver"
      Expand-Archive -Force adapter.zip -DestinationPath .
      Move-Item -Force .\printer_driver_adapter.dll $dist
    } else { Write-Warning "Druckertreiber: Prüfsumme passt nicht, ohne Treiber weiter." }
  } catch { Write-Warning "Druckertreiber übersprungen: $_" }

  Step "WindowInjection.dll (Datenschutzmodus)"
  $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
  $msbuild = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
  if (-not (Test-Path RustDeskTempTopMostWindow)) {
    Run git @("clone", "-q", "https://github.com/rustdesk-org/RustDeskTempTopMostWindow", "RustDeskTempTopMostWindow")
  }
  Push-Location RustDeskTempTopMostWindow
  Run git @("checkout", "-q", $TopMostCommit)
  Run $msbuild @("WindowInjection\WindowInjection.vcxproj", "-p:Configuration=Release", "-p:Platform=x64", "/p:TargetVersion=Windows10")
  Copy-Item "WindowInjection\x64\Release\WindowInjection.dll" $dist
  Pop-Location

  $runnerRes = Get-ChildItem -Recurse -Filter Runner.res -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($runnerRes) { Copy-Item -Force $runnerRes.FullName ".\libs\portable\Runner.res" }

  $out = Join-Path $Repo "out"
  New-Item -ItemType Directory -Force $out | Out-Null
  $base = "$App-$Version-b$Build-x86_64"

  Step "Installer (exe)"
  (Get-Content res\manifest.xml) | Where-Object { $_ -notmatch "dpiAware" } | Set-Content res\manifest.xml
  Push-Location libs\portable
  Run py @("-3.11", "-m", "pip", "install", "-r", "requirements.txt")
  Run py @("-3.11", ".\generate.py", "-f", "..\..\dist\", "-o", ".", "-e", "..\..\dist\$App.exe")
  Pop-Location
  Copy-Item -Force ".\target\release\rustdesk-portable-packer.exe" "$out\$base.exe"

  Step "Installer (msi)"
  Push-Location res\msi
  Run py @("-3.11", "preprocess.py", "--arp", "-d", "..\..\dist", "--app-name", $App, "--manufacturer", $Company, "--revision-version", "$Build")
  Run nuget @("restore", "msi.sln")
  Run $msbuild @("msi.sln", "-p:Configuration=Release", "-p:Platform=x64", "/p:TargetVersion=Windows10")
  $msi = Get-ChildItem .\Package\bin\*\Release\en-us\Package.msi | Select-Object -First 1
  Copy-Item -Force $msi.FullName "$out\$base.msi"
  Pop-Location

  Write-Host "`nFertig:" -ForegroundColor Green
  Get-ChildItem $out | Format-Table Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
} finally {
  Pop-Location
}
