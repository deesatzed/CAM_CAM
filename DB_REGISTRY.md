# CAM Database Registry

**Canonical runtime:** `/Volumes/WS4TB/repo622sn/CAM_CAM`

This file records the database topology selected by the tracked `claw.toml`. It is not an inventory of every historical CAM database or backup on attached volumes.

| Role | Path | Configuration | Verified 2026-08-09 |
|---|---|---|---:|
| Live root corpus | `/Volumes/WS4TB/repo622sn/CAM_CAM/claw.db` | `[database].db_path` | 2,668 methodologies; integrity `ok` |
| Go sibling ganglion | `/Volumes/WS4TB/repo622sn/instances/go/claw.db` | `[[instances.siblings]]`, name `go` | 53 methodologies; integrity `ok` |
| Misc sibling ganglion | `/Volumes/WS4TB/repo622sn/instances/misc/claw.db` | `[[instances.siblings]]`, name `misc` | 28 methodologies; integrity `ok` |

## Operational Rules

- Pin both `--config /Volumes/WS4TB/repo622sn/CAM_CAM/claw.toml` and `--db /Volumes/WS4TB/repo622sn/CAM_CAM/claw.db` for corpus-changing operations.
- Treat `claw.db-wal` and `claw.db-shm` as live SQLite state. They are ignored by Git but must not be deleted as a cleanup step.
- Treat `claw.db.bak-*` and `*.db.bak-*` as recoverable local backups, not source files.
- Run `PRAGMA integrity_check;` before and after material corpus operations.
- Update this registry whenever the tracked configuration changes the live root or sibling topology.

## Non-Canonical Copies

Older checkouts and backups may contain files named `claw.db`. Their presence does not make them active. The paths above are authoritative until a reviewed configuration change updates both `claw.toml` and this registry.
