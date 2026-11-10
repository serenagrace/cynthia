# Member-screening cog

**Source:** `cynthia/bot/cogs/bouncer.py` — `BouncerCog`; screening decisions
are implemented by `cynthia/utils/insights.py`.

## Responsibility and flow

`BouncerCog` listens for member join/remove events. It only acts in guilds
where a role named `Bouncer` is configured, then uses `InsightView` to gather
the member's server-visible profile signals. Depending on the result and
configured suspicion threshold, the bot can greet the member, take the
configured moderation action, or leave the decision to a moderator.

The cog uses existing guild and permission context; it does not install a
separate moderation policy. Keep role and action checks explicit: a missing
role or unavailable permission should not be interpreted as approval to ban
or kick.

## Extension and tests

Add scoring or user-facing review states in `InsightView`; keep event
registration, role gating, and applying a guild action in this cog. Avoid
blocking Discord event handlers on external/profile lookups. Screening
behavior and thresholds are covered by `tests/test_insights.py`; use
`docs/discord-features.md` for operator-facing behavior.
