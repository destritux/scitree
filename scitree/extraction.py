"""Automated manuscript extraction for DOCX and PDF files (Requirements 6 & 7).

Extracts:
- Embedded images into Figures_Text/v{version_id}/
- Bibliography/References section into References/v{version_id}.bib and References/references_extracted.bib
- Inline [COMMENT: ...] markers and native DOCX/PDF comments
- Extraction logs and warnings into Automation/extraction_{version_id}.log
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import bibtexparser
from bibtexparser.model import Entry, Field

from scitree.models import utc_now_iso

INLINE_COMMENT_RE = re.compile(r"\[COMMENT(?:\(([^)]+)\))?:\s*(.+?)\]", re.DOTALL | re.IGNORECASE)
REF_HEADING_RE = re.compile(
    r"^\s*(?:references|bibliography|works\s+cited|literature\s+cited)\s*$",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}[a-z]?)\b")


def extract_manuscript_artifacts(
    manuscript_path: Path,
    project_dir: Path,
    version_id: str,
    default_author: str | None = None,
) -> dict[str, Any]:
    """Run image, reference, and comment extraction on a DOCX or PDF manuscript."""
    ext = manuscript_path.suffix.lower()
    figures_dir = project_dir / "Figures_Text" / version_id
    references_dir = project_dir / "References"
    automation_dir = project_dir / "Automation"

    figures_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)
    automation_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    figures_extracted = 0
    paragraphs: list[str] = []
    comments: list[dict[str, Any]] = []
    detected_doc_author = (default_author or "").strip() or "unassigned"

    if ext == ".docx":
        docx_res = _extract_from_docx(
            manuscript_path=manuscript_path,
            figures_dir=figures_dir,
            default_author=detected_doc_author,
        )
        figures_extracted = docx_res["figures_extracted"]
        paragraphs = docx_res["paragraphs"]
        comments.extend(docx_res["comments"])
        warnings.extend(docx_res["warnings"])
        if docx_res.get("doc_author"):
            detected_doc_author = docx_res["doc_author"]
    elif ext == ".pdf":
        pdf_res = _extract_from_pdf(
            manuscript_path=manuscript_path,
            figures_dir=figures_dir,
            default_author=detected_doc_author,
        )
        figures_extracted = pdf_res["figures_extracted"]
        paragraphs = pdf_res["paragraphs"]
        comments.extend(pdf_res["comments"])
        warnings.extend(pdf_res["warnings"])
        if pdf_res.get("doc_author"):
            detected_doc_author = pdf_res["doc_author"]
    else:
        # Fallback plain-text reading if another extension is supplied
        try:
            raw_text = manuscript_path.read_text(encoding="utf-8", errors="replace")
            paragraphs = [line.strip() for line in raw_text.splitlines() if line.strip()]
        except OSError as exc:
            warnings.append(f"Could not read manuscript text: {exc}")

    # Extract inline [COMMENT: ...] markers from text
    full_text = "\n".join(paragraphs)
    for match in INLINE_COMMENT_RE.finditer(full_text):
        explicit_owner = (match.group(1) or "").strip()
        comment_body = match.group(2).strip()
        full_marker = f"[COMMENT: {comment_body}]"
        owner_name = explicit_owner or detected_doc_author or "unassigned"
        owner_type = "agent" if owner_name.lower().startswith("agent:") else "human"
        comments.append(
            {
                "text": full_marker,
                "owner_type": owner_type,
                "owner_name": owner_name,
                "source": "inline_marker",
            }
        )

    # Extract and parse references into BibTeX
    ref_lines, ref_warnings = _extract_reference_lines(paragraphs)
    warnings.extend(ref_warnings)
    bib_str, refs_count, parse_warnings = _build_bibtex_from_lines(ref_lines, version_id)
    warnings.extend(parse_warnings)

    version_bib_path = references_dir / f"{version_id}.bib"
    extracted_bib_path = references_dir / "references_extracted.bib"
    version_bib_path.write_text(bib_str, encoding="utf-8")
    extracted_bib_path.write_text(bib_str, encoding="utf-8")

    # Write extraction log
    log_path = automation_dir / f"extraction_{version_id}.log"
    log_lines = [
        f"[{utc_now_iso()}] Extraction completed for version '{version_id}' ({manuscript_path.name})",
        f"Figures extracted: {figures_extracted}",
        f"References parsed: {refs_count}",
        f"Comments extracted: {len(comments)}",
    ]
    if warnings:
        log_lines.append("Warnings:")
        for w in warnings:
            log_lines.append(f"  - {w}")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    status = "success" if not warnings else ("partial" if (figures_extracted or refs_count or paragraphs) else "warning")
    return {
        "status": status,
        "figures_extracted": figures_extracted,
        "references_parsed": refs_count,
        "warnings": warnings,
        "comments": comments,
        "bib_rel_path": f"References/{version_id}.bib",
        "figures_rel_dir": f"Figures_Text/{version_id}/",
    }


def _extract_from_docx(
    manuscript_path: Path,
    figures_dir: Path,
    default_author: str,
) -> dict[str, Any]:
    import docx

    warnings: list[str] = []
    paragraphs: list[str] = []
    comments: list[dict[str, Any]] = []
    figures_extracted = 0
    doc_author = default_author

    try:
        doc = docx.Document(str(manuscript_path))
        if doc.core_properties and doc.core_properties.author:
            doc_author = str(doc.core_properties.author).strip() or default_author
        for p in doc.paragraphs:
            text = p.text.strip()
            if text:
                paragraphs.append(text)
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
    except Exception as exc:
        warnings.append(f"DOCX text parsing warning: {exc}")

    try:
        with zipfile.ZipFile(manuscript_path, "r") as zf:
            names = zf.namelist()
            media_files = sorted(n for n in names if n.startswith("word/media/") and not n.endswith("/"))
            for idx, member in enumerate(media_files, start=1):
                suffix = Path(member).suffix or ".png"
                out_name = f"fig_{idx:03d}_{Path(member).name}"
                if not out_name.lower().endswith(suffix.lower()):
                    out_name += suffix
                target = figures_dir / out_name
                target.write_bytes(zf.read(member))
                figures_extracted += 1

            # Check for Word native comments in word/comments.xml (reject DTD/ENTITY declarations for XXE safety)
            if "word/comments.xml" in names:
                xml_bytes = zf.read("word/comments.xml")
                if b"<!ENTITY" in xml_bytes.upper() or b"<!DOCTYPE" in xml_bytes.upper():
                    raise ValueError("Refusing to parse word/comments.xml containing DTD/ENTITY declarations.")
                root = ET.fromstring(xml_bytes)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for c_elem in root.findall(".//w:comment", ns):
                    c_author = c_elem.attrib.get(f"{{{ns['w']}}}author") or doc_author or "unassigned"
                    texts = [t.text for t in c_elem.findall(".//w:t", ns) if t.text]
                    body = "".join(texts).strip()
                    if body:
                        owner_type = "agent" if c_author.lower().startswith("agent:") else "human"
                        comments.append(
                            {
                                "text": body,
                                "owner_type": owner_type,
                                "owner_name": c_author,
                                "source": "docx_comment",
                            }
                        )
    except Exception as exc:
        warnings.append(f"DOCX archive media/comment extraction warning: {exc}")

    return {
        "figures_extracted": figures_extracted,
        "paragraphs": paragraphs,
        "comments": comments,
        "warnings": warnings,
        "doc_author": doc_author,
    }


def _extract_from_pdf(
    manuscript_path: Path,
    figures_dir: Path,
    default_author: str,
) -> dict[str, Any]:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    warnings: list[str] = []
    paragraphs: list[str] = []
    comments: list[dict[str, Any]] = []
    figures_extracted = 0
    doc_author = default_author

    try:
        pdf_doc = fitz.open(str(manuscript_path))
        meta = pdf_doc.metadata or {}
        if meta.get("author"):
            doc_author = str(meta["author"]).strip() or default_author

        seen_xrefs: set[int] = set()
        for page_index in range(len(pdf_doc)):
            page = pdf_doc[page_index]
            page_text = page.get_text("text") or ""
            for line in page_text.splitlines():
                stripped = line.strip()
                if stripped:
                    paragraphs.append(stripped)

            # Extract embedded images
            for img_idx, img_info in enumerate(page.get_images(full=True), start=1):
                xref = img_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    base_image = pdf_doc.extract_image(xref)
                    if base_image and base_image.get("image"):
                        ext = base_image.get("ext", "png")
                        out_file = figures_dir / f"page_{page_index + 1:02d}_img_{img_idx:02d}.{ext}"
                        out_file.write_bytes(base_image["image"])
                        figures_extracted += 1
                except Exception as img_exc:
                    warnings.append(f"Failed to extract image xref {xref} on page {page_index + 1}: {img_exc}")

            # Extract PDF annotations/comments
            annot = page.first_annot
            while annot:
                info = annot.info or {}
                content = (info.get("content") or "").strip()
                title_author = (info.get("title") or "").strip() or doc_author or "unassigned"
                if content:
                    owner_type = "agent" if title_author.lower().startswith("agent:") else "human"
                    comments.append(
                        {
                            "text": content,
                            "owner_type": owner_type,
                            "owner_name": title_author,
                            "source": "pdf_comment",
                        }
                    )
                annot = annot.next
        pdf_doc.close()
    except Exception as exc:
        warnings.append(f"PDF extraction warning: {exc}")

    return {
        "figures_extracted": figures_extracted,
        "paragraphs": paragraphs,
        "comments": comments,
        "warnings": warnings,
        "doc_author": doc_author,
    }


def _extract_reference_lines(paragraphs: list[str]) -> tuple[list[str], list[str]]:
    """Locate the References/Bibliography section and return individual reference strings."""
    warnings: list[str] = []
    start_idx: int | None = None

    for idx, para in enumerate(paragraphs):
        cleaned = re.sub(r"^[\d.\s]+", "", para).strip()
        if REF_HEADING_RE.match(cleaned):
            start_idx = idx + 1
            break

    if start_idx is None:
        warnings.append("No explicit References or Bibliography heading detected in manuscript.")
        return [], warnings

    ref_lines: list[str] = []
    for para in paragraphs[start_idx:]:
        # Stop if another major post-bibliography appendix section appears and looks like a short header
        if len(para) < 40 and re.match(r"^\s*(?:appendix|supplementary\s+material)\b", para, re.IGNORECASE):
            break
        # Strip inline comment markers from reference text
        cleaned_ref = INLINE_COMMENT_RE.sub("", para).strip()
        if cleaned_ref:
            ref_lines.append(cleaned_ref)

    if not ref_lines:
        warnings.append("References heading found, but no reference entries could be extracted.")
    return ref_lines, warnings


def _build_bibtex_from_lines(ref_lines: list[str], version_id: str) -> tuple[str, int, list[str]]:
    """Parse raw reference strings or embedded BibTeX blocks into a normalized BibTeX library."""
    warnings: list[str] = []
    if not ref_lines:
        empty_comment = f"% Generated by sciTree for {version_id} - 0 references extracted.\n"
        return empty_comment, 0, warnings

    joined = "\n".join(ref_lines)
    if "@" in joined and "{" in joined:
        try:
            lib = bibtexparser.parse_string(joined)
            if len(lib.entries) > 0:
                return bibtexparser.write_string(lib), len(lib.entries), warnings
        except Exception as exc:
            warnings.append(f"Direct BibTeX parse fallback triggered: {exc}")

    entries: list[Entry] = []
    used_keys: set[str] = set()

    for idx, line in enumerate(ref_lines, start=1):
        # Heuristic extraction of author, year, and title from standard citation strings
        cleaned = re.sub(r"^\s*(?:\[\d+\]|\d+\.)\s*", "", line).strip()
        if len(cleaned) < 8:
            continue

        year_match = YEAR_RE.search(cleaned)
        year = year_match.group(1) if year_match else "n.d."

        if year_match:
            author_part = cleaned[: year_match.start()].strip(" .,;()")
            remainder = cleaned[year_match.end() :].strip(" .,;()")
        else:
            parts = cleaned.split(".", 2)
            author_part = parts[0].strip() if parts else "Unknown"
            remainder = ".".join(parts[1:]).strip() if len(parts) > 1 else cleaned

        if not author_part:
            author_part = "Unknown"

        title_parts = [p.strip() for p in remainder.split(".") if p.strip()]
        title = title_parts[0] if title_parts else cleaned
        journal_or_note = ". ".join(title_parts[1:]) if len(title_parts) > 1 else ""

        first_surname = re.sub(r"[^a-zA-Z0-9]", "", author_part.split(",")[0].split()[0]).lower() or "ref"
        year_digits = re.sub(r"[^0-9a-z]", "", year.lower()) or f"{idx:02d}"
        base_key = f"{first_surname}{year_digits}"
        key = base_key
        suffix_num = 1
        while key in used_keys:
            suffix_num += 1
            key = f"{base_key}_{suffix_num}"
        used_keys.add(key)

        fields = [
            Field("author", author_part),
            Field("title", title),
            Field("year", year),
            Field("note", cleaned),
        ]
        if journal_or_note:
            fields.append(Field("journal", journal_or_note))

        entries.append(Entry(entry_type="article", key=key, fields=fields))

    lib = bibtexparser.Library(entries)
    bib_output = bibtexparser.write_string(lib) if entries else f"% No valid references parsed for {version_id}\n"
    return bib_output, len(entries), warnings
