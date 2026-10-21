"""Windows Space support, driven against a local PowerShell standing in for the Space.

Needs PowerShell 7 (`pwsh`) on Linux or macOS, or Windows PowerShell on Windows. On a Windows runner
this exercises the real Windows PowerShell 5.1 and Git Bash.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cua_spaces import windows as win
from hermes_cua_spaces.client import ExecResult
from hermes_cua_spaces.config import Settings

ON_WINDOWS = sys.platform.startswith("win")
PWSH = os.environ.get("HERMES_TEST_PWSH") or shutil.which("pwsh") or (shutil.which("powershell") if ON_WINDOWS else None)
needs_powershell = pytest.mark.skipif(PWSH is None, reason="needs PowerShell (pwsh)")


# -- pure pieces: no PowerShell needed --


def test_probe_is_parsed():
    out = "hermes-cua-shell=pwsh\r\nhermes-cua-home=C:\\Users\\cua\r\nhermes-cua-temp=C:\\Users\\cua\\AppData\\Local\\Temp\r\nhermes-cua-bash=\r\nhermes-cua-user=cua\r\n"
    info = win.parse_probe(out)
    assert info == win.WindowsInfo(shell="pwsh", home="C:\\Users\\cua", temp="C:/Users/cua/AppData/Local/Temp", bash="", user="cua")


def test_probe_without_answer_is_none():
    assert win.parse_probe("The term 'x' is not recognized") is None


def test_windows_paths():
    assert win.looks_like_windows_path("C:\\Users\\me") and win.looks_like_windows_path("c:/x")
    assert win.looks_like_windows_path("\\\\server\\share")
    assert not win.looks_like_windows_path("/root") and not win.looks_like_windows_path("~")
    assert win.to_forward("C:\\a\\b") == "C:/a/b"


def test_clean_output_drops_powershell_noise_only():
    assert win.clean_output("yes\n\nMK/c/xMK\n\x1b[H\x1b[2J\x1b[3J") == "yes\n\nMK/c/xMK\n"
    assert win.clean_output('a\n#< CLIXML\n<Objs Version="1"><Obj/></Objs>') == "a\n"
    assert win.clean_output("keep \x1b[31mred\x1b[0m text\n") == "keep \x1b[31mred\x1b[0m text\n"


def test_git_bash_path_forms():
    assert win.to_msys("C:\\Users\\cua") == "/c/Users/cua" and win.to_msys("D:/x y") == "/d/x y"
    assert win.to_msys("/tmp/x") == "/tmp/x" and win.to_msys("C:") == "/c"
    assert win.from_msys("/c/Users/cua") == "C:/Users/cua" and win.from_msys("/c") == "C:/"
    assert win.from_msys("/tmp/x") == "/tmp/x" and win.from_msys("C:\\a\\b") == "C:/a/b"
    assert win.looks_like_msys_path("/c/Users") and not win.looks_like_msys_path("/root")


def test_bash_script_points_python3_at_the_real_python():
    script = win.build_bash_script("python3 x.py", "/c/Users/cua", "MARK")
    assert "WindowsApps" in script and "hermes-cua-bin" in script and "exec" in script


def test_powershell_script_carries_command_as_base64_only():
    cmd = "Write-Output 'it''s \"quoted\"' ; $x = `n"
    script = win.build_powershell_script(cmd, "C:\\Users\\cua", "MARK")
    assert script.isascii() and cmd not in script
    assert win.b64(cmd) in script and win.b64("C:/Users/cua") in script


def test_command_lines_stay_short_and_quote_free():
    info = win.WindowsInfo(shell="powershell.exe", home="C:\\Users\\cua", temp="C:/Users/cua/AppData/Local/Temp", bash="")
    line = win.powershell_line(info, win.script_path(info, "abc", "ps1"))
    assert '"' not in line and "'" not in line  # cmd.exe /C would mangle quotes
    prefix = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
    assert line.startswith(prefix)
    import base64

    script = base64.b64decode(line[len(prefix):]).decode("utf-16-le")
    assert "& 'C:/Users/cua/AppData/Local/Temp/hermes-cua-run-abc.ps1'" in script and "exit $LASTEXITCODE" in script
    assert len(win.probe_line()) < 4000
    assert len(win.cancel_line(info, "abc")) < 4000


def test_bash_script_reports_the_git_bash_folder():
    script = win.build_bash_script("echo 'hi'", "C:\\Users\\cua\\my dir", "MARK")
    assert "builtin cd -- 'C:/Users/cua/my dir'" in script
    assert "pwd -W" not in script and "$(pwd)" in script and "\r" not in script


# -- a Space that is really a local PowerShell --


class PowerShellSpace:
    """Stands in for a Windows Space: runs command lines locally, with `powershell.exe` mapped to pwsh."""

    os = "windows"

    def __init__(self, root: Path, with_bash: bool, install_works: bool = True):
        self.id, self.name, self.root = "local:win-test", "win-test", root
        self.with_bash = with_bash
        self.install_works = install_works
        self.installs = 0
        self.lines: list[str] = []

    def run(self, command: str, timeout_s: float) -> ExecResult:
        self.lines.append(command)
        script = self._script_of(command)
        if script is not None and "hermes-cua-git-ok" in script:
            # The Git for Windows installer: a test machine cannot really install it.
            self.installs += 1
            if not self.install_works:
                return ExecResult("hermes-cua-git-failed=installer: no network\n", 3)
            self.with_bash = True
            return ExecResult("hermes-cua-git-ok=/bin/bash\nhermes-cua-git-version=git version test\n", 0)
        if script is not None and "hermes-cua-bridge" in script:
            self.bridged = True
            return ExecResult("hermes-cua-bridge=ok\n", 0)
        if script is not None and "hermes-cua-python-ok" in script:
            return ExecResult("hermes-cua-python-ok=/usr/bin/python3\n", 0)
        if not ON_WINDOWS:
            command = re.sub(r"^(powershell\.exe|pwsh)\b", PWSH.replace("\\", "/"), command)
        p = subprocess.run(command, shell=True, capture_output=True, timeout=timeout_s, cwd=self.root)
        out = p.stdout.decode("utf-8", "replace")
        if "hermes-cua-shell=" in out and not ON_WINDOWS:
            # The probe cannot find Git Bash off Windows, so this stands in for it.
            out += f"hermes-cua-bash={'/bin/bash' if self.with_bash else ''}\n"
        return ExecResult(out + p.stderr.decode("utf-8", "replace"), p.returncode)

    @staticmethod
    def _script_of(command: str):
        m = re.search(r"-EncodedCommand (\S+)", command)
        if not m:
            return None
        import base64

        runner = base64.b64decode(m.group(1)).decode("utf-16-le")
        p = re.search(r"& '([^']+\.ps1)'", runner)
        if not p or not Path(p.group(1)).exists():
            return None
        return Path(p.group(1)).read_text(encoding="utf-8-sig")

    def write(self, path: str, data: bytes) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def home(self) -> str:
        return str(self.root)


class OneSpaceClient:
    def __init__(self, space):
        self.space, self.deleted = space, []

    def attach(self, space):
        return self.space

    def ensure(self, name, settings):
        return self.space, True

    def delete(self, space_id):
        self.deleted.append(space_id)


pytest.importorskip("tools.environments.base", reason="needs Hermes installed")

from hermes_cua_spaces.environment import CuaSpaceEnvironment  # noqa: E402


@pytest.fixture(params=[True, False], ids=["git-bash", "no-bash"])
def with_bash(request):
    if ON_WINDOWS and not request.param:
        pytest.skip("a real Windows runner has Git Bash; the install case is covered on Linux and macOS")
    return request.param


@pytest.fixture
def winenv(tmp_path, with_bash):
    if PWSH is None:
        pytest.skip("needs PowerShell (pwsh)")
    space = PowerShellSpace(tmp_path, with_bash)
    env = CuaSpaceEnvironment(
        cwd="/root", timeout=60, task_id="t", settings=Settings(), client=OneSpaceClient(space), persistent=True
    )
    yield env
    env.cleanup()


def term(env, command, **kw):
    """What Hermes's terminal tool does."""
    return env.execute(command, bounded_capture=True, **kw)


@needs_powershell
def test_cwd_starts_in_the_user_profile(winenv):
    assert winenv.windows_info.home and winenv.cwd == win.to_msys(winenv.windows_info.home)


@needs_powershell
def test_terminal_runs_powershell(winenv):
    r = term(winenv, "$PSVersionTable.PSVersion.Major")
    assert r["returncode"] == 0 and r["output"].strip().isdigit()


@needs_powershell
def test_exit_codes(winenv):
    assert term(winenv, "Write-Output ok")["returncode"] == 0
    assert term(winenv, "exit 7")["returncode"] == 7
    assert term(winenv, "throw 'boom'")["returncode"] == 1
    assert term(winenv, "Get-Item (Join-Path $env:TEMP 'definitely-not-here-xyz')")["returncode"] == 1
    assert term(winenv, "$null = 1; Write-Output after")["returncode"] == 0


@needs_powershell
def test_native_exit_code_is_kept(winenv):
    shell = "cmd /c exit 5" if ON_WINDOWS else "sh -c 'exit 5'"
    assert term(winenv, shell)["returncode"] == 5


@needs_powershell
def test_output_is_utf8_with_unix_newlines(winenv):
    r = term(winenv, "Write-Output 'héllo ✓ 日本'; Write-Output 'two'")
    assert r["output"].splitlines() == ["héllo ✓ 日本", "two"]
    assert "\r" not in r["output"]


@needs_powershell
def test_errors_and_warnings_reach_the_output(winenv):
    r = term(winenv, "Write-Error oops; Write-Warning careful; 'done'")
    assert "oops" in r["output"] and "careful" in r["output"] and "done" in r["output"]


@needs_powershell
def test_syntax_error_is_reported_and_fails(winenv):
    r = term(winenv, "if (")
    assert r["returncode"] == 1 and r["output"].strip()


@needs_powershell
def test_working_folder_is_remembered(winenv, tmp_path):
    sub = tmp_path / "sub folder"
    sub.mkdir()
    term(winenv, f"Set-Location -LiteralPath '{sub}'")
    assert Path(win.from_msys(winenv.cwd)).resolve() == sub.resolve()
    assert Path(term(winenv, "(Get-Location).Path")["output"].strip()).resolve() == sub.resolve()


@needs_powershell
def test_missing_working_folder_is_plain(winenv, tmp_path):
    r = term(winenv, "Write-Output hi", cwd=str(tmp_path / "gone"))
    assert r["returncode"] == 126 and "does not exist" in r["output"]


@needs_powershell
def test_long_command_is_not_limited_by_the_command_line(winenv):
    big = "Write-Output 'x'\n" * 3000 + "Write-Output 'end'"
    assert len(big) > 40000
    r = term(winenv, big)
    assert r["returncode"] == 0 and r["output"].split()[-1] == "end"


@needs_powershell
def test_temp_folder_is_absolute_for_hermes(winenv):
    # Hermes ignores a temp folder that does not start with "/" and uses the host's: it must stay in the Space.
    assert winenv.get_temp_dir().startswith("/")


@needs_powershell
def test_scripts_are_cleaned_up(winenv, tmp_path):
    temp = Path(winenv.windows_info.temp)
    before = set(temp.glob("hermes-cua-*"))
    term(winenv, "Write-Output hi")
    winenv.execute("echo x")
    winenv.run_powershell("exit 3")
    assert set(temp.glob("hermes-cua-*")) == before


@needs_powershell
def test_background_and_compound_syntax_is_left_alone(winenv):
    # Hermes's bash rewrite of `A && B &` must not run on PowerShell commands.
    r = term(winenv, "Write-Output 'a & b'")
    assert "a & b" in r["output"]


@needs_powershell
def test_unix_tools_run_in_git_bash(winenv, with_bash):
    r = winenv.execute("echo from-bash && pwd")  # not the terminal tool: a Unix shell command
    assert r["returncode"] == 0 and "from-bash" in r["output"]
    assert winenv.windows_info.bash
    assert getattr(winenv._space, "bridged", False)  # the /c/ -> C:\\ folder alias was set up
    # A Space without Git for Windows got it installed once; one that had it was left alone.
    assert winenv._space.installs == (0 if with_bash else 1)


@needs_powershell
def test_missing_git_that_cannot_be_installed_fails_with_the_fix(tmp_path):
    if ON_WINDOWS:
        pytest.skip("a real Windows runner has Git Bash")
    from hermes_cua_spaces.errors import UnsupportedSpaceError

    space = PowerShellSpace(tmp_path, with_bash=False, install_works=False)
    with pytest.raises(UnsupportedSpaceError) as err:
        CuaSpaceEnvironment(
            cwd="/root", timeout=60, task_id="t", settings=Settings(), client=OneSpaceClient(space), persistent=True
        )
    assert "winget install --id Git.Git -e" in str(err.value) and "no network" in str(err.value)
    assert space.installs == 1


@needs_powershell
def test_unix_tool_error_does_not_break_the_terminal(winenv):
    winenv.execute("echo x")
    assert term(winenv, "Write-Output still-works")["output"].strip() == "still-works"


# -- file tools on a Windows Space --


@pytest.fixture
def fops(winenv):
    from tools.file_operations import ShellFileOperations

    return ShellFileOperations(winenv)  # Hermes's own file tools, unchanged


@needs_powershell
def test_write_then_read(fops, winenv, tmp_path):
    target = tmp_path / "new folder" / "a.txt"
    w = fops.write_file(str(target), "one\ntwo\nthree\n")
    assert not w.error and w.bytes_written == 14
    assert target.read_bytes() == b"one\ntwo\nthree\n"
    r = fops.read_file(str(target))
    assert not r.error and r.total_lines == 3 and "two" in r.content


@needs_powershell
def test_read_pages(fops, tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("\n".join(f"line {i}" for i in range(1, 101)) + "\n")
    r = fops.read_file(str(f), offset=11, limit=5)
    assert r.truncated and "line 11" in r.content and "line 15" in r.content and "line 16" not in r.content
    assert "offset=16" in r.hint


@needs_powershell
def test_relative_paths_follow_the_terminal_folder(fops, winenv, tmp_path):
    term(winenv, f"Set-Location -LiteralPath '{tmp_path}'")
    assert not fops.write_file("rel.txt", "hi").error
    assert (tmp_path / "rel.txt").read_text() == "hi"


@needs_powershell
def test_unicode_and_spaces_in_paths(fops, tmp_path):
    f = tmp_path / "mi carpeta" / "ñandú ✓.txt"
    assert not fops.write_file(str(f), "héllo ✓\n").error
    assert "héllo ✓" in fops.read_file(str(f)).content


@needs_powershell
def test_missing_file_is_plain(fops, tmp_path):
    r = fops.read_file(str(tmp_path / "nope.txt"))
    assert r.error and "not found" in r.error.lower()


@needs_powershell
def test_patch_replace(fops, tmp_path):
    f = tmp_path / "p.py"
    f.write_text("def f():\n    return 1\n")
    r = fops.patch_replace(str(f), "return 1", "return 2")
    assert r.success and f.read_text() == "def f():\n    return 2\n"
    assert not fops.patch_replace(str(f), "nothing like this", "x").success


@needs_powershell
def test_delete_and_move(fops, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "deep" / "b.txt"
    a.write_text("x")
    b.parent.mkdir()  # Hermes's own move does not create folders
    assert not fops.move_file(str(a), str(b)).error and b.exists() and not a.exists()
    assert not fops.delete_file(str(b)).error and not b.exists()
    assert not fops.delete_file(str(b)).error  # already gone is fine
    (tmp_path / "d").mkdir()
    assert fops.delete_file(str(tmp_path / "d")).error  # a folder is not a file
    assert (tmp_path / "d").exists()


@needs_powershell
def test_binary_file_is_not_dumped(fops, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x00\x01\x02" * 100)
    r = fops.read_file(str(f))
    assert r.is_binary


@needs_powershell
def test_search(fops, tmp_path):
    (tmp_path / "s.txt").write_text("needle here\n")
    r = fops.search("needle", str(tmp_path))
    assert not r.error and r.total_count >= 1


def test_provider_describes_a_windows_space(tmp_path):
    import hermes_cua_spaces as plugin

    if PWSH is None:
        pytest.skip("needs PowerShell (pwsh)")
    space = PowerShellSpace(tmp_path, with_bash=True)
    provider = plugin.CuaSpacesProvider(get_config=lambda k, default=None: default, client=OneSpaceClient(space))
    assert "Windows" in provider.env_description  # names all three systems before a Space is known
    env = provider.create_environment(cwd="/root", timeout=30, task_id="w")
    try:
        assert env.is_windows
        assert "PowerShell" in provider.env_description
    finally:
        env.cleanup()


def test_install_scripts_are_pinned_and_checked():
    from hermes_cua_spaces import windows_setup as g

    git, py = g.install_script(), g.install_python_script()
    assert all(len(h) == 64 for h in (*g.GIT_SHA256.values(), *g.PY_SHA256.values()))
    assert g.GIT_SHA256["64-bit"] in git and g.GIT_TAG in git and "/VERYSILENT" in git and "winget" in git
    assert g.PY_SHA256["64-bit"] in py and g.PY_VERSION in py and "/quiet" in py
    assert "@" not in git.replace("@(", "").replace("@{", "") and "@PYV@" not in py
    assert g.parse_result("x\nhermes-cua-git-ok=C:/Program Files/Git/bin/bash.exe\n") == ("C:/Program Files/Git/bin/bash.exe", "")
    assert g.parse_result("hermes-cua-git-failed=no network\n") == ("", "no network")
