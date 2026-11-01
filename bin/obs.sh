#!/bin/bash
# Run OBS headless and restart it after crashes.
#
# OBS renders on the GPU when a headless NVIDIA Xorg server can be started
# (deploy/xorg-headless.conf); otherwise it falls back to Xvfb, where OpenGL is
# software-rendered and the scene alone can take several CPU cores.
# Enable the WebSocket server (Tools > WebSocket Server Settings) or set
# "server_enabled" in ~/.config/obs-studio/plugin_config/obs-websocket/config.json.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPU_DISPLAY="${OBS_GPU_DISPLAY:-:98}"

start_gpu_display() {
    command -v Xorg >/dev/null && command -v nvidia-smi >/dev/null || return 1
    [ -e "/tmp/.X11-unix/X${GPU_DISPLAY#:}" ] && return 0
    local sudo=""
    [ "$(id -u)" -ne 0 ] && sudo="sudo -n"
    $sudo Xorg "$GPU_DISPLAY" -config "$DIR/deploy/xorg-headless.conf" -noreset -ac \
        -novtswitch -sharevts -nolisten tcp -logfile /tmp/xorg-headless.log \
        >/dev/null 2>&1 &
    for _ in $(seq 20); do
        [ -e "/tmp/.X11-unix/X${GPU_DISPLAY#:}" ] && return 0
        sleep 0.5
    done
    return 1
}

while true; do
    # A stale sentinel makes OBS block on a "safe mode" dialog nobody can click
    rm -rf "$HOME/.config/obs-studio/.sentinel"
    if start_gpu_display; then
        DISPLAY="$GPU_DISPLAY" obs --disable-shutdown-check --minimize-to-tray
    else
        echo "No GPU display available; using Xvfb with software rendering" >&2
        xvfb-run -a -s "-screen 0 1920x1080x24" obs --disable-shutdown-check --minimize-to-tray
    fi
    case $? in
        0|130|143)
            break
            ;;
    esac
    sleep 5
done
