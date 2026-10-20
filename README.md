# Hermes on Cua Spaces

Run Hermes Agent's terminal, file and code tools inside a [Cua Space](https://cua.ai/spaces): an isolated machine you can watch live, on your own hardware or in your own cloud account.

Hermes still runs where it runs today. When it needs to run a command, write a file or execute code, that work happens in the Space instead of on your computer. Because the Space is the sandbox, Hermes skips its risky-command prompts for Spaces this plugin creates.

```
you  ->  Hermes (your machine)  ->  this plugin  ->  Cua Space (an isolated Linux machine)
                                                      terminal, files, code run here
```

## Install in 3 steps

1. Install Cua and sign in (sign-in is only needed for Spaces on your cua.ai account; a local Space needs none):

   ```bash
   curl -fsSL https://cua.ai/install.sh | sh
   cua auth login
   ```

2. Install the plugin:

   ```bash
   hermes plugins install https://github.com/trycua/hermes-cua-spaces
   ```

   Hermes asks to install one Python package (`cua`). Say yes, and say yes to enabling the plugin.

3. Point Hermes at it:

   ```bash
   hermes config set terminal.backend cua
   ```

Start Hermes as usual. The first command creates a Space (the first one takes a few minutes while Cua downloads the machine image). After that, every terminal command, file read, file write and code run lands in the Space.

Check it worked by asking Hermes: `run hostname and cat /etc/os-release`. You will see the Space's name and Ubuntu, not your own computer.

## Settings

The plugin keeps its settings in Hermes's `config.yaml`, under `plugins.entries.cua-spaces.settings`. Set them with `hermes config set`.

| Setting | Default | What it does |
|---|---|---|
| `space` | `create` | `create` makes a Space for you. Or give the name or id of a Space you already have, for example `my-box`. |
| `on` | your Cua default | Where a new Space goes: `local`, `cloud`, `host:<machine>`, or the name of one of your machines. |
| `image` | `linux` | The image for a new Space. `linux` is Ubuntu with a desktop. |
| `delete_on_exit` | `true` | Delete a Space the plugin created when Hermes finishes. Set `false` to keep it for next time. A Space you named is never deleted. |
| `create_timeout` | `600` | Seconds to wait for a new Space to be ready. |

Examples:

```bash
# use a Space you already made
hermes config set plugins.entries.cua-spaces.settings.space my-box

# make new Spaces on another of your machines
hermes config set plugins.entries.cua-spaces.settings.on "spare mac mini"
```

The environment variables `HERMES_CUA_SPACE`, `HERMES_CUA_ON` and `HERMES_CUA_IMAGE` override the same settings for one shell.

How the plugin picks a Space:

- `space: create` (the default): each Hermes run makes its own Space, named `hermes-<task>-<random>`, does the work there and deletes it when it finishes. Two Hermes runs at once get two Spaces and never touch each other's files.
- `space: create` and `delete_on_exit: false`: the plugin makes one Space called `hermes-default` the first time and reuses it after that, so your files are still there next session. It stays running when Hermes exits. Stop it with `cua spaces stop hermes-default` or delete it with `cua spaces delete hermes-default`.
- `space: my-box`: the plugin uses that Space and never deletes or stops it. Because it is your machine and not a throwaway one, Hermes keeps asking before risky commands.

### Sign-in and keys

The plugin never stores a token or key. It talks to Cua through the `cua` Python package, which uses the sign-in that `cua auth login` saved. Nothing about Cua goes in `config.yaml` or `.env`.

### Working folder

Leave `terminal.cwd` alone. A new session starts in the Space user's home folder (`/home/cua`). If you ask Hermes to create files, use absolute paths such as `/home/cua/project/app.py`.

## Watch the Space live

Open the Cua Spaces app and click the Space (`hermes-default`, or the one you named). You see its desktop as Hermes works. In a terminal, `cua spaces ls` lists your Spaces and `cua viewer` serves a browser viewer for all of them. You can click in the viewer to take over; Hermes keeps working next to you.

## Run several in parallel

Give each Hermes its own Space.

- Separate Hermes profiles, each with its own Space:

  ```bash
  HERMES_CUA_SPACE=build-a hermes --profile a
  HERMES_CUA_SPACE=build-b hermes --profile b
  ```

  `build-a` and `build-b` must exist (create them with `cua spaces create linux --name build-a`).

- Throwaway Spaces, one per run: this is the default. Every Hermes you start makes its own Space and deletes it when it finishes, so you can start as many as your machine can hold.

## Two other ways to use Cua with Hermes

These work today and need no plugin.

**1. Give Hermes the Cua tools (`cua mcp`).** Hermes can then create Spaces, run commands in them, drive their desktops and delete them, as tools it calls itself. Add this to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  cua:
    command: cua
    args: ["mcp"]
```

Limit what Hermes may do with `--permissions` (for example `args: ["mcp", "--permissions", "spaces:readonly"]`) and with `tools.include` in the same block.

**2. Run Hermes itself inside a Space.** Everything stays in the Space: the agent, its keys and its tools.

```bash
cua agent create ada --harness hermes --in local:dev --env-from-host OPENAI_API_KEY
cua agent tell ada "summarize the repo in /home/cua/project"
```

Hermes keeps its memory in your Cua Volume, so it survives if the Space is replaced.

## What does and does not run in the Space

| | In the Space with this plugin |
|---|---|
| `terminal` tool, background processes | yes |
| File tools (read, write, patch, search) | yes |
| `execute_code` | yes |
| Browser tools, `computer_use`, Bot Desktop | no, not yet. They still use your own machine (see below) |

Hermes only lets `computer_use` and Bot Desktop follow the built-in `docker`, `ssh` and `singularity` backends. Following a plugin backend needs a small change in Hermes. It is proposed to Nous. Until it lands, use the second option above (Hermes inside a Space) if you want the desktop to live in the Space.

## What the plugin does and sends

- It calls the Cua SDK to create, find, start and delete Spaces, and to run commands and write files in them.
- With a local Space, nothing leaves your machine. With a Space on another machine or your cloud account, commands and files go through Cua's encrypted relay or your own network.
- It does not sync your Hermes skills, cache or credentials into the Space. The Space starts with what its image has.
- It adds no telemetry. The `cua` package has its own anonymous usage telemetry; turn it off with `cua telemetry off` or `CUA_TELEMETRY=0`.

## When something goes wrong

The plugin explains errors in plain words and says what to run next. The most common ones:

| You see | Do this |
|---|---|
| "Cua did not accept your sign-in" | `cua auth login` |
| "Cua can't find the Space ..." | `cua spaces ls`, then fix the `space` setting or use `create` |
| "Cua can't start a Space here yet" | `cua doctor` shows what is missing |
| "The `cua` Python package is not installed" | `hermes pm repair` |

## Develop

```bash
uv venv --python 3.14 && source .venv/bin/activate
pip install -e ".[test]" hermes-agent
pytest
hermes plugins validate . --install-deps
```

The tests run the whole environment against a local shell standing in for a Space, so they need no Cua account.

## Licence

MIT, the same as the Cua SDKs. See [LICENSE](LICENSE).
