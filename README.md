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
- **Understands scientific workflows.** Lifecycle columns, version states (`draft` → `submitted` → `published`), risks, milestones, and submission packages are first-class.
- **Extracts what matters.** Upload a DOCX or PDF manuscript and sciTree pulls out embedded figures, parses the bibliography into a `.bib`, and turns inline comments into resolvable task cards.
- **Loves automation.** Every UI action is also a CLI command, an HTTP endpoint, an MCP tool, and a declarative manifest. Agents can drive the whole app.

---

## Features

### Kanban and views
- **Board, List, and Timeline views** sharing the same filters and search state.
- **Drag-and-drop** between columns: *Idea → Literature → Data → Analysis → Writing → Submitted → Published*.
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
- **Submission package export** — one click generates a `.zip` with the manuscript, text figures, `.bib`, extracted comments, and a `metadata.json`, with checksums.
- **Optional Zotero sync** — link a Zotero collection to keep `references_zotero.bib` version-aware and up to date.

### Automation-first
- **CLI** — every operation, with `--json`, `--dry-run`, and stable exit codes.
- **Local HTTP API** — loopback-only FastAPI mirror of the CLI.
- **MCP server** — call sciTree from any MCP-enabled LLM agent.
- **Manifest ingestion** — drop a JSON manifest into `Automation/inbox/` and get a structured result report in `Automation/outbox/`.
- **Activity log** — every mutation is attributed to `human` or `agent` and recorded in a per-project JSONL log that powers the Timeline view.

---

## Screenshots

> Screenshots coming soon. The first release targets a clean, minimalist Flutter-based UI via [Flet](https://flet.dev).

---

## Installation

sciTree requires **Python 3.11+**.

Run the desktop app:

bash
python -m scitree
Or use the CLI directly:

bash
scitree --help
Packaged builds
Standalone executables can be built with flet pack or PyInstaller. The packaged install exposes the UI, the CLI, the HTTP API, and the MCP server from the same binary:

bash
flet pack src/scitree/main.py --name sciTree
See docs/packaging.md for details.

Quick Start
1. First run
On first launch, sciTree asks where to store your projects:

Choose folder — pick any folder.

Use recommended location — the default for your OS:

Windows: %USERPROFILE%\Documents\sciTree

macOS: ~/Documents/sciTree

Linux: $XDG_DATA_HOME/scitree or ~/.local/share/scitree

Skip — same as Use recommended location.

You'll only be asked once. You can reset onboarding later from settings or with scitree init.

2. Create a project
From the UI: click New Project, choose a template (e.g. Empirical Paper), pick a name.

From the CLI:

bash
scitree project create --name "Alpha Study" --template "Empirical Paper"
3. Upload a manuscript
From the UI: drop a DOCX or PDF into the project's version panel.

From the CLI:

bash
scitree version add \
  --project "Alpha Study" \
  --file ./manuscript_v1.docx \
  --author "Jane Doe" \
  --version-id v1 \
  --changelog "First full draft."
sciTree will automatically:

extract figures to Figures_Text/v1/

parse references into References/v1.bib

turn inline comments into task cards

4. Submit and lock
When you're ready:

bash
scitree version submit --project "Alpha Study" --version v1 --to "Journal of Sleep Research"
scitree export package --project "Alpha Study" --version v1
The version becomes immutable. Any subsequent edits must create a derived version.

Project Structure
Every project lives in its own folder under the root you chose:

text
<root>/
├── Projects/
│   └── Alpha Study/
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
│           ├── inbox/                 # Drop manifests here
│           └── outbox/                # Results appear here
├── Templates/                         # Reusable project templates
├── Exports/                           # Submission packages
└── Automation/
    ├── logs/                          # Global audit log
    └── inbox/                         # Root-level manifest inbox
The folder is the source of truth. The SQLite database is a rebuildable index.

Automation
CLI
Install the CLI alongside the app. Every command supports --json, --dry-run, and stable exit codes.

bash
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
scitree milestone add --project "Alpha Study" --title "First submission" --due 2025-03-20

scitree export package --project "Alpha Study" --version v1
scitree zotero link --project "Alpha Study" --collection ABCD1234
scitree zotero sync --project "Alpha Study"
HTTP API
Start a loopback-only HTTP server that mirrors the CLI:

bash
scitree serve --host 127.0.0.1 --port 8765
http
POST   /projects
GET    /projects
GET    /projects/{name}
PATCH  /projects/{name}
POST   /projects/{name}/versions
POST   /projects/{name}/files
POST   /projects/{name}/comments
PATCH  /projects/{name}/comments/{id}
POST   /projects/{name}/risks
POST   /projects/{name}/milestones
POST   /projects/{name}/export
POST   /apply
All responses include schema_version. Errors are structured:

json
{
  "error": "VERSION_IMMUTABLE",
  "message": "Version v1 is immutable. Create a derived version instead.",
  "details": { "project": "Alpha Study", "version": "v1" }
}
MCP Server
sciTree exposes an MCP server for LLM agents:

bash
scitree mcp
Available tools include create_project, list_projects, add_version, list_versions, add_file, add_comment, resolve_comment, add_risk, add_milestone, export_package, apply_manifest, and more. All tools share the same JSON schemas as the CLI and HTTP API.

Manifest Ingestion
Drop a JSON manifest into Automation/inbox/:

json
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
A result report appears in Automation/outbox/ listing created, skipped, and failed items. Manifests are also accepted via scitree apply --manifest <path> and POST /apply.

Data Model
Two files anchor every project:

metadata.json — human-readable source of truth for the project's authors, versions, comments, risks, milestones, template, Zotero link, and exports. Commit it to git and diff it.

activity_log.jsonl — append-only log of every event, one JSON object per line. Powers the Timeline view and the audit trail.

Both files are schema-versioned. See docs/schemas/metadata.md and docs/schemas/activity_log.md for the full specifications.

The SQLite database at <root>/.scitree.db is a rebuildable index. Delete it and sciTree will reconstruct it on next launch from the filesystem.

Configuration
Minimal state is stored per install:

Onboarding completed — a single flag so the root folder picker only appears once.

Effective root path — the folder currently in use.

Both can be reset from settings or with scitree init --reset. The app never modifies the folder silently; all file writes are logged to the Activity Log.

Roadmap
v0.1 — MVP

Kanban board with drag-and-drop

Simplified version control with immutable submission snapshots

DOCX/PDF extraction (figures, references, comments)

CLI, HTTP API, MCP server, manifest ingestion

Activity log and Timeline view

v0.2

Risk and milestone panels

Project templates

Submission package export

Optional Zotero sync

v0.3+

Markdown and Typst manuscript support

Declarative project automations (pipeline-style)

Calendar and Gantt views

Statistics dashboard

Multi-user sync for the HTTP API

Contributing
Issues and pull requests are welcome. Before opening a PR:

Run pytest and ruff check .

Update docs/schemas/ if you change any JSON shape

Add an entry to CHANGELOG.md

See CONTRIBUTING.md for the full guide.

License
Released under the MIT License. See LICENSE.

Acknowledgments
sciTree draws inspiration from Open Science Framework, Calkit, Manubot, PASTA-ELN, Kan.bn, and Aldine, among others. It exists because research de
