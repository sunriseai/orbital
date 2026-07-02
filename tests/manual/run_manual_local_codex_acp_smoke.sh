#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ORBITAL_MANUAL_LOG_DIR:-$ROOT_DIR/tests/manual/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/local_codex_acp_smoke_$(date -u +%Y%m%dT%H%M%SZ).log"

PROFILE="codex_acp_local"
PROFILE_LABEL="Codex local ACP"
PROFILE_REQUIREMENT="You should have your local Codex command installed and authenticated before starting this script."
TIMEOUT_SECONDS="${ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS:-120}"
FAILURES=0
SMOKE_TMP=""
SMOKE_BASE=""
SMOKE_WORKDIR=""

log() {
  printf '%s\n' "$*" | tee -a "$LOG_FILE"
}

section() {
  log ""
  log "==== $* ===="
}

run_cmd() {
  local label="$1"
  shift
  section "$label"
  log "+ $*"
  (
    cd "$ROOT_DIR"
    "$@"
  ) 2>&1 | tee -a "$LOG_FILE"
  local status=${PIPESTATUS[0]}
  log "[exit $status] $label"
  if [[ $status -ne 0 ]]; then
    FAILURES=$((FAILURES + 1))
  fi
  return "$status"
}

print_intro() {
  section "manual local ACP smoke: $PROFILE_LABEL"
  log "This script tests Orbital's real local ACP path for profile '$PROFILE'."
  log "It runs 'orbital doctor' from the source tree, then asks that one local harness to execute a small file-creation smoke task through Orbital."
  log "$PROFILE_REQUIREMENT"
  log "It may launch a real local worker and may consume local subscription or configured model capacity."
  log "This smoke should not require external approvals. If the local harness opens login, onboarding, or an unexpected approval prompt, stop and complete that setup before rerunning."
}

confirm_continue() {
  local answer
  printf '\nContinue with %s smoke? Type "yes" to continue: ' "$PROFILE_LABEL" | tee -a "$LOG_FILE"
  read -r answer
  printf '%s\n' "$answer" >> "$LOG_FILE"
  if [[ "$answer" != "yes" ]]; then
    log "Aborted by user before launching real local harness smoke."
    exit 2
  fi
}

setup_temp_dirs() {
  SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp/}orbital-local-codex-acp-smoke.XXXXXX")"
  SMOKE_BASE="$SMOKE_TMP/base"
  SMOKE_WORKDIR="$SMOKE_TMP/work"
  mkdir -p "$SMOKE_BASE" "$SMOKE_WORKDIR"
}

cleanup_repo_artifacts() {
  section "cleanup generated repo artifacts"
  find "$ROOT_DIR/src" "$ROOT_DIR/tests" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$ROOT_DIR" -maxdepth 1 -name '.tmp-test-*' -type d -prune -exec rm -rf {} +
  if [[ -n "$SMOKE_TMP" && -d "$SMOKE_TMP" ]]; then
    rm -rf "$SMOKE_TMP"
  fi
  log "Cleanup complete."
}

main() {
  print_intro
  confirm_continue
  setup_temp_dirs
  log "root: $ROOT_DIR"
  log "log: $LOG_FILE"
  log "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "python: $(command -v python3 || true)"
  python3 --version 2>&1 | tee -a "$LOG_FILE"
  log "git_head: $(git -C "$ROOT_DIR" log --oneline --decorate -1 2>/dev/null || true)"
  log "timeout_seconds: $TIMEOUT_SECONDS"
  log "smoke_base: $SMOKE_BASE"
  log "smoke_workdir: $SMOKE_WORKDIR"

  run_cmd "git status before smoke" git status --short

  run_cmd "source-tree doctor for local profile readiness" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m orbital_mcp.setup_cli --base-dir "$SMOKE_BASE" doctor --json

  run_cmd "manual $PROFILE real-harness smoke" \
    env PYTHONPATH="$ROOT_DIR/src" \
      PYTHONDONTWRITEBYTECODE=1 \
      python3 -m orbital_mcp.smoke \
        --base-dir "$SMOKE_BASE" \
        --profile "$PROFILE" \
        --workdir "$SMOKE_WORKDIR" \
        --timeout-seconds "$TIMEOUT_SECONDS"

  cleanup_repo_artifacts

  run_cmd "git status after cleanup" git status --short

  section "summary"
  if [[ $FAILURES -eq 0 ]]; then
    log "PASS: manual $PROFILE smoke completed with no command failures."
  else
    log "FAIL: manual $PROFILE smoke completed with $FAILURES command failure(s)."
  fi
  log "Review log: $LOG_FILE"
  return "$FAILURES"
}

main "$@"
