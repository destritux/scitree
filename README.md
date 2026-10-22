# sciTree

**Local-first Kanban and interactive workspace for scientific manuscripts, with in-app LaTeX/source editing, automated figure/reference extraction, and agent-ready automation.**

sciTree is a local-first desktop workspace and Kanban application for scientific manuscripts. It combines visual version control, an expandable per-paper file explorer and in-app article editor (`.tex`, `.bib`, `.md`, `.py`, `.csv`), automatic figure and bibliography extraction from DOCX/PDF, resolvable comment cards, and an integrated CLI command console alongside full HTTP API and MCP automation. All data stays as plain files on your disk. No cloud or lock-in.

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

Researchers juggle manuscripts, figures, data tables, scripts, references, and reviewer comments across too many tools: a Kanban app here, a reference manager there, a folder full of `final_v3_REAL_FINAL.docx` files, and spreadsheets tracking who owes what. sciTree brings these together in a single local-first workspace that:

- **Stays on your disk.** All data lives as plain files in a folder you choose. The SQLite database is only an index that can be rebuilt from those files at any time.
- **Understands scientific workflows.** Lifecycle columns, version states (`draft` -> `submitted` -> `published`), risks, milestones, and submission packages are first-class.
- **Lets you inspect and edit every paper's files in one place.** Clicking a paper collapses the project list into a compact sidebar and expands a full-screen workspace with a categorized file explorer, high-resolution figure viewer, interactive CSV table previewer, and full-width LaTeX/BibTeX/Markdown/Python editor with one-click `pdflatex` compilation.
- **Extracts what matters.** Upload a DOCX or PDF manuscript and sciTree pulls out embedded figures, parses the bibliography into `.bib`, and turns inline comments into resolvable task cards.
- **Loves automation.** Every UI action is also a CLI command (accessible directly from the built-in UI CLI console or terminal), an HTTP endpoint, an MCP tool, and a declarative manifest.

---

## Features

### Kanban, Views, and Themes
- **Dark Mode by default + instant theme toggle** — modern dark scientific palette (`#0B0F19` / `#111827`) with a `Theme: Dark` / `Theme: Light` switch in the top bar persisted across sessions.
- **Board, List, and Timeline views** sharing the same filters and search state.
- **Smart responsive Kanban lanes** — empty columns automatically compact so active manuscript columns remain immediately visible without horizontal scrolling.
- **Drag-and-drop** between columns: *Idea -> Literature -> Data -> Analysis -> Writing -> Submitted -> Published*.
- **Quick filters**: *My tasks* / *Agent tasks* / *All*, plus pending-comment filtering and sorting.
- **Card badges**: latest version state, file counts (versions, figures, datasets), pending comments, open high/critical risks, and next upcoming milestone.

### Collapsible Paper List & Expanded File / Article Editor Workspace
- **Compact Paper Sidebar** — clicking any paper card on the Board or row in the List shrinks the project overview into a `225px` left sidebar for one-click switching between papers or returning to the full board (`<- Back to Full Board`).
- **Categorized Paper File Explorer** — automatically indexes and filters all files in the paper directory across `All`, `Manuscripts`, `Figures`, `Data (CSV)`, `BibTeX`, and `Scripts`.
- **Full-Width In-App Article & Code Editor** — edit `.tex`, `.bib`, `.md`, `.py`, `.json`, and `.txt` files directly inside sciTree:
  - **`Maximize Editor` mode** — collapses sidebars to give 100% window width to the article editor, with a **`Quick File Switcher`** dropdown in the toolbar to jump between modular LaTeX sections (e.g. `01_introducao.tex`, `02_modelagem_metodos.tex`, `03_resultados.tex`, `04_discussao.tex`, `05_conclusao.tex`, `main.tex`).
  - **Smart `Compile LaTeX (pdflatex)`** — saves the active `.tex` file, detects modular section files, compiles the master `main.tex` document, and updates the manuscript PDF.
  - **`+ New File`** — create new editable Markdown notes, LaTeX sections, or Python scripts directly inside the paper workspace.
- **Interactive Figure, CSV, and Manuscript Viewers**:
  - **Figures (`.png`, `.jpg`, `.webp`)** — native high-resolution preview inside the workspace.
  - **Datasets (`.csv`, `.tsv`)** — interactive scrollable data table preview with one-click toggle to raw CSV text editing (`Edit Raw CSV Text`).
  - **Manuscripts (`.pdf`, `.docx`)** — version metadata, clickable gallery of extracted figures, quick-jump buttons to companion `.tex`/`.bib` sources, one-click `Register as New Version`, and `Open in System App` (`xdg-open`).

### Integrated CLI Bar & Command Console in the UI
- **Persistent Bottom `CLI Bar`** — always accessible at the bottom of the expanded paper workspace to run any `scitree` command without leaving the editor.
- **`CLI & Article Commands` Tab** — full in-app CLI console with 17 pre-configured command templates bound to the active paper (`project show`, `version list`, `version add`, `version submit`, `comment add`, `comment resolve`, `milestone add`, `risk list`, `export package`, `db rebuild`, etc.), with `Fill` (edit before running) and `Run` (execute immediately) buttons.

### Version Control & Automatic Extraction
- **Simplified visual version control** — upload DOCX or PDF, record the author and changelog, and track version history.
- **Immutable snapshots** — once a version is marked `submitted` or `published`, it is locked (`[LOCKED]`). Subsequent edits create a derived version (`derived_from`).
- **Automatic artifact extraction**:
  - **Figures** — embedded images in DOCX or PDF are extracted to `Figures_Text/v{n}/`.
  - **References** — bibliography entries are parsed and saved as `.bib` files under `References/`.
  - **Comments** — Word comments, PDF annotations, and `[COMMENT: ...]` markers become resolvable task cards.
  - **Extraction logs** — per-version logs saved to `Automation/extraction_v{n}.log`.

### Scientific Workflow & Packaging
- **Risks** — severity, likelihood, owner, trigger, and mitigation tracking per project.
- **Milestones** — phased and dated (`short_term_7d`, `medium_term_30d`, `submission_ready`, `revision_ready`, `custom`).
- **Submission package export** — one click generates a reproducible `.zip` archive in `Exports/` containing the manuscript, extracted figures, `.bib` files, comments, `metadata.json`, and SHA-256 checksums.
- **Optional Zotero sync** — link a Zotero collection to synchronize `References/references_zotero.bib`.

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

### Packaged Standalone Builds
Standalone Linux/macOS/Windows executables can be compiled with `flet pack`:

```bash
flet pack scitree/__main__.py --name sciTree -y
```

This produces the standalone binary at `dist/sciTree`, which can be launched directly or pinned to the desktop dock via `~/.local/share/applications/scitree.desktop`.

---

## Quick Start

### 1. First run
On first launch, sciTree asks where to store your projects:
- **Choose folder** — pick any custom directory via native folder dialog.
- **Use recommended location** — uses the OS default:
  - Windows: `%USERPROFILE%\Documents\sciTree`
  - macOS: `~/Documents/sciTree`
  - Linux: `$XDG_DATA_HOME/scitree` or `~/.local/share/scitree`
- **Skip and use recommended location** — initializes the recommended OS path immediately.

You will only be asked once. You can change the root folder or reset onboarding at any time from **Root Settings** in the top bar or via `scitree init --reset`.

### 2. Create a project
From the UI: click **+ New Project**, choose a template (e.g. `Empirical Paper`), and enter a title.

From the CLI:

```bash
scitree project create --name "Alpha Study" --template "Empirical Paper"
```

### 3. Upload a manuscript or edit LaTeX in-app
From the UI: click on your paper card to expand the **Files & Article Editor** workspace, select any `.tex`, `.bib`, `.md`, or `.csv` file to edit in full width, or upload a new `.docx`/`.pdf` version in the **Versions** tab.

From the CLI:

```bash
scitree version add \
  --project "Alpha Study" \
  --file ./manuscript_v1.docx \
  --author "Jane Doe" \
  --version-id v1 \
  --changelog "First full draft."
```

### 4. Submit and lock
When ready for journal submission:

```bash
scitree version submit --project "Alpha Study" --version v1 --to "Journal of Plant Physiology"
scitree export package --project "Alpha Study" --version v1
```

---

## Project Structure

Every project lives in its own human-browsable folder under the configured root directory:

```text
<root>/
|-- scitree.db                         # Rebuildable SQLite index
|-- Projects/
|   `-- Alpha_Study/
|       |-- metadata.json              # Human-readable source of truth
|       |-- activity_log.jsonl         # Append-only event log
|       |-- Versions/
|       |   |-- v1/manuscript.docx
|       |   |-- v2/manuscript.pdf
|       |   |-- main.tex               # Optional modular LaTeX sources
|       |   `-- 01_introducao.tex
|       |-- Figures_Text/
|       |   |-- v1/                    # Figures extracted from v1
|       |   `-- v2/                    # Figures extracted from v2
|       |-- Figures_Standalone/        # High-resolution standalone figures (.png/.pdf)
|       |-- Data/                      # Experimental datasets & statistical tables (.csv/.xlsx)
|       |-- References/
|       |   |-- v1.bib
|       |   |-- v2.bib
|       |   |-- references_extracted.bib
|       |   `-- references_zotero.bib
|       |-- Scripts/                   # Computational pipeline scripts (.py/.R)
|       |-- Protocols/                 # Methodological protocols & notes (.md)
|       `-- Automation/
|           `-- extraction_v1.log
|-- Templates/                         # Reusable project templates (.json)
|-- Exports/                           # Reproducible submission packages (.zip)
`-- Automation/
    |-- logs/                          # Global audit log
    |-- inbox/                         # Root-level manifest watch folder
    `-- outbox/                        # Manifest execution reports
```

The filesystem is always the source of truth. The SQLite database is a rebuildable cache (`scitree db rebuild`).

---

## Automation

### CLI
Every command supports `--json`, `--dry-run`, `--actor-name`, `--actor-type`, and deterministic exit codes:

```bash
scitree init --root ~/scitree
scitree init --auto-root

scitree project create --name "Alpha Study" --template "Empirical Paper" --column "Idea"
scitree project list --json
scitree project show --name "Alpha Study" --json
scitree project move --name "Alpha Study" --column "Writing"

scitree version add --project "Alpha Study" --file ./v1.docx --author "Jane Doe" --version-id v1
scitree version list --project "Alpha Study" --json
scitree version submit --project "Alpha Study" --version v1 --to "Journal X"

scitree file add --project "Alpha Study" --file ./data.csv --kind data
scitree file add --project "Alpha Study" --file ./fig1.png --kind figure

scitree comment add --project "Alpha Study" --text "Fix intro citation" --version v1
scitree comment resolve --project "Alpha Study" --comment-id cmt_001
scitree comment list --project "Alpha Study" --status pending --json

scitree risk add --project "Alpha Study" --title "Small sample" --severity high
scitree milestone add --project "Alpha Study" --title "First submission" --due 2026-11-20

scitree export package --project "Alpha Study" --version v1
scitree zotero link --project "Alpha Study" --collection ABCD1234
scitree zotero sync --project "Alpha Study"
scitree db rebuild
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

### MCP Server
sciTree exposes a Model Context Protocol (MCP) server for LLM agents:

```bash
scitree mcp
# or:
scitree-mcp
```

Available tools include `init_root`, `create_project`, `list_projects`, `get_project`, `move_project`, `add_version`, `list_versions`, `update_version_state`, `add_file`, `add_comment`, `resolve_comment`, `list_comments`, `add_risk`, `list_risks`, `update_risk`, `close_risk`, `add_milestone`, `list_milestones`, `update_milestone`, `close_milestone`, `add_timeline_note`, `get_timeline`, `list_activity`, `export_package`, `list_templates`, `save_template`, `template_apply`, `zotero_link`, `zotero_sync`, `zotero_unlink`, and `apply_manifest`.

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
    { "kind": "data", "file": "path/to/data.csv" },
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

---

## Data Model

Two files anchor every project:
- `metadata.json` — human-readable source of truth for the project's authors, versions, files, comments, risks, milestones, template, Zotero link, and exports.
- `activity_log.jsonl` — append-only log of every event, one JSON object per line. Powers the Timeline view and the audit trail.

Both files are schema-versioned. See [docs/SCHEMA.md](docs/SCHEMA.md) for the complete JSON schemas, CLI exit codes, HTTP status mappings, MCP tool definitions, and DOCX/PDF extraction notes.

---

## Configuration

Minimal bootstrap state is stored in `~/.config/scitree/bootstrap.json` (permissions `0600`):
- `onboarding_completed` — boolean flag so the root folder picker only appears on first run.
- `root_path` — active workspace directory on disk.
- `ui_state` — active view (`board`, `list`, `timeline`) and theme preference (`dark_mode`).

---

## Roadmap

### v0.1 - MVP (Completed)
- Kanban board with drag-and-drop and smart compact empty lanes
- Simplified version control with immutable submission snapshots
- DOCX/PDF extraction (figures, references, comments)
- CLI, HTTP API, MCP server, and manifest ingestion
- Activity log and Timeline view

### v0.2 (Completed)
- Dark Mode & Light Mode switch
- Collapsible paper sidebar + expanded per-paper File Explorer & full-width In-App Article Editor (`.tex`, `.bib`, `.md`, `.py`, `.csv`)
- Built-in CLI Command Bar & interactive Console inside the desktop UI
- Risk and milestone panels, project templates, submission package export, and Zotero sync

### v0.3+
- Typst manuscript compilation support
- Declarative pipeline automations
- Calendar and Gantt views
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
