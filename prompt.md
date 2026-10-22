Role:
You are a senior desktop application developer with expertise in Python, modern UI frameworks, document parsing, local-first scientific workflow tools, and automation/agent interfaces.

Task:
Create a new desktop application from scratch named "sciTree". Before implementation, do a quick name-collision check; if "sciTree" is already used by a directly competing scientific project management tool, flag it and propose alternatives before coding. Otherwise, proceed with the name sciTree.

General Vision:
Build a minimalist, modern, and functional Kanban-style desktop application for managing scientific projects and manuscripts. The application must be local-first and offline. The entire UI, all code identifiers, comments, documentation, and user-facing strings must be in English.

A core design goal is that every user-facing action must also be executable programmatically by an automated agent. The app must expose a first-class, stable automation surface so an AI agent or script can create projects, define versions, register authors, attach files, and update statuses without touching the UI.

Core Functional Requirements:

1. First-Run Setup
- On the first launch only, prompt the user to choose a root folder where all projects and data will be stored.
- Do not persist this choice as a long-term user-editable preference. Persist only the minimal state required to avoid asking again: an onboarding-completed marker and the effective root path currently in use.
- If the user skips the folder selection, automatically choose the best default location for the operating system, create it if missing, and use it. Show a non-blocking notice explaining where files will be stored.
- Default best locations:
  - Windows: %USERPROFILE%\Documents\sciTree
  - macOS: ~/Documents/sciTree
  - Linux: $XDG_DATA_HOME/scitree if set, otherwise ~/.local/share/scitree, falling back to ~/Documents/sciTree
- Provide a way to reset onboarding and choose a different root later through settings and CLI.
- Automation must never silently fail due to missing root configuration. Automation commands may accept an explicit --root. If no root is configured and onboarding is incomplete, automation must either require --root or auto-initialize the default best location when invoked with --auto-root.

2. Project / Article Creation
- Allow the user to create a new "Project", representing a scientific manuscript or research article.
- Each project must create its own dedicated subfolder inside the root folder, organized so a human can browse it directly. Suggested structure:
  /ProjectName/
    Versions/
    Figures_Text/
    Figures_Standalone/
    Data/
    References/
    Automation/      (logs, manifests, ingested files)
- Store project metadata in a local SQLite database.
- Project creation must be idempotent: creating the same project twice returns the existing one without duplicating folders.

3. Kanban Board (Trello-style)
- Implement a Kanban board with columns representing the manuscript lifecycle, e.g.:
  Idea, Writing, Review, Submitted, Published.
- Support smooth drag-and-drop of project cards between columns.
- Each card must display:
  - Project title
  - Latest version number
  - Author(s) who submitted the latest version
  - Number of pending comments, if any
- The latest version must be visually obvious.

4. Simplified Visual Version Control
- Allow the user to upload a new version of the manuscript text as DOCX or PDF.
- When a new version is uploaded, record:
  - Version number, e.g. v1, v2, v3
  - Author name who submitted it
  - Upload timestamp
  - Optional changelog note
- Provide a simple visual timeline or version list per project.
- Clearly highlight the latest version.
- If two versions with the same number are uploaded, warn the user and suggest a suffix such as v2a, v2b.
- Version creation must be idempotent when a client supplies an explicit version_id; re-submitting the same version_id with identical content returns success without duplicating data.

5. File Upload and Management
- Support uploading data files such as Excel and CSV into the project's Data folder.
- Support uploading standalone figures into Figures_Standalone.
- Support uploading manuscript files into Versions.
- Keep the folder structure human-readable and organized.

6. Automated Text Extraction and Organization
When a DOCX or PDF manuscript is uploaded:
- Extract all embedded images and save them into:
  /ProjectName/Figures_Text/v{version_number}/
- Extract the bibliography/references section from the text.
- Parse the references into a standard bibliography format and save them as a .bib file inside:
  /ProjectName/References/
- Save extraction logs or warnings if parsing partially fails.

7. Comment Cards from Text
- Scan uploaded manuscripts for inline comments. Support at least:
  - Standard Word comments, when available
  - Explicit markers such as [COMMENT: ...]
- Automatically create Kanban cards or comment cards for each extracted comment.
- Each comment card must have a selectable checkbox to mark it as Done / Resolved.
- Show pending comments per project.

Automation and Agent Interface (Critical Requirement):
The app must expose a stable, documented, and machine-friendly interface for automated agents. The UI is a client of the same underlying operations; no feature may exist only in the UI.

Required automation surfaces:

A. Local CLI ("scitree")
- Provide a command-line tool installed alongside the app, usable without opening the UI.
- Must support at minimum:
  - scitree init --root <path>
  - scitree init --auto-root
  - scitree project create --name "<name>" [--description "<text>"] [--column "<col>"]
  - scitree project list [--json]
  - scitree project show --name "<name>" [--json]
  - scitree project move --name "<name>" --column "<col>"
  - scitree version add --project "<name>" --file "<path>" --author "<name>" [--version-id "<id>"] [--changelog "<text>"]
  - scitree version list --project "<name>" [--json]
  - scitree file add --project "<name>" --file "<path>" --kind data|figure|manuscript
  - scitree comment add --project "<name>" --text "<text>" [--version "<id>"]
  - scitree comment resolve --project "<name>" --comment-id "<id>"
  - scitree comment list --project "<name>" [--json] [--status pending|resolved]
- Every command must support --json for structured output and --dry-run for validation without side effects.
- Exit codes must be stable and documented.
- If no root is configured, commands must fail with a clear error unless --root or --auto-root is provided.

B. Local HTTP API
- Start an optional local HTTP server (loopback only, e.g. 127.0.0.1:8765) that mirrors the CLI operations with REST endpoints:
  - POST /projects
  - GET  /projects
  - GET  /projects/{name}
  - PATCH /projects/{name}          (e.g. change column)
  - POST /projects/{name}/versions
  - GET  /projects/{name}/versions
  - POST /projects/{name}/files
  - POST /projects/{name}/comments
  - PATCH /projects/{name}/comments/{id}
  - GET  /projects/{name}/comments
  - POST /init                      (choose root or auto-root)
- Bind to loopback only by default. Require a token stored in the app settings for non-loopback access.
- All endpoints must be idempotent where applicable and return the same schema as the CLI --json output.
- If no root is configured, endpoints except /init must return a clear, machine-readable error.

C. Manifest-Based Ingestion
- Support a declarative JSON manifest format that an agent can write and submit, e.g.:
  {
    "project": { "name": "Alpha Study", "description": "...", "column": "Writing" },
    "versions": [
      { "version_id": "v1", "file": "path/to/manuscript_v1.docx",
        "author": "Jane Doe", "changelog": "First draft" }
    ],
    "files": [
      { "kind": "data", "file": "path/to/data.xlsx" },
      { "kind": "figure", "file": "path/to/figure1.png" }
    ],
    "comments": [
      { "text": "Fix intro citation", "version": "v1" }
    ]
  }
- Accept manifests via:
  - CLI: scitree apply --manifest <path>
  - HTTP: POST /apply
  - Watch folder: any .json file dropped into <root>/Automation/inbox/ is processed automatically; results go to <root>/Automation/outbox/<filename>.result.json
- The manifest application must be transactional per item, idempotent on version_id and comment content, and produce a structured result report listing created, skipped, and failed items.
- Manifests may include an optional root or auto_root directive for first-time automation bootstrap.

D. MCP Server (Model Context Protocol)
- Provide an optional MCP server exposing the same operations as tools, so LLM agents can call them directly. Suggested tools:
  - init_root
  - create_project
  - list_projects
  - get_project
  - move_project
  - add_version
  - list_versions
  - add_file
  - add_comment
  - resolve_comment
  - list_comments
  - apply_manifest
- Each tool must have a clear JSON schema, documented inputs and outputs, and return the same objects as the CLI/HTTP layer.

E. Shared Core
- Implement all automation surfaces on top of a single internal Python core (e.g. scitree.core) that owns all business logic, validation, folder creation, extraction, and SQLite writes.
- The UI, CLI, HTTP API, MCP server, and manifest processor must all call this same core. No duplicated business rules.

F. Safety and Observability
- All automated operations must be logged to <root>/Automation/logs/ with timestamp, actor (ui|cli|http|mcp|manifest), operation, and result.
- Support --dry-run / "validate_only": true to check inputs without side effects.
- Clear, machine-readable error responses: { "error": "<code>", "message": "<human text>", "details": { ... } }.
- Include a schema/version field in every JSON payload (e.g. schema_version: "1.0") for forward compatibility.

UI/UX Requirements:
- Minimalist, modern, clean, and functional.
- Ample whitespace, neutral color palette, soft grays, white, and one accent color.
- Modern typography.
- Smooth drag-and-drop interactions.
- Clear visual hierarchy.
- The latest manuscript version must be immediately obvious.
- No clutter. Prefer simple, readable workflows over feature density.
- Provide a small "Automation" panel in the UI showing: last manifest result, API/MCP server status, and recent automated operations.
- On first launch, show the root-folder onboarding dialog with clear options: "Choose folder", "Use recommended location", and "Skip and use recommended location".

Technical Stack:
- Language: Python 3.11+
- UI Framework: Flet as the primary recommendation for a modern Flutter-based UI with good drag-and-drop support. Use PySide6 only if Flet cannot meet a specific requirement.
- Document parsing:
  - DOCX: python-docx plus zipfile for embedded image extraction
  - PDF: PyMuPDF / fitz
  - Bibliography parsing: bibtexparser plus regex-based section detection
- Database: SQLite for projects, versions, authors, comments, and minimal onboarding state.
- File storage: local filesystem under the selected or auto-selected root folder.
- HTTP API: FastAPI (with uvicorn), loopback only.
- CLI: Typer or argparse, sharing the same core.
- MCP server: official MCP Python SDK, exposing tools backed by the same core.
- Packaging: ensure the app can be packaged as a standalone executable using flet pack or PyInstaller, with CLI, HTTP API, and MCP server available from the packaged install.

Deliverables:
- Complete project structure
- All source code
- requirements.txt
- README.md with setup, run, packaging, and automation usage instructions
- JSON schema documentation for the manifest, HTTP API, CLI --json output, and MCP tools
- Brief explanation of the folder structure and data model
- Notes on any limitations in DOCX/PDF comment or bibliography extraction
- A minimal example manifest and a sample agent invocation script

Future Enhancements (nice-to-have; do not block the MVP):
- Global search across manuscripts, references, and comments
- Custom tags and filters for Kanban cards
- Backup/export of the entire root folder as a structured .zip
- Import/sync support for .bib files from Zotero/Mendeley
- Statistics panel: word count per version, number of extracted figures, pending comments
- Authentication and multi-user sync for the HTTP API

================================================================
ADDENDUM — EXTENDED FUNCTIONAL REQUIREMENTS
================================================================

This addendum extends and, where explicitly stated, overrides the original prompt above. Apply every item below in addition to the original requirements. Do not drop any original requirement; this section only adds and refines.

----------------------------------------------------------------
Section A — Multiple Views per Board
----------------------------------------------------------------

Extend Requirement 3 (Kanban Board) with the following:

A1. Provide at least two synchronized views of the same project collection:
    - Board view (Kanban, the default and primary view)
    - List / Table view (compact, sortable, filterable)
    Optionally add a Calendar or Gantt-style view as a future enhancement.

A2. Both views must operate on the same underlying dataset and share:
    - The same search bar
    - The same filter state (column, tags, owner_type, has_pending_comments, author)
    - The same sort order where applicable

A3. The user's last selected view per board must be remembered as UI state (not as a long-term preference).

A4. Switching views must not require reloading the project data; it should be instantaneous.

A5. Automation must expose the same data in a view-agnostic JSON shape; views are a UI concern only.

----------------------------------------------------------------
Section B — Risks and Milestones per Project
----------------------------------------------------------------

Add two new first-class entities attached to each project.

B1. Risk
    - Fields: id, title, description, severity (low | medium | high | critical),
      likelihood (low | medium | high), owner (free text), status (open | mitigating | closed),
      trigger (optional text), mitigation (optional text), created_at, updated_at.
    - Risks are listed per project and visible in a dedicated panel on the project view.
    - Risks can be created, edited, and closed via UI and via automation.

B2. Milestone
    - Fields: id, title, description, due_date (optional), status (pending | in_progress | done | missed),
      phase (e.g. short_term_7d, medium_term_30d, submission_ready, revision_ready, custom),
      created_at, updated_at.
    - Milestones are hierarchical in the sense that phases are ordered and can contain multiple milestones.
    - Milestones are shown in a per-project milestones panel and optionally as badges on the Kanban card.

B3. Card indicators
    - The Kanban card must show small badges for: open high/critical risks, next upcoming milestone,
      pending comments count.

B4. Automation
    - Extend the CLI, HTTP API, manifest, and MCP tools with:
      - risk add / list / update / close
      - milestone add / list / update / close
    - These operations must be idempotent when a client supplies an explicit id.

----------------------------------------------------------------
Section C — Project Timeline / Route View
----------------------------------------------------------------

Add a third view per project: Timeline (also called "Route View").

C1. The Timeline shows a chronological list of all significant events for a project:
    - Project created
    - Version added (with version_id, author, changelog)
    - Card moved between columns
    - Comment added / resolved
    - Risk added / closed
    - Milestone reached / missed
    - Manual notes (optional, actor-provided)

C2. Each event must record: timestamp, actor (human | agent), actor_source (ui | cli | http | mcp | manifest), event_type, and payload.

C3. The Timeline must be readable at a glance, with grouping by day and color coding by event type.

C4. The Timeline is derived from the Activity Log (Section E below); it is not a separate store.

C5. Automation must be able to append timeline events via the standard operations and via a dedicated `timeline note add` operation (optional convenience).

----------------------------------------------------------------
Section D — Immutable Submission Snapshots
----------------------------------------------------------------

Extend Requirement 4 (Version Control) with the following:

D1. Each version has a `state` field: draft | submitted | published | revision.
    - Default state on upload: draft.
    - The user can promote a version to submitted or published.

D2. Once a version is marked submitted or published, it becomes immutable:
    - Its manuscript file, extracted figures, and generated .bib cannot be modified or overwritten.
    - Any subsequent change must create a new derived version (e.g. v2 from v1-submitted) with a recorded `derived_from` link.

D3. Immutable versions must show a clear lock indicator in the UI (in the version list and on the Timeline).

D4. Automation must refuse to modify immutable versions and return a stable error code `VERSION_IMMUTABLE` with a suggestion to create a new derived version.

D5. Deleting an immutable version is forbidden; only archiving (hiding from default views) is allowed.

----------------------------------------------------------------
Section E — Actor Attribution, Owner Filtering, and Activity Log
----------------------------------------------------------------

Extend Requirement 7 and the Automation section with the following:

E1. Every mutation must record:
    - actor_id (optional)
    - actor_name (free text, e.g. "Jane Doe" or "agent:claude")
    - actor_type: human | agent
    - actor_source: ui | cli | http | mcp | manifest

E2. Project cards and comment cards must carry an `owner_type` field (human | agent).
    - Comments extracted from a manuscript default to owner_type = human with owner_name = document author if detectable, otherwise "unassigned".
    - Comments created by an agent default to owner_type = agent.

E3. Provide a quick filter on all views: "My tasks", "Agent tasks", "All".

E4. Activity Log
    - A per-project Activity Log must exist and be visible in the UI (not only in the automation logs directory).
    - The Activity Log is append-only and records every mutation with the fields from E1 plus timestamp, event_type, and a compact payload.
    - The Activity Log is the source for the Timeline (Section C).
    - Provide filters by actor_type, actor_source, event_type, and date range.

E5. Automation must return the actor attribution it applied in its response payload, so callers can verify attribution was recorded correctly.

----------------------------------------------------------------
Section F — Submission Package Export
----------------------------------------------------------------

Add a new operation: Export Submission Package.

F1. For a given project (and optionally a specific version), generate a structured .zip containing:
    - The manuscript file of the chosen version (or latest)
    - All text figures for that version (from Figures_Text/v{n}/)
    - The generated .bib file
    - A metadata.json with: project name, version_id, version state, authors, submission date (if any), changelog, and a list of file checksums
    - A manifest of extracted comments and their resolution state

F2. Export must be reproducible: the same project + version + option must yield the same zip contents (excluding timestamps).

F3. Export must be available via UI (button), CLI (`scitree export package`), HTTP (`POST /projects/{name}/export`), and MCP (`export_package`).

F4. The export must not modify any source data.

----------------------------------------------------------------
Section G — Project Templates
----------------------------------------------------------------

Add a template system.

G1. Built-in templates, at minimum:
    - Empirical Paper: Idea → Literature → Data → Analysis → Writing → Submitted → Published
    - Review Article: Idea → Literature → Drafting → Revision → Submitted → Published
    - Grant Proposal: Idea → Team → Budget → Writing → Review → Submitted → Awarded / Rejected

G2. Each template defines:
    - Initial columns
    - Default milestones per phase
    - Default folder structure additions (optional)
    - Default risk categories (optional)

G3. Users can save a custom template from an existing project.

G4. Templates are stored as human-readable JSON under <root>/Templates/ and are editable outside the app.

G5. Automation must accept `--template "<name>"` on `project create` and `create_project` MCP tool, and support `template_apply` to apply a template to an existing project (only adds missing items; never removes).

----------------------------------------------------------------
Section H — Optional Zotero Sync
----------------------------------------------------------------

Add an optional Zotero integration (post-MVP, but expose the interface in the MVP).

H1. Per project, the user may link a Zotero collection (by collection key) using the local Zotero API.

H2. When linked, sciTree syncs the collection's items into the project's References/ folder as a .bib file, preserving the existing extracted .bib (it is stored as `references_extracted.bib`, while the synced one is `references_zotero.bib`).

H3. Sync must be version-aware: it only updates the file if the Zotero collection changed since the last sync (compare item versions).

H4. Sync is opt-in and never blocks offline use. If Zotero is unavailable, the app must degrade gracefully and log a warning in the Activity Log.

H5. Automation must expose `zotero link`, `zotero sync`, and `zotero unlink` operations with the same JSON schema conventions.

----------------------------------------------------------------
Section I — Updates to Existing Sections
----------------------------------------------------------------

Apply the following refinements to the original prompt:

I1. Requirement 1 (First-Run Setup)
    - After choosing or auto-selecting the root, the app should offer the template picker as an optional second step (skippable).
    - The default folder structure under the root should include: Projects/, Templates/, Automation/ (already implied), Exports/.

I2. Requirement 2 (Project Creation)
    - Project creation accepts an optional template name (see Section G).
    - The SQLite schema must include tables for: projects, versions, files, comments, risks, milestones, activity_log, templates, settings.
    - The SQLite database is an index/cache; the filesystem under the root remains the source of truth. The database must be rebuildable from the filesystem plus a machine-readable metadata.json per project.

I3. Requirement 4 (Version Control)
    - Version numbering must remain sequential per project; derived versions must carry `derived_from`.

I4. Automation surfaces (CLI, HTTP, MCP, manifest)
    - Extend all four surfaces with the new operations introduced in this addendum:
      risks, milestones, timeline, export, templates, zotero, activity log queries.
    - Manifest schema must accept new top-level keys: `risks`, `milestones`, `template`, `zotero_link`, `export` (optional), and `activity_notes`.
    - All new operations must obey idempotency, --dry-run, --json, schema_version, and stable error codes.

I5. Stable error codes to add:
    - VERSION_IMMUTABLE
    - TEMPLATE_NOT_FOUND
    - RISK_NOT_FOUND
    - MILESTONE_NOT_FOUND
    - ZOTERO_UNAVAILABLE
    - EXPORT_FAILED
    - ACTOR_REQUIRED (for agent mutations without actor_name)

I6. Technical Stack additions
    - Zotero: local Zotero HTTP API (read-only sync in MVP).
    - Export: standard library zipfile + hashlib; no external dependency required.

I7. UI/UX additions
    - Top-right view switcher: Board | List | Timeline.
    - Right-side drawer on project view with tabs: Versions | Comments | Risks | Milestones | Activity.
    - Small owner filter chip row above the board: My tasks | Agent tasks | All.
    - Lock icon on immutable versions and on cards whose latest version is immutable.
    - Export button in the project view (generates a submission package).

----------------------------------------------------------------
Section J — Future Enhancements (nice-to-have; do not block the MVP)
----------------------------------------------------------------

- Markdown and Typst as input formats for manuscript ingestion, with the same extraction pipeline (figures + references + comments).
- Declarative project automations (rules like "when a new CSV is added, run script X and store figure Y") inspired by pipeline-style scientific tools.
- Global search across manuscripts, references, comments, risks, and milestones.
- Custom tags and saved filter presets for board and list views.
- Statistics panel: word count per version, number of extracted figures, pending comments, open risks, milestones overdue.
- Optional multi-user sync with authentication for the HTTP API.
- Calendar / Gantt view in addition to Board, List, and Timeline.
================================================================
