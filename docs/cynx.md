# Wired Switch control with CyNX

[CyNX](https://github.com/serenagrace/cynx) is Cynthia's Raspberry Pi companion for
wired Nintendo Switch input. Install and maintain the Pi from that repository.
This guide covers the Cynthia side and the contract between the two services.

## Architecture

```text
Discord commands, macros, and computer vision
                    Cynthia
                       |
              Wired Ethernet LAN
              /                \
     Command and heartbeat    Macro steps
          TCP 3140             TCP 3141
              \                /
                      CyNX
                       |
                USB-C gadget port
                       |
                  Switch dock
```

UDP discovery uses the same port number as the command TCP listener. No fixed Pi
address is required. Discovery normally stays on the local broadcast domain;
it does not scan unrelated subnets or traverse routers.

Cynthia owns macro expansion, conditional scene checks, and playback position.
The Pi receives one expanded input step at a time, executes its hold and release
timing locally, and reports completion. It does not need Cynthia's drive or
Discord credentials.

## Prepare the Pi

Follow the [CyNX installation instructions](https://github.com/serenagrace/cynx/blob/development/docs/installation.md)
to configure Raspberry Pi OS, USB peripheral mode, and the systemd service.
A Pi 4B uses its USB-C port for gadget data as well as power. A suitable powered
data hub must connect upstream to the Switch dock and downstream to the Pi.
A charging-only port or cable cannot carry controller input. Do not assume the
dock alone can reliably power a Pi 4B.

Keep the Switch awake. This design does not establish USB wake-from-sleep
support. Test controller assignment and the recovery menu sequence on the
specific console and game before unattended automation.

## Configure Cynthia

Add these values to Cynthia's `config.yaml`:

```yaml
cynx_enabled: true
cynx_auto_connect: true
cynx_command_port: 3140
cynx_macro_port: 3141
cynx_heartbeat_interval: 1.0
cynx_discovery_timeout: 1.0
cynx_discovery_interval: 2.0
```

Configure the same command and macro port numbers in CyNX's `config.yaml`.
Allow command TCP, macro TCP, and command-port UDP discovery only on the trusted
LAN. Do not expose these listeners through an Internet-facing port forward.

Set the same `CYNX_PASSPHRASE` in each project's working-directory `.env`.
The real files are gitignored; they must never be copied to Cynthia's drive.
Blank values on both endpoints disable authentication. This is shared-passphrase
authentication over plaintext LAN TCP, not transport encryption. Use a private
network or a separate secure tunnel when the LAN is not trusted.
Restart both applications after changing their port or dotenv settings.

Upgrade Cynthia and CyNX together: discovery and handshake responses now use
`identity: "cynx"`, Cynthia's YAML settings use the `cynx_` prefix, and both
working-directory dotenv files use `CYNX_PASSPHRASE`. No legacy aliases remain.
Stop both services before renaming configuration keys and updating the
companion, then restart both. Keep the existing port numbers and passphrase
values. Hostnames do not need to change. To roll back, restore both previous
versions and their matching configuration names together.

The Pi accepts only its owning authenticated session's command and macro
channels. `/cynx connect`, `/cynx status`, and `/cynx disconnect` use those
same channels. Explicit disconnect runs controller cleanup and leaves USB
detached, but keeps the authenticated network session, owner, and channels
available while USB is idle. Intentional Cynthia shutdown then sends `release`
and waits for its acknowledgment before closing either channel, so this is not
reported as network loss. Unexpected loss past reconnect grace releases the
lease after recovery and detach. Changing an address
through DHCP does not require editing Cynthia's config, although a host
address change during an existing session may require a new session after the
old lease is released.

When fresh CV confidently identifies Change Grip/Order, intentional disconnect
and release skip the menu-navigation inputs: the Pi still cancels work,
neutralizes the controller, and detaches USB. Bluetooth cleanup uses the same
CV gate. Missing, stale, or uncertain CV keeps the normal cleanup sequence.
Unexpected Pi network-loss recovery still runs its normal cleanup because the
Pi has no independent video feed.

## Automatic connection and menu setup

`cynx_auto_connect: true` enables startup USB connection. Set it to `false` in
Cynthia's `config.yaml` to leave USB idle until `/cynx connect` or `/connect`
is requested. Discovery and `/cynx status` still work. An explicitly requested
connection remains eligible for normal reconnect recovery until disconnected.
Restart Cynthia after changing the setting.

After each wired connection, including startup and reconnects, the controller
worker waits for fresh CV results. Only a confident `change_grip_order` scene
match runs `A`, wait, `A`, wait, `B`, wait, `HOME`, using the normal NXBT input
timings. Other screens, stale frames, and unavailable CV never trigger these
inputs. The sequence finishes before queued macros resume, while the separate
CyNX daemon continues heartbeats.

## Commands

| Command | Behavior |
| --- | --- |
| `/connect` | Prefer a discovered Pi; retain an active Bluetooth controller. Use Bluetooth when no Pi is available. |
| `/disconnect` | Disconnect the active controller. |
| `/cynx connect` | Explicitly select wired Pi control. Switching transports stops queued playback first. |
| `/cynx disconnect` | Clear Pi playback, run the recovery menu sequence, and detach USB while retaining the authenticated network session. |
| `/cynx status` | Show Pi availability, version, uptime, USB detection, spoofing, and Switch connection state. |
| `/cynx restart` | Ask the Pi to restart CyNX. Owner-only. |
| `/cynx reboot` | Ask the Pi to reboot. Owner-only. |
| `/nxbt connect` | Explicitly select Bluetooth, disconnecting an active Pi controller first. |
| `/nxbt disconnect` | Disconnect Bluetooth without disconnecting an active Pi controller. |
| `/stop` | Cancel active playback and invalidate queued macros; send an immediate Pi stop when available. |
| `/pause` | Pause macro playback only; it does not disconnect a controller. |

Existing controller permissions continue to apply. A network connection to the
Pi is distinct from an active USB controller connection.

## Acknowledgments and recovery

Each raw input step has a session-scoped, increasing identifier. The Pi sends
an `accepted` acknowledgment, then a `completed` notification after the hold
and release wait finish. Cynthia validates the identifier, session, and event
order before advancing. There is only one in-flight step from Cynthia.

The Pi retains recent completion records. If a completion response is lost,
reconnecting to the same session retrieves the recorded outcome rather than
replaying a completed input. It finishes an already accepted step during brief
network loss, releases buttons, and pauses before further work.

After the configured reconnect grace expires, the Pi cancels unfinished work
and clears its queue. Explicit Pi disconnect and grace-expired connection loss
use the same input sequence as Cynthia's built-in NXBT `cleanup` macro:
`H`, `wait`, `V`, six `>`, `hold A`, `noblock A`. `H` is Home, `V` is down, and
`>` is right. The wait is two seconds; the complete sequence has 5.85 seconds
of configured input timing. The Pi then detaches USB. Cynthia waits for the
bounded recovery window before Bluetooth takeover, performs the normal
Bluetooth connection setup, and resumes the last uncompleted step. It does
not opportunistically switch an active Bluetooth hunt back to USB.

Completion confirms execution of timed USB reports, not a game's interpretation
of those reports. If a step is interrupted before completion, replay can repeat
a partial game action. Service restarts and power loss also discard in-memory
completion records. There is no transactional, exactly-once guarantee for
physical controller effects.

The cleanup sequence depends on the console's menu layout and current screen.
If USB itself disappears, software cannot navigate the Switch through that
broken connection. Bluetooth fallback still depends on a working adapter,
pairing, and a console state from which normal setup can reopen the game.

## Logging and owner alerts

CyNX keeps a rotating local log at `logs/cynx.log` in its working directory and
also writes service output to the systemd journal. The Pi remains diagnosable
when Cynthia or the LAN is unavailable. Authentication values must not appear
in either log.

Recent error summaries accompany status responses. Cynthia remembers up to
256 error IDs per worker run and records each new event in its full local log.
Owner alerts throttle identical messages for 60 seconds, even when separate
events have different IDs. The alert queue holds at most 100 messages, so an
unavailable Discord connection cannot grow memory indefinitely.

The network error history is bounded and in memory; use the Pi's local log for
older errors or errors preceding a service restart.

## Troubleshooting

1. Use `/cynx status` to distinguish LAN availability from USB spoofing.
2. Verify that both configurations use matching ports and dotenv passphrases.
3. Check that the firewall permits UDP discovery and both TCP ports on the LAN.
4. On the Pi, inspect `systemctl status cynx.service` and
   `journalctl -u cynx.service -n 100 --no-pager`.
5. Check `/sys/class/udc/*/state`. `configured` indicates USB enumeration;
   it does not prove that the game assigned this controller to the active player.
6. If the Pi is healthy but input is not accepted, check the data cable,
   powered hub, console sleep state, and Change Grip/Order screen.
