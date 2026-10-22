"""Shared internal core for sciTree (Requirement E & Sections A-I).

All user-facing and automated surfaces (UI, CLI, HTTP API, MCP server, and
manifest processor) call SciTreeCore so business rules, validation, folder
organization, extraction, SQLite indexing, and activity logging live in one place.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from scitree import SCHEMA_VERSION
from scitree.config import BootstrapStateManager, get_recommended_root_path
from scitree.db import SciTreeDatabase
from scitree.errors import (
    ERR_COMMENT_NOT_FOUND,
    ERR_FILE_NOT_FOUND,
    ERR_MILESTONE_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_RISK_NOT_FOUND,
    ERR_ROOT_NOT_CONFIGURED,
    ERR_VALIDATION_ERROR,
    ERR_VERSION_CONFLICT,
    ERR_VERSION_IMMUTABLE,
    ERR_VERSION_NOT_FOUND,
    SciTreeError,
)
from scitree.exporter import build_submission_package
from scitree.extraction import extract_manuscript_artifacts
from scitree.models import (
    MILESTONE_PHASE_ORDER,
    VALID_COMMENT_STATUSES,
    VALID_FILE_KINDS,
    VALID_MILESTONE_PHASES,
    VALID_MILESTONE_STATUSES,
    VALID_RISK_LIKELIHOODS,
    VALID_RISK_SEVERITIES,
    VALID_RISK_STATUSES,
    VALID_VERSION_STATES,
    compute_sha256,
    make_id,
    safe_folder_name,
    slugify,
    utc_now_iso,
    validate_actor,
    wrap_response,
)
from scitree.templates import (
    DEFAULT_COLUMNS,
    ensure_builtin_templates_on_disk,
    list_all_templates,
    load_template_by_name,
    save_template_from_project,
)
from scitree.zotero import sync_zotero_collection

EVENT_COLOR_CATEGORY: dict[str, str] = {
    "project.created": "blue",
    "project.updated": "blue",
    "project.column_changed": "indigo",
    "project.template_applied": "blue",
    "version.added": "teal",
    "version.submitted": "green",
    "version.locked": "amber",
    "version.published": "green",
    "version.derived": "teal",
    "version.archived": "grey",
    "file.added": "cyan",
    "file.removed": "grey",
    "comment.added": "orange",
    "comment.resolved": "green",
    "comment.reopened": "orange",
    "risk.added": "red",
    "risk.updated": "amber",
    "risk.closed": "green",
    "milestone.added": "purple",
    "milestone.updated": "purple",
    "milestone.completed": "green",
    "milestone.missed": "red",
    "zotero.linked": "blue",
    "zotero.unlinked": "grey",
    "zotero.synced": "teal",
    "export.created": "indigo",
    "note.added": "slate",
}


class SciTreeCore:
    """Single source of business logic for sciTree."""

    def __init__(
        self,
        root_path: str | Path | None = None,
        auto_root: bool = False,
        state_manager: BootstrapStateManager | None = None,
    ) -> None:
        self.state_manager = state_manager or BootstrapStateManager()
        self._explicit_root = Path(root_path).expanduser().resolve() if root_path else None
        self._auto_root = auto_root
        self._db: SciTreeDatabase | None = None

    # ------------------------------------------------------------------
    # Root setup and resolution
    # ------------------------------------------------------------------
    def get_root_status(self) -> dict[str, Any]:
        state = self.state_manager.load()
        effective = self._explicit_root or (
            Path(state["root_path"]).expanduser().resolve() if state.get("root_path") else None
        )
        return wrap_response(
            {
                "onboarding_completed": bool(state.get("onboarding_completed", False)),
                "root_path": str(effective) if effective else None,
                "recommended_root": str(get_recommended_root_path()),
                "api_token": state.get("api_token"),
                "ui_state": state.get("ui_state", {"last_view": "board"}),
            }
        )

    def init_root(
        self,
        root_path: str | Path | None = None,
        auto_root: bool = False,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Initialize the sciTree root folder and minimal bootstrap state."""
        actor_info = actor or validate_actor(actor_source="cli")
        if root_path:
            target = Path(root_path).expanduser().resolve()
            mode = "explicit"
        elif auto_root:
            target = get_recommended_root_path().resolve()
            mode = "auto"
        else:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                "Either root_path (--root) or auto_root (--auto-root) must be specified for init.",
            )

        required_subdirs = [
            "Projects",
            "Templates",
            "Automation",
            "Automation/inbox",
            "Automation/inbox/processed",
            "Automation/outbox",
            "Automation/logs",
            "Exports",
        ]

        if dry_run:
            return wrap_response(
                {
                    "dry_run": True,
                    "initialized": False,
                    "mode": mode,
                    "root_path": str(target),
                    "directories_to_create": [str(target / d) for d in required_subdirs],
                },
                actor=actor_info,
            )

        target.mkdir(parents=True, exist_ok=True)
        for sub in required_subdirs:
            (target / sub).mkdir(parents=True, exist_ok=True)

        ensure_builtin_templates_on_disk(target / "Templates")
        self._explicit_root = target
        self.state_manager.save(onboarding_completed=True, root_path=target)

        db = SciTreeDatabase(target / "scitree.db")
        db.set_setting("root_path", str(target))
        db.set_setting("initialized_at", utc_now_iso())
        rebuild_stats = db.rebuild_from_filesystem(target)
        self._db = db

        self._write_automation_log(
            target,
            actor_info,
            "init_root",
            {"mode": mode, "root_path": str(target), "rebuild": rebuild_stats},
        )
        return wrap_response(
            {
                "initialized": True,
                "mode": mode,
                "root_path": str(target),
                "recommended_root": str(get_recommended_root_path()),
                "index": rebuild_stats,
                "notice": f"sciTree workspace initialized at {target}",
            },
            actor=actor_info,
        )

    def reset_onboarding(
        self,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        if dry_run:
            return wrap_response({"dry_run": True, "reset": True}, actor=actor_info)
        state = self.state_manager.reset()
        self._explicit_root = None
        self._db = None
        return wrap_response(
            {
                "reset": True,
                "onboarding_completed": state["onboarding_completed"],
                "root_path": state["root_path"],
            },
            actor=actor_info,
        )

    def resolve_root(self, create_if_auto: bool = True) -> Path:
        """Resolve the active root directory or fail with ROOT_NOT_CONFIGURED."""
        if self._explicit_root:
            root = self._explicit_root
            if not root.exists():
                root.mkdir(parents=True, exist_ok=True)
            self._ensure_root_layout(root)
            return root

        state = self.state_manager.load()
        if state.get("root_path"):
            root = Path(state["root_path"]).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            self._ensure_root_layout(root)
            return root

        if self._auto_root and create_if_auto:
            res = self.init_root(auto_root=True)
            return Path(res["root_path"])

        raise SciTreeError(
            ERR_ROOT_NOT_CONFIGURED,
            "No sciTree root folder is configured. Run 'scitree init --root <path>' or pass --root / --auto-root.",
            {"recommended_root": str(get_recommended_root_path())},
        )

    def _ensure_root_layout(self, root: Path) -> None:
        for sub in [
            "Projects",
            "Templates",
            "Automation",
            "Automation/inbox",
            "Automation/inbox/processed",
            "Automation/outbox",
            "Automation/logs",
            "Exports",
        ]:
            (root / sub).mkdir(parents=True, exist_ok=True)
        ensure_builtin_templates_on_disk(root / "Templates")

    def _get_db(self, root: Path) -> SciTreeDatabase:
        if self._db is None or self._db.db_path != (root / "scitree.db"):
            self._db = SciTreeDatabase(root / "scitree.db")
        return self._db

    # ------------------------------------------------------------------
    # Automation & Activity Logging
    # ------------------------------------------------------------------
    def _write_automation_log(
        self,
        root: Path,
        actor: dict[str, Any],
        operation: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        logs_dir = root / "Automation" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "schema_version": SCHEMA_VERSION,
            "timestamp": utc_now_iso(),
            "actor": actor,
            "operation": operation,
            "result": result,
        }
        log_file = logs_dir / "operations.jsonl"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry

    def get_recent_automation_logs(self, limit: int = 25) -> dict[str, Any]:
        root = self.resolve_root()
        log_file = root / "Automation" / "logs" / "operations.jsonl"
        entries: list[dict[str, Any]] = []
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                    if len(entries) >= limit:
                        break
                except json.JSONDecodeError:
                    continue

        outbox_dir = root / "Automation" / "outbox"
        last_manifest: dict[str, Any] | None = None
        if outbox_dir.exists():
            result_files = sorted(outbox_dir.glob("*.result.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if result_files:
                try:
                    last_manifest = json.loads(result_files[0].read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    last_manifest = None

        return wrap_response(
            {
                "root_path": str(root),
                "logs": entries,
                "last_manifest_result": last_manifest,
            }
        )

    def _append_project_event(
        self,
        root: Path,
        project_dir: Path,
        metadata: dict[str, Any],
        actor: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now_iso()
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": make_id("evt"),
            "project_id": metadata["project_id"],
            "project_name": metadata["name"],
            "timestamp": now,
            "actor": actor,
            "event_type": event_type,
            "color": EVENT_COLOR_CATEGORY.get(event_type, "slate"),
            "payload": payload,
        }
        log_path = project_dir / "activity_log.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

        # Update activity_summary inside metadata
        summary = metadata.setdefault(
            "activity_summary",
            {
                "total_events": 0,
                "last_event_at": now,
                "actors": {"human": 0, "agent": 0},
                "sources": {"ui": 0, "cli": 0, "http": 0, "mcp": 0, "manifest": 0},
            },
        )
        summary["total_events"] = int(summary.get("total_events", 0)) + 1
        summary["last_event_at"] = now
        atype = actor.get("actor_type", "human")
        asrc = actor.get("actor_source", "cli")
        summary.setdefault("actors", {"human": 0, "agent": 0})
        summary["actors"][atype] = int(summary["actors"].get(atype, 0)) + 1
        summary.setdefault("sources", {"ui": 0, "cli": 0, "http": 0, "mcp": 0, "manifest": 0})
        summary["sources"][asrc] = int(summary["sources"].get(asrc, 0)) + 1
        metadata["updated_at"] = now

        self._get_db(root).append_activity_event(metadata["project_id"], metadata["name"], event)
        return event

    # ------------------------------------------------------------------
    # Project directory helpers
    # ------------------------------------------------------------------
    def _iter_project_dirs(self, root: Path) -> list[Path]:
        dirs: list[Path] = []
        projects_container = root / "Projects"
        if projects_container.exists():
            for d in sorted(projects_container.iterdir()):
                if d.is_dir() and (d / "metadata.json").exists():
                    dirs.append(d)
        # Also support projects placed directly under <root>/<ProjectName>
        reserved = {"Projects", "Templates", "Automation", "Exports"}
        for d in sorted(root.iterdir()):
            if d.is_dir() and d.name not in reserved and (d / "metadata.json").exists():
                dirs.append(d)
        return dirs

    def _find_project(self, root: Path, name_or_slug: str) -> tuple[Path, dict[str, Any]]:
        target = name_or_slug.strip().lower()
        target_slug = slugify(name_or_slug)
        for pdir in self._iter_project_dirs(root):
            meta_file = pdir / "metadata.json"
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            pname = str(meta.get("name", "")).strip().lower()
            pslug = str(meta.get("slug", "")).strip().lower()
            pid = str(meta.get("project_id", "")).strip().lower()
            if target in {pname, pslug, pid, pdir.name.lower()} or target_slug == pslug:
                return pdir, meta

        raise SciTreeError(
            ERR_PROJECT_NOT_FOUND,
            f"Project '{name_or_slug}' not found.",
            {"project": name_or_slug},
        )

    def _recompute_summaries(self, metadata: dict[str, Any]) -> None:
        # Comments summary
        comments = metadata.get("comments", [])
        pending_c = sum(1 for c in comments if c.get("status") == "pending")
        resolved_c = sum(1 for c in comments if c.get("status") == "resolved")
        metadata["comments_summary"] = {"pending": pending_c, "resolved": resolved_c}

        # Per-version comment counts
        for ver in metadata.get("versions", []):
            vid = ver.get("version_id")
            vp = sum(1 for c in comments if c.get("version") == vid and c.get("status") == "pending")
            vr = sum(1 for c in comments if c.get("version") == vid and c.get("status") == "resolved")
            ver["comments_count"] = {"pending": vp, "resolved": vr}

        # Risks summary
        risks = metadata.get("risks", [])
        open_r = sum(1 for r in risks if r.get("status") == "open")
        mit_r = sum(1 for r in risks if r.get("status") == "mitigating")
        closed_r = sum(1 for r in risks if r.get("status") == "closed")
        high_crit = sum(
            1
            for r in risks
            if r.get("status") in {"open", "mitigating"} and r.get("severity") in {"high", "critical"}
        )
        metadata["risks_summary"] = {
            "open": open_r,
            "mitigating": mit_r,
            "closed": closed_r,
            "high_or_critical_open": high_crit,
        }

        # Milestones summary
        milestones = metadata.get("milestones", [])
        ms_pending = sum(1 for m in milestones if m.get("status") == "pending")
        ms_prog = sum(1 for m in milestones if m.get("status") == "in_progress")
        ms_done = sum(1 for m in milestones if m.get("status") == "done")
        ms_missed = sum(1 for m in milestones if m.get("status") == "missed")
        upcoming_dates = sorted(
            str(m["due_date"])
            for m in milestones
            if m.get("status") in {"pending", "in_progress"} and m.get("due_date")
        )
        next_due = upcoming_dates[0] if upcoming_dates else None
        metadata["milestones_summary"] = {
            "pending": ms_pending,
            "in_progress": ms_prog,
            "done": ms_done,
            "missed": ms_missed,
            "next_due": next_due,
        }

        # Latest version indicators
        active_versions = [v for v in metadata.get("versions", []) if not v.get("archived")]
        if active_versions:
            latest = active_versions[-1]
            metadata["latest_version_id"] = latest["version_id"]
            metadata["latest_version_locked"] = bool(latest.get("immutable", False))
        else:
            metadata["latest_version_id"] = None
            metadata["latest_version_locked"] = False

    def _save_project(self, root: Path, project_dir: Path, metadata: dict[str, Any]) -> None:
        self._recompute_summaries(metadata)
        meta_path = project_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self._get_db(root).sync_project(project_dir.name, metadata)

    # ------------------------------------------------------------------
    # Project Operations (Requirement 2, 3, Sections A, G)
    # ------------------------------------------------------------------
    def create_project(
        self,
        name: str,
        description: str = "",
        column: str | None = None,
        template_name: str | None = None,
        owner_type: str | None = None,
        owner_name: str | None = None,
        authors: list[dict[str, Any]] | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Create a new scientific project idempotently."""
        actor_info = actor or validate_actor(actor_source="cli")
        clean_name = (name or "").strip()
        if not clean_name:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Project name cannot be empty.")

        root = self.resolve_root()
        # Check idempotency: if project already exists, return it without duplicating folders
        try:
            existing_dir, existing_meta = self._find_project(root, clean_name)
            return wrap_response(
                {
                    "created": False,
                    "idempotent": True,
                    "project_dir": str(existing_dir),
                    "project": existing_meta,
                },
                actor=actor_info,
            )
        except SciTreeError:
            pass

        tpl = load_template_by_name(root / "Templates", template_name or "Default")
        columns = list(tpl.get("columns") or DEFAULT_COLUMNS)
        effective_col = column.strip() if column and column.strip() else columns[0]
        if effective_col not in columns:
            columns.append(effective_col)

        now = utc_now_iso()
        folder = safe_folder_name(clean_name)
        project_dir = root / "Projects" / folder
        # Also create a convenience symlink or ensure human-browsable structure
        eff_owner_type = owner_type or actor_info["actor_type"]
        eff_owner_name = owner_name or actor_info["actor_name"]

        initial_milestones: list[dict[str, Any]] = []
        for idx, ms_tpl in enumerate(tpl.get("milestones", []), start=1):
            initial_milestones.append(
                {
                    "milestone_id": f"ms_{idx:03d}",
                    "title": ms_tpl.get("title", f"Milestone {idx}"),
                    "description": ms_tpl.get("description", ""),
                    "phase": ms_tpl.get("phase", "custom"),
                    "due_date": ms_tpl.get("due_date"),
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                    "completed_at": None,
                }
            )

        initial_risks: list[dict[str, Any]] = []
        for idx, rsk_tpl in enumerate(tpl.get("risks", []), start=1):
            initial_risks.append(
                {
                    "risk_id": f"rsk_{idx:03d}",
                    "title": rsk_tpl.get("title", f"Risk {idx}"),
                    "description": rsk_tpl.get("description", ""),
                    "severity": rsk_tpl.get("severity", "medium"),
                    "likelihood": rsk_tpl.get("likelihood", "medium"),
                    "owner": eff_owner_name,
                    "status": "open",
                    "trigger": rsk_tpl.get("trigger", ""),
                    "mitigation": rsk_tpl.get("mitigation", ""),
                    "created_at": now,
                    "created_by": actor_info,
                    "updated_at": now,
                }
            )

        metadata: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "project_id": make_id("prj"),
            "name": clean_name,
            "slug": slugify(clean_name),
            "description": description or "",
            "template": {
                "name": tpl["name"],
                "version": tpl.get("version", "1.0"),
                "applied_at": now,
            },
            "status": {
                "column": effective_col,
                "column_order": columns,
                "owner_type": eff_owner_type,
                "owner_name": eff_owner_name,
            },
            "authors": authors or [{"name": eff_owner_name, "role": "corresponding"}],
            "created_at": now,
            "updated_at": now,
            "created_by": actor_info,
            "versions": [],
            "latest_version_id": None,
            "latest_version_locked": False,
            "files": {
                "data": [],
                "figures_standalone": [],
                "manuscripts": [],
            },
            "comments": [],
            "comments_summary": {"pending": 0, "resolved": 0},
            "risks": initial_risks,
            "risks_summary": {"open": 0, "mitigating": 0, "closed": 0, "high_or_critical_open": 0},
            "milestones": initial_milestones,
            "milestones_summary": {"pending": 0, "in_progress": 0, "done": 0, "missed": 0, "next_due": None},
            "zotero": {
                "linked": False,
                "collection_key": None,
                "collection_name": None,
                "last_sync_at": None,
                "last_sync_status": None,
                "bib_file": "References/references_zotero.bib",
            },
            "exports": [],
            "activity_summary": {
                "total_events": 0,
                "last_event_at": now,
                "actors": {"human": 0, "agent": 0},
                "sources": {"ui": 0, "cli": 0, "http": 0, "mcp": 0, "manifest": 0},
            },
            "settings_overrides": {
                "auto_extract_on_upload": True,
                "default_column_for_new_versions": "Writing" if "Writing" in columns else columns[0],
                "notify_on_immutable_latest": True,
            },
        }
        self._recompute_summaries(metadata)

        if dry_run:
            return wrap_response(
                {
                    "dry_run": True,
                    "created": True,
                    "project_dir": str(project_dir),
                    "project": metadata,
                },
                actor=actor_info,
            )

        for sub in [
            "Versions",
            "Figures_Text",
            "Figures_Standalone",
            "Data",
            "References",
            "Automation",
        ] + list(tpl.get("folders", [])):
            (project_dir / sub).mkdir(parents=True, exist_ok=True)

        self._append_project_event(
            root,
            project_dir,
            metadata,
            actor_info,
            "project.created",
            {"name": clean_name, "column": effective_col, "template": tpl["name"]},
        )
        self._save_project(root, project_dir, metadata)
        self._write_automation_log(
            root,
            actor_info,
            "project.create",
            {"project": clean_name, "project_id": metadata["project_id"], "created": True},
        )
        return wrap_response(
            {
                "created": True,
                "idempotent": False,
                "project_dir": str(project_dir),
                "project": metadata,
            },
            actor=actor_info,
        )

    def list_projects(
        self,
        column: str | None = None,
        owner_type: str | None = None,
        has_pending_comments: bool | None = None,
        author: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
    ) -> dict[str, Any]:
        """List all projects with optional filtering and sorting (Section A2 & A5)."""
        root = self.resolve_root()
        projects: list[dict[str, Any]] = []
        for pdir in self._iter_project_dirs(root):
            try:
                meta = json.loads((pdir / "metadata.json").read_text(encoding="utf-8"))
                self._recompute_summaries(meta)
                projects.append(meta)
            except (OSError, json.JSONDecodeError):
                continue

        filtered: list[dict[str, Any]] = []
        for p in projects:
            status = p.get("status", {})
            if column and status.get("column", "").lower() != column.strip().lower():
                continue
            if owner_type and owner_type.lower() != "all":
                # Match project owner_type OR any pending comment with that owner_type
                p_owner_match = status.get("owner_type", "human").lower() == owner_type.lower()
                c_owner_match = any(
                    c.get("owner_type", "human").lower() == owner_type.lower() and c.get("status") == "pending"
                    for c in p.get("comments", [])
                )
                if not (p_owner_match or c_owner_match):
                    continue
            if has_pending_comments is not None:
                pending_cnt = int(p.get("comments_summary", {}).get("pending", 0))
                if has_pending_comments and pending_cnt == 0:
                    continue
                if not has_pending_comments and pending_cnt > 0:
                    continue
            if author:
                q_auth = author.strip().lower()
                authors_list = [str(a.get("name", "")).lower() for a in p.get("authors", [])]
                ver_authors = [str(v.get("author", "")).lower() for v in p.get("versions", [])]
                if not any(q_auth in a for a in (authors_list + ver_authors)):
                    continue
            if search:
                q = search.strip().lower()
                haystack = " ".join(
                    [
                        str(p.get("name", "")),
                        str(p.get("description", "")),
                        str(status.get("column", "")),
                        str(status.get("owner_name", "")),
                        " ".join(str(v.get("author", "")) for v in p.get("versions", [])),
                    ]
                ).lower()
                if q not in haystack:
                    continue
            filtered.append(p)

        if sort_by == "name":
            filtered.sort(key=lambda x: str(x.get("name", "")).lower())
        elif sort_by == "column":
            filtered.sort(key=lambda x: str(x.get("status", {}).get("column", "")).lower())
        else:
            filtered.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)

        return wrap_response({"count": len(filtered), "projects": filtered})

    def get_project(self, name: str) -> dict[str, Any]:
        root = self.resolve_root()
        pdir, meta = self._find_project(root, name)
        self._recompute_summaries(meta)
        return wrap_response({"project_dir": str(pdir), "project": meta})

    def move_project(
        self,
        name: str,
        column: str,
        owner_type: str | None = None,
        owner_name: str | None = None,
        description: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, name)
        clean_col = (column or "").strip()
        if not clean_col:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Target column cannot be empty.")

        status = meta.setdefault("status", {})
        old_col = status.get("column", "Idea")
        col_order = list(status.get("column_order") or DEFAULT_COLUMNS)
        if clean_col not in col_order:
            col_order.append(clean_col)
            status["column_order"] = col_order

        status["column"] = clean_col
        if owner_type:
            status["owner_type"] = owner_type
        if owner_name:
            status["owner_name"] = owner_name
        if description is not None:
            meta["description"] = description

        if dry_run:
            return wrap_response(
                {
                    "dry_run": True,
                    "previous_column": old_col,
                    "column": clean_col,
                    "project": meta,
                },
                actor=actor_info,
            )

        if old_col != clean_col:
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "project.column_changed",
                {"from_column": old_col, "to_column": clean_col},
            )
        else:
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "project.updated",
                {"column": clean_col},
            )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "project.move",
            {"project": meta["name"], "from": old_col, "to": clean_col},
        )
        return wrap_response(
            {
                "previous_column": old_col,
                "column": clean_col,
                "project": meta,
            },
            actor=actor_info,
        )

    # ------------------------------------------------------------------
    # Version Control & Immutable Snapshots (Req 4, 6, 7 & Section D)
    # ------------------------------------------------------------------
    def _suggest_version_suffixes(self, existing_ids: set[str], base_id: str) -> list[str]:
        suggestions: list[str] = []
        for ch in "abcdefghijklmnopqrstuvwxyz":
            cand = f"{base_id}{ch}"
            if cand not in existing_ids:
                suggestions.append(cand)
                if len(suggestions) >= 3:
                    break
        return suggestions or [f"{base_id}_rev1"]

    def add_version(
        self,
        project_name: str,
        file_path: str | Path,
        author: str,
        version_id: str | None = None,
        changelog: str = "",
        state: str = "draft",
        derived_from: str | None = None,
        submitted_to: str | None = None,
        auto_suffix: bool = False,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Upload a manuscript version, run extraction, and register extracted comments."""
        actor_info = actor or validate_actor(actor_source="cli")
        if state not in VALID_VERSION_STATES:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                f"Invalid version state '{state}'. Expected one of {sorted(VALID_VERSION_STATES)}.",
            )
        src_path = Path(file_path).expanduser().resolve()
        if not src_path.exists() or not src_path.is_file():
            raise SciTreeError(
                ERR_FILE_NOT_FOUND,
                f"Manuscript file not found: '{file_path}'.",
                {"file": str(file_path)},
            )
        clean_author = (author or "").strip()
        if not clean_author:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Version author cannot be empty.")

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        versions: list[dict[str, Any]] = meta.setdefault("versions", [])
        existing_by_id = {v["version_id"]: v for v in versions}
        src_checksum = compute_sha256(src_path)

        # Determine version_id or check conflict/idempotency
        if version_id:
            target_vid = version_id.strip()
            if target_vid in existing_by_id:
                existing_v = existing_by_id[target_vid]
                if existing_v.get("immutable"):
                    suggestions = self._suggest_version_suffixes(set(existing_by_id.keys()), target_vid)
                    next_seq = f"v{len(versions) + 1}"
                    raise SciTreeError(
                        ERR_VERSION_IMMUTABLE,
                        f"Version '{target_vid}' is immutable ({existing_v.get('state')}) and cannot be overwritten. "
                        f"Create a new derived version such as '{next_seq}' with derived_from='{target_vid}'.",
                        {
                            "version_id": target_vid,
                            "state": existing_v.get("state"),
                            "suggested_derived_version": next_seq,
                            "derived_from": target_vid,
                            "suffix_alternatives": suggestions,
                        },
                    )
                existing_checksum = (existing_v.get("checksums") or {}).get("manuscript")
                if existing_checksum == src_checksum:
                    return wrap_response(
                        {
                            "created": False,
                            "idempotent": True,
                            "version": existing_v,
                            "project": meta,
                        },
                        actor=actor_info,
                    )
                suggestions = self._suggest_version_suffixes(set(existing_by_id.keys()), target_vid)
                if not auto_suffix:
                    raise SciTreeError(
                        ERR_VERSION_CONFLICT,
                        f"Version '{target_vid}' already exists with different content. "
                        f"Suggested suffix: {suggestions[0]} (or {', '.join(suggestions)}).",
                        {
                            "version_id": target_vid,
                            "suggested_version_id": suggestions[0],
                            "alternatives": suggestions,
                        },
                    )
                target_vid = suggestions[0]
        else:
            seq_num = len(versions) + 1
            target_vid = f"v{seq_num}"
            while target_vid in existing_by_id:
                seq_num += 1
                target_vid = f"v{seq_num}"

        # Automatically link derived_from if previous latest version was immutable
        eff_derived_from = derived_from
        if not eff_derived_from and versions:
            prev_v = versions[-1]
            if prev_v.get("immutable"):
                eff_derived_from = prev_v["version_id"]

        now = utc_now_iso()
        is_immutable = state in {"submitted", "published"}
        ext = src_path.suffix.lower() or ".docx"
        rel_ms_path = f"Versions/{target_vid}/manuscript{ext}"

        if dry_run:
            preview_ver = {
                "version_id": target_vid,
                "state": state,
                "immutable": is_immutable,
                "derived_from": eff_derived_from,
                "author": clean_author,
                "changelog": changelog or "",
                "created_at": now,
                "created_by": actor_info,
                "files": {
                    "manuscript": rel_ms_path,
                    "figures_dir": f"Figures_Text/{target_vid}/",
                    "bib": f"References/{target_vid}.bib",
                },
                "checksums": {"manuscript": src_checksum},
            }
            return wrap_response(
                {
                    "dry_run": True,
                    "created": True,
                    "version": preview_ver,
                },
                actor=actor_info,
            )

        dest_ms_path = pdir / rel_ms_path
        dest_ms_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_ms_path)

        extraction_res = extract_manuscript_artifacts(
            manuscript_path=dest_ms_path,
            project_dir=pdir,
            version_id=target_vid,
            default_author=clean_author,
        )
        bib_full = pdir / extraction_res["bib_rel_path"]
        bib_checksum = compute_sha256(bib_full) if bib_full.exists() else ""

        # Register extracted comments idempotently
        existing_comments = meta.setdefault("comments", [])
        existing_comment_keys = {(c.get("version"), c.get("text")) for c in existing_comments}
        extracted_comments_added = 0
        for idx, c_item in enumerate(extraction_res.get("comments", []), start=1):
            ckey = (target_vid, c_item["text"])
            if ckey in existing_comment_keys:
                continue
            existing_comment_keys.add(ckey)
            new_cmt = {
                "comment_id": make_id("cmt"),
                "text": c_item["text"],
                "version": target_vid,
                "owner_type": c_item.get("owner_type", "human"),
                "owner_name": c_item.get("owner_name") or clean_author,
                "status": "pending",
                "source": c_item.get("source", "docx_comment"),
                "created_at": now,
                "created_by": {
                    "actor_name": f"system:{ext.lstrip('.')}-extractor",
                    "actor_type": "agent",
                    "actor_source": actor_info["actor_source"],
                },
            }
            existing_comments.append(new_cmt)
            extracted_comments_added += 1

        version_entry: dict[str, Any] = {
            "version_id": target_vid,
            "state": state,
            "immutable": is_immutable,
            "archived": False,
            "author": clean_author,
            "changelog": changelog or "",
            "created_at": now,
            "created_by": actor_info,
            "files": {
                "manuscript": rel_ms_path,
                "figures_dir": extraction_res["figures_rel_dir"],
                "bib": extraction_res["bib_rel_path"],
            },
            "extraction": {
                "status": extraction_res["status"],
                "figures_extracted": extraction_res["figures_extracted"],
                "references_parsed": extraction_res["references_parsed"],
                "warnings": extraction_res["warnings"],
            },
            "checksums": {
                "manuscript": src_checksum,
                "bib": bib_checksum,
            },
            "comments_count": {"pending": 0, "resolved": 0},
        }
        if eff_derived_from:
            version_entry["derived_from"] = eff_derived_from
        if submitted_to:
            version_entry["submitted_to"] = submitted_to
        if is_immutable:
            version_entry["submitted_at"] = now
            version_entry["locked_at"] = now
            version_entry["locked_by"] = actor_info

        # Ensure author is in project authors list
        proj_authors = meta.setdefault("authors", [])
        if not any(str(a.get("name", "")).lower() == clean_author.lower() for a in proj_authors):
            proj_authors.append({"name": clean_author, "role": "co-author"})

        versions.append(version_entry)
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "version.derived" if eff_derived_from else "version.added",
            {
                "version_id": target_vid,
                "author": clean_author,
                "changelog": changelog or "",
                "state": state,
                "derived_from": eff_derived_from,
                "figures_extracted": extraction_res["figures_extracted"],
                "references_parsed": extraction_res["references_parsed"],
                "comments_extracted": extracted_comments_added,
            },
        )
        if is_immutable:
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "version.locked",
                {"version_id": target_vid, "state": state},
            )

        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "version.add",
            {"project": meta["name"], "version_id": target_vid, "state": state},
        )
        return wrap_response(
            {
                "created": True,
                "idempotent": False,
                "version": version_entry,
                "extraction_comments_added": extracted_comments_added,
                "project": meta,
            },
            actor=actor_info,
        )

    def list_versions(self, project_name: str, include_archived: bool = False) -> dict[str, Any]:
        root = self.resolve_root()
        _, meta = self._find_project(root, project_name)
        versions = [
            v
            for v in meta.get("versions", [])
            if include_archived or not v.get("archived", False)
        ]
        return wrap_response(
            {
                "project": meta["name"],
                "latest_version_id": meta.get("latest_version_id"),
                "latest_version_locked": bool(meta.get("latest_version_locked", False)),
                "count": len(versions),
                "versions": versions,
            }
        )

    def update_version_state(
        self,
        project_name: str,
        version_id: str,
        state: str | None = None,
        changelog: str | None = None,
        submitted_to: str | None = None,
        archived: bool | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Promote a version to submitted/published (making it immutable) or archive it."""
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        versions = meta.get("versions", [])
        target_v: dict[str, Any] | None = None
        for v in versions:
            if v.get("version_id") == version_id:
                target_v = v
                break

        if not target_v:
            raise SciTreeError(
                ERR_VERSION_NOT_FOUND,
                f"Version '{version_id}' not found in project '{meta['name']}'.",
                {"project": meta["name"], "version_id": version_id},
            )

        # Archiving is allowed even on immutable versions (Section D5)
        if archived is not None and state is None and changelog is None and submitted_to is None:
            if dry_run:
                preview = copy.deepcopy(target_v)
                preview["archived"] = bool(archived)
                return wrap_response({"dry_run": True, "version": preview}, actor=actor_info)
            target_v["archived"] = bool(archived)
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "version.archived",
                {"version_id": version_id, "archived": bool(archived)},
            )
            self._save_project(root, pdir, meta)
            return wrap_response({"version": target_v, "project": meta}, actor=actor_info)

        # Check immutability constraint (Section D2 & D4)
        if target_v.get("immutable"):
            # Allow only promoting from submitted -> published without altering files/changelog
            if state == "published" and target_v.get("state") == "submitted" and changelog is None:
                pass
            else:
                next_seq = f"v{len(versions) + 1}"
                raise SciTreeError(
                    ERR_VERSION_IMMUTABLE,
                    f"Version '{version_id}' is immutable ({target_v.get('state')}) and cannot be modified. "
                    f"Create a new derived version '{next_seq}' with derived_from='{version_id}'.",
                    {
                        "version_id": version_id,
                        "current_state": target_v.get("state"),
                        "suggested_derived_version": next_seq,
                        "derived_from": version_id,
                    },
                )

        if state is not None and state not in VALID_VERSION_STATES:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                f"Invalid version state '{state}'. Expected one of {sorted(VALID_VERSION_STATES)}.",
            )

        now = utc_now_iso()
        preview_v = copy.deepcopy(target_v)
        if changelog is not None:
            preview_v["changelog"] = changelog
        if submitted_to is not None:
            preview_v["submitted_to"] = submitted_to
        if archived is not None:
            preview_v["archived"] = bool(archived)
        if state is not None:
            preview_v["state"] = state
            if state in {"submitted", "published"}:
                preview_v["immutable"] = True
                preview_v.setdefault("submitted_at", now)
                preview_v["locked_at"] = now
                preview_v["locked_by"] = actor_info

        if dry_run:
            return wrap_response({"dry_run": True, "version": preview_v}, actor=actor_info)

        target_v.update(preview_v)
        if state == "submitted":
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "version.submitted",
                {"version_id": version_id, "submitted_to": target_v.get("submitted_to")},
            )
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "version.locked",
                {"version_id": version_id, "state": "submitted"},
            )
        elif state == "published":
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "version.published",
                {"version_id": version_id},
            )
            self._append_project_event(
                root,
                pdir,
                meta,
                actor_info,
                "version.locked",
                {"version_id": version_id, "state": "published"},
            )

        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "version.update_state",
            {"project": meta["name"], "version_id": version_id, "state": target_v.get("state")},
        )
        return wrap_response({"version": target_v, "project": meta}, actor=actor_info)

    def delete_version(
        self,
        project_name: str,
        version_id: str,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attempt to delete a version; strictly forbidden on immutable versions (Section D5)."""
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        versions = meta.get("versions", [])
        target_v = next((v for v in versions if v.get("version_id") == version_id), None)
        if not target_v:
            raise SciTreeError(ERR_VERSION_NOT_FOUND, f"Version '{version_id}' not found.")
        if target_v.get("immutable"):
            raise SciTreeError(
                ERR_VERSION_IMMUTABLE,
                f"Deleting immutable version '{version_id}' is forbidden. Only archiving is allowed.",
                {"version_id": version_id, "allowed_action": "archive"},
            )
        meta["versions"] = [v for v in versions if v.get("version_id") != version_id]
        self._save_project(root, pdir, meta)
        return wrap_response({"deleted": version_id, "project": meta}, actor=actor_info)

    # ------------------------------------------------------------------
    # File Upload and Management (Requirement 5)
    # ------------------------------------------------------------------
    def add_file(
        self,
        project_name: str,
        file_path: str | Path,
        kind: str,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_kind = (kind or "").strip().lower()
        if clean_kind not in VALID_FILE_KINDS:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                f"Invalid file kind '{kind}'. Expected one of {sorted(VALID_FILE_KINDS)}.",
            )
        src_path = Path(file_path).expanduser().resolve()
        if not src_path.exists() or not src_path.is_file():
            raise SciTreeError(
                ERR_FILE_NOT_FOUND,
                f"File not found: '{file_path}'.",
                {"file": str(file_path)},
            )

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)

        if clean_kind == "data":
            sub_dir = "Data"
            meta_key = "data"
            prefix = "f_d"
        elif clean_kind == "figure":
            sub_dir = "Figures_Standalone"
            meta_key = "figures_standalone"
            prefix = "f_f"
        else:
            sub_dir = "Versions"
            meta_key = "manuscripts"
            prefix = "f_m"

        rel_dest = f"{sub_dir}/{src_path.name}"
        checksum = compute_sha256(src_path)
        files_section = meta.setdefault("files", {"data": [], "figures_standalone": [], "manuscripts": []})
        bucket: list[dict[str, Any]] = files_section.setdefault(meta_key, [])

        for existing in bucket:
            if existing.get("path") == rel_dest and existing.get("checksum") == checksum:
                return wrap_response(
                    {"created": False, "idempotent": True, "file": existing, "project": meta},
                    actor=actor_info,
                )

        now = utc_now_iso()
        file_entry = {
            "file_id": f"{prefix}{len(bucket) + 1}",
            "kind": clean_kind,
            "path": rel_dest,
            "size_bytes": src_path.stat().st_size,
            "checksum": checksum,
            "added_at": now,
            "added_by": actor_info,
        }

        if dry_run:
            return wrap_response({"dry_run": True, "created": True, "file": file_entry}, actor=actor_info)

        dest_full = pdir / rel_dest
        dest_full.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_full)

        # Replace existing entry if same path or append
        bucket = [f for f in bucket if f.get("path") != rel_dest]
        bucket.append(file_entry)
        files_section[meta_key] = bucket

        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "file.added",
            {"file_id": file_entry["file_id"], "kind": clean_kind, "path": rel_dest},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "file.add",
            {"project": meta["name"], "kind": clean_kind, "path": rel_dest},
        )
        return wrap_response(
            {"created": True, "idempotent": False, "file": file_entry, "project": meta},
            actor=actor_info,
        )

    # ------------------------------------------------------------------
    # Comment Cards (Requirement 7 & Section E)
    # ------------------------------------------------------------------
    def add_comment(
        self,
        project_name: str,
        text: str,
        version: str | None = None,
        owner_type: str | None = None,
        owner_name: str | None = None,
        comment_id: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_text = (text or "").strip()
        if not clean_text:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Comment text cannot be empty.")

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        comments: list[dict[str, Any]] = meta.setdefault("comments", [])

        eff_version = version or meta.get("latest_version_id")
        for existing in comments:
            if (comment_id and existing.get("comment_id") == comment_id) or (
                existing.get("text") == clean_text and existing.get("version") == eff_version
            ):
                return wrap_response(
                    {"created": False, "idempotent": True, "comment": existing, "project": meta},
                    actor=actor_info,
                )

        eff_owner_type = owner_type or actor_info["actor_type"]
        eff_owner_name = owner_name or actor_info["actor_name"]
        now = utc_now_iso()
        new_cmt = {
            "comment_id": comment_id or f"cmt_{len(comments) + 1:03d}",
            "text": clean_text,
            "version": eff_version,
            "owner_type": eff_owner_type,
            "owner_name": eff_owner_name,
            "status": "pending",
            "source": "manual" if actor_info["actor_type"] == "human" else "agent",
            "created_at": now,
            "created_by": actor_info,
        }

        if dry_run:
            return wrap_response({"dry_run": True, "created": True, "comment": new_cmt}, actor=actor_info)

        comments.append(new_cmt)
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "comment.added",
            {"comment_id": new_cmt["comment_id"], "version": eff_version, "owner_type": eff_owner_type},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "comment.add",
            {"project": meta["name"], "comment_id": new_cmt["comment_id"]},
        )
        return wrap_response(
            {"created": True, "idempotent": False, "comment": new_cmt, "project": meta},
            actor=actor_info,
        )

    def resolve_comment(
        self,
        project_name: str,
        comment_id: str,
        resolved: bool = True,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        comments = meta.get("comments", [])
        target = next((c for c in comments if c.get("comment_id") == comment_id), None)
        if not target:
            raise SciTreeError(
                ERR_COMMENT_NOT_FOUND,
                f"Comment '{comment_id}' not found in project '{meta['name']}'.",
                {"project": meta["name"], "comment_id": comment_id},
            )

        new_status = "resolved" if resolved else "pending"
        now = utc_now_iso()
        preview = copy.deepcopy(target)
        preview["status"] = new_status
        if resolved:
            preview["resolved_at"] = now
            preview["resolved_by"] = actor_info
        else:
            preview.pop("resolved_at", None)
            preview.pop("resolved_by", None)

        if dry_run:
            return wrap_response({"dry_run": True, "comment": preview}, actor=actor_info)

        target.update(preview)
        if not resolved:
            target.pop("resolved_at", None)
            target.pop("resolved_by", None)

        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "comment.resolved" if resolved else "comment.reopened",
            {"comment_id": comment_id, "status": new_status},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "comment.resolve",
            {"project": meta["name"], "comment_id": comment_id, "status": new_status},
        )
        return wrap_response({"comment": target, "project": meta}, actor=actor_info)

    def list_comments(
        self,
        project_name: str,
        status: str | None = None,
        owner_type: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        if status and status not in VALID_COMMENT_STATUSES:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                f"Invalid comment status filter '{status}'. Expected pending or resolved.",
            )
        root = self.resolve_root()
        _, meta = self._find_project(root, project_name)
        items = meta.get("comments", [])
        if status:
            items = [c for c in items if c.get("status") == status]
        if owner_type and owner_type != "all":
            items = [c for c in items if c.get("owner_type") == owner_type]
        if version:
            items = [c for c in items if c.get("version") == version]
        return wrap_response(
            {
                "project": meta["name"],
                "count": len(items),
                "summary": meta.get("comments_summary", {}),
                "comments": items,
            }
        )

    # ------------------------------------------------------------------
    # Risks per Project (Section B1 & B4)
    # ------------------------------------------------------------------
    def add_risk(
        self,
        project_name: str,
        title: str,
        description: str = "",
        severity: str = "medium",
        likelihood: str = "medium",
        owner: str = "",
        status: str = "open",
        trigger: str = "",
        mitigation: str = "",
        risk_id: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_title = (title or "").strip()
        if not clean_title:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Risk title cannot be empty.")
        if severity not in VALID_RISK_SEVERITIES:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid risk severity '{severity}'.")
        if likelihood not in VALID_RISK_LIKELIHOODS:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid risk likelihood '{likelihood}'.")
        if status not in VALID_RISK_STATUSES:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid risk status '{status}'.")

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        risks: list[dict[str, Any]] = meta.setdefault("risks", [])

        for existing in risks:
            if (risk_id and existing.get("risk_id") == risk_id) or (
                existing.get("title", "").lower() == clean_title.lower()
            ):
                return wrap_response(
                    {"created": False, "idempotent": True, "risk": existing, "project": meta},
                    actor=actor_info,
                )

        now = utc_now_iso()
        new_risk: dict[str, Any] = {
            "risk_id": risk_id or f"rsk_{len(risks) + 1:03d}",
            "title": clean_title,
            "description": description or "",
            "severity": severity,
            "likelihood": likelihood,
            "owner": owner or actor_info["actor_name"],
            "status": status,
            "trigger": trigger or "",
            "mitigation": mitigation or "",
            "created_at": now,
            "created_by": actor_info,
            "updated_at": now,
        }

        if dry_run:
            return wrap_response({"dry_run": True, "created": True, "risk": new_risk}, actor=actor_info)

        risks.append(new_risk)
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "risk.added",
            {"risk_id": new_risk["risk_id"], "title": clean_title, "severity": severity},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "risk.add",
            {"project": meta["name"], "risk_id": new_risk["risk_id"]},
        )
        return wrap_response(
            {"created": True, "idempotent": False, "risk": new_risk, "project": meta},
            actor=actor_info,
        )

    def list_risks(self, project_name: str, status: str | None = None) -> dict[str, Any]:
        root = self.resolve_root()
        _, meta = self._find_project(root, project_name)
        risks = meta.get("risks", [])
        if status:
            risks = [r for r in risks if r.get("status") == status]
        return wrap_response(
            {
                "project": meta["name"],
                "count": len(risks),
                "summary": meta.get("risks_summary", {}),
                "risks": risks,
            }
        )

    def update_risk(
        self,
        project_name: str,
        risk_id: str,
        title: str | None = None,
        description: str | None = None,
        severity: str | None = None,
        likelihood: str | None = None,
        owner: str | None = None,
        status: str | None = None,
        trigger: str | None = None,
        mitigation: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        risks = meta.get("risks", [])
        target = next((r for r in risks if r.get("risk_id") == risk_id), None)
        if not target:
            raise SciTreeError(
                ERR_RISK_NOT_FOUND,
                f"Risk '{risk_id}' not found in project '{meta['name']}'.",
                {"project": meta["name"], "risk_id": risk_id},
            )

        if severity is not None and severity not in VALID_RISK_SEVERITIES:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid risk severity '{severity}'.")
        if likelihood is not None and likelihood not in VALID_RISK_LIKELIHOODS:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid risk likelihood '{likelihood}'.")
        if status is not None and status not in VALID_RISK_STATUSES:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid risk status '{status}'.")

        preview = copy.deepcopy(target)
        if title is not None:
            preview["title"] = title
        if description is not None:
            preview["description"] = description
        if severity is not None:
            preview["severity"] = severity
        if likelihood is not None:
            preview["likelihood"] = likelihood
        if owner is not None:
            preview["owner"] = owner
        if status is not None:
            preview["status"] = status
        if trigger is not None:
            preview["trigger"] = trigger
        if mitigation is not None:
            preview["mitigation"] = mitigation
        preview["updated_at"] = utc_now_iso()

        if dry_run:
            return wrap_response({"dry_run": True, "risk": preview}, actor=actor_info)

        target.update(preview)
        ev_type = "risk.closed" if status == "closed" else "risk.updated"
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            ev_type,
            {"risk_id": risk_id, "status": target.get("status"), "severity": target.get("severity")},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "risk.update",
            {"project": meta["name"], "risk_id": risk_id, "status": target.get("status")},
        )
        return wrap_response({"risk": target, "project": meta}, actor=actor_info)

    def close_risk(
        self,
        project_name: str,
        risk_id: str,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.update_risk(
            project_name=project_name,
            risk_id=risk_id,
            status="closed",
            actor=actor,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    # Milestones per Project (Section B2 & B4)
    # ------------------------------------------------------------------
    def add_milestone(
        self,
        project_name: str,
        title: str,
        phase: str = "short_term_7d",
        description: str = "",
        due_date: str | None = None,
        status: str = "pending",
        milestone_id: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_title = (title or "").strip()
        if not clean_title:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Milestone title cannot be empty.")
        if phase not in VALID_MILESTONE_PHASES:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                f"Invalid milestone phase '{phase}'. Expected one of {sorted(VALID_MILESTONE_PHASES)}.",
            )
        if status not in VALID_MILESTONE_STATUSES:
            raise SciTreeError(
                ERR_VALIDATION_ERROR,
                f"Invalid milestone status '{status}'. Expected one of {sorted(VALID_MILESTONE_STATUSES)}.",
            )

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        milestones: list[dict[str, Any]] = meta.setdefault("milestones", [])

        for existing in milestones:
            if (milestone_id and existing.get("milestone_id") == milestone_id) or (
                existing.get("title", "").lower() == clean_title.lower() and existing.get("phase") == phase
            ):
                return wrap_response(
                    {"created": False, "idempotent": True, "milestone": existing, "project": meta},
                    actor=actor_info,
                )

        now = utc_now_iso()
        new_ms: dict[str, Any] = {
            "milestone_id": milestone_id or f"ms_{len(milestones) + 1:03d}",
            "title": clean_title,
            "description": description or "",
            "phase": phase,
            "due_date": due_date,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "completed_at": now if status == "done" else None,
        }
        if status == "done":
            new_ms["completed_by"] = actor_info

        if dry_run:
            return wrap_response({"dry_run": True, "created": True, "milestone": new_ms}, actor=actor_info)

        milestones.append(new_ms)
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "milestone.added",
            {"milestone_id": new_ms["milestone_id"], "title": clean_title, "phase": phase, "due_date": due_date},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "milestone.add",
            {"project": meta["name"], "milestone_id": new_ms["milestone_id"]},
        )
        return wrap_response(
            {"created": True, "idempotent": False, "milestone": new_ms, "project": meta},
            actor=actor_info,
        )

    def list_milestones(self, project_name: str, status: str | None = None, phase: str | None = None) -> dict[str, Any]:
        root = self.resolve_root()
        _, meta = self._find_project(root, project_name)
        items = list(meta.get("milestones", []))
        if status:
            items = [m for m in items if m.get("status") == status]
        if phase:
            items = [m for m in items if m.get("phase") == phase]

        phase_rank = {p: i for i, p in enumerate(MILESTONE_PHASE_ORDER)}
        items.sort(key=lambda m: (phase_rank.get(m.get("phase", "custom"), 99), str(m.get("due_date") or "9999")))

        return wrap_response(
            {
                "project": meta["name"],
                "count": len(items),
                "summary": meta.get("milestones_summary", {}),
                "milestones": items,
            }
        )

    def update_milestone(
        self,
        project_name: str,
        milestone_id: str,
        title: str | None = None,
        description: str | None = None,
        phase: str | None = None,
        due_date: str | None = None,
        status: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        milestones = meta.get("milestones", [])
        target = next((m for m in milestones if m.get("milestone_id") == milestone_id), None)
        if not target:
            raise SciTreeError(
                ERR_MILESTONE_NOT_FOUND,
                f"Milestone '{milestone_id}' not found in project '{meta['name']}'.",
                {"project": meta["name"], "milestone_id": milestone_id},
            )

        if phase is not None and phase not in VALID_MILESTONE_PHASES:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid milestone phase '{phase}'.")
        if status is not None and status not in VALID_MILESTONE_STATUSES:
            raise SciTreeError(ERR_VALIDATION_ERROR, f"Invalid milestone status '{status}'.")

        now = utc_now_iso()
        preview = copy.deepcopy(target)
        if title is not None:
            preview["title"] = title
        if description is not None:
            preview["description"] = description
        if phase is not None:
            preview["phase"] = phase
        if due_date is not None:
            preview["due_date"] = due_date
        if status is not None:
            preview["status"] = status
            if status == "done":
                preview["completed_at"] = now
                preview["completed_by"] = actor_info
            else:
                preview["completed_at"] = None
                preview.pop("completed_by", None)
        preview["updated_at"] = now

        if dry_run:
            return wrap_response({"dry_run": True, "milestone": preview}, actor=actor_info)

        target.update(preview)
        if status == "done":
            ev_type = "milestone.completed"
        elif status == "missed":
            ev_type = "milestone.missed"
        else:
            ev_type = "milestone.updated"

        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            ev_type,
            {"milestone_id": milestone_id, "status": target.get("status"), "phase": target.get("phase")},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "milestone.update",
            {"project": meta["name"], "milestone_id": milestone_id, "status": target.get("status")},
        )
        return wrap_response({"milestone": target, "project": meta}, actor=actor_info)

    def close_milestone(
        self,
        project_name: str,
        milestone_id: str,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.update_milestone(
            project_name=project_name,
            milestone_id=milestone_id,
            status="done",
            actor=actor,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    # Activity Log and Timeline / Route View (Sections C & E4)
    # ------------------------------------------------------------------
    def _read_project_events(self, project_dir: Path) -> list[dict[str, Any]]:
        log_path = project_dir / "activity_log.jsonl"
        if not log_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if isinstance(ev, dict):
                    events.append(ev)
            except json.JSONDecodeError:
                continue
        return events

    def list_activity(
        self,
        project_name: str,
        actor_type: str | None = None,
        actor_source: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        events = self._read_project_events(pdir)

        filtered: list[dict[str, Any]] = []
        for ev in events:
            actor = ev.get("actor", {})
            ts = str(ev.get("timestamp", ""))
            day = ts[:10]
            if actor_type and actor_type != "all" and actor.get("actor_type") != actor_type:
                continue
            if actor_source and actor_source != "all" and actor.get("actor_source") != actor_source:
                continue
            if event_type and ev.get("event_type") != event_type:
                continue
            if date_from and day < date_from[:10]:
                continue
            if date_to and day > date_to[:10]:
                continue
            filtered.append(ev)

        return wrap_response(
            {
                "project": meta["name"],
                "count": len(filtered),
                "summary": meta.get("activity_summary", {}),
                "events": filtered,
            }
        )

    def get_timeline(
        self,
        project_name: str,
        actor_type: str | None = None,
        actor_source: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        """Derive the chronological Timeline / Route View grouped by day from the Activity Log."""
        act = self.list_activity(
            project_name=project_name,
            actor_type=actor_type,
            actor_source=actor_source,
            event_type=event_type,
        )
        events = sorted(act["events"], key=lambda e: str(e.get("timestamp", "")), reverse=True)
        days_map: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            day = str(ev.get("timestamp", ""))[:10] or "unknown"
            days_map.setdefault(day, []).append(ev)

        grouped_days = [{"date": d, "events": evs} for d, evs in days_map.items()]
        return wrap_response(
            {
                "project": act["project"],
                "total_events": len(events),
                "days": grouped_days,
                "events": events,
            }
        )

    def add_timeline_note(
        self,
        project_name: str,
        note: str,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_note = (note or "").strip()
        if not clean_note:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Timeline note text cannot be empty.")

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        if dry_run:
            return wrap_response(
                {"dry_run": True, "event_type": "note.added", "note": clean_note},
                actor=actor_info,
            )

        ev = self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "note.added",
            {"note": clean_note},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "timeline.note_add",
            {"project": meta["name"], "event_id": ev["event_id"]},
        )
        return wrap_response({"event": ev, "project": meta}, actor=actor_info)

    # ------------------------------------------------------------------
    # Submission Package Export (Section F)
    # ------------------------------------------------------------------
    def export_package(
        self,
        project_name: str,
        version_id: str | None = None,
        output_path: str | Path | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        target_vid = version_id or meta.get("latest_version_id")

        if dry_run:
            return wrap_response(
                {
                    "dry_run": True,
                    "project": meta["name"],
                    "version": target_vid,
                },
                actor=actor_info,
            )

        out_p = Path(output_path) if output_path else None
        pkg = build_submission_package(
            root_path=root,
            project_dir=pdir,
            project_metadata=meta,
            version_id=target_vid,
            output_path=out_p,
        )

        exports_list: list[dict[str, Any]] = meta.setdefault("exports", [])
        export_record = {
            "export_id": f"exp_{len(exports_list) + 1:03d}",
            "version": pkg["version"],
            "path": pkg["path"],
            "absolute_path": pkg["absolute_path"],
            "created_at": utc_now_iso(),
            "created_by": actor_info,
            "checksum": pkg["checksum"],
        }
        exports_list.append(export_record)
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "export.created",
            {"export_id": export_record["export_id"], "version": pkg["version"], "path": pkg["path"]},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "export.package",
            {"project": meta["name"], "version": pkg["version"], "checksum": pkg["checksum"]},
        )
        return wrap_response(
            {
                "export": export_record,
                "included_files": pkg["included_files"],
                "package_metadata": pkg["package_metadata"],
            },
            actor=actor_info,
        )

    # ------------------------------------------------------------------
    # Project Templates (Section G)
    # ------------------------------------------------------------------
    def list_templates(self) -> dict[str, Any]:
        root = self.resolve_root()
        tpls = list_all_templates(root / "Templates")
        for t in tpls:
            self._get_db(root).sync_template(t)
        return wrap_response({"count": len(tpls), "templates": tpls})

    def save_template(
        self,
        project_name: str,
        template_name: str,
        description: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_tpl_name = (template_name or "").strip()
        if not clean_tpl_name:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Template name cannot be empty.")

        root = self.resolve_root()
        _, meta = self._find_project(root, project_name)
        if dry_run:
            return wrap_response(
                {"dry_run": True, "template_name": clean_tpl_name, "source_project": meta["name"]},
                actor=actor_info,
            )

        tpl = save_template_from_project(
            templates_dir=root / "Templates",
            template_name=clean_tpl_name,
            project_metadata=meta,
            description=description,
        )
        self._get_db(root).sync_template(tpl)
        self._write_automation_log(
            root,
            actor_info,
            "template.save",
            {"template": clean_tpl_name, "from_project": meta["name"]},
        )
        return wrap_response({"template": tpl}, actor=actor_info)

    def apply_template(
        self,
        project_name: str,
        template_name: str,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Apply a template to an existing project (only adds missing items; never removes)."""
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        tpl = load_template_by_name(root / "Templates", template_name)

        added_columns: list[str] = []
        added_milestones: list[str] = []
        added_risks: list[str] = []
        added_folders: list[str] = []

        status = meta.setdefault("status", {})
        col_order: list[str] = list(status.get("column_order") or DEFAULT_COLUMNS)
        for col in tpl.get("columns", []):
            if col not in col_order:
                col_order.append(col)
                added_columns.append(col)
        status["column_order"] = col_order

        now = utc_now_iso()
        milestones: list[dict[str, Any]] = meta.setdefault("milestones", [])
        existing_ms_titles = {str(m.get("title", "")).lower() for m in milestones}
        for ms_tpl in tpl.get("milestones", []):
            t_str = str(ms_tpl.get("title", "")).strip()
            if t_str and t_str.lower() not in existing_ms_titles:
                existing_ms_titles.add(t_str.lower())
                milestones.append(
                    {
                        "milestone_id": f"ms_{len(milestones) + 1:03d}",
                        "title": t_str,
                        "description": ms_tpl.get("description", ""),
                        "phase": ms_tpl.get("phase", "custom"),
                        "due_date": ms_tpl.get("due_date"),
                        "status": "pending",
                        "created_at": now,
                        "updated_at": now,
                        "completed_at": None,
                    }
                )
                added_milestones.append(t_str)

        risks: list[dict[str, Any]] = meta.setdefault("risks", [])
        existing_rsk_titles = {str(r.get("title", "")).lower() for r in risks}
        for rsk_tpl in tpl.get("risks", []):
            t_str = str(rsk_tpl.get("title", "")).strip()
            if t_str and t_str.lower() not in existing_rsk_titles:
                existing_rsk_titles.add(t_str.lower())
                risks.append(
                    {
                        "risk_id": f"rsk_{len(risks) + 1:03d}",
                        "title": t_str,
                        "description": rsk_tpl.get("description", ""),
                        "severity": rsk_tpl.get("severity", "medium"),
                        "likelihood": rsk_tpl.get("likelihood", "medium"),
                        "owner": status.get("owner_name", actor_info["actor_name"]),
                        "status": "open",
                        "trigger": rsk_tpl.get("trigger", ""),
                        "mitigation": rsk_tpl.get("mitigation", ""),
                        "created_at": now,
                        "created_by": actor_info,
                        "updated_at": now,
                    }
                )
                added_risks.append(t_str)

        for folder_name in tpl.get("folders", []):
            f_path = pdir / folder_name
            if not f_path.exists():
                added_folders.append(folder_name)
                if not dry_run:
                    f_path.mkdir(parents=True, exist_ok=True)

        meta["template"] = {
            "name": tpl["name"],
            "version": tpl.get("version", "1.0"),
            "applied_at": now,
        }

        changes = {
            "template": tpl["name"],
            "added_columns": added_columns,
            "added_milestones": added_milestones,
            "added_risks": added_risks,
            "added_folders": added_folders,
        }
        if dry_run:
            return wrap_response({"dry_run": True, "changes": changes, "project": meta}, actor=actor_info)

        self._append_project_event(root, pdir, meta, actor_info, "project.template_applied", changes)
        self._save_project(root, pdir, meta)
        self._write_automation_log(root, actor_info, "template.apply", {"project": meta["name"], **changes})
        return wrap_response({"changes": changes, "project": meta}, actor=actor_info)

    # ------------------------------------------------------------------
    # Zotero Integration (Section H)
    # ------------------------------------------------------------------
    def zotero_link(
        self,
        project_name: str,
        collection_key: str,
        collection_name: str | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        clean_key = (collection_key or "").strip()
        if not clean_key:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Zotero collection_key cannot be empty.")

        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        zcfg = meta.setdefault("zotero", {})
        zcfg.update(
            {
                "linked": True,
                "collection_key": clean_key,
                "collection_name": collection_name or f"Collection {clean_key}",
                "bib_file": "References/references_zotero.bib",
            }
        )
        if dry_run:
            return wrap_response({"dry_run": True, "zotero": zcfg}, actor=actor_info)

        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "zotero.linked",
            {"collection_key": clean_key, "collection_name": zcfg["collection_name"]},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "zotero.link",
            {"project": meta["name"], "collection_key": clean_key},
        )
        return wrap_response({"zotero": zcfg, "project": meta}, actor=actor_info)

    def zotero_unlink(
        self,
        project_name: str,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        zcfg = meta.setdefault("zotero", {})
        prev_key = zcfg.get("collection_key")
        zcfg["linked"] = False
        zcfg["collection_key"] = None
        zcfg["collection_name"] = None

        if dry_run:
            return wrap_response({"dry_run": True, "zotero": zcfg}, actor=actor_info)

        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "zotero.unlinked",
            {"previous_collection_key": prev_key},
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(root, actor_info, "zotero.unlink", {"project": meta["name"]})
        return wrap_response({"zotero": zcfg, "project": meta}, actor=actor_info)

    def zotero_sync(
        self,
        project_name: str,
        strict: bool = False,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        actor_info = actor or validate_actor(actor_source="cli")
        root = self.resolve_root()
        pdir, meta = self._find_project(root, project_name)
        zcfg = meta.get("zotero") or {}

        if dry_run:
            return wrap_response({"dry_run": True, "zotero": zcfg}, actor=actor_info)

        sync_res = sync_zotero_collection(project_dir=pdir, zotero_config=zcfg, strict=strict)
        meta["zotero"] = sync_res["zotero"]
        self._append_project_event(
            root,
            pdir,
            meta,
            actor_info,
            "zotero.synced",
            {
                "status": sync_res["status"],
                "changed": sync_res.get("changed", False),
                "warning": sync_res.get("warning"),
            },
        )
        self._save_project(root, pdir, meta)
        self._write_automation_log(
            root,
            actor_info,
            "zotero.sync",
            {"project": meta["name"], "status": sync_res["status"], "changed": sync_res.get("changed", False)},
        )
        return wrap_response(sync_res, actor=actor_info)

    # ------------------------------------------------------------------
    # Manifest-Based Ingestion & Watch Folder (Requirement C & Section I4)
    # ------------------------------------------------------------------
    def apply_manifest(
        self,
        manifest: dict[str, Any],
        manifest_dir: Path | None = None,
        actor: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Apply a declarative manifest transactionally per item with a structured report."""
        if not isinstance(manifest, dict):
            raise SciTreeError(ERR_VALIDATION_ERROR, "Manifest must be a JSON object.")

        eff_dry_run = dry_run or bool(manifest.get("validate_only", False))
        manifest_actor_raw = manifest.get("actor") or {}
        if actor:
            actor_info = actor
        else:
            actor_info = validate_actor(
                actor_name=manifest_actor_raw.get("actor_name", "agent:manifest"),
                actor_type=manifest_actor_raw.get("actor_type", "agent"),
                actor_source="manifest",
                actor_id=manifest_actor_raw.get("actor_id"),
            )

        # Optional first-time root bootstrap directive inside manifest (Req C line 146)
        if manifest.get("root"):
            self.init_root(root_path=manifest["root"], actor=actor_info, dry_run=eff_dry_run)
            if eff_dry_run:
                self._explicit_root = Path(manifest["root"]).expanduser().resolve()
        elif manifest.get("auto_root"):
            self.init_root(auto_root=True, actor=actor_info, dry_run=eff_dry_run)
            if eff_dry_run:
                self._explicit_root = get_recommended_root_path().resolve()

        root = self.resolve_root()
        base_dir = manifest_dir or Path.cwd()

        created_items: list[dict[str, Any]] = []
        skipped_items: list[dict[str, Any]] = []
        failed_items: list[dict[str, Any]] = []

        proj_spec = manifest.get("project") or {}
        proj_name = (proj_spec.get("name") or "").strip()
        if not proj_name:
            raise SciTreeError(ERR_VALIDATION_ERROR, "Manifest must include 'project.name'.")

        tpl_name = manifest.get("template") or proj_spec.get("template")
        try:
            proj_res = self.create_project(
                name=proj_name,
                description=proj_spec.get("description", ""),
                column=proj_spec.get("column"),
                template_name=tpl_name,
                owner_type=proj_spec.get("owner_type"),
                owner_name=proj_spec.get("owner_name"),
                authors=proj_spec.get("authors"),
                actor=actor_info,
                dry_run=eff_dry_run,
            )
            if proj_res.get("created"):
                created_items.append({"type": "project", "name": proj_name})
            else:
                skipped_items.append({"type": "project", "name": proj_name, "reason": "already_exists"})
                if proj_spec.get("column") and not eff_dry_run:
                    self.move_project(
                        name=proj_name,
                        column=proj_spec["column"],
                        description=proj_spec.get("description"),
                        actor=actor_info,
                        dry_run=eff_dry_run,
                    )
        except SciTreeError as exc:
            failed_items.append({"type": "project", "name": proj_name, "error": exc.to_dict()})
            return wrap_response(
                {
                    "dry_run": eff_dry_run,
                    "project": proj_name,
                    "created": created_items,
                    "skipped": skipped_items,
                    "failed": failed_items,
                },
                actor=actor_info,
            )

        # Apply explicit template if project already existed and template is specified
        if tpl_name and skipped_items and not eff_dry_run:
            try:
                self.apply_template(proj_name, tpl_name, actor=actor_info, dry_run=eff_dry_run)
            except SciTreeError as exc:
                failed_items.append({"type": "template", "name": tpl_name, "error": exc.to_dict()})

        # Process versions
        for v_item in manifest.get("versions", []):
            vid = v_item.get("version_id")
            raw_file = v_item.get("file", "")
            resolved_file = (base_dir / raw_file).resolve() if not Path(raw_file).is_absolute() else Path(raw_file)
            try:
                v_res = self.add_version(
                    project_name=proj_name,
                    file_path=resolved_file,
                    author=v_item.get("author", actor_info["actor_name"]),
                    version_id=vid,
                    changelog=v_item.get("changelog", ""),
                    state=v_item.get("state", "draft"),
                    derived_from=v_item.get("derived_from"),
                    submitted_to=v_item.get("submitted_to"),
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                if v_res.get("created"):
                    created_items.append({"type": "version", "version_id": v_res["version"]["version_id"]})
                else:
                    skipped_items.append(
                        {"type": "version", "version_id": v_res["version"]["version_id"], "reason": "idempotent"}
                    )
            except SciTreeError as exc:
                failed_items.append({"type": "version", "version_id": vid, "error": exc.to_dict()})

        # Process files
        for f_item in manifest.get("files", []):
            raw_file = f_item.get("file", "")
            resolved_file = (base_dir / raw_file).resolve() if not Path(raw_file).is_absolute() else Path(raw_file)
            try:
                f_res = self.add_file(
                    project_name=proj_name,
                    file_path=resolved_file,
                    kind=f_item.get("kind", "data"),
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                if f_res.get("created"):
                    created_items.append({"type": "file", "path": f_res["file"]["path"]})
                else:
                    skipped_items.append({"type": "file", "path": f_res["file"]["path"], "reason": "idempotent"})
            except SciTreeError as exc:
                failed_items.append({"type": "file", "file": raw_file, "error": exc.to_dict()})

        # Process comments
        for c_item in manifest.get("comments", []):
            try:
                c_res = self.add_comment(
                    project_name=proj_name,
                    text=c_item.get("text", ""),
                    version=c_item.get("version"),
                    owner_type=c_item.get("owner_type"),
                    owner_name=c_item.get("owner_name"),
                    comment_id=c_item.get("comment_id") or c_item.get("id"),
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                if c_res.get("created"):
                    created_items.append({"type": "comment", "comment_id": c_res["comment"]["comment_id"]})
                else:
                    skipped_items.append(
                        {"type": "comment", "comment_id": c_res["comment"]["comment_id"], "reason": "idempotent"}
                    )
            except SciTreeError as exc:
                failed_items.append({"type": "comment", "text": c_item.get("text"), "error": exc.to_dict()})

        # Process risks
        for r_item in manifest.get("risks", []):
            try:
                r_res = self.add_risk(
                    project_name=proj_name,
                    title=r_item.get("title", ""),
                    description=r_item.get("description", ""),
                    severity=r_item.get("severity", "medium"),
                    likelihood=r_item.get("likelihood", "medium"),
                    owner=r_item.get("owner", ""),
                    status=r_item.get("status", "open"),
                    trigger=r_item.get("trigger", ""),
                    mitigation=r_item.get("mitigation", ""),
                    risk_id=r_item.get("risk_id") or r_item.get("id"),
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                if r_res.get("created"):
                    created_items.append({"type": "risk", "risk_id": r_res["risk"]["risk_id"]})
                else:
                    skipped_items.append({"type": "risk", "risk_id": r_res["risk"]["risk_id"], "reason": "idempotent"})
            except SciTreeError as exc:
                failed_items.append({"type": "risk", "title": r_item.get("title"), "error": exc.to_dict()})

        # Process milestones
        for m_item in manifest.get("milestones", []):
            try:
                m_res = self.add_milestone(
                    project_name=proj_name,
                    title=m_item.get("title", ""),
                    phase=m_item.get("phase", "short_term_7d"),
                    description=m_item.get("description", ""),
                    due_date=m_item.get("due_date"),
                    status=m_item.get("status", "pending"),
                    milestone_id=m_item.get("milestone_id") or m_item.get("id"),
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                if m_res.get("created"):
                    created_items.append({"type": "milestone", "milestone_id": m_res["milestone"]["milestone_id"]})
                else:
                    skipped_items.append(
                        {"type": "milestone", "milestone_id": m_res["milestone"]["milestone_id"], "reason": "idempotent"}
                    )
            except SciTreeError as exc:
                failed_items.append({"type": "milestone", "title": m_item.get("title"), "error": exc.to_dict()})

        # Process zotero_link
        z_spec = manifest.get("zotero_link")
        if isinstance(z_spec, dict) and z_spec.get("collection_key"):
            try:
                self.zotero_link(
                    project_name=proj_name,
                    collection_key=z_spec["collection_key"],
                    collection_name=z_spec.get("collection_name"),
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                created_items.append({"type": "zotero_link", "collection_key": z_spec["collection_key"]})
                if z_spec.get("sync_on_apply"):
                    self.zotero_sync(project_name=proj_name, strict=False, actor=actor_info, dry_run=eff_dry_run)
            except SciTreeError as exc:
                failed_items.append({"type": "zotero_link", "error": exc.to_dict()})

        # Process activity_notes
        for note_item in manifest.get("activity_notes", []):
            note_text = note_item.get("note") if isinstance(note_item, dict) else str(note_item)
            try:
                self.add_timeline_note(
                    project_name=proj_name,
                    note=note_text or "",
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                created_items.append({"type": "activity_note", "note": note_text})
            except SciTreeError as exc:
                failed_items.append({"type": "activity_note", "error": exc.to_dict()})

        # Process optional export directive
        exp_spec = manifest.get("export")
        if exp_spec:
            exp_ver = exp_spec.get("version") if isinstance(exp_spec, dict) else None
            try:
                exp_res = self.export_package(
                    project_name=proj_name,
                    version_id=exp_ver,
                    actor=actor_info,
                    dry_run=eff_dry_run,
                )
                created_items.append(
                    {"type": "export", "path": exp_res.get("export", {}).get("path", "dry_run")}
                )
            except SciTreeError as exc:
                failed_items.append({"type": "export", "error": exc.to_dict()})

        report = {
            "dry_run": eff_dry_run,
            "project": proj_name,
            "summary": {
                "created_count": len(created_items),
                "skipped_count": len(skipped_items),
                "failed_count": len(failed_items),
            },
            "created": created_items,
            "skipped": skipped_items,
            "failed": failed_items,
        }
        if not eff_dry_run:
            self._write_automation_log(root, actor_info, "manifest.apply", report["summary"])
        return wrap_response(report, actor=actor_info)

    def process_inbox_once(self) -> dict[str, Any]:
        """Scan <root>/Automation/inbox/*.json, apply each manifest, and write result to outbox."""
        root = self.resolve_root()
        inbox_dir = root / "Automation" / "inbox"
        processed_dir = inbox_dir / "processed"
        outbox_dir = root / "Automation" / "outbox"
        processed_dir.mkdir(parents=True, exist_ok=True)
        outbox_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        for mfile in sorted(inbox_dir.glob("*.json")):
            if not mfile.is_file():
                continue
            try:
                manifest_data = json.loads(mfile.read_text(encoding="utf-8"))
                res = self.apply_manifest(manifest_data, manifest_dir=mfile.parent)
            except SciTreeError as exc:
                res = exc.to_dict()
            except Exception as exc:
                res = {
                    "schema_version": SCHEMA_VERSION,
                    "error": ERR_VALIDATION_ERROR,
                    "message": f"Failed to parse or apply inbox manifest '{mfile.name}': {exc}",
                    "details": {"file": mfile.name},
                }

            out_file = outbox_dir / f"{mfile.name}.result.json"
            out_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
            shutil.move(str(mfile), str(processed_dir / mfile.name))
            results.append({"manifest_file": mfile.name, "result_file": str(out_file), "result": res})

        return wrap_response({"processed_count": len(results), "results": results})
