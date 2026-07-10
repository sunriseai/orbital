#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${ORBITAL_MANUAL_LOG_DIR:-$ROOT_DIR/tests/manual/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/local_opencode_acp_smoke_$(date -u +%Y%m%dT%H%M%SZ).log"

PROFILE="opencode_acp_local"
PROFILE_LABEL="OpenCode local ACP"
PROFILE_REQUIREMENT="You should have your local OpenCode command installed and authenticated before starting this script."
REQUIRED_COMMAND="opencode"
TIMEOUT_SECONDS="${ORBITAL_REAL_HARNESS_TIMEOUT_SECONDS:-120}"
FAILURES=0
SMOKE_TMP=""
SMOKE_BASE=""
SMOKE_WORKDIR=""
TOKEN_WORKDIR=""

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
  log "It records the OpenCode binary path, version, ACP help, and ACP initialize handshake before asking OpenCode to execute a small file-creation smoke task through Orbital."
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
  SMOKE_TMP="$(mktemp -d "${TMPDIR:-/tmp/}orbital-local-opencode-acp-smoke.XXXXXX")"
  SMOKE_BASE="$SMOKE_TMP/base"
  SMOKE_WORKDIR="$SMOKE_TMP/work"
  TOKEN_WORKDIR="$SMOKE_TMP/token-work"
  mkdir -p "$SMOKE_BASE" "$SMOKE_WORKDIR" "$TOKEN_WORKDIR"
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
  log "FAIL: manual $PROFILE smoke stopped before launch because prerequisite checks failed."
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

run_opencode_acp_initialize_preflight() {
  run_cmd "opencode command path" command -v opencode
  run_cmd "opencode version" opencode --version
  run_cmd "opencode ACP help" opencode acp --help
  run_cmd "opencode ACP initialize handshake" python3 - <<'PY'
import json
import select
import subprocess
import sys

proc = subprocess.Popen(
    ["opencode", "acp", "--pure"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
try:
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}}
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    proc.stdin.flush()

    assert proc.stdout is not None
    response = ""
    readable, _, _ = select.select([proc.stdout], [], [], 10)
    if readable:
        response = proc.stdout.readline().strip()

    if not response:
        print("ERROR: OpenCode ACP initialize did not return a response within 10 seconds.", file=sys.stderr)
        sys.exit(1)

    print(response)
    payload = json.loads(response)
    result = payload.get("result") or {}
    print(
        "summary: "
        f"protocolVersion={result.get('protocolVersion')} "
        f"agentName={(result.get('agentInfo') or {}).get('name')} "
        f"agentVersion={(result.get('agentInfo') or {}).get('version')}"
    )
    if result.get("protocolVersion") != 1:
        print(f"ERROR: expected ACP protocolVersion 1, got {result.get('protocolVersion')}", file=sys.stderr)
        sys.exit(1)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

    stderr = ""
    if proc.stderr is not None:
        stderr = proc.stderr.read()
    if stderr.strip():
        print("stderr:")
        print(stderr.strip())
PY
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
  log "token_workdir: $TOKEN_WORKDIR"

  run_cmd "git status before smoke" git status --short

  require_command
  run_opencode_acp_initialize_preflight

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

  run_cmd "manual $PROFILE canonical token telemetry smoke" \
    env PYTHONPATH="$ROOT_DIR/src" \
      PYTHONDONTWRITEBYTECODE=1 \
      ORBITAL_TOKEN_SMOKE_BASE="$SMOKE_BASE" \
      ORBITAL_TOKEN_SMOKE_WORKDIR="$TOKEN_WORKDIR" \
      ORBITAL_TOKEN_SMOKE_PROFILE="$PROFILE" \
      ORBITAL_TOKEN_SMOKE_TIMEOUT="$TIMEOUT_SECONDS" \
      python3 "$ROOT_DIR/tests/manual/run_token_probe.py"

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
