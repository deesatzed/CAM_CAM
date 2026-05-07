# CAM-SEQ M7 External Specialist Exchange Plan

Date: 2026-05-07
Status: Planning draft
Scope: docs-only plan for the remaining M7 A2A/external specialist exchange gap

## Objective

Add the smallest useful handoff surface that lets CAM-SEQ package a weak or high-risk slot for an external specialist and ingest a bounded reply without changing parser or security internals.

This is not a new autonomous transport layer yet. The first milestone should prove that CAM can create, export, track, and reconcile specialist packets while preserving the canonical chain:

Component Card -> Slot -> Application Packet -> Pair Event -> Landing Event -> Outcome Event -> Recipe

## Current Base

Already present in M7:

- packet-native federation search and UI
- specialist packet exchange route and MCP tool
- mining mission queue
- recipe promotion and automatic repeated-success distillation
- federation trend signals that can become governance recommendations

Remaining gap:

- no true A2A transport or external specialist exchange boundary with durable request/reply state, identity, timeout, trust, and replay behavior

## Minimal Surface

Implement the first external exchange as a packet handoff envelope, not as direct remote execution.

### Candidate 1: File-Based Handoff Spool

Shape:

- write JSON request envelopes under a configured spool directory
- read JSON reply envelopes from a sibling inbox directory
- require explicit operator or MCP client movement between outbox and inbox

Why first:

- deterministic
- easy to test without network
- works with human specialists, Codex/Claude/Gemini sessions, and future bridge processes
- keeps transport risk out of the core packet model

Implementation candidates:

- `ExternalSpecialistRequest` envelope with request ID, plan ID, slot ID, packet ID, requested specialty, task text, allowed context, deadline, and redaction summary
- `ExternalSpecialistReply` envelope with reply ID, request ID, specialist identity, recommendation kind, candidate component refs or patch notes, confidence, evidence, constraints, and unsafe/unusable reasons
- repository persistence for request/reply metadata, with raw envelope path retained for audit
- MCP tools:
  - `claw_export_specialist_packet`
  - `claw_import_specialist_reply`
  - `claw_list_specialist_exchanges`

### Candidate 2: MCP-to-MCP Bridge

Shape:

- CAM keeps the same envelope model
- a bridge process sends request envelopes to a configured external MCP server and imports replies

Why later:

- closer to real A2A behavior
- still avoids changing the packet model
- requires timeout, auth, and tool capability negotiation decisions

Implementation candidates:

- bridge config with allowed server names, allowed tools, timeout, max bytes, and auth token source
- capability probe result cached per specialist
- replies imported through the same reconciliation path as file-based replies

### Candidate 3: HTTP Webhook Adapter

Shape:

- POST request envelopes to a configured HTTPS endpoint
- accept signed webhook replies

Why last:

- useful for remote teams and managed specialists
- highest operational/security surface
- should reuse the same envelope and reconciliation semantics after Candidate 1 proves the model

Implementation candidates:

- allowlist by endpoint origin
- request signing and reply signature verification
- idempotency keys per exchange ID
- dead-letter queue for malformed, late, duplicate, or untrusted replies

## Exchange Lifecycle

Minimum states:

- `draft`: envelope assembled but not exported
- `exported`: handoff created and durable
- `awaiting_reply`: external side owns the next action
- `reply_received`: reply imported and schema-valid
- `reconciled`: reply was accepted, rejected, or converted into a packet candidate
- `expired`: deadline passed without a valid reply
- `revoked`: operator canceled the exchange

Reconciliation outcomes:

- `accepted_as_runner_up`
- `accepted_as_selected_candidate`
- `stored_as_mining_mission`
- `stored_as_failure_context`
- `rejected_low_evidence`
- `rejected_policy_or_scope`
- `rejected_schema_or_trust`

## Acceptance Criteria

- A weak-evidence or high-risk slot can produce a schema-versioned external handoff envelope from an existing plan/packet.
- The envelope contains no unbounded workspace dump; context is explicit, scoped, and redaction-aware.
- A reply can be imported idempotently and tied back to the original plan, slot, packet, and specialist identity.
- Invalid, late, duplicate, oversized, or untrusted replies fail closed and remain inspectable.
- Accepted replies do not mutate source code directly; they only influence packet selection, runner-up state, mining missions, or failure context.
- The operator can list exchange status and inspect request/reply summaries.
- Existing MCP tool semantics remain unchanged; new external-exchange tools are additive.
- Feature flags off leave current CAM, CAM-SEQ, federation, and MCP behavior unchanged.
- Focused tests cover envelope validation, file-spool round trip, duplicate import, timeout/expiry, and rejected reply cases before code rollout.

## Risks

- Context leakage: specialist packets may expose secrets or unnecessary source. Mitigation: scoped context builder, redaction summary, size caps, and explicit included-file list.
- Trust confusion: external replies may look authoritative without evidence. Mitigation: specialist identity, confidence basis, evidence list, and policy-aware reconciliation.
- Transport creep: adding HTTP or MCP bridge first could blur handoff and execution. Mitigation: file-spool envelope first, bridge second.
- Packet drift: external advice may bypass Application Packet review. Mitigation: imported replies only become candidates or annotations until reviewed.
- Replay and duplicate replies: delayed specialists may send stale advice. Mitigation: exchange ID, request hash, deadline, idempotency key, and terminal states.
- Security lane bypass: specialist recommendations might weaken critical-slot gates. Mitigation: critical slots preserve existing proof gates, waiver rules, and policy checks.

## Proposed Rollout

1. Freeze envelope schemas and lifecycle names in docs.
2. Add file-spool export/import behind `a2a_packets`.
3. Add MCP listing/export/import tools over the same repository methods.
4. Surface status in Federation Hub or plan review without creating a new app section.
5. Add MCP-to-MCP bridge only after file-spool behavior is validated.
6. Defer signed HTTP webhooks until the trust, audit, and replay model has real use.

## Non-Goals For This Slice

- remote code execution by specialists
- automatic source mutation from external replies
- broad HTTP transport
- changes to parser precision work
- changes to Semgrep, CodeQL, or critical-slot policy internals
- broad benchmark expansion beyond focused exchange tests
