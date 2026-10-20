"""Bot Desktop, computer_use and the browser following the terminal into the Space, and the
Space-home start directory. These need no Cua account: a stand-in `cua` script and a stand-in Space."""

import os
import stat
import sys

import pytest

pytest.importorskip("agent.terminal_env_provider", reason="needs Hermes installed")

import hermes_cua_spaces as plugin  # noqa: E402
from hermes_cua_spaces import environment, streams  # noqa: E402
from hermes_cua_spaces.config import load_settings  # noqa: E402

posix_only = pytest.mark.skipif(sys.platform.startswith("win"), reason="stand-in `cua` is a shell script")


def fake_cua(directory, *, with_stdin_flag=True):
    directory.mkdir(exist_ok=True)
    exe = directory / "cua"
    flag = "      --stdin  Forward stdin" if with_stdin_flag else "      --local  local only"
    exe.write_text(f"#!/bin/sh\ncat <<'EOF'\nUsage: cua sandbox exec [OPTIONS] <NAME> <COMMAND>...\n{flag}\nEOF\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


@pytest.fixture(autouse=True)
def fresh_checks():
    streams.forget_cli_checks()
    yield
    streams.forget_cli_checks()


def make_env(client, cwd="~"):
    provider = plugin.CuaSpacesProvider(get_config=lambda k, default=None: default, client=client)
    return provider, provider.create_environment(cwd=cwd, timeout=10, task_id="t")


@posix_only
def test_exec_prefix_is_cua_sandbox_exec(client, tmp_path, monkeypatch):
    exe = fake_cua(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("CUA_HOME", raising=False)
    _, env = make_env(client)
    assert env.exec_prefix() == [str(exe), "sandbox", "exec", "-i", client.space.id, "--"]
    assert env.exec_prefix(user="agent", interactive=False) == [
        str(exe), "sandbox", "exec", "-i", "--user", "agent", client.space.id, "--",
    ]


@posix_only
def test_cua_home_travels_with_the_command(client, tmp_path, monkeypatch):
    # The browser and the computer_use driver start from a scrubbed environment; `cua` must still
    # look in the same CUA_HOME as the plugin.
    exe = fake_cua(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CUA_HOME", "/srv/cua-home")
    _, env = make_env(client)
    assert env.exec_prefix(user="agent") == [
        "env", "CUA_HOME=/srv/cua-home", str(exe), "sandbox", "exec", "-i", "--user", "agent", client.space.id, "--",
    ]


@posix_only
def test_missing_cua_command_returns_none_and_warns_once(client, monkeypatch, caplog):
    monkeypatch.setenv("PATH", str(os.devnull))
    _, env = make_env(client)
    with caplog.at_level("WARNING"):
        assert env.exec_prefix() is None
        assert env.exec_prefix() is None
    warnings = [r.getMessage() for r in caplog.records if "not on PATH" in r.getMessage()]
    assert len(warnings) == 1 and "install.sh" in warnings[0]


@posix_only
def test_old_cua_command_returns_none_and_says_to_upgrade(client, tmp_path, monkeypatch, caplog):
    exe = fake_cua(tmp_path / "bin", with_stdin_flag=False)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    _, env = make_env(client)
    with caplog.at_level("WARNING"):
        assert env.exec_prefix() is None
    assert any("too old" in r.getMessage() and "cua update" in r.getMessage() for r in caplog.records)


@posix_only
def test_windows_space_has_no_exec_prefix(client, tmp_path, monkeypatch):
    exe = fake_cua(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    _, env = make_env(client)
    env._win = object()  # what a probed Windows Space sets
    assert env.exec_prefix() is None


@posix_only
def test_macos_space_has_no_exec_prefix(client, tmp_path, monkeypatch):
    exe = fake_cua(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    client.space.os = "macos"
    _, env = make_env(client)
    assert env.exec_prefix() is None


def test_provider_declares_streams_and_home():
    p = plugin.CuaSpacesProvider()
    assert p.supports_streams is True
    expected = "~" if streams.hermes_sets_start_dir() else None
    assert p.default_cwd == expected


def test_new_hermes_starts_in_the_space_home(client, monkeypatch):
    monkeypatch.setattr(streams, "hermes_sets_start_dir", lambda: True)
    _, env = make_env(client, cwd="~")
    assert env.cwd == client.space.home()
    # A literal /root is a real choice now, not the generic default.
    assert environment._generic_cwds() == ("", "~")


def test_old_hermes_still_treats_root_as_the_generic_default(client, monkeypatch):
    monkeypatch.setattr(streams, "hermes_sets_start_dir", lambda: False)
    assert environment._generic_cwds() == ("", "/root", "~")
    provider = plugin.CuaSpacesProvider(get_config=lambda k, default=None: default, client=client)
    assert provider.default_cwd is None
    env = provider.create_environment(cwd="/root", timeout=10, task_id="t")
    assert env.cwd == client.space.home()


def test_old_base_class_without_default_cwd(monkeypatch):
    from agent import terminal_env_provider as tep

    class OldBase:  # a Hermes before the plugin start-dir contract
        pass

    monkeypatch.setattr(tep, "TerminalEnvironmentProvider", OldBase)
    assert streams.hermes_sets_start_dir() is False
    assert streams.hermes_hosts_streams() is False


@posix_only
def test_commands_may_arrive_with_a_tilde_cwd(client, monkeypatch):
    monkeypatch.setenv("HOME", str(client.space.root))  # the stand-in Space's home
    _, env = make_env(client)
    out = env.execute("pwd", cwd="~")
    assert out["returncode"] == 0
    assert out["output"].strip() == os.path.realpath(client.space.home())
    env.cleanup()
