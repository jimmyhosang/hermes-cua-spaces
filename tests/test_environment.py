"""The Hermes environment, driven end to end against a local shell standing in for the Space."""
import pytest

pytest.importorskip("tools.environments.base", reason="needs Hermes installed")

from hermes_cua_spaces.config import Settings  # noqa: E402
from hermes_cua_spaces.streams import hermes_sets_start_dir  # noqa: E402

# What this Hermes sends when the user set no working folder.
GENERIC_CWD = "~" if hermes_sets_start_dir() else "/root"
from hermes_cua_spaces.environment import CuaSpaceEnvironment  # noqa: E402


def make(client, **kw):
    args = dict(cwd=GENERIC_CWD, timeout=30, task_id="t1", settings=Settings(), client=client, persistent=True)
    args.update(kw)
    return CuaSpaceEnvironment(**args)


def test_runs_command_and_returns_output(client):
    env = make(client)
    r = env.execute("echo hello && echo oops 1>&2")
    assert r["returncode"] == 0
    assert "hello" in r["output"] and "oops" in r["output"]
    env.cleanup()


def test_exit_code(client):
    env = make(client)
    assert env.execute("exit 7")["returncode"] == 7
    env.cleanup()


def test_default_cwd_is_space_home_not_root(client, space):
    env = make(client, cwd=GENERIC_CWD)
    assert env.cwd == str(space.root)
    assert env.execute("pwd")["output"].strip() == str(space.root)
    env.cleanup()


def test_cwd_and_env_persist_between_commands(client, space):
    env = make(client)
    (space.root / "sub").mkdir()
    env.execute("cd sub && export FOO=bar")
    out = env.execute("pwd; echo $FOO")["output"]
    assert out.splitlines()[0].endswith("/sub") and out.splitlines()[1] == "bar"
    env.cleanup()


def test_stdin_data_is_delivered_exactly(client, space):
    env = make(client)
    payload = "no trailing newline é"
    r = env.execute("cat > out.txt", stdin_data=payload)
    assert r["returncode"] == 0
    assert (space.root / "out.txt").read_bytes() == payload.encode()
    env.cleanup()


def test_timeout_is_reported(client):
    env = make(client, timeout=1)
    r = env.execute("sleep 5", timeout=1)
    assert r["returncode"] == 124
    env.cleanup()


def test_create_mode_uses_task_name_and_settings(client):
    env = make(client, task_id="Session 9", settings=Settings(image="linux", on="local"))
    assert client.calls[0][:1] == ("ensure",) and client.calls[0][1].startswith("hermes-session-9-")
    assert client.calls[0][2:] == ("linux", "local")
    env.cleanup()


def test_named_space_is_attached_and_never_deleted(client):
    env = make(client, settings=Settings(space="my-box"), persistent=False)
    assert client.calls[0] == ("attach", "my-box")
    env.cleanup()
    assert client.deleted == []


def test_created_space_deleted_by_default_and_kept_when_asked(client):
    make(client, settings=Settings(delete_on_exit=False), persistent=True).cleanup()
    assert client.deleted == []
    assert client.calls[-1][1] == "hermes-t1"  # kept Spaces have a stable name
    env = make(client, persistent=True)
    env.cleanup()
    assert client.deleted == [client.space.id]
    client.deleted.clear()
    env = make(client, settings=Settings(delete_on_exit=False), persistent=False)
    env.cleanup()
    env.cleanup()  # idempotent
    assert client.deleted == [client.space.id]


def test_space_error_becomes_readable_output(client, space):
    from hermes_cua_spaces.errors import CuaSpacesError

    env = make(client)

    def broken(command, timeout_s):
        raise CuaSpacesError("The Space is gone. Check `cua spaces ls`.")

    space.run = broken
    r = env.execute("echo hi")
    assert r["returncode"] != 0 and "Cua Space error" in r["output"] and "cua spaces ls" in r["output"]
