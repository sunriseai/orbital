#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export ORBITAL_CODEX_ACP_SMOKE_PROFILE="${ORBITAL_CODEX_ACP_SMOKE_PROFILE:-codex_acp_official}"
export ORBITAL_CODEX_ACP_SMOKE_LABEL="${ORBITAL_CODEX_ACP_SMOKE_LABEL:-Codex official ACP}"
export ORBITAL_CODEX_ACP_SMOKE_REQUIRED_COMMAND="${ORBITAL_CODEX_ACP_SMOKE_REQUIRED_COMMAND:-npx}"
export ORBITAL_CODEX_ACP_SMOKE_LOG_SLUG="${ORBITAL_CODEX_ACP_SMOKE_LOG_SLUG:-local_codex_acp_official_smoke}"
export ORBITAL_CODEX_ACP_SMOKE_REQUIREMENT="${ORBITAL_CODEX_ACP_SMOKE_REQUIREMENT:-You should have npx available and local Codex authentication ready. The first run may download @agentclientprotocol/codex-acp.}"

exec "$ROOT_DIR/tests/manual/run_manual_local_codex_acp_smoke.sh"
