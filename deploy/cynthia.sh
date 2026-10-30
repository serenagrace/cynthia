#!/bin/bash
# Start Cynthia inside a detached tmux session. Installed to /usr/local/bin and
# called by cynthia.service. Attach later with: tmux attach -t cynthia
set -u

# Change to the directory containing your checkout and its `env/` virtualenv
CYNTHIA_DIR=/srv/usr/cynthia
SESSION=cynthia

# Do nothing if the session already exists
tmux has-session -t "$SESSION" 2>/dev/null && exit 0

tmux new-session -d -s "$SESSION"

# Window 0: the bot, restarted automatically by bin/run.sh
tmux send-keys -t "$SESSION:0" "cd $CYNTHIA_DIR" Enter
tmux send-keys -t "$SESSION:0" 'source env/bin/activate' Enter
tmux send-keys -t "$SESSION:0" 'bin/run.sh' Enter

# Window 1: a spare shell with the virtualenv active
tmux new-window -t "$SESSION:1" -n dev
tmux send-keys -t "$SESSION:1" "cd $CYNTHIA_DIR" Enter
tmux send-keys -t "$SESSION:1" 'source env/bin/activate' Enter

# Leave the bot window selected
tmux select-window -t "$SESSION:0"
