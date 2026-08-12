"""Deterministic, read-only inventory of a Typer command tree."""

from __future__ import annotations

from typing import Any

from typer import Typer
from typer.main import get_command_name, solve_typer_info_defaults


def _command_path(prefix: tuple[str, ...], name: str) -> str:
    return " ".join((*prefix, name))


def _inventory(
    application: Typer,
    *,
    prefix: tuple[str, ...] = (),
    parent_hidden: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for command in application.registered_commands:
        if command.callback is None:
            continue
        name = command.name or get_command_name(command.callback.__name__)
        items.append(
            {
                "path": _command_path(prefix, name),
                "kind": "command",
                "hidden": parent_hidden or bool(command.hidden),
            }
        )

    for group in application.registered_groups:
        solved = solve_typer_info_defaults(group)
        name = solved.name
        child_prefix = prefix
        child_hidden = parent_hidden or bool(solved.hidden)
        if name:
            child_prefix = (*prefix, name)
            items.append(
                {
                    "path": " ".join(child_prefix),
                    "kind": "group",
                    "hidden": child_hidden,
                }
            )
        items.extend(
            _inventory(
                group.typer_instance,
                prefix=child_prefix,
                parent_hidden=child_hidden,
            )
        )

    return items


def build_capability_manifest(application: Typer) -> dict[str, Any]:
    """Return every registered CLI path in a stable JSON-serializable payload."""
    items = sorted(
        _inventory(application),
        key=lambda item: (item["path"], item["kind"]),
    )
    paths = [item["path"] for item in items]
    if len(paths) != len(set(paths)):
        raise ValueError("Typer command tree contains duplicate invocation paths")
    return {"schema_version": 1, "items": items}
