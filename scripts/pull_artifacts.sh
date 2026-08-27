#!/usr/bin/env bash
# Pull a batch's artifacts off the harness VM. Runs LOCALLY.
#
#   scripts/pull_artifacts.sh root@<ip> <ssh-port> experiments/exp5/results/glm-paired
#
# Generalized 2026-08-26: took an exp3 arm label and hardcoded experiments/exp3/results
# around it; now takes the results path directly, so it works for any experiment.
#
# tar-over-ssh rather than scp: scp/sftp hung indefinitely against vast.ai's SSH
# proxy in exp1 while plain `ssh host 'cmd'` worked throughout.
#
# exp2 destroyed both instances before pulling trajectories for 4 of 5 instances.
# That data is gone permanently. For exp3 the trajectories ARE the measurement.
set -euo pipefail

HOST="${1:?usage: pull_artifacts.sh <user@host> <port> <results-path>}"
PORT="${2:?}"
REMOTE_DIR="${3:?}"                                   # repo-relative, e.g. experiments/exp5/results/glm-paired
REMOTE_REPO="${REMOTE_REPO:-coding_agent_benchmark}"  # relative to the SSH user's $HOME
LOCAL_DIR="$(dirname "$REMOTE_DIR")"
NAME="$(basename "$REMOTE_DIR")"

mkdir -p "$LOCAL_DIR"
echo "Pulling ${REMOTE_DIR} from ${HOST}:${PORT} (repo: ~/${REMOTE_REPO}) ..."
# A non-interactive `ssh host 'cmd'` starts in $HOME, not the repo — cd explicitly rather
# than assuming REMOTE_DIR resolves. Found the hard way: silently pulled from ~/, not the repo.
ssh -p "$PORT" "$HOST" "cd ${REMOTE_REPO} && tar czf - -C \$(dirname ${REMOTE_DIR}) \$(basename ${REMOTE_DIR})" \
  | tar xzf - -C "$LOCAL_DIR"

echo "Pulled. Contents:"
find "${LOCAL_DIR}/${NAME}" -maxdepth 2 -type d | sort
echo
echo "Now run:  .venv/bin/python scripts/verify_artifacts.py ${LOCAL_DIR}/${NAME}"
echo "Do NOT run 'vastai destroy' until that exits 0."
