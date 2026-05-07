"""File-spool specialist packet exchange helpers.

The first external specialist exchange surface is intentionally transport-light:
CAM writes bounded request envelopes to an outbox and imports reply envelopes
from an inbox. External tools, humans, or later MCP bridges can move files
without gaining direct mutation authority inside CAM.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from claw.core.models import ExternalSpecialistExchange

SCHEMA_VERSION = "cam.specialist.exchange.v1"


def new_exchange_id() -> str:
    return f"specex_{uuid.uuid4().hex[:12]}"


def new_request_id() -> str:
    return f"specreq_{uuid.uuid4().hex[:12]}"


def specialist_exchange_spool_dir(workspace_dir: str | Path | None = None) -> Path:
    configured = os.getenv("CLAW_SPECIALIST_EXCHANGE_SPOOL_DIR")
    if configured:
        return Path(configured).expanduser()
    root = Path(workspace_dir) if workspace_dir is not None else Path.cwd()
    return root / "data" / "specialist_exchange"


def ensure_spool_dirs(spool_dir: Path) -> dict[str, Path]:
    outbox = spool_dir / "outbox"
    inbox = spool_dir / "inbox"
    archive = spool_dir / "archive"
    for path in (outbox, inbox, archive):
        path.mkdir(parents=True, exist_ok=True)
    return {"outbox": outbox, "inbox": inbox, "archive": archive}


def deadline_from_seconds(seconds: int | None) -> datetime | None:
    if seconds is None or seconds <= 0:
        return None
    capped = min(seconds, 60 * 60 * 24 * 14)
    return datetime.now(UTC) + timedelta(seconds=capped)


def build_request_envelope(
    exchange: ExternalSpecialistExchange,
    *,
    selected_agent: str,
    task_archetype: str | None,
    archetype_confidence: float | None,
    slot: dict[str, Any] | None,
    packet_candidates: list[dict[str, Any]],
    allowed_context: dict[str, Any] | None = None,
    redaction_summary: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "external_specialist_request",
        "exchange_id": exchange.id,
        "request_id": exchange.request_id,
        "created_at": exchange.created_at.isoformat(),
        "deadline_at": exchange.deadline_at.isoformat() if exchange.deadline_at else None,
        "plan_id": exchange.plan_id,
        "slot_id": exchange.slot_id,
        "packet_id": exchange.packet_id,
        "task_text": exchange.task_text,
        "requested_specialty": exchange.specialty,
        "selected_agent": selected_agent,
        "task_archetype": task_archetype,
        "archetype_confidence": archetype_confidence,
        "slot": slot,
        "allowed_context": allowed_context or {},
        "redaction_summary": redaction_summary,
        "packet_candidates": packet_candidates,
        "reply_contract": {
            "kind": "external_specialist_reply",
            "required_fields": [
                "schema_version",
                "kind",
                "request_id",
                "reply_id",
                "specialist_identity",
                "recommendation_kind",
                "confidence",
                "evidence",
            ],
            "allowed_recommendation_kinds": [
                "accepted_as_runner_up",
                "accepted_as_selected_candidate",
                "stored_as_mining_mission",
                "stored_as_failure_context",
                "rejected_low_evidence",
                "rejected_policy_or_scope",
                "rejected_schema_or_trust",
            ],
        },
    }


def write_request_envelope(spool_dir: Path, envelope: dict[str, Any]) -> Path:
    paths = ensure_spool_dirs(spool_dir)
    output = paths["outbox"] / f"{envelope['request_id']}.json"
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
    return output


def candidate_reply_paths(spool_dir: Path, reply_path: str | None = None) -> list[Path]:
    paths = ensure_spool_dirs(spool_dir)
    inbox = paths["inbox"].resolve()
    if reply_path:
        candidate = Path(reply_path).expanduser()
        if not candidate.is_absolute():
            candidate = inbox / candidate
        resolved = candidate.resolve()
        if inbox not in resolved.parents and resolved != inbox:
            raise ValueError("reply_path must be inside the specialist exchange inbox")
        return [resolved]
    return sorted(inbox.glob("*.json"))


def load_reply_envelope(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"reply is not readable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("reply envelope must be a JSON object")
    return payload


def validate_reply_envelope(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported specialist reply schema_version")
    if payload.get("kind") != "external_specialist_reply":
        raise ValueError("specialist reply kind must be external_specialist_reply")
    for field in ("request_id", "reply_id", "specialist_identity", "recommendation_kind"):
        if not str(payload.get(field) or "").strip():
            raise ValueError(f"specialist reply missing {field}")
    confidence = payload.get("confidence", 0)
    if not isinstance(confidence, int | float) or confidence < 0 or confidence > 1:
        raise ValueError("specialist reply confidence must be between 0 and 1")
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("specialist reply evidence must be a list")


def archive_reply(spool_dir: Path, path: Path, request_id: str, reply_id: str) -> Path:
    paths = ensure_spool_dirs(spool_dir)
    output = paths["archive"] / f"{request_id}-{reply_id}.json"
    output.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return output


def write_inbox_reply(spool_dir: Path, envelope: dict[str, Any]) -> Path:
    paths = ensure_spool_dirs(spool_dir)
    output = paths["inbox"] / f"{envelope['request_id']}-{envelope['reply_id']}.json"
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
    return output


MCPBridgeCaller = Callable[[str, dict[str, Any]], Awaitable[Any]]


def mcp_bridge_arguments(request_envelope: dict[str, Any]) -> dict[str, Any]:
    slot = request_envelope.get("slot") if isinstance(request_envelope.get("slot"), dict) else {}
    return {
        "task_text": request_envelope.get("task_text") or "",
        "slot_name": slot.get("name"),
        "preferred_agent": request_envelope.get("selected_agent"),
        "target_language": None,
        "limit": 5,
        "request_envelope": request_envelope,
    }


def _coerce_tool_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str) and text.strip():
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
            if isinstance(payload, dict):
                return payload
    return {"result": str(result)}


def normalize_mcp_bridge_reply(
    request_envelope: dict[str, Any],
    result: Any,
    *,
    specialist_identity: str,
    max_reply_bytes: int = 65536,
) -> dict[str, Any]:
    payload = _coerce_tool_payload(result)
    if payload.get("schema_version") == SCHEMA_VERSION and payload.get("kind") == "external_specialist_reply":
        reply = dict(payload)
    else:
        candidates = payload.get("packet_candidates") or payload.get("results") or []
        has_candidates = isinstance(candidates, list) and bool(candidates)
        confidence = payload.get("confidence")
        if not isinstance(confidence, int | float):
            confidence = payload.get("archetype_confidence") if has_candidates else 0.0
        if not isinstance(confidence, int | float):
            confidence = 0.0
        confidence = max(0.0, min(float(confidence), 1.0))
        recommendation_kind = "accepted_as_runner_up" if has_candidates else "rejected_low_evidence"
        identity = (
            specialist_identity
            if specialist_identity and specialist_identity != "mcp_bridge"
            else payload.get("specialist_identity") or payload.get("selected_agent") or "mcp_bridge"
        )
        reply = {
            "schema_version": SCHEMA_VERSION,
            "kind": "external_specialist_reply",
            "request_id": request_envelope["request_id"],
            "reply_id": f"mcpreply_{uuid.uuid4().hex[:12]}",
            "specialist_identity": identity,
            "recommendation_kind": recommendation_kind,
            "confidence": confidence,
            "evidence": [
                {
                    "kind": "mcp_tool_result",
                    "summary": payload.get("summary") or payload.get("status") or "external MCP bridge reply",
                    "payload": payload,
                }
            ],
            "constraints": payload.get("constraints", []),
            "unsafe_or_unusable_reasons": payload.get("unsafe_or_unusable_reasons", []),
        }
    reply.setdefault("request_id", request_envelope["request_id"])
    reply.setdefault("reply_id", f"mcpreply_{uuid.uuid4().hex[:12]}")
    reply.setdefault("specialist_identity", specialist_identity or "mcp_bridge")
    reply.setdefault("recommendation_kind", "rejected_schema_or_trust")
    reply.setdefault("confidence", 0.0)
    reply.setdefault("evidence", [])
    encoded = json.dumps(reply, sort_keys=True).encode("utf-8")
    if len(encoded) > max_reply_bytes:
        raise ValueError("external MCP bridge reply exceeds max_reply_bytes")
    validate_reply_envelope(reply)
    return reply


async def call_stdio_mcp_tool(
    *,
    command: str,
    args: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: int = 60,
    env: dict[str, str] | None = None,
) -> Any:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as exc:  # pragma: no cover - depends on optional mcp extra
        raise RuntimeError("mcp SDK is required for stdio MCP bridge transport") from exc

    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(
                tool_name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            )
