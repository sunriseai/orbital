#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export ORBITAL_CODEX_ACP_PERMISSION_PROFILE="${ORBITAL_CODEX_ACP_PERMISSION_PROFILE:-codex_acp_official}"
export ORBITAL_CODEX_ACP_PERMISSION_LABEL="${ORBITAL_CODEX_ACP_PERMISSION_LABEL:-Codex official ACP permission}"
export ORBITAL_CODEX_ACP_PERMISSION_REQUIRED_COMMAND="${ORBITAL_CODEX_ACP_PERMISSION_REQUIRED_COMMAND:-npx}"
export ORBITAL_CODEX_ACP_PERMISSION_LOG_SLUG="${ORBITAL_CODEX_ACP_PERMISSION_LOG_SLUG:-local_codex_acp_official_permission_smoke}"
export ORBITAL_CODEX_ACP_PERMISSION_REQUIREMENT="${ORBITAL_CODEX_ACP_PERMISSION_REQUIREMENT:-You should have npx available and local Codex authentication ready. The first run may download @agentclientprotocol/codex-acp.}"

exec "$ROOT_DIR/tests/manual/run_manual_local_codex_acp_permission_smoke.sh"
