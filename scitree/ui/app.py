"""Minimalist, modern Flet desktop application for sciTree (Dark & Light Themes).

All user-facing mutations invoke SciTreeCore with actor_source='ui' or execute
scitree CLI commands directly through the integrated CLI command console.
Supports:
- Dark Mode (default) and Light Mode toggle
- Board (Kanban with drag-and-drop), List/Table, and Timeline/Route views
- Collapsible compact paper list + expanded Paper & File Workspace on paper click
- Full-width expandable In-App Article Editor (.tex/.bib/.md/.py/.csv) with Maximize Editor mode
- Interactive File Explorer, Image/CSV/PDF/DOCX previewer, and smart pdflatex compiler
- Integrated CLI Command Bar & Console with one-click article editing presets
"""

from __future__ import annotations

import csv
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import flet as ft
from typer.testing import CliRunner

from scitree.cli import app as cli_typer_app
from scitree.config import get_recommended_root_path
from scitree.core import SciTreeCore
from scitree.errors import ERR_VERSION_CONFLICT, SciTreeError
from scitree.models import (
    MILESTONE_PHASE_ORDER,
    VALID_RISK_LIKELIHOODS,
    VALID_RISK_SEVERITIES,
    validate_actor,
)
from scitree.templates import DEFAULT_COLUMNS

DARK_PALETTE = {
    "BG_APP": "#0B0F19",
    "BG_SURFACE": "#111827",
    "BG_SUBTLE": "#1E293B",
    "BORDER_COLOR": "#334155",
    "TEXT_PRIMARY": "#F8FAFC",
    "TEXT_SECONDARY": "#CBD5E1",
    "TEXT_MUTED": "#94A3B8",
    "ACCENT_BLUE": "#3B82F6",
    "ACCENT_BLUE_LIGHT": "#1E3A8A",
    "BADGE_GREEN_BG": "#064E3B",
    "BADGE_GREEN_FG": "#6EE7B7",
    "BADGE_AMBER_BG": "#78350F",
    "BADGE_AMBER_FG": "#FCD34D",
    "BADGE_RED_BG": "#7F1D1D",
    "BADGE_RED_FG": "#FCA5A5",
    "BADGE_PURPLE_BG": "#4C1D95",
    "BADGE_PURPLE_FG": "#DDD6FE",
}

LIGHT_PALETTE = {
    "BG_APP": "#F8FAFC",
    "BG_SURFACE": "#FFFFFF",
    "BG_SUBTLE": "#F1F5F9",
    "BORDER_COLOR": "#E2E8F0",
    "TEXT_PRIMARY": "#0F172A",
    "TEXT_SECONDARY": "#475569",
    "TEXT_MUTED": "#64748B",
    "ACCENT_BLUE": "#2563EB",
    "ACCENT_BLUE_LIGHT": "#EFF6FF",
    "BADGE_GREEN_BG": "#DCFCE7",
    "BADGE_GREEN_FG": "#166534",
    "BADGE_AMBER_BG": "#FEF3C7",
    "BADGE_AMBER_FG": "#92400E",
    "BADGE_RED_BG": "#FEE2E2",
    "BADGE_RED_FG": "#991B1B",
    "BADGE_PURPLE_BG": "#F3E8FF",
    "BADGE_PURPLE_FG": "#6B21A8",
}

TEXT_EXTENSIONS = {".tex", ".bib", ".md", ".txt", ".py", ".json", ".yaml", ".yml", ".log", ".sh", ".cfg", ".ini"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
CSV_EXTENSIONS = {".csv", ".tsv"}
DOC_EXTENSIONS = {".pdf", ".docx", ".doc"}
IGNORED_AUX_EXTENSIONS = {".aux", ".out", ".blg", ".bbl", ".toc", ".lof", ".lot", ".fls", ".fdb_latexmk", ".synctex"}


def _make_dropdown(
    label: str | None = None,
    width: int | None = None,
    value: str | None = None,
    options: list[Any] | None = None,
    on_select: Any = None,
) -> ft.Dropdown:
    """Create a Flet Dropdown compatible with both Flet 1.0+ (on_select) and 0.2x (on_change)."""
    try:
        return ft.Dropdown(
            label=label,
            width=width,
            value=value,
            options=options or [],
            on_select=on_select,
        )
    except TypeError:
        return ft.Dropdown(  # type: ignore[call-arg]
            label=label,
            width=width,
            value=value,
            options=options or [],
            on_change=on_select,
        )


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


class SciTreeDesktopUI:
    """Controller and view builder for the sciTree Flet desktop interface."""

    def __init__(self, page: ft.Page, initial_root: str | None = None) -> None:
        self.page = page
        self.core = SciTreeCore(root_path=initial_root)
        self.actor = validate_actor(actor_name="local-user", actor_type="human", actor_source="ui")
        self.cli_runner = CliRunner()

        # Cached in-memory dataset so switching views does not reload from disk (Section A4)
        self.projects_cache: list[dict[str, Any]] = []
        self.templates_cache: list[dict[str, Any]] = []
        self.selected_project_name: str | None = None
        self.active_drawer_tab: str = "files"
        self.show_automation_panel: bool = False

        # Per-paper file & editor workspace state
        self.file_category_filter: str = "all"
        self.selected_file_relpath: str | None = None
        self.csv_edit_raw_mode: bool = False
        self.editor_maximized: bool = False

        # Integrated CLI console state
        self.cli_command_text: str = ""
        self.cli_output_text: str = (
            "Integrated sciTree CLI ready. Click any command preset or type a scitree command "
            "(e.g., project show --name \"...\") and press Run CLI."
        )

        # Shared filter/sort & theme state across Board, List, and Timeline views
        root_status = self.core.get_root_status()
        ui_state = root_status.get("ui_state") or {}
        self.current_view: str = ui_state.get("last_view", "board")
        self.dark_mode: bool = bool(ui_state.get("dark_mode", True))
        self.search_query: str = ""
        self.owner_filter: str = "all"
        self.column_filter: str = "all"
        self.author_filter: str = ""
        self.only_pending_comments: bool = False
        self.sort_by: str = "updated_at"

        # Activity log filter state
        self.act_actor_type: str = "all"
        self.act_actor_source: str = "all"
        self.act_event_type: str = ""

        # Notice message banner
        self.notice_message: str = ""

        self._apply_palette()
        self._configure_page()
        self.file_picker = ft.FilePicker()
        if hasattr(self.page, "services"):
            self.page.services.append(self.file_picker)
        elif hasattr(self.page, "overlay"):
            self.page.overlay.append(self.file_picker)

        self.root_container = ft.Container(expand=True, bgcolor=self.BG_APP)
        self.page.add(self.root_container)

        configured_root = root_status.get("root_path")
        root_exists = bool(configured_root and Path(str(configured_root)).exists())
        if not root_status.get("onboarding_completed") or not root_exists:
            self._render_onboarding_step1()
        else:
            self._reload_data_from_core()
            self._render_main_workspace()

    def _apply_palette(self) -> None:
        pal = DARK_PALETTE if self.dark_mode else LIGHT_PALETTE
        self.BG_APP = pal["BG_APP"]
        self.BG_SURFACE = pal["BG_SURFACE"]
        self.BG_SUBTLE = pal["BG_SUBTLE"]
        self.BORDER_COLOR = pal["BORDER_COLOR"]
        self.TEXT_PRIMARY = pal["TEXT_PRIMARY"]
        self.TEXT_SECONDARY = pal["TEXT_SECONDARY"]
        self.TEXT_MUTED = pal["TEXT_MUTED"]
        self.ACCENT_BLUE = pal["ACCENT_BLUE"]
        self.ACCENT_BLUE_LIGHT = pal["ACCENT_BLUE_LIGHT"]
        self.BADGE_GREEN_BG = pal["BADGE_GREEN_BG"]
        self.BADGE_GREEN_FG = pal["BADGE_GREEN_FG"]
        self.BADGE_AMBER_BG = pal["BADGE_AMBER_BG"]
        self.BADGE_AMBER_FG = pal["BADGE_AMBER_FG"]
        self.BADGE_RED_BG = pal["BADGE_RED_BG"]
        self.BADGE_RED_FG = pal["BADGE_RED_FG"]
        self.BADGE_PURPLE_BG = pal["BADGE_PURPLE_BG"]
        self.BADGE_PURPLE_FG = pal["BADGE_PURPLE_FG"]

    def _configure_page(self) -> None:
        self.page.title = "sciTree - Scientific Project and Manuscript Workspace"
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark_mode else ft.ThemeMode.LIGHT
        self.page.bgcolor = self.BG_APP
        self.page.padding = 0

    def _toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self._apply_palette()
        self._configure_page()
        self.root_container.bgcolor = self.BG_APP
        try:
            st = self.core.state_manager.load()
            ui_st = dict(st.get("ui_state") or {})
            ui_st["dark_mode"] = self.dark_mode
            self.core.state_manager.save(
                onboarding_completed=bool(st.get("onboarding_completed", True)),
                root_path=st.get("root_path"),
                api_token=st.get("api_token"),
                ui_state=ui_st,
            )
        except Exception:
            pass
        self._render_main_workspace()

    def _set_notice(self, msg: str) -> None:
        self.notice_message = msg
        self._render_main_workspace()

    def _reload_data_from_core(self) -> None:
        try:
            res = self.core.list_projects()
            self.projects_cache = res.get("projects", [])
            tpl_res = self.core.list_templates()
            self.templates_cache = tpl_res.get("templates", [])
            if self.selected_project_name:
                if not any(p["name"] == self.selected_project_name for p in self.projects_cache):
                    self.selected_project_name = None
        except SciTreeError as exc:
            self.notice_message = f"[{exc.code}] {exc.message}"

    def _get_project_dir(self, project_name: str) -> Path | None:
        try:
            info = self.core.get_project(project_name)
            return Path(info["project_dir"])
        except Exception:
            return None

    def _collect_project_files(self, proj: dict[str, Any]) -> list[dict[str, Any]]:
        """Scan the paper's folder on disk and return a structured list of all project files."""
        pdir = self._get_project_dir(proj["name"])
        if not pdir or not pdir.exists():
            return []

        items: list[dict[str, Any]] = []
        seen_rel: set[str] = set()

        folder_categories = [
            ("Versions", "manuscripts", "Manuscripts & LaTeX"),
            ("Figures_Standalone", "figures", "Figures (Standalone)"),
            ("Figures_Text", "figures", "Figures (Extracted)"),
            ("Data", "data", "Datasets (CSV)"),
            ("References", "references", "References (.bib)"),
            ("Scripts", "scripts", "Scripts & Code"),
            ("Protocols", "scripts", "Protocols & Notes"),
        ]

        for folder_name, cat_key, cat_label in folder_categories:
            sub = pdir / folder_name
            if not sub.exists():
                continue
            for fpath in sorted(sub.rglob("*")):
                if not fpath.is_file() or fpath.is_symlink():
                    continue
                if fpath.suffix.lower() in IGNORED_AUX_EXTENSIONS:
                    continue
                rel = str(fpath.relative_to(pdir))
                if rel in seen_rel:
                    continue
                seen_rel.add(rel)
                try:
                    st = fpath.stat()
                    size_b = st.st_size
                except OSError:
                    size_b = 0
                items.append(
                    {
                        "rel_path": rel,
                        "abs_path": fpath,
                        "name": fpath.name,
                        "ext": fpath.suffix.lower(),
                        "category": cat_key,
                        "category_label": cat_label,
                        "size_bytes": size_b,
                        "size_str": _format_size(size_b),
                    }
                )

        for root_f in ("metadata.json", "activity_log.jsonl"):
            rf_path = pdir / root_f
            if rf_path.exists() and rf_path.is_file():
                st_size = rf_path.stat().st_size
                items.append(
                    {
                        "rel_path": root_f,
                        "abs_path": rf_path,
                        "name": root_f,
                        "ext": rf_path.suffix.lower(),
                        "category": "scripts",
                        "category_label": "Metadata & Logs",
                        "size_bytes": st_size,
                        "size_str": _format_size(st_size),
                    }
                )

        return items

    def _open_path_externally(self, target_path: Path) -> None:
        """Open a file or folder in the user's native OS viewer/editor."""
        if not target_path.exists():
            self._set_notice(f"Path does not exist: {target_path}")
            return
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(target_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif os.name == "nt":
                os.startfile(str(target_path))  # type: ignore[attr-defined]
            self._set_notice(f"Opened in system application: {target_path.name}")
        except Exception as exc:
            self._set_notice(f"Could not open externally: {exc}")

    def _execute_cli_command(self, cmd_str: str) -> None:
        """Execute a scitree CLI command in-process and refresh workspace state."""
        raw = (cmd_str or "").strip()
        if not raw:
            return
        self.cli_command_text = raw
        try:
            tokens = shlex.split(raw)
        except ValueError as exc:
            self.cli_output_text = f"Command parse error: {exc}"
            self._render_main_workspace()
            return

        if tokens and tokens[0] in ("scitree", "./scitree"):
            tokens = tokens[1:]

        if not tokens:
            tokens = ["--help"]

        try:
            result = self.cli_runner.invoke(cli_typer_app, tokens)
            out = (result.output or "").strip()
            header = f"$ scitree {' '.join(shlex.quote(t) for t in tokens)}\n[exit_code={result.exit_code}]\n"
            self.cli_output_text = header + (out if out else "(No output)")
        except Exception as exc:
            self.cli_output_text = f"$ scitree {raw}\n[execution error]: {exc}"

        self._reload_data_from_core()
        self._render_main_workspace()

    def _get_filtered_projects(self) -> list[dict[str, Any]]:
        """Filter and sort the in-memory projects_cache instantaneously (Section A2 & A4)."""
        result: list[dict[str, Any]] = []
        for p in self.projects_cache:
            status = p.get("status", {})
            if self.column_filter != "all" and status.get("column", "").lower() != self.column_filter.lower():
                continue
            if self.owner_filter != "all":
                p_match = status.get("owner_type", "human") == self.owner_filter
                c_match = any(
                    c.get("owner_type") == self.owner_filter and c.get("status") == "pending"
                    for c in p.get("comments", [])
                )
                if not (p_match or c_match):
                    continue
            if self.only_pending_comments:
                if int(p.get("comments_summary", {}).get("pending", 0)) == 0:
                    continue
            if self.author_filter.strip():
                qa = self.author_filter.strip().lower()
                authors = [str(a.get("name", "")).lower() for a in p.get("authors", [])]
                v_authors = [str(v.get("author", "")).lower() for v in p.get("versions", [])]
                if not any(qa in a for a in authors + v_authors):
                    continue
            if self.search_query.strip():
                q = self.search_query.strip().lower()
                haystack = " ".join(
                    [
                        str(p.get("name", "")),
                        str(p.get("description", "")),
                        str(status.get("column", "")),
                        str(status.get("owner_name", "")),
                        " ".join(str(v.get("author", "")) for v in p.get("versions", [])),
                    ]
                ).lower()
                if q not in haystack:
                    continue
            result.append(p)

        if self.sort_by == "name":
            result.sort(key=lambda x: str(x.get("name", "")).lower())
        elif self.sort_by == "column":
            result.sort(key=lambda x: str(x.get("status", {}).get("column", "")).lower())
        else:
            result.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        return result

    # ------------------------------------------------------------------
    # First-Run Onboarding (Requirement 1 & Section I1)
    # ------------------------------------------------------------------
    def _render_onboarding_step1(self) -> None:
        rec_path = str(get_recommended_root_path())
        custom_path_field = ft.TextField(
            label="Root Folder Path",
            value=rec_path,
            width=410,
            border_color=self.BORDER_COLOR,
        )

        async def on_browse_native(_: Any) -> None:
            try:
                picked = await self.file_picker.get_directory_path(
                    dialog_title="Select sciTree Root Folder",
                )
                if picked:
                    custom_path_field.value = picked
                    self.page.update()
            except Exception:
                pass

        async def on_choose_folder(_: Any) -> None:
            current_val = (custom_path_field.value or "").strip()
            if not current_val or current_val == rec_path:
                try:
                    picked = await self.file_picker.get_directory_path(
                        dialog_title="Select sciTree Root Folder",
                    )
                    if picked:
                        current_val = picked
                        custom_path_field.value = picked
                except Exception:
                    pass
            chosen = current_val or rec_path
            self.core.init_root(root_path=chosen, actor=self.actor)
            self.notice_message = f"Workspace initialized at: {chosen}"
            self._render_onboarding_step2()

        def on_use_recommended(_: Any) -> None:
            res = self.core.init_root(auto_root=True, actor=self.actor)
            self.notice_message = f"Using recommended workspace location: {res['root_path']}"
            self._render_onboarding_step2()

        def on_skip_and_use_recommended(_: Any) -> None:
            res = self.core.init_root(auto_root=True, actor=self.actor)
            self.notice_message = (
                f"Folder selection skipped. Files are stored in the recommended OS location: {res['root_path']}"
            )
            self._reload_data_from_core()
            self._render_main_workspace()

        card = ft.Container(
            width=640,
            padding=32,
            bgcolor=self.BG_SURFACE,
            border=ft.Border.all(1, self.BORDER_COLOR),
            border_radius=12,
            content=ft.Column(
                tight=True,
                spacing=18,
                controls=[
                    ft.Text("Welcome to sciTree - First-Run Setup", size=22, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    ft.Text(
                        "Choose the root folder where all scientific projects, manuscript versions, "
                        "extracted figures, references, and automation logs will be stored locally.",
                        size=14,
                        color=self.TEXT_SECONDARY,
                    ),
                    ft.Container(
                        padding=12,
                        bgcolor=self.BG_SUBTLE,
                        border_radius=8,
                        content=ft.Text(f"Recommended OS Location: {rec_path}", size=13, color=self.TEXT_PRIMARY),
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            custom_path_field,
                            ft.OutlinedButton("Browse...", on_click=on_browse_native),
                        ],
                    ),
                    ft.Row(
                        spacing=12,
                        controls=[
                            ft.Button(
                                "Choose folder",
                                bgcolor=self.ACCENT_BLUE,
                                color="#FFFFFF",
                                on_click=on_choose_folder,
                            ),
                            ft.OutlinedButton(
                                "Use recommended location",
                                on_click=on_use_recommended,
                            ),
                            ft.TextButton(
                                "Skip and use recommended location",
                                on_click=on_skip_and_use_recommended,
                            ),
                        ],
                    ),
                ],
            ),
        )
        self.root_container.content = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=card,
        )
        self.page.update()

    def _render_onboarding_step2(self) -> None:
        """Optional second onboarding step: Template Picker (Section I1)."""
        self._reload_data_from_core()
        proj_name_input = ft.TextField(
            label="Initial Project Name (optional)",
            value="Alpha Study",
            width=480,
            border_color=self.BORDER_COLOR,
        )
        tpl_names = [t["name"] for t in self.templates_cache] or ["Empirical Paper", "Review Article", "Grant Proposal"]
        selected_tpl = {"name": tpl_names[0]}

        tpl_dropdown = _make_dropdown(
            label="Select Project Template",
            width=480,
            value=tpl_names[0],
            options=[ft.dropdown.Option(name) for name in tpl_names],
            on_select=lambda e: selected_tpl.update({"name": e.control.value}),
        )

        def on_create_from_template(_: Any) -> None:
            pname = (proj_name_input.value or "").strip()
            if pname:
                self.core.create_project(
                    name=pname,
                    template_name=selected_tpl["name"],
                    actor=self.actor,
                )
                self.selected_project_name = pname
            self._reload_data_from_core()
            self._render_main_workspace()

        def on_skip_template(_: Any) -> None:
            self._reload_data_from_core()
            self._render_main_workspace()

        card = ft.Container(
            width=600,
            padding=32,
            bgcolor=self.BG_SURFACE,
            border=ft.Border.all(1, self.BORDER_COLOR),
            border_radius=12,
            content=ft.Column(
                tight=True,
                spacing=16,
                controls=[
                    ft.Text("Step 2 (Optional): Start from a Template", size=20, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    ft.Text(
                        "Choose a workflow template (Empirical Paper, Review Article, or Grant Proposal) "
                        "to initialize lifecycle columns, milestones, and risk categories, or skip to open an empty board.",
                        size=13,
                        color=self.TEXT_SECONDARY,
                    ),
                    proj_name_input,
                    tpl_dropdown,
                    ft.Row(
                        spacing=12,
                        controls=[
                            ft.Button(
                                "Create Project with Template",
                                bgcolor=self.ACCENT_BLUE,
                                color="#FFFFFF",
                                on_click=on_create_from_template,
                            ),
                            ft.TextButton("Skip", on_click=on_skip_template),
                        ],
                    ),
                ],
            ),
        )
        self.root_container.content = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, 0),
            content=card,
        )
        self.page.update()

    # ------------------------------------------------------------------
    # Main Workspace Layout
    # ------------------------------------------------------------------
    def _switch_view(self, view_name: str) -> None:
        self.current_view = view_name
        self.selected_project_name = None
        self.core.state_manager.update_ui_state(last_view=view_name)
        self._render_main_workspace()

    def _render_main_workspace(self) -> None:
        header = self._build_top_bar()
        controls: list[ft.Control] = [header]

        if not (self.selected_project_name and self.editor_maximized):
            controls.append(self._build_filter_bar())

        if self.notice_message:
            controls.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=20, vertical=8),
                    bgcolor=self.ACCENT_BLUE_LIGHT,
                    border=ft.Border.only(bottom=ft.BorderSide(1, self.BORDER_COLOR)),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(self.notice_message, size=13, color=self.TEXT_PRIMARY),
                            ft.TextButton("Dismiss", on_click=lambda _: self._set_notice("")),
                        ],
                    ),
                )
            )

        body_row_items: list[ft.Control] = []

        if self.selected_project_name:
            expanded_workspace = self._build_expanded_paper_workspace(self.selected_project_name)
            if expanded_workspace is not None:
                if not self.editor_maximized:
                    body_row_items.append(self._build_compact_paper_sidebar())
                body_row_items.append(expanded_workspace)
            else:
                self.selected_project_name = None

        if not self.selected_project_name:
            if self.current_view == "list":
                main_view = self._build_list_view()
            elif self.current_view == "timeline":
                main_view = self._build_timeline_view()
            else:
                main_view = self._build_board_view()
            body_row_items.append(ft.Container(expand=True, content=main_view))

        if self.show_automation_panel:
            body_row_items.append(self._build_automation_panel())

        controls.append(
            ft.Container(
                expand=True,
                content=ft.Row(
                    expand=True,
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=body_row_items,
                ),
            )
        )

        self.root_container.content = ft.Column(expand=True, spacing=0, controls=controls)
        self.page.update()

    def _build_top_bar(self) -> ft.Control:
        root_status = self.core.get_root_status()
        root_label = root_status.get("root_path") or "Unconfigured"

        def make_view_btn(label: str, key: str) -> ft.Control:
            is_active = (self.current_view == key) and (self.selected_project_name is None)
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=14, vertical=6),
                bgcolor=self.ACCENT_BLUE if is_active else self.BG_SUBTLE,
                border_radius=6,
                on_click=lambda _: self._switch_view(key),
                content=ft.Text(
                    label,
                    size=13,
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                    color="#FFFFFF" if is_active else self.TEXT_PRIMARY,
                ),
            )

        theme_label = "Theme: Dark" if self.dark_mode else "Theme: Light"

        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=12),
            bgcolor=self.BG_SURFACE,
            border=ft.Border.only(bottom=ft.BorderSide(1, self.BORDER_COLOR)),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=16,
                        controls=[
                            ft.Text("sciTree", size=20, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                bgcolor=self.BG_SUBTLE,
                                border_radius=4,
                                content=ft.Text(f"Root: {root_label}", size=11, color=self.TEXT_MUTED),
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Button(
                                "+ New Project",
                                bgcolor=self.ACCENT_BLUE,
                                color="#FFFFFF",
                                on_click=lambda _: self._open_new_project_modal(),
                            ),
                            ft.OutlinedButton(
                                theme_label,
                                on_click=lambda _: self._toggle_theme(),
                            ),
                            ft.OutlinedButton(
                                "Automation Panel",
                                on_click=lambda _: self._toggle_automation_panel(),
                            ),
                            ft.OutlinedButton(
                                "Root Settings",
                                on_click=lambda _: self._open_settings_modal(),
                            ),
                            ft.Container(width=8),
                            ft.Row(
                                spacing=4,
                                controls=[
                                    make_view_btn("Board", "board"),
                                    make_view_btn("List", "list"),
                                    make_view_btn("Timeline", "timeline"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        )

    def _build_filter_bar(self) -> ft.Control:
        search_field = ft.TextField(
            hint_text="Search projects, authors, descriptions...",
            value=self.search_query,
            width=250,
            height=36,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_color=self.BORDER_COLOR,
            on_change=lambda e: self._update_search(e.control.value),
        )

        def make_owner_chip(label: str, val: str) -> ft.Control:
            active = self.owner_filter == val
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=5),
                bgcolor=self.ACCENT_BLUE if active else self.BG_SURFACE,
                border=ft.Border.all(1, self.ACCENT_BLUE if active else self.BORDER_COLOR),
                border_radius=16,
                on_click=lambda _: self._set_owner_filter(val),
                content=ft.Text(
                    label,
                    size=12,
                    color="#FFFFFF" if active else self.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL,
                ),
            )

        pending_cb = ft.Checkbox(
            label="Has pending comments",
            value=self.only_pending_comments,
            on_change=lambda e: self._set_pending_filter(bool(e.control.value)),
        )

        sort_dd = _make_dropdown(
            width=165,
            value=self.sort_by,
            options=[
                ft.dropdown.Option("updated_at", "Sort: Updated"),
                ft.dropdown.Option("name", "Sort: Name"),
                ft.dropdown.Option("column", "Sort: Column"),
            ],
            on_select=lambda e: self._set_sort_order(e.control.value or "updated_at"),
        )

        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=8),
            bgcolor=self.BG_SURFACE,
            border=ft.Border.only(bottom=ft.BorderSide(1, self.BORDER_COLOR)),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            search_field,
                            ft.Text("Tasks:", size=12, color=self.TEXT_MUTED),
                            make_owner_chip("All", "all"),
                            make_owner_chip("My tasks", "human"),
                            make_owner_chip("Agent tasks", "agent"),
                            pending_cb,
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            sort_dd,
                            ft.OutlinedButton("Refresh Disk", on_click=lambda _: self._refresh_all()),
                        ],
                    ),
                ],
            ),
        )

    def _update_search(self, val: str) -> None:
        self.search_query = val
        self._render_main_workspace()

    def _set_owner_filter(self, val: str) -> None:
        self.owner_filter = val
        self._render_main_workspace()

    def _set_pending_filter(self, val: bool) -> None:
        self.only_pending_comments = val
        self._render_main_workspace()

    def _set_sort_order(self, val: str) -> None:
        self.sort_by = val
        self._render_main_workspace()

    def _refresh_all(self) -> None:
        self._reload_data_from_core()
        self._render_main_workspace()

    def _toggle_automation_panel(self) -> None:
        self.show_automation_panel = not self.show_automation_panel
        self._render_main_workspace()

    # ------------------------------------------------------------------
    # Collapsed Left Sidebar when a Paper is Selected
    # ------------------------------------------------------------------
    def _build_compact_paper_sidebar(self) -> ft.Control:
        projects = self._get_filtered_projects()
        items: list[ft.Control] = []
        for p in projects:
            pname = p["name"]
            is_sel = pname == self.selected_project_name
            col = p.get("status", {}).get("column", "Idea")
            lvid = p.get("latest_version_id") or "no-ver"
            n_data = len(p.get("files", {}).get("data", []))
            n_fig = len(p.get("files", {}).get("figures_standalone", []))
            items.append(
                ft.Container(
                    padding=10,
                    bgcolor=self.ACCENT_BLUE_LIGHT if is_sel else self.BG_SURFACE,
                    border=ft.Border.all(2 if is_sel else 1, self.ACCENT_BLUE if is_sel else self.BORDER_COLOR),
                    border_radius=8,
                    on_click=lambda _, pn=pname: self._select_project(pn),
                    content=ft.Column(
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Text(
                                pname,
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color=self.TEXT_PRIMARY,
                                max_lines=2,
                            ),
                            ft.Row(
                                spacing=6,
                                wrap=True,
                                controls=[
                                    ft.Container(
                                        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                        bgcolor=self.ACCENT_BLUE if is_sel else self.BG_SUBTLE,
                                        border_radius=4,
                                        content=ft.Text(
                                            col,
                                            size=10,
                                            weight=ft.FontWeight.BOLD,
                                            color="#FFFFFF" if is_sel else self.TEXT_SECONDARY,
                                        ),
                                    ),
                                    ft.Text(f"{lvid} | {n_fig} figs | {n_data} CSVs", size=10, color=self.TEXT_MUTED),
                                ],
                            ),
                        ],
                    ),
                )
            )

        return ft.Container(
            width=225,
            padding=12,
            bgcolor=self.BG_SUBTLE,
            border=ft.Border.only(right=ft.BorderSide(1, self.BORDER_COLOR)),
            content=ft.Column(
                expand=True,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Button(
                        "<- Back to Full Board",
                        width=200,
                        bgcolor=self.ACCENT_BLUE,
                        color="#FFFFFF",
                        on_click=lambda _: self._close_drawer(),
                    ),
                    ft.Text(f"Papers ({len(projects)})", size=12, weight=ft.FontWeight.BOLD, color=self.TEXT_SECONDARY),
                    *items,
                ],
            ),
        )

    # ------------------------------------------------------------------
    # View 1: Kanban Board View (Requirement 3, Sections A, B3, D3, I7)
    # ------------------------------------------------------------------
    def _get_board_columns(self, projects: list[dict[str, Any]]) -> list[str]:
        cols: list[str] = []
        for p in projects:
            for c in p.get("status", {}).get("column_order", DEFAULT_COLUMNS):
                if c not in cols:
                    cols.append(c)
            curr = p.get("status", {}).get("column")
            if curr and curr not in cols:
                cols.append(curr)
        if not cols:
            cols = list(DEFAULT_COLUMNS)
        return cols

    def _build_board_view(self) -> ft.Control:
        projects = self._get_filtered_projects()
        columns = self._get_board_columns(self.projects_cache or projects)

        col_controls: list[ft.Control] = []
        for col_name in columns:
            col_projects = [p for p in projects if p.get("status", {}).get("column") == col_name]
            cards = [self._build_kanban_card(p, columns) for p in col_projects]
            has_items = len(col_projects) > 0
            col_width = 270 if has_items else 118

            column_box = ft.Container(
                width=col_width,
                padding=10 if not has_items else 12,
                bgcolor=self.BG_SUBTLE,
                border=ft.Border.all(1, self.ACCENT_BLUE if has_items else self.BORDER_COLOR),
                border_radius=10,
                content=ft.Column(
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(col_name, size=12 if not has_items else 14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                ft.Container(
                                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                                    bgcolor=self.ACCENT_BLUE if has_items else self.BG_SURFACE,
                                    border_radius=10,
                                    content=ft.Text(
                                        str(len(col_projects)),
                                        size=11,
                                        weight=ft.FontWeight.BOLD if has_items else ft.FontWeight.NORMAL,
                                        color="#FFFFFF" if has_items else self.TEXT_SECONDARY,
                                    ),
                                ),
                            ],
                        ),
                        ft.Column(spacing=10, controls=cards),
                    ],
                ),
            )

            drag_target = ft.DragTarget(
                group="kanban_cards",
                content=column_box,
                on_accept=lambda e, target_col=col_name: self._on_card_dropped(e, target_col),
            )
            col_controls.append(drag_target)

        return ft.Container(
            expand=True,
            padding=14,
            content=ft.Row(
                spacing=8,
                scroll=ft.ScrollMode.ALWAYS,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=col_controls,
            ),
        )

    def _on_card_dropped(self, e: Any, target_col: str) -> None:
        try:
            src_control = self.page.get_control(e.src_id)
            proj_name = src_control.data if src_control else None
        except Exception:
            proj_name = getattr(e, "data", None)
        if proj_name:
            self.core.move_project(name=str(proj_name), column=target_col, actor=self.actor)
            self._reload_data_from_core()
            self._render_main_workspace()

    def _build_kanban_card(self, project: dict[str, Any], all_columns: list[str]) -> ft.Control:
        pname = project["name"]
        versions = project.get("versions", [])
        latest_vid = project.get("latest_version_id")
        is_locked = bool(project.get("latest_version_locked", False))
        latest_author = "No versions uploaded"
        latest_state = "none"
        if latest_vid:
            for v in reversed(versions):
                if v.get("version_id") == latest_vid:
                    latest_author = v.get("author", "Unknown")
                    latest_state = v.get("state", "draft")
                    break

        pending_comments = int(project.get("comments_summary", {}).get("pending", 0))
        high_crit_risks = int(project.get("risks_summary", {}).get("high_or_critical_open", 0))
        next_due = project.get("milestones_summary", {}).get("next_due")
        owner_type = project.get("status", {}).get("owner_type", "human")
        n_data = len(project.get("files", {}).get("data", []))
        n_figs = len(project.get("files", {}).get("figures_standalone", []))

        version_badge_text = f"Latest: {latest_vid} ({latest_state})" if latest_vid else "No Version"
        if is_locked:
            version_badge_text += " [LOCKED]"

        badges_row: list[ft.Control] = [
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                bgcolor=self.BADGE_GREEN_BG if is_locked else self.ACCENT_BLUE_LIGHT,
                border_radius=4,
                content=ft.Text(
                    version_badge_text,
                    size=11,
                    weight=ft.FontWeight.BOLD,
                    color=self.BADGE_GREEN_FG if is_locked else self.TEXT_PRIMARY,
                ),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=6, vertical=3),
                bgcolor=self.BG_SUBTLE,
                border_radius=4,
                content=ft.Text(f"Owner: {owner_type}", size=10, color=self.TEXT_SECONDARY),
            ),
        ]

        files_summary_row = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            bgcolor=self.BG_SUBTLE,
            border_radius=4,
            content=ft.Text(
                f"Files: {len(versions)} versions | {n_figs} figures | {n_data} datasets",
                size=11,
                color=self.TEXT_PRIMARY,
                weight=ft.FontWeight.W_500,
            ),
        )

        indicators: list[ft.Control] = []
        if pending_comments > 0:
            indicators.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    bgcolor=self.BADGE_AMBER_BG,
                    border_radius=4,
                    content=ft.Text(f"Comments: {pending_comments}", size=11, color=self.BADGE_AMBER_FG),
                )
            )
        if high_crit_risks > 0:
            indicators.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    bgcolor=self.BADGE_RED_BG,
                    border_radius=4,
                    content=ft.Text(f"High/Crit Risks: {high_crit_risks}", size=11, color=self.BADGE_RED_FG),
                )
            )
        if next_due:
            indicators.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    bgcolor=self.BADGE_PURPLE_BG,
                    border_radius=4,
                    content=ft.Text(f"Next Due: {next_due}", size=11, color=self.BADGE_PURPLE_FG),
                )
            )

        curr_col = project.get("status", {}).get("column", "Idea")
        curr_idx = all_columns.index(curr_col) if curr_col in all_columns else 0
        move_buttons: list[ft.Control] = []
        if curr_idx > 0:
            prev_c = all_columns[curr_idx - 1]
            move_buttons.append(
                ft.TextButton(
                    f"<- {prev_c}",
                    on_click=lambda _, pn=pname, tc=prev_c: self._move_card_click(pn, tc),
                )
            )
        if curr_idx < len(all_columns) - 1:
            next_c = all_columns[curr_idx + 1]
            move_buttons.append(
                ft.TextButton(
                    f"{next_c} ->",
                    on_click=lambda _, pn=pname, tc=next_c: self._move_card_click(pn, tc),
                )
            )

        is_selected = self.selected_project_name == pname
        card_visual = ft.Container(
            width=244,
            padding=12,
            bgcolor=self.BG_SURFACE,
            border=ft.Border.all(2 if is_selected else 1, self.ACCENT_BLUE if is_selected else self.BORDER_COLOR),
            border_radius=8,
            on_click=lambda _, pn=pname: self._select_project(pn),
            content=ft.Column(
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Text(pname, size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    ft.Row(wrap=True, spacing=6, run_spacing=4, controls=badges_row),
                    files_summary_row,
                    ft.Text(f"Submitted by: {latest_author}", size=11, color=self.TEXT_SECONDARY),
                    ft.Row(wrap=True, spacing=6, run_spacing=4, controls=indicators) if indicators else ft.Container(),
                    ft.Button(
                        "Open Paper Files & Editor ->",
                        width=218,
                        bgcolor=self.ACCENT_BLUE,
                        color="#FFFFFF",
                        on_click=lambda _, pn=pname: self._select_project(pn),
                    ),
                    ft.Row(spacing=4, controls=move_buttons) if move_buttons else ft.Container(),
                ],
            ),
        )

        return ft.Draggable(
            group="kanban_cards",
            data=pname,
            content=card_visual,
            content_feedback=ft.Container(
                width=240,
                padding=10,
                bgcolor=self.ACCENT_BLUE_LIGHT,
                border=ft.Border.all(1, self.ACCENT_BLUE),
                border_radius=8,
                content=ft.Text(pname, size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
            ),
        )

    def _move_card_click(self, project_name: str, target_column: str) -> None:
        self.core.move_project(name=project_name, column=target_column, actor=self.actor)
        self._reload_data_from_core()
        self._render_main_workspace()

    def _select_project(self, project_name: str) -> None:
        if self.selected_project_name != project_name:
            self.selected_project_name = project_name
            self.selected_file_relpath = None
            self.active_drawer_tab = "files"
        self._render_main_workspace()

    # ------------------------------------------------------------------
    # View 2: List / Table View (Section A1 & A2)
    # ------------------------------------------------------------------
    def _build_list_view(self) -> ft.Control:
        projects = self._get_filtered_projects()
        rows: list[ft.DataRow] = []
        for p in projects:
            pname = p["name"]
            col = p.get("status", {}).get("column", "")
            owner = f"{p.get('status', {}).get('owner_type', 'human')}:{p.get('status', {}).get('owner_name', '')}"
            lvid = p.get("latest_version_id") or "-"
            if p.get("latest_version_locked"):
                lvid = f"{lvid} [LOCKED]"
            n_files = (
                len(p.get("versions", []))
                + len(p.get("files", {}).get("data", []))
                + len(p.get("files", {}).get("figures_standalone", []))
            )
            pending_c = str(p.get("comments_summary", {}).get("pending", 0))
            hc_risks = str(p.get("risks_summary", {}).get("high_or_critical_open", 0))
            next_due = str(p.get("milestones_summary", {}).get("next_due") or "-")

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.TextButton(
                                pname,
                                on_click=lambda _, pn=pname: self._select_project(pn),
                            )
                        ),
                        ft.DataCell(ft.Text(col, size=13, color=self.TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(lvid, size=13, weight=ft.FontWeight.BOLD, color=self.ACCENT_BLUE)),
                        ft.DataCell(ft.Text(str(n_files), size=13, color=self.TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(owner, size=12, color=self.TEXT_SECONDARY)),
                        ft.DataCell(ft.Text(pending_c, size=13, color=self.TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(hc_risks, size=13, color=self.BADGE_RED_FG if hc_risks != "0" else self.TEXT_MUTED)),
                        ft.DataCell(ft.Text(next_due, size=12, color=self.TEXT_SECONDARY)),
                    ]
                )
            )

        table = ft.DataTable(
            border=ft.Border.all(1, self.BORDER_COLOR),
            border_radius=8,
            heading_row_color=self.BG_SUBTLE,
            columns=[
                ft.DataColumn(ft.Text("Paper / Project", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Column", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Latest Version", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Tracked Files", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Owner", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Pending Comments", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("High/Crit Risks", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Next Milestone", weight=ft.FontWeight.BOLD)),
            ],
            rows=rows,
        )
        return ft.Container(
            expand=True,
            padding=24,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"Papers Table ({len(projects)}) - Click any paper title to expand its File & CLI Workspace",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=self.TEXT_PRIMARY,
                    ),
                    table,
                ],
            ),
        )

    # ------------------------------------------------------------------
    # View 3: Timeline / Route View (Section C)
    # ------------------------------------------------------------------
    def _build_timeline_view(self) -> ft.Control:
        projects = self._get_filtered_projects()
        target_name = self.selected_project_name or (projects[0]["name"] if projects else None)
        if not target_name:
            return ft.Container(
                padding=32,
                content=ft.Text("No project available to display Timeline / Route View.", size=14, color=self.TEXT_MUTED),
            )

        proj_selector = _make_dropdown(
            label="Project Timeline",
            width=280,
            value=target_name,
            options=[ft.dropdown.Option(p["name"]) for p in self.projects_cache],
            on_select=lambda e: self._select_project(e.control.value or target_name),
        )
        note_input = ft.TextField(
            hint_text="Add a manual note to this project's timeline...",
            width=420,
            height=38,
            border_color=self.BORDER_COLOR,
        )

        def on_add_note(_: Any) -> None:
            val = (note_input.value or "").strip()
            if val:
                self.core.add_timeline_note(project_name=target_name, note=val, actor=self.actor)
                self._reload_data_from_core()
                self._render_main_workspace()

        tl_data = self.core.get_timeline(project_name=target_name)
        day_groups: list[ft.Control] = []
        for day_obj in tl_data.get("days", []):
            ev_cards: list[ft.Control] = []
            for ev in day_obj.get("events", []):
                ev_type = ev.get("event_type", "")
                actor_obj = ev.get("actor", {})
                payload = ev.get("payload", {})
                is_lock_event = ev_type in {"version.locked", "version.submitted", "version.published"}
                lock_tag = " [LOCKED]" if is_lock_event else ""
                ev_cards.append(
                    ft.Container(
                        padding=10,
                        bgcolor=self.BG_SURFACE,
                        border=ft.Border.all(1, self.BORDER_COLOR),
                        border_radius=6,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            f"{ev_type}{lock_tag}",
                                            size=13,
                                            weight=ft.FontWeight.BOLD,
                                            color=self.ACCENT_BLUE,
                                        ),
                                        ft.Text(str(payload), size=12, color=self.TEXT_SECONDARY),
                                    ],
                                ),
                                ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                    spacing=2,
                                    controls=[
                                        ft.Text(str(ev.get("timestamp", "")), size=11, color=self.TEXT_MUTED),
                                        ft.Text(
                                            f"{actor_obj.get('actor_name')} ({actor_obj.get('actor_type')}/{actor_obj.get('actor_source')})",
                                            size=11,
                                            color=self.TEXT_SECONDARY,
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    )
                )
            day_groups.append(
                ft.Container(
                    padding=12,
                    bgcolor=self.BG_SUBTLE,
                    border_radius=8,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text(f"Date: {day_obj['date']}", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                            *ev_cards,
                        ],
                    ),
                )
            )

        return ft.Container(
            expand=True,
            padding=24,
            content=ft.Column(
                expand=True,
                spacing=14,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(
                        spacing=12,
                        controls=[
                            proj_selector,
                            note_input,
                            ft.Button("Add Note", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_add_note),
                        ],
                    ),
                    *day_groups,
                ],
            ),
        )

    # ------------------------------------------------------------------
    # Expanded Paper Workspace (Files & Editor, CLI Console, Versions, Comments, Risks, Milestones, Activity)
    # ------------------------------------------------------------------
    def _build_expanded_paper_workspace(self, project_name: str) -> ft.Control | None:
        proj = next((p for p in self.projects_cache if p["name"] == project_name), None)
        if not proj:
            return None

        pdir = self._get_project_dir(project_name)
        all_files = self._collect_project_files(proj)

        def switch_tab(tab_key: str) -> None:
            self.active_drawer_tab = tab_key
            self._render_main_workspace()

        def tab_btn(label: str, key: str) -> ft.Control:
            active = self.active_drawer_tab == key
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=7),
                bgcolor=self.ACCENT_BLUE if active else self.BG_SUBTLE,
                border_radius=6,
                on_click=lambda _: switch_tab(key),
                content=ft.Text(
                    label,
                    size=12,
                    weight=ft.FontWeight.BOLD if active else ft.FontWeight.NORMAL,
                    color="#FFFFFF" if active else self.TEXT_PRIMARY,
                ),
            )

        if self.active_drawer_tab == "cli":
            tab_body = self._build_drawer_cli_tab(proj, all_files)
        elif self.active_drawer_tab == "versions":
            tab_body = self._build_drawer_versions_tab(proj)
        elif self.active_drawer_tab == "comments":
            tab_body = self._build_drawer_comments_tab(proj)
        elif self.active_drawer_tab == "risks":
            tab_body = self._build_drawer_risks_tab(proj)
        elif self.active_drawer_tab == "milestones":
            tab_body = self._build_drawer_milestones_tab(proj)
        elif self.active_drawer_tab == "activity":
            tab_body = self._build_drawer_activity_tab(proj)
        else:
            tab_body = self._build_drawer_files_tab(proj, all_files)

        def on_export_package(_: Any) -> None:
            try:
                res = self.core.export_package(project_name=project_name, actor=self.actor)
                self._reload_data_from_core()
                self._set_notice(f"Exported submission package: {res['export']['path']}")
            except SciTreeError as exc:
                self._set_notice(f"Export error [{exc.code}]: {exc.message}")

        cols = proj.get("status", {}).get("column_order", DEFAULT_COLUMNS)
        curr_col = proj.get("status", {}).get("column", cols[0] if cols else "Idea")
        stage_dd = _make_dropdown(
            label="Kanban Stage",
            width=155,
            value=curr_col,
            options=[ft.dropdown.Option(c) for c in cols],
            on_select=lambda e: self._move_card_click(project_name, e.control.value or curr_col),
        )

        # Quick embedded CLI bar at bottom of the paper workspace
        quick_cli_input = ft.TextField(
            value=self.cli_command_text or f'project show --name "{project_name}"',
            hint_text='Run scitree CLI command (e.g. comment add --project "..." --text "...")',
            expand=True,
            height=36,
            text_style=ft.TextStyle(font_family="monospace", size=12, color=self.TEXT_PRIMARY),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_color=self.BORDER_COLOR,
            on_submit=lambda e: self._execute_cli_command(e.control.value or ""),
        )

        def make_cli_preset_chip(label: str, cmd_template: str, run_now: bool = False) -> ft.Control:
            def _on_click(_: Any) -> None:
                self.cli_command_text = cmd_template
                if run_now:
                    self._execute_cli_command(cmd_template)
                else:
                    self.active_drawer_tab = "cli"
                    self._render_main_workspace()

            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                bgcolor=self.BG_SURFACE,
                border=ft.Border.all(1, self.BORDER_COLOR),
                border_radius=4,
                on_click=_on_click,
                content=ft.Text(label, size=11, font_family="monospace", color=self.ACCENT_BLUE),
            )

        quick_cli_bar = ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            bgcolor=self.BG_SUBTLE,
            border=ft.Border.only(top=ft.BorderSide(1, self.BORDER_COLOR)),
            content=ft.Column(
                spacing=6,
                tight=True,
                controls=[
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Text("CLI Bar:", size=12, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                            quick_cli_input,
                            ft.Button(
                                "Run CLI",
                                bgcolor=self.ACCENT_BLUE,
                                color="#FFFFFF",
                                on_click=lambda _: self._execute_cli_command(quick_cli_input.value or ""),
                            ),
                            ft.OutlinedButton(
                                "Full CLI Console",
                                on_click=lambda _: switch_tab("cli"),
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=6,
                        wrap=True,
                        controls=[
                            ft.Text("Article CLI Presets:", size=11, color=self.TEXT_MUTED),
                            make_cli_preset_chip(
                                "project show",
                                f'project show --name "{project_name}"',
                                run_now=True,
                            ),
                            make_cli_preset_chip(
                                "version list",
                                f'version list --project "{project_name}"',
                                run_now=True,
                            ),
                            make_cli_preset_chip(
                                "comment add",
                                f'comment add --project "{project_name}" --text "Revise section" --version {proj.get("latest_version_id") or "v1"}',
                            ),
                            make_cli_preset_chip(
                                "version add",
                                f'version add --project "{project_name}" --file "{pdir / "Versions/v2/manuscript.pdf" if pdir else ""}" --author "Thiago Francisco de Carvalho Oliveira" --changelog "Updated manuscript"',
                            ),
                            make_cli_preset_chip(
                                "version submit (lock)",
                                f'version submit --project "{project_name}" --version {proj.get("latest_version_id") or "v2"}',
                            ),
                            make_cli_preset_chip(
                                "export package",
                                f'export package --project "{project_name}"',
                                run_now=True,
                            ),
                        ],
                    ),
                ],
            ),
        )

        return ft.Container(
            expand=True,
            bgcolor=self.BG_SURFACE,
            content=ft.Column(
                expand=True,
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    # Paper Header
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                        bgcolor=self.BG_SURFACE,
                        border=ft.Border.only(bottom=ft.BorderSide(1, self.BORDER_COLOR)),
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Column(
                                            spacing=2,
                                            expand=True,
                                            controls=[
                                                ft.Text(proj["name"], size=18, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                                ft.Text(
                                                    proj.get("description") or "No description.",
                                                    size=12,
                                                    color=self.TEXT_SECONDARY,
                                                    max_lines=1,
                                                ),
                                            ],
                                        ),
                                        ft.Row(
                                            spacing=8,
                                            controls=[
                                                stage_dd,
                                                ft.OutlinedButton(
                                                    "Open Folder",
                                                    on_click=lambda _: self._open_path_externally(pdir) if pdir else None,
                                                ),
                                                ft.OutlinedButton(
                                                    "Add File",
                                                    on_click=lambda _: self._open_add_file_modal(project_name),
                                                ),
                                                ft.Button(
                                                    "Export Package",
                                                    bgcolor=self.ACCENT_BLUE,
                                                    color="#FFFFFF",
                                                    on_click=on_export_package,
                                                ),
                                                ft.OutlinedButton(
                                                    "<- Board",
                                                    on_click=lambda _: self._close_drawer(),
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                ft.Row(
                                    spacing=6,
                                    wrap=True,
                                    controls=[
                                        tab_btn(f"Files & Article Editor ({len(all_files)})", "files"),
                                        tab_btn("CLI & Article Commands", "cli"),
                                        tab_btn(f"Versions ({len(proj.get('versions', []))})", "versions"),
                                        tab_btn(f"Comments ({len(proj.get('comments', []))})", "comments"),
                                        tab_btn(f"Risks ({len(proj.get('risks', []))})", "risks"),
                                        tab_btn(f"Milestones ({len(proj.get('milestones', []))})", "milestones"),
                                        tab_btn("Activity Log", "activity"),
                                    ],
                                ),
                            ],
                        ),
                    ),
                    # Main Tab Content Area
                    ft.Container(
                        expand=True,
                        padding=12,
                        content=tab_body,
                    ),
                    # Persistent Bottom CLI Bar
                    quick_cli_bar,
                ],
            ),
        )

    def _close_drawer(self) -> None:
        self.selected_project_name = None
        self.editor_maximized = False
        self._render_main_workspace()

    # ------------------------------------------------------------------
    # Tab 1: Paper Files Explorer, Previewer & In-App Article Editor
    # ------------------------------------------------------------------
    def _build_drawer_files_tab(self, proj: dict[str, Any], all_files: list[dict[str, Any]]) -> ft.Control:
        pname = proj["name"]
        pdir = self._get_project_dir(pname)

        if self.file_category_filter == "all":
            filtered_files = all_files
        else:
            filtered_files = [f for f in all_files if f["category"] == self.file_category_filter]

        if not self.selected_file_relpath or not any(f["rel_path"] == self.selected_file_relpath for f in all_files):
            tex_cand = next((f for f in all_files if f["name"] == "01_introducao.tex"), None) or next(
                (f for f in all_files if f["ext"] == ".tex"), None
            )
            pdf_cand = next((f for f in all_files if f["ext"] == ".pdf"), None)
            first_cand = tex_cand or pdf_cand or (all_files[0] if all_files else None)
            self.selected_file_relpath = first_cand["rel_path"] if first_cand else None

        selected_file_obj = next((f for f in all_files if f["rel_path"] == self.selected_file_relpath), None)

        def set_cat_filter(cat: str) -> None:
            self.file_category_filter = cat
            self._render_main_workspace()

        def select_file(rel_p: str) -> None:
            self.selected_file_relpath = rel_p
            self.csv_edit_raw_mode = False
            self._render_main_workspace()

        def make_cat_chip(label: str, key: str) -> ft.Control:
            active = self.file_category_filter == key
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                bgcolor=self.ACCENT_BLUE if active else self.BG_SURFACE,
                border=ft.Border.all(1, self.ACCENT_BLUE if active else self.BORDER_COLOR),
                border_radius=12,
                on_click=lambda _: set_cat_filter(key),
                content=ft.Text(
                    label,
                    size=11,
                    weight=ft.FontWeight.BOLD if active else ft.FontWeight.NORMAL,
                    color="#FFFFFF" if active else self.TEXT_SECONDARY,
                ),
            )

        file_list_controls: list[ft.Control] = []
        for fobj in filtered_files:
            rel_p = fobj["rel_path"]
            is_sel = rel_p == self.selected_file_relpath
            file_list_controls.append(
                ft.Container(
                    padding=8,
                    bgcolor=self.ACCENT_BLUE_LIGHT if is_sel else self.BG_SURFACE,
                    border=ft.Border.all(2 if is_sel else 1, self.ACCENT_BLUE if is_sel else self.BORDER_COLOR),
                    border_radius=6,
                    on_click=lambda _, rp=rel_p: select_file(rp),
                    content=ft.Column(
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        fobj["name"],
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=self.TEXT_PRIMARY,
                                    ),
                                    ft.Text(fobj["size_str"], size=10, color=self.TEXT_MUTED),
                                ],
                            ),
                            ft.Text(f"{fobj['category_label']} - {rel_p}", size=10, color=self.TEXT_SECONDARY),
                        ],
                    ),
                )
            )

        left_explorer = ft.Container(
            width=285,
            padding=10,
            bgcolor=self.BG_SUBTLE,
            border=ft.Border.all(1, self.BORDER_COLOR),
            border_radius=8,
            content=ft.Column(
                expand=True,
                spacing=8,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(f"Paper Files ({len(filtered_files)})", size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                            ft.TextButton("+ New File", on_click=lambda _: self._open_create_text_file_modal(pname, pdir)),
                        ],
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=4,
                        run_spacing=4,
                        controls=[
                            make_cat_chip("All", "all"),
                            make_cat_chip("Manuscripts", "manuscripts"),
                            make_cat_chip("Figures", "figures"),
                            make_cat_chip("Data (CSV)", "data"),
                            make_cat_chip("BibTeX", "references"),
                            make_cat_chip("Scripts", "scripts"),
                        ],
                    ),
                    ft.Column(
                        expand=True,
                        spacing=6,
                        scroll=ft.ScrollMode.AUTO,
                        controls=file_list_controls,
                    ),
                ],
            ),
        )

        right_viewer = self._build_file_interactive_viewer(proj, selected_file_obj, all_files)

        row_children: list[ft.Control] = []
        if not self.editor_maximized:
            row_children.append(left_explorer)
        row_children.append(ft.Container(expand=True, content=right_viewer))

        return ft.Row(
            expand=True,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=row_children,
        )

    def _toggle_editor_maximized(self) -> None:
        self.editor_maximized = not self.editor_maximized
        self._render_main_workspace()

    def _build_file_interactive_viewer(
        self,
        proj: dict[str, Any],
        file_obj: dict[str, Any] | None,
        all_files: list[dict[str, Any]],
    ) -> ft.Control:
        if not file_obj:
            return ft.Container(
                expand=True,
                padding=24,
                bgcolor=self.BG_SUBTLE,
                border=ft.Border.all(1, self.BORDER_COLOR),
                border_radius=8,
                content=ft.Text("Select any file on the left to preview, interact, or edit.", size=13, color=self.TEXT_MUTED),
            )

        pname = proj["name"]
        abs_path: Path = file_obj["abs_path"]
        rel_path: str = file_obj["rel_path"]
        ext: str = file_obj["ext"]

        # Quick file switcher dropdown (especially useful when editor is maximized)
        quick_file_dd = _make_dropdown(
            label="Quick File Switcher",
            width=260,
            value=rel_path,
            options=[ft.dropdown.Option(f["rel_path"], f"{f['name']} ({f['category_label']})") for f in all_files],
            on_select=lambda e: self._select_file_direct(e.control.value or rel_path),
        )

        max_btn_label = "Restore File List" if self.editor_maximized else "Maximize Editor"
        action_buttons: list[ft.Control] = [
            quick_file_dd,
            ft.OutlinedButton(
                max_btn_label,
                on_click=lambda _: self._toggle_editor_maximized(),
            ),
            ft.OutlinedButton(
                "Open in System App",
                on_click=lambda _: self._open_path_externally(abs_path),
            ),
            ft.OutlinedButton(
                "Open Folder",
                on_click=lambda _: self._open_path_externally(abs_path.parent),
            ),
        ]

        body_control: ft.Control

        if ext in IMAGE_EXTENSIONS:
            body_control = ft.Container(
                expand=True,
                padding=12,
                bgcolor=self.BG_SURFACE,
                border=ft.Border.all(1, self.BORDER_COLOR),
                border_radius=8,
                alignment=ft.Alignment(0, 0),
                content=ft.Column(
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        ft.Image(
                            src=str(abs_path),
                            fit=ft.BoxFit.CONTAIN,
                            height=440,
                        ),
                        ft.Text(f"Figure Preview: {rel_path} ({file_obj['size_str']})", size=12, color=self.TEXT_SECONDARY),
                    ],
                ),
            )

        elif ext in CSV_EXTENSIONS and not self.csv_edit_raw_mode:
            action_buttons.insert(
                0,
                ft.OutlinedButton(
                    "Edit Raw CSV Text",
                    on_click=lambda _: self._toggle_csv_raw_mode(True),
                ),
            )
            headers: list[str] = []
            data_rows: list[list[str]] = []
            total_rows = 0
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    for idx, row in enumerate(reader):
                        if idx == 0:
                            headers = row[:12]
                        else:
                            total_rows += 1
                            if len(data_rows) < 25:
                                data_rows.append(row[:12])
            except Exception as exc:
                headers = ["Error"]
                data_rows = [[str(exc)]]

            if not headers:
                headers = ["Empty CSV"]

            dt = ft.DataTable(
                border=ft.Border.all(1, self.BORDER_COLOR),
                border_radius=6,
                heading_row_color=self.BG_SUBTLE,
                column_spacing=16,
                columns=[ft.DataColumn(ft.Text(h, size=11, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY)) for h in headers],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(str(cell)[:36], size=11, color=self.TEXT_SECONDARY))
                            for cell in (r + [""] * (len(headers) - len(r)))[: len(headers)]
                        ]
                    )
                    for r in data_rows
                ],
            )
            body_control = ft.Column(
                expand=True,
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"Showing first {len(data_rows)} of {total_rows} rows (up to 12 columns) from {rel_path}",
                        size=12,
                        color=self.TEXT_SECONDARY,
                    ),
                    ft.Row(scroll=ft.ScrollMode.ALWAYS, controls=[dt]),
                ],
            )

        elif ext in TEXT_EXTENSIONS or (ext in CSV_EXTENSIONS and self.csv_edit_raw_mode):
            if ext in CSV_EXTENSIONS:
                action_buttons.insert(
                    0,
                    ft.OutlinedButton(
                        "Table View",
                        on_click=lambda _: self._toggle_csv_raw_mode(False),
                    ),
                )
            try:
                raw_text = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raw_text = f"Error reading file: {exc}"

            is_truncated = len(raw_text) > 180_000
            display_text = raw_text[:180_000] if is_truncated else raw_text

            # Wrapped inside ft.Row(expand=True) with expand=True on TextField
            # so Flutter's Expanded widget stretches the editor across 100% of the width & height!
            editor_field = ft.TextField(
                value=display_text,
                expand=True,
                multiline=True,
                min_lines=22,
                max_lines=36,
                text_style=ft.TextStyle(font_family="monospace", size=13, color=self.TEXT_PRIMARY),
                bgcolor=self.BG_SURFACE,
                border_color=self.BORDER_COLOR,
            )

            def on_save_file(_: Any) -> None:
                if is_truncated:
                    self._set_notice("File is larger than 180 KB and opened in read-only preview mode.")
                    return
                try:
                    abs_path.write_text(editor_field.value or "", encoding="utf-8")
                    self._reload_data_from_core()
                    self._set_notice(f"Saved changes to {rel_path} ({_format_size(abs_path.stat().st_size)}).")
                except OSError as exc:
                    self._set_notice(f"Failed to save {rel_path}: {exc}")

            action_buttons.insert(
                0,
                ft.Button(
                    "Save File",
                    bgcolor=self.ACCENT_BLUE,
                    color="#FFFFFF",
                    on_click=on_save_file,
                ),
            )

            if ext == ".tex":
                def on_compile_latex(_: Any) -> None:
                    try:
                        abs_path.write_text(editor_field.value or "", encoding="utf-8")
                        # If editing a modular section (e.g. 01_introducao.tex), compile main.tex in the same folder
                        main_cand = abs_path.parent / "main.tex"
                        compile_target = (
                            main_cand
                            if ("\\documentclass" not in (editor_field.value or "") and main_cand.exists())
                            else abs_path
                        )
                        proc = subprocess.run(
                            ["pdflatex", "-interaction=nonstopmode", compile_target.name],
                            cwd=str(compile_target.parent),
                            capture_output=True,
                            text=True,
                            timeout=45,
                        )
                        out_pdf = compile_target.with_suffix(".pdf")
                        if out_pdf.exists() and proc.returncode == 0:
                            # Also update Versions/v2/manuscript.pdf if present
                            v2_pdf = compile_target.parent / "v2" / "manuscript.pdf"
                            if v2_pdf.parent.exists():
                                import shutil
                                shutil.copy2(out_pdf, v2_pdf)
                            self._reload_data_from_core()
                            self._set_notice(f"Compiled LaTeX successfully ({compile_target.name} -> {out_pdf.name}).")
                        else:
                            self._set_notice(f"pdflatex finished (rc={proc.returncode}) on {compile_target.name}.")
                    except Exception as exc:
                        self._set_notice(f"LaTeX compilation error: {exc}")

                action_buttons.insert(
                    1,
                    ft.OutlinedButton(
                        "Compile LaTeX (pdflatex)",
                        on_click=on_compile_latex,
                    ),
                )

            body_control = ft.Column(
                expand=True,
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Text(
                        f"In-App Article & Source Editor: {rel_path}"
                        + (" [TRUNCATED >180KB]" if is_truncated else " (Editable - full width)"),
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=self.ACCENT_BLUE,
                    ),
                    ft.Container(
                        expand=True,
                        content=ft.Row(
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                            controls=[editor_field],
                        ),
                    ),
                ],
            )

        elif ext in DOC_EXTENSIONS:
            def on_register_new_version(_: Any) -> None:
                next_v = f"v{len(proj.get('versions', [])) + 1}"
                self.cli_command_text = (
                    f'version add --project "{pname}" --file "{abs_path}" '
                    f'--author "Thiago Francisco de Carvalho Oliveira" --version-id {next_v} '
                    f'--changelog "Updated from {abs_path.name}"'
                )
                self._execute_cli_command(self.cli_command_text)

            action_buttons.insert(
                0,
                ft.Button(
                    "Register as New Version",
                    bgcolor=self.ACCENT_BLUE,
                    color="#FFFFFF",
                    on_click=on_register_new_version,
                ),
            )

            fig_companions = [f for f in all_files if f["category"] == "figures"][:8]
            tex_companions = [f for f in all_files if f["ext"] == ".tex"]
            bib_companion = next((f for f in all_files if f["ext"] == ".bib"), None)

            companion_btns: list[ft.Control] = []
            for tc in tex_companions:
                companion_btns.append(
                    ft.Button(
                        f"Edit {tc['name']}",
                        bgcolor=self.ACCENT_BLUE,
                        color="#FFFFFF",
                        on_click=lambda _, rp=tc["rel_path"]: self._select_file_direct(rp),
                    )
                )
            if bib_companion:
                companion_btns.append(
                    ft.OutlinedButton(
                        f"Edit BibTeX ({bib_companion['name']})",
                        on_click=lambda _, rp=bib_companion["rel_path"]: self._select_file_direct(rp),
                    )
                )

            thumb_cards: list[ft.Control] = []
            for fc in fig_companions:
                thumb_cards.append(
                    ft.Container(
                        width=145,
                        padding=6,
                        bgcolor=self.BG_SURFACE,
                        border=ft.Border.all(1, self.BORDER_COLOR),
                        border_radius=6,
                        on_click=lambda _, rp=fc["rel_path"]: self._select_file_direct(rp),
                        content=ft.Column(
                            spacing=4,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Image(src=str(fc["abs_path"]), height=85, fit=ft.BoxFit.CONTAIN),
                                ft.Text(fc["name"], size=10, max_lines=1, color=self.TEXT_PRIMARY),
                            ],
                        ),
                    )
                )

            body_control = ft.Column(
                expand=True,
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Container(
                        padding=14,
                        bgcolor=self.BG_SURFACE,
                        border=ft.Border.all(1, self.BORDER_COLOR),
                        border_radius=8,
                        content=ft.Column(
                            spacing=8,
                            horizontal_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Text(f"Manuscript Document: {rel_path}", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                ft.Text(
                                    f"Size: {file_obj['size_str']} | Format: {ext.upper()}. "
                                    "Click any LaTeX section below to edit the article text directly inside sciTree, "
                                    "or click 'Open in System App' to view the compiled PDF/DOCX.",
                                    size=12,
                                    color=self.TEXT_SECONDARY,
                                ),
                                ft.Row(spacing=8, wrap=True, run_spacing=6, controls=companion_btns)
                                if companion_btns
                                else ft.Container(),
                            ],
                        ),
                    ),
                    ft.Text("Paper Figures (Click any figure to inspect in high resolution):", size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    ft.Row(wrap=True, spacing=10, run_spacing=10, controls=thumb_cards),
                ],
            )
        else:
            body_control = ft.Container(
                padding=16,
                bgcolor=self.BG_SURFACE,
                border=ft.Border.all(1, self.BORDER_COLOR),
                border_radius=8,
                content=ft.Text(
                    f"Binary file ({rel_path}, {file_obj['size_str']}). Click 'Open in System App' above to interact.",
                    size=12,
                    color=self.TEXT_SECONDARY,
                ),
            )

        return ft.Container(
            expand=True,
            padding=14,
            bgcolor=self.BG_SUBTLE,
            border=ft.Border.all(1, self.BORDER_COLOR),
            border_radius=8,
            content=ft.Column(
                expand=True,
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        wrap=True,
                        controls=[
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Text(file_obj["name"], size=15, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                    ft.Text(f"Path: {rel_path} | Size: {file_obj['size_str']}", size=11, color=self.TEXT_MUTED),
                                ],
                            ),
                            ft.Row(spacing=8, wrap=True, controls=action_buttons),
                        ],
                    ),
                    ft.Divider(height=1, color=self.BORDER_COLOR),
                    ft.Container(expand=True, content=body_control),
                ],
            ),
        )

    def _select_file_direct(self, rel_path: str) -> None:
        self.selected_file_relpath = rel_path
        self.csv_edit_raw_mode = False
        self._render_main_workspace()

    def _toggle_csv_raw_mode(self, raw_mode: bool) -> None:
        self.csv_edit_raw_mode = raw_mode
        self._render_main_workspace()

    def _open_create_text_file_modal(self, project_name: str, pdir: Path | None) -> None:
        if not pdir:
            return
        rel_in = ft.TextField(
            label="Relative File Path (e.g. Versions/notes.md or Scripts/analysis.py)",
            value="Protocols/article_notes.md",
            width=420,
        )

        def on_create_file(_: Any) -> None:
            rel_val = (rel_in.value or "").strip().lstrip("/")
            if not rel_val or ".." in rel_val:
                return
            target = (pdir / rel_val).resolve()
            if not str(target).startswith(str(pdir.resolve())):
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(f"# {target.name}\n\n", encoding="utf-8")
            self._close_dialog(dlg)
            self.selected_file_relpath = str(target.relative_to(pdir))
            self._render_main_workspace()

        dlg = ft.AlertDialog(
            title=ft.Text(f"Create New Editable File in {project_name}"),
            content=ft.Column(tight=True, spacing=10, controls=[rel_in]),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Create & Edit", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_create_file),
            ],
        )
        self._show_dialog(dlg)

    # ------------------------------------------------------------------
    # Tab 2: Integrated CLI Console & Article Editing Commands
    # ------------------------------------------------------------------
    def _build_drawer_cli_tab(self, proj: dict[str, Any], all_files: list[dict[str, Any]]) -> ft.Control:
        pname = proj["name"]
        pdir = self._get_project_dir(pname)
        latest_vid = proj.get("latest_version_id") or "v2"

        cmd_input = ft.TextField(
            label="scitree CLI Command (supports all CLI subcommands & flags)",
            value=self.cli_command_text or f'project show --name "{pname}"',
            expand=True,
            text_style=ft.TextStyle(font_family="monospace", size=13, color=self.TEXT_PRIMARY),
            border_color=self.BORDER_COLOR,
            on_submit=lambda e: self._execute_cli_command(e.control.value or ""),
        )

        presets = [
            ("Inspect Project JSON", f'project show --name "{pname}" --json'),
            ("Move Column -> Submitted", f'project move --name "{pname}" --column "Submitted"'),
            ("Move Column -> Writing", f'project move --name "{pname}" --column "Writing"'),
            ("List Versions", f'version list --project "{pname}"'),
            (
                "Add New Manuscript Version",
                f'version add --project "{pname}" --file "{pdir / "Versions/v2/manuscript.pdf" if pdir else ""}" '
                f'--author "Thiago Francisco de Carvalho Oliveira" --changelog "Revised manuscript"',
            ),
            ("Lock / Submit Version", f'version submit --project "{pname}" --version {latest_vid} --to "Journal"'),
            ("Add Review Comment", f'comment add --project "{pname}" --version {latest_vid} --text "Check equations and units"'),
            ("List Comments", f'comment list --project "{pname}"'),
            ("Resolve Comment cmt_001", f'comment resolve --project "{pname}" --comment-id cmt_001'),
            ("List Milestones", f'milestone list --project "{pname}"'),
            ("Add Milestone", f'milestone add --project "{pname}" --title "Final proofread" --phase short_term_7d --due 2026-03-30'),
            ("List Risks", f'risk list --project "{pname}"'),
            ("Export Submission ZIP", f'export package --project "{pname}" --version {latest_vid}'),
            ("Show Timeline", f'timeline show --project "{pname}"'),
            ("Add Timeline Note", f'timeline note add --project "{pname}" --text "Completed internal review"'),
            ("Rebuild SQLite Index", "db rebuild"),
            ("CLI Help (--help)", "--help"),
        ]

        def set_and_run(cmd_t: str, execute: bool) -> None:
            self.cli_command_text = cmd_t
            if execute:
                self._execute_cli_command(cmd_t)
            else:
                self._render_main_workspace()

        preset_cards: list[ft.Control] = []
        for title_p, cmd_p in presets:
            preset_cards.append(
                ft.Container(
                    padding=8,
                    bgcolor=self.BG_SURFACE,
                    border=ft.Border.all(1, self.BORDER_COLOR),
                    border_radius=6,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                spacing=2,
                                expand=True,
                                controls=[
                                    ft.Text(title_p, size=12, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                    ft.Text(f"scitree {cmd_p}", size=11, font_family="monospace", color=self.TEXT_SECONDARY, max_lines=1),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.OutlinedButton("Fill", on_click=lambda _, c=cmd_p: set_and_run(c, False)),
                                    ft.Button("Run", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=lambda _, c=cmd_p: set_and_run(c, True)),
                                ],
                            ),
                        ],
                    ),
                )
            )

        output_box = ft.TextField(
            value=self.cli_output_text,
            expand=True,
            multiline=True,
            read_only=True,
            min_lines=18,
            max_lines=30,
            text_style=ft.TextStyle(font_family="monospace", size=12, color=self.TEXT_PRIMARY),
            bgcolor=self.BG_SURFACE,
            border_color=self.BORDER_COLOR,
        )

        return ft.Column(
            expand=True,
            spacing=12,
            controls=[
                ft.Row(
                    spacing=10,
                    controls=[
                        cmd_input,
                        ft.Button(
                            "Execute Command",
                            bgcolor=self.ACCENT_BLUE,
                            color="#FFFFFF",
                            on_click=lambda _: self._execute_cli_command(cmd_input.value or ""),
                        ),
                    ],
                ),
                ft.Row(
                    expand=True,
                    spacing=14,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        ft.Container(
                            width=420,
                            padding=10,
                            bgcolor=self.BG_SUBTLE,
                            border=ft.Border.all(1, self.BORDER_COLOR),
                            border_radius=8,
                            content=ft.Column(
                                expand=True,
                                spacing=6,
                                scroll=ft.ScrollMode.AUTO,
                                controls=[
                                    ft.Text("Article & Project CLI Commands", size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                    *preset_cards,
                                ],
                            ),
                        ),
                        ft.Container(
                            expand=True,
                            padding=10,
                            bgcolor=self.BG_SUBTLE,
                            border=ft.Border.all(1, self.BORDER_COLOR),
                            border_radius=8,
                            content=ft.Column(
                                expand=True,
                                spacing=6,
                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                controls=[
                                    ft.Text("CLI Output Console", size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                    ft.Container(
                                        expand=True,
                                        content=ft.Row(
                                            expand=True,
                                            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                                            controls=[output_box],
                                        ),
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            ],
        )

    def _build_drawer_versions_tab(self, proj: dict[str, Any]) -> ft.Control:
        pname = proj["name"]
        versions = [v for v in proj.get("versions", []) if not v.get("archived")]
        latest_vid = proj.get("latest_version_id")

        file_input = ft.TextField(label="Manuscript Path (.docx or .pdf)", width=410, border_color=self.BORDER_COLOR)
        vid_input = ft.TextField(label="Version ID (e.g. v1, v2)", value=f"v{len(versions) + 1}", width=195, border_color=self.BORDER_COLOR)
        author_input = ft.TextField(label="Author Name", value="Thiago Francisco de Carvalho Oliveira", width=205, border_color=self.BORDER_COLOR)
        changelog_input = ft.TextField(label="Changelog Note", width=410, border_color=self.BORDER_COLOR)
        conflict_banner = ft.Column(spacing=4)

        def submit_version(override_vid: str | None = None) -> None:
            target_vid = override_vid or (vid_input.value or "").strip() or None
            try:
                self.core.add_version(
                    project_name=pname,
                    file_path=(file_input.value or "").strip(),
                    author=(author_input.value or "").strip(),
                    version_id=target_vid,
                    changelog=(changelog_input.value or "").strip(),
                    actor=self.actor,
                )
                self._reload_data_from_core()
                self._set_notice(f"Added version '{target_vid}' to {pname}.")
            except SciTreeError as exc:
                if exc.code == ERR_VERSION_CONFLICT:
                    sug = exc.details.get("suggested_version_id", "v2a")
                    conflict_banner.controls = [
                        ft.Text(f"Warning: {exc.message}", size=12, color=self.BADGE_RED_FG),
                        ft.Button(
                            f"Use Suggested Suffix '{sug}'",
                            on_click=lambda _: submit_version(sug),
                        ),
                    ]
                    self.page.update()
                else:
                    self._set_notice(f"Error [{exc.code}]: {exc.message}")

        ver_items: list[ft.Control] = []
        for v in reversed(versions):
            vid = v["version_id"]
            is_latest = vid == latest_vid
            is_imm = bool(v.get("immutable"))
            lock_str = " [LOCKED]" if is_imm else ""
            latest_str = " [LATEST]" if is_latest else ""
            ext_info = v.get("extraction", {})
            v_file = v.get("file", "")

            action_btns: list[ft.Control] = []
            if v_file:
                action_btns.append(
                    ft.OutlinedButton(
                        f"Inspect {v_file} in Files Tab",
                        on_click=lambda _, vf=v_file: self._jump_to_file(vf),
                    )
                )
            if not is_imm:
                action_btns.append(
                    ft.TextButton(
                        "Mark Submitted (Lock)",
                        on_click=lambda _, v_id=vid: self._promote_version(pname, v_id, "submitted"),
                    )
                )
            elif v.get("state") == "submitted":
                action_btns.append(
                    ft.TextButton(
                        "Mark Published",
                        on_click=lambda _, v_id=vid: self._promote_version(pname, v_id, "published"),
                    )
                )

            ver_items.append(
                ft.Container(
                    padding=10,
                    bgcolor=self.ACCENT_BLUE_LIGHT if is_latest else self.BG_SUBTLE,
                    border=ft.Border.all(1, self.ACCENT_BLUE if is_latest else self.BORDER_COLOR),
                    border_radius=6,
                    content=ft.Column(
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Text(
                                f"{vid} ({v.get('state')}){latest_str}{lock_str}",
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=self.TEXT_PRIMARY,
                            ),
                            ft.Text(f"Author: {v.get('author')} | Uploaded: {v.get('created_at')}", size=11, color=self.TEXT_SECONDARY),
                            ft.Text(f"Changelog: {v.get('changelog') or '-'}", size=12, color=self.TEXT_PRIMARY),
                            ft.Text(
                                f"Extracted: {ext_info.get('figures_extracted', 0)} figures, "
                                f"{ext_info.get('references_parsed', 0)} references",
                                size=11,
                                color=self.TEXT_MUTED,
                            ),
                            ft.Row(spacing=6, wrap=True, controls=action_btns) if action_btns else ft.Container(),
                        ],
                    ),
                )
            )

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            controls=[
                ft.Text("Upload New Manuscript Version", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                file_input,
                ft.Row(spacing=10, controls=[vid_input, author_input]),
                changelog_input,
                conflict_banner,
                ft.Button("Upload Version", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=lambda _: submit_version()),
                ft.Divider(height=1, color=self.BORDER_COLOR),
                ft.Text(f"Version History ({len(versions)})", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                *ver_items,
            ],
        )

    def _jump_to_file(self, rel_path: str) -> None:
        self.selected_file_relpath = rel_path
        self.active_drawer_tab = "files"
        self._render_main_workspace()

    def _promote_version(self, project_name: str, version_id: str, new_state: str) -> None:
        try:
            self.core.update_version_state(
                project_name=project_name,
                version_id=version_id,
                state=new_state,
                actor=self.actor,
            )
            self._reload_data_from_core()
            self._render_main_workspace()
        except SciTreeError as exc:
            self._set_notice(f"Error [{exc.code}]: {exc.message}")

    def _build_drawer_comments_tab(self, proj: dict[str, Any]) -> ft.Control:
        pname = proj["name"]
        comments = proj.get("comments", [])
        text_input = ft.TextField(label="New Comment Text", width=520, border_color=self.BORDER_COLOR)

        def on_add_cmt(_: Any) -> None:
            val = (text_input.value or "").strip()
            if val:
                self.core.add_comment(project_name=pname, text=val, actor=self.actor)
                self._reload_data_from_core()
                self._render_main_workspace()

        cmt_controls: list[ft.Control] = []
        for c in comments:
            cid = c["comment_id"]
            is_res = c.get("status") == "resolved"
            cmt_controls.append(
                ft.Container(
                    padding=8,
                    bgcolor=self.BG_SUBTLE,
                    border_radius=6,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Checkbox(
                                label=f"[{c.get('version') or 'gen'}] {c.get('text')} ({c.get('owner_type')}:{c.get('owner_name')})",
                                value=is_res,
                                on_change=lambda e, c_id=cid: self._toggle_comment(pname, c_id, bool(e.control.value)),
                            )
                        ],
                    ),
                )
            )

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            controls=[
                ft.Row(
                    spacing=10,
                    controls=[
                        text_input,
                        ft.Button("Add Comment", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_add_cmt),
                    ],
                ),
                ft.Text(f"Comments ({len(comments)})", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                *cmt_controls,
            ],
        )

    def _toggle_comment(self, project_name: str, comment_id: str, resolved: bool) -> None:
        self.core.resolve_comment(project_name=project_name, comment_id=comment_id, resolved=resolved, actor=self.actor)
        self._reload_data_from_core()
        self._render_main_workspace()

    def _build_drawer_risks_tab(self, proj: dict[str, Any]) -> ft.Control:
        pname = proj["name"]
        risks = proj.get("risks", [])
        title_in = ft.TextField(label="Risk Title", width=410, border_color=self.BORDER_COLOR)
        desc_in = ft.TextField(label="Description / Mitigation", width=410, border_color=self.BORDER_COLOR)
        sev_dd = _make_dropdown(
            label="Severity",
            width=195,
            value="high",
            options=[ft.dropdown.Option(s) for s in sorted(VALID_RISK_SEVERITIES)],
        )
        lik_dd = _make_dropdown(
            label="Likelihood",
            width=195,
            value="medium",
            options=[ft.dropdown.Option(s) for s in sorted(VALID_RISK_LIKELIHOODS)],
        )

        def on_add_risk(_: Any) -> None:
            t_val = (title_in.value or "").strip()
            if t_val:
                self.core.add_risk(
                    project_name=pname,
                    title=t_val,
                    description=(desc_in.value or "").strip(),
                    severity=sev_dd.value or "medium",
                    likelihood=lik_dd.value or "medium",
                    actor=self.actor,
                )
                self._reload_data_from_core()
                self._render_main_workspace()

        r_cards: list[ft.Control] = []
        for r in risks:
            rid = r["risk_id"]
            is_closed = r.get("status") == "closed"
            r_cards.append(
                ft.Container(
                    padding=10,
                    bgcolor=self.BG_SUBTLE,
                    border_radius=6,
                    content=ft.Column(
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        f"{r['title']} [{r.get('severity')}/{r.get('status')}]",
                                        size=13,
                                        weight=ft.FontWeight.BOLD,
                                        color=self.TEXT_PRIMARY,
                                    ),
                                    ft.TextButton(
                                        "Close",
                                        disabled=is_closed,
                                        on_click=lambda _, r_id=rid: self._close_risk_ui(pname, r_id),
                                    ),
                                ],
                            ),
                            ft.Text(r.get("description") or "", size=12, color=self.TEXT_SECONDARY),
                            ft.Text(f"Mitigation: {r.get('mitigation') or '-'}", size=11, color=self.TEXT_MUTED)
                            if r.get("mitigation")
                            else ft.Container(),
                        ],
                    ),
                )
            )

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            controls=[
                ft.Row(spacing=10, controls=[title_in, desc_in]),
                ft.Row(
                    spacing=10,
                    controls=[
                        sev_dd,
                        lik_dd,
                        ft.Button("Add Risk", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_add_risk),
                    ],
                ),
                ft.Text(f"Project Risks ({len(risks)})", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                *r_cards,
            ],
        )

    def _close_risk_ui(self, project_name: str, risk_id: str) -> None:
        self.core.close_risk(project_name=project_name, risk_id=risk_id, actor=self.actor)
        self._reload_data_from_core()
        self._render_main_workspace()

    def _build_drawer_milestones_tab(self, proj: dict[str, Any]) -> ft.Control:
        pname = proj["name"]
        milestones = proj.get("milestones", [])
        title_in = ft.TextField(label="Milestone Title", width=410, border_color=self.BORDER_COLOR)
        due_in = ft.TextField(label="Due Date (YYYY-MM-DD)", value="2026-11-15", width=195, border_color=self.BORDER_COLOR)
        phase_dd = _make_dropdown(
            label="Phase",
            width=205,
            value="short_term_7d",
            options=[ft.dropdown.Option(p) for p in MILESTONE_PHASE_ORDER],
        )

        def on_add_ms(_: Any) -> None:
            t_val = (title_in.value or "").strip()
            if t_val:
                self.core.add_milestone(
                    project_name=pname,
                    title=t_val,
                    phase=phase_dd.value or "short_term_7d",
                    due_date=(due_in.value or "").strip() or None,
                    actor=self.actor,
                )
                self._reload_data_from_core()
                self._render_main_workspace()

        ms_cards: list[ft.Control] = []
        for phase in MILESTONE_PHASE_ORDER:
            p_items = [m for m in milestones if m.get("phase") == phase]
            if not p_items:
                continue
            ms_cards.append(ft.Text(f"Phase: {phase}", size=12, weight=ft.FontWeight.BOLD, color=self.ACCENT_BLUE))
            for m in p_items:
                mid = m["milestone_id"]
                is_done = m.get("status") == "done"
                ms_cards.append(
                    ft.Container(
                        padding=8,
                        bgcolor=self.BG_SUBTLE,
                        border_radius=6,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(
                                    f"{m['title']} (due: {m.get('due_date') or 'none'}) [{m.get('status')}]",
                                    size=12,
                                    color=self.TEXT_PRIMARY,
                                ),
                                ft.TextButton(
                                    "Mark Done",
                                    disabled=is_done,
                                    on_click=lambda _, m_id=mid: self._close_milestone_ui(pname, m_id),
                                ),
                            ],
                        ),
                    )
                )

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            controls=[
                ft.Row(
                    spacing=10,
                    controls=[
                        title_in,
                        phase_dd,
                        due_in,
                        ft.Button("Add Milestone", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_add_ms),
                    ],
                ),
                ft.Text(f"Milestones ({len(milestones)})", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                *ms_cards,
            ],
        )

    def _close_milestone_ui(self, project_name: str, milestone_id: str) -> None:
        self.core.close_milestone(project_name=project_name, milestone_id=milestone_id, actor=self.actor)
        self._reload_data_from_core()
        self._render_main_workspace()

    def _build_drawer_activity_tab(self, proj: dict[str, Any]) -> ft.Control:
        pname = proj["name"]
        act = self.core.list_activity(
            project_name=pname,
            actor_type=self.act_actor_type if self.act_actor_type != "all" else None,
            actor_source=self.act_actor_source if self.act_actor_source != "all" else None,
        )
        events = list(reversed(act.get("events", [])))

        atype_dd = _make_dropdown(
            label="Actor Type",
            width=190,
            value=self.act_actor_type,
            options=[
                ft.dropdown.Option("all", "All Actors"),
                ft.dropdown.Option("human", "Human"),
                ft.dropdown.Option("agent", "Agent"),
            ],
            on_select=lambda e: self._set_act_filters(e.control.value or "all", self.act_actor_source),
        )
        asrc_dd = _make_dropdown(
            label="Source",
            width=190,
            value=self.act_actor_source,
            options=[
                ft.dropdown.Option("all", "All Sources"),
                ft.dropdown.Option("ui", "UI"),
                ft.dropdown.Option("cli", "CLI"),
                ft.dropdown.Option("http", "HTTP"),
                ft.dropdown.Option("mcp", "MCP"),
                ft.dropdown.Option("manifest", "Manifest"),
            ],
            on_select=lambda e: self._set_act_filters(self.act_actor_type, e.control.value or "all"),
        )

        ev_rows: list[ft.Control] = []
        for ev in events[:40]:
            actor_o = ev.get("actor", {})
            ev_rows.append(
                ft.Container(
                    padding=8,
                    bgcolor=self.BG_SUBTLE,
                    border_radius=6,
                    content=ft.Column(
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Text(
                                f"[{ev.get('timestamp')}] {ev.get('event_type')}",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color=self.TEXT_PRIMARY,
                            ),
                            ft.Text(
                                f"Actor: {actor_o.get('actor_name')} ({actor_o.get('actor_type')}/{actor_o.get('actor_source')})",
                                size=11,
                                color=self.TEXT_SECONDARY,
                            ),
                            ft.Text(str(ev.get("payload", {})), size=11, color=self.TEXT_MUTED),
                        ],
                    ),
                )
            )

        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            controls=[
                ft.Row(spacing=10, controls=[atype_dd, asrc_dd]),
                ft.Text(f"Activity Log ({len(events)} events)", size=14, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                *ev_rows,
            ],
        )

    def _set_act_filters(self, atype: str, asrc: str) -> None:
        self.act_actor_type = atype
        self.act_actor_source = asrc
        self._render_main_workspace()

    # ------------------------------------------------------------------
    # Automation Panel (UI/UX Requirement line 182)
    # ------------------------------------------------------------------
    def _build_automation_panel(self) -> ft.Control:
        obs = self.core.get_recent_automation_logs(limit=15)
        logs = obs.get("logs", [])
        last_manifest = obs.get("last_manifest_result")

        def on_process_inbox(_: Any) -> None:
            res = self.core.process_inbox_once()
            self._reload_data_from_core()
            self._set_notice(f"Processed {res['processed_count']} manifest file(s) from Automation/inbox.")

        log_controls = [
            ft.Container(
                padding=8,
                bgcolor=self.BG_SUBTLE,
                border_radius=6,
                content=ft.Column(
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Text(f"[{lg.get('timestamp')}] {lg.get('operation')}", size=11, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                        ft.Text(
                            f"Actor: {lg.get('actor', {}).get('actor_name')} ({lg.get('actor', {}).get('actor_source')})",
                            size=11,
                            color=self.TEXT_SECONDARY,
                        ),
                    ],
                ),
            )
            for lg in logs
        ]

        return ft.Container(
            width=340,
            padding=18,
            bgcolor=self.BG_SURFACE,
            border=ft.Border.only(left=ft.BorderSide(1, self.BORDER_COLOR)),
            content=ft.Column(
                expand=True,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text("Automation & Agent Panel", size=16, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    ft.Container(
                        padding=10,
                        bgcolor=self.BG_SUBTLE,
                        border_radius=6,
                        content=ft.Column(
                            spacing=4,
                            horizontal_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Text("Interfaces Ready:", size=12, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                                ft.Text("CLI: scitree (also in Paper CLI tab)", size=11, color=self.TEXT_SECONDARY),
                                ft.Text("HTTP API: 127.0.0.1:8765 (scitree-api)", size=11, color=self.TEXT_SECONDARY),
                                ft.Text("MCP Server: stdio/SSE (scitree-mcp)", size=11, color=self.TEXT_SECONDARY),
                            ],
                        ),
                    ),
                    ft.Button(
                        "Process Automation/inbox Now",
                        bgcolor=self.ACCENT_BLUE,
                        color="#FFFFFF",
                        on_click=on_process_inbox,
                    ),
                    ft.Text("Last Manifest Result:", size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    ft.Text(
                        str(last_manifest.get("summary") if isinstance(last_manifest, dict) else "None yet"),
                        size=11,
                        color=self.TEXT_SECONDARY,
                    ),
                    ft.Text("Recent Automated Operations:", size=13, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY),
                    *log_controls,
                ],
            ),
        )

    # ------------------------------------------------------------------
    # Modal Dialog Helpers
    # ------------------------------------------------------------------
    def _open_new_project_modal(self) -> None:
        name_in = ft.TextField(label="Project Name", width=400)
        desc_in = ft.TextField(label="Description", width=400)
        tpl_names = [t["name"] for t in self.templates_cache] or ["Default", "Empirical Paper"]
        tpl_dd = _make_dropdown(
            label="Template",
            width=400,
            value=tpl_names[0],
            options=[ft.dropdown.Option(n) for n in tpl_names],
        )

        def on_create(_: Any) -> None:
            pname = (name_in.value or "").strip()
            if pname:
                self.core.create_project(
                    name=pname,
                    description=(desc_in.value or "").strip(),
                    template_name=tpl_dd.value,
                    actor=self.actor,
                )
                self._close_dialog(dlg)
                self._reload_data_from_core()
                self.selected_project_name = pname
                self._render_main_workspace()

        dlg = ft.AlertDialog(
            title=ft.Text("Create Scientific Project"),
            content=ft.Column(tight=True, spacing=12, controls=[name_in, desc_in, tpl_dd]),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Create", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_create),
            ],
        )
        self._show_dialog(dlg)

    def _open_add_file_modal(self, project_name: str) -> None:
        path_in = ft.TextField(label="File Path", width=400)
        kind_dd = _make_dropdown(
            label="File Kind",
            width=400,
            value="data",
            options=[
                ft.dropdown.Option("data", "Data (Data/)"),
                ft.dropdown.Option("figure", "Standalone Figure (Figures_Standalone/)"),
                ft.dropdown.Option("manuscript", "Manuscript (Versions/)"),
            ],
        )

        def on_submit(_: Any) -> None:
            try:
                self.core.add_file(
                    project_name=project_name,
                    file_path=(path_in.value or "").strip(),
                    kind=kind_dd.value or "data",
                    actor=self.actor,
                )
                self._close_dialog(dlg)
                self._reload_data_from_core()
                self._set_notice(f"Added file to {project_name}.")
            except SciTreeError as exc:
                self._set_notice(f"Error [{exc.code}]: {exc.message}")

        dlg = ft.AlertDialog(
            title=ft.Text(f"Add File to {project_name}"),
            content=ft.Column(tight=True, spacing=12, controls=[path_in, kind_dd]),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Upload", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_submit),
            ],
        )
        self._show_dialog(dlg)

    def _open_zotero_modal(self, proj: dict[str, Any]) -> None:
        pname = proj["name"]
        zcfg = proj.get("zotero") or {}
        key_in = ft.TextField(label="Zotero Collection Key", value=zcfg.get("collection_key") or "", width=400)
        cname_in = ft.TextField(label="Collection Name", value=zcfg.get("collection_name") or "", width=400)

        def on_link_and_sync(_: Any) -> None:
            kval = (key_in.value or "").strip()
            if kval:
                self.core.zotero_link(
                    project_name=pname,
                    collection_key=kval,
                    collection_name=(cname_in.value or "").strip() or None,
                    actor=self.actor,
                )
                res = self.core.zotero_sync(project_name=pname, strict=False, actor=self.actor)
                self._close_dialog(dlg)
                self._reload_data_from_core()
                self._set_notice(f"Zotero sync status: {res.get('status')}")

        dlg = ft.AlertDialog(
            title=ft.Text(f"Zotero Integration - {pname}"),
            content=ft.Column(tight=True, spacing=12, controls=[key_in, cname_in]),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Link & Sync", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_link_and_sync),
            ],
        )
        self._show_dialog(dlg)

    def _open_save_template_modal(self, project_name: str) -> None:
        tname_in = ft.TextField(label="Custom Template Name", width=400)
        tdesc_in = ft.TextField(label="Template Description", width=400)

        def on_save(_: Any) -> None:
            val = (tname_in.value or "").strip()
            if val:
                self.core.save_template(
                    project_name=project_name,
                    template_name=val,
                    description=(tdesc_in.value or "").strip() or None,
                    actor=self.actor,
                )
                self._close_dialog(dlg)
                self._reload_data_from_core()
                self._set_notice(f"Saved template '{val}'.")

        dlg = ft.AlertDialog(
            title=ft.Text(f"Save Template from {project_name}"),
            content=ft.Column(tight=True, spacing=12, controls=[tname_in, tdesc_in]),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Save Template", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_save),
            ],
        )
        self._show_dialog(dlg)

    def _open_settings_modal(self) -> None:
        status = self.core.get_root_status()
        local_token = self.core.state_manager.load().get("api_token")
        root_in = ft.TextField(label="Root Folder Path", value=status.get("root_path") or "", width=440)

        def on_change_root(_: Any) -> None:
            val = (root_in.value or "").strip()
            if val:
                self.core.init_root(root_path=val, actor=self.actor)
                self._close_dialog(dlg)
                self._reload_data_from_core()
                self._set_notice(f"Switched root folder to: {val}")

        def on_reset_onboarding(_: Any) -> None:
            self.core.reset_onboarding(actor=self.actor)
            self._close_dialog(dlg)
            self._render_onboarding_step1()

        dlg = ft.AlertDialog(
            title=ft.Text("Workspace & Onboarding Settings"),
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    root_in,
                    ft.Text(f"Non-loopback API Token: {local_token}", size=11, color=self.TEXT_MUTED),
                ],
            ),
            actions=[
                ft.TextButton("Reset Onboarding", on_click=on_reset_onboarding),
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Apply Root Path", bgcolor=self.ACCENT_BLUE, color="#FFFFFF", on_click=on_change_root),
            ],
        )
        self._show_dialog(dlg)

    def _show_dialog(self, dlg: ft.AlertDialog) -> None:
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(dlg)
        elif hasattr(self.page, "open"):
            self.page.open(dlg)
        else:
            self.page.dialog = dlg
            dlg.open = True
            self.page.update()

    def _close_dialog(self, dlg: ft.AlertDialog) -> None:
        if hasattr(self.page, "pop_dialog"):
            self.page.pop_dialog()
        elif hasattr(self.page, "close"):
            self.page.close(dlg)
        else:
            dlg.open = False
            self.page.update()


def run_ui(page: ft.Page) -> None:
    SciTreeDesktopUI(page)


def main() -> None:
    if hasattr(ft, "run"):
        ft.run(run_ui)
    else:
        ft.app(target=run_ui)
