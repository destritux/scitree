"""FastAPI Local HTTP Server for sciTree (Requirement B & Section I4)."""

from __future__ import annotations

import secrets
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from scitree import SCHEMA_VERSION
from scitree.config import BootstrapStateManager
from scitree.core import SciTreeCore
from scitree.errors import ERR_UNAUTHORIZED, SciTreeError
from scitree.models import validate_actor


class ActorMixin(BaseModel):
    actor_name: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    dry_run: bool = False
    validate_only: bool = False
    root: str | None = None
    auto_root: bool = False


class InitRequest(ActorMixin):
    reset: bool = False


class CreateProjectRequest(ActorMixin):
    name: str
    description: str = ""
    column: str | None = None
    template: str | None = None
    owner_type: str | None = None
    owner_name: str | None = None
    authors: list[dict[str, Any]] | None = None


class UpdateProjectRequest(ActorMixin):
    column: str
    description: str | None = None
    owner_type: str | None = None
    owner_name: str | None = None


class AddVersionRequest(ActorMixin):
    file: str
    author: str
    version_id: str | None = None
    changelog: str = ""
    state: str = "draft"
    derived_from: str | None = None
    submitted_to: str | None = None
    auto_suffix: bool = False


class UpdateVersionStateRequest(ActorMixin):
    state: str | None = None
    changelog: str | None = None
    submitted_to: str | None = None
    archived: bool | None = None


class AddFileRequest(ActorMixin):
    file: str
    kind: str


class AddCommentRequest(ActorMixin):
    text: str
    version: str | None = None
    owner_type: str | None = None
    owner_name: str | None = None
    comment_id: str | None = None


class ResolveCommentRequest(ActorMixin):
    status: str = "resolved"


class AddRiskRequest(ActorMixin):
    id: str | None = None
    risk_id: str | None = None
    title: str
    description: str = ""
    severity: str = "medium"
    likelihood: str = "medium"
    owner: str = ""
    status: str = "open"
    trigger: str = ""
    mitigation: str = ""


class UpdateRiskRequest(ActorMixin):
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    likelihood: str | None = None
    owner: str | None = None
    status: str | None = None
    trigger: str | None = None
    mitigation: str | None = None


class AddMilestoneRequest(ActorMixin):
    id: str | None = None
    milestone_id: str | None = None
    title: str
    description: str = ""
    phase: str = "short_term_7d"
    due_date: str | None = None
    status: str = "pending"


class UpdateMilestoneRequest(ActorMixin):
    title: str | None = None
    description: str | None = None
    phase: str | None = None
    due_date: str | None = None
    status: str | None = None


class TimelineNoteRequest(ActorMixin):
    note: str


class ExportPackageRequest(ActorMixin):
    version: str | None = None
    output_path: str | None = None


class SaveTemplateRequest(ActorMixin):
    project: str
    name: str
    description: str | None = None


class ApplyTemplateRequest(ActorMixin):
    template: str


class ZoteroLinkRequest(ActorMixin):
    collection_key: str
    collection_name: str | None = None


class ZoteroSyncRequest(ActorMixin):
    strict: bool = False


def create_app(
    default_root: str | None = None,
    state_manager: BootstrapStateManager | None = None,
) -> FastAPI:
    api = FastAPI(
        title="sciTree Local HTTP API",
        version=SCHEMA_VERSION,
        description="Loopback REST API mirroring all sciTree CLI, UI, and MCP operations.",
    )
    mgr = state_manager or BootstrapStateManager()

    def _get_core(root: str | None = None, auto_root: bool = False) -> SciTreeCore:
        return SciTreeCore(root_path=root or default_root, auto_root=auto_root, state_manager=mgr)

    def _build_actor(body: ActorMixin | None = None) -> dict[str, Any]:
        if body is None:
            return validate_actor(actor_source="http")
        return validate_actor(
            actor_name=body.actor_name,
            actor_type=body.actor_type,
            actor_source="http",
            actor_id=body.actor_id,
            require_agent_name=(body.actor_type == "agent"),
        )

    @api.middleware("http")
    async def loopback_or_token_guard(request: Request, call_next: Any) -> Any:
        client_host = (request.client.host if request.client else "127.0.0.1") or "127.0.0.1"
        is_loopback = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
        if not is_loopback:
            state = mgr.load()
            expected_token = str(state.get("api_token") or "")
            auth_header = request.headers.get("Authorization", "")
            token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
            if not expected_token or not token or not secrets.compare_digest(token, expected_token):
                err = SciTreeError(
                    ERR_UNAUTHORIZED,
                    "Non-loopback requests require a valid Bearer token from sciTree settings.",
                    {"client_host": client_host},
                )
                return JSONResponse(status_code=err.http_status, content=err.to_dict())
        return await call_next(request)

    @api.exception_handler(SciTreeError)
    async def scitree_error_handler(_: Request, exc: SciTreeError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @api.get("/status")
    def get_status() -> dict[str, Any]:
        return _get_core().get_root_status()

    @api.post("/init")
    def post_init(req: InitRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        dry = req.dry_run or req.validate_only
        if req.reset:
            return core.reset_onboarding(actor=actor, dry_run=dry)
        return core.init_root(root_path=req.root, auto_root=req.auto_root, actor=actor, dry_run=dry)

    @api.post("/projects")
    def post_projects(req: CreateProjectRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.create_project(
            name=req.name,
            description=req.description,
            column=req.column,
            template_name=req.template,
            owner_type=req.owner_type,
            owner_name=req.owner_name,
            authors=req.authors,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects")
    def get_projects(
        root: str | None = None,
        auto_root: bool = False,
        column: str | None = None,
        owner_type: str | None = None,
        has_pending_comments: bool | None = None,
        author: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_projects(
            column=column,
            owner_type=owner_type,
            has_pending_comments=has_pending_comments,
            author=author,
            search=search,
            sort_by=sort_by,
        )

    @api.get("/projects/{name}")
    def get_project_by_name(name: str, root: str | None = None, auto_root: bool = False) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.get_project(name)

    @api.patch("/projects/{name}")
    def patch_project(name: str, req: UpdateProjectRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.move_project(
            name=name,
            column=req.column,
            owner_type=req.owner_type,
            owner_name=req.owner_name,
            description=req.description,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/versions")
    def post_version(name: str, req: AddVersionRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.add_version(
            project_name=name,
            file_path=req.file,
            author=req.author,
            version_id=req.version_id,
            changelog=req.changelog,
            state=req.state,
            derived_from=req.derived_from,
            submitted_to=req.submitted_to,
            auto_suffix=req.auto_suffix,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects/{name}/versions")
    def get_versions(
        name: str,
        include_archived: bool = False,
        root: str | None = None,
        auto_root: bool = False,
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_versions(name, include_archived=include_archived)

    @api.patch("/projects/{name}/versions/{version_id}")
    def patch_version_state(name: str, version_id: str, req: UpdateVersionStateRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.update_version_state(
            project_name=name,
            version_id=version_id,
            state=req.state,
            changelog=req.changelog,
            submitted_to=req.submitted_to,
            archived=req.archived,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/files")
    def post_file(name: str, req: AddFileRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.add_file(
            project_name=name,
            file_path=req.file,
            kind=req.kind,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/comments")
    def post_comment(name: str, req: AddCommentRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.add_comment(
            project_name=name,
            text=req.text,
            version=req.version,
            owner_type=req.owner_type,
            owner_name=req.owner_name,
            comment_id=req.comment_id,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.patch("/projects/{name}/comments/{comment_id}")
    def patch_comment(name: str, comment_id: str, req: ResolveCommentRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        resolved = req.status.lower() == "resolved"
        return core.resolve_comment(
            project_name=name,
            comment_id=comment_id,
            resolved=resolved,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects/{name}/comments")
    def get_comments(
        name: str,
        status: str | None = None,
        owner_type: str | None = None,
        version: str | None = None,
        root: str | None = None,
        auto_root: bool = False,
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_comments(name, status=status, owner_type=owner_type, version=version)

    @api.post("/projects/{name}/risks")
    def post_risk(name: str, req: AddRiskRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.add_risk(
            project_name=name,
            title=req.title,
            description=req.description,
            severity=req.severity,
            likelihood=req.likelihood,
            owner=req.owner,
            status=req.status,
            trigger=req.trigger,
            mitigation=req.mitigation,
            risk_id=req.risk_id or req.id,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects/{name}/risks")
    def get_risks(
        name: str,
        status: str | None = None,
        root: str | None = None,
        auto_root: bool = False,
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_risks(name, status=status)

    @api.patch("/projects/{name}/risks/{risk_id}")
    def patch_risk(name: str, risk_id: str, req: UpdateRiskRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.update_risk(
            project_name=name,
            risk_id=risk_id,
            title=req.title,
            description=req.description,
            severity=req.severity,
            likelihood=req.likelihood,
            owner=req.owner,
            status=req.status,
            trigger=req.trigger,
            mitigation=req.mitigation,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/milestones")
    def post_milestone(name: str, req: AddMilestoneRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.add_milestone(
            project_name=name,
            title=req.title,
            phase=req.phase,
            description=req.description,
            due_date=req.due_date,
            status=req.status,
            milestone_id=req.milestone_id or req.id,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects/{name}/milestones")
    def get_milestones(
        name: str,
        status: str | None = None,
        phase: str | None = None,
        root: str | None = None,
        auto_root: bool = False,
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_milestones(name, status=status, phase=phase)

    @api.patch("/projects/{name}/milestones/{milestone_id}")
    def patch_milestone(name: str, milestone_id: str, req: UpdateMilestoneRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.update_milestone(
            project_name=name,
            milestone_id=milestone_id,
            title=req.title,
            description=req.description,
            phase=req.phase,
            due_date=req.due_date,
            status=req.status,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects/{name}/timeline")
    def get_project_timeline(
        name: str,
        actor_type: str | None = None,
        actor_source: str | None = None,
        event_type: str | None = None,
        root: str | None = None,
        auto_root: bool = False,
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.get_timeline(name, actor_type=actor_type, actor_source=actor_source, event_type=event_type)

    @api.post("/projects/{name}/timeline/notes")
    def post_timeline_note(name: str, req: TimelineNoteRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.add_timeline_note(
            project_name=name,
            note=req.note,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/projects/{name}/activity")
    def get_project_activity(
        name: str,
        actor_type: str | None = None,
        actor_source: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        root: str | None = None,
        auto_root: bool = False,
    ) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_activity(
            name,
            actor_type=actor_type,
            actor_source=actor_source,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
        )

    @api.post("/projects/{name}/export")
    def post_project_export(name: str, req: ExportPackageRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.export_package(
            project_name=name,
            version_id=req.version,
            output_path=req.output_path,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/template")
    def post_project_template(name: str, req: ApplyTemplateRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.apply_template(
            project_name=name,
            template_name=req.template,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/zotero/link")
    def post_zotero_link(name: str, req: ZoteroLinkRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.zotero_link(
            project_name=name,
            collection_key=req.collection_key,
            collection_name=req.collection_name,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/zotero/sync")
    def post_zotero_sync(name: str, req: ZoteroSyncRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.zotero_sync(
            project_name=name,
            strict=req.strict,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/projects/{name}/zotero/unlink")
    def post_zotero_unlink(name: str, req: ActorMixin) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.zotero_unlink(
            project_name=name,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.get("/templates")
    def get_templates(root: str | None = None, auto_root: bool = False) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.list_templates()

    @api.post("/templates")
    def post_template(req: SaveTemplateRequest) -> dict[str, Any]:
        core = _get_core(req.root, req.auto_root)
        actor = _build_actor(req)
        return core.save_template(
            project_name=req.project,
            template_name=req.name,
            description=req.description,
            actor=actor,
            dry_run=req.dry_run or req.validate_only,
        )

    @api.post("/apply")
    def post_apply(manifest: dict[str, Any], root: str | None = None, auto_root: bool = False) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.apply_manifest(manifest)

    @api.post("/inbox/process")
    def post_inbox_process(root: str | None = None, auto_root: bool = False) -> dict[str, Any]:
        core = _get_core(root, auto_root)
        return core.process_inbox_once()

    return api


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Start the sciTree local HTTP API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765).")
    parser.add_argument("--root", default=None, help="Optional explicit root path.")
    args = parser.parse_args()

    api_app = create_app(default_root=args.root)
    uvicorn.run(api_app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
