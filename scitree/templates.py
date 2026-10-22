"""Built-in and custom project templates management (Section G)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scitree import SCHEMA_VERSION
from scitree.errors import ERR_TEMPLATE_NOT_FOUND, SciTreeError
from scitree.models import safe_folder_name, utc_now_iso

DEFAULT_COLUMNS = ["Idea", "Writing", "Review", "Submitted", "Published"]

BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "Default": {
        "schema_version": SCHEMA_VERSION,
        "name": "Default",
        "version": "1.0",
        "description": "Standard minimalist scientific manuscript Kanban lifecycle.",
        "columns": ["Idea", "Writing", "Review", "Submitted", "Published"],
        "milestones": [
            {
                "title": "Outline and core argument ready",
                "phase": "short_term_7d",
                "description": "Define central research question and manuscript structure.",
            },
            {
                "title": "First full draft completed",
                "phase": "medium_term_30d",
                "description": "Complete initial draft with figures and bibliography.",
            },
            {
                "title": "Manuscript ready for journal submission",
                "phase": "submission_ready",
                "description": "All co-author comments resolved and submission package verified.",
            },
        ],
        "folders": [],
        "risks": [],
    },
    "Empirical Paper": {
        "schema_version": SCHEMA_VERSION,
        "name": "Empirical Paper",
        "version": "1.0",
        "description": "Experimental or observational study lifecycle from literature to publication.",
        "columns": ["Idea", "Literature", "Data", "Analysis", "Writing", "Submitted", "Published"],
        "milestones": [
            {
                "title": "Data collection completed",
                "phase": "short_term_7d",
                "description": "Raw datasets validated and stored in Data folder.",
            },
            {
                "title": "Statistical analysis and figures finalized",
                "phase": "medium_term_30d",
                "description": "Primary models and standalone/text figures generated.",
            },
            {
                "title": "First submission",
                "phase": "submission_ready",
                "description": "Manuscript formatted and submitted to target journal.",
            },
            {
                "title": "Revision ready",
                "phase": "revision_ready",
                "description": "Point-by-point response and revised manuscript prepared.",
            },
        ],
        "folders": ["Protocols", "Scripts"],
        "risks": [
            {
                "title": "Sample size or statistical power limitation",
                "description": "Insufficient statistical power in one or more experimental conditions.",
                "severity": "medium",
                "likelihood": "medium",
                "trigger": "If reviewers question statistical power",
                "mitigation": "Include sensitivity analysis and effect size confidence intervals.",
            }
        ],
    },
    "Review Article": {
        "schema_version": SCHEMA_VERSION,
        "name": "Review Article",
        "version": "1.0",
        "description": "Systematic, narrative, or scoping literature review workflow.",
        "columns": ["Idea", "Literature", "Drafting", "Revision", "Submitted", "Published"],
        "milestones": [
            {
                "title": "Search strategy and screening criteria defined",
                "phase": "short_term_7d",
                "description": "Database queries and inclusion/exclusion rules documented.",
            },
            {
                "title": "Synthesis matrix and taxonomy completed",
                "phase": "medium_term_30d",
                "description": "All selected articles categorized and synthesis figures drafted.",
            },
            {
                "title": "Submission ready",
                "phase": "submission_ready",
                "description": "Complete bibliography verified and manuscript ready for submission.",
            },
            {
                "title": "Revision ready",
                "phase": "revision_ready",
                "description": "Updated literature search and reviewer comments addressed.",
            },
        ],
        "folders": ["Screening"],
        "risks": [
            {
                "title": "Scope creep across subtopics",
                "description": "Review boundaries may expand excessively during screening.",
                "severity": "medium",
                "likelihood": "high",
                "trigger": "More than 200 candidate papers retained after abstract screening",
                "mitigation": "Apply stricter inclusion criteria and focus on primary taxonomy.",
            }
        ],
    },
    "Grant Proposal": {
        "schema_version": SCHEMA_VERSION,
        "name": "Grant Proposal",
        "version": "1.0",
        "description": "Research funding proposal lifecycle including team and budget preparation.",
        "columns": ["Idea", "Team", "Budget", "Writing", "Review", "Submitted", "Awarded / Rejected"],
        "milestones": [
            {
                "title": "Specific aims and partner commitments confirmed",
                "phase": "short_term_7d",
                "description": "One-page aims summary and co-PI letters collected.",
            },
            {
                "title": "Budget justification and workplan finalized",
                "phase": "medium_term_30d",
                "description": "Detailed budget tables and institutional sign-off ready.",
            },
            {
                "title": "Agency portal submission ready",
                "phase": "submission_ready",
                "description": "All attachments, biosketches, and narrative sections verified.",
            },
        ],
        "folders": ["Budget", "Biosketches", "Letters"],
        "risks": [
            {
                "title": "Budget cap or institutional overhead mismatch",
                "description": "Total direct/indirect costs may exceed funding agency ceiling.",
                "severity": "high",
                "likelihood": "medium",
                "trigger": "Pre-award institutional review flags budget items",
                "mitigation": "Prepare modular budget fallback scenarios early.",
            }
        ],
    },
}


def ensure_builtin_templates_on_disk(templates_dir: Path) -> list[dict[str, Any]]:
    """Write built-in templates to <root>/Templates/ if they do not exist yet."""
    templates_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for name, tpl in BUILTIN_TEMPLATES.items():
        fname = f"{safe_folder_name(name)}.json"
        fpath = templates_dir / fname
        if not fpath.exists():
            fpath.write_text(json.dumps(tpl, indent=2), encoding="utf-8")
        written.append(tpl)
    return written


def list_all_templates(templates_dir: Path) -> list[dict[str, Any]]:
    """Return all templates from <root>/Templates/, seeding built-in ones if needed."""
    ensure_builtin_templates_on_disk(templates_dir)
    results: dict[str, dict[str, Any]] = {}
    for name, tpl in BUILTIN_TEMPLATES.items():
        results[name.lower()] = dict(tpl)

    if templates_dir.exists():
        for fpath in sorted(templates_dir.glob("*.json")):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("name"):
                    results[str(data["name"]).lower()] = data
            except (OSError, json.JSONDecodeError):
                continue

    return list(results.values())


def load_template_by_name(templates_dir: Path, name: str) -> dict[str, Any]:
    """Resolve a template by name (case-insensitive) from disk or built-ins."""
    target = name.strip().lower()
    for tpl in list_all_templates(templates_dir):
        if str(tpl.get("name", "")).strip().lower() == target:
            return tpl
    raise SciTreeError(
        ERR_TEMPLATE_NOT_FOUND,
        f"Template '{name}' was not found.",
        {"template": name, "available": [t["name"] for t in list_all_templates(templates_dir)]},
    )


def save_template_from_project(
    templates_dir: Path,
    template_name: str,
    project_metadata: dict[str, Any],
    description: str | None = None,
) -> dict[str, Any]:
    """Create and save a reusable template JSON file from an existing project."""
    templates_dir.mkdir(parents=True, exist_ok=True)
    status = project_metadata.get("status", {})
    columns = status.get("column_order") or list(DEFAULT_COLUMNS)

    milestones_tpl = []
    for ms in project_metadata.get("milestones", []):
        milestones_tpl.append(
            {
                "title": ms.get("title", ""),
                "phase": ms.get("phase", "custom"),
                "description": ms.get("description", ""),
            }
        )

    risks_tpl = []
    for rsk in project_metadata.get("risks", []):
        risks_tpl.append(
            {
                "title": rsk.get("title", ""),
                "description": rsk.get("description", ""),
                "severity": rsk.get("severity", "medium"),
                "likelihood": rsk.get("likelihood", "medium"),
                "trigger": rsk.get("trigger", ""),
                "mitigation": rsk.get("mitigation", ""),
            }
        )

    tpl = {
        "schema_version": SCHEMA_VERSION,
        "name": template_name.strip(),
        "version": "1.0",
        "description": description or f"Custom template derived from project '{project_metadata.get('name', '')}'.",
        "created_at": utc_now_iso(),
        "columns": columns,
        "milestones": milestones_tpl,
        "folders": project_metadata.get("custom_folders", []),
        "risks": risks_tpl,
    }
    fname = f"{safe_folder_name(template_name)}.json"
    fpath = templates_dir / fname
    fpath.write_text(json.dumps(tpl, indent=2), encoding="utf-8")
    return tpl
