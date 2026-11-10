# Status and alerts cog

**Source:** `cynthia/bot/cogs/status.py` — `StatusCog`.

## Responsibility and state

`StatusCog` periodically gathers the bot's current activity, controller
connection, CV/hunt state, and daemon alerts. It refreshes user activity about
every three seconds and Discord presence about every 15 seconds. When a Drive
is available, it also writes status/activity files consumed by the local web
service and overlays.

It forwards owner-visible controller/CyNX and encounter alerts through the
bot's existing owner/channel services. It does not own capture, controller
network sockets, or homepage rendering: those remain with the corresponding
daemons and `cynthia/site/homepage.py`.

## Extension and tests

Keep status output derived from shared service state rather than a second
mutable copy. Ensure periodic tasks are cancelled on cog unload and a missing
Drive or optional daemon degrades to absent status instead of preventing bot
startup. The web service consumes these files; see
[`CYStream`](../daemons/cystream.md). Status behavior is tested in
`tests/test_status.py` and the API-facing cases in `tests/test_cystream_api.py`.
