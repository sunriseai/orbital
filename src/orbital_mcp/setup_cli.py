from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import __version__
from .config import CONFIG_FILE, load_config
from .guidance import prompt_pack
from .profiles import HarnessRegistry, profile_execution_contract


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure and inspect Orbital.")
    parser.add_argument("--base-dir", default=".", help="Directory containing orbital.config.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Validate local Orbital setup.")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    init = subparsers.add_parser("init", help="Print setup status and next commands.")
    init.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    profiles = subparsers.add_parser("profiles", help="Inspect harness profiles.")
    profiles.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    profile_subcommands = profiles.add_subparsers(dest="profiles_command")
    detect = profile_subcommands.add_parser("detect", help="Detect configured secondary harnesses.")
    detect.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    mcp = subparsers.add_parser("mcp-config", help="Print or write primary-harness MCP config.")
    mcp.add_argument("--host", choices=["codex", "claude", "cursor", "generic"], default="generic")
    mcp.add_argument("--write", action="store_true", help="Write config under .orbital/mcp.")
    mcp.add_argument("--output", help="Explicit output path when --write is used.")

    pack = subparsers.add_parser("prompt-pack", help="Print or install primary-harness guidance.")
    pack_subcommands = pack.add_subparsers(dest="pack_command", required=True)
    pack_print = pack_subcommands.add_parser("print", help="Print host-specific guidance.")
    pack_print.add_argument("--host", choices=["codex", "claude", "cursor", "generic"], default="generic")
    pack_install = pack_subcommands.add_parser("install", help="Install host-specific guidance.")
    pack_install.add_argument("--host", choices=["codex", "claude", "cursor", "generic"], default="generic")
    pack_install.add_argument("--target", help="Explicit file path. Defaults under .orbital/prompt-packs.")

    smoke = subparsers.add_parser("smoke", help="Print the profile smoke-test command.")
    smoke.add_argument("--profile", default="opencode_acp_local")
    smoke.add_argument("--workdir", help="Optional target workdir for the smoke test.")

    args = parser.parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.command == "doctor":
        _emit(_doctor(base_dir), as_json=args.json)
    elif args.command == "init":
        _emit(_init_payload(base_dir), as_json=args.json)
    elif args.command == "profiles" and args.profiles_command in {None, "detect"}:
        _emit(_profiles_payload(base_dir), as_json=getattr(args, "json", False))
    elif args.command == "mcp-config":
        payload = mcp_config(args.host, base_dir)
        if args.write:
            target = Path(args.output).expanduser().resolve() if args.output else base_dir / ".orbital" / "mcp" / f"{args.host}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(str(target))
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.command == "prompt-pack" and args.pack_command == "print":
        print(prompt_pack(args.host), end="")
    elif args.command == "prompt-pack" and args.pack_command == "install":
        text = prompt_pack(args.host)
        target = (
            Path(args.target).expanduser().resolve()
            if args.target
            else base_dir / ".orbital" / "prompt-packs" / args.host / "ORBITAL_PROMPT_PACK.md"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(str(target))
    elif args.command == "smoke":
        command = ["orbital-mcp-smoke", "--profile", args.profile, "--base-dir", str(base_dir)]
        if args.workdir:
            command.extend(["--workdir", args.workdir])
        print(" ".join(command))


def mcp_config(host: str, base_dir: Path) -> dict[str, Any]:
    server = {
        "command": "orbital-mcp",
        "args": ["--base-dir", str(base_dir)],
    }
    if host == "cursor":
        return {"mcpServers": {"orbital": server}}
    if host == "codex":
        return {"mcp_servers": {"orbital": server}}
    if host == "claude":
        return {"mcpServers": {"orbital": server}}
    return {"mcpServers": {"orbital": server}}


def _doctor(base_dir: Path) -> dict[str, Any]:
    config = load_config(base_dir)
    registry = HarnessRegistry(config)
    profiles = []
    ready_count = 0
    for profile in registry.list_profiles():
        readiness = registry.readiness(profile, base_dir)
        ready_count += int(readiness.ready)
        profiles.append(
            {
                "id": profile.id,
                "display_name": profile.display_name,
                "adapter": profile.adapter,
                "runtime_family": profile.runtime_family,
                "auth_mode": profile.auth_mode,
                "cost_posture": profile.cost_posture,
                "ready": readiness.ready,
                "status": readiness.status,
                "missing_prerequisites": readiness.missing_prerequisites,
                "execution_contract": profile_execution_contract(profile),
            }
        )
    storage_root = base_dir / config.storage_root
    return {
        "name": "orbital",
        "version": __version__,
        "base_dir": str(base_dir),
        "config_path": str(base_dir / CONFIG_FILE),
        "config_exists": (base_dir / CONFIG_FILE).exists(),
        "storage_root": str(storage_root),
        "storage_parent_exists": storage_root.parent.exists(),
        "profile_count": len(profiles),
        "ready_profile_count": ready_count,
        "profiles": profiles,
        "recommended_next_steps": [
            "orbital mcp-config --host <host>",
            "orbital prompt-pack print --host <host>",
            "orbital smoke --profile <profile>",
        ],
    }


def _profiles_payload(base_dir: Path) -> dict[str, Any]:
    return {"profiles": _doctor(base_dir)["profiles"]}


def _init_payload(base_dir: Path) -> dict[str, Any]:
    doctor = _doctor(base_dir)
    return {
        "doctor": doctor,
        "mcp_config_example": mcp_config("generic", base_dir),
        "prompt_pack_command": "orbital prompt-pack print --host generic",
        "smoke_command": f"orbital-mcp-smoke --profile opencode_acp_local --base-dir {base_dir}",
    }


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Orbital {payload.get('version', '')}".strip())
    if "doctor" in payload:
        payload = payload["doctor"]
    print(f"Base dir: {payload.get('base_dir')}")
    print(f"Profiles ready: {payload.get('ready_profile_count', 0)}/{payload.get('profile_count', 0)}")
    for profile in payload.get("profiles", []):
        marker = "ready" if profile.get("ready") else "not_ready"
        detail = ", ".join(profile.get("missing_prerequisites", []))
        print(f"- {profile.get('id')}: {marker}" + (f" ({detail})" if detail else ""))
    steps = payload.get("recommended_next_steps") or []
    if steps:
        print("Next:")
        for step in steps:
            print(f"- {step}")


if __name__ == "__main__":
    main()
