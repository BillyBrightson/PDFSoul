<#
  Build the Windows installer: dist\PDFSoul-By-Billy-Setup-<version>.exe

  Needs: uv, Inno Setup 6 (iscc on PATH or in its default folder), and Ghostscript installed
  (choco install ghostscript) so its runtime can be bundled into bin\.

  Usage:  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building PDFSoul $Version"

# 1. Bundle Ghostscript (exe + dll; its resources are compiled into the dll).
$GsBin = Get-ChildItem "C:\Program Files\gs\gs*\bin" -Directory -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if ($GsBin) {
    Copy-Item "$($GsBin.FullName)\gswin64c.exe", "$($GsBin.FullName)\gsdll64.dll" -Destination bin -Force
    Write-Host "Bundled Ghostscript from $($GsBin.FullName)"
} else {
    Write-Warning "Ghostscript not found - the build will fall back to MuPDF compression."
}

# 2. Stamp the version into the Windows version resource.
$parts = ($Version.Split(".") + @("0", "0", "0"))[0..3] -join ", "
(Get-Content packaging\version_info.txt -Raw) `
    -replace "filevers=\([^)]*\)", "filevers=($parts)" `
    -replace "prodvers=\([^)]*\)", "prodvers=($parts)" `
    -replace "'FileVersion', '[^']*'", "'FileVersion', '$Version'" `
    -replace "'ProductVersion', '[^']*'", "'ProductVersion', '$Version'" |
    Set-Content packaging\version_info.txt -Encoding utf8

# 3. Freeze.
uv sync --group build
uv run pyinstaller packaging\pdfsoul.spec --noconfirm --clean --distpath dist --workpath build

# 4. `pdfsoul` in a terminal should run the CLI: Windows prefers .com over .exe.
Move-Item dist\PDFSoul\pdfsoul-cli.exe dist\PDFSoul\pdfsoul.com -Force

# 5. Smoke-test the frozen CLI before packaging it.
& dist\PDFSoul\pdfsoul.com --version
if ($LASTEXITCODE -ne 0) { throw "Frozen CLI failed to start" }

# 6. Installer.
$Iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $Iscc) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $Iscc "/DAppVersion=$Version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$Size = [math]::Round((Get-Item "dist\PDFSoul-By-Billy-Setup-$Version.exe").Length / 1MB, 1)
Write-Host "Done: dist\PDFSoul-By-Billy-Setup-$Version.exe ($Size MB)"
