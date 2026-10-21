"""Getting a Windows Space ready for Hermes: Git for Windows, Python and the Git Bash drive folders.

Hermes runs on Windows through Git Bash (it needs Git for Windows and stops with "Hermes needs bash"
without it). Its file tools, search, background processes and code execution all build Unix shell
commands, so this plugin runs them in Git Bash too, exactly as Hermes does on a Windows PC. A Windows
Space that has no Git for Windows (the Cua Windows image has it; a bare Windows machine does not)
gets it installed once, when Hermes first connects.

The install uses the pinned official installer, checked against its SHA-256, and falls back to
`winget`. Nothing in Hermes is replaced: the plugin only prepares the machine.
"""

from __future__ import annotations

GIT_VERSION = "2.56.0.2"
GIT_TAG = "v2.56.0.windows.2"
GIT_SHA256 = {
    "64-bit": "52188f917b378f00c70ec136bcf090005f30d44fbc4eba0bce759cc6592d60f6",
    "arm64": "b9ced78ce371577dc966f50ae571909d6731e36d31065d35c8efa21544c58bf0",
}
PY_VERSION = "3.13.17"
PY_SHA256 = {
    "64-bit": "5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190",
    "arm64": "3089a1977c32b26f5078e5a7d0285b7a861b8c96250c5dac3b6af59fbe9e9a75",
}
INSTALL_TIMEOUT_S = 1200

FIX = "Install Git for Windows in the Space (in its PowerShell: `winget install --id Git.Git -e`), then start Hermes again."

_INSTALL = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
function Find-Bash {
  $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs')) | Where-Object { $_ }
  foreach ($r in $roots) {
    $c = Join-Path $r 'Git\bin\bash.exe'
    if (Test-Path -LiteralPath $c) { return $c }
  }
  return $null
}
function Done($bash) {
  $v = (& $bash --version 2>&1 | Select-Object -First 1)
  if ($LASTEXITCODE -ne 0) { throw "bash --version failed" }
  Write-Output "hermes-cua-git-ok=$bash"
  Write-Output "hermes-cua-git-version=$v"
  exit 0
}
$have = Find-Bash
if ($have) { Done $have }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { '64-bit' }
$sha = @{ '64-bit' = '@SHA64@'; 'arm64' = '@SHAARM@' }[$arch]
$name = "Git-@VERSION@-$arch.exe"
$exe = Join-Path ([IO.Path]::GetTempPath()) $name
$log = @()
try {
  Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/git-for-windows/git/releases/download/@TAG@/$name" -OutFile $exe
  $got = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLower()
  if ($got -ne $sha) { throw "installer checksum mismatch ($got)" }
  $args = @('/VERYSILENT', '/NORESTART', '/SP-', '/SUPPRESSMSGBOXES', '/NOCANCEL', '/COMPONENTS=icons,ext\reg\shellhere,assoc,assoc_sh')
  if (-not $admin) { $args += '/CURRENTUSER' }
  $p = Start-Process -FilePath $exe -ArgumentList $args -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "installer exit code $($p.ExitCode)" }
} catch {
  $log += "installer: $($_.Exception.Message)"
} finally {
  Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue
}
$have = Find-Bash
if (-not $have -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  try {
    & winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    $log += "winget exit code $LASTEXITCODE"
  } catch { $log += "winget: $($_.Exception.Message)" }
  $have = Find-Bash
}
if ($have) { Done $have }
Write-Output ("hermes-cua-git-failed=" + ($log -join '; '))
exit 3
"""


_INSTALL_PY = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
function Find-Py {
  foreach ($n in 'python3', 'python') {
    $c = Get-Command $n -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*\WindowsApps\*' } | Select-Object -First 1
    if ($c) { return $c.Source }
  }
  foreach ($r in @($env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs\Python'))) {
    if (-not $r) { continue }
    $c = Get-ChildItem -Path $r -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'python.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($c) { return $c }
  }
  return $null
}
$have = Find-Py
if ($have) { Write-Output "hermes-cua-python-ok=$have"; exit 0 }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { '64-bit' }
$file = if ($arch -eq 'arm64') { 'python-@PYV@-arm64.exe' } else { 'python-@PYV@-amd64.exe' }
$sha = @{ '64-bit' = '@SHA64@'; 'arm64' = '@SHAARM@' }[$arch]
$exe = Join-Path ([IO.Path]::GetTempPath()) $file
try {
  Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/@PYV@/$file" -OutFile $exe
  $got = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLower()
  if ($got -ne $sha) { throw "installer checksum mismatch ($got)" }
  $code = 1
  foreach ($all in @([int]$admin, 0)) {
    $a = @('/quiet', "InstallAllUsers=$all", 'PrependPath=1', 'Include_test=0', 'Include_launcher=0', 'Include_doc=0')
    $p = Start-Process -FilePath $exe -ArgumentList $a -Wait -PassThru
    $code = $p.ExitCode
    if ($code -eq 0 -or (Find-Py)) { $code = 0; break }
  }
  if ($code -ne 0) { throw "installer exit code $code" }
} catch {
  Write-Output ("hermes-cua-python-failed=" + $_.Exception.Message)
  exit 3
} finally {
  Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue
}
$have = Find-Py
if ($have) { Write-Output "hermes-cua-python-ok=$have"; exit 0 }
Write-Output "hermes-cua-python-failed=installed but python.exe was not found"
exit 3
"""


def install_python_script() -> str:
    return (
        _INSTALL_PY.replace("@PYV@", PY_VERSION)
        .replace("@SHA64@", PY_SHA256["64-bit"])
        .replace("@SHAARM@", PY_SHA256["arm64"])
        .lstrip("\n")
    )


# Hermes names Windows files the Git Bash way (`/c/Users/me/a.txt`): that is the only absolute-path form
# its file tools accept when Hermes itself does not run on Windows. Bash understands it, but a native
# Windows program (the Python Hermes runs for deleting files, for example) reads `/c/Users` as
# `C:\c\Users`. A junction `C:\c` -> `C:\` (one per fixed drive, on the system drive) makes both mean the
# same folder. A junction is a folder alias, not a copy; recursive tools do not follow it.
_BRIDGE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$sys = $env:SystemDrive + '\'
foreach ($d in [IO.DriveInfo]::GetDrives() | Where-Object { $_.DriveType -eq 'Fixed' -and $_.IsReady }) {
  $letter = $d.Name.Substring(0, 1).ToLower()
  $link = Join-Path $sys $letter
  if (-not (Test-Path -LiteralPath $link)) {
    & cmd.exe /c mklink /J "$link" "$($d.Name)" | Out-Null
  }
}
Write-Output 'hermes-cua-bridge=ok'
"""


def bridge_script() -> str:
    return _BRIDGE.lstrip("\n")


def install_script() -> str:
    return (
        _INSTALL.replace("@VERSION@", GIT_VERSION)
        .replace("@TAG@", GIT_TAG)
        .replace("@SHA64@", GIT_SHA256["64-bit"])
        .replace("@SHAARM@", GIT_SHA256["arm64"])
        .lstrip("\n")
    )


def missing_message(space: str, reason: str = "") -> str:
    why = f" ({reason})" if reason else ""
    return (
        f"The Windows Space '{space}' has no Git for Windows, and the plugin could not install it{why}. "
        "Hermes runs its file tools, search, background processes and code execution in Git Bash on "
        f"Windows. {FIX}"
    )


def parse_result(output: str) -> tuple[str, str]:
    """(bash path, failure reason) from the install script's output. One of them is empty."""
    bash, reason = "", ""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("hermes-cua-git-ok="):
            bash = line.split("=", 1)[1].strip()
        elif line.startswith("hermes-cua-git-failed="):
            reason = line.split("=", 1)[1].strip()
    return bash, reason
