# Conectify

A local design-memory vault for Claude Desktop and Codex. Separate **Cash grab** and **Serious game** preferences, with game-specific exceptions, linked references, and shared progress.

## Install on macOS

The standalone Apple Silicon `.dmg` includes Python. Drag **Conectify.app** to
Applications, eject the disk image, and open the installed app. It starts a local
service and opens the interface in your default browser. This personal build is
ad-hoc signed, not Apple-notarized.

The packaged app stores its vault in
`~/Library/Application Support/Conectify/vault`. On first launch, if that folder
does not exist, it copies the existing Conectify vault configured in Claude
Desktop. The original remains in place. Reconnect and restart both AI clients
before continuing work in the new vault.

## Run from source

Requires macOS and Python 3.9+. The source uses Python's standard library; no
runtime packages or model API keys are required.

```sh
python3 -B app.py --open
```

This runs a foreground server at http://127.0.0.1:4317. Stop it with Ctrl+C.
Source mode stores data in a local `vault/` folder, which is excluded from Git.

## First steps

1. Choose **Cash grab** or **Serious game**.
2. Open **Art style**, **Menus & buttons**, **Animations**, or **Controls & feedback**. Write only preferences you want remembered. Save them.
3. In **References**, link an existing file or folder and say what to reuse. Folder browsing loads one directory at a time. Filename search applies to the current directory, not the entire recursive library.
4. Add a game in **Games**. Select it under **Apply to** to write exceptions. Shared preferences remain unchanged.
5. In **Shared work**, create a task and record an owner, objective, status, progress, and handoff.
6. **Preview AI context** shows the selected context, with a character count and explicit truncation indicator.

Nothing is prefilled as your taste. Each style starts empty.

## Connect Claude Desktop and Codex

In the app, open **AI connections** and click **Connect Claude & Codex**, then fully quit and reopen both clients. Source users can also run `python3 -B connect_ai.py`. The installer preserves other server configurations and creates timestamped backups beside each modified config file. It modifies only Conectify's entry in:

- `~/Library/Application Support/Claude/claude_desktop_config.json`
- `~/.codex/config.toml`

Alternatively, follow **AI connections** in the app to merge the generated configurations manually. The executable and vault paths are absolute. If you move this folder, rerun the installer. Keep a copy of your vault before moving it.

Ask each AI:

> Use Conectify. List my games, read the relevant style categories, and check shared work before starting. Record meaningful progress and results. Only change my permanent preferences when I explicitly ask you to remember something.

The MCP server advertises this workflow too, but the user prompt makes the intent explicit. Clients may ask you to approve tool access.

**Shared data is not automatic agent-to-agent messaging.** Agents can read each other's updates and task handoffs when prompted or when they invoke the tools. Conectify does not wake another AI, dispatch autonomous work, or inject updates into an already-running conversation. “Last seen” means the client last invoked the local server; it is not a live online indicator.

The UI reads local changes every two seconds while visible. This polling uses no model tokens. MCP works even with the browser and web server closed because each client accesses the same vault independently.

## Learn from a screenshot

Use **Learn from screenshot** on the style overview, a preference section, or References. Choose/drop a PNG, JPEG, or WebP up to 4 MB, or paste an image into the dialog. Select the section and whether it applies to all games of the current type or one specific game. Optionally explain what you like.

Conectify saves an image copy in `vault/attachments/` and creates a learning task assigned to Codex. Click **Copy request for Codex**, then paste and send it in Codex Desktop. Codex uses the existing image-reading and note-saving MCP tools. It is instructed to preserve existing rules, block on conflicts or ambiguity, and avoid guessing animation timing from a still image. Your request authorizes saving the supported preferences in the chosen scope.

Uploading alone does not analyze the image, change preferences, or wake Codex. The UI explicitly shows that the task is waiting. Results appear when Codex saves them. This uses your existing Codex account and its usage allowance, not a separate API key. The image is sent to the model provider when Codex reads it.

Uploaded screenshots are included in vault backups; externally linked reference originals still are not. Game-specific screenshot references are excluded from other games' context.

## Tools exposed to the AIs

- `list_games`, `get_context`, `read_note`, `save_note`
- `list_references`, `browse_reference`, `read_reference`
- `list_tasks`, `read_task`, `create_task`, `update_task`, `get_changes`

Reads are scoped and bounded. Images are loaded only on an explicit reference read and are limited to 4 MB; larger images, videos, PDFs, and Blender files return metadata/path. The interface previews common images and media; unsupported formats can be revealed in Finder or downloaded. Only references explicitly linked in the UI can be read by reference tools. Neither agent can register arbitrary new folders through MCP.

`save_note` and `update_task` require the latest revision. Stale writes fail instead of overwriting another edit. Task ownership is a coordination label, not a lock on your Roblox or Blender sessions. No game-editing automation is included.

## Your data

Source mode uses `vault/` next to this README. The standalone app uses
`~/Library/Application Support/Conectify/vault`. Each vault contains:

- `styles/<type>/<section>.md`: shared Markdown preferences.
- `games/<id>/<section>.md`: game-specific exceptions.
- `conectify.sqlite3`: games, references, tasks, activity, connection timestamps.
- `history/`: previous note versions saved by Conectify.
- `server.log`: local server startup/request logs when using the launcher.

You can edit the Markdown files in another editor. Changes appear in Conectify and in the agents' change feed. Conectify retains prior versions for its own writes; external editors do not participate in its write lock and should not write the same file simultaneously. Notes are limited to 60,000 characters to keep this a focused memory store.

**Back up your vault** downloads a ZIP with Markdown notes, note history, and a consistent SQLite backup. Linked files are represented by paths and are not included. Back those original folders up separately.

To restore: quit MCP clients and stop the local server first. Rename the current vault as a backup, create a new folder at the same vault location, and extract the ZIP contents there (including `conectify.sqlite3`, `styles/`, and `games/`). Then reopen Conectify and the clients. The exported `manifest.json` is a portable human-readable record; the app uses SQLite and Markdown as the live sources.

## Scope and privacy

The server binds to loopback only, rejects foreign host/origin requests, and requires a per-launch token for mutations. No telemetry or third-party requests are built in. Local files you ask an AI to read may be sent to that AI's provider as context under your existing account; local storage does not mean local model inference.

No API keys are required by Conectify. Claude/Codex use your own accounts and normal tool permissions. This build does not add Roblox or Blender API credentials.

The launcher starts one local background server. To stop it, find its PID with `lsof -iTCP:4317 -sTCP:LISTEN` and terminate that specific PID. Closing the browser alone does not stop the server. A native tray app, cloud sync, recursive search, automatic AI tagging, and automatic agent wakeups are not included.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v
```

Tests cover persistence, style isolation, optimistic conflicts, concurrent note writes, game context precedence, bounded responses, external Markdown changes, reference path boundaries, task handoffs, cursor pagination, stdio MCP, configuration merging, localhost access checks, backup creation, and media byte ranges.

Browser checks covered saving a preference, switching styles, creating a game, linking/browsing a reference folder, and a live shared-task update from a separate MCP process. Actual client activation requires restarting Claude Desktop and Codex after installation; protocol testing is not proof that both applications have loaded the integration.

Protocol references: [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle), [local Claude Desktop servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).

## Repository contents

Personal vaults, reference files, screenshots, logs, credentials, local client
settings, build environments, and compiled app bundles are excluded. Distribute
installers as GitHub Release assets rather than committing them to Git.

No project license file is included. Third-party components in packaged builds
retain their own licenses and required notices.
