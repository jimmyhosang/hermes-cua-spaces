"""Windows Space support: the PowerShell and bash scripts Hermes commands are wrapped in.

Hermes writes its terminal tools for a POSIX shell. A Windows Space has none, so the plugin:

* runs the `terminal` tool's commands in PowerShell (`pwsh` if the Space has it, else the
  `powershell.exe` every Windows has),
* runs the commands Hermes builds for its other tools (file read/write/patch, search, background
  processes, code execution) in Git Bash, as Hermes itself does on Windows. A Space without Git for
  Windows gets it installed first (see `windows_setup.py`). Hermes's own code is never replaced.

Every script is staged as a file in the Space and started with a short command line. That keeps
quoting, the Windows 8,191-character command limit and the console code page out of the way:
the command text travels as base64, and output leaves as UTF-8 bytes.
"""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass

# What the plugin tells the model and the user about a Windows Space.
TERMINAL_NOTE = (
    "On this Windows machine the terminal tool runs PowerShell, not bash. The file tools (read_file, "
    "write_file, patch, search_files) take Git Bash paths: write C:\\Users\\me\\a.txt as /c/Users/me/a.txt, "
    "or use a path relative to the terminal's current folder."
)

# Windows PowerShell 5.1 and PowerShell 7 both run these options.
_PS_FLAGS = "-NoProfile -NonInteractive -ExecutionPolicy Bypass"

_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


_CONSOLE_CODES = re.compile(r"(?:\x1b\[[0-9;?]*[A-Za-z]|#< CLIXML\r?\n<Objs[^\n]*(?:\r?\n)?)+\s*$")
_CLIXML = re.compile(r"#< CLIXML\r?\n<Objs.*?</Objs>\r?\n?", re.S)


def clean_output(text: str) -> str:
    """Drop what Windows PowerShell 5.1 adds to redirected output: a trailing screen-clear sequence
    (`ESC[H ESC[2J ESC[3J`) and CLIXML progress records. Command output itself is left alone."""
    text = _CLIXML.sub("", text)
    return _CONSOLE_CODES.sub("", text)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def ps_quote(text: str) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + text.replace("'", "''") + "'"


def encoded_command(script: str) -> str:
    """`-EncodedCommand` payload: base64 of the script as UTF-16LE."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def to_forward(path: str) -> str:
    """`C:\\Users\\me` -> `C:/Users/me`. Every Windows API, PowerShell and Git Bash accept it."""
    return path.replace("\\", "/")


def looks_like_windows_path(path: str) -> bool:
    return bool(_DRIVE.match(path)) or path.startswith("\\\\")


_MSYS = re.compile(r"^/([A-Za-z])(/.*)?$")
_WIN_DRIVE = re.compile(r"^([A-Za-z]):([\\/].*)?$")


def looks_like_msys_path(path: str) -> bool:
    """`/c/Users/me`, the Git Bash form of `C:\\Users\\me`."""
    return bool(_MSYS.match(path))


def to_msys(path: str) -> str:
    """`C:\\Users\\me` -> `/c/Users/me`.

    Hermes runs on a Unix-style host: its file tools only treat a path starting with `/` as absolute,
    and `C:/Users/me` would be taken as a relative one. The Git Bash form is absolute everywhere, so
    the folder the plugin reports to Hermes uses it.
    """
    m = _WIN_DRIVE.match(path)
    if not m:
        return path
    return "/" + m.group(1).lower() + (m.group(2) or "").replace("\\", "/")


def from_msys(path: str) -> str:
    """`/c/Users/me` -> `C:/Users/me`; anything else is only given forward slashes."""
    m = _MSYS.match(path)
    if m:
        return m.group(1).upper() + ":" + (m.group(2) or "/")
    return to_forward(path)


@dataclass(frozen=True)
class WindowsInfo:
    """What the first probe learned about the Space."""

    shell: str  # "pwsh" or "powershell.exe"
    home: str  # the user profile folder, e.g. C:\Users\cua
    temp: str  # temp folder with forward slashes
    bash: str  # Git Bash, or "" when the Space has none
    user: str = ""


_PROBE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$pw = Get-Command pwsh | Select-Object -First 1
$sh = 'powershell.exe'
if ($pw) { $sh = 'pwsh' }
$home_ = [Environment]::GetFolderPath('UserProfile')
$tmp = [IO.Path]::GetTempPath().TrimEnd('\', '/')
$roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs')) | Where-Object { $_ }
$bash = ''
foreach ($r in $roots) {
  $c = Join-Path $r 'Git\bin\bash.exe'
  if (Test-Path -LiteralPath $c) { $bash = $c; break }
}
Write-Output "hermes-cua-shell=$sh"
Write-Output "hermes-cua-home=$home_"
Write-Output "hermes-cua-temp=$tmp"
Write-Output "hermes-cua-bash=$bash"
Write-Output "hermes-cua-user=$([Environment]::UserName)"
"""


def probe_line() -> str:
    """The command line that asks the Space about itself. Always `powershell.exe`: it is on every Windows."""
    return f"powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded_command(_PROBE)}"


def parse_probe(output: str) -> WindowsInfo | None:
    found: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("hermes-cua-") and "=" in line:
            key, _, value = line[len("hermes-cua-"):].partition("=")
            found[key] = value.strip()
    if not found.get("home") or not found.get("shell"):
        return None
    return WindowsInfo(
        shell=found["shell"],
        home=found["home"],
        temp=to_forward(found.get("temp") or found["home"]),
        bash=found.get("bash", ""),
        user=found.get("user", ""),
    )


def script_path(info: WindowsInfo, run_id: str, ext: str) -> str:
    """Where a staged script lives. The run id is in the name so a stuck command can be found and stopped."""
    return f"{info.temp}/hermes-cua-run-{run_id}.{ext}"


# -- PowerShell: the terminal tool --

_PS_WRAPPER = r"""
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$__enc = New-Object System.Text.UTF8Encoding($false)
try { [Console]::OutputEncoding = $__enc } catch {}
try { [Console]::InputEncoding = $__enc } catch {}
$OutputEncoding = $__enc
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:AI_AGENT) { $env:AI_AGENT = 'hermes-agent' }
if (-not $env:HERMES_AGENT) { $env:HERMES_AGENT = 'true' }
$__stdout = [Console]::OpenStandardOutput()
function __hw([string]$s) { $b = $__enc.GetBytes($s); $__stdout.Write($b, 0, $b.Length); $__stdout.Flush() }
function __b64([string]$s) { $__enc.GetString([Convert]::FromBase64String($s)) }
$__cwd = __b64 '@CWD@'
$__cmd = __b64 '@CMD@'
$__ec = 0
try {
  $__cdok = $true
  try { Set-Location -LiteralPath $__cwd -ErrorAction Stop } catch {
    $__cdok = $false
    __hw ("hermes: the working folder '" + $__cwd + "' does not exist in this Space.`n")
    $__ec = 126
  }
  if ($__cdok) {
@STDIN@    $global:LASTEXITCODE = $null
    $global:__ok = $true
    $global:__code = $null
    try {
      $__sb = [scriptblock]::Create($__cmd + "`n`$global:__ok = `$?`n`$global:__code = `$global:LASTEXITCODE")
      & $__sb *>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
          if ($_.FullyQualifiedErrorId -eq 'NativeCommandError' -or $_.CategoryInfo.Category -eq 'NotSpecified') { $_.Exception.Message }
          else { ($_ | Out-String).TrimEnd() }
        } else { $_ }
      } | Out-String -Stream -Width 4096 | ForEach-Object { __hw ($_ + "`n") }
    } catch {
      __hw (($_ | Out-String).TrimEnd() + "`n")
      $global:__ok = $false
      $global:__code = 1
    }
    if (-not $global:__ok) {
      if (($global:__code -is [int]) -and ($global:__code -ne 0)) { $__ec = $global:__code } else { $__ec = 1 }
    }
  }
} finally {
  $__here = ((Get-Location -PSProvider FileSystem).ProviderPath) -replace '\\', '/'
  if ($__here -match '^([A-Za-z]):(.*)$') { $__here = '/' + $Matches[1].ToLower() + $Matches[2] }
  __hw ("`n@MARKER@" + $__here + "@MARKER@`n")
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
exit $__ec
"""


def build_powershell_script(command: str, cwd: str, marker: str, stdin_path: str = "") -> str:
    """The script file for one terminal command. Ends by printing the working folder between `marker`s."""
    stdin = ""
    if stdin_path:
        # Feed the staged text to the command's input, then delete it.
        stdin = (
            f"    $__in = [IO.File]::ReadAllText({ps_quote(stdin_path)}, $__enc)\n"
            f"    Remove-Item -LiteralPath {ps_quote(stdin_path)} -Force -ErrorAction SilentlyContinue\n"
        )
        command = f"$__in | & {{\n{command}\n}}"
    return (
        _PS_WRAPPER.replace("@CWD@", b64(from_msys(cwd)))
        .replace("@CMD@", b64(command))
        .replace("@MARKER@", marker)
        .replace("@STDIN@", stdin)
        .lstrip("\n")
    )


def powershell_line(info: WindowsInfo, path: str) -> str:
    """The command line that runs a staged script file. It holds no double quote.

    A Space starts a command line with `cmd.exe /C`, which mangles quotes (`-File "a b.ps1"` reaches
    PowerShell as `-File \\"a b.ps1\\"`). So the path travels inside `-EncodedCommand`, which also copes
    with spaces in it, and the script's exit code is passed on.
    """
    # No progress records: with output redirected PowerShell would print them as CLIXML noise.
    runner = f"$ProgressPreference = 'SilentlyContinue'\n& {ps_quote(path)}\nexit $LASTEXITCODE\n"
    return f"{info.shell} {_PS_FLAGS} -EncodedCommand {encoded_command(runner)}"


# -- Git Bash: the commands Hermes builds for its other tools --

_BASH_LAUNCHER = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$p = New-Object System.Diagnostics.Process
$p.StartInfo.FileName = @BASH@
$p.StartInfo.Arguments = '-l "' + @SCRIPT@ + '"'
$p.StartInfo.UseShellExecute = $false
$p.StartInfo.RedirectStandardOutput = $true
$p.StartInfo.CreateNoWindow = $true
[void]$p.Start()
$out = [Console]::OpenStandardOutput()
$p.StandardOutput.BaseStream.CopyTo($out)
$out.Flush()
$p.WaitForExit()
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
exit $p.ExitCode
"""


_PY_PATH = (
    # A Python installed after the Space's agent started is not on that agent's PATH yet.
    'for __d in "/c/Program Files"/Python3*/ "${LOCALAPPDATA:-/nonexistent}"/Programs/Python/Python3*/; do\n'
    '  [ -x "${__d}python.exe" ] && PATH="${__d%/}:${__d%/}/Scripts:$PATH"\n'
    "done\n"
    "export PATH\n"
)

_PY3_SHIM = (
    # Hermes runs its code tool with `python3` (through `exec`, so a shell function would not do).
    # Windows has `python` (and a Store stub called `python3` that does nothing): when `python3` is
    # not a real interpreter, put a one-line `python3` script for the real one first on PATH.
    '__p3="$(command -v python3 2>/dev/null)"\n'
    'case "$__p3" in ""|*/WindowsApps/*)\n'
    "  for __p in python py; do\n"
    '    __pp="$(command -v $__p 2>/dev/null)"\n'
    '    case "$__pp" in ""|*/WindowsApps/*) ;; *)\n'
    '      __sd="${TMPDIR:-/tmp}/hermes-cua-bin"; mkdir -p "$__sd"\n'
    "      printf '#!/bin/sh\\nexec \"%s\" \"$@\"\\n' \"$__pp\" > \"$__sd/python3\"; chmod +x \"$__sd/python3\"\n"
    '      PATH="$__sd:$PATH"; export PATH; break ;;\n'
    "    esac\n"
    "  done ;;\n"
    "esac\n"
)


def build_bash_script(command: str, cwd: str, marker: str) -> str:
    """A bash script (LF endings) that runs `command` in `cwd` and prints the folder between `marker`s.

    `pwd` gives the Git Bash form of the folder (`/c/Users/me`), which is the form Hermes's file
    tools need; the PowerShell side converts it back when it starts the next command there.
    """
    return (
        "exec 2>&1\n"
        "trap 'rm -f -- \"$0\"' EXIT\n"
        'export AI_AGENT="${AI_AGENT:-hermes-agent}" HERMES_AGENT="${HERMES_AGENT:-true}"\n'
        + _PY_PATH
        + _PY3_SHIM
        + f"builtin cd -- {shlex.quote(from_msys(cwd))} || exit 126\n"
        f"eval {shlex.quote(command)}\n"
        "__hermes_ec=$?\n"
        f"printf '\\n{marker}%s{marker}\\n' \"$(pwd)\"\n"
        "exit $__hermes_ec\n"
    )


def build_bash_launcher(info: WindowsInfo, bash_script_path: str) -> str:
    """A tiny PowerShell file that starts Git Bash and copies its output through byte for byte.

    Going through PowerShell's own output would turn every LF into CRLF and so corrupt file reads.
    """
    return (
        _BASH_LAUNCHER.replace("@BASH@", ps_quote(info.bash))
        .replace("@SCRIPT@", ps_quote(bash_script_path))
        .lstrip("\n")
    )


def cancel_line(info: WindowsInfo, run_id: str) -> str:
    """Stop a command (and its children) by the run id in its script name, and remove its leftovers."""
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"$needle = {ps_quote('*hermes-cua-run-' + run_id + '*')}\n"
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like $needle -and $_.ProcessId -ne $PID } |\n"
        "  ForEach-Object { & taskkill.exe /T /F /PID $_.ProcessId | Out-Null }\n"
        f"Remove-Item -Path {ps_quote(info.temp + '/hermes-cua-run-' + run_id + '.*')} -Force\n"
    )
    return f"{info.shell} {_PS_FLAGS} -EncodedCommand {encoded_command(script)}"
