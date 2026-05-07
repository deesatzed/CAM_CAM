"""Critical-slot static analysis helpers for CAM-SEQ.

This module intentionally treats Semgrep and CodeQL as optional integrations.
If the tool or required local configuration is unavailable, the result is
returned honestly so reviewed runs can require an explicit waiver.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any


def _codeql_mode() -> str:
    mode = os.getenv("CLAW_CODEQL_MODE", "deferred").strip().lower()
    return mode if mode in {"off", "deferred", "required"} else "deferred"


def _candidate_scan_paths(workspace_dir: str, file_paths: list[str]) -> list[str]:
    workspace = Path(workspace_dir)
    selected: list[str] = []
    for rel in file_paths:
        if not rel:
            continue
        path = workspace / rel
        if path.exists():
            selected.append(str(path))
    return selected or [str(workspace)]


async def _run_command(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _default_semgrep_config(workspace_dir: str) -> str | None:
    candidate = Path(workspace_dir) / "security" / "semgrep.yml"
    return str(candidate) if candidate.exists() else None


def _docker_semgrep_runner(workspace_dir: str) -> str | None:
    candidate = Path(workspace_dir) / "scripts" / "camseq_semgrep.sh"
    if candidate.exists():
        return str(candidate)
    return None


def get_security_lane_status(workspace_dir: str) -> dict[str, Any]:
    """Return static-analysis lane configuration without executing scanners."""
    semgrep_config = os.getenv("CLAW_SEMGREP_CONFIG") or _default_semgrep_config(workspace_dir)
    semgrep_runner = os.getenv("CLAW_SEMGREP_RUNNER") or _docker_semgrep_runner(workspace_dir)
    codeql_database = os.getenv("CLAW_CODEQL_DATABASE")
    codeql_queries = os.getenv("CLAW_CODEQL_QUERIES")
    return {
        "semgrep": {
            "cli_available": shutil.which("semgrep") is not None,
            "docker_available": shutil.which("docker") is not None,
            "docker_runner_available": bool(semgrep_runner),
            "docker_runner_path": semgrep_runner,
            "config_available": bool(semgrep_config),
            "config_path": semgrep_config,
            "use_docker": os.getenv("CLAW_SECURITY_USE_DOCKER", "").lower() in {"1", "true", "yes"},
        },
        "codeql": {
            "mode": _codeql_mode(),
            "cli_available": shutil.which("codeql") is not None,
            "database_configured": bool(codeql_database),
            "queries_configured": bool(codeql_queries),
            "database_path": codeql_database,
            "queries_path": codeql_queries,
        },
    }


async def _run_semgrep_docker(workspace_dir: str, file_paths: list[str], config_path: str) -> dict[str, Any]:
    runner = os.getenv("CLAW_SEMGREP_RUNNER") or _docker_semgrep_runner(workspace_dir)
    if not runner:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": ["docker semgrep runner not found"],
        }
    if shutil.which("docker") is None:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": ["docker not installed"],
        }

    args = [runner, workspace_dir, config_path, *file_paths]
    code, stdout, stderr = await _run_command(args)
    if code not in {0, 1}:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": [stderr.strip() or stdout.strip() or f"docker semgrep exited {code}"],
        }
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": ["docker semgrep returned non-JSON output"],
        }

    findings = []
    for result in payload.get("results", []):
        extra = result.get("extra", {})
        severity = str(extra.get("severity") or "medium").lower()
        findings.append(
            {
                "tool": "semgrep",
                "severity": severity,
                "rule_id": result.get("check_id"),
                "message": extra.get("message") or "",
                "path": result.get("path"),
                "line": (result.get("start") or {}).get("line"),
            }
        )
    return {
        "tool": "semgrep",
        "status": "fail" if findings else "pass",
        "findings": findings,
        "details": [],
    }


async def _run_semgrep(workspace_dir: str, file_paths: list[str]) -> dict[str, Any]:
    config_path = os.getenv("CLAW_SEMGREP_CONFIG") or _default_semgrep_config(workspace_dir)
    if not config_path:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": ["CLAW_SEMGREP_CONFIG not set and no repo-local security/semgrep.yml found"],
        }

    use_docker = os.getenv("CLAW_SECURITY_USE_DOCKER", "").lower() in {"1", "true", "yes"}
    if use_docker:
        return await _run_semgrep_docker(workspace_dir, file_paths, config_path)

    if shutil.which("semgrep") is None:
        docker_runner = _docker_semgrep_runner(workspace_dir)
        if docker_runner and shutil.which("docker") is not None:
            return await _run_semgrep_docker(workspace_dir, file_paths, config_path)
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": ["semgrep not installed and docker fallback unavailable"],
        }

    args = [
        "semgrep",
        "scan",
        "--config",
        config_path,
        "--json",
        "--quiet",
        *(_candidate_scan_paths(workspace_dir, file_paths)),
    ]
    code, stdout, stderr = await _run_command(args)
    if code not in {0, 1}:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": [stderr.strip() or stdout.strip() or f"semgrep exited {code}"],
        }
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return {
            "tool": "semgrep",
            "status": "unavailable",
            "findings": [],
            "details": ["semgrep returned non-JSON output"],
        }

    findings = []
    for result in payload.get("results", []):
        extra = result.get("extra", {})
        severity = str(extra.get("severity") or "medium").lower()
        findings.append(
            {
                "tool": "semgrep",
                "severity": severity,
                "rule_id": result.get("check_id"),
                "message": extra.get("message") or "",
                "path": result.get("path"),
                "line": (result.get("start") or {}).get("line"),
            }
        )
    return {
        "tool": "semgrep",
        "status": "fail" if findings else "pass",
        "findings": findings,
        "details": [],
    }


async def _run_codeql(workspace_dir: str, file_paths: list[str]) -> dict[str, Any]:
    mode = _codeql_mode()
    if mode == "off":
        return {
            "tool": "codeql",
            "status": "skipped",
            "findings": [],
            "details": ["CodeQL disabled by CLAW_CODEQL_MODE=off"],
        }

    if shutil.which("codeql") is None:
        status = "unavailable" if mode == "required" else "deferred"
        return {
            "tool": "codeql",
            "status": status,
            "findings": [],
            "details": [
                "codeql not installed; required by CLAW_CODEQL_MODE=required"
                if mode == "required"
                else "codeql not installed; deferred in local mode"
            ],
        }

    database_path = os.getenv("CLAW_CODEQL_DATABASE")
    query_suite = os.getenv("CLAW_CODEQL_QUERIES")
    if not database_path or not query_suite:
        status = "unavailable" if mode == "required" else "deferred"
        return {
            "tool": "codeql",
            "status": status,
            "findings": [],
            "details": [
                "CLAW_CODEQL_DATABASE and CLAW_CODEQL_QUERIES required by CLAW_CODEQL_MODE=required"
                if mode == "required"
                else "CLAW_CODEQL_DATABASE or CLAW_CODEQL_QUERIES not set; deferred in local mode"
            ],
        }

    output_path = str(Path(workspace_dir) / ".claw_codeql_results.sarif")
    args = [
        "codeql",
        "database",
        "analyze",
        database_path,
        query_suite,
        "--format=sarif-latest",
        f"--output={output_path}",
    ]
    code, stdout, stderr = await _run_command(args)
    if code != 0:
        return {
            "tool": "codeql",
            "status": "unavailable",
            "findings": [],
            "details": [stderr.strip() or stdout.strip() or f"codeql exited {code}"],
        }

    try:
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "tool": "codeql",
            "status": "unavailable",
            "findings": [],
            "details": ["codeql did not produce readable SARIF"],
        }

    allowed_paths = {Path(path).as_posix() for path in file_paths if path}
    findings = []
    for run in payload.get("runs", []):
        rules = {rule.get("id"): rule for rule in (run.get("tool", {}).get("driver", {}).get("rules") or [])}
        for result in run.get("results", []):
            rule_id = result.get("ruleId")
            rule = rules.get(rule_id, {})
            level = str(result.get("level") or "warning").lower()
            severity = "high" if level == "error" else "medium" if level == "warning" else "low"
            locations = result.get("locations") or []
            path = None
            line = None
            if locations:
                physical = (locations[0].get("physicalLocation") or {})
                artifact = physical.get("artifactLocation") or {}
                path = artifact.get("uri")
                region = physical.get("region") or {}
                line = region.get("startLine")
            if allowed_paths and path and path not in allowed_paths and Path(path).as_posix() not in allowed_paths:
                continue
            findings.append(
                {
                    "tool": "codeql",
                    "severity": severity,
                    "rule_id": rule_id,
                    "message": (result.get("message") or {}).get("text") or rule.get("shortDescription", {}).get("text") or "",
                    "path": path,
                    "line": line,
                }
            )
    return {
        "tool": "codeql",
        "status": "fail" if findings else "pass",
        "findings": findings,
        "details": [],
    }


async def run_critical_slot_policy_checks(workspace_dir: str, file_paths: list[str]) -> dict[str, dict[str, Any]]:
    return {
        "semgrep": await _run_semgrep(workspace_dir, file_paths),
        "codeql": await _run_codeql(workspace_dir, file_paths),
    }
