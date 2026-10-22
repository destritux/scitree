"""Optional Zotero collection synchronization via local Zotero HTTP API (Section H)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import bibtexparser
import httpx
from bibtexparser.model import Entry, Field

from scitree.errors import ERR_VALIDATION_ERROR, ERR_ZOTERO_UNAVAILABLE, SciTreeError
from scitree.models import utc_now_iso

DEFAULT_ZOTERO_BASE_URL = "http://127.0.0.1:23119/api"
COLLECTION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def get_zotero_base_url() -> str:
    return os.environ.get("SCITREE_ZOTERO_API_URL", DEFAULT_ZOTERO_BASE_URL).rstrip("/")


def sync_zotero_collection(
    project_dir: Path,
    zotero_config: dict[str, Any],
    strict: bool = False,
) -> dict[str, Any]:
    """Synchronize a linked Zotero collection into References/references_zotero.bib.

    Rules (Section H):
    - Preserves References/references_extracted.bib; writes References/references_zotero.bib.
    - Version-aware: compares item versions and only rewrites the file when items changed.
    - Degrades gracefully when Zotero is unreachable unless strict=True.
    """
    collection_key = (zotero_config.get("collection_key") or "").strip()
    if not zotero_config.get("linked") or not collection_key:
        raise SciTreeError(
            ERR_ZOTERO_UNAVAILABLE,
            "Project is not linked to a Zotero collection.",
            {"linked": False},
        )
    if not COLLECTION_KEY_RE.match(collection_key):
        raise SciTreeError(
            ERR_VALIDATION_ERROR,
            f"Invalid Zotero collection_key '{collection_key}'.",
            {"collection_key": collection_key},
        )

    base_url = get_zotero_base_url()
    items_url = f"{base_url}/users/0/collections/{collection_key}/items"
    previous_versions: dict[str, int] = dict(zotero_config.get("item_versions") or {})
    bib_rel_path = "References/references_zotero.bib"
    bib_full_path = project_dir / bib_rel_path
    bib_full_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(timeout=3.5) as client:
            resp = client.get(items_url, params={"format": "json", "limit": 100})
            resp.raise_for_status()
            items = resp.json()
    except Exception as exc:
        updated_cfg = dict(zotero_config)
        updated_cfg["last_sync_at"] = utc_now_iso()
        updated_cfg["last_sync_status"] = "unavailable"
        updated_cfg["last_error"] = str(exc)
        if strict:
            raise SciTreeError(
                ERR_ZOTERO_UNAVAILABLE,
                f"Local Zotero API at '{base_url}' is unavailable: {exc}",
                {"collection_key": collection_key, "url": items_url},
            ) from exc
        return {
            "synced": False,
            "changed": False,
            "status": "unavailable",
            "warning": f"Local Zotero API unavailable: {exc}",
            "zotero": updated_cfg,
        }

    if not isinstance(items, list):
        items = []

    current_versions: dict[str, int] = {}
    entries: list[Entry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        version = int(item.get("version") or 0)
        data = item.get("data") or {}
        item_type = str(data.get("itemType") or "article").lower()
        if item_type in {"attachment", "note"}:
            continue
        if key:
            current_versions[key] = version

        title = str(data.get("title") or "Untitled")
        date_str = str(data.get("date") or "n.d.")
        creators = data.get("creators") or []
        author_names: list[str] = []
        for c in creators:
            if isinstance(c, dict):
                last = c.get("lastName") or c.get("name") or ""
                first = c.get("firstName") or ""
                full = f"{last}, {first}".strip(", ")
                if full:
                    author_names.append(full)
        author_field = " and ".join(author_names) if author_names else "Unknown"
        pub_title = str(data.get("publicationTitle") or "")

        fields = [
            Field("author", author_field),
            Field("title", title),
            Field("year", date_str[:4] if len(date_str) >= 4 else date_str),
        ]
        if pub_title:
            fields.append(Field("journal", pub_title))
        if data.get("DOI"):
            fields.append(Field("doi", str(data["DOI"])))

        cite_key = key or f"zotero_{len(entries) + 1}"
        entries.append(Entry(entry_type="article", key=cite_key, fields=fields))

    changed = (current_versions != previous_versions) or (not bib_full_path.exists())
    if changed:
        lib = bibtexparser.Library(entries)
        bib_content = (
            bibtexparser.write_string(lib)
            if entries
            else f"% Zotero collection {collection_key} synced (0 items)\n"
        )
        bib_full_path.write_text(bib_content, encoding="utf-8")

    updated_cfg = dict(zotero_config)
    updated_cfg["last_sync_at"] = utc_now_iso()
    updated_cfg["last_sync_status"] = "success"
    updated_cfg["bib_file"] = bib_rel_path
    updated_cfg["item_versions"] = current_versions
    updated_cfg["items_count"] = len(entries)
    updated_cfg.pop("last_error", None)

    return {
        "synced": True,
        "changed": changed,
        "items_count": len(entries),
        "status": "success",
        "zotero": updated_cfg,
    }
