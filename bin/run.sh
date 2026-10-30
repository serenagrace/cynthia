#!/bin/bash
# Run Cynthia as root (NXBT needs it) and restart it after crashes.
# Run from the repository root with the virtualenv at ./env. Arguments are
# passed to `cynthia`, e.g. bin/run.sh --config config.yaml --perms perms.yaml
while true; do
    sudo env/bin/cynthia "${@:1}"
    case $? in
        # Exit codes 0 and 1 are deliberate shutdowns; stop restarting
        0)
            break
            ;;
        1)
            break
            ;;
        # Anything else is a crash or a requested restart
        *)
            ;;
    esac
done
