#!/usr/bin/env python3
"""Sample automated agent invocation script for sciTree.

Demonstrates programmatic usage across:
1. Direct Python Core API (scitree.core.SciTreeCore)
2. Declarative Manifest ingestion (examples/example_manifest.json)
3. Watch-folder inbox processing (<root>/Automation/inbox/)
4. Reproducible submission package export
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

import docx

from scitree.core import SciTreeCore
from scitree.models import validate_actor


def _create_sample_assets(asset_dir: Path) -> dict[str, Path]:
    """Generate a synthetic DOCX manuscript (with embedded image, Word comment, and references), CSV, and PNG."""
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Minimal valid 1x1 PNG bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    fig_path = asset_dir / "sample_figure.png"
    fig_path.write_bytes(png_bytes)

    csv_path = asset_dir / "sample_data.csv"
    csv_path.write_text("subject_id,condition,sleep_score\nS01,control,74.2\nS02,treatment,86.5\n", encoding="utf-8")

    docx_path = asset_dir / "sample_manuscript_v1.docx"
    doc = docx.Document()
    doc.core_properties.author = "Jane Doe"
    doc.add_heading("Alpha Study: Sleep Quality and Cognitive Performance", level=1)
    doc.add_paragraph(
        "Introduction text discussing longitudinal sleep architecture. "
        "[COMMENT(agent:claude): Verify whether Figure 1 supports the baseline comparison.]"
    )
    doc.add_picture(str(fig_path))
    doc.add_heading("References", level=1)
    doc.add_paragraph("Smith, J., & Doe, J. (2024). Sleep spindles and memory consolidation. Journal of Sleep Research, 33(2), 101-115.")
    doc.add_paragraph("Silva, M. (2023). Circadian alignment in graduate cohorts. Nature Human Behaviour, 7, 45-58.")
    doc.save(str(docx_path))

    return {"manuscript": docx_path, "csv": csv_path, "figure": fig_path}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="scitree_agent_demo_") as tmp:
        tmp_path = Path(tmp)
        os.environ["SCITREE_STATE_FILE"] = str(tmp_path / "bootstrap.json")
        workspace_root = tmp_path / "workspace"
        assets_dir = tmp_path / "assets"
        _create_sample_assets(assets_dir)

        # Copy example_manifest.json into assets_dir so relative file paths resolve
        repo_dir = Path(__file__).resolve().parent
        manifest_data = json.loads((repo_dir / "example_manifest.json").read_text(encoding="utf-8"))
        manifest_data["root"] = str(workspace_root)
        manifest_data.pop("auto_root", None)

        core = SciTreeCore(root_path=workspace_root)
        agent_actor = validate_actor(
            actor_name="agent:demo-bot",
            actor_type="agent",
            actor_source="cli",
        )

        print("1. Applying declarative manifest...")
        report = core.apply_manifest(manifest_data, manifest_dir=assets_dir, actor=agent_actor)
        print(json.dumps(report["summary"], indent=2))

        print("\n2. Promoting version v1 to 'submitted' (making it immutable)...")
        promote_res = core.update_version_state(
            project_name="Alpha Study",
            version_id="v1",
            state="submitted",
            submitted_to="Journal of Sleep Research",
            actor=agent_actor,
        )
        print(
            f"Version v1 state={promote_res['version']['state']}, "
            f"immutable={promote_res['version']['immutable']}"
        )

        print("\n3. Querying project Timeline / Route View...")
        timeline = core.get_timeline(project_name="Alpha Study")
        print(f"Total timeline events recorded: {timeline['total_events']}")
        for ev in timeline["events"][:5]:
            print(f"  - [{ev['timestamp']}] {ev['event_type']} by {ev['actor']['actor_name']}")

        print("\n4. Testing watch-folder inbox ingestion...")
        inbox_manifest = workspace_root / "Automation" / "inbox" / "delta_update.json"
        inbox_manifest.write_text(
            json.dumps(
                {
                    "project": {"name": "Alpha Study"},
                    "activity_notes": [{"note": "Processed via Automation/inbox watch folder."}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        inbox_res = core.process_inbox_once()
        print(f"Inbox manifests processed: {inbox_res['processed_count']}")

        # Verify exported submission zip
        exports = promote_res["project"].get("exports", [])
        if exports:
            zip_file = workspace_root / exports[0]["path"]
            with zipfile.ZipFile(zip_file, "r") as zf:
                print(f"\n5. Exported submission package contents ({zip_file.name}):")
                for member in zf.namelist():
                    print(f"  - {member}")


if __name__ == "__main__":
    main()
