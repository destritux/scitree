"""Minimalist, modern Flet desktop application for sciTree.

All user-facing mutations invoke SciTreeCore with actor_source='ui'.
Supports Board (Kanban with drag-and-drop), List/Table, and Timeline/Route views,
plus a right-side project detail drawer (Versions, Comments, Risks, Milestones, Activity)
and an Automation observability panel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import flet as ft

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

# Palette constants: neutral soft grays, white, and a single blue accent
BG_APP = "#F8FAFC"
BG_SURFACE = "#FFFFFF"
BG_SUBTLE = "#F1F5F9"
BORDER_COLOR = "#E2E8F0"
TEXT_PRIMARY = "#0F172A"
TEXT_SECONDARY = "#475569"
TEXT_MUTED = "#64748B"
ACCENT_BLUE = "#2563EB"
ACCENT_BLUE_LIGHT = "#EFF6FF"
BADGE_GREEN_BG = "#DCFCE7"
BADGE_GREEN_FG = "#166534"
BADGE_AMBER_BG = "#FEF3C7"
BADGE_AMBER_FG = "#92400E"
BADGE_RED_BG = "#FEE2E2"
BADGE_RED_FG = "#991B1B"
BADGE_PURPLE_BG = "#F3E8FF"
BADGE_PURPLE_FG = "#6B21A8"


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


class SciTreeDesktopUI:
    """Controller and view builder for the sciTree Flet desktop interface."""

    def __init__(self, page: ft.Page, initial_root: str | None = None) -> None:
        self.page = page
        self.core = SciTreeCore(root_path=initial_root)
        self.actor = validate_actor(actor_name="local-user", actor_type="human", actor_source="ui")

        # Cached in-memory dataset so switching views does not reload from disk (Section A4)
        self.projects_cache: list[dict[str, Any]] = []
        self.templates_cache: list[dict[str, Any]] = []
        self.selected_project_name: str | None = None
        self.active_drawer_tab: str = "versions"
        self.show_automation_panel: bool = False

        # Shared filter/sort state across Board, List, and Timeline views (Section A2)
        root_status = self.core.get_root_status()
        ui_state = root_status.get("ui_state") or {}
        self.current_view: str = ui_state.get("last_view", "board")
        self.search_query: str = ""
        self.owner_filter: str = "all"  # "human" (My tasks) | "agent" (Agent tasks) | "all"
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

        self._configure_page()
        self.file_picker = ft.FilePicker()
        if hasattr(self.page, "services"):
            self.page.services.append(self.file_picker)
        elif hasattr(self.page, "overlay"):
            self.page.overlay.append(self.file_picker)

        self.root_container = ft.Container(expand=True, bgcolor=BG_APP)
        self.page.add(self.root_container)

        configured_root = root_status.get("root_path")
        root_exists = bool(configured_root and Path(str(configured_root)).exists())
        if not root_status.get("onboarding_completed") or not root_exists:
            self._render_onboarding_step1()
        else:
            self._reload_data_from_core()
            self._render_main_workspace()

    def _configure_page(self) -> None:
        self.page.title = "sciTree - Scientific Project and Manuscript Workspace"
        self.page.bgcolor = BG_APP
        self.page.padding = 0

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
            border_color=BORDER_COLOR,
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
            bgcolor=BG_SURFACE,
            border=ft.Border.all(1, BORDER_COLOR),
            border_radius=12,
            content=ft.Column(
                tight=True,
                spacing=18,
                controls=[
                    ft.Text("Welcome to sciTree - First-Run Setup", size=22, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                    ft.Text(
                        "Choose the root folder where all scientific projects, manuscript versions, "
                        "extracted figures, references, and automation logs will be stored locally.",
                        size=14,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Container(
                        padding=12,
                        bgcolor=BG_SUBTLE,
                        border_radius=8,
                        content=ft.Text(f"Recommended OS Location: {rec_path}", size=13, color=TEXT_PRIMARY),
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
                                bgcolor=ACCENT_BLUE,
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
            border_color=BORDER_COLOR,
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
            bgcolor=BG_SURFACE,
            border=ft.Border.all(1, BORDER_COLOR),
            border_radius=12,
            content=ft.Column(
                tight=True,
                spacing=16,
                controls=[
                    ft.Text("Step 2 (Optional): Start from a Template", size=20, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                    ft.Text(
                        "Choose a workflow template (Empirical Paper, Review Article, or Grant Proposal) "
                        "to initialize lifecycle columns, milestones, and risk categories, or skip to open an empty board.",
                        size=13,
                        color=TEXT_SECONDARY,
                    ),
                    proj_name_input,
                    tpl_dropdown,
                    ft.Row(
                        spacing=12,
                        controls=[
                            ft.Button(
                                "Create Project with Template",
                                bgcolor=ACCENT_BLUE,
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
        self.core.state_manager.update_ui_state(last_view=view_name)
        # Instantaneous re-render from cached projects without disk reload (Section A4)
        self._render_main_workspace()

    def _render_main_workspace(self) -> None:
        header = self._build_top_bar()
        filter_bar = self._build_filter_bar()

        controls: list[ft.Control] = [header, filter_bar]
        if self.notice_message:
            controls.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=20, vertical=8),
                    bgcolor=ACCENT_BLUE_LIGHT,
                    border=ft.Border.only(bottom=ft.BorderSide(1, BORDER_COLOR)),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(self.notice_message, size=13, color=ACCENT_BLUE),
                            ft.TextButton("Dismiss", on_click=lambda _: self._set_notice("")),
                        ],
                    ),
                )
            )

        # Active view content
        if self.current_view == "list":
            main_view = self._build_list_view()
        elif self.current_view == "timeline":
            main_view = self._build_timeline_view()
        else:
            main_view = self._build_board_view()

        body_row_items: list[ft.Control] = [ft.Container(expand=True, content=main_view)]
        if self.selected_project_name:
            drawer = self._build_project_drawer(self.selected_project_name)
            if drawer is not None:
                body_row_items.append(drawer)
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
            is_active = self.current_view == key
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=14, vertical=6),
                bgcolor=ACCENT_BLUE if is_active else BG_SUBTLE,
                border_radius=6,
                on_click=lambda _: self._switch_view(key),
                content=ft.Text(
                    label,
                    size=13,
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                    color="#FFFFFF" if is_active else TEXT_PRIMARY,
                ),
            )

        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=24, vertical=14),
            bgcolor=BG_SURFACE,
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER_COLOR)),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=16,
                        controls=[
                            ft.Text("sciTree", size=20, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                            ft.Container(
                                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                bgcolor=BG_SUBTLE,
                                border_radius=4,
                                content=ft.Text(f"Root: {root_label}", size=11, color=TEXT_MUTED),
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Button(
                                "+ New Project",
                                bgcolor=ACCENT_BLUE,
                                color="#FFFFFF",
                                on_click=lambda _: self._open_new_project_modal(),
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
                            # Top-right view switcher: Board | List | Timeline (Section I7)
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
            width=260,
            height=38,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_color=BORDER_COLOR,
            on_change=lambda e: self._update_search(e.control.value),
        )

        # Quick owner filter chip row: My tasks | Agent tasks | All (Section E3 & I7)
        def make_owner_chip(label: str, val: str) -> ft.Control:
            active = self.owner_filter == val
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=5),
                bgcolor=ACCENT_BLUE if active else BG_SURFACE,
                border=ft.Border.all(1, ACCENT_BLUE if active else BORDER_COLOR),
                border_radius=16,
                on_click=lambda _: self._set_owner_filter(val),
                content=ft.Text(
                    label,
                    size=12,
                    color="#FFFFFF" if active else TEXT_SECONDARY,
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
            padding=ft.Padding.symmetric(horizontal=24, vertical=10),
            bgcolor=BG_SURFACE,
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER_COLOR)),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=12,
                        controls=[
                            search_field,
                            ft.Text("Tasks:", size=12, color=TEXT_MUTED),
                            make_owner_chip("All", "all"),
                            make_owner_chip("My tasks", "human"),
                            make_owner_chip("Agent tasks", "agent"),
                            pending_cb,
                        ],
                    ),
                    ft.Row(
                        spacing=12,
                        controls=[
                            sort_dd,
                            ft.TextButton("Refresh Disk", on_click=lambda _: self._refresh_all()),
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

            column_box = ft.Container(
                width=290,
                padding=14,
                bgcolor=BG_SUBTLE,
                border=ft.Border.all(1, BORDER_COLOR),
                border_radius=10,
                content=ft.Column(
                    spacing=10,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(col_name, size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                                ft.Container(
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                    bgcolor=BG_SURFACE,
                                    border_radius=10,
                                    content=ft.Text(str(len(col_projects)), size=12, color=TEXT_SECONDARY),
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
            padding=20,
            content=ft.Row(
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
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

        # Prominent latest version badge + [LOCKED] indicator (Requirement 3, 4 & Section D3, I7)
        version_badge_text = f"Latest: {latest_vid} ({latest_state})" if latest_vid else "No Version"
        if is_locked:
            version_badge_text += " [LOCKED]"

        badges_row: list[ft.Control] = [
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                bgcolor=BADGE_GREEN_BG if is_locked else ACCENT_BLUE_LIGHT,
                border_radius=4,
                content=ft.Text(
                    version_badge_text,
                    size=11,
                    weight=ft.FontWeight.BOLD,
                    color=BADGE_GREEN_FG if is_locked else ACCENT_BLUE,
                ),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=6, vertical=3),
                bgcolor=BG_SUBTLE,
                border_radius=4,
                content=ft.Text(f"Owner: {owner_type}", size=10, color=TEXT_SECONDARY),
            ),
        ]

        # Indicator badges for pending comments, open high/critical risks, and next milestone (Section B3)
        indicators: list[ft.Control] = []
        if pending_comments > 0:
            indicators.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    bgcolor=BADGE_AMBER_BG,
                    border_radius=4,
                    content=ft.Text(f"Comments: {pending_comments}", size=11, color=BADGE_AMBER_FG),
                )
            )
        if high_crit_risks > 0:
            indicators.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    bgcolor=BADGE_RED_BG,
                    border_radius=4,
                    content=ft.Text(f"High/Crit Risks: {high_crit_risks}", size=11, color=BADGE_RED_FG),
                )
            )
        if next_due:
            indicators.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                    bgcolor=BADGE_PURPLE_BG,
                    border_radius=4,
                    content=ft.Text(f"Next Due: {next_due}", size=11, color=BADGE_PURPLE_FG),
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
            width=262,
            padding=14,
            bgcolor=BG_SURFACE,
            border=ft.Border.all(2 if is_selected else 1, ACCENT_BLUE if is_selected else BORDER_COLOR),
            border_radius=8,
            on_click=lambda _, pn=pname: self._select_project(pn),
            content=ft.Column(
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Text(pname, size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                    ft.Row(wrap=True, spacing=6, run_spacing=4, controls=badges_row),
                    ft.Text(f"Submitted by: {latest_author}", size=12, color=TEXT_SECONDARY),
                    ft.Row(wrap=True, spacing=6, run_spacing=4, controls=indicators) if indicators else ft.Container(),
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
                bgcolor=ACCENT_BLUE_LIGHT,
                border=ft.Border.all(1, ACCENT_BLUE),
                border_radius=8,
                content=ft.Text(pname, size=13, weight=ft.FontWeight.BOLD, color=ACCENT_BLUE),
            ),
        )

    def _move_card_click(self, project_name: str, target_column: str) -> None:
        self.core.move_project(name=project_name, column=target_column, actor=self.actor)
        self._reload_data_from_core()
        self._render_main_workspace()

    def _select_project(self, project_name: str) -> None:
        self.selected_project_name = project_name
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
                        ft.DataCell(ft.Text(col, size=13, color=TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(lvid, size=13, weight=ft.FontWeight.BOLD, color=ACCENT_BLUE)),
                        ft.DataCell(ft.Text(owner, size=12, color=TEXT_SECONDARY)),
                        ft.DataCell(ft.Text(pending_c, size=13, color=TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(hc_risks, size=13, color=BADGE_RED_FG if hc_risks != "0" else TEXT_MUTED)),
                        ft.DataCell(ft.Text(next_due, size=12, color=TEXT_SECONDARY)),
                    ]
                )
            )

        table = ft.DataTable(
            border=ft.Border.all(1, BORDER_COLOR),
            border_radius=8,
            heading_row_color=BG_SUBTLE,
            columns=[
                ft.DataColumn(ft.Text("Project", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Column", weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text("Latest Version", weight=ft.FontWeight.BOLD)),
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
                    ft.Text(f"Projects Table ({len(projects)})", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
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
                content=ft.Text("No project available to display Timeline / Route View.", size=14, color=TEXT_MUTED),
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
            border_color=BORDER_COLOR,
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
                        bgcolor=BG_SURFACE,
                        border=ft.Border.all(1, BORDER_COLOR),
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
                                            color=ACCENT_BLUE,
                                        ),
                                        ft.Text(str(payload), size=12, color=TEXT_SECONDARY),
                                    ],
                                ),
                                ft.Column(
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                    spacing=2,
                                    controls=[
                                        ft.Text(str(ev.get("timestamp", "")), size=11, color=TEXT_MUTED),
                                        ft.Text(
                                            f"{actor_obj.get('actor_name')} ({actor_obj.get('actor_type')}/{actor_obj.get('actor_source')})",
                                            size=11,
                                            color=TEXT_SECONDARY,
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
                    bgcolor=BG_SUBTLE,
                    border_radius=8,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Text(f"Date: {day_obj['date']}", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
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
                            ft.Button("Add Note", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_add_note),
                        ],
                    ),
                    *day_groups,
                ],
            ),
        )

    # ------------------------------------------------------------------
    # Right-Side Project Detail Drawer (Section I7)
    # Tabs: Versions | Comments | Risks | Milestones | Activity
    # ------------------------------------------------------------------
    def _build_project_drawer(self, project_name: str) -> ft.Control | None:
        proj = next((p for p in self.projects_cache if p["name"] == project_name), None)
        if not proj:
            return None

        def switch_tab(tab_key: str) -> None:
            self.active_drawer_tab = tab_key
            self._render_main_workspace()

        def tab_btn(label: str, key: str) -> ft.Control:
            active = self.active_drawer_tab == key
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                bgcolor=ACCENT_BLUE if active else BG_SUBTLE,
                border_radius=6,
                on_click=lambda _: switch_tab(key),
                content=ft.Text(
                    label,
                    size=12,
                    weight=ft.FontWeight.BOLD if active else ft.FontWeight.NORMAL,
                    color="#FFFFFF" if active else TEXT_PRIMARY,
                ),
            )

        if self.active_drawer_tab == "comments":
            tab_body = self._build_drawer_comments_tab(proj)
        elif self.active_drawer_tab == "risks":
            tab_body = self._build_drawer_risks_tab(proj)
        elif self.active_drawer_tab == "milestones":
            tab_body = self._build_drawer_milestones_tab(proj)
        elif self.active_drawer_tab == "activity":
            tab_body = self._build_drawer_activity_tab(proj)
        else:
            tab_body = self._build_drawer_versions_tab(proj)

        def on_export_package(_: Any) -> None:
            try:
                res = self.core.export_package(project_name=project_name, actor=self.actor)
                self._reload_data_from_core()
                self._set_notice(f"Exported submission package: {res['export']['path']}")
            except SciTreeError as exc:
                self._set_notice(f"Export error [{exc.code}]: {exc.message}")

        return ft.Container(
            width=460,
            padding=18,
            bgcolor=BG_SURFACE,
            border=ft.Border.only(left=ft.BorderSide(1, BORDER_COLOR)),
            content=ft.Column(
                expand=True,
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(proj["name"], size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                            ft.TextButton("Close", on_click=lambda _: self._close_drawer()),
                        ],
                    ),
                    ft.Text(proj.get("description") or "No description.", size=12, color=TEXT_SECONDARY),
                    ft.Row(
                        wrap=True,
                        spacing=8,
                        controls=[
                            ft.Button(
                                "Export Package",
                                bgcolor=ACCENT_BLUE,
                                color="#FFFFFF",
                                on_click=on_export_package,
                            ),
                            ft.OutlinedButton(
                                "Add File",
                                on_click=lambda _: self._open_add_file_modal(project_name),
                            ),
                            ft.OutlinedButton(
                                "Zotero Sync",
                                on_click=lambda _: self._open_zotero_modal(proj),
                            ),
                            ft.OutlinedButton(
                                "Save Template",
                                on_click=lambda _: self._open_save_template_modal(project_name),
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=6,
                        controls=[
                            tab_btn("Versions", "versions"),
                            tab_btn("Comments", "comments"),
                            tab_btn("Risks", "risks"),
                            tab_btn("Milestones", "milestones"),
                            tab_btn("Activity", "activity"),
                        ],
                    ),
                    ft.Divider(height=1, color=BORDER_COLOR),
                    tab_body,
                ],
            ),
        )

    def _close_drawer(self) -> None:
        self.selected_project_name = None
        self._render_main_workspace()

    def _build_drawer_versions_tab(self, proj: dict[str, Any]) -> ft.Control:
        pname = proj["name"]
        versions = [v for v in proj.get("versions", []) if not v.get("archived")]
        latest_vid = proj.get("latest_version_id")

        file_input = ft.TextField(label="Manuscript Path (.docx or .pdf)", width=410, border_color=BORDER_COLOR)
        vid_input = ft.TextField(label="Version ID (e.g. v1, v2)", value=f"v{len(versions) + 1}", width=195, border_color=BORDER_COLOR)
        author_input = ft.TextField(label="Author Name", value="Jane Doe", width=205, border_color=BORDER_COLOR)
        changelog_input = ft.TextField(label="Changelog Note", width=410, border_color=BORDER_COLOR)
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
                        ft.Text(f"Warning: {exc.message}", size=12, color=BADGE_RED_FG),
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

            action_btns: list[ft.Control] = []
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
                    bgcolor=ACCENT_BLUE_LIGHT if is_latest else BG_SUBTLE,
                    border=ft.Border.all(1, ACCENT_BLUE if is_latest else BORDER_COLOR),
                    border_radius=6,
                    content=ft.Column(
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Text(
                                f"{vid} ({v.get('state')}){latest_str}{lock_str}",
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=TEXT_PRIMARY,
                            ),
                            ft.Text(f"Author: {v.get('author')} | Uploaded: {v.get('created_at')}", size=11, color=TEXT_SECONDARY),
                            ft.Text(f"Changelog: {v.get('changelog') or '-'}", size=12, color=TEXT_PRIMARY),
                            ft.Text(
                                f"Extracted: {ext_info.get('figures_extracted', 0)} figures, "
                                f"{ext_info.get('references_parsed', 0)} references",
                                size=11,
                                color=TEXT_MUTED,
                            ),
                            ft.Row(spacing=6, controls=action_btns) if action_btns else ft.Container(),
                        ],
                    ),
                )
            )

        return ft.Column(
            spacing=10,
            controls=[
                ft.Text("Upload New Manuscript Version", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                file_input,
                ft.Row(spacing=10, controls=[vid_input, author_input]),
                changelog_input,
                conflict_banner,
                ft.Button("Upload Version", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=lambda _: submit_version()),
                ft.Divider(height=1, color=BORDER_COLOR),
                ft.Text(f"Version History ({len(versions)})", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                *ver_items,
            ],
        )

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
        text_input = ft.TextField(label="New Comment Text", width=410, border_color=BORDER_COLOR)

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
                    bgcolor=BG_SUBTLE,
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
            spacing=10,
            controls=[
                text_input,
                ft.Button("Add Comment", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_add_cmt),
                ft.Text(f"Comments ({len(comments)})", size=14, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
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
        title_in = ft.TextField(label="Risk Title", width=410, border_color=BORDER_COLOR)
        desc_in = ft.TextField(label="Description / Mitigation", width=410, border_color=BORDER_COLOR)
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
                    bgcolor=BG_SUBTLE,
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
                                    ),
                                    ft.TextButton(
                                        "Close",
                                        disabled=is_closed,
                                        on_click=lambda _, r_id=rid: self._close_risk_ui(pname, r_id),
                                    ),
                                ],
                            ),
                            ft.Text(r.get("description") or "", size=12, color=TEXT_SECONDARY),
                        ],
                    ),
                )
            )

        return ft.Column(
            spacing=10,
            controls=[
                title_in,
                desc_in,
                ft.Row(spacing=10, controls=[sev_dd, lik_dd]),
                ft.Button("Add Risk", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_add_risk),
                ft.Text(f"Project Risks ({len(risks)})", size=14, weight=ft.FontWeight.BOLD),
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
        title_in = ft.TextField(label="Milestone Title", width=410, border_color=BORDER_COLOR)
        due_in = ft.TextField(label="Due Date (YYYY-MM-DD)", value="2026-11-15", width=195, border_color=BORDER_COLOR)
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
            ms_cards.append(ft.Text(f"Phase: {phase}", size=12, weight=ft.FontWeight.BOLD, color=ACCENT_BLUE))
            for m in p_items:
                mid = m["milestone_id"]
                is_done = m.get("status") == "done"
                ms_cards.append(
                    ft.Container(
                        padding=8,
                        bgcolor=BG_SUBTLE,
                        border_radius=6,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(
                                    f"{m['title']} (due: {m.get('due_date') or 'none'}) [{m.get('status')}]",
                                    size=12,
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
            spacing=10,
            controls=[
                title_in,
                ft.Row(spacing=10, controls=[phase_dd, due_in]),
                ft.Button("Add Milestone", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_add_ms),
                ft.Text(f"Milestones ({len(milestones)})", size=14, weight=ft.FontWeight.BOLD),
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
                    bgcolor=BG_SUBTLE,
                    border_radius=6,
                    content=ft.Column(
                        spacing=2,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Text(
                                f"[{ev.get('timestamp')}] {ev.get('event_type')}",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color=TEXT_PRIMARY,
                            ),
                            ft.Text(
                                f"Actor: {actor_o.get('actor_name')} ({actor_o.get('actor_type')}/{actor_o.get('actor_source')})",
                                size=11,
                                color=TEXT_SECONDARY,
                            ),
                            ft.Text(str(ev.get("payload", {})), size=11, color=TEXT_MUTED),
                        ],
                    ),
                )
            )

        return ft.Column(
            spacing=10,
            controls=[
                ft.Row(spacing=10, controls=[atype_dd, asrc_dd]),
                ft.Text(f"Activity Log ({len(events)} events)", size=14, weight=ft.FontWeight.BOLD),
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
                bgcolor=BG_SUBTLE,
                border_radius=6,
                content=ft.Column(
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Text(f"[{lg.get('timestamp')}] {lg.get('operation')}", size=11, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            f"Actor: {lg.get('actor', {}).get('actor_name')} ({lg.get('actor', {}).get('actor_source')})",
                            size=11,
                            color=TEXT_SECONDARY,
                        ),
                    ],
                ),
            )
            for lg in logs
        ]

        return ft.Container(
            width=360,
            padding=18,
            bgcolor=BG_SURFACE,
            border=ft.Border.only(left=ft.BorderSide(1, BORDER_COLOR)),
            content=ft.Column(
                expand=True,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text("Automation & Agent Panel", size=16, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                    ft.Container(
                        padding=10,
                        bgcolor=BG_SUBTLE,
                        border_radius=6,
                        content=ft.Column(
                            spacing=4,
                            horizontal_alignment=ft.CrossAxisAlignment.START,
                            controls=[
                                ft.Text("Interfaces Ready:", size=12, weight=ft.FontWeight.BOLD),
                                ft.Text("CLI: scitree", size=11, color=TEXT_SECONDARY),
                                ft.Text("HTTP API: 127.0.0.1:8765 (scitree-api)", size=11, color=TEXT_SECONDARY),
                                ft.Text("MCP Server: stdio/SSE (scitree-mcp)", size=11, color=TEXT_SECONDARY),
                            ],
                        ),
                    ),
                    ft.Button(
                        "Process Automation/inbox Now",
                        bgcolor=ACCENT_BLUE,
                        color="#FFFFFF",
                        on_click=on_process_inbox,
                    ),
                    ft.Text("Last Manifest Result:", size=13, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        str(last_manifest.get("summary") if isinstance(last_manifest, dict) else "None yet"),
                        size=11,
                        color=TEXT_SECONDARY,
                    ),
                    ft.Text("Recent Automated Operations:", size=13, weight=ft.FontWeight.BOLD),
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
                ft.Button("Create", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_create),
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
                ft.Button("Upload", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_submit),
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
                ft.Button("Link & Sync", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_link_and_sync),
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
                ft.Button("Save Template", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_save),
            ],
        )
        self._show_dialog(dlg)

    def _open_settings_modal(self) -> None:
        status = self.core.get_root_status()
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
                    ft.Text(f"Non-loopback API Token: {status.get('api_token')}", size=11, color=TEXT_MUTED),
                ],
            ),
            actions=[
                ft.TextButton("Reset Onboarding", on_click=on_reset_onboarding),
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dlg)),
                ft.Button("Apply Root Path", bgcolor=ACCENT_BLUE, color="#FFFFFF", on_click=on_change_root),
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


if __name__ == "__main__":
    main()
