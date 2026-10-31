# SENTINEL setup guide

SENTINEL is being built to use Meta AI evaluators to interpret restrictions and
evaluate the actions of other AI agents. The current gateway checks submitted
tool actions, with a configurable Meta reviewer alongside hard rules. Use the native
app to see activity and approve or deny requests. You do not need to open a webpage.

## Already have the app configured?

1. Open **SENTINEL**. Click **Connect protection** if it says Not connected.
2. Click **Connect an AI**, then **Connect Codex** or **Connect Claude Code**.
   The assistant's command-line tool must already be installed. No model API key
   is needed to connect the assistant.
3. Restart the assistant if you just added the connection. Click **Copy test
   message** and paste it into a new assistant chat.
4. Look for **Look at files → Completed** in SENTINEL. A saved connection alone
   does not prove that actions are being monitored.

Codex may show **Already configured**; that is fine. The Claude button connects
**Claude Code**, not the separate Claude chat desktop app.

## First-time installation from source

This is a development proof of concept, not a finished installer. Install Git,
Python 3.12 or newer, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
macOS has been tested; Windows support is implemented but has not been verified
on a Windows machine.

Run these commands in Terminal (macOS) or PowerShell (Windows):

```sh
git clone https://github.com/aadarsh-ulayil/sentinel.git
cd sentinel
uv sync --locked --extra desktop --extra integrations --extra package
uv run --no-sync python -c "from pathlib import Path; import secrets; p=Path('.env'); p.exists() or p.write_text(Path('.env.example').read_text().replace('SENTINEL_TOKEN=', 'SENTINEL_TOKEN='+secrets.token_urlsafe(32), 1).replace('SENTINEL_AGENT_TOKEN=', 'SENTINEL_AGENT_TOKEN='+secrets.token_urlsafe(32), 1))"
uv run --no-sync python -m sentinel.desktop
```

The configuration command creates two different local access tokens and leaves
an existing `.env` unchanged. Keep that file private. Meta review is off by default;
the deterministic rules and connection test do not need a model key.

Click **Connect protection**, then follow the connection steps above. Keep the
repository and its `.venv` folder in place: this development build uses them as
the connection helper. Moving the folder requires reconnecting the assistant.

## Choose a real project

Without a project selection, new tasks use an isolated demo folder.
Click **Set up a project**, choose one specific folder, and choose:

- **Read only**: the assistant cannot change files through SENTINEL.
- **Ask me before every edit or deletion**: changes pause for your decision.

Save, then start a new task in your assistant. Existing tasks do not gain access
to the new folder. Changing or disconnecting the project revokes previous project
access. Hidden credential locations, symlinks and paths outside the folder are
restricted. Arbitrary build commands are not supported: only `pwd`, `ls` and
`whoami` are currently allowed.

## Optional Meta review of other agents

Meta is an additional reviewer; it is not required to connect Codex or Claude.
Configure the Baseten values in `.env.example` in your private `.env`, supplying
your own key. Restart the gateway after changing environment settings. Enable
**Use Meta AI to review other agents’ actions** in project setup only when you
want task text, action metadata and rules sent to Baseten. File contents and
message bodies are omitted, but metadata may still contain sensitive data.

Hard rules run first. Meta cannot override a block or grant approval. A flag,
timeout or invalid model response sends the action to human review. No human
reply within 60 seconds denies it. Live reviewer validation remains incomplete;
the integration is covered by automated tests with simulated model responses.
The separate Meta Model API rule compiler is optional and requires separate
configuration; leave it blank if unavailable.

## Build a desktop app

From the repository folder:

```sh
uv run --no-sync python scripts/build_desktop.py
```

On macOS, open `dist/SENTINEL.app`. On Windows, open
`dist/SENTINEL/SENTINEL.exe` and keep its entire surrounding folder. Build on the
target operating system. These are unsigned development builds.

If asked for a configuration, choose the repository's `.env`. On macOS,
Command–Shift–Period reveals hidden files. This selection currently needs to be
repeated when opening the packaged app. Keep the original development folder
available for the assistant connection helper.

## Troubleshooting

- **Assistant not found:** install Codex CLI or Claude Code, then reopen setup.
- **Different SENTINEL connection exists:** the app leaves it unchanged. Remove
  the old entry in that assistant's MCP settings before reconnecting.
- **No activity:** explicitly ask the assistant to use SENTINEL tools. Its ordinary
  file, browser and terminal tools bypass this gateway.
- **Project setup fails after updating:** restart the background gateway too;
  updating the desktop window does not replace a running service. For the legacy
  macOS LaunchAgent installation, run `launchctl kickstart -k gui/$(id -u)/local.sentinel.gateway`
  in Terminal after finishing active tasks. For a manually started gateway, stop
  it with Ctrl+C and restart it. Do not start two gateways on port 8000.
- **Meta unavailable:** leave review off for a rules-only test, or review the paused
  action yourself. Do not interpret an unavailable reviewer as a safety verdict.

## Limits

SENTINEL only governs actions routed through its gateway. Adding an MCP connection
does not force the assistant to use it or disable other tools. It cannot control
an agent using screen/mouse automation or other bypasses. Humans choose the rules.
This is a proof of concept, not operating-system isolation. Payments and messages
are simulations. Windows still needs real-device testing.

## Developer checks

```sh
uv run --no-sync pytest -q
```

Never commit `.env`, local activity databases, downloaded files or private project
contents. The repository ignores `.env`, `.runtime`, `.venv`, `build` and `dist`.
