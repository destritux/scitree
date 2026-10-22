"""Reproducible Submission Package Export (Section F)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from scitree import SCHEMA_VERSION
from scitree.errors import ERR_EXPORT_FAILED, ERR_VERSION_NOT_FOUND, SciTreeError
from scitree.models import compute_sha256, safe_folder_name

# Deterministic timestamp for reproducible ZIP archives: 2025-01-01 00:00:00
DETERMINISTIC_ZIP_DATE = (2025, 1, 1, 0, 0, 0)


def _write_deterministic_bytes(zf: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(filename=arcname, date_time=DETERMINISTIC_ZIP_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def build_submission_package(
    root_path: Path,
    project_dir: Path,
    project_metadata: dict[str, Any],
    version_id: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Create a reproducible .zip submission package for a project and version.

    Includes:
    - Manuscript file of chosen (or latest) version
    - All text figures from Figures_Text/v{n}/
    - Generated .bib file
    - metadata.json with project name, version_id, state, authors, submission date,
      changelog, and SHA-256 file checksums
    - comments_manifest.json with extracted comments and resolution state
    """
    versions = project_metadata.get("versions", [])
    target_vid = version_id or project_metadata.get("latest_version_id")
    if not target_vid and versions:
        target_vid = versions[-1]["version_id"]

    if not target_vid:
        raise SciTreeError(
            ERR_VERSION_NOT_FOUND,
            f"Project '{project_metadata.get('name')}' has no versions to export.",
            {"project": project_metadata.get("name")},
        )

    version_obj: dict[str, Any] | None = None
    for v in versions:
        if v.get("version_id") == target_vid:
            version_obj = v
            break

    if not version_obj:
        raise SciTreeError(
            ERR_VERSION_NOT_FOUND,
            f"Version '{target_vid}' not found in project '{project_metadata.get('name')}'.",
            {"project": project_metadata.get("name"), "version_id": target_vid},
        )

    exports_dir = root_path / "Exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    proj_safe = safe_folder_name(project_metadata.get("name", "Project"))
    zip_filename = f"{proj_safe}_{target_vid}_submission.zip"
    final_zip_path = output_path.expanduser().resolve() if output_path else (exports_dir / zip_filename)
    final_zip_path.parent.mkdir(parents=True, exist_ok=True)

    files_to_pack: list[tuple[str, bytes]] = []
    checksums: dict[str, str] = {}

    v_files = version_obj.get("files") or {}
    manuscript_rel = v_files.get("manuscript")
    if manuscript_rel:
        ms_path = project_dir / manuscript_rel
        if ms_path.exists() and ms_path.is_file():
            data = ms_path.read_bytes()
            arcname = f"manuscript/{ms_path.name}"
            files_to_pack.append((arcname, data))
            checksums[arcname] = f"sha256:{hashlib.sha256(data).hexdigest()}"

    figures_rel = v_files.get("figures_dir") or f"Figures_Text/{target_vid}/"
    figures_dir = project_dir / figures_rel
    if figures_dir.exists() and figures_dir.is_dir():
        for fig_file in sorted(figures_dir.iterdir()):
            if fig_file.is_file():
                data = fig_file.read_bytes()
                arcname = f"figures/{fig_file.name}"
                files_to_pack.append((arcname, data))
                checksums[arcname] = f"sha256:{hashlib.sha256(data).hexdigest()}"

    bib_rel = v_files.get("bib") or f"References/{target_vid}.bib"
    bib_path = project_dir / bib_rel
    if not bib_path.exists():
        alt_bib = project_dir / "References" / "references_extracted.bib"
        if alt_bib.exists():
            bib_path = alt_bib
    if bib_path.exists() and bib_path.is_file():
        data = bib_path.read_bytes()
        arcname = f"references/{bib_path.name}"
        files_to_pack.append((arcname, data))
        checksums[arcname] = f"sha256:{hashlib.sha256(data).hexdigest()}"

    # Filter comments for this version (or all project comments if version unspecified on comment)
    all_comments = project_metadata.get("comments", [])
    version_comments = [
        {
            "comment_id": c.get("comment_id"),
            "version": c.get("version"),
            "text": c.get("text"),
            "owner_type": c.get("owner_type"),
            "owner_name": c.get("owner_name"),
            "status": c.get("status"),
            "source": c.get("source"),
            "created_at": c.get("created_at"),
            "resolved_at": c.get("resolved_at"),
        }
        for c in all_comments
        if c.get("version") in {None, target_vid}
    ]
    comments_manifest_Payload = {
        "schema_version": SCHEMA_VERSION,
        "project": project_metadata.get("name"),
        "version_id": target_vid,
        "total_comments": len(version_comments),
        "pending_count": sum(1 for c in version_comments if c.get("status") == "pending"),
        "resolved_count": sum(1 for c in version_comments if c.get("status") == "resolved"),
        "comments": version_comments,
    }
    comments_bytes = json.dumps(comments_manifest_Payload, indent=2, sort_keys=True).encode("utf-8")
    checksums["comments_manifest.json"] = f"sha256:{hashlib.sha256(comments_bytes).hexdigest()}"

    package_metadata = {
        "schema_version": SCHEMA_VERSION,
        "project_name": project_metadata.get("name"),
        "project_id": project_metadata.get("project_id"),
        "version_id": target_vid,
        "version_state": version_obj.get("state", "draft"),
        "immutable": bool(version_obj.get("immutable", False)),
        "derived_from": version_obj.get("derived_from"),
        "authors": project_metadata.get("authors", []),
        "version_author": version_obj.get("author"),
        "submission_date": version_obj.get("submitted_at"),
        "submitted_to": version_obj.get("submitted_to"),
        "changelog": version_obj.get("changelog", ""),
        "checksums": dict(sorted(checksums.items())),
    }
    metadata_bytes = json.dumps(package_metadata, indent=2, sort_keys=True).encode("utf-8")

    try:
        with zipfile.ZipFile(final_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, content in sorted(files_to_pack, key=lambda item: item[0]):
                _write_deterministic_bytes(zf, arcname, content)
            _write_deterministic_bytes(zf, "comments_manifest.json", comments_bytes)
            _write_deterministic_bytes(zf, "metadata.json", metadata_bytes)
    except OSError as exc:
        raise SciTreeError(
            ERR_EXPORT_FAILED,
            f"Failed to write submission package zip '{final_zip_path}': {exc}",
            {"output_path": str(final_zip_path)},
        ) from exc

    zip_checksum = compute_sha256(final_zip_path)
    try:
        rel_export_path = str(final_zip_path.relative_to(root_path))
    except ValueError:
        rel_export_path = str(final_zip_path)

    return {
        "version": target_vid,
        "path": rel_export_path,
        "absolute_path": str(final_zip_path),
        "checksum": zip_checksum,
        "included_files": list(sorted(checksums.keys())) + ["metadata.json"],
        "package_metadata": package_metadata,
    }
