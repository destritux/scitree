# sciTree

**Local-first Kanban for scientific manuscripts, with automated figure/reference extraction and agent-ready automation.**

sciTree is a local-first Kanban app for scientific manuscripts. It offers simple visual version control, automatic figure and bibliography extraction from DOCX/PDF, resolvable comment cards, and agent-friendly automation via CLI, HTTP API, and MCP. All data stays as plain files on your disk. No cloud or lock-in.

---

## Table of Contents

- [Why sciTree](#why-scitree)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Automation](#automation)
  - [CLI](#cli)
  - [HTTP API](#http-api)
  - [MCP Server](#mcp-server)
  - [Manifest Ingestion](#manifest-ingestion)
- [Data Model](#data-model)
- [Configuration](#configuration)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Why sciTree

Researchers juggle manuscripts, figures, data, references, and reviewer comments across too many tools: a Kanban app here, a reference manager there, a folder full of `final_v3_REAL_FINAL.docx` files, and spreadsheets tracking who owes what. sciTree brings these together in a single local-first app that:

- **Stays on your disk.** All data lives as plain files in a folder you choose. The SQLite database is only an index that can be rebuilt from those files.
- **Understands scientific workflows.** Lifecycle columns, version states (`draft` -> `submitted` -> `published`), risks, milestones, and submission packages are first-class.
- **Extracts what matters.** Upload a DOCX or PDF manuscript and sciTree pulls out embedded figures, parses the bibliography into a `.bib`, and turns inline comments into resolvable task cards.
- **Loves automation.** Every UI action is also a CLI command, an HTTP endpoint, an MCP tool, and a declarative manifest. Agents can drive the whole app.

---

## Features

### Kanban and views
- **Board, List, and Timeline views** sharing the same filters and search state.
- **Drag-and-drop** between columns: *Idea -> Literature -> Data -> Analysis -> Writing -> Submitted -> Published*.
- **Quick filters**: *My tasks* / *Agent tasks* / *All*.
- **Card badges**: pending comments, open high/critical risks, next upcoming milestone.

### Version control
- **Simplified visual version control** — upload DOCX or PDF, record the author and a changelog, get a clean version list.
- **Immutable snapshots** — once a version is marked `submitted` or `published`, it cannot be modified. Any change creates a derived version (`derived_from`), with a lock indicator in the UI.
- **Latest version is always visually obvious**, in the board and in the version list.

### Automatic extraction
- **Figures** — every embedded image in a DOCX or PDF is extracted to `Figures_Text/v{n}/`.
- **References** — the bibliography section is parsed and saved as a `.bib` file under `References/`.
- **Comments** — Word comments and `[COMMENT: ...]` markers become task cards with a resolution checkbox.
- **Extraction logs** — warnings are surfaced per version, not silently swallowed.

### Scientific workflow
- **Risks** — severity, likelihood, owner, trigger, and mitigation per project.
- **Milestones** — phased and dated (7-day, 30-day, submission-ready, revision-ready).
- **Submission package export** — one click generates a reproducible `.zip` with the manuscript, text figures, `.bib`, extracted comments, and a `metadata.json`, with SHA-256 checksums.
- **Optional Zotero sync** — link a Zotero collection to keep `references_zotero.bib` version-aware and up to date.

### Automation-first
- **CLI** — every operation, with `--json`, `--dry-run`, and stable exit codes.
- **Local HTTP API** — loopback-only FastAPI mirror of the CLI.
- **MCP server** — call sciTree from any MCP-enabled LLM agent.
- **Manifest ingestion** — drop a JSON manifest into `Automation/inbox/` and get a structured result report in `Automation/outbox/`.
- **Activity log** — every mutation is attributed to `human` or `agent` and recorded in a per-project JSONL log that powers the Timeline view.

---

## Installation

sciTree requires **Python 3.11+**.

```bash
git clone https://github.com/destritux/scitree.git
cd scitree
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .
```

Run the desktop app:

```bash
python -m scitree
# or:
scitree-ui
```

Or use the CLI directly:

```bash
scitree --help
```

### Packaged builds
Standalone executables can be built with `flet pack` or `PyInstaller`. The packaged install exposes the UI, the CLI, the HTTP API, and the MCP server from the same codebase:

```bash
flet pack scitree/ui/app.py --name sciTree
# or with PyInstaller:
pyinstaller --noconfirm --onedir --name sciTree scitree/ui/app.py
```

---

## Quick Start

### 1. First run
On first launch, sciTree asks where to store your projects:
- **Choose folder** — pick any folder.
- **Use recommended location** — the default for your OS:
  - Windows: `%USERPROFILE%\Documents\sciTree`
  - macOS: `~/Documents/sciTree`
  - Linux: `$XDG_DATA_HOME/scitree` or `~/.local/share/scitree`
- **Skip and use recommended location** — same as Use recommended location.

You will only be asked once. You can reset onboarding later from settings or with `scitree init --reset`.

### 2. Create a project
From the UI: click **+ New Project**, choose a template (e.g. `Empirical Paper`), pick a name.

From the CLI:

```bash
scitree project create --name "Alpha Study" --template "Empirical Paper"
```

### 3. Upload a manuscript
From the UI: upload a DOCX or PDF in the project's version panel.

From the CLI:

```bash
scitree version add \
  --project "Alpha Study" \
  --file ./manuscript_v1.docx \
  --author "Jane Doe" \
  --version-id v1 \
  --changelog "First full draft."
```

sciTree will automatically:
- extract figures to `Figures_Text/v1/`
- parse references into `References/v1.bib` and `References/references_extracted.bib`
- turn inline comments and Word/PDF annotations into task cards

### 4. Submit and lock
When you are ready:

```bash
scitree version submit --project "Alpha Study" --version v1 --to "Journal of Sleep Research"
scitree export package --project "Alpha Study" --version v1
```

The version becomes immutable. Any subsequent edits must create a derived version.

---

## Project Structure

Every project lives in its own folder under the root you chose:

```text
<root>/
├── scitree.db                         # Rebuildable SQLite index
├── Projects/
│   └── Alpha_Study/
│       ├── metadata.json              # Human-readable source of truth
│       ├── activity_log.jsonl         # Append-only event log
│       ├── Versions/
│       │   ├── v1/manuscript.docx
│       │   └── v2/manuscript.pdf
│       ├── Figures_Text/
│       │   ├── v1/                    # Figures extracted from v1
│       │   └── v2/
│       ├── Figures_Standalone/
│       ├── Data/                      # Excel, CSV, etc.
│       ├── References/
│       │   ├── v1.bib
│       │   ├── references_extracted.bib
│       │   └── references_zotero.bib
│       └── Automation/
│           └── extraction_v1.log
├── Templates/                         # Reusable project templates
├── Exports/                           # Submission packages
└── Automation/
    ├── logs/                          # Global audit log
    ├── inbox/                         # Root-level manifest inbox
    └── outbox/                        # Manifest execution reports
```

The folder is the source of truth. The SQLite database is a rebuildable index (`scitree db rebuild`).

---

## Automation

### CLI
Every command supports `--json`, `--dry-run`, and stable exit codes:

```bash
scitree init --root ~/Documents/sciTree
scitree init --auto-root

scitree project create --name "Alpha Study" --template "Empirical Paper" --column "Idea"
scitree project list --json
scitree project show --name "Alpha Study" --json
scitree project move --name "Alpha Study" --column "Writing"

scitree version add --project "Alpha Study" --file ./v1.docx --author "Jane Doe" --version-id v1
scitree version list --project "Alpha Study" --json
scitree version submit --project "Alpha Study" --version v1 --to "Journal X"

scitree file add --project "Alpha Study" --file ./data.xlsx --kind data
scitree file add --project "Alpha Study" --file ./fig1.png --kind figure

scitree comment add --project "Alpha Study" --text "Fix intro citation" --version v1
scitree comment resolve --project "Alpha Study" --comment-id cmt_001
scitree comment list --project "Alpha Study" --status pending --json

scitree risk add --project "Alpha Study" --title "Small sample" --severity high
scitree milestone add --project "Alpha Study" --title "First submission" --due 2026-11-20

scitree export package --project "Alpha Study" --version v1
scitree zotero link --project "Alpha Study" --collection ABCD1234
scitree zotero sync --project "Alpha Study"
```

### HTTP API
Start a loopback-only HTTP server that mirrors the CLI:

```bash
scitree serve --host 127.0.0.1 --port 8765
# or:
scitree-api --host 127.0.0.1 --port 8765
```

```http
POST   /init
POST   /projects
GET    /projects
GET    /projects/{name}
PATCH  /projects/{name}
POST   /projects/{name}/versions
GET    /projects/{name}/versions
PATCH  /projects/{name}/versions/{version_id}
POST   /projects/{name}/files
POST   /projects/{name}/comments
PATCH  /projects/{name}/comments/{id}
GET    /projects/{name}/comments
POST   /projects/{name}/risks
GET    /projects/{name}/risks
PATCH  /projects/{name}/risks/{id}
POST   /projects/{name}/milestones
GET    /projects/{name}/milestones
PATCH  /projects/{name}/milestones/{id}
GET    /projects/{name}/timeline
POST   /projects/{name}/timeline/notes
GET    /projects/{name}/activity
POST   /projects/{name}/export
POST   /projects/{name}/template
POST   /projects/{name}/zotero/link
POST   /projects/{name}/zotero/sync
POST   /projects/{name}/zotero/unlink
GET    /templates
POST   /templates
POST   /apply
POST   /inbox/process
```

All responses include `schema_version`. Errors are structured:

```json
{
  "schema_version": "1.0",
  "error": "VERSION_IMMUTABLE",
  "message": "Version 'v1' is immutable (submitted) and cannot be modified. Create a new derived version 'v2' with derived_from='v1'.",
  "details": {
    "version_id": "v1",
    "current_state": "submitted",
    "suggested_derived_version": "v2",
    "derived_from": "v1"
  }
}
```

### MCP Server
sciTree exposes an MCP server for LLM agents:

```bash
scitree mcp
# or:
scitree-mcp
```

Available tools include `init_root`, `create_project`, `list_projects`, `get_project`, `move_project`, `add_version`, `list_versions`, `update_version_state`, `add_file`, `add_comment`, `resolve_comment`, `list_comments`, `add_risk`, `list_risks`, `update_risk`, `close_risk`, `add_milestone`, `list_milestones`, `update_milestone`, `close_milestone`, `add_timeline_note`, `get_timeline`, `list_activity`, `export_package`, `list_templates`, `save_template`, `template_apply`, `zotero_link`, `zotero_sync`, `zotero_unlink`, and `apply_manifest`. All tools share the same JSON schemas as the CLI and HTTP API.

### Manifest Ingestion
Drop a JSON manifest into `Automation/inbox/` or run `scitree apply --manifest examples/example_manifest.json`:

```json
{
  "project": { "name": "Alpha Study", "template": "Empirical Paper", "column": "Writing" },
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
  ],
  "risks": [
    { "title": "Small sample", "severity": "high", "likelihood": "medium" }
  ]
}
```

A result report appears in `Automation/outbox/` listing created, skipped, and failed items. You can also run the complete end-to-end agent demonstration script:

```bash
python examples/sample_agent.py
```

---

## Data Model

Two files anchor every project:
- `metadata.json` — human-readable source of truth for the project's authors, versions, comments, risks, milestones, template, Zotero link, and exports.
- `activity_log.jsonl` — append-only log of every event, one JSON object per line. Powers the Timeline view and the audit trail.

Both files are schema-versioned. See [docs/SCHEMA.md](docs/SCHEMA.md) for the complete JSON schemas, CLI exit codes, HTTP status mappings, MCP tool definitions, and DOCX/PDF extraction notes.

---

## Configuration

Minimal state is stored per install:
- **Onboarding completed** — a single flag so the root folder picker only appears once.
- **Effective root path** — the folder currently in use.

Both can be reset from settings or with `scitree init --reset`.

---

## Roadmap

### v0.1 — MVP
- Kanban board with drag-and-drop
- Simplified version control with immutable submission snapshots
- DOCX/PDF extraction (figures, references, comments)
- CLI, HTTP API, MCP server, manifest ingestion
- Activity log and Timeline view

### v0.2
- Risk and milestone panels
- Project templates
- Submission package export
- Optional Zotero sync

### v0.3+
- Markdown and Typst manuscript support
- Declarative project automations (pipeline-style)
- Calendar and Gantt views
- Statistics dashboard
- Multi-user sync for the HTTP API

---

## Contributing

Run the automated test suite with:

```bash
pytest -v
```

---

## License

Released under the MIT License.
