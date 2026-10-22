"""Model Context Protocol (MCP) server for sciTree (Requirement D & Section I4).

Exposes all sciTree operations as MCP tools backed by SciTreeCore.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as _MCPServerClass
except ImportError:
    from mcp.server.fastmcp import FastMCP as _MCPServerClass  # type: ignore[no-redef]

from scitree.core import SciTreeCore
from scitree.errors import SciTreeError
from scitree.models import validate_actor

mcp_server = _MCPServerClass("sciTree")


def _exec_tool(
    root: str | None,
    auto_root: bool,
    actor_name: str,
    actor_type: str,
    fn: Any,
) -> dict[str, Any]:
    try:
        core = SciTreeCore(root_path=root, auto_root=auto_root)
        actor = validate_actor(
            actor_name=actor_name,
            actor_type=actor_type,
            actor_source="mcp",
            require_agent_name=(actor_type == "agent"),
        )
        return fn(core, actor)
    except SciTreeError as exc:
        return exc.to_dict()


@mcp_server.tool()
def init_root(
    root: str | None = None,
    auto_root: bool = False,
    reset: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Initialize or reset the sciTree root directory."""
    if reset:
        return _exec_tool(
            root,
            auto_root,
            actor_name,
            actor_type,
            lambda core, actor: core.reset_onboarding(actor=actor, dry_run=dry_run),
        )
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.init_root(root_path=root, auto_root=auto_root, actor=actor, dry_run=dry_run),
    )


@mcp_server.tool()
def create_project(
    name: str,
    description: str = "",
    column: str | None = None,
    template: str | None = None,
    owner_type: str | None = None,
    owner_name: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a new scientific manuscript project idempotently."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.create_project(
            name=name,
            description=description,
            column=column,
            template_name=template,
            owner_type=owner_type,
            owner_name=owner_name,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def list_projects(
    column: str | None = None,
    owner_type: str | None = None,
    has_pending_comments: bool | None = None,
    author: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """List all projects with optional filter and sort parameters."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_projects(
            column=column,
            owner_type=owner_type,
            has_pending_comments=has_pending_comments,
            author=author,
            search=search,
            sort_by=sort_by,
        ),
    )


@mcp_server.tool()
def get_project(
    name: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """Retrieve complete project metadata by name, slug, or ID."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.get_project(name=name),
    )


@mcp_server.tool()
def move_project(
    name: str,
    column: str,
    description: str | None = None,
    owner_type: str | None = None,
    owner_name: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Move a project card to a target Kanban lifecycle column."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.move_project(
            name=name,
            column=column,
            description=description,
            owner_type=owner_type,
            owner_name=owner_name,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def add_version(
    project: str,
    file: str,
    author: str,
    version_id: str | None = None,
    changelog: str = "",
    state: str = "draft",
    derived_from: str | None = None,
    submitted_to: str | None = None,
    auto_suffix: bool = False,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add a new DOCX/PDF manuscript version and extract figures, references, and comments."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.add_version(
            project_name=project,
            file_path=file,
            author=author,
            version_id=version_id,
            changelog=changelog,
            state=state,
            derived_from=derived_from,
            submitted_to=submitted_to,
            auto_suffix=auto_suffix,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def list_versions(
    project: str,
    include_archived: bool = False,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """List manuscript versions for a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_versions(project_name=project, include_archived=include_archived),
    )


@mcp_server.tool()
def update_version_state(
    project: str,
    version_id: str,
    state: str | None = None,
    changelog: str | None = None,
    submitted_to: str | None = None,
    archived: bool | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote a manuscript version to submitted/published (immutable) or archive it."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.update_version_state(
            project_name=project,
            version_id=version_id,
            state=state,
            changelog=changelog,
            submitted_to=submitted_to,
            archived=archived,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def add_file(
    project: str,
    file: str,
    kind: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upload a data, standalone figure, or manuscript file to a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.add_file(
            project_name=project,
            file_path=file,
            kind=kind,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def add_comment(
    project: str,
    text: str,
    version: str | None = None,
    owner_type: str | None = None,
    owner_name: str | None = None,
    comment_id: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a comment card on a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.add_comment(
            project_name=project,
            text=text,
            version=version,
            owner_type=owner_type,
            owner_name=owner_name,
            comment_id=comment_id,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def resolve_comment(
    project: str,
    comment_id: str,
    resolved: bool = True,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Resolve or reopen a comment card."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.resolve_comment(
            project_name=project,
            comment_id=comment_id,
            resolved=resolved,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def list_comments(
    project: str,
    status: str | None = None,
    owner_type: str | None = None,
    version: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """List comment cards for a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_comments(
            project_name=project,
            status=status,
            owner_type=owner_type,
            version=version,
        ),
    )


@mcp_server.tool()
def add_risk(
    project: str,
    title: str,
    description: str = "",
    severity: str = "medium",
    likelihood: str = "medium",
    owner: str = "",
    status: str = "open",
    trigger: str = "",
    mitigation: str = "",
    risk_id: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add a risk entry to a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.add_risk(
            project_name=project,
            title=title,
            description=description,
            severity=severity,
            likelihood=likelihood,
            owner=owner,
            status=status,
            trigger=trigger,
            mitigation=mitigation,
            risk_id=risk_id,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def list_risks(
    project: str,
    status: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """List risks for a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_risks(project_name=project, status=status),
    )


@mcp_server.tool()
def update_risk(
    project: str,
    risk_id: str,
    title: str | None = None,
    description: str | None = None,
    severity: str | None = None,
    likelihood: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    mitigation: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update fields of an existing risk."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.update_risk(
            project_name=project,
            risk_id=risk_id,
            title=title,
            description=description,
            severity=severity,
            likelihood=likelihood,
            owner=owner,
            status=status,
            trigger=trigger,
            mitigation=mitigation,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def close_risk(
    project: str,
    risk_id: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Close an open or mitigating risk."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.close_risk(
            project_name=project,
            risk_id=risk_id,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def add_milestone(
    project: str,
    title: str,
    phase: str = "short_term_7d",
    description: str = "",
    due_date: str | None = None,
    status: str = "pending",
    milestone_id: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add a milestone to a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.add_milestone(
            project_name=project,
            title=title,
            phase=phase,
            description=description,
            due_date=due_date,
            status=status,
            milestone_id=milestone_id,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def list_milestones(
    project: str,
    status: str | None = None,
    phase: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """List milestones for a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_milestones(project_name=project, status=status, phase=phase),
    )


@mcp_server.tool()
def update_milestone(
    project: str,
    milestone_id: str,
    title: str | None = None,
    description: str | None = None,
    phase: str | None = None,
    due_date: str | None = None,
    status: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update an existing milestone."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.update_milestone(
            project_name=project,
            milestone_id=milestone_id,
            title=title,
            description=description,
            phase=phase,
            due_date=due_date,
            status=status,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def close_milestone(
    project: str,
    milestone_id: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mark a milestone as done."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.close_milestone(
            project_name=project,
            milestone_id=milestone_id,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def add_timeline_note(
    project: str,
    note: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append a manual note event to a project's Timeline / Activity Log."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.add_timeline_note(
            project_name=project,
            note=note,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def get_timeline(
    project: str,
    actor_type_filter: str | None = None,
    actor_source: str | None = None,
    event_type: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """Retrieve the chronological Timeline / Route View grouped by day."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.get_timeline(
            project_name=project,
            actor_type=actor_type_filter,
            actor_source=actor_source,
            event_type=event_type,
        ),
    )


@mcp_server.tool()
def list_activity(
    project: str,
    actor_type_filter: str | None = None,
    actor_source: str | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """Query the append-only Activity Log for a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_activity(
            project_name=project,
            actor_type=actor_type_filter,
            actor_source=actor_source,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
        ),
    )


@mcp_server.tool()
def export_package(
    project: str,
    version: str | None = None,
    output_path: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Export a reproducible .zip submission package for a project and version."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.export_package(
            project_name=project,
            version_id=version,
            output_path=output_path,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def list_templates(
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
) -> dict[str, Any]:
    """List all built-in and custom project templates."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, _: core.list_templates(),
    )


@mcp_server.tool()
def save_template(
    project: str,
    name: str,
    description: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Save a custom template from an existing project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.save_template(
            project_name=project,
            template_name=name,
            description=description,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def template_apply(
    project: str,
    template: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply a template to an existing project (adds missing items; never removes)."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.apply_template(
            project_name=project,
            template_name=template,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def zotero_link(
    project: str,
    collection_key: str,
    collection_name: str | None = None,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Link a Zotero collection key to a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.zotero_link(
            project_name=project,
            collection_key=collection_key,
            collection_name=collection_name,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def zotero_sync(
    project: str,
    strict: bool = False,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synchronize a project's linked Zotero collection into References/references_zotero.bib."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.zotero_sync(
            project_name=project,
            strict=strict,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def zotero_unlink(
    project: str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Unlink a Zotero collection from a project."""
    return _exec_tool(
        root,
        auto_root,
        actor_name,
        actor_type,
        lambda core, actor: core.zotero_unlink(
            project_name=project,
            actor=actor,
            dry_run=dry_run,
        ),
    )


@mcp_server.tool()
def apply_manifest(
    manifest: dict[str, Any] | str,
    root: str | None = None,
    auto_root: bool = False,
    actor_name: str = "agent:mcp",
    actor_type: str = "agent",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply a declarative manifest dictionary or JSON file path."""
    def _run(core: SciTreeCore, actor: dict[str, Any]) -> dict[str, Any]:
        if isinstance(manifest, str):
            p = Path(manifest).expanduser()
            if p.exists() and p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                return core.apply_manifest(data, manifest_dir=p.parent, actor=actor, dry_run=dry_run)
            data = json.loads(manifest)
            return core.apply_manifest(data, actor=actor, dry_run=dry_run)
        return core.apply_manifest(manifest, actor=actor, dry_run=dry_run)

    return _exec_tool(root, auto_root, actor_name, actor_type, _run)


def main() -> None:
    mcp_server.run()


if __name__ == "__main__":
    main()
