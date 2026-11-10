# Cynthia

[![Tests](https://github.com/serenagrace/cynthia/actions/workflows/tests.yml/badge.svg)](https://github.com/serenagrace/cynthia/actions/workflows/tests.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)

**Customizable Internal Network Task Handler + Interactive Assistant**

Cynthia is a Python Discord bot for server tools, Nintendo Switch control and
automation, game capture, and optional streaming and chat integrations.

## What it does

- Control a Switch over Bluetooth with NXBT or wired USB through the
  [CyNX Raspberry Pi service](https://github.com/serenagrace/cynx).
- Create and run macros, inspect game scenes, and automate supported hunts.
- Serve a live capture feed and integrate it with OBS and Twitch.
- Add Discord music playback, server utilities, and an optional local Ollama
  chat persona.
- Expose status APIs and optional desktop Discord Rich Presence.

Hardware, credentials, permissions, and optional integrations are required for
some features. See the [feature guides](docs/README.md) for scope and setup.

## Quick start

Cynthia requires Linux and Python 3.11. The PaddlePaddle OCR dependency does not
support other Python versions in this project.

```bash
python3.11 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[cpu]"
cp .env.example .env
cp config.example.yaml config.yaml
cp perms.example.yaml perms.yaml
```

Set `DISCORD_BOT_TOKEN` in `.env`, set the owner ID and drive path in
`config.yaml`, and configure command permissions in `perms.yaml`. Then run:

```bash
bin/run.sh --config config.yaml --perms perms.yaml
```

`bin/run.sh` uses `sudo` because NXBT Bluetooth control needs elevated host
access. For GPU OCR, install the `gpu` extra instead of `cpu`; see
[installation and configuration](docs/getting-started.md).

For USB control, also install [CyNX](https://github.com/serenagrace/cynx) and
follow the [wired-controller setup guide](docs/cynx.md).

Optional Python tools: `python -m pip install -e ".[dev]"` adds testing and
formatting tools; `python -m pip install -e ".[cyclient]"` adds desktop Rich
Presence dependencies. Neither replaces the required `cpu` or `gpu` choice.
See [optional packages and services](docs/getting-started.md#optional-python-packages)
for explicit OBS, WebRTC, Ollama, voice, and standalone desktop-client setup.

## Documentation

Start with [installation and getting started](docs/getting-started.md), then
browse the [GitHub documentation index](docs/README.md) or the
[public documentation site](https://serenegrace.io/docs/cynthia/). Guides cover
configuration, operations, features, and a code-oriented reference for every
daemon and discovered cog. Documentation is published separately from the
Cynthia bot; its local API does not host it.

## Development

```bash
python -m pytest -m "not discord_live"
bin/black.sh
```

See [development and integrations](docs/development.md) for the architecture,
extension conventions, test setup, API, and optional `cyclient` utility.

## License

Cynthia is licensed under the [GNU General Public License v3.0 or later](LICENSE).
