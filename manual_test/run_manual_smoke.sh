#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ORBITAL_MANUAL_LOG_DIR:-$ROOT_DIR/manual_test/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/manual_smoke_$(date -u +%Y%m%dT%H%M%SZ).log"

FAILURES=0

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

run_optional_real_harness() {
  if [[ "${ORBITAL_RUN_REAL_HARNESS_SMOKE:-0}" != "1" ]]; then
    section "optional real-harness smoke"
    log "Skipped. Set ORBITAL_RUN_REAL_HARNESS_SMOKE=1 and ORBITAL_REAL_HARNESS_PROFILES=<profile[,profile]> to run."
    return 0
  fi
  run_cmd \
    "optional real-harness smoke" \
    env ORBITAL_RUN_REAL_HARNESS_SMOKE=1 \
      ORBITAL_REAL_HARNESS_PROFILES="${ORBITAL_REAL_HARNESS_PROFILES:-}" \
      ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS="${ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS:-120}" \
      PYTHONDONTWRITEBYTECODE=1 \
      python3 -m unittest discover -s tests -p 'test_validation_optional_smoke.py' -v
}

cleanup_repo_artifacts() {
  section "cleanup generated repo artifacts"
  find "$ROOT_DIR/src" "$ROOT_DIR/tests" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$ROOT_DIR" -maxdepth 1 -name '.tmp-test-*' -type d -prune -exec rm -rf {} +
  find "$ROOT_DIR" -maxdepth 1 -name '.orbital' -type d -prune -exec rm -rf {} +
  log "Cleanup complete."
}

main() {
  section "manual smoke metadata"
  log "root: $ROOT_DIR"
  log "log: $LOG_FILE"
  log "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "python: $(command -v python3 || true)"
  python3 --version 2>&1 | tee -a "$LOG_FILE"
  log "git_head: $(git -C "$ROOT_DIR" log --oneline --decorate -1 2>/dev/null || true)"

  run_cmd "git status before smoke" git status --short

  run_cmd "source-tree CLI help: orbital" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m orbital_mcp.setup_cli --help

  run_cmd "source-tree CLI doctor" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m orbital_mcp.setup_cli doctor --json

  run_cmd "source-tree CLI profiles" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m orbital_mcp.setup_cli profiles --json

  run_cmd "source-tree MCP config" \
    env PYTHONPATH="$ROOT_DIR/src" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m orbital_mcp.setup_cli mcp-config

  run_cmd "default unattended suite" \
    env PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -v

  run_cmd "syntax compile" \
    env PYTHONDONTWRITEBYTECODE=1 \
    python3 -B -m py_compile $(find "$ROOT_DIR/src" "$ROOT_DIR/tests" -name '*.py' -print)

  run_cmd "explicit MCP stdio transport smoke" \
    env PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -p 'test_validation_mcp_transport.py' -v

  run_cmd "explicit installed-package smoke" \
    env ORBITAL_RUN_PACKAGING_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -p 'test_validation_optional_smoke.py' -v

  run_optional_real_harness

  cleanup_repo_artifacts

  run_cmd "git status after cleanup" git status --short

  section "summary"
  if [[ $FAILURES -eq 0 ]]; then
    log "PASS: manual smoke completed with no command failures."
  else
    log "FAIL: manual smoke completed with $FAILURES command failure(s)."
  fi
  log "Review log: $LOG_FILE"
  return "$FAILURES"
}

main "$@"
