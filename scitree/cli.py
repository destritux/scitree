"""Command-line interface for sciTree (Requirement A & Section I4).

Provides full parity with the UI, HTTP API, MCP server, and manifest processor.
Every command accepts --root, --auto-root, --json, --dry-run, --actor-name, and --actor-type.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import typer

from scitree import SCHEMA_VERSION
from scitree.core import SciTreeCore
from scitree.errors import EXIT_INTERNAL, EXIT_OK, SciTreeError
from scitree.models import validate_actor

app = typer.Typer(
    name="scitree",
    help="sciTree: Local-first scientific project and manuscript Kanban CLI.",
    add_completion=False,
    no_args_is_help=True,
)

project_app = typer.Typer(help="Create, list, inspect, and move projects.", no_args_is_help=True)
version_app = typer.Typer(help="Add, list, and promote manuscript versions.", no_args_is_help=True)
file_app = typer.Typer(help="Upload data, figure, or manuscript files.", no_args_is_help=True)
comment_app = typer.Typer(help="Add, resolve, and list manuscript comments.", no_args_is_help=True)
risk_app = typer.Typer(help="Add, list, update, and close project risks.", no_args_is_help=True)
milestone_app = typer.Typer(help="Add, list, update, and close project milestones.", no_args_is_help=True)
timeline_app = typer.Typer(help="Inspect project timeline or add timeline notes.", no_args_is_help=True)
timeline_note_app = typer.Typer(help="Manage manual timeline notes.", no_args_is_help=True)
activity_app = typer.Typer(help="Query per-project append-only Activity Log.", no_args_is_help=True)
export_app = typer.Typer(help="Export reproducible submission packages.", no_args_is_help=True)
template_app = typer.Typer(help="List, save, and apply project templates.", no_args_is_help=True)
zotero_app = typer.Typer(help="Link, sync, and unlink Zotero collections.", no_args_is_help=True)
inbox_app = typer.Typer(help="Process manifests from the Automation/inbox watch folder.", no_args_is_help=True)
db_app = typer.Typer(help="Manage and rebuild the SQLite index cache.", no_args_is_help=True)

timeline_app.add_typer(timeline_note_app, name="note")
app.add_typer(project_app, name="project")
app.add_typer(version_app, name="version")
app.add_typer(file_app, name="file")
app.add_typer(comment_app, name="comment")
app.add_typer(risk_app, name="risk")
app.add_typer(milestone_app, name="milestone")
app.add_typer(timeline_app, name="timeline")
app.add_typer(activity_app, name="activity")
app.add_typer(export_app, name="export")
app.add_typer(template_app, name="template")
app.add_typer(zotero_app, name="zotero")
app.add_typer(inbox_app, name="inbox")
app.add_typer(db_app, name="db")


class GlobalOptions:
    root: str | None = None
    auto_root: bool = False
    json_output: bool = False
    dry_run: bool = False
    actor_name: str | None = None
    actor_type: str | None = None


STATE = GlobalOptions()


def _resolve_opts(
    root: str | None,
    auto_root: bool,
    json_out: bool,
    dry_run: bool,
    actor_name: str | None,
    actor_type: str | None,
) -> tuple[SciTreeCore, dict[str, Any], bool, bool]:
    eff_root = root or STATE.root
    eff_auto = auto_root or STATE.auto_root
    eff_json = json_out or STATE.json_output
    eff_dry = dry_run or STATE.dry_run
    eff_actor_name = actor_name if actor_name is not None else STATE.actor_name
    eff_actor_type = actor_type if actor_type is not None else STATE.actor_type

    core = SciTreeCore(root_path=eff_root, auto_root=eff_auto)
    actor = validate_actor(
        actor_name=eff_actor_name,
        actor_type=eff_actor_type,
        actor_source="cli",
        require_agent_name=(eff_actor_type == "agent"),
    )
    return core, actor, eff_json, eff_dry


def _emit(payload: dict[str, Any], as_json: bool, summary_fn: Callable[[dict[str, Any]], str] | None = None) -> None:
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
    else:
        if summary_fn:
            typer.echo(summary_fn(payload))
        else:
            typer.echo(json.dumps(payload, indent=2))


def _handle_call(
    as_json: bool,
    fn: Callable[[], dict[str, Any]],
    summary_fn: Callable[[dict[str, Any]], str] | None = None,
) -> None:
    try:
        res = fn()
        _emit(res, as_json=as_json, summary_fn=summary_fn)
    except SciTreeError as exc:
        if as_json:
            typer.echo(json.dumps(exc.to_dict(), indent=2))
        else:
            typer.echo(f"Error [{exc.code}]: {exc.message}", err=True)
            if exc.details:
                typer.echo(f"Details: {json.dumps(exc.details)}", err=True)
        raise typer.Exit(code=exc.exit_code)
    except Exception as exc:
        err_dict = {
            "schema_version": SCHEMA_VERSION,
            "error": "INTERNAL_ERROR",
            "message": str(exc),
            "details": {},
        }
        if as_json:
            typer.echo(json.dumps(err_dict, indent=2))
        else:
            typer.echo(f"Internal Error: {exc}", err=True)
        raise typer.Exit(code=EXIT_INTERNAL)


@app.callback()
def main_callback(
    root: Optional[str] = typer.Option(None, "--root", help="Explicit sciTree root folder path."),
    auto_root: bool = typer.Option(False, "--auto-root", help="Automatically initialize/use OS default root path."),
    json_output: bool = typer.Option(False, "--json", help="Emit structured JSON output."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without modifying disk or database."),
    actor_name: Optional[str] = typer.Option(None, "--actor-name", help="Actor name for attribution."),
    actor_type: Optional[str] = typer.Option(None, "--actor-type", help="Actor type: human or agent."),
) -> None:
    STATE.root = root
    STATE.auto_root = auto_root
    STATE.json_output = json_output
    STATE.dry_run = dry_run
    STATE.actor_name = actor_name
    STATE.actor_type = actor_type


# ------------------------------------------------------------------
# init & apply
# ------------------------------------------------------------------
@app.command("init")
def cmd_init(
    root: Optional[str] = typer.Option(None, "--root", help="Root folder path."),
    auto_root: bool = typer.Option(False, "--auto-root", help="Use OS recommended default root path."),
    reset: bool = typer.Option(False, "--reset", help="Reset onboarding state."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON output."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate only."),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    """Initialize or reset the sciTree root directory."""
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    if reset:
        _handle_call(
            eff_json,
            lambda: core.reset_onboarding(actor=actor, dry_run=eff_dry),
            lambda r: "Onboarding state reset.",
        )
    else:
        _handle_call(
            eff_json,
            lambda: core.init_root(
                root_path=root or STATE.root,
                auto_root=auto_root or STATE.auto_root,
                actor=actor,
                dry_run=eff_dry,
            ),
            lambda r: f"Initialized sciTree root at: {r['root_path']}",
        )


@app.command("apply")
def cmd_apply(
    manifest: str = typer.Option(..., "--manifest", help="Path to declarative JSON manifest file."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    """Apply a declarative JSON manifest transactionally."""
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)

    def _run() -> dict[str, Any]:
        mpath = Path(manifest).expanduser().resolve()
        if not mpath.exists():
            from scitree.errors import ERR_FILE_NOT_FOUND

            raise SciTreeError(ERR_FILE_NOT_FOUND, f"Manifest file not found: '{manifest}'.", {"manifest": manifest})
        data = json.loads(mpath.read_text(encoding="utf-8"))
        explicit_actor = actor if (actor_name or STATE.actor_name) else None
        return core.apply_manifest(data, manifest_dir=mpath.parent, actor=explicit_actor, dry_run=eff_dry)

    _handle_call(
        eff_json,
        _run,
        lambda r: (
            f"Manifest applied for '{r['project']}': "
            f"created={r['summary']['created_count']}, "
            f"skipped={r['summary']['skipped_count']}, "
            f"failed={r['summary']['failed_count']}"
        ),
    )


# ------------------------------------------------------------------
# project subcommands
# ------------------------------------------------------------------
@project_app.command("create")
def cmd_project_create(
    name: str = typer.Option(..., "--name", help="Project name."),
    description: str = typer.Option("", "--description", help="Project description."),
    column: Optional[str] = typer.Option(None, "--column", help="Initial Kanban column."),
    template: Optional[str] = typer.Option(None, "--template", help="Template name."),
    owner_type: Optional[str] = typer.Option(None, "--owner-type", help="Owner type: human or agent."),
    owner_name: Optional[str] = typer.Option(None, "--owner-name", help="Owner name."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.create_project(
            name=name,
            description=description,
            column=column,
            template_name=template,
            owner_type=owner_type,
            owner_name=owner_name,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Project '{r['project']['name']}' ({'created' if r.get('created') else 'existing'}) in column '{r['project']['status']['column']}'.",
    )


@project_app.command("list")
def cmd_project_list(
    column: Optional[str] = typer.Option(None, "--column", help="Filter by Kanban column."),
    owner_type: Optional[str] = typer.Option(None, "--owner-type", help="Filter by owner_type (human|agent|all)."),
    has_pending_comments: Optional[bool] = typer.Option(None, "--has-pending-comments", help="Filter by pending comments."),
    author: Optional[str] = typer.Option(None, "--author", help="Filter by author."),
    search: Optional[str] = typer.Option(None, "--search", help="Search query."),
    sort_by: str = typer.Option("updated_at", "--sort-by", help="Sort field: updated_at, name, column."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_projects(
            column=column,
            owner_type=owner_type,
            has_pending_comments=has_pending_comments,
            author=author,
            search=search,
            sort_by=sort_by,
        ),
        lambda r: "\n".join(
            [f"Projects ({r['count']}):"]
            + [
                f"  - {p['name']} [{p['status']['column']}] latest={p.get('latest_version_id') or 'none'}"
                f"{' [LOCKED]' if p.get('latest_version_locked') else ''} "
                f"pending_comments={p.get('comments_summary', {}).get('pending', 0)}"
                for p in r["projects"]
            ]
        ),
    )


@project_app.command("show")
def cmd_project_show(
    name: str = typer.Option(..., "--name", help="Project name."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.get_project(name=name),
        lambda r: (
            f"Project: {r['project']['name']} ({r['project']['project_id']})\n"
            f"Column: {r['project']['status']['column']}\n"
            f"Latest Version: {r['project'].get('latest_version_id') or 'none'} "
            f"(locked={r['project'].get('latest_version_locked')})\n"
            f"Comments: {r['project']['comments_summary']}\n"
            f"Risks: {r['project']['risks_summary']}\n"
            f"Milestones: {r['project']['milestones_summary']}"
        ),
    )


@project_app.command("move")
def cmd_project_move(
    name: str = typer.Option(..., "--name", help="Project name."),
    column: str = typer.Option(..., "--column", help="Target Kanban column."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.move_project(name=name, column=column, actor=actor, dry_run=eff_dry),
        lambda r: f"Moved '{r['project']['name']}' from '{r['previous_column']}' to '{r['column']}'.",
    )


# ------------------------------------------------------------------
# version subcommands
# ------------------------------------------------------------------
@version_app.command("add")
def cmd_version_add(
    project: str = typer.Option(..., "--project", help="Project name."),
    file: str = typer.Option(..., "--file", help="Path to DOCX or PDF manuscript."),
    author: str = typer.Option(..., "--author", help="Author who submitted this version."),
    version_id: Optional[str] = typer.Option(None, "--version-id", help="Explicit version identifier, e.g. v1."),
    changelog: str = typer.Option("", "--changelog", help="Optional changelog note."),
    state: str = typer.Option("draft", "--state", help="Version state: draft|submitted|published|revision."),
    derived_from: Optional[str] = typer.Option(None, "--derived-from", help="Parent version_id if derived."),
    submitted_to: Optional[str] = typer.Option(None, "--submitted-to", help="Target journal or venue."),
    auto_suffix: bool = typer.Option(False, "--auto-suffix", help="Auto-apply suffix like v2a on version conflict."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.add_version(
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
            dry_run=eff_dry,
        ),
        lambda r: (
            f"Version '{r['version']['version_id']}' ({r['version']['state']}) "
            f"{'added' if r.get('created') else 'already up-to-date (idempotent)'} for project '{project}'."
        ),
    )


@version_app.command("list")
def cmd_version_list(
    project: str = typer.Option(..., "--project", help="Project name."),
    include_archived: bool = typer.Option(False, "--include-archived", help="Include archived versions."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_versions(project_name=project, include_archived=include_archived),
        lambda r: "\n".join(
            [f"Versions for '{r['project']}' (latest={r['latest_version_id']}):"]
            + [
                f"  - {v['version_id']} [{v['state']}]{' [LOCKED]' if v.get('immutable') else ''} "
                f"by {v['author']} ({v['created_at']})"
                for v in r["versions"]
            ]
        ),
    )


@version_app.command("state")
def cmd_version_state(
    project: str = typer.Option(..., "--project", help="Project name."),
    version_id: str = typer.Option(..., "--version-id", "--version", help="Version ID to update."),
    state: Optional[str] = typer.Option(None, "--state", help="New state: draft|submitted|published|revision."),
    submitted_to: Optional[str] = typer.Option(None, "--submitted-to", "--to", help="Target journal."),
    archive: Optional[bool] = typer.Option(None, "--archive/--unarchive", help="Archive or unarchive version."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.update_version_state(
            project_name=project,
            version_id=version_id,
            state=state,
            submitted_to=submitted_to,
            archived=archive,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Version '{r['version']['version_id']}' updated: state={r['version']['state']}, immutable={r['version'].get('immutable')}.",
    )


@version_app.command("submit")
def cmd_version_submit(
    project: str = typer.Option(..., "--project", help="Project name."),
    version_id: str = typer.Option(..., "--version-id", "--version", help="Version ID to mark submitted."),
    submitted_to: Optional[str] = typer.Option(None, "--to", "--submitted-to", help="Target journal or venue."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    """Promote a manuscript version to 'submitted' and lock it as immutable."""
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.update_version_state(
            project_name=project,
            version_id=version_id,
            state="submitted",
            submitted_to=submitted_to,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Version '{r['version']['version_id']}' submitted and locked (immutable=True).",
    )


# ------------------------------------------------------------------
# file subcommands
# ------------------------------------------------------------------
@file_app.command("add")
def cmd_file_add(
    project: str = typer.Option(..., "--project", help="Project name."),
    file: str = typer.Option(..., "--file", help="Path to file."),
    kind: str = typer.Option(..., "--kind", help="File kind: data|figure|manuscript."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.add_file(
            project_name=project,
            file_path=file,
            kind=kind,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"File '{r['file']['path']}' ({r['file']['kind']}) added to '{project}'.",
    )


# ------------------------------------------------------------------
# comment subcommands
# ------------------------------------------------------------------
@comment_app.command("add")
def cmd_comment_add(
    project: str = typer.Option(..., "--project", help="Project name."),
    text: str = typer.Option(..., "--text", help="Comment text."),
    version: Optional[str] = typer.Option(None, "--version", help="Associated version ID."),
    owner_type: Optional[str] = typer.Option(None, "--owner-type", help="human or agent."),
    owner_name: Optional[str] = typer.Option(None, "--owner-name", help="Owner name."),
    comment_id: Optional[str] = typer.Option(None, "--id", help="Optional explicit comment ID."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.add_comment(
            project_name=project,
            text=text,
            version=version,
            owner_type=owner_type,
            owner_name=owner_name,
            comment_id=comment_id,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Comment '{r['comment']['comment_id']}' on '{project}' ({r['comment']['status']}).",
    )


@comment_app.command("resolve")
def cmd_comment_resolve(
    project: str = typer.Option(..., "--project", help="Project name."),
    comment_id: str = typer.Option(..., "--comment-id", help="Comment ID to resolve."),
    reopen: bool = typer.Option(False, "--reopen", help="Reopen instead of resolving."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.resolve_comment(
            project_name=project,
            comment_id=comment_id,
            resolved=not reopen,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Comment '{r['comment']['comment_id']}' marked as {r['comment']['status']}.",
    )


@comment_app.command("list")
def cmd_comment_list(
    project: str = typer.Option(..., "--project", help="Project name."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter: pending|resolved."),
    owner_type: Optional[str] = typer.Option(None, "--owner-type", help="Filter: human|agent."),
    version: Optional[str] = typer.Option(None, "--version", help="Filter by version ID."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_comments(
            project_name=project,
            status=status,
            owner_type=owner_type,
            version=version,
        ),
        lambda r: "\n".join(
            [f"Comments for '{r['project']}' ({r['count']}):"]
            + [
                f"  - [{c['status'].upper()}] {c['comment_id']} ({c.get('version') or 'general'}, {c['owner_type']}:{c['owner_name']}): {c['text']}"
                for c in r["comments"]
            ]
        ),
    )


# ------------------------------------------------------------------
# risk subcommands (Section B1 & B4)
# ------------------------------------------------------------------
@risk_app.command("add")
def cmd_risk_add(
    project: str = typer.Option(..., "--project", help="Project name."),
    title: str = typer.Option(..., "--title", help="Risk title."),
    description: str = typer.Option("", "--description", help="Risk description."),
    severity: str = typer.Option("medium", "--severity", help="low|medium|high|critical."),
    likelihood: str = typer.Option("medium", "--likelihood", help="low|medium|high."),
    owner: str = typer.Option("", "--owner", help="Risk owner."),
    status: str = typer.Option("open", "--status", help="open|mitigating|closed."),
    trigger: str = typer.Option("", "--trigger", help="Optional risk trigger."),
    mitigation: str = typer.Option("", "--mitigation", help="Optional mitigation plan."),
    risk_id: Optional[str] = typer.Option(None, "--id", help="Explicit risk ID for idempotency."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.add_risk(
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
            dry_run=eff_dry,
        ),
        lambda r: f"Risk '{r['risk']['risk_id']}' ({r['risk']['severity']}) on '{project}'.",
    )


@risk_app.command("list")
def cmd_risk_list(
    project: str = typer.Option(..., "--project", help="Project name."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter: open|mitigating|closed."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_risks(project_name=project, status=status),
        lambda r: "\n".join(
            [f"Risks for '{r['project']}' ({r['count']}):"]
            + [
                f"  - {rk['risk_id']} [{rk['status']}] severity={rk['severity']} likelihood={rk['likelihood']}: {rk['title']}"
                for rk in r["risks"]
            ]
        ),
    )


@risk_app.command("update")
def cmd_risk_update(
    project: str = typer.Option(..., "--project", help="Project name."),
    risk_id: str = typer.Option(..., "--id", help="Risk ID."),
    title: Optional[str] = typer.Option(None, "--title"),
    description: Optional[str] = typer.Option(None, "--description"),
    severity: Optional[str] = typer.Option(None, "--severity"),
    likelihood: Optional[str] = typer.Option(None, "--likelihood"),
    owner: Optional[str] = typer.Option(None, "--owner"),
    status: Optional[str] = typer.Option(None, "--status"),
    trigger: Optional[str] = typer.Option(None, "--trigger"),
    mitigation: Optional[str] = typer.Option(None, "--mitigation"),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.update_risk(
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
            dry_run=eff_dry,
        ),
        lambda r: f"Risk '{r['risk']['risk_id']}' updated (status={r['risk']['status']}).",
    )


@risk_app.command("close")
def cmd_risk_close(
    project: str = typer.Option(..., "--project", help="Project name."),
    risk_id: str = typer.Option(..., "--id", help="Risk ID to close."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.close_risk(project_name=project, risk_id=risk_id, actor=actor, dry_run=eff_dry),
        lambda r: f"Risk '{r['risk']['risk_id']}' closed.",
    )


# ------------------------------------------------------------------
# milestone subcommands (Section B2 & B4)
# ------------------------------------------------------------------
@milestone_app.command("add")
def cmd_milestone_add(
    project: str = typer.Option(..., "--project", help="Project name."),
    title: str = typer.Option(..., "--title", help="Milestone title."),
    phase: str = typer.Option("short_term_7d", "--phase", help="short_term_7d|medium_term_30d|submission_ready|revision_ready|custom."),
    description: str = typer.Option("", "--description", help="Milestone description."),
    due_date: Optional[str] = typer.Option(None, "--due-date", "--due", help="Optional due date YYYY-MM-DD."),
    status: str = typer.Option("pending", "--status", help="pending|in_progress|done|missed."),
    milestone_id: Optional[str] = typer.Option(None, "--id", help="Explicit milestone ID."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.add_milestone(
            project_name=project,
            title=title,
            phase=phase,
            description=description,
            due_date=due_date,
            status=status,
            milestone_id=milestone_id,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Milestone '{r['milestone']['milestone_id']}' ({r['milestone']['phase']}) added to '{project}'.",
    )


@milestone_app.command("list")
def cmd_milestone_list(
    project: str = typer.Option(..., "--project", help="Project name."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status."),
    phase: Optional[str] = typer.Option(None, "--phase", help="Filter by phase."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_milestones(project_name=project, status=status, phase=phase),
        lambda r: "\n".join(
            [f"Milestones for '{r['project']}' ({r['count']}):"]
            + [
                f"  - {m['milestone_id']} [{m['status']}] ({m['phase']}, due={m.get('due_date') or 'none'}): {m['title']}"
                for m in r["milestones"]
            ]
        ),
    )


@milestone_app.command("update")
def cmd_milestone_update(
    project: str = typer.Option(..., "--project", help="Project name."),
    milestone_id: str = typer.Option(..., "--id", help="Milestone ID."),
    title: Optional[str] = typer.Option(None, "--title"),
    description: Optional[str] = typer.Option(None, "--description"),
    phase: Optional[str] = typer.Option(None, "--phase"),
    due_date: Optional[str] = typer.Option(None, "--due-date"),
    status: Optional[str] = typer.Option(None, "--status"),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.update_milestone(
            project_name=project,
            milestone_id=milestone_id,
            title=title,
            description=description,
            phase=phase,
            due_date=due_date,
            status=status,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Milestone '{r['milestone']['milestone_id']}' updated (status={r['milestone']['status']}).",
    )


@milestone_app.command("close")
def cmd_milestone_close(
    project: str = typer.Option(..., "--project", help="Project name."),
    milestone_id: str = typer.Option(..., "--id", help="Milestone ID to mark done."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.close_milestone(project_name=project, milestone_id=milestone_id, actor=actor, dry_run=eff_dry),
        lambda r: f"Milestone '{r['milestone']['milestone_id']}' marked done.",
    )


# ------------------------------------------------------------------
# timeline & activity subcommands (Sections C & E)
# ------------------------------------------------------------------
@timeline_app.command("show")
def cmd_timeline_show(
    project: str = typer.Option(..., "--project", help="Project name."),
    actor_type: Optional[str] = typer.Option(None, "--actor-type-filter"),
    actor_source: Optional[str] = typer.Option(None, "--actor-source"),
    event_type: Optional[str] = typer.Option(None, "--event-type"),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type_attr: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type_attr)
    _handle_call(
        eff_json,
        lambda: core.get_timeline(
            project_name=project,
            actor_type=actor_type,
            actor_source=actor_source,
            event_type=event_type,
        ),
        lambda r: "\n".join(
            [f"Timeline for '{r['project']}' ({r['total_events']} events):"]
            + [
                f"  [{ev['timestamp']}] {ev['event_type']} by {ev['actor']['actor_name']} ({ev['actor']['actor_source']})"
                for ev in r["events"]
            ]
        ),
    )


@timeline_note_app.command("add")
def cmd_timeline_note_add(
    project: str = typer.Option(..., "--project", help="Project name."),
    note: str = typer.Option(..., "--note", help="Manual note text."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.add_timeline_note(project_name=project, note=note, actor=actor, dry_run=eff_dry),
        lambda r: f"Timeline note added to '{project}'.",
    )


@activity_app.command("list")
def cmd_activity_list(
    project: str = typer.Option(..., "--project", help="Project name."),
    filter_actor_type: Optional[str] = typer.Option(None, "--filter-actor-type", help="human or agent."),
    filter_actor_source: Optional[str] = typer.Option(None, "--filter-actor-source", help="ui|cli|http|mcp|manifest."),
    event_type: Optional[str] = typer.Option(None, "--event-type", help="Event type filter."),
    date_from: Optional[str] = typer.Option(None, "--date-from", help="Start date YYYY-MM-DD."),
    date_to: Optional[str] = typer.Option(None, "--date-to", help="End date YYYY-MM-DD."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_activity(
            project_name=project,
            actor_type=filter_actor_type,
            actor_source=filter_actor_source,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
        ),
        lambda r: f"Activity events for '{r['project']}': {r['count']}",
    )


# ------------------------------------------------------------------
# export, template, zotero, inbox, db subcommands
# ------------------------------------------------------------------
@export_app.command("package")
def cmd_export_package(
    project: str = typer.Option(..., "--project", help="Project name."),
    version: Optional[str] = typer.Option(None, "--version", help="Version ID (defaults to latest)."),
    output: Optional[str] = typer.Option(None, "--output", help="Custom output zip file path."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.export_package(
            project_name=project,
            version_id=version,
            output_path=output,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: (
            f"Exported submission package for '{project}' ({r.get('version') or r.get('export', {}).get('version')}): "
            f"{r.get('export', {}).get('path', 'dry-run')}"
        ),
    )


@template_app.command("list")
def cmd_template_list(
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.list_templates(),
        lambda r: "\n".join(
            [f"Templates ({r['count']}):"]
            + [f"  - {t['name']}: {' -> '.join(t.get('columns', []))}" for t in r["templates"]]
        ),
    )


@template_app.command("save")
def cmd_template_save(
    project: str = typer.Option(..., "--project", help="Source project name."),
    name: str = typer.Option(..., "--name", help="New template name."),
    description: Optional[str] = typer.Option(None, "--description", help="Template description."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.save_template(
            project_name=project,
            template_name=name,
            description=description,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Saved custom template '{name}' from project '{project}'.",
    )


@template_app.command("apply")
def cmd_template_apply(
    project: str = typer.Option(..., "--project", help="Target project name."),
    template: str = typer.Option(..., "--template", help="Template name to apply."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.apply_template(
            project_name=project,
            template_name=template,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Applied template '{template}' to '{project}'.",
    )


@zotero_app.command("link")
def cmd_zotero_link(
    project: str = typer.Option(..., "--project", help="Project name."),
    collection_key: str = typer.Option(..., "--collection-key", "--collection", help="Zotero collection key."),
    collection_name: Optional[str] = typer.Option(None, "--collection-name", help="Collection display name."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.zotero_link(
            project_name=project,
            collection_key=collection_key,
            collection_name=collection_name,
            actor=actor,
            dry_run=eff_dry,
        ),
        lambda r: f"Linked Zotero collection '{collection_key}' to '{project}'.",
    )


@zotero_app.command("sync")
def cmd_zotero_sync(
    project: str = typer.Option(..., "--project", help="Project name."),
    strict: bool = typer.Option(False, "--strict", help="Fail with ZOTERO_UNAVAILABLE if Zotero is unreachable."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.zotero_sync(project_name=project, strict=strict, actor=actor, dry_run=eff_dry),
        lambda r: f"Zotero sync for '{project}': status={r.get('status')}, changed={r.get('changed')}.",
    )


@zotero_app.command("unlink")
def cmd_zotero_unlink(
    project: str = typer.Option(..., "--project", help="Project name."),
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, eff_dry = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.zotero_unlink(project_name=project, actor=actor, dry_run=eff_dry),
        lambda r: f"Unlinked Zotero collection from '{project}'.",
    )


@inbox_app.command("process")
def cmd_inbox_process(
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, _, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)
    _handle_call(
        eff_json,
        lambda: core.process_inbox_once(),
        lambda r: f"Processed {r['processed_count']} manifest(s) from Automation/inbox.",
    )


@db_app.command("rebuild")
def cmd_db_rebuild(
    root: Optional[str] = typer.Option(None, "--root"),
    auto_root: bool = typer.Option(False, "--auto-root"),
    json_out: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    actor_name: Optional[str] = typer.Option(None, "--actor-name"),
    actor_type: Optional[str] = typer.Option(None, "--actor-type"),
) -> None:
    core, actor, eff_json, _ = _resolve_opts(root, auto_root, json_out, dry_run, actor_name, actor_type)

    def _run() -> dict[str, Any]:
        rpath = core.resolve_root()
        stats = core._get_db(rpath).rebuild_from_filesystem(rpath)
        return {"schema_version": SCHEMA_VERSION, "actor": actor, "rebuilt": True, **stats}

    _handle_call(
        eff_json,
        _run,
        lambda r: f"Rebuilt SQLite index: {r['projects_indexed']} projects, {r['templates_indexed']} templates.",
    )


@app.command("serve")
def cmd_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host (default: 127.0.0.1)."),
    port: int = typer.Option(8765, "--port", help="Bind port (default: 8765)."),
    root: Optional[str] = typer.Option(None, "--root", help="Optional explicit root path."),
) -> None:
    """Start the local HTTP REST API server."""
    import uvicorn
    from scitree.api.server import create_app

    api_app = create_app(default_root=root or STATE.root)
    uvicorn.run(api_app, host=host, port=port)


@app.command("mcp")
def cmd_mcp() -> None:
    """Start the Model Context Protocol (MCP) server."""
    from scitree.mcp_server import main as run_mcp

    run_mcp()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
