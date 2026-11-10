# Discord features

This guide summarizes the non-streaming Discord features and their important
prerequisites. Slash commands may be hidden unless they are allowed by
`perms.yaml`; Discord application permissions and bot role permissions also
apply.

## Music

`/music` plays YouTube audio in the invoking user's voice channel. Add `music`
to `allowed_commands` in the global or relevant guild context before using the
group.

| Command | Purpose |
| --- | --- |
| `/music play <query>` | Play or queue a search, video, playlist, or album. No query resumes paused playback. |
| `/music search <query>` | Search and queue a match. |
| `/music pause`, `/skip` | Pause or skip the current song. |
| `/music stop` | Stop and clear the queue; remain in the voice channel. |
| `/music queue` | Show the current item and next ten. |
| `/music clear` | Clear upcoming items without stopping the current song. |
| `/music pin <link> [query]` | Prefer a fixed link for matching searches. |
| `/music pins`, `/unpin <number>` | List or remove this server's saved pins. |
| `/music join`, `/leave` | Join the caller's channel or stop and leave. |

Queues are per server and hold up to 100 songs. Playlists/albums are capped at
50 items. Search ranking favors exact title/artist, YouTube Music results, and
song-like lengths; it downranks covers, remixes, lives, and long mixes unless
the query asks for them. Direct links load one video; live streams cannot be
queued. Playback runs in the bot process because Discord voice connections
cannot be shared with a daemon.

Public videos need no login. Restricted videos and private playlists can use a
Premium session's exported Netscape `cookies.txt` via `YTDL_COOKIES_FILE`.
Do not commit cookies, and never enter a site password into the bot.
Install FFmpeg and Opus for voice playback.

## Permissions and server administration

The permission loader merges global and per-guild rules. The configured owner
is added to each permission list except `allowed_commands`; a guild context can
allow or deny users, roles, or guilds. See
[permission configuration](getting-started.md#configuration-and-permissions).

The `/auth` commands inspect and update these permission lists. `/cset` and
`/cget` inspect/change configuration; config-changing commands require
appropriate admin access. `/set_server_nickname` and `/set_server_avatar`
require Manage Server access and apply to the current server.

`/shell` is a privileged host-side command, not a sandbox. Only grant its
required access to trusted administrators. `/restart`, `/shutdown`, and
`/reboot` are lifecycle controls; do not make them generally available.
Commands for reloading application modules, cogs, and daemons are administrative
maintenance controls. Daemon reload is restricted to the reloadable daemons
supported by the manager.

## Member screening and moderation

When the bot has a role named `Bouncer`, the Bouncer cog inspects new members,
can post an interactive insight view in the configured channel, and greets
members that pass screening in `general-chat`. The cog may automatically kick
or ban based on its fixed suspicion rules (including flagged spammer status,
account age, digit-heavy names, default avatars, and whether the member
rejoined). Confirm that this behavior and its role permissions fit the server
before assigning `Bouncer`.

The interactive insight view supports moderator review and actions. Its
screens and automatic actions need the bot to have the necessary server and
channel permissions. Not assigning a `Bouncer` role disables the screening
listener's actions.

## Status, logs, and messaging

- `/about` shows version/startup information.
- Owner `/status` checks configured systemd services, network hosts, and drive
  availability. Hostnames come from `STATUS_HOSTS`; see
  [operations](operations.md#health-and-logs).
- `/loaded_modules` and `/loaded_commands` report command registration state.
- Owner `/set_status` and `/clear_status` manage the bot's custom status.
- `allowed_commands` and the `privileged` permission gate selected message
  responses and non-global commands.
- Drive-backed Discord logs and `OnMessage` rules use `cynthia.db`; saved rules
  load after the bot is ready and persist during cleanup.

The package also includes optional game-reference commands. `/pokemon` and
`/ev` require a `pokemonDB_dataset.csv` dataset in the drive and are disabled
when it is absent.
