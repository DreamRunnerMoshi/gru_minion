#!/usr/bin/env bash
# Pull every exp3 artifact off the harness VM. Runs LOCALLY.
#
#   scripts/pull_artifacts.sh root@<ip> <ssh-port> B
#
# tar-over-ssh rather than scp: scp/sftp hung indefinitely against vast.ai's SSH
# proxy in exp1 while plain `ssh host 'cmd'` worked throughout.
#
# exp2 destroyed both instances before pulling trajectories for 4 of 5 instances.
# That data is gone permanently. For exp3 the trajectories ARE the measurement.
set -euo pipefail

HOST="${1:?usage: pull_artifacts.sh <user@host> <port> <arm>}"
PORT="${2:?}"
ARM="${3:?}"
REMOTE_DIR="experiments/exp3/results/${ARM}"
LOCAL_DIR="experiments/exp3/results"

mkdir -p "$LOCAL_DIR"
echo "Pulling ${REMOTE_DIR} from ${HOST}:${PORT} ..."
ssh -p "$PORT" "$HOST" "tar czf - -C \$(dirname ${REMOTE_DIR}) \$(basename ${REMOTE_DIR})" \
  | tar xzf - -C "$LOCAL_DIR"

echo "Pulled. Contents:"
find "${LOCAL_DIR}/${ARM}" -maxdepth 2 -type d | sort
echo
echo "Now run:  .venv/bin/python scripts/verify_artifacts.py ${LOCAL_DIR}/${ARM}"
echo "Do NOT run 'vastai destroy' until that exits 0."
