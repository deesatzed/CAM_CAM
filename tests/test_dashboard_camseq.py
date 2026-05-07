from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from claw.core.models import (
    AdaptationStep,
    ApplicationPacket,
    CandidateSummary,
    ComponentCard,
    CoverageState,
    ExpectedLandingSite,
    ProofGate,
    Receipt,
    SlotSpec,
)


@pytest.fixture(autouse=True)
def _reset_state():
    from claw.web import dashboard_server

    dashboard_server._state.clear()
    yield
    dashboard_server._state.clear()


def _setup_client(repo: AsyncMock) -> TestClient:
    from claw.web.dashboard_server import app as dash_app, _state

    engine = AsyncMock()
    engine.close = AsyncMock()

    if "list_run_events" not in repo.__dict__:
        repo.list_run_events = AsyncMock(return_value=[])
    if "list_run_slot_executions" not in repo.__dict__:
        repo.list_run_slot_executions = AsyncMock(return_value=[])
    if "save_run_event" not in repo.__dict__:
        repo.save_run_event = AsyncMock(return_value=MagicMock())
    if "save_run_slot_execution" not in repo.__dict__:
        repo.save_run_slot_execution = AsyncMock(return_value=MagicMock())
    if "list_run_action_audits" not in repo.__dict__:
        repo.list_run_action_audits = AsyncMock(return_value=[])
    if "save_run_action_audit" not in repo.__dict__:
        repo.save_run_action_audit = AsyncMock(return_value=MagicMock())
    if "find_component_by_source_barcode" not in repo.__dict__:
        repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    if "find_lineage_by_hash" not in repo.__dict__:
        repo.find_lineage_by_hash = AsyncMock(return_value=None)
    if "upsert_component_lineage" not in repo.__dict__:
        repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    if "upsert_component_card" not in repo.__dict__:
        repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)
    if "save_governance_policy" not in repo.__dict__:
        repo.save_governance_policy = AsyncMock(return_value=MagicMock(model_dump=lambda mode="json": {"id": "pol_1"}))
    if "list_governance_policies" not in repo.__dict__:
        repo.list_governance_policies = AsyncMock(return_value=[])
    if "list_failure_knowledge" not in repo.__dict__:
        repo.list_failure_knowledge = AsyncMock(return_value=[])
    if "mark_failure_knowledge_resolved" not in repo.__dict__:
        repo.mark_failure_knowledge_resolved = AsyncMock()

    feature_flags = MagicMock()
    feature_flags.component_cards = False
    feature_flags.application_packets = False
    feature_flags.connectome_seq = False
    feature_flags.critical_slot_policy = False
    feature_flags.a2a_packets = False
    config = MagicMock()
    config.feature_flags = feature_flags

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None
    _state["ready"] = True

    return TestClient(dash_app)


def test_component_search_endpoint_returns_summary_items(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(
        return_value=[
            MagicMock(
                model_dump=lambda mode="json": {"id": "comp_1", "title": "Retry Helper"},
                family_barcode="fam_retry",
                file_path="src/retry_helper.py",
                title="Retry Helper",
                component_type="helper",
                symbol="retry_helper",
                success_count=0,
                failure_count=0,
            )
        ]
    )
    repo.list_governance_policies = AsyncMock(
        return_value=[MagicMock(policy_kind="family_policy", family_barcode="fam_retry", status="active")]
    )
    client = _setup_client(repo)

    resp = client.get("/api/v2/components/search", params={"q": "retry", "workspace_dir": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["id"] == "comp_1"
    assert data["items"][0]["governance_summary"]["active_policy_count"] == 1
    assert data["items"][0]["source_scope"] == "memory"


def test_component_search_filters_noise_paths(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(
        return_value=[
            MagicMock(
                model_dump=lambda mode="json": {"id": "comp_noise", "title": "Noise"},
                family_barcode="fam_noise",
                file_path=".uv-cache/archive-v0/noise.py",
                title="Noise",
                component_type="helper",
                symbol="noise",
                success_count=0,
                failure_count=0,
            ),
            MagicMock(
                model_dump=lambda mode="json": {"id": "comp_real", "title": "Real"},
                family_barcode="fam_real",
                file_path="src/real_component.py",
                title="Real",
                component_type="helper",
                symbol="real_component",
                success_count=0,
                failure_count=0,
            ),
        ]
    )
    repo.list_governance_policies = AsyncMock(return_value=[])
    client = _setup_client(repo)

    resp = client.get("/api/v2/components/search", params={"q": "component", "workspace_dir": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["id"] == "comp_real"


def test_component_search_merges_memory_and_workspace_by_score(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(
        return_value=[
            MagicMock(
                model_dump=lambda mode="json": {"id": "comp_db", "title": "Utility Helper"},
                family_barcode="fam_utility",
                file_path="src/utils.py",
                title="Utility Helper",
                component_type="helper",
                symbol="util_helper",
                success_count=2,
                failure_count=0,
            )
        ]
    )
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "auth_service.py").write_text(
        "class OAuthSessionClient:\n"
        "    def refresh_token(self, refresh_token: str) -> str:\n"
        "        return refresh_token\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert "auth_service.py" in data["items"][0]["file_path"]
    assert data["items"][0]["source_scope"] == "workspace"


def test_component_search_falls_back_to_local_workspace(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "auth_service.py").write_text(
        "class OAuthSessionClient:\n"
        "    def refresh_token(self, refresh_token: str) -> str:\n"
        "        return refresh_token\n",
        encoding="utf-8",
    )
    (tmp_path / "test_auth_service.py").write_text(
        "def test_refresh_token_roundtrip():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert "auth_service.py" in data["items"][0]["file_path"]


def test_component_search_falls_back_on_content_overlap(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "server.py").write_text(
        "class SessionManager:\n"
        "    def issue(self):\n"
        "        auth_token = 'x'\n"
        "        return auth_token\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth token", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any("server.py" in item["file_path"] for item in data["items"])
    assert all(item["search_score"] > 0 for item in data["items"])


def test_component_search_content_match_does_not_emit_every_symbol(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "server.py").write_text(
        "class SessionManager:\n"
        "    def issue(self):\n"
        "        auth_token = 'x'\n"
        "        return auth_token\n"
        "    def revoke(self):\n"
        "        return None\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth token", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    server_hits = [item for item in data["items"] if item["file_path"] == "server.py"]
    assert len(server_hits) == 1
    assert server_hits[0]["component_type"] == "module"
    assert server_hits[0]["source_scope"] == "workspace"


def test_component_search_single_token_auth_query_uses_semantic_expansion(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "auth_service.py").write_text(
        "class OAuthSessionClient:\n"
        "    def refresh_token(self, refresh_token: str) -> str:\n"
        "        auth_token = refresh_token\n"
        "        return auth_token\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any(item["file_path"] == "auth_service.py" for item in data["items"])
    assert all(item["search_score"] > 0 for item in data["items"])


def test_component_search_excludes_tests_for_normal_queries(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth_helpers.py").write_text(
        "def test_auth_token_roundtrip():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "server.py").write_text(
        "class SessionManager:\n"
        "    def issue(self):\n"
        "        auth_token = 'x'\n"
        "        return auth_token\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all("tests/" not in item["file_path"] for item in data["items"])


def test_component_search_single_token_auth_query_does_not_use_content_only_fallback(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "server.py").write_text(
        "class SessionManager:\n"
        "    def issue(self):\n"
        "        auth_token = 'x'\n"
        "        return auth_token\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


def test_component_search_auth_query_excludes_weak_alias_only_matches(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)

    client = _setup_client(repo)

    (tmp_path / "token_tracker.py").write_text(
        "class TokenTracker:\n"
        "    def get_session_totals(self):\n"
        "        return {}\n",
        encoding="utf-8",
    )
    (tmp_path / "auth_service.py").write_text(
        "class OAuthSessionClient:\n"
        "    def refresh_token(self, refresh_token: str) -> str:\n"
        "        auth_token = refresh_token\n"
        "        return auth_token\n",
        encoding="utf-8",
    )

    resp = client.get(
        "/api/v2/components/search",
        params={"q": "auth", "workspace_dir": str(tmp_path), "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(item["file_path"] == "auth_service.py" for item in data["items"])
    assert all(item["file_path"] != "token_tracker.py" for item in data["items"])


def test_component_detail_endpoint_returns_component_payload():
    repo = AsyncMock()
    component = MagicMock()
    component.id = "comp_1"
    component.methodology_id = "meth_1"
    component.receipt.lineage_id = "lin_1"
    component.receipt.family_barcode = "fam_auth"
    component.model_dump = lambda mode="json": {"id": "comp_1", "title": "Retry Helper"}
    lineage = MagicMock(model_dump=lambda mode="json": {"id": "lin_1"})
    fit = MagicMock(model_dump=lambda mode="json": {"id": "fit_1"})
    rel = MagicMock(model_dump=lambda mode="json": {"id": "comp_2"})

    repo.get_component_card = AsyncMock(return_value=component)
    repo.get_component_lineage = AsyncMock(return_value=lineage)
    repo.list_component_fit = AsyncMock(return_value=[fit])
    repo.list_components_for_methodology = AsyncMock(return_value=[rel])
    repo.list_governance_policies = AsyncMock(
        return_value=[
            MagicMock(
                id="pol_1",
                policy_kind="family_policy",
                family_barcode="fam_auth",
                severity="high",
                status="active",
                reason="unsafe family",
                recommendation="quarantine",
            )
        ]
    )

    client = _setup_client(repo)
    resp = client.get("/api/v2/components/comp_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["component"]["id"] == "comp_1"
    assert data["lineage"]["id"] == "lin_1"
    assert data["fit_history"][0]["id"] == "fit_1"
    assert data["governance_summary"]["active_policy_count"] == 1


def test_federation_packets_endpoint_returns_primary_and_sibling_packet_results():
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.get_component_card = AsyncMock(return_value=_component_card("comp_1", "refresh_access_token"))

    client = _setup_client(repo)
    from claw.web.dashboard_server import _state

    sibling_result = MagicMock()
    sibling_result.as_dict.return_value = {
        "component_id": "comp_remote",
        "title": "refresh_access_token_remote",
        "component_type": "helper",
        "abstract_jobs": ["token_refresh_serialization"],
        "language": "python",
        "repo": "remote/auth",
        "file_path": "auth/session.py",
        "symbol": "refresh_access_token_remote",
        "family_barcode": "fam_remote",
        "provenance_precision": "symbol",
        "source_instance": "remote",
        "match_type": "direct_fit",
        "match_score": 0.9,
        "relevance_score": 0.8,
    }
    federation = AsyncMock()
    federation.query_component_packets = AsyncMock(return_value=[sibling_result])
    _state["federation"] = federation

    resp = client.get("/api/v2/federation/packets", params={"q": "Add OAuth session handling with token refresh", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"]
    assert any(item["source_instance"] == "primary" for item in data["results"])
    assert any(item["source_instance"] == "remote" for item in data["results"])


def test_component_history_endpoint_returns_packet_and_lineage_history():
    repo = AsyncMock()
    component = MagicMock()
    component.receipt.lineage_id = "lin_1"
    packet = MagicMock(model_dump=lambda mode="json": {"packet_id": "pkt_1"})
    fit = MagicMock(model_dump=lambda mode="json": {"id": "fit_1"})
    lineage_component = MagicMock(model_dump=lambda mode="json": {"id": "comp_2"})

    repo.get_component_card = AsyncMock(return_value=component)
    repo.list_packet_history_for_component = AsyncMock(return_value=[packet])
    repo.list_component_fit = AsyncMock(return_value=[fit])
    repo.list_lineage_components = AsyncMock(return_value=[lineage_component])

    client = _setup_client(repo)
    resp = client.get("/api/v2/components/comp_1/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["packet_history"][0]["packet_id"] == "pkt_1"
    assert data["lineage_components"][0]["id"] == "comp_2"


def test_specialist_packet_exchange_endpoint_returns_routed_candidates():
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(
        return_value=[MagicMock(id="comp_1", family_barcode="fam_auth")]
    )
    repo.get_component_card = AsyncMock(
        return_value=MagicMock(
            id="comp_1",
            title="refresh_access_token",
            component_type="helper",
            abstract_jobs=["token_refresh_serialization"],
            language="python",
            receipt=MagicMock(
                repo="org/service",
                file_path="app/auth.py",
                symbol="refresh_access_token",
                family_barcode="fam_auth",
                provenance_precision="symbol",
            ),
        )
    )
    client = _setup_client(repo)

    from claw.web.dashboard_server import _state

    _state["config"].feature_flags.a2a_packets = True
    sibling_result = MagicMock()
    sibling_result.as_dict.return_value = {
        "component_id": "comp_remote",
        "title": "async_refresh_lock",
        "component_type": "helper",
        "abstract_jobs": ["token_refresh_serialization"],
        "language": "python",
        "repo": "remote/auth",
        "file_path": "auth/session.py",
        "symbol": "async_refresh_lock",
        "family_barcode": "fam_remote",
        "provenance_precision": "symbol",
        "source_instance": "remote",
        "match_type": "direct_fit",
        "match_score": 0.9,
        "relevance_score": 0.8,
    }
    federation = AsyncMock()
    federation.query_component_packets = AsyncMock(return_value=[sibling_result])
    _state["federation"] = federation

    resp = client.post(
        "/api/v2/federation/specialist-packet",
        json={
            "task_text": "Fix token refresh races in the OAuth client",
            "preferred_agent": "codex",
            "target_language": "python",
            "limit": 4,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_agent"] == "codex"
    assert data["results"]


def test_component_backfill_endpoint_returns_summary():
    repo = AsyncMock()
    client = _setup_client(repo)

    with patch("claw.miner.RepoMiner.backfill_components", new_callable=AsyncMock) as backfill:
        backfill.return_value = {"created": 2, "updated": 1, "skipped": 0, "methodologies": 3, "skip_reasons": []}
        resp = client.post("/api/v2/components/backfill", json={"limit": 25})

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 2
    assert data["updated"] == 1


def _component_card(component_id: str, title: str, abstract_job: str = "authenticated_api_client") -> ComponentCard:
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


def _candidate_summary(
    component_id: str,
    title: str,
    *,
    fit_bucket: str = "will_help",
    transfer_mode: str = "direct_fit",
    confidence: float = 0.86,
) -> CandidateSummary:
    return CandidateSummary(
        component_id=component_id,
        title=title,
        fit_bucket=fit_bucket,
        transfer_mode=transfer_mode,
        confidence=confidence,
        confidence_basis=["test_fixture"],
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
        why_fit=["token refresh support"],
        prior_success_count=2,
        deduped_lineage_count=1,
        adaptation_burden="low",
    )


def _application_packet(plan_id: str, *, packet_id: str = "pkt_1", slot_id: str = "slot_refresh") -> ApplicationPacket:
    selected = _candidate_summary("comp_1", "refresh_access_token")
    runner_up = _candidate_summary("comp_2", "refresh_access_token_async", confidence=0.78)
    return ApplicationPacket(
        packet_id=packet_id,
        plan_id=plan_id,
        task_archetype="oauth_session_management",
        slot=SlotSpec(
            slot_id=slot_id,
            slot_barcode=f"slotbc_{slot_id}",
            name="token_refresh",
            abstract_job="token_refresh_serialization",
            risk="critical",
            constraints=["async"],
            target_stack=["python", "fastapi"],
            proof_expectations=["tests", "verifier"],
        ),
        status="approved",
        selected=selected,
        runner_ups=[runner_up],
        why_selected=["selected for token refresh support"],
        why_runner_up_lost={runner_up.component_id: ["lower confidence"]},
        adaptation_plan=[AdaptationStep(title="convert lock", rationale="async runtime", blocking=True)],
        proof_plan=[
            ProofGate(gate_id="tests", gate_type="tests", required=True),
            ProofGate(gate_id="verifier", gate_type="verifier", required=True),
        ],
        expected_landing_sites=[ExpectedLandingSite(file_path="app/auth/session.py", symbol="refresh_session")],
        reviewer_required=True,
        review_required_reasons=["critical_slot"],
        confidence_basis=["unit_test_fixture"],
        coverage_state="covered",
    )


def test_plan_create_and_get_endpoints_return_packets():
    repo = AsyncMock()
    card = _component_card("comp_1", "refresh_access_token", "token_refresh_serialization")
    saved_packets = {}

    async def _save_packet(packet):
        saved_packets[packet.packet_id] = packet

    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(return_value=card)
    repo.find_component_fit = AsyncMock(return_value=[])
    repo.save_application_packet = AsyncMock(side_effect=_save_packet)
    repo.list_packets_for_plan = AsyncMock(side_effect=lambda plan_id: [
        MagicMock(packet_id=packet.packet_id)
        for packet in saved_packets.values()
        if packet.plan_id == plan_id
    ])
    repo.get_application_packet = AsyncMock(side_effect=lambda packet_id: saved_packets.get(packet_id))

    client = _setup_client(repo)
    create_resp = client.post("/api/v2/plans", json={"task_text": "Add OAuth session handling with token refresh"})
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["plan_id"].startswith("plan_")
    assert created["summary"]["total_slots"] >= 1

    get_resp = client.get(f"/api/v2/plans/{created['plan_id']}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["plan_id"] == created["plan_id"]
    assert data["packets"]


def test_plan_create_reflects_active_governance_policy_in_packet_review():
    repo = AsyncMock()
    governed = _component_card("comp_1", "refresh_access_token", "token_refresh_serialization")
    governed.receipt.family_barcode = "fam_governed"
    safer = _component_card("comp_2", "refresh_access_token_async", "token_refresh_serialization")
    safer.receipt.family_barcode = "fam_safe"
    saved_packets = {}

    async def _save_packet(packet):
        saved_packets[packet.packet_id] = packet

    async def _get_component_card(component_id):
        return {"comp_1": governed, "comp_2": safer}[component_id]

    async def _get_packet(packet_id):
        return saved_packets[packet_id]

    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1"), MagicMock(id="comp_2")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(side_effect=_get_component_card)
    repo.find_component_fit = AsyncMock(return_value=[])
    repo.save_application_packet = AsyncMock(side_effect=_save_packet)
    repo.get_application_packet = AsyncMock(side_effect=_get_packet)
    repo.list_packets_for_plan = AsyncMock(
        side_effect=lambda plan_id: [
            MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)
            for packet in saved_packets.values()
            if packet.plan_id == plan_id
        ]
    )
    repo.save_slot_instance = AsyncMock(return_value=MagicMock())
    repo.save_task_plan = AsyncMock(return_value=MagicMock())
    repo.list_governance_policies = AsyncMock(
        side_effect=[
            [MagicMock(id="pol_1", task_archetype="oauth_session_management", status="active", policy_kind="family_policy", family_barcode="fam_governed", severity="high", reason="unsafe family", recommendation="quarantine family")],
            [MagicMock(id="pol_1", task_archetype="oauth_session_management", status="active", policy_kind="family_policy", family_barcode="fam_governed", severity="high", reason="unsafe family", recommendation="quarantine family")],
        ]
    )

    client = _setup_client(repo)
    create_resp = client.post("/api/v2/plans", json={"task_text": "Add OAuth session handling with token refresh"})
    assert create_resp.status_code == 200
    created = create_resp.json()

    get_resp = client.get(f"/api/v2/plans/{created['plan_id']}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    first_packet = data["packets"][0]
    assert first_packet["selected"]["component_id"] == "comp_2"
    runner_up_ids = [item["component_id"] for item in first_packet["runner_ups"]]
    assert "comp_1" in runner_up_ids


def test_plan_create_adds_semgrep_and_codeql_gates_for_critical_slots_when_flag_enabled():
    repo = AsyncMock()
    card = _component_card("comp_1", "refresh_access_token", "token_refresh_serialization")
    saved_packets = {}

    async def _save_packet(packet):
        saved_packets[packet.packet_id] = packet

    async def _get_packet(packet_id):
        return saved_packets[packet_id]

    client = _setup_client(repo)
    from claw.web.dashboard_server import _state

    _state["config"].feature_flags.critical_slot_policy = True
    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(return_value=card)
    repo.find_component_fit = AsyncMock(return_value=[])
    repo.save_application_packet = AsyncMock(side_effect=_save_packet)
    repo.get_application_packet = AsyncMock(side_effect=_get_packet)
    repo.list_packets_for_plan = AsyncMock(
        side_effect=lambda plan_id: [
            MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)
            for packet in saved_packets.values()
            if packet.plan_id == plan_id
        ]
    )
    repo.save_slot_instance = AsyncMock(return_value=MagicMock())
    repo.save_task_plan = AsyncMock(return_value=MagicMock())
    repo.list_governance_policies = AsyncMock(return_value=[])

    create_resp = client.post("/api/v2/plans", json={"task_text": "Add OAuth session handling with token refresh"})
    assert create_resp.status_code == 200
    created = create_resp.json()
    get_resp = client.get(f"/api/v2/plans/{created['plan_id']}")
    assert get_resp.status_code == 200
    packet = get_resp.json()["packets"][0]
    gate_types = {gate["gate_type"] for gate in packet["proof_plan"]}
    assert "semgrep" in gate_types
    assert "codeql" in gate_types
    assert "critical_policy_scan_required" in packet["review_required_reasons"]


def test_plan_approve_and_execute_endpoints():
    repo = AsyncMock()
    card = _component_card("comp_1", "refresh_access_token", "token_refresh_serialization")
    saved_packets = {}

    async def _save_packet(packet):
        saved_packets[packet.packet_id] = packet

    repo.search_component_cards_text = AsyncMock(return_value=[MagicMock(id="comp_1")])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.get_component_card = AsyncMock(return_value=card)
    repo.find_component_fit = AsyncMock(return_value=[])
    repo.save_application_packet = AsyncMock(side_effect=_save_packet)
    repo.list_packets_for_plan = AsyncMock(side_effect=lambda plan_id: [
        MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)
        for packet in saved_packets.values()
        if packet.plan_id == plan_id
    ])
    repo.get_application_packet = AsyncMock(side_effect=lambda packet_id: saved_packets.get(packet_id))

    client = _setup_client(repo)
    created = client.post("/api/v2/plans", json={"task_text": "Add OAuth session handling with token refresh"}).json()
    slot_ids = [slot["slot_id"] for slot in created["slots"]]

    approve_resp = client.post(f"/api/v2/plans/{created['plan_id']}/approve", json={"slot_ids": slot_ids})
    assert approve_resp.status_code == 200
    approved = approve_resp.json()
    assert approved["approved_slot_ids"]

    with patch("claw.web.dashboard_server._start_playground_execution", new_callable=AsyncMock) as start_exec:
        start_exec.return_value = MagicMock(body=b'{\"session_id\":\"run_1\",\"status\":\"started\",\"plan_id\":\"plan_x\"}')
        exec_resp = client.post(f"/api/v2/plans/{created['plan_id']}/execute", json={"approved_slot_ids": slot_ids})

    assert exec_resp.status_code == 200
    data = exec_resp.json()
    assert data["session_id"] == "run_1"
    assert data["redirect_to"] == "/forge/run/run_1"


def test_run_status_and_connectome_endpoints():
    repo = AsyncMock()
    connectome = MagicMock(id="conn_1", status="verified", task_archetype="oauth_session_management")
    pair = MagicMock(slot_id="slot_refresh", component_id="comp_1", packet_id="pkt_1")
    landing = MagicMock(id="locus_1", file_path="app/auth/session.py", symbol=None, diff_hunk_id="hunk_1", slot_id="slot_refresh", packet_id="pkt_1", origin=MagicMock(value="adapted_component"))
    outcome = MagicMock(id="out_1", slot_id="slot_refresh", packet_id="pkt_1", success=True, created_at=MagicMock(isoformat=lambda: "2026-04-12T00:00:00+00:00"))

    repo.get_run_connectome = AsyncMock(return_value=connectome)
    repo.list_run_pair_events = AsyncMock(return_value=[pair])
    repo.list_run_landing_events = AsyncMock(return_value=[landing])
    repo.list_run_outcome_events = AsyncMock(return_value=[outcome])
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    repo.list_run_connectome_edges = AsyncMock(return_value=[{"source_node": "slot_refresh", "target_node": "comp_1", "edge_type": "paired", "metadata_json": "{}"}])

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {
        "run_1": {
            "status": "completed",
            "plan_id": "plan_1",
            "task_description": "Add OAuth session handling",
            "approved_slot_ids": ["slot_refresh"],
            "corrections": [],
            "steps": [{"step": "verify", "detail": "done", "timestamp": "2026-04-12T00:00:00+00:00"}],
            "gates": [],
            "result": {"success": True},
        }
    }

    status_resp = client.get("/api/v2/runs/run_1")
    assert status_resp.status_code == 200
    assert status_resp.json()["summary"]["pair_events"] == 1
    assert status_resp.json()["summary"]["action_audits"] == 0

    connectome_resp = client.get("/api/v2/runs/run_1/connectome")
    assert connectome_resp.status_code == 200
    assert connectome_resp.json()["edges"]

    landings_resp = client.get("/api/v2/runs/run_1/landings")
    assert landings_resp.status_code == 200
    assert landings_resp.json()["landings"][0]["file_path"] == "app/auth/session.py"

    events_resp = client.get("/api/v2/runs/run_1/events")
    assert events_resp.status_code == 200
    assert events_resp.json()["events"]

    stream_resp = client.get("/api/v2/runs/run_1/events/stream", params={"once": "true"})
    assert stream_resp.status_code == 200
    assert "text/event-stream" in stream_resp.headers["content-type"]


def test_run_status_respects_explicit_slot_execution_state():
    repo = AsyncMock()
    packet = _application_packet("plan_1")
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(id="conn_1", status="running", task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(slot_id="slot_refresh", component_id="comp_1", packet_id="pkt_1")])
    repo.list_run_landing_events = AsyncMock(return_value=[])
    repo.list_run_outcome_events = AsyncMock(return_value=[])
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    repo.list_packets_for_plan = AsyncMock(return_value=[MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)])
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app

    dash_app.state.playground_jobs = {
        "run_queued": {
            "status": "running",
            "plan_id": "plan_1",
            "task_description": "Add OAuth session handling",
            "approved_slot_ids": ["slot_refresh"],
            "slot_execution": [
                {
                    "slot_id": "slot_refresh",
                    "status": "queued",
                    "current_step": "pending",
                    "retry_count": 0,
                    "last_retry_detail": None,
                    "replacement_count": 0,
                    "selected_component_id": "comp_1",
                }
            ],
            "replacement_history": [],
            "corrections": [],
            "steps": [],
            "gates": [],
            "result": None,
        }
    }

    status_resp = client.get("/api/v2/runs/run_queued")
    assert status_resp.status_code == 200
    slot = status_resp.json()["slots"][0]
    assert slot["status"] == "queued"
    assert slot["selected_component_id"] == "comp_1"


def test_run_retrograde_and_distill_endpoints():
    repo = AsyncMock()
    packet = MagicMock()
    packet.slot.slot_id = "slot_refresh"
    packet.slot.name = "token_refresh"
    packet.slot.risk = "critical"
    packet.runner_ups = [MagicMock(component_id="comp_2", why_fit=["Native async lock semantics"], transfer_mode="direct_fit")]
    packet.selected.component_id = "comp_1"
    packet.selected.transfer_mode = "pattern_transfer"

    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1", component_id="comp_1")])
    repo.list_run_landing_events = AsyncMock(return_value=[MagicMock(id="locus_1", packet_id="pkt_1", file_path="app/auth/session.py")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1", slot_id="slot_refresh", success=False, verifier_findings=["race"], negative_memory_updates=["sync wrapper fails"])])
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {
        "run_2": {
            "task_description": "Fix token refresh races",
        }
    }

    retro_resp = client.get("/api/v2/runs/run_2/retrograde")
    assert retro_resp.status_code == 200
    retro = retro_resp.json()
    assert retro["cause_chain"]
    assert retro["runner_up_analysis"]["component_id"] == "comp_2"
    assert retro["runner_up_analysis"]["transfer_mode"] == "direct_fit"
    assert any(item["kind"] == "federation" for item in retro["cause_chain"])

    distill_resp = client.get("/api/v2/runs/run_2/distill")
    assert distill_resp.status_code == 200
    distill = distill_resp.json()
    assert distill["downgrades"]
    assert distill["negative_memory_updates"] == ["sync wrapper fails"]
    assert distill["packet_transfer_summary"]["pattern_transfer"] == 1
    assert distill["federation_recommendations"]


def test_run_retrograde_prioritizes_proof_gate_failures():
    repo = AsyncMock()
    packet = MagicMock()
    packet.slot.slot_id = "slot_exec"
    packet.slot.name = "external_execution"
    packet.slot.risk = "critical"
    packet.runner_ups = [MagicMock(component_id="comp_safe", why_fit=["Avoids shell invocation"], transfer_mode="direct_fit")]
    packet.selected.component_id = "comp_shell"
    packet.selected.transfer_mode = "direct_fit"

    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="sandboxing"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_exec", component_id="comp_shell")])
    repo.list_run_landing_events = AsyncMock(return_value=[MagicMock(id="locus_exec", packet_id="pkt_exec", file_path="src/claw/cli/_monolith.py")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(id="out_exec", packet_id="pkt_exec", slot_id="slot_exec", success=False, verifier_findings=["semgrep: shell=true", "codeql: tainted subprocess"], negative_memory_updates=[])])
    repo.list_run_slot_executions = AsyncMock(return_value=[MagicMock(slot_id="slot_exec", retry_count=1, current_step="verifying", blocked_wait_ms=0, family_wait_ms=0)])
    repo.list_run_events = AsyncMock(
        return_value=[
            MagicMock(
                id="evt_pf",
                slot_id="slot_exec",
                event_type="proof_gate_failed",
                payload={
                    "gates": {
                        "semgrep": {"status": "failed", "details": ["shell=true"], "findings": ["shell=true"]},
                        "codeql": {"status": "failed", "details": ["tainted subprocess"], "findings": ["tainted subprocess"]},
                    }
                },
                created_at=MagicMock(isoformat=lambda: "2026-04-13T00:00:00+00:00"),
            )
        ]
    )
    repo.list_run_action_audits = AsyncMock(return_value=[])
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {"run_proof": {"task_description": "Harden critical subprocess execution"}}

    retro_resp = client.get("/api/v2/runs/run_proof/retrograde")
    assert retro_resp.status_code == 200
    retro = retro_resp.json()
    assert retro["cause_chain"][0]["kind"] == "proof_gate"
    assert any(item["kind"] == "outcome" for item in retro["cause_chain"])


def test_recipe_promotion_and_mining_mission_endpoints():
    repo = AsyncMock()
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(success=True)])
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    packet = MagicMock()
    packet.slot.name = "token_refresh"
    packet.slot.slot_id = "slot_refresh"
    packet.selected.component_id = "comp_1"
    packet.selected.receipt.family_barcode = "fam_auth"
    packet.proof_plan = [MagicMock(gate_type="tests"), MagicMock(gate_type="verifier")]
    repo.get_application_packet = AsyncMock(return_value=packet)
    saved_recipe = MagicMock(model_dump=lambda mode="json": {"id": "recipe_1", "recipe_name": "oauth_v1"})
    repo.save_compiled_recipe = AsyncMock(return_value=saved_recipe)
    saved_mission = MagicMock(
        model_dump=lambda mode="json": {
            "id": "mission_1",
            "run_id": "run_3",
            "slot_family": "async_token_refresh_serialization",
            "priority": "high",
            "reason": "undercovered",
            "status": "queued",
            "mission_json": {
                "slot_family": "async_token_refresh_serialization",
                "priority": "high",
                "reason": "undercovered",
            },
        }
    )
    repo.save_mining_mission = AsyncMock(return_value=saved_mission)
    repo.list_mining_missions = AsyncMock(return_value=[saved_mission])

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {"run_3": {"task_description": "Add OAuth session handling"}}

    promote_resp = client.post("/api/v2/runs/run_3/recipes/promote", json={"recipe_name": "oauth_v1", "minimum_sample_size": 1})
    assert promote_resp.status_code == 200
    assert promote_resp.json()["recipe"]["recipe_name"] == "oauth_v1"

    mission_resp = client.post(
        "/api/v2/runs/run_3/gaps/create-mining-mission",
        json={"slot_family": "async_token_refresh_serialization", "priority": "high", "reason": "undercovered"},
    )
    assert mission_resp.status_code == 200
    mission = mission_resp.json()["mission"]
    assert mission["slot_family"] == "async_token_refresh_serialization"

    missions_resp = client.get("/api/v2/missions/mining")
    assert missions_resp.status_code == 200
    assert missions_resp.json()["missions"]


def test_run_distill_includes_compiled_recipes():
    repo = AsyncMock()
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1", slot_id="slot_refresh", success=True, negative_memory_updates=[])])
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_1")])
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    repo.list_run_action_audits = AsyncMock(return_value=[])
    repo.get_application_packet = AsyncMock(return_value=_application_packet("plan_1"))
    repo.list_compiled_recipes = AsyncMock(return_value=[MagicMock(model_dump=lambda mode="json": {"id": "recipe_1", "recipe_name": "oauth_session_management_auto"})])

    client = _setup_client(repo)
    resp = client.get("/api/v2/runs/run_2/distill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["compiled_recipes"][0]["recipe_name"] == "oauth_session_management_auto"


@pytest.mark.asyncio
async def test_auto_distill_compiled_recipe_promotes_after_repeated_signature():
    from claw.web.dashboard_server import _auto_distill_compiled_recipe

    repo = AsyncMock()
    connectome = MagicMock(task_archetype="oauth_session_management")
    packets = [_application_packet("plan_1")]
    repo.get_compiled_recipe = AsyncMock(side_effect=[None, MagicMock(sample_size=1), MagicMock(sample_size=2)])
    repo.save_compiled_recipe = AsyncMock(side_effect=lambda recipe: recipe)

    first = await _auto_distill_compiled_recipe(repo, connectome, packets)
    second = await _auto_distill_compiled_recipe(repo, connectome, packets)
    third = await _auto_distill_compiled_recipe(repo, connectome, packets)

    assert first.sample_size == 1 and first.is_active is False
    assert second.sample_size == 2 and second.is_active is False
    assert third.sample_size == 3 and third.is_active is True


def test_active_run_swap_candidate_endpoint_persists_replacement():
    repo = AsyncMock()
    packet = _application_packet("plan_swap")
    saved_packets = {packet.packet_id: packet}
    saved_pairs = []

    async def _save_packet(updated):
        saved_packets[updated.packet_id] = updated
        return updated

    async def _get_packet(packet_id):
        return saved_packets[packet_id]

    async def _save_pair(event):
        saved_pairs.append(event)
        return event

    repo.list_packets_for_plan = AsyncMock(return_value=[MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)])
    repo.get_application_packet = AsyncMock(side_effect=_get_packet)
    repo.save_application_packet = AsyncMock(side_effect=_save_packet)
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(id="conn_swap"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(id="pair_old", slot_id="slot_refresh")])
    repo.save_run_slot_execution = AsyncMock(return_value=MagicMock())
    repo.save_pair_event = AsyncMock(side_effect=_save_pair)
    repo.save_run_connectome_edge = AsyncMock(return_value=None)
    repo.save_task_plan = AsyncMock(return_value=MagicMock())

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app

    dash_app.state.playground_jobs = {
        "run_swap": {
            "status": "running",
            "plan_id": "plan_swap",
            "task_description": "Fix token refresh races",
            "approved_slot_ids": ["slot_refresh"],
            "slot_execution": [
                {
                    "slot_id": "slot_refresh",
                    "status": "executing",
                    "current_step": "analyzing",
                    "retry_count": 1,
                    "last_retry_detail": "initial retry",
                    "replacement_count": 0,
                    "selected_component_id": "comp_1",
                }
            ],
            "replacement_history": [],
            "corrections": [],
            "steps": [],
            "gates": [],
            "result": None,
        }
    }
    dash_app.state.playground_plans = {
        "plan_swap": {
            "plan_id": "plan_swap",
            "task_text": "Fix token refresh races",
            "task_archetype": "oauth_session_management",
            "archetype_confidence": 0.88,
            "status": "approved",
            "summary": {"total_slots": 1, "critical_slots": 1, "weak_evidence_slots": 0},
            "approved_slot_ids": ["slot_refresh"],
            "replacement_history": [],
            "slots": [{"slot_id": "slot_refresh", "risk": "critical"}],
        }
    }

    resp = client.post(
        "/api/v2/runs/run_swap/slots/slot_refresh/swap-candidate",
        json={"candidate_component_id": "comp_2", "reason": "Prefer async-native lock implementation"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["packet"]["selected"]["component_id"] == "comp_2"
    assert saved_pairs[-1].replacement_of_pair_id == "pair_old"
    assert dash_app.state.playground_jobs["run_swap"]["replacement_history"][0]["new_component_id"] == "comp_2"
    assert dash_app.state.playground_jobs["run_swap"]["slot_execution"][0]["selected_component_id"] == "comp_2"
    assert dash_app.state.playground_jobs["run_swap"]["slot_execution"][0]["replacement_count"] == 1


def test_active_run_swap_candidate_rejects_high_severity_family_policy_on_critical_slot():
    repo = AsyncMock()
    packet = _application_packet("plan_swap_policy")
    saved_packets = {packet.packet_id: packet}

    repo.list_packets_for_plan = AsyncMock(return_value=[MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)])
    repo.get_application_packet = AsyncMock(side_effect=lambda packet_id: saved_packets[packet_id])
    repo.list_governance_policies = AsyncMock(
        side_effect=[
            [MagicMock(task_archetype="oauth_session_management", policy_kind="family_policy", family_barcode="fam_auth", severity="high", status="active", reason="unsafe family", recommendation="do not use")],
            [MagicMock(task_archetype="oauth_session_management", policy_kind="family_policy", family_barcode="fam_auth", severity="high", status="active", reason="unsafe family", recommendation="do not use")],
        ]
    )

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app

    dash_app.state.playground_jobs = {
        "run_swap_policy": {
            "status": "running",
            "plan_id": "plan_swap_policy",
            "approved_slot_ids": ["slot_refresh"],
            "banned_family_barcodes": {},
            "slot_execution": [{"slot_id": "slot_refresh", "status": "executing"}],
            "replacement_history": [],
        }
    }
    dash_app.state.playground_plans = {
        "plan_swap_policy": {
            "plan_id": "plan_swap_policy",
            "task_text": "Fix token refresh races",
            "task_archetype": "oauth_session_management",
            "approved_slot_ids": ["slot_refresh"],
            "slots": [{"slot_id": "slot_refresh", "risk": "critical"}],
        }
    }

    resp = client.post(
        "/api/v2/runs/run_swap_policy/slots/slot_refresh/swap-candidate",
        json={"candidate_component_id": "comp_2"},
    )
    assert resp.status_code == 400
    assert "high-severity family policy" in resp.json()["error"]


def test_active_run_pause_resume_reverify_endpoints():
    repo = AsyncMock()
    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app

    dash_app.state.playground_jobs = {
        "run_ctrl": {
            "status": "running",
            "plan_id": "plan_ctrl",
            "task_description": "Fix token refresh races",
            "approved_slot_ids": ["slot_refresh"],
            "slot_execution": [
                {
                    "slot_id": "slot_refresh",
                    "packet_id": "pkt_1",
                    "status": "executing",
                    "current_step": "verify",
                    "retry_count": 1,
                    "last_retry_detail": "style_match: mismatch",
                    "replacement_count": 0,
                    "selected_component_id": "comp_1",
                }
            ],
            "replacement_history": [],
            "reverify_requested_slots": {},
            "corrections": [],
            "steps": [],
            "gates": [],
            "result": None,
            "paused_slot_id": None,
        }
    }

    pause_resp = client.post("/api/v2/runs/run_ctrl/slots/slot_refresh/pause")
    assert pause_resp.status_code == 200
    assert dash_app.state.playground_jobs["run_ctrl"]["paused_slot_id"] == "slot_refresh"
    assert dash_app.state.playground_jobs["run_ctrl"]["slot_execution"][0]["status"] == "paused"

    resume_resp = client.post("/api/v2/runs/run_ctrl/slots/slot_refresh/resume")
    assert resume_resp.status_code == 200
    assert dash_app.state.playground_jobs["run_ctrl"]["paused_slot_id"] is None
    assert dash_app.state.playground_jobs["run_ctrl"]["slot_execution"][0]["status"] == "executing"

    reverify_resp = client.post("/api/v2/runs/run_ctrl/slots/slot_refresh/reverify")
    assert reverify_resp.status_code == 200
    assert dash_app.state.playground_jobs["run_ctrl"]["reverify_requested_slots"]["slot_refresh"] is True


def test_active_run_waive_proof_gate_endpoint():
    repo = AsyncMock()
    packet = _application_packet("plan_ctrl")
    packet.proof_plan.append(ProofGate(gate_id="semgrep", gate_type="semgrep", required=True))
    saved_packets = {packet.packet_id: packet}

    repo.list_packets_for_plan = AsyncMock(return_value=[MagicMock(packet_id=packet.packet_id, slot_id=packet.slot.slot_id)])
    repo.get_application_packet = AsyncMock(side_effect=lambda packet_id: saved_packets[packet_id])
    repo.save_application_packet = AsyncMock(side_effect=lambda updated: saved_packets.__setitem__(updated.packet_id, updated))
    repo.save_run_event = AsyncMock(return_value=MagicMock())
    repo.save_run_action_audit = AsyncMock(return_value=MagicMock())
    repo.save_task_plan = AsyncMock(return_value=MagicMock())

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app

    dash_app.state.playground_jobs = {
        "run_ctrl": {
            "status": "running",
            "plan_id": "plan_ctrl",
            "approved_slot_ids": ["slot_refresh"],
            "slot_execution": [{"slot_id": "slot_refresh", "status": "executing"}],
        }
    }
    dash_app.state.playground_plans = {
        "plan_ctrl": {
            "plan_id": "plan_ctrl",
            "task_text": "Fix token refresh races",
            "task_archetype": "oauth_session_management",
            "approved_slot_ids": ["slot_refresh"],
            "slots": [{"slot_id": "slot_refresh", "risk": "critical"}],
        }
    }

    resp = client.post(
        f"/api/v2/runs/run_ctrl/slots/slot_refresh/proof-gates/semgrep/waive",
        json={"reason": "tool unavailable in local env"},
    )
    assert resp.status_code == 200
    assert saved_packets[packet.packet_id].proof_plan[-1].status == "waived"
    assert saved_packets[packet.packet_id].proof_plan[-1].details == ["tool unavailable in local env"]


def test_active_run_block_unblock_and_family_ban_endpoints():
    repo = AsyncMock()
    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app

    dash_app.state.playground_jobs = {
        "run_gov": {
            "status": "running",
            "plan_id": "plan_gov",
            "task_description": "Fix token refresh races",
            "approved_slot_ids": ["slot_refresh"],
            "slot_execution": [
                {
                    "slot_id": "slot_refresh",
                    "packet_id": "pkt_1",
                    "status": "queued",
                    "current_step": "pending",
                    "retry_count": 0,
                    "last_retry_detail": None,
                    "replacement_count": 0,
                    "selected_component_id": "comp_1",
                }
            ],
            "replacement_history": [],
            "reverify_requested_slots": {},
            "blocked_slot_ids": {},
            "banned_family_barcodes": {},
            "corrections": [],
            "steps": [],
            "gates": [],
            "result": None,
            "paused_slot_id": None,
        }
    }

    block_resp = client.post("/api/v2/runs/run_gov/slots/slot_refresh/block", json={"reason": "needs human review"})
    assert block_resp.status_code == 200
    assert dash_app.state.playground_jobs["run_gov"]["blocked_slot_ids"]["slot_refresh"] == "needs human review"
    assert dash_app.state.playground_jobs["run_gov"]["slot_execution"][0]["status"] == "blocked"

    unblock_resp = client.post("/api/v2/runs/run_gov/slots/slot_refresh/unblock", json={"reason": "review complete"})
    assert unblock_resp.status_code == 200
    assert "slot_refresh" not in dash_app.state.playground_jobs["run_gov"]["blocked_slot_ids"]
    assert dash_app.state.playground_jobs["run_gov"]["slot_execution"][0]["status"] == "queued"

    ban_resp = client.post("/api/v2/runs/run_gov/families/fam_auth/ban", json={"reason": "family unsafe"})
    assert ban_resp.status_code == 200
    assert dash_app.state.playground_jobs["run_gov"]["banned_family_barcodes"]["fam_auth"] == "family unsafe"

    unban_resp = client.post("/api/v2/runs/run_gov/families/fam_auth/unban", json={"reason": "family cleared"})
    assert unban_resp.status_code == 200
    assert "fam_auth" not in dash_app.state.playground_jobs["run_gov"]["banned_family_barcodes"]


def test_run_status_uses_persisted_slot_execution_when_job_missing():
    repo = AsyncMock()
    packet = _application_packet("plan_persist", packet_id="pkt_persist")
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(id="conn_persist", status="running", task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(slot_id="slot_refresh", component_id="comp_1", packet_id="pkt_persist")])
    repo.list_run_landing_events = AsyncMock(return_value=[])
    repo.list_run_outcome_events = AsyncMock(return_value=[])
    repo.list_run_slot_executions = AsyncMock(return_value=[
        MagicMock(
            slot_id="slot_refresh",
            packet_id="pkt_persist",
            selected_component_id="comp_1",
            status="executing",
            current_step="verify",
            retry_count=2,
            last_retry_detail="retry from verifier",
            replacement_count=1,
        )
    ])
    repo.list_packets_for_plan = AsyncMock(return_value=[MagicMock(packet_id="pkt_persist", slot_id="slot_refresh")])
    repo.get_application_packet = AsyncMock(return_value=packet)
    repo.get_task_plan = AsyncMock(
        return_value=MagicMock(
            id="plan_persist",
            task_text="Fix token refresh races",
            workspace_dir=None,
            branch=None,
            target_brain=None,
            execution_mode="interactive",
            check_commands=[],
            task_archetype="oauth_session_management",
            archetype_confidence=0.82,
            status="executing",
            summary={"total_slots": 1, "critical_slots": 1, "weak_evidence_slots": 0},
            approved_slot_ids=["slot_refresh"],
            created_at=MagicMock(isoformat=lambda: "2026-04-12T00:00:00+00:00"),
            plan_json={"plan_id": "plan_persist", "slots": [{"slot_id": "slot_refresh", "risk": "critical"}]},
        )
    )

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {}
    dash_app.state.playground_plans = {}

    # connectome-only run has no in-memory job, but status should still use persisted slot execution
    status_resp = client.get("/api/v2/runs/run_persisted")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["summary"]["total_slots"] == 1
    assert data["slots"][0]["slot_id"] == "slot_refresh"
    assert data["slots"][0]["status"] == "executing"


def test_run_audits_endpoint_and_retrograde_include_actions():
    repo = AsyncMock()
    packet = _application_packet("plan_audit", packet_id="pkt_audit")
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_audit", component_id="comp_1")])
    repo.list_run_landing_events = AsyncMock(return_value=[MagicMock(id="locus_1", packet_id="pkt_audit", file_path="app/auth/session.py")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_audit", slot_id="slot_refresh", success=False, verifier_findings=["race"], negative_memory_updates=["sync wrapper fails"])])
    repo.list_run_events = AsyncMock(return_value=[MagicMock(id="evt_retry", slot_id="slot_refresh", event_type="retry_delta", payload={"violations": [{"check": "race"}]}, created_at=MagicMock(isoformat=lambda: "2026-04-12T00:00:00+00:00"))])
    repo.list_run_slot_executions = AsyncMock(return_value=[MagicMock(slot_id="slot_refresh", retry_count=2, current_step="verify")])
    repo.list_run_action_audits = AsyncMock(return_value=[MagicMock(id="audit_1", slot_id="slot_refresh", action_type="block_slot", reason="needs review", actor="operator", action_payload={"status": "blocked"}, created_at=MagicMock(isoformat=lambda: "2026-04-12T00:00:00+00:00"))])
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {"run_audit": {"task_description": "Fix token refresh races"}}

    audits_resp = client.get("/api/v2/runs/run_audit/audits")
    assert audits_resp.status_code == 200
    assert audits_resp.json()["audits"][0]["action_type"] == "block_slot"

    retro_resp = client.get("/api/v2/runs/run_audit/retrograde")
    assert retro_resp.status_code == 200
    retro = retro_resp.json()
    cause_kinds = [item["kind"] for item in retro["cause_chain"]]
    assert "action" in cause_kinds
    assert "slot_execution" in cause_kinds
    assert any("rank_score" in item for item in retro["cause_chain"])


def test_retrograde_includes_negative_memory_and_waived_proof_gate_actions():
    repo = AsyncMock()
    packet = _application_packet("plan_negmem", packet_id="pkt_negmem")
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_negmem", component_id="comp_1")])
    repo.list_run_landing_events = AsyncMock(return_value=[MagicMock(id="locus_1", packet_id="pkt_negmem", file_path="app/auth/session.py")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(id="out_negmem", packet_id="pkt_negmem", slot_id="slot_refresh", success=False, verifier_findings=["race"], negative_memory_updates=["sync wrapper fails"])])
    repo.list_run_events = AsyncMock(return_value=[])
    repo.list_run_slot_executions = AsyncMock(return_value=[MagicMock(slot_id="slot_refresh", retry_count=1, current_step="verify", blocked_wait_ms=0, family_wait_ms=0)])
    repo.list_run_action_audits = AsyncMock(return_value=[MagicMock(id="audit_wp", slot_id="slot_refresh", action_type="waive_proof_gate", reason="accepted for local mode", actor="operator", action_payload={"gate_id": "codeql"}, created_at=MagicMock(isoformat=lambda: "2026-04-13T00:00:00+00:00"))])
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    from claw.web.dashboard_server import app as dash_app
    dash_app.state.playground_jobs = {"run_negmem": {"task_description": "Fix token refresh races"}}

    retro_resp = client.get("/api/v2/runs/run_negmem/retrograde")
    assert retro_resp.status_code == 200
    retro = retro_resp.json()
    cause_kinds = [item["kind"] for item in retro["cause_chain"]]
    assert "negative_memory" in cause_kinds
    assert "action" in cause_kinds
    assert any("supporting_signals" in item for item in retro["cause_chain"])
    assert retro["root_cause_summary"]["primary_kind"] in cause_kinds
    assert retro["root_cause_summary"]["counterfactual_available"] is True
    assert retro["root_cause_summary"]["proof_pressure"] is True
    assert retro["root_cause_summary"]["clusters"]
    assert retro["root_cause_summary"]["narrative"]
    assert retro["root_cause_summary"]["confidence_band"] in {"medium", "high"}
    assert retro["root_cause_summary"]["recommended_action"]
    assert retro["root_cause_summary"]["actionability"] in {"immediate", "review"}
    assert retro["root_cause_summary"]["decision_path"]
    assert retro["root_cause_summary"]["dominant_cluster"]
    assert retro["root_cause_summary"]["evidence_count"] >= len(retro["cause_chain"])
    assert retro["root_cause_summary"]["confidence_drivers"]
    assert isinstance(retro["root_cause_summary"]["confidence_score"], float)
    assert retro["root_cause_summary"]["confidence_reason"]
    assert retro["root_cause_summary"]["calibration"] in {"stable", "mixed", "tentative"}
    assert retro["root_cause_summary"]["stability"] in {"stable", "competitive", "fragile"}
    assert retro["root_cause_summary"]["stability_reason"]
    assert retro["root_cause_summary"]["summary_version"] == "v2"


def test_distill_returns_governance_recommendations():
    repo = AsyncMock()
    packet = _application_packet("plan_distill", packet_id="pkt_distill")
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_distill")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(success=False, packet_id="pkt_distill", negative_memory_updates=["sync wrapper fails"])])
    repo.list_run_slot_executions = AsyncMock(return_value=[MagicMock(blocked_wait_ms=6000, family_wait_ms=7000)])
    repo.list_run_action_audits = AsyncMock(
        return_value=[
            MagicMock(action_type="block_slot"),
            MagicMock(action_type="block_slot"),
            MagicMock(action_type="ban_family"),
            MagicMock(action_type="reverify_slot"),
            MagicMock(action_type="reverify_slot"),
        ]
    )
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    resp = client.get("/api/v2/runs/run_distill/distill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["governance_recommendations"]
    kinds = {item["kind"] for item in data["governance_recommendations"]}
    assert "slot_policy" in kinds
    assert "family_policy" in kinds
    assert "proof_policy" in kinds


def test_distill_persists_negative_memory_as_failure_knowledge():
    repo = AsyncMock()
    packet = _application_packet("plan_negmem_distill", packet_id="pkt_negmem_distill")
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_negmem_distill")])
    repo.list_run_outcome_events = AsyncMock(
        return_value=[
            MagicMock(
                success=False,
                packet_id="pkt_negmem_distill",
                slot_id="slot_refresh",
                negative_memory_updates=["sync wrapper fails under concurrent refresh"],
            )
        ]
    )
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    repo.list_run_action_audits = AsyncMock(return_value=[])
    repo.get_application_packet = AsyncMock(return_value=packet)
    repo.record_failure_knowledge = AsyncMock()

    client = _setup_client(repo)
    resp = client.get("/api/v2/runs/run_negmem_distill/distill")
    assert resp.status_code == 200
    data = resp.json()

    repo.record_failure_knowledge.assert_awaited_once()
    kwargs = repo.record_failure_knowledge.await_args.kwargs
    assert kwargs["error_signature"].startswith("camseq_negative_memory:")
    assert kwargs["error_category"] == "camseq_negative_memory"
    assert kwargs["task_type"] == "oauth_session_management"
    assert kwargs["source_task_id"] == "run_negmem_distill"
    assert "sync wrapper fails" in kwargs["prevention_hint"]
    assert data["persisted_negative_memory"][0]["error_signature"] == kwargs["error_signature"]


def test_distill_returns_federation_recommendations_for_pattern_transfer():
    repo = AsyncMock()
    packet = _application_packet("plan_fed_distill", packet_id="pkt_fed_distill")
    packet.selected.transfer_mode = "pattern_transfer"
    packet.slot.risk = "critical"
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.list_run_pair_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_fed_distill")])
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(success=False, packet_id="pkt_fed_distill", negative_memory_updates=[])])
    repo.list_run_slot_executions = AsyncMock(return_value=[])
    repo.list_run_action_audits = AsyncMock(return_value=[])
    repo.get_application_packet = AsyncMock(return_value=packet)
    repo.list_compiled_recipes = AsyncMock(return_value=[])

    client = _setup_client(repo)
    resp = client.get("/api/v2/runs/run_fed_distill/distill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["packet_transfer_summary"]["pattern_transfer"] == 1
    assert data["federation_recommendations"]


def test_federation_trends_endpoint_aggregates_transfer_pressure():
    repo = AsyncMock()
    repo.engine.fetch_all = AsyncMock(return_value=[{"run_id": "run_fed_1", "task_archetype": "oauth_session_management"}])
    packet = _application_packet("plan_fed_trends", packet_id="pkt_fed_trends")
    packet.selected.transfer_mode = "pattern_transfer"
    packet.slot.risk = "critical"
    repo.list_run_outcome_events = AsyncMock(return_value=[MagicMock(packet_id="pkt_fed_trends", success=False)])
    repo.get_application_packet = AsyncMock(return_value=packet)

    client = _setup_client(repo)
    resp = client.get("/api/v2/federation/trends")
    assert resp.status_code == 200
    data = resp.json()
    assert data["by_archetype"][0]["pattern_transfer"] == 1
    assert data["by_archetype"][0]["critical_pattern_transfer"] == 1
    assert data["by_family"][0]["family_barcode"] == "fam_auth"


def test_federation_policy_recommendations_endpoint_returns_cross_run_actions():
    repo = AsyncMock()
    repo.engine.fetch_all = AsyncMock(return_value=[{"run_id": "run_fed_1", "task_archetype": "oauth_session_management"}])
    packet = _application_packet("plan_fed_reco", packet_id="pkt_fed_reco")
    packet.selected.transfer_mode = "pattern_transfer"
    packet.slot.risk = "critical"
    repo.list_run_outcome_events = AsyncMock(
        return_value=[
            MagicMock(packet_id="pkt_fed_reco", success=False),
            MagicMock(packet_id="pkt_fed_reco", success=False),
        ]
    )
    repo.get_application_packet = AsyncMock(return_value=packet)
    repo.list_governance_policies = AsyncMock(return_value=[])

    client = _setup_client(repo)
    resp = client.get("/api/v2/federation/policy-recommendations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendations"]
    assert any(item["policy_kind"] == "family_policy" for item in data["recommendations"])
    assert any(item["policy_kind"] == "slot_policy" for item in data["recommendations"])


def test_federation_policy_promotion_endpoint_saves_policy():
    repo = AsyncMock()
    repo.save_governance_policy = AsyncMock(
        return_value=MagicMock(
            model_dump=lambda mode="json": {
                "id": "pol_fed_1",
                "policy_kind": "family_policy",
                "task_archetype": "oauth_session_management",
                "family_barcode": "fam_auth",
                "evidence_json": {
                    "source_route": "/api/v2/federation/policy-recommendations",
                    "source_kind": "federation_trend",
                },
            }
        )
    )
    client = _setup_client(repo)
    resp = client.post(
        "/api/v2/federation/policies/promote",
        json={
            "policy_kind": "family_policy",
            "severity": "high",
            "task_archetype": "oauth_session_management",
            "family_barcode": "fam_auth",
            "reason": "Repeated federation failures",
            "recommendation": "Quarantine family",
            "evidence_json": {"trend_scope": "family"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["policy"]["id"] == "pol_fed_1"
    assert data["policy"]["evidence_json"]["source_kind"] == "federation_trend"


def test_governance_policy_promotion_and_listing():
    repo = AsyncMock()
    repo.get_run_connectome = AsyncMock(return_value=MagicMock(task_archetype="oauth_session_management"))
    repo.save_governance_policy = AsyncMock(
        return_value=MagicMock(model_dump=lambda mode="json": {
            "id": "pol_1",
            "policy_kind": "family_policy",
            "severity": "high",
            "reason": "Repeated bans",
            "recommendation": "Quarantine family",
            "evidence_json": {"source_run_id": "run_policy", "source_route": "/evolution/run/run_policy"},
        })
    )
    repo.list_governance_policies = AsyncMock(
        return_value=[MagicMock(model_dump=lambda mode="json": {"id": "pol_1", "policy_kind": "family_policy"})]
    )

    client = _setup_client(repo)
    promote_resp = client.post(
        "/api/v2/runs/run_policy/governance/promote",
        json={
            "policy_kind": "family_policy",
            "severity": "high",
            "reason": "Repeated bans",
            "recommendation": "Quarantine family",
            "family_barcode": "fam_auth",
        },
    )
    assert promote_resp.status_code == 200
    assert promote_resp.json()["policy"]["id"] == "pol_1"
    assert promote_resp.json()["policy"]["evidence_json"]["source_run_id"] == "run_policy"

    list_resp = client.get("/api/v2/governance/policies", params={"active_only": "true"})
    assert list_resp.status_code == 200
    assert list_resp.json()["policies"][0]["policy_kind"] == "family_policy"


def test_governance_policy_status_update():
    repo = AsyncMock()
    policy = MagicMock(
        id="pol_1",
        status="active",
        reason="Repeated bans",
        evidence_json={},
        updated_at=None,
        model_dump=lambda mode="json": {
            "id": "pol_1",
            "status": "waived",
            "policy_kind": "family_policy",
        },
    )
    repo.get_governance_policy = AsyncMock(return_value=policy)
    repo.save_governance_policy = AsyncMock(return_value=policy)
    client = _setup_client(repo)

    resp = client.post(
        "/api/v2/governance/policies/pol_1/status",
        json={"status": "waived", "reason": "temporary exception", "waiver_note": "approved for benchmark"},
    )
    assert resp.status_code == 200
    assert resp.json()["policy"]["status"] == "waived"


def test_failure_knowledge_list_and_resolve_endpoints():
    repo = AsyncMock()
    repo.list_failure_knowledge = AsyncMock(
        return_value=[
            {
                "id": "fk_1",
                "error_signature": "camseq_negative_memory:auth:slot:comp:abc",
                "error_category": "camseq_negative_memory",
                "diagnosis": "sync wrapper failed",
                "prevention_hint": "avoid sync wrapper",
                "task_type": "oauth_session_management",
                "project_id": None,
                "source_task_id": "run_1",
                "occurrence_count": 2,
                "resolved": 0,
                "resolution_approach": None,
                "created_at": "2026-05-07T00:00:00Z",
                "updated_at": "2026-05-07T00:00:00Z",
            }
        ]
    )
    repo.mark_failure_knowledge_resolved = AsyncMock()

    client = _setup_client(repo)
    list_resp = client.get(
        "/api/v2/failure-knowledge",
        params={
            "task_type": "oauth_session_management",
            "error_category": "camseq_negative_memory",
            "limit": "10",
        },
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["count"] == 1
    assert data["summary"]["unresolved_count"] == 1
    assert data["summary"]["category_counts"]["camseq_negative_memory"] == 1
    repo.list_failure_knowledge.assert_awaited_once()

    resolve_resp = client.post(
        "/api/v2/failure-knowledge/resolve",
        json={
            "error_signature": "camseq_negative_memory:auth:slot:comp:abc",
            "resolution_approach": "replaced wrapper with async lock",
        },
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "resolved"
    repo.mark_failure_knowledge_resolved.assert_awaited_once_with(
        "camseq_negative_memory:auth:slot:comp:abc",
        "replaced wrapper with async lock",
    )


def test_governance_trends_endpoint():
    repo = AsyncMock()
    engine = AsyncMock()
    engine.close = AsyncMock()
    engine.fetch_all = AsyncMock(
        side_effect=[
            [
                {
                    "task_archetype": "oauth_session_management",
                    "runs": 2,
                    "blocked_wait_ms": 12000,
                    "family_wait_ms": 3000,
                }
            ],
            [
                {
                    "task_archetype": "oauth_session_management",
                    "action_type": "block_slot",
                    "count": 3,
                }
            ],
            [
                {
                    "action_type": "ban_family",
                    "action_payload_json": "{\"family_barcode\": \"fam_auth\"}",
                },
                {
                    "action_type": "family_wait",
                    "action_payload_json": "{\"family_barcode\": \"fam_auth\"}",
                },
            ],
        ]
    )
    repo.engine = engine
    repo.list_governance_policies = AsyncMock(
        return_value=[MagicMock(family_barcode="fam_auth")]
    )
    client = _setup_client(repo)
    from claw.web.dashboard_server import _state
    _state["engine"] = engine

    resp = client.get("/api/v2/governance/trends")
    assert resp.status_code == 200
    data = resp.json()
    assert data["by_archetype"][0]["task_archetype"] == "oauth_session_management"
    assert data["by_archetype"][0]["block_actions"] == 3
    assert data["by_family"][0]["family_barcode"] == "fam_auth"


def test_governance_conflicts_endpoint():
    repo = AsyncMock()
    repo.list_governance_policies = AsyncMock(
        return_value=[
            MagicMock(
                id="pol_1",
                task_archetype="oauth_session_management",
                slot_id=None,
                family_barcode="fam_auth",
                policy_kind="family_policy",
                severity="high",
                status="active",
                reason="quarantine family",
                recommendation="quarantine family",
            ),
            MagicMock(
                id="pol_2",
                task_archetype="oauth_session_management",
                slot_id=None,
                family_barcode="fam_auth",
                policy_kind="family_policy",
                severity="medium",
                status="active",
                reason="allow with review",
                recommendation="allow with review",
            ),
        ]
    )
    client = _setup_client(repo)
    resp = client.get("/api/v2/governance/conflicts", params={"active_only": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["policy_count"] == 2
    assert data["conflicts"]
    assert "directive_conflict" in data["conflicts"][0]["conflict_reasons"]


def test_search_endpoint_returns_governance_context():
    repo = AsyncMock()
    engine = AsyncMock()
    engine.close = AsyncMock()
    engine.fetch_all = AsyncMock(
        return_value=[
            {
                "id": "meth_1",
                "problem_description": "OAuth refresh handling",
                "solution_code": "def refresh(): pass",
                "methodology_notes": "token refresh",
                "tags": "[]",
                "language": "python",
                "lifecycle_state": "active",
                "novelty_score": 0.7,
                "retrieval_count": 4,
                "success_count": 2,
                "failure_count": 0,
                "fts_rank": 0.2,
            }
        ]
    )
    repo.engine = engine
    repo.list_governance_policies = AsyncMock(
        side_effect=[
            [MagicMock(id="pol_1", task_archetype="oauth_session_management", slot_id=None, family_barcode="fam_auth", policy_kind="family_policy", severity="high", status="active", reason="unsafe family", recommendation="quarantine")],
            [MagicMock(id="pol_1", task_archetype="oauth_session_management", slot_id=None, family_barcode="fam_auth", policy_kind="family_policy", severity="high", status="active", reason="unsafe family", recommendation="quarantine")],
        ]
    )
    client = _setup_client(repo)
    resp = client.get("/api/search", params={"q": "OAuth token refresh", "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["governance_context"]["task_archetype"] == "oauth_session_management"
    assert data["governance_context"]["active_policy_count"] == 1


def test_create_plan_falls_back_to_local_workspace_components(tmp_path):
    repo = AsyncMock()
    repo.search_component_cards_text = AsyncMock(return_value=[])
    repo.list_component_cards = AsyncMock(return_value=[])
    repo.find_component_fit = AsyncMock(return_value=[])
    repo.list_governance_policies = AsyncMock(return_value=[])
    repo.list_compiled_recipes = AsyncMock(return_value=[])
    repo.find_component_by_source_barcode = AsyncMock(return_value=None)
    repo.find_lineage_by_hash = AsyncMock(return_value=None)
    repo.upsert_component_lineage = AsyncMock(side_effect=lambda lineage: lineage)
    repo.upsert_component_card = AsyncMock(side_effect=lambda card: card)
    repo.save_application_packet = AsyncMock(side_effect=lambda packet: packet)
    repo.save_task_plan = AsyncMock(side_effect=lambda record: record)
    repo.get_task_plan = AsyncMock(return_value=None)

    client = _setup_client(repo)

    (tmp_path / "auth_service.py").write_text(
        "class OAuthSessionClient:\n"
        "    def refresh_token(self, refresh_token: str) -> str:\n"
        "        return refresh_token\n",
        encoding="utf-8",
    )
    (tmp_path / "test_auth_service.py").write_text(
        "def test_refresh_token_roundtrip():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    resp = client.post(
        "/api/v2/plans",
        json={
            "task_text": "Add OAuth session handling with token refresh",
            "workspace_dir": str(tmp_path),
            "target_language": "python",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan_id"].startswith("plan_")
    assert data["slots"]
