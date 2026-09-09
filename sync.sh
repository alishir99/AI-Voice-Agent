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
  echo "== pulling the live provider stack into build_assistant.py"
  python -m agent.pull_assistant --write
fi

echo "== rebuilding assistant.json from prompt.md"
python -m agent.build_assistant

echo "== pushing to Vapi"
python -m agent.deploy_assistant

python -m agent.pull_assistant --show
