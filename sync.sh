#!/usr/bin/env bash
# ./sync.sh          code -> Vapi (re-applies x-vapi-secret headers)
# ./sync.sh --pull   Vapi -> code -> Vapi, after publishing from the dashboard
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--pull" ]; then
  echo "== what the live assistant would change in build_assistant.py"
  out=$(python -m agent.pull_assistant)
  echo "$out"
  if echo "$out" | grep -q "already matches"; then
    echo "== nothing to pull"
  else
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

python -m agent.pull_assistant --show || echo "(set VAPI_ASSISTANT_ID in .env, then rerun)"
