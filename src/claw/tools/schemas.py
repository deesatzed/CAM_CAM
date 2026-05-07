"""Pydantic input schemas for CLAW MCP tools.

Each MCP tool has a corresponding Pydantic model that validates input
parameters and generates JSON Schema for the MCP protocol.  This replaces
the hardcoded TOOL_SCHEMAS dicts in mcp_server.py with type-safe models.

Usage:
    from claw.tools.schemas import generate_mcp_tool_schemas, validate_tool_input

    schemas = generate_mcp_tool_schemas()   # for MCP list_tools
    parsed = validate_tool_input("claw_query_memory", {"query": "retry logic"})
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Input models — one per MCP tool
# ---------------------------------------------------------------------------

class QueryMemoryInput(BaseModel):
    """Input for claw_query_memory: search semantic memory for past solutions."""
    query: str = Field(..., description="Search query describing the problem or pattern you need")
    limit: int = Field(default=3, ge=1, le=20, description="Maximum number of results to return")
    language: Optional[str] = Field(default=None, description="Filter results by programming language")


class StoreFindingInput(BaseModel):
    """Input for claw_store_finding: persist a discovered pattern or fix."""
    problem_description: str = Field(..., description="Description of the problem this finding solves")
    solution_code: str = Field(..., description="The solution code, pattern, or technique")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    methodology_type: Optional[str] = Field(default=None, description="Type: PATTERN, FIX, ARCHITECTURE, TECHNIQUE")


class VerifyClaimInput(BaseModel):
    """Input for claw_verify_claim: validate a code assertion."""
    claim: str = Field(..., description="The claim to verify (e.g. 'all tests pass')")
    workspace_dir: Optional[str] = Field(default=None, description="Path to workspace for file-based checks")


class RequestSpecialistInput(BaseModel):
    """Input for claw_request_specialist: route a subtask to a different agent."""
    task_description: str = Field(..., description="Description of the subtask to delegate")
    preferred_agent: Optional[Literal["claude", "codex", "gemini", "grok"]] = Field(
        default=None, description="Preferred agent for the task"
    )


class EscalateInput(BaseModel):
    """Input for claw_escalate: flag a task as requiring human intervention."""
    reason: str = Field(..., description="Why this task cannot be completed autonomously")
    context: Optional[dict[str, Any]] = Field(default=None, description="Additional context for the human reviewer")
    task_id: Optional[str] = Field(default=None, description="ID of the task being escalated")


class DecomposeTaskInput(BaseModel):
    """Input for claw_decompose_task."""
    task_text: str = Field(..., description="Task to decompose into slots")
    workspace_dir: Optional[str] = Field(default=None, description="Optional workspace root")
    target_language: Optional[str] = Field(default=None, description="Optional target language hint")
    target_stack_hints: list[str] = Field(default_factory=list, description="Optional stack hints")
    check_commands: list[str] = Field(default_factory=list, description="Optional verification commands")


class BuildApplicationPacketInput(BaseModel):
    """Input for claw_build_application_packet."""
    workspace_dir: str = Field(..., description="Workspace root for the target repository")
    task_text: str = Field(..., description="Task request")
    slot_name: str = Field(..., description="Slot name to build a packet for")
    target_language: Optional[str] = Field(default=None, description="Optional language hint")
    target_stack_hints: list[str] = Field(default_factory=list, description="Optional stack hints")


class GetRunConnectomeInput(BaseModel):
    """Input for claw_get_run_connectome."""
    run_id: str = Field(..., description="Reviewed run identifier")


class TraceFailureInput(BaseModel):
    """Input for claw_trace_failure."""
    run_id: str = Field(..., description="Reviewed run identifier")
    root: Optional[str] = Field(default=None, description="Optional failure root such as test:<name>")


class PromoteRecipeInput(BaseModel):
    """Input for claw_promote_recipe."""
    run_id: str = Field(..., description="Reviewed run identifier")
    recipe_name: str = Field(..., description="Recipe name to promote")
    minimum_sample_size: int = Field(default=5, ge=1, description="Minimum sample size gate")


class QueueMiningMissionInput(BaseModel):
    """Input for claw_queue_mining_mission."""
    run_id: str = Field(..., description="Reviewed run identifier")
    slot_family: str = Field(..., description="Slot family or gap family to mine")
    priority: str = Field(default="medium", description="Mission priority")
    reason: str = Field(..., description="Why the mining mission is needed")


class RequestSpecialistPacketInput(BaseModel):
    """Input for claw_request_specialist_packet."""
    task_text: str = Field(..., description="Task request that needs specialist packet help")
    slot_name: Optional[str] = Field(default=None, description="Optional target slot name")
    preferred_agent: Optional[Literal["claude", "codex", "gemini", "grok"]] = Field(
        default=None, description="Preferred specialist agent"
    )
    target_language: Optional[str] = Field(default=None, description="Optional language hint")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum packet candidates to return")


class ExportSpecialistExchangeInput(BaseModel):
    """Input for claw_export_specialist_exchange."""
    task_text: str = Field(..., description="Task request to hand off for external specialist review")
    slot_name: Optional[str] = Field(default=None, description="Optional target slot name")
    preferred_agent: Optional[Literal["claude", "codex", "gemini", "grok"]] = Field(
        default=None, description="Preferred specialist agent"
    )
    target_language: Optional[str] = Field(default=None, description="Optional language hint")
    deadline_seconds: Optional[int] = Field(default=None, ge=1, description="Optional reply deadline")
    workspace_dir: Optional[str] = Field(default=None, description="Workspace root for the exchange spool")
    plan_id: Optional[str] = Field(default=None, description="Optional CAM-SEQ plan identifier")
    slot_id: Optional[str] = Field(default=None, description="Optional CAM-SEQ slot identifier")
    packet_id: Optional[str] = Field(default=None, description="Optional application packet identifier")
    allowed_context: dict[str, Any] = Field(default_factory=dict, description="Bounded context allowed in the handoff")
    redaction_summary: str = Field(default="", description="Summary of redactions applied before export")


class ImportSpecialistExchangeInput(BaseModel):
    """Input for claw_import_specialist_exchange."""
    reply_path: Optional[str] = Field(default=None, description="Optional inbox reply filename or path")
    workspace_dir: Optional[str] = Field(default=None, description="Workspace root for the exchange spool")


class ListSpecialistExchangesInput(BaseModel):
    """Input for claw_list_specialist_exchanges."""
    status: Optional[str] = Field(default=None, description="Optional exchange status filter")
    limit: int = Field(default=25, ge=1, le=100, description="Maximum exchanges to return")


class BridgeSpecialistExchangeInput(BaseModel):
    """Input for claw_bridge_specialist_exchange."""
    exchange_id: str = Field(..., description="External specialist exchange ID to submit")
    command: Optional[str] = Field(default=None, description="External MCP stdio server command")
    args: list[str] = Field(default_factory=list, description="External MCP stdio server args")
    tool_name: str = Field(
        default="claw_request_specialist_packet",
        description="External MCP tool to call",
    )
    workspace_dir: Optional[str] = Field(default=None, description="Workspace root for the exchange spool")
    timeout_seconds: int = Field(default=60, ge=1, le=600, description="External MCP call timeout")
    max_reply_bytes: int = Field(default=65536, ge=1024, le=1048576, description="Reply size cap")
    specialist_identity: str = Field(default="mcp_bridge", description="Bridge identity label")


class SubmitSpecialistWebhookInput(BaseModel):
    """Input for claw_submit_specialist_webhook."""
    exchange_id: str = Field(..., description="External specialist exchange ID to submit")
    endpoint_url: str = Field(..., description="HTTPS endpoint that accepts CAM exchange envelopes")
    shared_secret: str = Field(..., description="HMAC secret used to sign the webhook body")
    timeout_seconds: int = Field(default=30, ge=1, le=300, description="HTTP submit timeout")
    allow_http: bool = Field(
        default=False,
        description="Allow plain HTTP for local test transports only",
    )


# ---------------------------------------------------------------------------
# Tool metadata registry
# ---------------------------------------------------------------------------

TOOL_METADATA: dict[str, tuple[type[BaseModel], str]] = {
    "claw_query_memory": (
        QueryMemoryInput,
        "Query CLAW's semantic memory for similar past solutions, patterns, and techniques.",
    ),
    "claw_store_finding": (
        StoreFindingInput,
        "Store a discovered pattern, fix, or technique in CLAW's semantic memory for fleet-wide reuse.",
    ),
    "claw_verify_claim": (
        VerifyClaimInput,
        "Verify a code assertion by scanning for placeholders, TODOs, and unsubstantiated claims.",
    ),
    "claw_request_specialist": (
        RequestSpecialistInput,
        "Request a different AI agent (claude, codex, gemini, grok) to handle a subtask.",
    ),
    "claw_escalate": (
        EscalateInput,
        "Flag a task as beyond AI capability and escalate to human review.",
    ),
    "claw_decompose_task": (
        DecomposeTaskInput,
        "Decompose a task into CAM-SEQ archetype and slot structure.",
    ),
    "claw_build_application_packet": (
        BuildApplicationPacketInput,
        "Build a CAM-SEQ application packet for a specific slot.",
    ),
    "claw_get_run_connectome": (
        GetRunConnectomeInput,
        "Return the stored connectome for a reviewed CAM-SEQ run.",
    ),
    "claw_trace_failure": (
        TraceFailureInput,
        "Trace a reviewed CAM-SEQ failure backward through its causal chain.",
    ),
    "claw_promote_recipe": (
        PromoteRecipeInput,
        "Promote a successful reviewed run into a compiled recipe.",
    ),
    "claw_queue_mining_mission": (
        QueueMiningMissionInput,
        "Queue a durable mining mission from a reviewed run gap.",
    ),
    "claw_request_specialist_packet": (
        RequestSpecialistPacketInput,
        "Request a structured specialist packet recommendation with packet candidates and routing guidance.",
    ),
    "claw_export_specialist_exchange": (
        ExportSpecialistExchangeInput,
        "Export a schema-versioned external specialist handoff envelope to the file spool.",
    ),
    "claw_import_specialist_exchange": (
        ImportSpecialistExchangeInput,
        "Import schema-versioned external specialist replies from the file spool inbox.",
    ),
    "claw_list_specialist_exchanges": (
        ListSpecialistExchangesInput,
        "List durable external specialist exchange lifecycle records.",
    ),
    "claw_bridge_specialist_exchange": (
        BridgeSpecialistExchangeInput,
        "Submit an existing specialist exchange envelope to an external MCP tool and import its reply.",
    ),
    "claw_submit_specialist_webhook": (
        SubmitSpecialistWebhookInput,
        "Submit an existing specialist exchange envelope to a signed HTTPS webhook endpoint.",
    ),
}


# ---------------------------------------------------------------------------
# Schema generation and validation
# ---------------------------------------------------------------------------

def generate_mcp_tool_schemas() -> list[dict[str, Any]]:
    """Generate MCP-format tool schema list from Pydantic models.

    Returns a list of dicts, each with 'name', 'description', and 'inputSchema'
    keys, suitable for MCP's list_tools response.
    """
    schemas: list[dict[str, Any]] = []
    for tool_name, (model_cls, description) in TOOL_METADATA.items():
        json_schema = model_cls.model_json_schema()
        # MCP expects inputSchema at the top level, not wrapped in $defs
        schemas.append({
            "name": tool_name,
            "description": description,
            "inputSchema": json_schema,
        })
    return schemas


def validate_tool_input(tool_name: str, arguments: dict[str, Any]) -> BaseModel:
    """Validate tool arguments against the Pydantic model.

    Args:
        tool_name: The MCP tool name (e.g. 'claw_query_memory').
        arguments: Raw dict of arguments from the MCP call.

    Returns:
        A validated Pydantic model instance.

    Raises:
        KeyError: If tool_name is not recognized.
        pydantic.ValidationError: If arguments fail validation.
    """
    if tool_name not in TOOL_METADATA:
        raise KeyError(f"Unknown tool: {tool_name}")
    model_cls, _ = TOOL_METADATA[tool_name]
    return model_cls.model_validate(arguments)
