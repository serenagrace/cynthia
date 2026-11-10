# Cynthia documentation

This documentation covers the behavior and operation of the Cynthia repository.
Optional hardware and integrations are called out where they are needed.
The [public documentation site](https://serenegrace.io/docs/cynthia/) provides
an online copy of these guides. It is published separately from the Cynthia
bot; its FastAPI service does not host this documentation.

## Start here

- [Getting started](getting-started.md): Linux/Python requirements, installation,
  runtime files, environment variables, permissions, and drive-backed state.
- [Configuration reference](configuration.md): media, controller, Twitch, and
  health-monitor settings beyond the initial setup.
- [Operations](operations.md): starting the bot, service deployment, backups,
  static documentation publishing, health checks, and troubleshooting.

## Feature guides

- [CyPi and cynx](cynx.md): wired Nintendo Switch control with the companion
  Raspberry Pi service, LAN discovery, acknowledgments, recovery, and setup.
- [Switch control and macros](switch-control.md): controller transports,
  permissions, macro syntax, scene-aware hunting, and sample macros.
- [Video, OBS, and Twitch](streaming.md): browser viewing, OBS, overlays,
  recording, Twitch authorization, title/category updates, and clips.
- [Discord features](discord-features.md): music, server utilities, moderation,
  status, and optional game-data lookups.
- [Local chat model and voice](local-chat.md): Ollama, Twitch chat behavior,
  safety controls, memory, TTS, and model settings.

## Code reference

- [Daemon processes](architecture/daemons/README.md): daemon inventory,
  lifecycle, inter-process communication, and one page per daemon module.
- [Discord cogs](architecture/cogs/README.md): automatically discovered
  event-driven modules, state ownership, background tasks, and tests.
- [Applications](architecture/applications/README.md): slash-command module
  discovery and the command-module catalog.
- [Utilities](architecture/utilities/README.md): shared services and helpers
  used across commands, cogs, and daemons.
- [Development and integrations](development.md): extension conventions,
  tests, formatting, HTTP APIs, and `cyclient`.

The [repository README](../README.md) is a concise project overview and quick
start. Example files are maintained in the repository root; the examples, not
this guide, are the source of truth for the complete default YAML structure.
