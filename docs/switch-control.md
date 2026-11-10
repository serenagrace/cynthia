# Switch control and macros

Cynthia's Switch integration separates controller transport from macro logic.
The NXBT daemon owns the selected controller session; Cynthia parses and queues
macros, evaluates scene conditions, and tracks playback. A Bluetooth adapter
is used by NXBT. For wired control, see [CyPi and cynx](cynx.md).

## Choose a controller

Run the Switch's Change Grip/Order menu before connecting:

| Command | Behavior |
| --- | --- |
| `/connect` | Use a discovered CyPi when available; retain an already active Bluetooth connection. |
| `/disconnect` | Disconnect the active controller. |
| `/nxbt connect` / `/nxbt disconnect` | Explicit Bluetooth control. |
| `/cynx connect` / `/cynx disconnect` | Explicit wired Pi control. |
| `/cynx status` | Show Pi network, version, uptime, USB and Switch state. |
| `/cynx restart` / `/cynx reboot` | Restart the service or reboot the Pi; owner-only. |
| `/switch` | Queue one button press. |
| `/stop`, `/pause`, `/unpause` | Stop or control macro playback. `/pause` pauses playback only; it does not disconnect the controller. |

Switch command access depends on the configured permissions. Generic connect
uses the `privileged` permission; disconnect uses `nxbt`. The `/cynx` lifecycle
commands are owner-only; other controller operations retain their existing
permission checks. Switching transports stops playback first. The default
command prefers a discovered Pi, but it does not switch away from an active
Bluetooth controller.

NXBT Bluetooth operation requires Linux Bluetooth tools and elevated host
access. It may restart `bluetoothd` with NXBT's runtime compatibility options,
which can interrupt other Bluetooth peripherals. The change is runtime rather
than a permanent edit to `/etc/bluetooth`. See the [NXBT fork](https://github.com/serenagrace/nxbt)
for adapter-specific setup.

## Define and run macros

Macros are line-oriented sequences. Post the body in Discord and use its
**Define Macro** context action. Start with a name line; names are
case-insensitive and spaces are normalized to underscores:

```text
$soft_reset
hold +
wait
tap A
```

Each subsequent line is one step. Buttons on a line are pressed together;
lines execute in order. Supported tokens are `a`, `b`, `x`, `y`, `l`, `r`,
`zl`, `zr`, `ls`, `rs`, `^`, `v`, `<`, `>`, `+`, `-`, `h`, and `c`.
The last group means directions, plus, minus, home, and capture. Joy-Con
shoulder buttons use `lsl`, `lsr`, `rsl`, and `rsr`. Tokens are
case-insensitive; numeric aliases are accepted (`6` for up and `.` for
right).

Timing prefixes:

| Prefix | Effect |
| --- | --- |
| `tap` | Press for 0.05 seconds. |
| `hold` | Press for 1 second. |
| `wait` | Pause for 1 second without pressing. |
| `(DOWN,UP)` | Set press and release timing in seconds, e.g. `(1.33,0.25) Bv`. |

Default presses use 0.15 seconds down and 0.15 seconds up. `noblock` is
accepted on a step for NXBT's nonblocking input behavior. The wired cynx
backend accepts the syntax but waits for every step to complete before sending
the next; it does not overlap or buffer button inputs.

Use another saved macro's name as a line to call it. Conditional steps use
`scene ? true_macro : false_macro`; the condition waits up to one second for a
matching capture scene. For example:

```text
home ? cleanup : zoom
```

Use `/get_macro` to inspect definitions and `/queue_macro` to add one to the
queue. The **Queue Macro** context action is also available. `$!name` replaces
an existing definition. The built-in `zoom` and `cleanup` macros are registered
by the bot. Avoid very short macro names: matching is substring-based, so
names such as `a` can collide with button tokens.

Macros live in `macros.json` under the configured drive directory. Without an
enabled drive they are not saved between restarts. The drive also holds
encounter logs and hunt statistics.

## Scene-aware automation

The CV daemon processes capture frames, compares them with bundled and
user-defined reference scenes, and publishes scores and input state to
automation and overlays. OCR can recognize selected game titles on the Switch
home screen; see [home-screen title OCR](development.md#home-screen-game-title-ocr)
for the limited catalog and how unknown text is handled. This is not universal
game-state or encounter detection: only implemented scene/game workflows are
recognized.

Supported BDSP hunt macros use conditional scene names such as `route_202`,
`roamer`, `bdsp_bag`, and `bdsp_run`. `examples/macros/` contains the Mesprit,
Cresselia, Shaymin, Arceus, and Darkrai workflows and their helper macros.
Define helper macros before defining a macro that calls them. The macros are
examples, not a guarantee of success in every game version or console state.

For scene matching, BDSP text box style 22 is recommended. Start from the
target game in a stable state and follow the relevant macro's expected starting
menu. `encounter_reset` restarts a looping macro after an encounter unless a
shiny-stop path has fired. Possible shiny detections pause automation and alert
the owner with a capture image; verify captures manually.

To try the sample Darkrai workflow, after defining the target and helpers:

```text
/connect
/set_hunt Darkrai
/queue_macro darkrai
/unpause
```

Change both hunt and macro names for another target. The optional
[`cyclient`](development.md#discord-rich-presence-client) can publish the
detected game/hunt to desktop Discord Rich Presence.

## Capture requirements

Scene-aware macros require a working capture card and CV daemon. Verify the
capture device with `v4l2-ctl --list-devices`; see
[operations](operations.md#hardware-checks) for udev and USB recovery. Capture
resolution is selected to cover active consumers. CV is capped at 30 fps even
when the web/OBS video rate is higher. Streaming details and scene overlays
are in [Video, OBS, and Twitch](streaming.md).
