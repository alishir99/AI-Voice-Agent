#!/usr/bin/env bash
# Push the assistant config to Vapi. Run from the repo root.
#
#   ./sync.sh            code -> Vapi        (after editing build_assistant.py or prompt.md)
#   ./sync.sh --pull     Vapi -> code -> Vapi  (after publishing from the Composer)
#
# Either way the x-vapi-secret headers are re-applied, which a Composer publish drops.
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--pull" ]; then
  echo "== what the live assistant would change in build_assistant.py"
  out=$(python -m agent.pull_assistant)
  echo "$out"
  if echo "$out" | grep -q "already matches"; then
    echo "== nothing to pull"
  else
    # Confirm, because a pull run at the wrong moment overwrites changes you just
    # pulled from git with the older values still live at Vapi.
    printf "\napply these to build_assistant.py? [y/N] "
    read -r answer
    case "$answer" in
      y|Y|yes) python -m agent.pull_assistant --write --force ;;
      *) echo "aborted, nothing written"; exit 1 ;;
    esac
  fi
fi

echo "== rebuilding assistant.json from prompt.md"
python -m agent.build_assistant

echo "== pushing to Vapi"
python -m agent.deploy_assistant

python -m agent.pull_assistant --show
