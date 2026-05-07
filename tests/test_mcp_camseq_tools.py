from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from claw.core.models import ComponentCard, CoverageState, ExternalSpecialistExchange, Receipt
from claw.mcp_server import ClawMCPServer


def _component_card(component_id: str, title: str, abstract_job: str = "token_refresh_serialization") -> ComponentCard:
    return ComponentCard(
        id=component_id,
        title=title,
        component_type="helper",
        abstract_jobs=[abstract_job],
        receipt=Receipt(
            source_barcode=f"src_{component_id}",
            family_barcode="fam_auth",
            lineage_id="lin_1",
            repo="org/service",
            file_path="app/auth.py",
            symbol=title,
            content_hash=f"sha256:{component_id}",
            provenance_precision="symbol",
        ),
        language="python",
        coverage_state=CoverageState.COVERED,
        keywords=["oauth", "token", "refresh"],
        applicability=["python", "auth"],
        test_evidence=["pytest"],
    )


async def test_claw_decompose_task_tool():
    repo = AsyncMock()
    server = ClawMCPServer(repository=repo)

    result = await server.dispatch_tool(
        "claw_decompose_task",
        {"task_text": "Add OAuth session handling with token refresh"},
    )
    assert result["status"] == "ok"
    assert result["task_archetype"] == "oauth_session_management"
    assert result["slots"]


async def test_claw_build_application_packet_tool():
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(return_value=_component_card("comp_1", "refresh_access_token"))
    repo.find_component_fit = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])

    server = ClawMCPServer(repository=repo)
    result = await server.dispatch_tool(
        "claw_build_application_packet",
        {
            "workspace_dir": "/tmp/repo",
            "task_text": "Add OAuth session handling with token refresh",
            "slot_name": "token_refresh",
            "target_language": "python",
            "target_stack_hints": ["fastapi"],
        },
    )
    assert result["status"] == "ok"
    assert result["packet"]["slot"]["name"] == "token_refresh"
    assert result["packet"]["selected"]["component_id"] == "comp_1"


async def test_claw_get_run_connectome_tool():
    repo = AsyncMock()
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(id="conn_1", task_archetype="oauth_session_management", status="verified"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(slot_id="slot_refresh", component_id="comp_1", packet_id="pkt_1")])
    repo.list_run_landing_events = AsyncMock(return_value=[MagicMock(file_path="app/auth/session.py", packet_id="pkt_1")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(id="out_1", packet_id="pkt_1")])
    repo.list_run_connectome_edges = AsyncMock(return_value=[])

    server = ClawMCPServer(repository=repo)
    result = await server.dispatch_tool("claw_get_run_connectome", {"run_id": "run_1"})
    assert result["status"] == "ok"
    assert result["connectome"]["edges"]


async def test_claw_trace_failure_tool():
    repo = AsyncMock()
    packet = MagicMock()
    packet.selected.title = "refresh_access_token"
    packet.runner_ups = [MagicMock(component_id="comp_2", why_fit=["native async lock semantics"])]
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(id="out_1", packet_id="pkt_1", slot_id="slot_refresh", success=False)])
    repo.list_run_landing_events = AsyncMock(return_value=[MagicMock(id="loc_1", packet_id="pkt_1", file_path="app/auth/session.py")])
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1", component_id="comp_1")])
    repo.list_run_slot_executions = AsyncMock(return_value=[MagicMock(slot_id="slot_refresh", retry_count=2, blocked_wait_ms=0, family_wait_ms=0)])
    repo.list_run_action_audits = AsyncMock(return_value=[])
    repo.list_run_events = AsyncMock(return_value=[])
    repo.get_application_packet = AsyncMock(return_value=packet)

    server = ClawMCPServer(repository=repo)
    result = await server.dispatch_tool("claw_trace_failure", {"run_id": "run_1"})
    assert result["status"] == "ok"
    assert result["cause_chain"]
    assert result["runner_up_analysis"]["component_id"] == "comp_2"


async def test_claw_promote_recipe_and_queue_mining_mission_tools():
    repo = AsyncMock()
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1")])
    packet = MagicMock()
    packet.slot.name = "token_refresh"
    packet.selected.receipt.family_barcode = "fam_auth"
    packet.proof_plan = [MagicMock(gate_type="tests"), MagicMock(gate_type="verifier")]
    repo.get_application_packet = AsyncMock(return_value=packet)
    repo.save_compiled_recipe = AsyncMock(side_effect=lambda recipe: recipe)
    repo.save_mining_mission = AsyncMock(side_effect=lambda mission: mission)

    server = ClawMCPServer(repository=repo)
    recipe_result = await server.dispatch_tool(
        "claw_promote_recipe",
        {"run_id": "run_1", "recipe_name": "oauth_v1", "minimum_sample_size": 1},
    )
    mission_result = await server.dispatch_tool(
        "claw_queue_mining_mission",
        {"run_id": "run_1", "slot_family": "async_token_refresh_serialization", "priority": "high", "reason": "undercovered"},
    )
    assert recipe_result["status"] == "ok"
    assert recipe_result["recipe"]["recipe_name"] == "oauth_v1"
    assert mission_result["status"] == "ok"
    assert mission_result["mission"]["slot_family"] == "async_token_refresh_serialization"


async def test_claw_request_specialist_packet_tool():
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(return_value=_component_card("comp_1", "refresh_access_token"))

    federation = AsyncMock()
    sibling = MagicMock()
    sibling.as_dict.return_value = {
        "component_id": "comp_sib",
        "title": "async_refresh_lock",
        "component_type": "helper",
        "abstract_jobs": ["token_refresh_serialization"],
        "language": "python",
        "repo": "org/sib",
        "file_path": "app/auth_async.py",
        "symbol": "async_refresh_lock",
        "family_barcode": "fam_auth",
        "provenance_precision": "symbol",
        "source_instance": "auth_brain",
        "match_type": "direct_fit",
        "match_score": 0.9,
        "relevance_score": 0.8,
    }
    federation.query_component_packets = AsyncMock(return_value=[sibling])

    server = ClawMCPServer(repository=repo, federation=federation)
    result = await server.dispatch_tool(
        "claw_request_specialist_packet",
        {
            "task_text": "Fix token refresh races in the OAuth client",
            "preferred_agent": "codex",
            "target_language": "python",
        },
    )
    assert result["status"] == "ok"
    assert result["selected_agent"] == "codex"
    assert result["packet_candidates"]


async def test_claw_external_specialist_exchange_tools(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAW_SPECIALIST_EXCHANGE_SPOOL_DIR", str(tmp_path / "spool"))
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(return_value=_component_card("comp_1", "refresh_access_token"))

    store: dict[str, ExternalSpecialistExchange] = {}

    async def save_exchange(exchange: ExternalSpecialistExchange) -> ExternalSpecialistExchange:
        store[exchange.id] = exchange
        return exchange

    async def get_exchange_by_request(request_id: str) -> ExternalSpecialistExchange | None:
        return next(
            (exchange for exchange in store.values() if exchange.request_id == request_id),
            None,
        )

    async def list_exchanges(
        status: str | None = None,
        limit: int = 25,
    ) -> list[ExternalSpecialistExchange]:
        items = list(store.values())
        if status:
            items = [exchange for exchange in items if exchange.status == status]
        return items[:limit]

    repo.save_external_specialist_exchange = AsyncMock(side_effect=save_exchange)
    repo.get_external_specialist_exchange = AsyncMock(side_effect=lambda exchange_id: store.get(exchange_id))
    repo.get_external_specialist_exchange_by_request = AsyncMock(side_effect=get_exchange_by_request)
    repo.list_external_specialist_exchanges = AsyncMock(side_effect=list_exchanges)
    repo.expire_external_specialist_exchanges = AsyncMock(return_value=0)

    async def bridge_caller(tool_name: str, arguments: dict):
        assert tool_name == "claw_request_specialist_packet"
        assert arguments["request_envelope"]["kind"] == "external_specialist_request"
        return {
            "status": "ok",
            "selected_agent": "external_codex",
            "archetype_confidence": 0.82,
            "packet_candidates": [
                {
                    "component_id": "remote_comp",
                    "title": "remote refresh lock",
                    "match_type": "direct_fit",
                }
            ],
        }

    server = ClawMCPServer(repository=repo, mcp_bridge_caller=bridge_caller)
    exported = await server.dispatch_tool(
        "claw_export_specialist_exchange",
        {
            "task_text": "Fix token refresh races in the OAuth client",
            "preferred_agent": "codex",
            "target_language": "python",
            "workspace_dir": str(tmp_path),
            "allowed_context": {"file_path": "app/auth.py"},
            "redaction_summary": "No secrets included",
        },
    )
    assert exported["status"] == "ok"
    assert Path(exported["request_path"]).exists()
    assert exported["exchange"]["status"] == "awaiting_reply"

    listed = await server.dispatch_tool(
        "claw_list_specialist_exchanges",
        {"workspace_dir": str(tmp_path), "limit": 5},
    )
    assert listed["status"] == "ok"
    assert listed["exchanges"][0]["exchange_id"] == exported["exchange"]["exchange_id"]

    request_id = exported["request_envelope"]["request_id"]
    inbox = tmp_path / "spool" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    reply_path = inbox / "reply.json"
    reply_path.write_text(
        json.dumps(
            {
                "schema_version": "cam.specialist.exchange.v1",
                "kind": "external_specialist_reply",
                "request_id": request_id,
                "reply_id": "reply_1",
                "specialist_identity": "codex",
                "recommendation_kind": "accepted_as_runner_up",
                "confidence": 0.85,
                "evidence": [{"kind": "analysis", "summary": "Use a per-account lock."}],
                "created_at": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    imported = await server.dispatch_tool(
        "claw_import_specialist_exchange",
        {"workspace_dir": str(tmp_path), "reply_path": "reply.json"},
    )
    assert imported["status"] == "ok"
    assert imported["imported"][0]["status"] == "reconciled"
    assert imported["imported"][0]["outcome"] == "reconciled"

    bridged_export = await server.dispatch_tool(
        "claw_export_specialist_exchange",
        {
            "task_text": "Review the remote packet bridge path",
            "preferred_agent": "codex",
            "workspace_dir": str(tmp_path),
        },
    )
    bridge_result = await server.dispatch_tool(
        "claw_bridge_specialist_exchange",
        {
            "exchange_id": bridged_export["exchange"]["exchange_id"],
            "workspace_dir": str(tmp_path),
            "specialist_identity": "external_codex",
        },
    )
    assert bridge_result["status"] == "ok"
    assert bridge_result["bridge_status"] == "submitted"
    assert bridge_result["imported"][0]["status"] == "reconciled"
    assert bridge_result["reply_envelope"]["specialist_identity"] == "external_codex"
