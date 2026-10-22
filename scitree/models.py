"""Data models and helper utilities for sciTree entities."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scitree import SCHEMA_VERSION
from scitree.errors import ERR_ACTOR_REQUIRED, ERR_VALIDATION_ERROR, SciTreeError

VALID_ACTOR_TYPES = {"human", "agent"}
VALID_ACTOR_SOURCES = {"ui", "cli", "http", "mcp", "manifest"}
VALID_VERSION_STATES = {"draft", "submitted", "published", "revision"}
VALID_FILE_KINDS = {"data", "figure", "manuscript"}
VALID_COMMENT_STATUSES = {"pending", "resolved"}
VALID_RISK_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_RISK_LIKELIHOODS = {"low", "medium", "high"}
VALID_RISK_STATUSES = {"open", "mitigating", "closed"}
VALID_MILESTONE_STATUSES = {"pending", "in_progress", "done", "missed"}
VALID_MILESTONE_PHASES = {
    "short_term_7d",
    "medium_term_30d",
    "submission_ready",
    "revision_ready",
    "custom",
}
MILESTONE_PHASE_ORDER = [
    "short_term_7d",
    "medium_term_30d",
    "submission_ready",
    "revision_ready",
    "custom",
]

VALID_EVENT_TYPES = {
    "project.created",
    "project.updated",
    "project.column_changed",
    "project.template_applied",
    "version.added",
    "version.submitted",
    "version.locked",
    "version.published",
    "version.derived",
    "version.archived",
    "file.added",
    "file.removed",
    "comment.added",
    "comment.resolved",
    "comment.reopened",
    "risk.added",
    "risk.updated",
    "risk.closed",
    "milestone.added",
    "milestone.updated",
    "milestone.completed",
    "milestone.missed",
    "zotero.linked",
    "zotero.unlinked",
    "zotero.synced",
    "export.created",
    "note.added",
}


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_id(prefix: str) -> str:
    """Generate a compact readable unique identifier with the given prefix."""
    token = uuid.uuid4().hex[:12].upper()
    return f"{prefix}_{token}"


def slugify(name: str) -> str:
    """Convert a project or template name into a URL/filesystem-safe slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "project"


def safe_folder_name(name: str) -> str:
    """Convert a project name into a human-readable, filesystem-safe folder name."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned or "Project"


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest with 'sha256:' prefix for a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def validate_actor(
    actor_name: str | None = None,
    actor_type: str | None = None,
    actor_source: str = "cli",
    actor_id: str | None = None,
    require_agent_name: bool = False,
) -> dict[str, Any]:
    """Validate and normalize actor attribution dictionary (Section E1 & I5)."""
    if actor_source not in VALID_ACTOR_SOURCES:
        raise SciTreeError(
            ERR_VALIDATION_ERROR,
            f"Invalid actor_source '{actor_source}'. Expected one of {sorted(VALID_ACTOR_SOURCES)}.",
        )

    effective_type = actor_type
    if not effective_type:
        if actor_source in {"mcp", "manifest"}:
            effective_type = "agent"
        elif actor_name and actor_name.lower().startswith(("agent:", "system:")):
            effective_type = "agent"
        else:
            effective_type = "human"

    if effective_type not in VALID_ACTOR_TYPES:
        raise SciTreeError(
            ERR_VALIDATION_ERROR,
            f"Invalid actor_type '{effective_type}'. Expected one of {sorted(VALID_ACTOR_TYPES)}.",
        )

    if effective_type == "agent" and require_agent_name and (not actor_name or not actor_name.strip()):
        raise SciTreeError(
            ERR_ACTOR_REQUIRED,
            "Mutations performed by an agent require a non-empty actor_name.",
            {"actor_type": effective_type, "actor_source": actor_source},
        )

    effective_name = (actor_name or "").strip()
    if not effective_name:
        effective_name = f"agent:{actor_source}" if effective_type == "agent" else "local-user"

    result: dict[str, Any] = {
        "actor_name": effective_name,
        "actor_type": effective_type,
        "actor_source": actor_source,
    }
    if actor_id:
        result["actor_id"] = actor_id
    return result


def wrap_response(data: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ensure every response payload carries schema_version and optional actor attribution."""
    payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if actor is not None:
        payload["actor"] = actor
    payload.update(data)
    return payload
