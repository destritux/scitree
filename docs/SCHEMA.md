# sciTree Data Model, Folder Structure, and Automation Schema Reference

All JSON payloads across the CLI (`--json`), Local HTTP API, MCP Server, and Manifest processor share a single `schema_version` (`"1.0"`) and are produced by `scitree.core.SciTreeCore`.

---

## 1. Workspace Folder Structure and Data Model

```text
<root>/
  scitree.db                       # SQLite index/cache (rebuildable from filesystem)
  Projects/
    <ProjectFolder>/
      metadata.json                # Primary source of truth for project state
      activity_log.jsonl           # Append-only per-project mutation event stream
      Versions/
        v1/
          manuscript.docx
        v2/
          manuscript.pdf
      Figures_Text/
        v1/
          fig_001_image1.png
        v2/
          page_01_img_01.png
      Figures_Standalone/
        conceptual_model.png
      Data/
        raw_sleep_2025_q1.csv
      References/
        v1.bib
        v2.bib
        references_extracted.bib
        references_zotero.bib
      Automation/
        extraction_v1.log
  Templates/
    Default.json
    Empirical_Paper.json
    Review_Article.json
    Grant_Proposal.json
  Automation/
    inbox/                         # Drop .json manifests here for automatic processing
      processed/                   # Archived manifests after processing
    outbox/                        # <manifest>.result.json reports
    logs/
      operations.jsonl             # Global audit log of all operations
  Exports/
    Alpha_Study_v2_submission.zip  # Reproducible submission packages
```

### Source of Truth vs. SQLite Index
- Each project directory contains `metadata.json` and `activity_log.jsonl`, which together represent the authoritative state on disk.
- `<root>/scitree.db` contains 9 tables (`projects`, `versions`, `files`, `comments`, `risks`, `milestones`, `activity_log`, `templates`, `settings`) and acts as a fast query/cache layer.
- Running `scitree db rebuild` reconstructs `scitree.db` completely from `<root>/Projects/*/metadata.json`, `<root>/Projects/*/activity_log.jsonl`, and `<root>/Templates/*.json`.

---

## 2. Standard Response and Error Envelopes

### Success Envelope
Every operation returns a JSON object containing `"schema_version": "1.0"`, the normalized `"actor"` attribution (for mutations), and operation-specific keys:

```json
{
  "schema_version": "1.0",
  "actor": {
    "actor_name": "agent:claude",
    "actor_type": "agent",
    "actor_source": "cli"
  },
  "created": true,
  "project": { ... }
}
```

### Error Envelope
All failures across CLI (`--json`), HTTP API, MCP tools, and manifest items return:

```json
{
  "schema_version": "1.0",
  "error": "VERSION_IMMUTABLE",
  "message": "Version 'v2' is immutable (submitted) and cannot be modified. Create a new derived version 'v3' with derived_from='v2'.",
  "details": {
    "version_id": "v2",
    "current_state": "submitted",
    "suggested_derived_version": "v3",
    "derived_from": "v2"
  }
}
```

### Stable Error Codes and CLI Exit Codes

| Error Code | HTTP Status | CLI Exit Code | Description |
| :--- | :---: | :---: | :--- |
| `ROOT_NOT_CONFIGURED` | 412 | 3 | No root directory initialized and neither `--root` nor `--auto-root` was supplied. |
| `VALIDATION_ERROR` | 400 | 2 | Invalid field value, state, severity, or missing required input. |
| `FILE_NOT_FOUND` | 400 | 2 | Referenced input file or manifest does not exist on disk. |
| `ACTOR_REQUIRED` | 400 | 6 | Mutation marked with `actor_type="agent"` omitted `actor_name`. |
| `UNAUTHORIZED` | 401 | 8 | Non-loopback HTTP request missing valid `Bearer <api_token>` header. |
| `PROJECT_NOT_FOUND` | 404 | 4 | Target project name, slug, or ID does not exist. |
| `VERSION_NOT_FOUND` | 404 | 4 | Target `version_id` does not exist on the project. |
| `COMMENT_NOT_FOUND` | 404 | 4 | Target `comment_id` does not exist on the project. |
| `RISK_NOT_FOUND` | 404 | 4 | Target `risk_id` does not exist on the project. |
| `MILESTONE_NOT_FOUND` | 404 | 4 | Target `milestone_id` does not exist on the project. |
| `TEMPLATE_NOT_FOUND` | 404 | 4 | Requested project template does not exist in `<root>/Templates/`. |
| `VERSION_CONFLICT` | 409 | 5 | Same `version_id` uploaded with different file checksum; includes `suggested_version_id` (e.g. `v2a`). |
| `VERSION_IMMUTABLE` | 409 | 5 | Attempted modification or deletion of a `submitted` or `published` version. |
| `EXPORT_FAILED` | 500 | 7 | Submission package archive creation failed. |
| `ZOTERO_UNAVAILABLE` | 503 | 7 | Local Zotero API unreachable or project not linked to a collection. |

---

## 3. Declarative Manifest JSON Schema (`scitree apply` / `POST /apply`)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "sciTreeManifest",
  "type": "object",
  "required": ["project"],
  "properties": {
    "schema_version": { "type": "string", "default": "1.0" },
    "root": { "type": "string", "description": "Optional explicit root directory path for bootstrap." },
    "auto_root": { "type": "boolean", "description": "Auto-initialize OS default root if unconfigured." },
    "validate_only": { "type": "boolean", "default": false },
    "actor": {
      "type": "object",
      "properties": {
        "actor_id": { "type": "string" },
        "actor_name": { "type": "string" },
        "actor_type": { "enum": ["human", "agent"] },
        "actor_source": { "enum": ["ui", "cli", "http", "mcp", "manifest"] }
      }
    },
    "template": { "type": "string" },
    "project": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": { "type": "string" },
        "description": { "type": "string" },
        "column": { "type": "string" },
        "template": { "type": "string" },
        "owner_type": { "enum": ["human", "agent"] },
        "owner_name": { "type": "string" },
        "authors": { "type": "array", "items": { "type": "object" } }
      }
    },
    "versions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file", "author"],
        "properties": {
          "version_id": { "type": "string" },
          "file": { "type": "string" },
          "author": { "type": "string" },
          "changelog": { "type": "string" },
          "state": { "enum": ["draft", "submitted", "published", "revision"] },
          "derived_from": { "type": "string" },
          "submitted_to": { "type": "string" }
        }
      }
    },
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["kind", "file"],
        "properties": {
          "kind": { "enum": ["data", "figure", "manuscript"] },
          "file": { "type": "string" }
        }
      }
    },
    "comments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["text"],
        "properties": {
          "comment_id": { "type": "string" },
          "text": { "type": "string" },
          "version": { "type": "string" },
          "owner_type": { "enum": ["human", "agent"] },
          "owner_name": { "type": "string" }
        }
      }
    },
    "risks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title"],
        "properties": {
          "risk_id": { "type": "string" },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "severity": { "enum": ["low", "medium", "high", "critical"] },
          "likelihood": { "enum": ["low", "medium", "high"] },
          "owner": { "type": "string" },
          "status": { "enum": ["open", "mitigating", "closed"] },
          "trigger": { "type": "string" },
          "mitigation": { "type": "string" }
        }
      }
    },
    "milestones": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title"],
        "properties": {
          "milestone_id": { "type": "string" },
          "title": { "type": "string" },
          "description": { "type": "string" },
          "phase": {
            "enum": ["short_term_7d", "medium_term_30d", "submission_ready", "revision_ready", "custom"]
          },
          "due_date": { "type": "string" },
          "status": { "enum": ["pending", "in_progress", "done", "missed"] }
        }
      }
    },
    "zotero_link": {
      "type": "object",
      "properties": {
        "collection_key": { "type": "string" },
        "collection_name": { "type": "string" },
        "sync_on_apply": { "type": "boolean" }
      }
    },
    "activity_notes": {
      "type": "array",
      "items": {
        "oneOf": [
          { "type": "string" },
          { "type": "object", "properties": { "note": { "type": "string" } } }
        ]
      }
    },
    "export": {
      "type": "object",
      "properties": { "version": { "type": "string" } }
    }
  }
}
```

---

## 4. Local HTTP API Endpoints (`127.0.0.1:8765`)

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/status` | Inspect onboarding state, active root folder, and recommended OS path. |
| `POST` | `/init` | Initialize root (`{"root": "..."}` or `{"auto_root": true}`) or reset (`{"reset": true}`). |
| `POST` | `/projects` | Create project idempotently (`name`, `description`, `column`, `template`). |
| `GET` | `/projects` | List projects with filters (`column`, `owner_type`, `has_pending_comments`, `author`, `search`, `sort_by`). |
| `GET` | `/projects/{name}` | Retrieve full project metadata. |
| `PATCH` | `/projects/{name}` | Move project between Kanban columns or update metadata. |
| `POST` | `/projects/{name}/versions` | Upload DOCX/PDF manuscript version and trigger automated extraction. |
| `GET` | `/projects/{name}/versions` | List project versions and lock status. |
| `PATCH` | `/projects/{name}/versions/{version_id}` | Promote version to `submitted`/`published` (locks version) or archive it. |
| `POST` | `/projects/{name}/files` | Upload `data`, `figure`, or `manuscript` file. |
| `POST` | `/projects/{name}/comments` | Add a comment card. |
| `PATCH` | `/projects/{name}/comments/{comment_id}` | Resolve (`{"status": "resolved"}`) or reopen (`{"status": "pending"}`) a comment. |
| `GET` | `/projects/{name}/comments` | List comments with optional `status`, `owner_type`, and `version` filters. |
| `POST` | `/projects/{name}/risks` | Create a risk item. |
| `GET` | `/projects/{name}/risks` | List project risks. |
| `PATCH` | `/projects/{name}/risks/{risk_id}` | Update or close a risk item. |
| `POST` | `/projects/{name}/milestones` | Create a milestone item. |
| `GET` | `/projects/{name}/milestones` | List project milestones ordered by phase and due date. |
| `PATCH` | `/projects/{name}/milestones/{milestone_id}` | Update or mark a milestone done. |
| `GET` | `/projects/{name}/timeline` | Retrieve chronological Timeline / Route View grouped by day. |
| `POST` | `/projects/{name}/timeline/notes` | Add a manual note event to the project timeline. |
| `GET` | `/projects/{name}/activity` | Query the append-only Activity Log (`actor_type`, `actor_source`, `event_type`, `date_from`, `date_to`). |
| `POST` | `/projects/{name}/export` | Generate a reproducible `.zip` submission package. |
| `POST` | `/projects/{name}/template` | Apply a template to an existing project (additive only). |
| `POST` | `/projects/{name}/zotero/link` | Link a Zotero collection key. |
| `POST` | `/projects/{name}/zotero/sync` | Synchronize linked Zotero collection into `References/references_zotero.bib`. |
| `POST` | `/projects/{name}/zotero/unlink` | Unlink Zotero collection. |
| `GET` | `/templates` | List built-in and custom templates. |
| `POST` | `/templates` | Save a custom template from an existing project. |
| `POST` | `/apply` | Apply a declarative manifest JSON payload. |
| `POST` | `/inbox/process` | Process all `.json` manifests waiting in `<root>/Automation/inbox/`. |

---

## 5. MCP Server Tools (`scitree-mcp`)

The MCP server exposes 31 tools with identical JSON outputs to the CLI and HTTP API:
- Root: `init_root`
- Projects: `create_project`, `list_projects`, `get_project`, `move_project`
- Versions: `add_version`, `list_versions`, `update_version_state`
- Files: `add_file`
- Comments: `add_comment`, `resolve_comment`, `list_comments`
- Risks: `add_risk`, `list_risks`, `update_risk`, `close_risk`
- Milestones: `add_milestone`, `list_milestones`, `update_milestone`, `close_milestone`
- Timeline & Activity: `add_timeline_note`, `get_timeline`, `list_activity`
- Export: `export_package`
- Templates: `list_templates`, `save_template`, `template_apply`
- Zotero: `zotero_link`, `zotero_sync`, `zotero_unlink`
- Manifest: `apply_manifest`

---

## 6. Notes on DOCX and PDF Extraction Limitations

1. **Embedded Figures**:
   - **DOCX**: Extracts all raster and vector media files stored inside `word/media/*` in the OpenXML archive. Shapes drawn purely with Word DrawingML primitives (`w:drawing` vector shapes without a backing media blob) are not rasterized by `zipfile` extraction.
   - **PDF**: Extracts embedded raster XObject images per page via `PyMuPDF` (`page.get_images(full=True)`). Pure vector PDF diagrams drawn directly as content-stream paths without an image XObject are not exported as separate raster files.
2. **Comments Extraction**:
   - **Inline Markers**: Both DOCX and PDF text streams support `[COMMENT: ...]` and attributed `[COMMENT(agent:claude): ...]` markers.
   - **DOCX Native Comments**: Extracted from `word/comments.xml` with `w:author` attribution. Tracked changes (`w:ins` / `w:del` revisions) are not treated as comment cards.
   - **PDF Annotations**: Extracted from standard PDF page annotations (`page.first_annot`). Flattened text boxes baked into page content streams cannot be distinguished from body text unless formatted with `[COMMENT: ...]`.
3. **Bibliography Detection and Parsing**:
   - Section detection searches for standalone headings matching `References`, `Bibliography`, `Works Cited`, or `Literature Cited`. Manuscripts lacking an explicit heading will log a warning in `Automation/extraction_v{n}.log` and produce an empty `.bib` file.
   - Reference strings formatted in APA, Vancouver, or numbered styles are heuristically split into `author`, `year`, `title`, `journal`, and full raw citation (`note`). If raw BibTeX entries (`@article{...}`) are present in the references section, they are parsed directly via `bibtexparser`.
