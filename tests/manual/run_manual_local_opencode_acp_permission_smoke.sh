#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ORBITAL_MANUAL_LOG_DIR:-$ROOT_DIR/tests/manual/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/local_opencode_acp_permission_smoke_$(date -u +%Y%m%dT%H%M%SZ).log"

PROFILE="opencode_acp_local_ask"
PROFILE_LABEL="OpenCode local ACP permission (ask config)"
REQUIRED_COMMAND="opencode"
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
  section "manual local ACP permission smoke: $PROFILE_LABEL"
  log "This script probes whether Orbital can receive, expose, approve, and record a real permission request from profile '$PROFILE'."
  log "This profile injects OPENCODE_CONFIG_CONTENT so OpenCode bash/edit actions are configured to ask instead of relying on prompt wording."
  log "It asks the secondary harness to create and verify PERMISSION_SMOKE.md via two separate shell commands, approves each allow-like adapter option, and records the resulting run evidence."
  log "You should have your local OpenCode command installed and authenticated before starting this script."
  log "This may launch a real local worker and may consume local subscription or configured model capacity."
  log "Expected pass condition: at least one ACP permission request is observed, approved, and the run completes."
  log "If the real harness completes the task without emitting an ACP permission request, the probe reports permission_capability_gap and exits successfully because Orbital had no permission event to mediate."
}

confirm_continue() {
  local answer
  printf '\nContinue with %s smoke? Type "yes" to continue: ' "$PROFILE_LABEL" | tee -a "$LOG_FILE"
  read -r answer
  printf '%s\n' "$answer" >> "$LOG_FILE"
  if [[ "$answer" != "yes" ]]; then
    log "Aborted by user before launching real local harness permission smoke."
    exit 2
  fi
}

setup_temp_dirs() {
  SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp/}orbital-local-opencode-acp-permission-smoke.XXXXXX")"
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

fail_summary() {
  cleanup_repo_artifacts
  run_cmd "git status after cleanup" git status --short
  section "summary"
  log "FAIL: manual $PROFILE permission smoke stopped before launch because prerequisite checks failed."
  log "Review log: $LOG_FILE"
  exit 1
}

require_command() {
  section "required command: $REQUIRED_COMMAND"
  local path
  path="$(command -v "$REQUIRED_COMMAND" || true)"
  if [[ -z "$path" ]]; then
    log "FAIL: required command '$REQUIRED_COMMAND' was not found on PATH."
    log "Install OpenCode or run this script from a shell where '$REQUIRED_COMMAND' is available, then rerun."
    FAILURES=$((FAILURES + 1))
    fail_summary
  fi
  log "$path"
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
  require_command

  run_cmd "source-tree doctor for local profile readiness" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m orbital_mcp.setup_cli --base-dir "$SMOKE_BASE" doctor --json

  run_cmd "manual $PROFILE permission round-trip smoke" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
      ORBITAL_PERMISSION_SMOKE_BASE="$SMOKE_BASE" \
      ORBITAL_PERMISSION_SMOKE_WORKDIR="$SMOKE_WORKDIR" \
      ORBITAL_PERMISSION_SMOKE_PROFILE="$PROFILE" \
      ORBITAL_PERMISSION_SMOKE_TIMEOUT="$TIMEOUT_SECONDS" \
      ORBITAL_PERMISSION_SMOKE_OBJECTIVE="Create PERMISSION_SMOKE.md by running this shell command rather than by direct file editing: echo \"OpenCode executed a shell-command permission smoke through Orbital MCP.\" > PERMISSION_SMOKE.md. Then verify it with this shell command: cat PERMISSION_SMOKE.md && ls -la PERMISSION_SMOKE.md. Run the create command and the verify command as two separate shell tool calls; do not combine them into one shell command." \
      python3 "$ROOT_DIR/tests/manual/run_permission_probe.py"

  cleanup_repo_artifacts
  run_cmd "git status after cleanup" git status --short

  section "summary"
  if [[ $FAILURES -eq 0 ]]; then
    log "PASS: manual $PROFILE permission smoke completed with no command failures. Review the probe result for pass vs permission_capability_gap."
  else
    log "FAIL: manual $PROFILE permission smoke completed with $FAILURES command failure(s)."
  fi
  log "Review log: $LOG_FILE"
  return "$FAILURES"
}

main "$@"
