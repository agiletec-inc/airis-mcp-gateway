#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


MANAGED_BLOCK_START = "# BEGIN AIRIS MANAGED BLOCK"
MANAGED_BLOCK_END = "# END AIRIS MANAGED BLOCK"


@dataclass
class Paths:
    registry_path: Path
    registry_dir: Path
    backup_dir: Path
    scan_root: Path
    codex_config_path: Path
    claude_desktop_config_path: Path
    claude_code_dir: Path
    gemini_dir: Path
    gateway_http_url: str
    gateway_sse_url: str
    manifest_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_registry(paths: Paths) -> dict[str, Any]:
    return {
        "version": 2,
        "gateway": {
            "streamableHttpEndpoint": paths.gateway_http_url,
            "sseEndpoint": paths.gateway_sse_url,
            "managed": True,
        },
        "clients": {
            "codex": {
                "managed": True,
                "configPath": str(paths.codex_config_path),
                "installed": paths.codex_config_path.exists(),
                "lastSyncedAt": None,
                "assetVersion": None,
                "assetInstallPath": str(paths.codex_config_path.parent / "airis"),
            },
            "claude_code": {
                "managed": True,
                "configPath": str(paths.claude_code_dir),
                "installed": paths.claude_code_dir.exists(),
                "lastSyncedAt": None,
                "assetVersion": None,
                "assetInstallPath": str(paths.claude_code_dir / "airis"),
            },
            "gemini_cli": {
                "managed": True,
                "configPath": str(paths.gemini_dir / "settings.json"),
                "installed": paths.gemini_dir.exists(),
                "lastSyncedAt": None,
                "assetVersion": None,
                "assetInstallPath": str(paths.gemini_dir / "airis"),
            },
            "claude_desktop": {
                "managed": False,
                "configPath": str(paths.claude_desktop_config_path),
                "installed": paths.claude_desktop_config_path.exists(),
                "lastSyncedAt": None,
            },
        },
        "policy": {
            "repoLocalMcpJson": "forbidden",
            "backupBeforeDelete": True,
            "mergeUserSettings": True,
        },
        "bootstrap": {
            "manifestPath": str(paths.manifest_path),
            "manifestVersion": None,
            "lastPlanAt": None,
            "lastApplyAt": None,
            "scanRoots": [],
            "assetBundles": [],
        },
        "servers": {},
        "imports": {},
    }


def load_manifest(paths: Paths) -> dict[str, Any]:
    with paths.manifest_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_registry(paths: Paths) -> tuple[dict[str, Any], bool]:
    if paths.registry_path.exists():
        with paths.registry_path.open(encoding="utf-8") as f:
            registry = json.load(f)
        changed = ensure_registry_shape(registry, paths)
        return registry, changed
    return default_registry(paths), True


def ensure_registry_shape(registry: dict[str, Any], paths: Paths) -> bool:
    changed = False
    if registry.get("version", 0) < 2:
        registry["version"] = 2
        changed = True
    gateway = registry.setdefault("gateway", {})
    if gateway.get("streamableHttpEndpoint") != paths.gateway_http_url:
        gateway["streamableHttpEndpoint"] = paths.gateway_http_url
        changed = True
    if gateway.get("sseEndpoint") != paths.gateway_sse_url:
        gateway["sseEndpoint"] = paths.gateway_sse_url
        changed = True
    clients = registry.setdefault("clients", {})
    expected = default_registry(paths)["clients"]
    for client_id, config in expected.items():
        current = clients.setdefault(client_id, config)
        for key, value in config.items():
            if key not in current:
                current[key] = value
                changed = True
    bootstrap = registry.setdefault("bootstrap", default_registry(paths)["bootstrap"])
    for key, value in default_registry(paths)["bootstrap"].items():
        if key not in bootstrap:
            bootstrap[key] = value
            changed = True
    registry.setdefault("policy", default_registry(paths)["policy"])
    registry.setdefault("servers", {})
    registry.setdefault("imports", {})
    return changed


def save_registry(paths: Paths, registry: dict[str, Any]) -> None:
    paths.registry_dir.mkdir(parents=True, exist_ok=True)
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    with paths.registry_path.open("w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)


def scan_repo_mcp_json(scan_root: Path, registry_dir: Path) -> list[Path]:
    skip_dirs = {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv",
        "dist", "build", ".next", "target", "__pycache__",
    }
    results: list[Path] = []
    for root, dirs, files in os.walk(scan_root):
        root_path = Path(root)
        dirs[:] = [
            d for d in dirs
            if d not in skip_dirs and not (root_path / d).resolve().as_posix().startswith(registry_dir.resolve().as_posix())
        ]
        if "mcp.json" in files:
            results.append(root_path / "mcp.json")
    return sorted(results)


def canonical(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": server.get("command", ""),
        "args": server.get("args", []),
        "env": server.get("env", {}),
        "enabled": server.get("enabled", True),
    }


def is_gateway_entry(name: str, server: dict[str, Any]) -> bool:
    if name == "airis-mcp-gateway":
        return True
    joined = " ".join([server.get("command", "")] + server.get("args", []))
    return "localhost:9400" in joined or "airis-mcp-gateway" in joined


def analyze_imports(paths: Paths, registry: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for source_path in scan_repo_mcp_json(paths.scan_root, paths.registry_dir):
        repo_path = str(source_path.parent)
        entry = {
            "repo": repo_path,
            "sourcePath": str(source_path),
            "results": [],
            "status": "imported",
        }
        try:
            with source_path.open(encoding="utf-8") as f:
                payload = json.load(f)
            mcp_servers = payload.get("mcpServers")
            if not isinstance(mcp_servers, dict):
                entry["status"] = "invalid"
                entry["results"].append(("invalid", "mcpServers"))
                results.append(entry)
                continue

            for name, server in mcp_servers.items():
                if not isinstance(server, dict):
                    entry["status"] = "invalid"
                    entry["results"].append(("invalid", name))
                    continue
                if is_gateway_entry(name, server):
                    entry["results"].append(("ignored-gateway-entry", name))
                    continue

                existing = registry["servers"].get(name)
                normalized = canonical(server)
                if existing is None:
                    entry["results"].append(("imported", name))
                else:
                    existing_normalized = canonical(existing)
                    if existing_normalized == normalized:
                        entry["results"].append(("duplicate", name))
                    else:
                        entry["status"] = "conflicted"
                        entry["results"].append(("conflicted", name))

            if not entry["results"]:
                entry["status"] = "empty"
        except Exception:
            entry["status"] = "invalid"
            entry["results"].append(("invalid", source_path.name))
        results.append(entry)
    return results


def update_installed_flags(paths: Paths, registry: dict[str, Any]) -> None:
    registry["clients"]["codex"]["installed"] = paths.codex_config_path.exists()
    registry["clients"]["claude_code"]["installed"] = paths.claude_code_dir.exists()
    registry["clients"]["gemini_cli"]["installed"] = paths.gemini_dir.exists()
    registry["clients"]["claude_desktop"]["installed"] = paths.claude_desktop_config_path.exists()


def backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = backup_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, candidate)
    return candidate


def merge_codex_config(paths: Paths, registry: dict[str, Any]) -> str:
    config_path = paths.codex_config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    block = (
        f"{MANAGED_BLOCK_START}\n"
        "[mcp_servers.airis-mcp-gateway]\n"
        f'url = "{paths.gateway_http_url}"\n'
        f"{MANAGED_BLOCK_END}\n"
    )

    previous = ""
    if config_path.exists():
        previous = config_path.read_text(encoding="utf-8")
        working = previous
        if MANAGED_BLOCK_START in working and MANAGED_BLOCK_END in working:
            start = working.index(MANAGED_BLOCK_START)
            end = working.index(MANAGED_BLOCK_END) + len(MANAGED_BLOCK_END)
            working = working[:start] + working[end:]

        lines = working.splitlines()
        filtered: list[str] = []
        skip_table = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if stripped == "[mcp_servers.airis-mcp-gateway]":
                    skip_table = True
                    continue
                if skip_table:
                    skip_table = False
            if skip_table:
                continue
            filtered.append(line)

        base = "\n".join(filtered).strip()
        new_content = (base + "\n\n" if base else "") + block
        if new_content != previous:
            backup_path = backup_file(config_path, paths.backup_dir)
            registry["clients"]["codex"]["lastBackupPath"] = str(backup_path)
            config_path.write_text(new_content, encoding="utf-8")
            return "updated"
        return "unchanged"

    config_path.write_text(block, encoding="utf-8")
    return "created"


def merge_gemini_settings(paths: Paths, registry: dict[str, Any]) -> str:
    settings_path = paths.gemini_dir / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if settings_path.exists():
        try:
            with settings_path.open(encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError:
            backup_path = backup_file(settings_path, paths.backup_dir)
            registry["clients"]["gemini_cli"]["lastBackupPath"] = str(backup_path)
            payload = {}
    payload.setdefault("mcpServers", {})
    server = payload["mcpServers"].get("airis-mcp-gateway", {})
    desired = {"url": paths.gateway_sse_url, "type": "sse"}
    changed = server != desired
    payload["mcpServers"]["airis-mcp-gateway"] = desired
    if changed or not settings_path.exists():
        if settings_path.exists():
            backup_path = backup_file(settings_path, paths.backup_dir)
            registry["clients"]["gemini_cli"]["lastBackupPath"] = str(backup_path)
        with settings_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return "updated" if changed else "created"
    return "unchanged"


def resolve_target_path(paths: Paths, client_id: str, relative: str) -> Path:
    base_map = {
        "codex": paths.codex_config_path.parent,
        "claude_code": paths.claude_code_dir,
        "gemini_cli": paths.gemini_dir,
    }
    return base_map[client_id] / relative


def deploy_assets(paths: Paths, registry: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    version = manifest["version"]
    actions: list[str] = []
    deployed_bundles: list[str] = []
    for client_id, spec in manifest["clients"].items():
        asset_root = resolve_target_path(paths, client_id, spec["assetRoot"])
        asset_root.mkdir(parents=True, exist_ok=True)
        meta = {"version": version, "assets": []}
        for asset in spec["assets"]:
            source = paths.manifest_path.parent / asset["source"]
            target = resolve_target_path(paths, client_id, asset["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            content = source.read_text(encoding="utf-8")
            previous = target.read_text(encoding="utf-8") if target.exists() else None
            if previous != content and target.exists():
                backup_path = backup_file(target, paths.backup_dir)
                registry["clients"][client_id]["lastBackupPath"] = str(backup_path)
            if previous != content:
                target.write_text(content, encoding="utf-8")
                actions.append(f"{client_id}: deployed {target}")
            meta["assets"].append(str(target))
        meta_path = asset_root / ".airis-bootstrap.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        registry["clients"][client_id]["assetVersion"] = version
        registry["clients"][client_id]["assetInstallPath"] = str(asset_root)
        registry["clients"][client_id]["lastSyncedAt"] = utc_now()
        deployed_bundles.append(client_id)
    registry["bootstrap"]["manifestVersion"] = version
    registry["bootstrap"]["assetBundles"] = deployed_bundles
    return actions


def apply_imports(paths: Paths, registry: dict[str, Any], analysis: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    for entry in analysis:
        source_path = Path(entry["sourcePath"])
        repo_path = entry["repo"]
        import_record = registry["imports"].get(repo_path, {})
        import_record.update(
            {
                "sourcePath": str(source_path),
                "status": entry["status"],
                "servers": {name: status for status, name in entry["results"]},
                "lastImportedAt": utc_now(),
                "backupPath": import_record.get("backupPath"),
                "cleanedAt": import_record.get("cleanedAt"),
            }
        )
        for status, name in entry["results"]:
            if status == "imported":
                with source_path.open(encoding="utf-8") as f:
                    payload = json.load(f)
                server = payload["mcpServers"][name]
                registry["servers"][name] = {
                    **canonical(server),
                    "source": "imported",
                    "origins": sorted(set(registry["servers"].get(name, {}).get("origins", []) + [str(source_path)])),
                }
                actions.append(f"imported: {name} <- {source_path}")
        registry["imports"][repo_path] = import_record

        if entry["status"] == "imported" and source_path.exists():
            backup_path = paths.backup_dir / f"{source_path.parent.name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-mcp.json"
            shutil.copy2(source_path, backup_path)
            source_path.unlink()
            import_record["backupPath"] = str(backup_path)
            import_record["cleanedAt"] = utc_now()
            actions.append(f"removed: {source_path}")
    return actions


def summarize_client_plan(paths: Paths) -> list[str]:
    return [
        f"codex config: {paths.codex_config_path}",
        f"claude assets: {paths.claude_code_dir}",
        f"gemini settings: {paths.gemini_dir / 'settings.json'}",
    ]


def cmd_init(paths: Paths, apply: bool) -> int:
    manifest = load_manifest(paths)
    registry, changed = load_registry(paths)
    update_installed_flags(paths, registry)
    analysis = analyze_imports(paths, registry)
    plan_lines = []
    if not paths.registry_path.exists():
        plan_lines.append(f"create registry: {paths.registry_path}")
    elif changed:
        plan_lines.append(f"upgrade registry schema: {paths.registry_path}")
    else:
        plan_lines.append(f"reuse registry: {paths.registry_path}")
    plan_lines.extend(summarize_client_plan(paths))

    if not apply:
        print("AIRIS MCP Init Plan")
        print("")
        print("Planned bootstrap:")
        for line in plan_lines:
            print(f"- {line}")
        print("")
        print(f"Manifest version: {manifest['version']}")
        print(f"Scan root: {paths.scan_root}")
        print("")
        if analysis:
            print("Repo-local mcp.json:")
            for entry in analysis:
                print(f"- {entry['sourcePath']}")
                for status, name in entry["results"]:
                    print(f"  {status}: {name}")
        else:
            print("Repo-local mcp.json: none found")
        print("")
        print("No files changed. Run with --apply to import configs, remove repo-local mcp.json,")
        print("and deploy AIRIS best-practice assets to Codex / Claude / Gemini.")
        return 0

    update_installed_flags(paths, registry)
    registry["bootstrap"]["lastPlanAt"] = utc_now()
    registry["bootstrap"]["scanRoots"] = sorted(set(registry["bootstrap"].get("scanRoots", []) + [str(paths.scan_root)]))
    import_actions = apply_imports(paths, registry, analysis)
    codex_status = merge_codex_config(paths, registry)
    gemini_status = merge_gemini_settings(paths, registry)
    asset_actions = deploy_assets(paths, registry, manifest)
    registry["clients"]["codex"]["lastSyncedAt"] = utc_now()
    registry["clients"]["gemini_cli"]["lastSyncedAt"] = utc_now()
    registry["clients"]["claude_code"]["lastSyncedAt"] = utc_now()
    registry["bootstrap"]["lastApplyAt"] = utc_now()
    save_registry(paths, registry)

    print("AIRIS MCP Init: APPLIED")
    print("")
    print(f"Registry: {paths.registry_path}")
    print(f"Manifest version: {manifest['version']}")
    print("")
    if import_actions:
        print("Registry import:")
        for action in import_actions:
            print(f"- {action}")
    else:
        print("Registry import: no repo-local mcp.json changes")
    print("")
    print("Client sync:")
    print(f"- codex: {codex_status}")
    print(f"- gemini: {gemini_status}")
    print("- claude: assets deployed")
    if asset_actions:
        print("")
        print("Assets:")
        for action in asset_actions:
            print(f"- {action}")
    return 0


def parse_toml_url(config_path: Path) -> str | None:
    if not config_path.exists() or tomllib is None:
        return None
    with config_path.open("rb") as f:
        payload = tomllib.load(f)
    return payload.get("mcp_servers", {}).get("airis-mcp-gateway", {}).get("url")


def cmd_doctor(paths: Paths) -> int:
    manifest = load_manifest(paths)
    if not paths.registry_path.exists():
        print("AIRIS MCP Doctor: FAILED")
        print("")
        print("Issues:")
        print(f"- registry not initialized: {paths.registry_path}")
        print("")
        print("Fix:")
        print(f"  airis-gateway init {paths.scan_root}")
        print(f"  airis-gateway init {paths.scan_root} --apply")
        return 1

    registry, _ = load_registry(paths)
    issues: list[str] = []
    notes: list[str] = []

    repo_local = scan_repo_mcp_json(paths.scan_root, paths.registry_dir)
    for path in repo_local:
        issues.append(f"repo-local mcp.json exists: {path}")

    for repo_path, entry in sorted(registry.get("imports", {}).items()):
        if entry.get("status") == "imported" and not entry.get("cleanedAt") and Path(entry.get("sourcePath", "")).exists():
            issues.append(f"imported but not cleaned: {entry.get('sourcePath')}")

    actual_codex_url = parse_toml_url(paths.codex_config_path)
    if not actual_codex_url:
        issues.append(f"Codex config missing mcp_servers.airis-mcp-gateway.url: {paths.codex_config_path}")
    elif actual_codex_url != paths.gateway_http_url:
        issues.append(f"Codex config points to stale endpoint: {actual_codex_url} (expected {paths.gateway_http_url})")

    gemini_settings = paths.gemini_dir / "settings.json"
    if not gemini_settings.exists():
        issues.append(f"Gemini settings missing: {gemini_settings}")
    else:
        with gemini_settings.open(encoding="utf-8") as f:
            payload = json.load(f)
        actual = payload.get("mcpServers", {}).get("airis-mcp-gateway", {}).get("url")
        if actual != paths.gateway_sse_url:
            issues.append(f"Gemini settings point to stale endpoint: {actual} (expected {paths.gateway_sse_url})")

    for client_id, spec in manifest["clients"].items():
        asset_root = resolve_target_path(paths, client_id, spec["assetRoot"])
        meta_path = asset_root / ".airis-bootstrap.json"
        if not meta_path.exists():
            issues.append(f"{client_id} AIRIS assets missing: {asset_root}")
            continue
        try:
            with meta_path.open(encoding="utf-8") as f:
                meta = json.load(f)
        except json.JSONDecodeError as exc:
            issues.append(f"{client_id} AIRIS asset metadata unreadable: {meta_path} ({exc})")
            continue
        if meta.get("version") != manifest["version"]:
            issues.append(f"{client_id} AIRIS assets out of date: {meta.get('version')} (expected {manifest['version']})")
        for asset_path in meta.get("assets", []):
            if not Path(asset_path).exists():
                issues.append(f"{client_id} AIRIS asset missing: {asset_path}")

    if paths.claude_desktop_config_path.exists():
        notes.append("Claude Desktop config is unmanaged by AIRIS and was not modified.")

    if issues:
        print("AIRIS MCP Doctor: FAILED")
        print("")
        print("Issues:")
        for issue in issues:
            print(f"- {issue}")
        print("")
        print("Fix:")
        print(f"  airis-gateway init {paths.scan_root} --apply")
        if notes:
            print("")
            print("Notes:")
            for note in notes:
                print(f"- {note}")
        return 1

    print("AIRIS MCP Doctor: OK")
    print("")
    print(f"Registry: {paths.registry_path}")
    print(f"Scanned: {paths.scan_root}")
    print(f"Manifest version: {manifest['version']}")
    if notes:
        print("")
        print("Notes:")
        for note in notes:
            print(f"- {note}")
    return 0


def build_paths(args: argparse.Namespace) -> Paths:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    return Paths(
        registry_path=Path(os.path.expanduser(args.registry_path)),
        registry_dir=Path(os.path.expanduser(args.registry_dir)),
        backup_dir=Path(os.path.expanduser(args.backup_dir)),
        scan_root=Path(os.path.expanduser(args.scan_root)).resolve(),
        codex_config_path=Path(os.path.expanduser(args.codex_config_path)),
        claude_desktop_config_path=Path(os.path.expanduser(args.claude_desktop_config_path)),
        claude_code_dir=Path(os.path.expanduser(args.claude_code_dir)),
        gemini_dir=Path(os.path.expanduser(args.gemini_dir)),
        gateway_http_url=args.gateway_http_url,
        gateway_sse_url=args.gateway_sse_url,
        manifest_path=repo_root / "config/bootstrap/assets-manifest.json",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "doctor"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scan-root", default=os.getcwd())
    parser.add_argument("--registry-path", required=True)
    parser.add_argument("--registry-dir", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--codex-config-path", required=True)
    parser.add_argument("--claude-desktop-config-path", required=True)
    parser.add_argument("--claude-code-dir", required=True)
    parser.add_argument("--gemini-dir", required=True)
    parser.add_argument("--gateway-http-url", required=True)
    parser.add_argument("--gateway-sse-url", required=True)
    args = parser.parse_args()

    paths = build_paths(args)
    if args.command == "init":
        return cmd_init(paths, args.apply)
    return cmd_doctor(paths)


if __name__ == "__main__":
    sys.exit(main())
