"""SQLite index/cache database layer for sciTree (Requirement 2 & Section I2).

The filesystem (<root>/Projects/<Project>/metadata.json and activity_log.jsonl)
is the primary source of truth. This SQLite database indexes all entities and
can be rebuilt at any time from the filesystem.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scitree.models import utc_now_iso

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT,
    columns_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    slug TEXT NOT NULL,
    folder_name TEXT NOT NULL,
    description TEXT,
    column_name TEXT NOT NULL,
    column_order_json TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    template_name TEXT,
    latest_version_id TEXT,
    latest_version_locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    version_id TEXT NOT NULL,
    state TEXT NOT NULL,
    immutable INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    derived_from TEXT,
    author TEXT NOT NULL,
    changelog TEXT,
    manuscript_path TEXT,
    figures_dir TEXT,
    bib_path TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(project_id, version_id)
);

CREATE TABLE IF NOT EXISTS files (
    file_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (project_id, file_id)
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    version TEXT,
    text TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (project_id, comment_id)
);

CREATE TABLE IF NOT EXISTS risks (
    risk_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL,
    likelihood TEXT NOT NULL,
    owner TEXT,
    status TEXT NOT NULL,
    trigger_text TEXT,
    mitigation TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (project_id, risk_id)
);

CREATE TABLE IF NOT EXISTS milestones (
    milestone_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    phase TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (project_id, milestone_id)
);

CREATE TABLE IF NOT EXISTS activity_log (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    actor_id TEXT,
    actor_name TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


class SciTreeDatabase:
    """Manages the SQLite cache/index database located at <root>/scitree.db."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def set_setting(self, key: str, value: Any) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )
            conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return row["value"]

    def sync_template(self, template: dict[str, Any]) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO templates (name, version, description, columns_json, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    version=excluded.version,
                    description=excluded.description,
                    columns_json=excluded.columns_json,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    template.get("name", ""),
                    template.get("version", "1.0"),
                    template.get("description", ""),
                    json.dumps(template.get("columns", [])),
                    json.dumps(template),
                    now,
                ),
            )
            conn.commit()

    def sync_project(
        self,
        folder_name: str,
        metadata: dict[str, Any],
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert a project and all its child entities into the SQLite index."""
        project_id = metadata["project_id"]
        project_name = metadata["name"]
        status = metadata.get("status", {})
        tpl_info = metadata.get("template") or {}

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    project_id, name, slug, folder_name, description,
                    column_name, column_order_json, owner_type, owner_name,
                    template_name, latest_version_id, latest_version_locked,
                    created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name=excluded.name,
                    slug=excluded.slug,
                    folder_name=excluded.folder_name,
                    description=excluded.description,
                    column_name=excluded.column_name,
                    column_order_json=excluded.column_order_json,
                    owner_type=excluded.owner_type,
                    owner_name=excluded.owner_name,
                    template_name=excluded.template_name,
                    latest_version_id=excluded.latest_version_id,
                    latest_version_locked=excluded.latest_version_locked,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    project_id,
                    project_name,
                    metadata.get("slug", ""),
                    folder_name,
                    metadata.get("description", ""),
                    status.get("column", "Idea"),
                    json.dumps(status.get("column_order", [])),
                    status.get("owner_type", "human"),
                    status.get("owner_name", "local-user"),
                    tpl_info.get("name"),
                    metadata.get("latest_version_id"),
                    1 if metadata.get("latest_version_locked") else 0,
                    metadata.get("created_at", utc_now_iso()),
                    metadata.get("updated_at", utc_now_iso()),
                    json.dumps(metadata),
                ),
            )

            # Replace child index rows for this project
            conn.execute("DELETE FROM versions WHERE project_id = ?", (project_id,))
            for ver in metadata.get("versions", []):
                vid = ver["version_id"]
                files_info = ver.get("files", {})
                conn.execute(
                    """
                    INSERT INTO versions (
                        id, project_id, project_name, version_id, state,
                        immutable, archived, derived_from, author, changelog,
                        manuscript_path, figures_dir, bib_path, created_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{project_id}:{vid}",
                        project_id,
                        project_name,
                        vid,
                        ver.get("state", "draft"),
                        1 if ver.get("immutable") else 0,
                        1 if ver.get("archived") else 0,
                        ver.get("derived_from"),
                        ver.get("author", ""),
                        ver.get("changelog", ""),
                        files_info.get("manuscript"),
                        files_info.get("figures_dir"),
                        files_info.get("bib"),
                        ver.get("created_at", utc_now_iso()),
                        json.dumps(ver),
                    ),
                )

            conn.execute("DELETE FROM files WHERE project_id = ?", (project_id,))
            files_group = metadata.get("files", {})
            for kind_key, kind_label in [
                ("data", "data"),
                ("figures_standalone", "figure"),
                ("manuscripts", "manuscript"),
            ]:
                for fitem in files_group.get(kind_key, []):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO files (
                            file_id, project_id, project_name, kind, path,
                            size_bytes, added_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fitem["file_id"],
                            project_id,
                            project_name,
                            kind_label,
                            fitem.get("path", ""),
                            int(fitem.get("size_bytes", 0)),
                            fitem.get("added_at", utc_now_iso()),
                            json.dumps(fitem),
                        ),
                    )

            conn.execute("DELETE FROM comments WHERE project_id = ?", (project_id,))
            for cmt in metadata.get("comments", []):
                conn.execute(
                    """
                    INSERT INTO comments (
                        comment_id, project_id, project_name, version, text,
                        owner_type, owner_name, status, source, created_at,
                        resolved_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cmt["comment_id"],
                        project_id,
                        project_name,
                        cmt.get("version"),
                        cmt.get("text", ""),
                        cmt.get("owner_type", "human"),
                        cmt.get("owner_name", "unassigned"),
                        cmt.get("status", "pending"),
                        cmt.get("source", "manual"),
                        cmt.get("created_at", utc_now_iso()),
                        cmt.get("resolved_at"),
                        json.dumps(cmt),
                    ),
                )

            conn.execute("DELETE FROM risks WHERE project_id = ?", (project_id,))
            for rsk in metadata.get("risks", []):
                conn.execute(
                    """
                    INSERT INTO risks (
                        risk_id, project_id, project_name, title, description,
                        severity, likelihood, owner, status, trigger_text,
                        mitigation, created_at, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rsk["risk_id"],
                        project_id,
                        project_name,
                        rsk.get("title", ""),
                        rsk.get("description", ""),
                        rsk.get("severity", "medium"),
                        rsk.get("likelihood", "medium"),
                        rsk.get("owner", ""),
                        rsk.get("status", "open"),
                        rsk.get("trigger", ""),
                        rsk.get("mitigation", ""),
                        rsk.get("created_at", utc_now_iso()),
                        rsk.get("updated_at", utc_now_iso()),
                        json.dumps(rsk),
                    ),
                )

            conn.execute("DELETE FROM milestones WHERE project_id = ?", (project_id,))
            for ms in metadata.get("milestones", []):
                conn.execute(
                    """
                    INSERT INTO milestones (
                        milestone_id, project_id, project_name, title, description,
                        phase, due_date, status, created_at, updated_at,
                        completed_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ms["milestone_id"],
                        project_id,
                        project_name,
                        ms.get("title", ""),
                        ms.get("description", ""),
                        ms.get("phase", "custom"),
                        ms.get("due_date"),
                        ms.get("status", "pending"),
                        ms.get("created_at", utc_now_iso()),
                        ms.get("updated_at", utc_now_iso()),
                        ms.get("completed_at"),
                        json.dumps(ms),
                    ),
                )

            if events is not None:
                conn.execute("DELETE FROM activity_log WHERE project_id = ?", (project_id,))
                for ev in events:
                    actor = ev.get("actor", {})
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO activity_log (
                            event_id, project_id, project_name, timestamp,
                            actor_id, actor_name, actor_type, actor_source,
                            event_type, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ev["event_id"],
                            project_id,
                            project_name,
                            ev.get("timestamp", utc_now_iso()),
                            actor.get("actor_id"),
                            actor.get("actor_name", "local-user"),
                            actor.get("actor_type", "human"),
                            actor.get("actor_source", "cli"),
                            ev.get("event_type", "note.added"),
                            json.dumps(ev),
                        ),
                    )
            conn.commit()

    def append_activity_event(self, project_id: str, project_name: str, ev: dict[str, Any]) -> None:
        actor = ev.get("actor", {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO activity_log (
                    event_id, project_id, project_name, timestamp,
                    actor_id, actor_name, actor_type, actor_source,
                    event_type, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev["event_id"],
                    project_id,
                    project_name,
                    ev.get("timestamp", utc_now_iso()),
                    actor.get("actor_id"),
                    actor.get("actor_name", "local-user"),
                    actor.get("actor_type", "human"),
                    actor.get("actor_source", "cli"),
                    ev.get("event_type", "note.added"),
                    json.dumps(ev),
                ),
            )
            conn.commit()

    def rebuild_from_filesystem(self, root_path: Path) -> dict[str, int]:
        """Rebuild the entire SQLite database from <root>/Projects and <root>/Templates."""
        with self._connect() as conn:
            for tbl in [
                "projects",
                "versions",
                "files",
                "comments",
                "risks",
                "milestones",
                "activity_log",
                "templates",
            ]:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()

        templates_count = 0
        templates_dir = root_path / "Templates"
        if templates_dir.exists():
            for tpl_file in sorted(templates_dir.glob("*.json")):
                try:
                    tpl = json.loads(tpl_file.read_text(encoding="utf-8"))
                    if isinstance(tpl, dict) and tpl.get("name"):
                        self.sync_template(tpl)
                        templates_count += 1
                except (OSError, json.JSONDecodeError):
                    continue

        projects_count = 0
        # Support both <root>/Projects/<ProjectName> and direct <root>/<ProjectName>
        candidate_dirs: list[Path] = []
        projects_dir = root_path / "Projects"
        if projects_dir.exists():
            candidate_dirs.extend([d for d in sorted(projects_dir.iterdir()) if d.is_dir()])
        for d in sorted(root_path.iterdir()):
            if d.is_dir() and d.name not in {"Projects", "Templates", "Automation", "Exports"}:
                if (d / "metadata.json").exists():
                    candidate_dirs.append(d)

        seen_ids: set[str] = set()
        for pdir in candidate_dirs:
            meta_file = pdir / "metadata.json"
            if not meta_file.exists():
                continue
            try:
                metadata = json.loads(meta_file.read_text(encoding="utf-8"))
                pid = metadata.get("project_id")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                events: list[dict[str, Any]] = []
                log_file = pdir / "activity_log.jsonl"
                if log_file.exists():
                    for line in log_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ev = json.loads(line)
                            if isinstance(ev, dict) and ev.get("event_id"):
                                events.append(ev)
                        except json.JSONDecodeError:
                            continue
                self.sync_project(pdir.name, metadata, events)
                projects_count += 1
            except (OSError, json.JSONDecodeError):
                continue

        return {"projects_indexed": projects_count, "templates_indexed": templates_count}
