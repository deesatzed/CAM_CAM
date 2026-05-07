from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from claw.core.config import DatabaseConfig
from claw.core.models import ExternalSpecialistExchange
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


@pytest.fixture(autouse=True)
def _reset_state():
    from claw.web import dashboard_server

    dashboard_server._state.clear()
    yield
    dashboard_server._state.clear()


def _setup_client(
    tmp_path: Path, repo: AsyncMock, monkeypatch: pytest.MonkeyPatch, *, a2a_packets: bool = True
) -> TestClient:
    from claw.web.dashboard_server import _state
    from claw.web.dashboard_server import app as dash_app

    engine = AsyncMock()
    engine.close = AsyncMock()
    spool_dir = tmp_path / "specialist-exchanges"
    monkeypatch.setenv("CLAW_SPECIALIST_EXCHANGE_SPOOL_DIR", str(spool_dir))

    store: dict[str, ExternalSpecialistExchange] = {}

    async def _save_exchange(exchange: ExternalSpecialistExchange) -> ExternalSpecialistExchange:
        store[exchange.id] = exchange
        return exchange

    async def _get_exchange(exchange_id: str) -> ExternalSpecialistExchange | None:
        return store.get(exchange_id)

    async def _get_exchange_by_request(request_id: str) -> ExternalSpecialistExchange | None:
        return next(
            (exchange for exchange in store.values() if exchange.request_id == request_id), None
        )

    async def _list_exchanges(
        status: str | None = None, limit: int = 100
    ) -> list[ExternalSpecialistExchange]:
        items = list(store.values())
        if status:
            items = [exchange for exchange in items if exchange.status == status]
        return sorted(items, key=lambda exchange: exchange.updated_at, reverse=True)[:limit]

    async def _expire_exchanges() -> int:
        now = datetime.now(UTC)
        expired = 0
        for exchange in store.values():
            if (
                exchange.status in {"exported", "awaiting_reply"}
                and exchange.deadline_at
                and exchange.deadline_at < now
            ):
                exchange.status = "expired"
                exchange.failure_reason = (
                    exchange.failure_reason or "deadline passed before valid reply"
                )
                exchange.updated_at = now
                expired += 1
        return expired

    if "save_specialist_exchange" not in repo.__dict__:
        repo.save_specialist_exchange = AsyncMock(side_effect=lambda exchange: exchange)
    if "list_specialist_exchanges" not in repo.__dict__:
        repo.list_specialist_exchanges = AsyncMock(return_value=[])
    if "get_specialist_exchange" not in repo.__dict__:
        repo.get_specialist_exchange = AsyncMock(return_value=None)
    if "update_specialist_exchange" not in repo.__dict__:
        repo.update_specialist_exchange = AsyncMock(
            side_effect=lambda exchange_id, **updates: MagicMock(id=exchange_id, **updates)
        )
    if "save_external_specialist_exchange" not in repo.__dict__:
        repo.save_external_specialist_exchange = AsyncMock(side_effect=_save_exchange)
    if "get_external_specialist_exchange" not in repo.__dict__:
        repo.get_external_specialist_exchange = AsyncMock(side_effect=_get_exchange)
    if "get_external_specialist_exchange_by_request" not in repo.__dict__:
        repo.get_external_specialist_exchange_by_request = AsyncMock(
            side_effect=_get_exchange_by_request
        )
    if "list_external_specialist_exchanges" not in repo.__dict__:
        repo.list_external_specialist_exchanges = AsyncMock(side_effect=_list_exchanges)
    if "expire_external_specialist_exchanges" not in repo.__dict__:
        repo.expire_external_specialist_exchanges = AsyncMock(side_effect=_expire_exchanges)
    if "save_run_event" not in repo.__dict__:
        repo.save_run_event = AsyncMock(return_value=MagicMock())
    repo._external_specialist_exchange_store = store

    feature_flags = MagicMock()
    feature_flags.component_cards = False
    feature_flags.application_packets = False
    feature_flags.connectome_seq = False
    feature_flags.critical_slot_policy = False
    feature_flags.critical_slot_prewrite_block = False
    feature_flags.a2a_packets = a2a_packets

    config = MagicMock()
    config.feature_flags = feature_flags
    config.specialist_exchange_dir = str(spool_dir)
    config.external_specialist_exchange_dir = str(spool_dir)

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repo
    _state["federation"] = None
    _state["ready"] = True

    return TestClient(dash_app)


def _export_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "task_text": "Review the OAuth refresh-token race fix and return concrete risks.",
        "slot_name": "token_refresh_serialization",
        "preferred_agent": "codex",
        "target_language": "python",
        "deadline_seconds": 3600,
        "context": {
            "component_id": "comp_auth_refresh",
            "file_path": "app/auth/session.py",
            "risk": "critical",
        },
    }
    payload.update(overrides)
    return payload


def _valid_reply_envelope(request_id: str, **overrides: Any) -> dict[str, Any]:
    reply = {
        "schema_version": "cam.specialist.exchange.v1",
        "kind": "external_specialist_reply",
        "request_id": request_id,
        "reply_id": "reply_1",
        "specialist_identity": "codex",
        "recommendation_kind": "accepted_as_runner_up",
        "confidence": 0.84,
        "evidence": [
            {
                "kind": "analysis",
                "summary": (
                    "The proposed lock placement is sound if refresh failures clear the "
                    "in-flight marker."
                ),
            }
        ],
    }
    reply.update(overrides)
    return reply


def _write_reply(
    tmp_path: Path,
    request_id: str,
    payload: dict[str, Any] | None = None,
    filename: str = "reply.json",
) -> Path:
    inbox = tmp_path / "specialist-exchanges" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    reply_path = inbox / filename

    reply_path.write_text(
        json.dumps(payload or _valid_reply_envelope(request_id)), encoding="utf-8"
    )
    return reply_path


def _data(resp) -> dict[str, Any]:
    assert resp.headers["content-type"].startswith("application/json")
    return resp.json()


def _exchange_id(data: dict[str, Any]) -> str:
    exchange = data.get("exchange") if isinstance(data.get("exchange"), dict) else {}
    value = (
        data.get("exchange_id")
        or data.get("id")
        or exchange.get("exchange_id")
        or exchange.get("id")
    )
    assert isinstance(value, str) and value
    return value


def _status(data: dict[str, Any]) -> str:
    exchange = data.get("exchange") if isinstance(data.get("exchange"), dict) else {}
    value = (
        data.get("status") or exchange.get("status") or data.get("state") or exchange.get("state")
    )
    assert isinstance(value, str) and value
    return value


def _list_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = (
        data.get("items") or data.get("exchanges") or data.get("results") or data.get("imported")
    )
    assert isinstance(items, list)
    return items


def _find_exchange(items: list[dict[str, Any]], exchange_id: str) -> dict[str, Any]:
    for item in items:
        if item.get("exchange_id") == exchange_id or item.get("id") == exchange_id:
            return item
    raise AssertionError(f"exchange {exchange_id!r} not found in {items!r}")


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def test_specialist_exchange_export_rejects_when_feature_flag_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = AsyncMock()
    client = _setup_client(tmp_path, repo, monkeypatch, a2a_packets=False)

    resp = client.post("/api/v2/federation/specialist-exchanges/export", json=_export_payload())

    assert resp.status_code == 403
    assert "disabled" in str(_data(resp)).lower()
    repo.save_external_specialist_exchange.assert_not_awaited()


def test_specialist_exchange_export_persists_awaiting_reply_and_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = AsyncMock()
    client = _setup_client(tmp_path, repo, monkeypatch)

    export_resp = client.post(
        "/api/v2/federation/specialist-exchanges/export", json=_export_payload()
    )
    assert export_resp.status_code in {200, 201}
    exported = _data(export_resp)
    exchange_id = _exchange_id(exported)
    assert _status(exported) == "awaiting_reply"
    assert exported["request_path"]
    assert Path(exported["request_path"]).exists()

    list_resp = client.get("/api/v2/federation/specialist-exchanges")
    assert list_resp.status_code == 200
    listed = _find_exchange(_list_items(_data(list_resp)), exchange_id)
    assert (listed.get("status") or listed.get("state")) == "awaiting_reply"

    if repo.save_external_specialist_exchange.await_count:
        persisted = repo.save_external_specialist_exchange.await_args.args[0]
        assert _field(persisted, "status") == "awaiting_reply"


def test_specialist_exchange_import_valid_reply_reconciles_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = AsyncMock()
    client = _setup_client(tmp_path, repo, monkeypatch)

    export_resp = client.post(
        "/api/v2/federation/specialist-exchanges/export", json=_export_payload()
    )
    assert export_resp.status_code in {200, 201}
    exported = _data(export_resp)
    exchange_id = _exchange_id(exported)
    request_id = exported["request_envelope"]["request_id"]
    reply_path = _write_reply(tmp_path, request_id)

    import_resp = client.post(
        "/api/v2/federation/specialist-exchanges/import",
        json={"reply_path": reply_path.name},
    )

    assert import_resp.status_code == 200
    imported = _data(import_resp)
    exchange = _find_exchange(_list_items(imported), exchange_id)
    assert (exchange.get("status") or exchange.get("state")) in {"reply_received", "reconciled"}
    assert (exchange.get("outcome") or exchange.get("reconciliation_outcome")) == "reconciled"

    list_resp = client.get("/api/v2/federation/specialist-exchanges")
    listed = _find_exchange(_list_items(_data(list_resp)), exchange_id)
    assert (listed.get("status") or listed.get("state")) in {"reply_received", "reconciled"}
    assert (listed.get("outcome") or listed.get("reconciliation_outcome")) == "reconciled"


def test_specialist_exchange_duplicate_import_is_cleanly_handled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = AsyncMock()
    client = _setup_client(tmp_path, repo, monkeypatch)

    export_resp = client.post(
        "/api/v2/federation/specialist-exchanges/export", json=_export_payload()
    )
    assert export_resp.status_code in {200, 201}
    exported = _data(export_resp)
    request_id = exported["request_envelope"]["request_id"]
    reply_path = _write_reply(tmp_path, request_id)
    payload = {"reply_path": reply_path.name}

    first_resp = client.post("/api/v2/federation/specialist-exchanges/import", json=payload)
    assert first_resp.status_code == 200

    duplicate_resp = client.post("/api/v2/federation/specialist-exchanges/import", json=payload)
    assert duplicate_resp.status_code in {200, 202, 409}
    duplicate = _data(duplicate_resp)
    text = str(duplicate).lower()
    imported_items = _list_items(duplicate)
    assert (
        "duplicate" in text
        or "already" in text
        or any(
            (item.get("status") or item.get("state")) in {"reply_received", "reconciled"}
            for item in imported_items
        )
        or duplicate.get("outcome") in {"duplicate", "already_imported", "reconciled"}
    )


def test_specialist_exchange_expired_deadline_is_marked_or_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = AsyncMock()
    client = _setup_client(tmp_path, repo, monkeypatch)

    export_resp = client.post(
        "/api/v2/federation/specialist-exchanges/export",
        json=_export_payload(deadline_seconds=3600),
    )

    assert export_resp.status_code in {200, 201}
    exported = _data(export_resp)
    exchange_id = _exchange_id(exported)
    request_id = exported["request_envelope"]["request_id"]
    stored = repo._external_specialist_exchange_store[exchange_id]
    stored.deadline_at = datetime.now(UTC) - timedelta(minutes=5)
    reply_path = _write_reply(tmp_path, request_id)
    import_resp = client.post(
        "/api/v2/federation/specialist-exchanges/import",
        json={"reply_path": reply_path.name},
    )
    assert import_resp.status_code in {200, 400, 409, 410}
    import_data = _data(import_resp)
    assert "expired" in str(import_data).lower() or any(
        (item.get("exchange_id") == exchange_id or item.get("id") == exchange_id)
        and (item.get("status") or item.get("state")) in {"expired", "rejected"}
        for item in _list_items(import_data)
    )

    list_resp = client.get("/api/v2/federation/specialist-exchanges")
    listed = _find_exchange(_list_items(_data(list_resp)), exchange_id)
    assert (listed.get("status") or listed.get("state")) in {"expired", "rejected"}


def test_specialist_exchange_import_rejects_invalid_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = AsyncMock()
    client = _setup_client(tmp_path, repo, monkeypatch)

    export_resp = client.post(
        "/api/v2/federation/specialist-exchanges/export", json=_export_payload()
    )
    assert export_resp.status_code in {200, 201}
    request_id = _data(export_resp)["request_envelope"]["request_id"]
    reply_path = _write_reply(
        tmp_path,
        request_id,
        payload=_valid_reply_envelope(request_id, confidence=1.7),
        filename="bad-reply.json",
    )

    resp = client.post(
        "/api/v2/federation/specialist-exchanges/import",
        json={"reply_path": reply_path.name},
    )

    assert resp.status_code in {200, 400, 409, 422}
    text = str(_data(resp)).lower()
    assert "invalid" in text or "rejected" in text or "confidence" in text


@pytest.mark.asyncio
async def test_external_specialist_exchange_repository_roundtrip(tmp_path: Path):
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "claw.db")))
    await engine.connect()
    try:
        await engine.initialize_schema()
        repo = Repository(engine)
        exchange = ExternalSpecialistExchange(
            id="specex_repo",
            request_id="specreq_repo",
            task_text="Review packet handoff",
            specialty="security",
            status="awaiting_reply",
            request_json={"schema_version": "cam.specialist.exchange.v1"},
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        saved = await repo.save_external_specialist_exchange(exchange)
        assert saved.id == "specex_repo"

        fetched = await repo.get_external_specialist_exchange_by_request("specreq_repo")
        assert fetched is not None
        assert fetched.request_json["schema_version"] == "cam.specialist.exchange.v1"

        expired_count = await repo.expire_external_specialist_exchanges()
        assert expired_count == 1
        listed = await repo.list_external_specialist_exchanges(status="expired")
        assert [item.id for item in listed] == ["specex_repo"]
        assert listed[0].failure_reason
    finally:
        await engine.close()
