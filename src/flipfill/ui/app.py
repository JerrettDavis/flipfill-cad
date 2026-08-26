from __future__ import annotations

import contextlib
import copy
import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from flipfill import commands
from flipfill.commands import CommandError
from flipfill.geometry.exporters import export_fitcheck_assembly, export_shape
from flipfill.geometry.generator import (
    GenerationError,
    GenerationResult,
    fit_envelope_to_objects,
    generate,
)
from flipfill.geometry.importers import GeometryRepository
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SliceCutterKind,
    Transform,
    Vector3,
)
from flipfill.project_io import load_project, save_project
from flipfill.ui.icons import IconStore
from flipfill.ui.tooltip import Tooltip
from flipfill.ui.viewport import CadViewport

ENVELOPE_ID = "__envelope__"
RESULT_ID = "__result__"


def _flat_state_map(hover: str, pressed: str) -> list[tuple[str, str]]:
    """ttk state map for a flat control: only hover/pressed deviate from the base color."""
    return [("pressed", pressed), ("active", hover)]


def _apply_windows_dark_titlebar(root: tk.Tk, dark: bool) -> None:
    """Ask the DWM to render the native title bar in dark mode on Windows.

    Silently does nothing on other platforms or older Windows builds that
    don't support the attribute - the OS just keeps its default chrome.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (current, pre-20H1)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
        # The DWM only repaints the caption on its own when the window is
        # resized/moved - force it immediately so toggling themes at runtime
        # doesn't leave a stale (wrong-mode) title bar until the next drag.
        SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)
    except (OSError, AttributeError):
        pass


class FlipFillApp:
    def __init__(self, root: tk.Tk, initial_project: str | None = None) -> None:
        self.root = root
        self.root.title("FlipFill CAD")
        self.root.geometry("1600x920")
        self.root.minsize(1180, 700)

        self.appearance = tk.StringVar(value="Dark")
        self.palette: dict[str, object] = {}
        self.icons = IconStore()
        self._icon_widgets: list[tuple[tk.Widget, str, str | None]] = []

        self.project = Project()
        self.project_path: Path | None = None
        self.repository = GeometryRepository()
        self.generated: GenerationResult | None = None
        self.dirty = False
        self.selected_id: str | None = None
        self.show_envelope = tk.BooleanVar(value=True)

        self._configure_style()
        self._build_menu()
        self._build_toolbar()
        self._build_workspace()
        self._build_statusbar()
        self._apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if initial_project:
            self.open_project_path(Path(initial_project))
        else:
            self._new_default_project()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")
        self._apply_theme()

    def _apply_theme(self) -> None:
        dark = self.appearance.get() == "Dark"
        p = {
            "bg": "#111318" if dark else "#eef0f3",
            "panel": "#1a1d23" if dark else "#ffffff",
            "panel_2": "#22262e" if dark else "#e4e7ec",
            "panel_3": "#2a2f38" if dark else "#d8dce3",
            "field": "#14161b" if dark else "#ffffff",
            "text": "#eef0f3" if dark else "#1c2029",
            "muted": "#8b93a1" if dark else "#5b6472",
            "border": "#2f333c" if dark else "#d6dae1",
            "border_soft": "#23262d" if dark else "#e6e9ee",
            "hover": "#2f343d" if dark else "#e4e7ec",
            "accent": "#4f8cff",
            "accent_active": "#3b74e6",
            "accent_soft": "#25324a" if dark else "#dbe6ff",
            "selection": "#2a4a7a" if dark else "#d6e4ff",
            "danger": "#ff6b6b" if dark else "#c0362c",
            "success": "#3ecf8e",
        }
        p["role_colors"] = {
            ObjectRole.OCCUPANT: p["accent"],
            ObjectRole.CUTOUT: "#f2b134",
            ObjectRole.ADDITIVE: p["success"],
        }
        self.palette = p
        self.root.configure(background=p["bg"])
        _apply_windows_dark_titlebar(self.root, dark)
        style = ttk.Style(self.root)
        style.configure(".", background=p["panel"], foreground=p["text"], font=("Segoe UI", 9))
        style.configure("TFrame", background=p["panel"])
        style.configure("Card.TFrame", background=p["panel_2"])
        style.configure("Toolbar.TFrame", background=p["panel_2"], padding=(14, 9))
        style.configure("MenuBar.TFrame", background=p["panel_2"], padding=(4, 3))
        style.configure(
            "MenuBar.TMenubutton",
            background=p["panel_2"],
            foreground=p["text"],
            bordercolor=p["panel_2"],
            lightcolor=p["panel_2"],
            darkcolor=p["panel_2"],
            padding=(8, 3),
            relief="flat",
        )
        style.map(
            "MenuBar.TMenubutton",
            background=_flat_state_map(p["hover"], p["hover"]),
            bordercolor=_flat_state_map(p["hover"], p["hover"]),
            lightcolor=_flat_state_map(p["hover"], p["hover"]),
            darkcolor=_flat_state_map(p["hover"], p["hover"]),
        )
        style.layout(
            "MenuBar.TMenubutton",
            [
                (
                    "Menubutton.border",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Menubutton.focus",
                                {
                                    "sticky": "nswe",
                                    "children": [
                                        (
                                            "Menubutton.padding",
                                            {
                                                "sticky": "we",
                                                "children": [
                                                    ("Menubutton.label", {"side": "left", "sticky": ""})
                                                ],
                                            },
                                        )
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.configure("Status.TFrame", background=p["panel_2"], padding=(12, 6))
        style.configure("TLabel", background=p["panel"], foreground=p["text"])
        style.configure("Toolbar.TLabel", background=p["panel_2"], foreground=p["text"])
        style.configure("Status.TLabel", background=p["panel_2"], foreground=p["text"])
        style.configure("Title.TLabel", background=p["panel"], font=("Segoe UI Semibold", 11), foreground=p["text"])
        style.configure("Brand.TLabel", background=p["panel_2"], font=("Segoe UI Semibold", 13), foreground=p["text"])
        style.configure("Muted.TLabel", background=p["panel"], foreground=p["muted"])
        style.configure("ToolbarMuted.TLabel", background=p["panel_2"], foreground=p["muted"], font=("Segoe UI", 7))
        style.configure("Section.TLabel", background=p["panel"], font=("Segoe UI Semibold", 8), foreground=p["muted"])
        style.configure("Card.TLabel", background=p["panel_2"], foreground=p["muted"])
        style.configure(
            "CardSection.TLabel",
            background=p["panel_2"],
            font=("Segoe UI Semibold", 8),
            foreground=p["muted"],
        )
        style.configure("Danger.TLabel", background=p["panel"], foreground=p["danger"])
        style.configure(
            "TButton",
            padding=(10, 6),
            background=p["panel_3"],
            foreground=p["text"],
            bordercolor=p["panel_3"],
            lightcolor=p["panel_3"],
            darkcolor=p["panel_3"],
            borderwidth=0,
            focusthickness=0,
            focuscolor=p["panel_3"],
            relief="flat",
        )
        style.map(
            "TButton",
            background=_flat_state_map(p["hover"], p["accent_active"]),
            bordercolor=_flat_state_map(p["hover"], p["accent_active"]),
            lightcolor=_flat_state_map(p["hover"], p["accent_active"]),
            darkcolor=_flat_state_map(p["hover"], p["accent_active"]),
            foreground=[("disabled", p["muted"])],
        )
        style.configure(
            "Accent.TButton",
            background=p["accent"],
            foreground="#ffffff",
            bordercolor=p["accent"],
            lightcolor=p["accent"],
            darkcolor=p["accent"],
            focuscolor=p["accent"],
            font=("Segoe UI Semibold", 9),
            padding=(14, 7),
        )
        style.map(
            "Accent.TButton",
            background=_flat_state_map(p["accent_active"], p["accent_active"]),
            bordercolor=_flat_state_map(p["accent_active"], p["accent_active"]),
            lightcolor=_flat_state_map(p["accent_active"], p["accent_active"]),
            darkcolor=_flat_state_map(p["accent_active"], p["accent_active"]),
        )
        style.configure(
            "Tool.TButton",
            padding=(8, 5),
            background=p["panel_2"],
            bordercolor=p["panel_2"],
            lightcolor=p["panel_2"],
            darkcolor=p["panel_2"],
            focuscolor=p["panel_2"],
        )
        style.map(
            "Tool.TButton",
            background=_flat_state_map(p["hover"], p["accent_active"]),
            bordercolor=_flat_state_map(p["hover"], p["accent_active"]),
            lightcolor=_flat_state_map(p["hover"], p["accent_active"]),
            darkcolor=_flat_state_map(p["hover"], p["accent_active"]),
        )
        style.configure(
            "View.TButton",
            padding=(6, 5),
            background=p["panel_2"],
            bordercolor=p["panel_2"],
            lightcolor=p["panel_2"],
            darkcolor=p["panel_2"],
            focuscolor=p["panel_2"],
        )
        style.map(
            "View.TButton",
            background=_flat_state_map(p["hover"], p["accent_active"]),
            bordercolor=_flat_state_map(p["hover"], p["accent_active"]),
            lightcolor=_flat_state_map(p["hover"], p["accent_active"]),
            darkcolor=_flat_state_map(p["hover"], p["accent_active"]),
        )
        style.configure(
            "TEntry",
            fieldbackground=p["field"],
            foreground=p["text"],
            insertcolor=p["text"],
            bordercolor=p["field"],
            lightcolor=p["field"],
            darkcolor=p["field"],
            padding=6,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", p["accent"]), ("!focus", p["field"])],
            lightcolor=[("focus", p["accent"]), ("!focus", p["field"])],
            darkcolor=[("focus", p["accent"]), ("!focus", p["field"])],
            fieldbackground=[("focus", p["field"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=p["field"],
            background=p["field"],
            foreground=p["text"],
            arrowcolor=p["muted"],
            bordercolor=p["field"],
            lightcolor=p["field"],
            darkcolor=p["field"],
            padding=5,
            relief="flat",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p["field"])],
            foreground=[("readonly", p["text"])],
            background=[("readonly", p["field"])],
            bordercolor=[("focus", p["accent"]), ("!focus", p["field"])],
            lightcolor=[("focus", p["accent"]), ("!focus", p["field"])],
            darkcolor=[("focus", p["accent"]), ("!focus", p["field"])],
            arrowcolor=[("hover", p["accent"]), ("!hover", p["muted"])],
        )
        style.configure(
            "TCheckbutton",
            background=p["panel"],
            foreground=p["text"],
            focuscolor=p["panel"],
            indicatorbackground=p["field"],
            indicatorforeground=p["field"],
            indicatormargin=(0, 0, 6, 0),
        )
        style.map(
            "TCheckbutton",
            background=[("active", p["panel"])],
            indicatorbackground=[("selected", p["accent"]), ("!selected", p["field"])],
            indicatorforeground=[("selected", p["accent"]), ("!selected", p["field"])],
        )
        style.configure(
            "Treeview",
            background=p["panel"],
            fieldbackground=p["panel"],
            foreground=p["text"],
            bordercolor=p["panel"],
            lightcolor=p["panel"],
            darkcolor=p["panel"],
            borderwidth=0,
            relief="flat",
            rowheight=27,
        )
        style.configure(
            "Treeview.Heading",
            background=p["panel_2"],
            foreground=p["muted"],
            font=("Segoe UI Semibold", 8),
            padding=(6, 7),
            relief="flat",
            borderwidth=0,
        )
        style.map("Treeview.Heading", background=[("active", p["panel_3"])])
        style.map(
            "Treeview",
            background=[("selected", p["selection"])],
            foreground=[("selected", "#ffffff" if dark else p["text"])],
        )
        style.configure(
            "TNotebook",
            background=p["panel"],
            bordercolor=p["panel"],
            lightcolor=p["panel"],
            darkcolor=p["panel"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=p["panel"],
            foreground=p["muted"],
            padding=(16, 9),
            font=("Segoe UI Semibold", 9),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", p["panel"])],
            foreground=[("selected", p["accent"])],
        )
        style.configure("TSeparator", background=p["border_soft"])
        style.configure(
            "Vertical.TScrollbar",
            background=p["panel_3"],
            troughcolor=p["panel"],
            bordercolor=p["panel"],
            arrowcolor=p["muted"],
            gripcount=0,
            relief="flat",
        )
        style.map("Vertical.TScrollbar", background=[("active", p["accent"])])
        style.configure(
            "Horizontal.TScrollbar",
            background=p["panel_3"],
            troughcolor=p["panel"],
            bordercolor=p["panel"],
            arrowcolor=p["muted"],
            gripcount=0,
            relief="flat",
        )
        style.map("Horizontal.TScrollbar", background=[("active", p["accent"])])
        self.root.option_add("*TCombobox*Listbox.background", p["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["selection"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff" if dark else p["text"])
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 9))
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.highlightThickness", 1)
        self.root.option_add("*TCombobox*Listbox.highlightColor", p["border"])
        if hasattr(self, "pane"):
            self.pane.configure(bg=p["bg"], sashwidth=6, sashrelief=tk.FLAT, bd=0)
        if hasattr(self, "log"):
            self.log.configure(
                background=p["field"],
                foreground=p["text"],
                insertbackground=p["text"],
                selectbackground=p["selection"],
                relief=tk.FLAT,
                borderwidth=0,
                highlightthickness=1,
                highlightbackground=p["border"],
                highlightcolor=p["accent"],
            )
            self.log.tag_configure("error", foreground=p["danger"])
            self.log.tag_configure("warning", foreground="#f2b134")
            self.log.tag_configure("info", foreground=p["accent"])
            self.log.tag_configure("success", foreground=p["success"])
        if hasattr(self, "viewport"):
            self.viewport.set_theme(dark)
        if hasattr(self, "_menu_bar_items"):
            self._restyle_menus()
        if hasattr(self, "status_dot"):
            self.status_dot.configure(background=p["panel_2"], foreground=p["success"])
        self._refresh_icon_widgets()

    def _refresh_icon_widgets(self) -> None:
        p = self.palette
        if not p:
            return
        for widget, name, accent in self._icon_widgets:
            style_name = ""
            with contextlib.suppress(tk.TclError):
                style_name = str(widget.cget("style"))
            color = "#ffffff" if style_name == "Accent.TButton" else p["muted"]
            photo = self.icons.get(name, color, size=16, accent=accent)
            widget.configure(image=photo)
            widget.image = photo  # type: ignore[attr-defined]

    def _icon_button(
        self,
        parent: tk.Widget,
        text: str,
        icon: str,
        command: Callable[[], None],
        *,
        style: str = "Tool.TButton",
        accent: str | None = None,
        width: int | None = None,
        tooltip: str | None = None,
    ) -> ttk.Button:
        color = "#ffffff" if style == "Accent.TButton" else self.palette.get("muted", "#8b93a1")
        photo = self.icons.get(icon, color, size=16, accent=accent)
        kwargs = {"width": width} if width is not None else {}
        button = ttk.Button(
            parent,
            text=f" {text}" if text else "",
            image=photo,
            compound=tk.LEFT if text else tk.CENTER,
            command=command,
            style=style,
            **kwargs,
        )
        button.image = photo  # type: ignore[attr-defined]
        self._icon_widgets.append((button, icon, accent))
        if tooltip:
            Tooltip(button, tooltip, lambda: self.palette)
        return button

    def _style_menu(self, menu: tk.Menu) -> None:
        p = self.palette
        menu.configure(background=p["panel"], foreground=p["text"], activebackground=p["selection"], activeforeground="#ffffff", borderwidth=0)
        end = menu.index("end")
        if end is not None:
            for index in range(end + 1):
                try:
                    child = menu.nametowidget(menu.entrycget(index, "menu"))
                except (tk.TclError, KeyError):
                    continue
                if isinstance(child, tk.Menu):
                    self._style_menu(child)

    def _restyle_menus(self) -> None:
        for _label, top_menu in self._menu_bar_items:
            self._style_menu(top_menu)

    def _build_menu(self) -> None:
        # A plain ttk.Menubutton row instead of root.config(menu=...): Windows
        # renders the native menu bar with its own light system chrome that
        # ttk/tk styling cannot reach, which reintroduces exactly the bright
        # divider this theme is trying to eliminate.
        bar = ttk.Frame(self.root, style="MenuBar.TFrame")
        bar.pack(side=tk.TOP, fill=tk.X)
        self.menu_bar = bar
        self._menu_bar_items: list[tuple[str, tk.Menu]] = []

        menu = tk.Menu(self.root)

        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_project)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save As…", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import CAD/Mesh…", accelerator="Ctrl+I", command=self.import_geometry)
        file_menu.add_separator()
        file_menu.add_command(label="Export Generated STEP…", command=self.export_step)
        file_menu.add_command(label="Export Fit-Check STEP…", command=self.export_fitcheck)
        file_menu.add_command(label="Export Generated STL…", command=self.export_stl)
        file_menu.add_command(label="Export Package…", command=self.export_package)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        self._menu_bar_items.append(("File", file_menu))

        object_menu = tk.Menu(menu, tearoff=False)
        object_menu.add_command(
            label="Add Occupant Box", command=lambda: self.add_primitive(ObjectRole.OCCUPANT)
        )
        object_menu.add_command(
            label="Add Cutout Blocker", command=lambda: self.add_primitive(ObjectRole.CUTOUT)
        )
        object_menu.add_command(
            label="Add Additive", command=lambda: self.add_primitive(ObjectRole.ADDITIVE)
        )
        object_menu.add_separator()
        object_menu.add_command(label="Duplicate", command=self.duplicate_selected)
        object_menu.add_command(label="Delete", command=self.delete_selected)
        object_menu.add_separator()
        object_menu.add_command(label="Ground to Z=0", command=self.ground_selected)
        object_menu.add_command(label="Center XY", command=self.center_xy_selected)
        self._menu_bar_items.append(("Object", object_menu))

        generate_menu = tk.Menu(menu, tearoff=False)
        generate_menu.add_command(label="Fit Envelope to Included Objects", command=self.fit_envelope_all)
        generate_menu.add_command(label="Fit Envelope to Selection", command=self.fit_envelope_selection)
        generate_menu.add_separator()
        generate_menu.add_command(label="Generate", accelerator="F5", command=self.generate_model)
        generate_menu.add_command(label="Validate", command=self.validate_model)
        self._menu_bar_items.append(("Generate", generate_menu))

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(
            label="Show Envelope", variable=self.show_envelope, command=self.refresh_view
        )
        view_menu.add_separator()
        view_menu.add_command(label="Fit Camera", command=self._fit_camera)
        view_menu.add_command(label="Isometric", command=self.viewport_isometric)
        view_menu.add_command(label="Top", command=self.viewport_top)
        view_menu.add_command(label="Front", command=self.viewport_front)
        view_menu.add_command(label="Side", command=self.viewport_side)
        view_menu.add_separator()
        view_menu.add_command(label="Save Viewport PNG…", command=self.save_viewport_png)
        view_menu.add_separator()
        appearance_menu = tk.Menu(view_menu, tearoff=False)
        for label in ("Dark", "Light"):
            appearance_menu.add_radiobutton(label=label, value=label, variable=self.appearance, command=self._apply_theme)
        view_menu.add_cascade(label="Appearance", menu=appearance_menu)
        self._menu_bar_items.append(("View", view_menu))

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Workflow", command=self.show_workflow_help)
        help_menu.add_command(label="About", command=self.show_about)
        self._menu_bar_items.append(("Help", help_menu))

        for index, (label, top_menu) in enumerate(self._menu_bar_items):
            button = ttk.Menubutton(
                bar, text=label, menu=top_menu, style="MenuBar.TMenubutton", direction="below"
            )
            button.pack(side=tk.LEFT, padx=(10 if index == 0 else 0, 0))
        self._restyle_menus()
        self.root.bind("<Control-n>", lambda _: self.new_project())
        self.root.bind("<Control-o>", lambda _: self.open_project())
        self.root.bind("<Control-s>", lambda _: self.save_project())
        self.root.bind("<Control-i>", lambda _: self.import_geometry())
        self.root.bind("<F5>", lambda _: self.generate_model())
        self.root.bind("<Delete>", lambda _: self.delete_selected())

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, style="Toolbar.TFrame")
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Separator(self.root).pack(side=tk.TOP, fill=tk.X)

        brand = ttk.Frame(bar, style="Toolbar.TFrame")
        brand.pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(brand, text="FLIPFILL", style="Brand.TLabel").pack(anchor=tk.W)
        ttk.Label(brand, text="CLEARANCE CAD", style="ToolbarMuted.TLabel").pack(anchor=tk.W)

        file_buttons: list[tuple[str, str, Callable[[], None]]] = [
            ("new", "New", self.new_project),
            ("open", "Open", self.open_project),
            ("save", "Save", self.save_project),
            ("import", "Import", self.import_geometry),
        ]
        for index, (icon, label, command) in enumerate(file_buttons):
            self._icon_button(bar, label, icon, command).pack(
                side=tk.LEFT, padx=(0 if index == 0 else 3, 0)
            )

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        add_buttons: list[tuple[str, ObjectRole, str]] = [
            ("Occupant", ObjectRole.OCCUPANT, "Add an occupant box (subtracts a clearance cavity)"),
            ("Cutout", ObjectRole.CUTOUT, "Add a cutout blocker (subtracts a port/tooling volume)"),
            ("Additive", ObjectRole.ADDITIVE, "Add an additive (fuses bosses, ribs, pads)"),
        ]
        for index, (label, role, tip) in enumerate(add_buttons):
            self._icon_button(
                bar,
                label,
                "box_add",
                lambda role=role: self.add_primitive(role),
                accent=self.palette["role_colors"][role],
                tooltip=tip,
            ).pack(side=tk.LEFT, padx=(0 if index == 0 else 3, 0))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        self._icon_button(
            bar, "Fit Envelope", "fit", self.fit_envelope_all, tooltip="Fit envelope to included objects"
        ).pack(side=tk.LEFT, padx=2)
        self._icon_button(
            bar,
            "Generate  F5",
            "generate",
            self.generate_model,
            style="Accent.TButton",
            tooltip="Generate the inverse-fill body",
        ).pack(side=tk.LEFT, padx=6)
        self._icon_button(bar, "Export", "export", self.export_step).pack(side=tk.LEFT, padx=2)

        views = ttk.Frame(bar, style="Toolbar.TFrame")
        views.pack(side=tk.RIGHT)
        view_buttons = [
            ("view_iso", "Isometric view", self.viewport_isometric),
            ("view_top", "Top view", self.viewport_top),
            ("view_front", "Front view", self.viewport_front),
            ("view_side", "Side view", self.viewport_side),
            ("fit", "Fit view to scene", self._fit_camera),
        ]
        for icon, tip, command in view_buttons:
            self._icon_button(
                views,
                "",
                icon,
                command,
                style="View.TButton",
                accent=self.palette["accent_soft"],
                tooltip=tip,
            ).pack(side=tk.LEFT, padx=2)

    def _build_workspace(self) -> None:
        pane = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            bg=self.palette["border"],
            showhandle=False,
        )
        self.pane = pane
        pane.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pane, padding=10)
        center = ttk.Frame(pane)
        right = ttk.Frame(pane, padding=10)
        pane.add(left, minsize=250, width=300)
        pane.add(center, minsize=500, stretch="always")
        pane.add(right, minsize=330, width=380)

        self._build_scene_panel(left)
        self.viewport = CadViewport(center, on_select=self._viewport_selected)
        self.viewport.pack(fill=tk.BOTH, expand=True)
        self._build_inspector(right)

    def _build_scene_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Scene", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 5))
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("role", "kind", "visible"),
            show="tree headings",
            selectmode="extended",
        )
        self.tree.heading("#0", text="Name")
        self.tree.heading("role", text="Role")
        self.tree.heading("kind", text="Type")
        self.tree.heading("visible", text="V")
        self.tree.column("#0", width=135, stretch=True)
        self.tree.column("role", width=72, stretch=False)
        self.tree.column("kind", width=65, stretch=False)
        self.tree.column("visible", width=24, stretch=False, anchor=tk.CENTER)

        yscroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.tree.bind("<Double-1>", self._tree_double_click)

        action = ttk.Frame(parent)
        action.pack(fill=tk.X, pady=(8, 0))
        self._icon_button(
            action, "Duplicate", "duplicate", self.duplicate_selected, tooltip="Duplicate selection"
        ).pack(side=tk.LEFT)
        self._icon_button(
            action, "Delete", "delete", self.delete_selected, tooltip="Delete selection"
        ).pack(side=tk.LEFT, padx=4)
        self._icon_button(
            action, "", "eye", self.toggle_visibility_selected, tooltip="Toggle visibility"
        ).pack(side=tk.LEFT)

        ttk.Separator(parent).pack(fill=tk.X, pady=10)
        card = ttk.Frame(parent, style="Card.TFrame", padding=10)
        card.pack(fill=tk.X)
        ttk.Label(card, text="Role semantics", style="CardSection.TLabel").pack(anchor=tk.W)
        help_text = (
            "Occupant  subtract a clearance cavity\n"
            "Cutout    subtract a port/tooling blocker\n"
            "Additive  fuse bosses, ribs, pads\n"
            "Reference display only"
        )
        ttk.Label(
            card, text=help_text, style="Card.TLabel", justify=tk.LEFT, wraplength=250
        ).pack(anchor=tk.W, pady=(5, 0))

    def _build_inspector(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Properties", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 5))
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        object_tab = ttk.Frame(self.notebook, padding=8)
        envelope_tab = ttk.Frame(self.notebook, padding=8)
        generate_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(object_tab, text="Object")
        self.notebook.add(envelope_tab, text="Envelope")
        self.notebook.add(generate_tab, text="Generate")

        self._build_object_tab(object_tab)
        self._build_envelope_tab(envelope_tab)
        self._build_generate_tab(generate_tab)

    @staticmethod
    def _entry_row(
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.Variable,
        width: int = 12,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 6), pady=2)
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(row=row, column=1, sticky=tk.EW, pady=2)
        return entry

    def _vector_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variables: tuple[tk.StringVar, tk.StringVar, tk.StringVar],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 6), pady=2)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky=tk.EW, pady=2)
        for axis, var in zip("XYZ", variables, strict=True):
            ttk.Label(frame, text=axis).pack(side=tk.LEFT, padx=(0, 2))
            ttk.Entry(frame, textvariable=var, width=7).pack(side=tk.LEFT, padx=(0, 5))

    def _build_object_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self.obj_name = tk.StringVar()
        self.obj_role = tk.StringVar(value=ObjectRole.OCCUPANT.value)
        self.obj_visible = tk.BooleanVar(value=True)
        self.obj_fit = tk.BooleanVar(value=True)
        self.obj_source = tk.StringVar(value="No object selected")
        self.obj_clearance_mode = tk.StringVar(value=ClearanceMode.AABB.value)
        self.obj_clearance = tk.StringVar(value="0.5")
        self.obj_tx, self.obj_ty, self.obj_tz = (tk.StringVar(value="0") for _ in range(3))
        self.obj_rx, self.obj_ry, self.obj_rz = (tk.StringVar(value="0") for _ in range(3))
        self.obj_primitive_kind = tk.StringVar(value=PrimitiveKind.BOX.value)
        self.obj_sx, self.obj_sy, self.obj_sz = (tk.StringVar(value="20") for _ in range(3))
        self.obj_radius = tk.StringVar(value="2")

        self._entry_row(parent, 0, "Name", self.obj_name)
        ttk.Label(parent, text="Role").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            parent,
            textvariable=self.obj_role,
            values=[role.value for role in ObjectRole if role is not ObjectRole.RESULT],
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, pady=2)

        check_frame = ttk.Frame(parent)
        check_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 6))
        ttk.Checkbutton(check_frame, text="Visible", variable=self.obj_visible).pack(side=tk.LEFT)
        ttk.Checkbutton(
            check_frame, text="Include in envelope fit", variable=self.obj_fit
        ).pack(side=tk.LEFT, padx=8)

        ttk.Label(parent, text="Source", style="Section.TLabel").grid(
            row=3, column=0, columnspan=2, sticky=tk.W, pady=(7, 2)
        )
        ttk.Label(parent, textvariable=self.obj_source, wraplength=320, justify=tk.LEFT).grid(
            row=4, column=0, columnspan=2, sticky=tk.W
        )

        ttk.Label(parent, text="Transform (mm / degrees)", style="Section.TLabel").grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=(10, 2)
        )
        self._vector_row(parent, 6, "Position", (self.obj_tx, self.obj_ty, self.obj_tz))
        self._vector_row(parent, 7, "Rotation", (self.obj_rx, self.obj_ry, self.obj_rz))

        ttk.Label(parent, text="Subtractive clearance", style="Section.TLabel").grid(
            row=8, column=0, columnspan=2, sticky=tk.W, pady=(10, 2)
        )
        ttk.Label(parent, text="Mode").grid(row=9, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            parent,
            textvariable=self.obj_clearance_mode,
            values=[mode.value for mode in ClearanceMode],
            state="readonly",
        ).grid(row=9, column=1, sticky=tk.EW, pady=2)
        self._entry_row(parent, 10, "Clearance", self.obj_clearance)

        ttk.Label(parent, text="Primitive", style="Section.TLabel").grid(
            row=11, column=0, columnspan=2, sticky=tk.W, pady=(10, 2)
        )
        ttk.Label(parent, text="Kind").grid(row=12, column=0, sticky=tk.W, pady=2)
        self.primitive_kind_widget = ttk.Combobox(
            parent,
            textvariable=self.obj_primitive_kind,
            values=[kind.value for kind in PrimitiveKind],
            state="readonly",
        )
        self.primitive_kind_widget.grid(row=12, column=1, sticky=tk.EW, pady=2)
        self._vector_row(parent, 13, "Size", (self.obj_sx, self.obj_sy, self.obj_sz))
        self._entry_row(parent, 14, "Radius", self.obj_radius)

        button_frame = ttk.Frame(parent)
        button_frame.grid(row=15, column=0, columnspan=2, sticky=tk.EW, pady=(14, 0))
        ttk.Button(button_frame, text="Apply", command=self.apply_object_properties).pack(
            side=tk.LEFT
        )
        ttk.Button(button_frame, text="Ground Z", command=self.ground_selected).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(button_frame, text="Center XY", command=self.center_xy_selected).pack(
            side=tk.LEFT
        )

    def _build_envelope_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        self.env_kind = tk.StringVar(value=PrimitiveKind.ROUNDED_BOX.value)
        self.env_sx, self.env_sy, self.env_sz = (tk.StringVar(value="100") for _ in range(3))
        self.env_tx, self.env_ty, self.env_tz = (tk.StringVar(value="0") for _ in range(3))
        self.env_rx, self.env_ry, self.env_rz = (tk.StringVar(value="0") for _ in range(3))
        self.env_radius = tk.StringVar(value="6")
        self.env_mx, self.env_my, self.env_mz = (tk.StringVar(value="3") for _ in range(3))

        ttk.Label(parent, text="Envelope primitive", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(parent, text="Kind").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            parent,
            textvariable=self.env_kind,
            values=[PrimitiveKind.BOX.value, PrimitiveKind.ROUNDED_BOX.value],
            state="readonly",
        ).grid(row=1, column=1, sticky=tk.EW, pady=2)
        self._vector_row(parent, 2, "Size", (self.env_sx, self.env_sy, self.env_sz))
        self._vector_row(parent, 3, "Center", (self.env_tx, self.env_ty, self.env_tz))
        self._vector_row(parent, 4, "Rotation", (self.env_rx, self.env_ry, self.env_rz))
        self._entry_row(parent, 5, "Corner radius", self.env_radius)

        ttk.Label(parent, text="Auto-fit margins", style="Section.TLabel").grid(
            row=6, column=0, columnspan=2, sticky=tk.W, pady=(12, 2)
        )
        self._vector_row(parent, 7, "Margins", (self.env_mx, self.env_my, self.env_mz))

        buttons = ttk.Frame(parent)
        buttons.grid(row=8, column=0, columnspan=2, sticky=tk.EW, pady=(14, 0))
        ttk.Button(buttons, text="Apply", command=self.apply_envelope_properties).pack(
            side=tk.LEFT
        )
        ttk.Button(buttons, text="Fit All", command=self.fit_envelope_all).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(buttons, text="Fit Selection", command=self.fit_envelope_selection).pack(
            side=tk.LEFT
        )

        ttk.Separator(parent).grid(row=9, column=0, columnspan=2, sticky=tk.EW, pady=14)
        ttk.Label(parent, text="Inverse-fill equation", style="Section.TLabel").grid(
            row=10, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(
            parent,
            text="result = (envelope ∪ additives) − occupants − cutouts",
            wraplength=320,
            justify=tk.LEFT,
        ).grid(row=11, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

    def _build_generate_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(8, weight=1)
        self.slicing_enabled = tk.BooleanVar(value=False)
        self.slice_remainder_name = tk.StringVar(value="Remainder")
        self.slice_name = tk.StringVar(value="")
        self.slice_cutter_kind = tk.StringVar(value=SliceCutterKind.PLANE.value)
        self.slice_object_ref = tk.StringVar(value="")
        self.slice_x = tk.StringVar(value="0")
        self.slice_y = tk.StringVar(value="0")
        self.slice_z = tk.StringVar(value="0")
        self.slice_rx = tk.StringVar(value="0")
        self.slice_ry = tk.StringVar(value="0")
        self.slice_rz = tk.StringVar(value="0")
        self.slice_gap = tk.StringVar(value="0")

        ttk.Label(parent, text="Slices", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Checkbutton(
            parent, text="Enable slicing on generate", variable=self.slicing_enabled
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=3)

        self.slice_tree = ttk.Treeview(
            parent,
            columns=("name", "kind", "summary"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self.slice_tree.heading("name", text="Name")
        self.slice_tree.heading("kind", text="Cutter")
        self.slice_tree.heading("summary", text="Summary")
        self.slice_tree.column("name", width=110)
        self.slice_tree.column("kind", width=60)
        self.slice_tree.column("summary", width=140)
        self.slice_tree.grid(row=2, column=0, columnspan=2, sticky=tk.NSEW, pady=(4, 4))
        self.slice_tree.bind("<<TreeviewSelect>>", self._slice_tree_selected)

        list_buttons = ttk.Frame(parent)
        list_buttons.grid(row=3, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(list_buttons, text="Add", command=self.add_slice_row).pack(side=tk.LEFT)
        ttk.Button(list_buttons, text="Remove", command=self.remove_slice_row).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(list_buttons, text="Move Up", command=lambda: self.move_slice_row(-1)).pack(
            side=tk.LEFT
        )
        ttk.Button(list_buttons, text="Move Down", command=lambda: self.move_slice_row(1)).pack(
            side=tk.LEFT, padx=4
        )

        editor = ttk.Frame(parent)
        editor.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(8, 0))
        editor.columnconfigure(1, weight=1)
        self._entry_row(editor, 0, "Name", self.slice_name)
        ttk.Label(editor, text="Cutter").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=2)
        ttk.Combobox(
            editor,
            textvariable=self.slice_cutter_kind,
            values=[kind.value for kind in SliceCutterKind],
            state="readonly",
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, pady=2)
        self._entry_row(editor, 2, "Object (id or name)", self.slice_object_ref)
        self._entry_row(editor, 3, "Plane X", self.slice_x)
        self._entry_row(editor, 4, "Plane Y", self.slice_y)
        self._entry_row(editor, 5, "Plane Z", self.slice_z)
        self._entry_row(editor, 6, "Plane rotate X", self.slice_rx)
        self._entry_row(editor, 7, "Plane rotate Y", self.slice_ry)
        self._entry_row(editor, 8, "Plane rotate Z", self.slice_rz)
        self._entry_row(editor, 9, "Kerf gap", self.slice_gap)
        ttk.Button(editor, text="Apply Row", command=self.apply_slice_row).grid(
            row=10, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        ttk.Label(parent, text="Remainder name").grid(row=5, column=0, sticky=tk.W, pady=(8, 2))
        ttk.Entry(parent, textvariable=self.slice_remainder_name).grid(
            row=5, column=1, sticky=tk.EW, pady=(8, 2)
        )

        buttons = ttk.Frame(parent)
        buttons.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(10, 4))
        ttk.Button(buttons, text="Generate", command=self.generate_model).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Validate", command=self.validate_model).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(buttons, text="Export Package", command=self.export_package).pack(
            side=tk.LEFT
        )

        ttk.Label(parent, text="Generation report", style="Section.TLabel").grid(
            row=7, column=0, columnspan=2, sticky=tk.W, pady=(8, 3)
        )
        log_frame = ttk.Frame(parent)
        log_frame.grid(row=8, column=0, columnspan=2, sticky=tk.NSEW)
        self.log = tk.Text(
            log_frame,
            height=18,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_statusbar(self) -> None:
        self.status = tk.StringVar(value="Ready")
        ttk.Separator(self.root).pack(side=tk.BOTTOM, fill=tk.X)
        frame = ttk.Frame(self.root, style="Status.TFrame")
        frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_dot = ttk.Label(frame, text="●", style="Status.TLabel")
        self.status_dot.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(frame, textvariable=self.status, style="Status.TLabel").pack(side=tk.LEFT)
        self.project_label = ttk.Label(frame, text="", style="ToolbarMuted.TLabel")
        self.project_label.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def _new_default_project(self) -> None:
        self.project = Project(name="Untitled Enclosure")
        self.project_path = None
        self.repository.clear()
        self.generated = None
        self.dirty = False
        self.selected_id = ENVELOPE_ID
        self._sync_all_controls()
        self.refresh_scene_tree()
        self.refresh_view(fit=True)
        self._update_title()
        self._write_log("Import STEP/BREP/IGES objects or add primitives to begin.\n", "info")

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()

    def _invalidate_generation(self) -> None:
        self.generated = None
        self._clear_log()

    def _update_title(self) -> None:
        marker = " *" if self.dirty else ""
        location = str(self.project_path) if self.project_path else "Unsaved project"
        self.root.title(f"FlipFill CAD — {self.project.name}{marker}")
        self.project_label.configure(text=location)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        response = messagebox.askyesnocancel(
            "Unsaved changes",
            "Save changes before continuing?",
            parent=self.root,
        )
        if response is None:
            return False
        if response:
            return self.save_project()
        return True

    @staticmethod
    def _float(value: tk.StringVar, label: str) -> float:
        try:
            return float(value.get().strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be a number") from exc

    @staticmethod
    def _slugify_body_name(name: str) -> str:
        slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
        return slug or "body"

    def _selected_scene_objects(self) -> list[SceneObject]:
        ids = set(self.tree.selection())
        return [obj for obj in self.project.objects if obj.id in ids]

    def _selected_object(self) -> SceneObject | None:
        return self.project.object_by_id(self.selected_id or "")

    # ------------------------------------------------------------------
    # Project commands
    # ------------------------------------------------------------------
    def new_project(self) -> None:
        if self._confirm_discard():
            self._new_default_project()

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Open FlipFill project",
            filetypes=(("FlipFill projects", "*.flipfill.json *.json"), ("All files", "*.*")),
        )
        if filename:
            self.open_project_path(Path(filename))

    def open_project_path(self, path: Path) -> None:
        try:
            project = load_project(path)
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc), parent=self.root)
            return
        self.project = project
        self.project_path = path.expanduser().resolve()
        self.repository.clear()
        self.generated = None
        self.dirty = False
        self.selected_id = ENVELOPE_ID
        self._sync_all_controls()
        self.refresh_scene_tree()
        self.refresh_view(fit=True)
        self._update_title()
        self.status.set(f"Opened {self.project_path.name}")

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_project_as()
        try:
            self._apply_current_panel_if_possible()
            save_project(self.project, self.project_path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return False
        self.dirty = False
        self._update_title()
        self.status.set(f"Saved {self.project_path.name}")
        return True

    def save_project_as(self) -> bool:
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save FlipFill project",
            defaultextension=".flipfill.json",
            filetypes=(("FlipFill project", "*.flipfill.json"), ("JSON", "*.json")),
        )
        if not filename:
            return False
        self.project_path = Path(filename).expanduser().resolve()
        return self.save_project()

    # ------------------------------------------------------------------
    # Scene commands
    # ------------------------------------------------------------------
    def import_geometry(self) -> None:
        filenames = filedialog.askopenfilenames(
            parent=self.root,
            title="Import CAD or mesh reference",
            filetypes=self.repository.supported_file_patterns(),
        )
        if not filenames:
            return

        added: list[SceneObject] = []
        failures: list[str] = []
        for filename in filenames:
            scene_object = SceneObject(
                name=Path(filename).stem,
                source_path=str(Path(filename).expanduser().resolve()),
                role=ObjectRole.OCCUPANT,
                clearance_mode=ClearanceMode.AABB,
                clearance_mm=0.5,
            )
            try:
                self.repository.resolve(scene_object)
            except Exception as exc:
                failures.append(f"{Path(filename).name}: {exc}")
                continue
            self.project.objects.append(scene_object)
            added.append(scene_object)

        if added:
            self._mark_dirty()
            self._invalidate_generation()
            self.selected_id = added[-1].id
            self.refresh_scene_tree()
            self._select_tree_id(self.selected_id)
            self.refresh_view(fit=True)
            self.status.set(f"Imported {len(added)} object(s)")
        if failures:
            messagebox.showwarning(
                "Some imports failed", "\n\n".join(failures), parent=self.root
            )

    def add_primitive(self, role: ObjectRole) -> None:
        if role is ObjectRole.OCCUPANT:
            primitive = PrimitiveSpec(
                PrimitiveKind.ROUNDED_BOX, Vector3(40.0, 30.0, 10.0), 3.0
            )
            clearance_mode = ClearanceMode.AABB
            name = "Occupant"
        elif role is ObjectRole.CUTOUT:
            primitive = PrimitiveSpec(PrimitiveKind.BOX, Vector3(14.0, 8.0, 8.0), 1.0)
            clearance_mode = ClearanceMode.EXACT
            name = "Cutout"
        else:
            primitive = PrimitiveSpec(PrimitiveKind.CYLINDER, Vector3(8.0, 8.0, 8.0), 0.0)
            clearance_mode = ClearanceMode.EXACT
            name = "Additive"

        scene_object = SceneObject(
            name=name,
            role=role,
            primitive=primitive,
            clearance_mode=clearance_mode,
            clearance_mm=0.5 if role is ObjectRole.OCCUPANT else 0.0,
            included_in_envelope_fit=role is not ObjectRole.CUTOUT,
        )
        self.project.objects.append(scene_object)
        self.selected_id = scene_object.id
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_scene_tree()
        self._select_tree_id(scene_object.id)
        self.refresh_view()

    def duplicate_selected(self) -> None:
        selected = self._selected_scene_objects()
        if not selected:
            return
        duplicates: list[SceneObject] = []
        from uuid import uuid4

        for scene_object in selected:
            duplicate = copy.deepcopy(scene_object)
            duplicate.id = str(uuid4())
            duplicate.name = f"{scene_object.name} Copy"
            duplicate.transform.translation.x += 5.0
            duplicate.transform.translation.y += 5.0
            duplicates.append(duplicate)
        self.project.objects.extend(duplicates)
        self.selected_id = duplicates[-1].id
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_scene_tree()
        self._select_tree_id(self.selected_id)
        self.refresh_view()

    def delete_selected(self) -> None:
        selected = self._selected_scene_objects()
        if not selected:
            return
        names = ", ".join(obj.name for obj in selected[:3])
        if len(selected) > 3:
            names += f" and {len(selected) - 3} more"
        if not messagebox.askyesno(
            "Delete objects", f"Delete {names}?", parent=self.root
        ):
            return
        self.project.remove_objects(obj.id for obj in selected)
        self.selected_id = ENVELOPE_ID
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_scene_tree()
        self._select_tree_id(ENVELOPE_ID)
        self.refresh_view()

    def toggle_visibility_selected(self) -> None:
        selected = self._selected_scene_objects()
        if not selected:
            if self.selected_id == ENVELOPE_ID:
                self.show_envelope.set(not self.show_envelope.get())
                self.refresh_view()
            return
        for scene_object in selected:
            scene_object.visible = not scene_object.visible
        self._mark_dirty()
        self.refresh_scene_tree()
        self.refresh_view()

    def ground_selected(self) -> None:
        scene_object = self._selected_object()
        if scene_object is None:
            return
        try:
            resolved = self.repository.resolve(scene_object)
            scene_object.transform.translation.z -= resolved.bounds.minimum.z
        except Exception as exc:
            messagebox.showerror("Ground failed", str(exc), parent=self.root)
            return
        self._after_object_change(scene_object)

    def center_xy_selected(self) -> None:
        scene_object = self._selected_object()
        if scene_object is None:
            return
        try:
            resolved = self.repository.resolve(scene_object)
            scene_object.transform.translation.x -= resolved.bounds.center.x
            scene_object.transform.translation.y -= resolved.bounds.center.y
        except Exception as exc:
            messagebox.showerror("Center failed", str(exc), parent=self.root)
            return
        self._after_object_change(scene_object)

    # ------------------------------------------------------------------
    # Property application
    # ------------------------------------------------------------------
    def apply_object_properties(self) -> None:
        scene_object = self._selected_object()
        if scene_object is None:
            return
        try:
            scene_object.name = self.obj_name.get().strip() or scene_object.name
            scene_object.role = ObjectRole(self.obj_role.get())
            scene_object.visible = bool(self.obj_visible.get())
            scene_object.included_in_envelope_fit = bool(self.obj_fit.get())
            scene_object.transform = Transform(
                translation=Vector3(
                    self._float(self.obj_tx, "Position X"),
                    self._float(self.obj_ty, "Position Y"),
                    self._float(self.obj_tz, "Position Z"),
                ),
                rotation_deg=Vector3(
                    self._float(self.obj_rx, "Rotation X"),
                    self._float(self.obj_ry, "Rotation Y"),
                    self._float(self.obj_rz, "Rotation Z"),
                ),
            )
            scene_object.clearance_mode = ClearanceMode(self.obj_clearance_mode.get())
            scene_object.clearance_mm = max(0.0, self._float(self.obj_clearance, "Clearance"))
            if scene_object.primitive is not None:
                scene_object.primitive.kind = PrimitiveKind(self.obj_primitive_kind.get())
                scene_object.primitive.size = Vector3(
                    self._float(self.obj_sx, "Size X"),
                    self._float(self.obj_sy, "Size Y"),
                    self._float(self.obj_sz, "Size Z"),
                )
                scene_object.primitive.radius = max(
                    0.0, self._float(self.obj_radius, "Radius")
                )
                self.repository.resolve(scene_object)
        except Exception as exc:
            messagebox.showerror("Invalid properties", str(exc), parent=self.root)
            self._load_object_controls(scene_object)
            return
        self._after_object_change(scene_object)

    def _after_object_change(self, scene_object: SceneObject) -> None:
        self._mark_dirty()
        self._invalidate_generation()
        self._load_object_controls(scene_object)
        self.refresh_scene_tree()
        self._select_tree_id(scene_object.id)
        self.refresh_view()

    def apply_envelope_properties(self) -> None:
        try:
            self.project.envelope.kind = PrimitiveKind(self.env_kind.get())
            self.project.envelope.size = Vector3(
                self._float(self.env_sx, "Envelope size X"),
                self._float(self.env_sy, "Envelope size Y"),
                self._float(self.env_sz, "Envelope size Z"),
            )
            self.project.envelope.transform = Transform(
                translation=Vector3(
                    self._float(self.env_tx, "Envelope center X"),
                    self._float(self.env_ty, "Envelope center Y"),
                    self._float(self.env_tz, "Envelope center Z"),
                ),
                rotation_deg=Vector3(
                    self._float(self.env_rx, "Envelope rotation X"),
                    self._float(self.env_ry, "Envelope rotation Y"),
                    self._float(self.env_rz, "Envelope rotation Z"),
                ),
            )
            self.project.envelope.radius = max(
                0.0, self._float(self.env_radius, "Envelope radius")
            )
            self.project.envelope.fit_margin = Vector3(
                max(0.0, self._float(self.env_mx, "Fit margin X")),
                max(0.0, self._float(self.env_my, "Fit margin Y")),
                max(0.0, self._float(self.env_mz, "Fit margin Z")),
            )
            from flipfill.geometry.generator import envelope_shape

            envelope_shape(self.project)
        except Exception as exc:
            messagebox.showerror("Invalid envelope", str(exc), parent=self.root)
            self._load_envelope_controls()
            return
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_view()

    def _slice_tree_selected(self, _event=None) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        slice_spec = self.project.slicing.slices[index]
        self.slice_name.set(slice_spec.name)
        self.slice_cutter_kind.set(slice_spec.cutter_kind.value)
        self.slice_object_ref.set(slice_spec.object_id or "")
        self.slice_x.set(str(slice_spec.transform.translation.x))
        self.slice_y.set(str(slice_spec.transform.translation.y))
        self.slice_z.set(str(slice_spec.transform.translation.z))
        self.slice_rx.set(str(slice_spec.transform.rotation_deg.x))
        self.slice_ry.set(str(slice_spec.transform.rotation_deg.y))
        self.slice_rz.set(str(slice_spec.transform.rotation_deg.z))
        self.slice_gap.set(str(slice_spec.gap))

    def refresh_slice_tree(self) -> None:
        self.slice_tree.delete(*self.slice_tree.get_children())
        for index, slice_spec in enumerate(self.project.slicing.slices):
            if slice_spec.cutter_kind is SliceCutterKind.PLANE:
                summary = (
                    f"z={slice_spec.transform.translation.z:.2f} gap={slice_spec.gap:.2f}"
                )
            else:
                target = self.project.object_by_id(slice_spec.object_id or "")
                summary = f"object: {target.name if target else slice_spec.object_id}"
            self.slice_tree.insert(
                "", tk.END, iid=str(index),
                values=(slice_spec.name, slice_spec.cutter_kind.value, summary),
            )

    def add_slice_row(self, index: int | None = None) -> None:
        try:
            commands.add_slice(
                self.project,
                name=self.slice_name.get() or f"Slice {len(self.project.slicing.slices) + 1}",
                cutter_kind=SliceCutterKind(self.slice_cutter_kind.get()),
                transform=Transform(
                    translation=Vector3(
                        self._float(self.slice_x, "Plane X"),
                        self._float(self.slice_y, "Plane Y"),
                        self._float(self.slice_z, "Plane Z"),
                    ),
                    rotation_deg=Vector3(
                        self._float(self.slice_rx, "Plane rotate X"),
                        self._float(self.slice_ry, "Plane rotate Y"),
                        self._float(self.slice_rz, "Plane rotate Z"),
                    ),
                ),
                gap=max(0.0, self._float(self.slice_gap, "Kerf gap")),
                object_id=self.slice_object_ref.get() or None,
                index=index,
            )
        except (CommandError, ValueError) as exc:
            messagebox.showerror("Invalid slice", str(exc), parent=self.root)
            return
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()

    def remove_slice_row(self) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        # The tree row index is authoritative here; passing the slice's name
        # would let a slice literally named "2" resolve as index 2.
        try:
            commands.remove_slice(self.project, str(index))
        except CommandError as exc:
            messagebox.showerror("Invalid slice", str(exc), parent=self.root)
            return
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()

    def move_slice_row(self, offset: int) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        try:
            commands.reorder_slice(self.project, str(index), index + offset)
        except CommandError as exc:
            messagebox.showerror("Invalid slice", str(exc), parent=self.root)
            return
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()
        new_index = max(0, min(index + offset, len(self.project.slicing.slices) - 1))
        self.slice_tree.selection_set(str(new_index))

    def apply_slice_row(self) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            self.add_slice_row()
            return
        index = int(selection[0])
        try:
            commands.update_slice(
                self.project,
                str(index),
                name=self.slice_name.get() or None,
                cutter_kind=SliceCutterKind(self.slice_cutter_kind.get()),
                transform=Transform(
                    translation=Vector3(
                        self._float(self.slice_x, "Plane X"),
                        self._float(self.slice_y, "Plane Y"),
                        self._float(self.slice_z, "Plane Z"),
                    ),
                    rotation_deg=Vector3(
                        self._float(self.slice_rx, "Plane rotate X"),
                        self._float(self.slice_ry, "Plane rotate Y"),
                        self._float(self.slice_rz, "Plane rotate Z"),
                    ),
                ),
                gap=max(0.0, self._float(self.slice_gap, "Kerf gap")),
                object_id=self.slice_object_ref.get() or None,
            )
        except (CommandError, ValueError) as exc:
            messagebox.showerror("Invalid slice", str(exc), parent=self.root)
            return
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()

    def _apply_slicing_controls(self) -> None:
        commands.configure_slicing(
            self.project,
            enabled=bool(self.slicing_enabled.get()),
            remainder_name=self.slice_remainder_name.get() or None,
        )

    def _apply_current_panel_if_possible(self) -> None:
        current = self.notebook.index(self.notebook.select())
        if current == 0 and self._selected_object() is not None:
            self.apply_object_properties()
        elif current == 1:
            self.apply_envelope_properties()
        elif current == 2:
            self._apply_slicing_controls()

    # ------------------------------------------------------------------
    # Envelope and generation
    # ------------------------------------------------------------------
    def fit_envelope_all(self) -> None:
        try:
            self.apply_envelope_properties()
            fitted = fit_envelope_to_objects(self.project, self.repository)
        except Exception as exc:
            messagebox.showerror("Envelope fit failed", str(exc), parent=self.root)
            return
        self._load_envelope_controls()
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_view(fit=True)
        size = fitted.size
        self.status.set(f"Envelope fitted to {size.x:.2f} × {size.y:.2f} × {size.z:.2f} mm")

    def fit_envelope_selection(self) -> None:
        selected = self._selected_scene_objects()
        if not selected:
            messagebox.showinfo(
                "Fit selection", "Select one or more scene objects first.", parent=self.root
            )
            return
        try:
            self.apply_envelope_properties()
            fit_envelope_to_objects(
                self.project, self.repository, [scene_object.id for scene_object in selected]
            )
        except Exception as exc:
            messagebox.showerror("Envelope fit failed", str(exc), parent=self.root)
            return
        self._load_envelope_controls()
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_view(fit=True)

    def generate_model(self) -> GenerationResult | None:
        try:
            self._apply_current_panel_if_possible()
            self._apply_slicing_controls()
            generated = generate(self.project, self.repository)
        except GenerationError as exc:
            self.generated = None
            self._clear_log()
            self._write_log(f"ERROR: {exc}\n", "error")
            messagebox.showerror("Generation failed", str(exc), parent=self.root)
            return None
        except Exception as exc:
            self.generated = None
            messagebox.showerror("Generation failed", str(exc), parent=self.root)
            return None

        self.generated = generated
        self.refresh_slice_tree()
        self._display_generation_report(generated)
        self.refresh_scene_tree()
        self.refresh_view(fit=True)
        error_count = len(generated.errors)
        warning_count = len(generated.warnings)
        self.status.set(
            f"Generated {generated.result.Volume():.1f} mm³; "
            f"{warning_count} warning(s), {error_count} error(s)"
        )
        self.notebook.select(2)
        return generated

    def validate_model(self) -> None:
        generated = self.generate_model()
        if generated is None:
            return
        if generated.errors:
            messagebox.showerror(
                "Validation failed",
                f"The model has {len(generated.errors)} validation error(s). See the report.",
                parent=self.root,
            )
        elif generated.warnings:
            messagebox.showwarning(
                "Validation completed",
                f"The model is valid but has {len(generated.warnings)} warning(s).",
                parent=self.root,
            )
        else:
            messagebox.showinfo(
                "Validation completed",
                "The generated BRep is valid and all tested cavity intersections are clear.",
                parent=self.root,
            )

    def _display_generation_report(self, generated: GenerationResult) -> None:
        self._clear_log()
        self._write_log(
            f"Generated volume: {generated.result.Volume():.3f} mm³\n"
            f"BRep valid: {generated.result.isValid()}\n"
            f"Occupant cavities: {len(generated.cavity_shapes)}\n"
            f"Cutouts: {len(generated.cutout_shapes)}\n"
            f"Additives: {len(generated.additive_shapes)}\n\n",
            "success" if not generated.errors else "warning",
        )
        if not generated.messages:
            self._write_log("No validation warnings or errors.\n", "success")
        for message in generated.messages:
            object_name = ""
            if message.object_id:
                scene_object = self.project.object_by_id(message.object_id)
                if scene_object:
                    object_name = f" [{scene_object.name}]"
            self._write_log(
                f"{message.level.value.upper()}{object_name}: {message.message}\n",
                message.level.value,
            )
        if generated.sliced_bodies:
            lines = "".join(
                f"{name} volume: {shape.Volume():.3f} mm³\n"
                for name, shape in generated.sliced_bodies.items()
            )
            self._write_log(f"\n{lines}", "info")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _ensure_generated(self) -> GenerationResult | None:
        return self.generated or self.generate_model()

    def export_step(self) -> None:
        generated = self._ensure_generated()
        if generated is None:
            return
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export generated STEP",
            defaultextension=".step",
            filetypes=(("STEP", "*.step *.stp"),),
        )
        if not filename:
            return
        try:
            path = export_shape(generated.result, filename)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        self.status.set(f"Exported {path.name}")

    def export_fitcheck(self) -> None:
        generated = self._ensure_generated()
        if generated is None:
            return
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export fit-check STEP assembly",
            defaultextension=".step",
            filetypes=(("STEP", "*.step *.stp"),),
        )
        if not filename:
            return
        try:
            path = export_fitcheck_assembly(self.project, generated, filename)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        self.status.set(f"Exported {path.name}")

    def export_stl(self) -> None:
        generated = self._ensure_generated()
        if generated is None:
            return
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export generated STL",
            defaultextension=".stl",
            filetypes=(("STL", "*.stl"),),
        )
        if not filename:
            return
        try:
            path = export_shape(generated.result, filename)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        self.status.set(f"Exported {path.name}")

    def export_package(self) -> None:
        generated = self._ensure_generated()
        if generated is None:
            return
        directory = filedialog.askdirectory(parent=self.root, title="Export package directory")
        if not directory:
            return
        output = Path(directory).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.project.name
        ).strip("_") or "flipfill"
        try:
            export_shape(generated.result, output / f"{safe_name}.step")
            export_shape(generated.result, output / f"{safe_name}.stl")
            export_fitcheck_assembly(
                self.project, generated, output / f"{safe_name}_fitcheck.step"
            )
            seen_slugs: dict[str, int] = {}
            for name, shape in generated.sliced_bodies.items():
                # Distinct body names can slugify identically ("Top"/"top");
                # suffix later collisions so no file silently overwrites another.
                slug = self._slugify_body_name(name)
                count = seen_slugs.get(slug, 0) + 1
                seen_slugs[slug] = count
                if count > 1:
                    slug = f"{slug}_{count}"
                export_shape(shape, output / f"{safe_name}_{slug}.step")
            save_project(self.project, output / f"{safe_name}.flipfill.json")
            self.viewport.save_screenshot(output / f"{safe_name}_preview.png")
        except Exception as exc:
            messagebox.showerror("Package export failed", str(exc), parent=self.root)
            return
        self.status.set(f"Exported package to {output}")
        messagebox.showinfo(
            "Package exported",
            f"Generated body, STL, fit-check assembly, project, sliced bodies (when enabled), "
            f"and preview were written to:\n\n{output}",
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Selection and control synchronization
    # ------------------------------------------------------------------
    def refresh_scene_tree(self) -> None:
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.tree.insert(
            "",
            tk.END,
            iid=ENVELOPE_ID,
            text="Envelope",
            values=("envelope", self.project.envelope.kind.value, "●" if self.show_envelope.get() else ""),
        )
        for scene_object in self.project.objects:
            kind = scene_object.geometry_kind.value
            self.tree.insert(
                "",
                tk.END,
                iid=scene_object.id,
                text=scene_object.name,
                values=(scene_object.role.value, kind, "●" if scene_object.visible else ""),
            )
        if self.generated is not None:
            self.tree.insert(
                "",
                tk.END,
                iid=RESULT_ID,
                text="Generated body",
                values=("result", "brep", "●"),
            )
        available = [item for item in selected if self.tree.exists(item)]
        if available:
            self.tree.selection_set(available)
        elif self.selected_id and self.tree.exists(self.selected_id):
            self.tree.selection_set(self.selected_id)

    def _tree_selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        selected_id = selection[-1]
        self.selected_id = selected_id
        self.viewport.select(selected_id)
        if selected_id == ENVELOPE_ID:
            self._load_envelope_controls()
            self.notebook.select(1)
        elif selected_id == RESULT_ID:
            self.notebook.select(2)
        else:
            scene_object = self.project.object_by_id(selected_id)
            if scene_object:
                self._load_object_controls(scene_object)
                self.notebook.select(0)

    def _tree_double_click(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        selected_id = selected[-1]
        if selected_id == ENVELOPE_ID:
            self.show_envelope.set(not self.show_envelope.get())
        elif selected_id not in {RESULT_ID}:
            scene_object = self.project.object_by_id(selected_id)
            if scene_object:
                scene_object.visible = not scene_object.visible
                self._mark_dirty()
        self.refresh_scene_tree()
        self.refresh_view()

    def _viewport_selected(self, object_id: str | None) -> None:
        if object_id is None or not self.tree.exists(object_id):
            return
        self._select_tree_id(object_id)

    def _select_tree_id(self, object_id: str) -> None:
        if self.tree.exists(object_id):
            self.tree.selection_set(object_id)
            self.tree.focus(object_id)
            self.tree.see(object_id)
            self._tree_selected()

    def _load_object_controls(self, scene_object: SceneObject) -> None:
        self.obj_name.set(scene_object.name)
        self.obj_role.set(scene_object.role.value)
        self.obj_visible.set(scene_object.visible)
        self.obj_fit.set(scene_object.included_in_envelope_fit)
        self.obj_source.set(scene_object.source_path or "Generated primitive")
        self.obj_clearance_mode.set(scene_object.clearance_mode.value)
        self.obj_clearance.set(f"{scene_object.clearance_mm:g}")
        transform = scene_object.transform
        for variable, value in zip(
            (self.obj_tx, self.obj_ty, self.obj_tz),
            transform.translation.to_list(),
            strict=True,
        ):
            variable.set(f"{value:g}")
        for variable, value in zip(
            (self.obj_rx, self.obj_ry, self.obj_rz),
            transform.rotation_deg.to_list(),
            strict=True,
        ):
            variable.set(f"{value:g}")
        if scene_object.primitive:
            self.obj_primitive_kind.set(scene_object.primitive.kind.value)
            for variable, value in zip(
                (self.obj_sx, self.obj_sy, self.obj_sz),
                scene_object.primitive.size.to_list(),
                strict=True,
            ):
                variable.set(f"{value:g}")
            self.obj_radius.set(f"{scene_object.primitive.radius:g}")
            self.primitive_kind_widget.configure(state="readonly")
        else:
            self.obj_primitive_kind.set("imported")
            self.obj_sx.set("-")
            self.obj_sy.set("-")
            self.obj_sz.set("-")
            self.obj_radius.set("-")
            self.primitive_kind_widget.configure(state=tk.DISABLED)

    def _load_envelope_controls(self) -> None:
        envelope = self.project.envelope
        self.env_kind.set(envelope.kind.value)
        for variable, value in zip(
            (self.env_sx, self.env_sy, self.env_sz), envelope.size.to_list(), strict=True
        ):
            variable.set(f"{value:g}")
        for variable, value in zip(
            (self.env_tx, self.env_ty, self.env_tz),
            envelope.transform.translation.to_list(),
            strict=True,
        ):
            variable.set(f"{value:g}")
        for variable, value in zip(
            (self.env_rx, self.env_ry, self.env_rz),
            envelope.transform.rotation_deg.to_list(),
            strict=True,
        ):
            variable.set(f"{value:g}")
        self.env_radius.set(f"{envelope.radius:g}")
        for variable, value in zip(
            (self.env_mx, self.env_my, self.env_mz),
            envelope.fit_margin.to_list(),
            strict=True,
        ):
            variable.set(f"{value:g}")

    def _load_slicing_controls(self) -> None:
        self.slicing_enabled.set(self.project.slicing.enabled)
        self.slice_remainder_name.set(self.project.slicing.remainder_name)
        self.slice_name.set("")
        self.slice_cutter_kind.set(SliceCutterKind.PLANE.value)
        self.slice_object_ref.set("")
        for var in (
            self.slice_x, self.slice_y, self.slice_z,
            self.slice_rx, self.slice_ry, self.slice_rz, self.slice_gap,
        ):
            var.set("0")
        self.refresh_slice_tree()

    def _sync_all_controls(self) -> None:
        self._load_envelope_controls()
        self._load_slicing_controls()

    # ------------------------------------------------------------------
    # View and reporting
    # ------------------------------------------------------------------
    def refresh_view(self, fit: bool = False) -> None:
        if not hasattr(self, "viewport"):
            return
        errors = self.viewport.refresh(
            self.project,
            self.repository,
            self.generated,
            self.show_envelope.get(),
        )
        if self.selected_id:
            self.viewport.select(self.selected_id)
        if fit:
            self.viewport.fit_camera()
        if errors:
            self.status.set(errors[0])

    def _fit_camera(self) -> None:
        self.viewport.fit_camera()

    def viewport_isometric(self) -> None:
        self.viewport.camera_isometric()

    def viewport_top(self) -> None:
        self.viewport.camera_top()

    def viewport_front(self) -> None:
        self.viewport.camera_front()

    def viewport_side(self) -> None:
        self.viewport.camera_side()

    def save_viewport_png(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save viewport image",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if filename:
            try:
                path = self.viewport.save_screenshot(filename)
            except Exception as exc:
                messagebox.showerror("Screenshot failed", str(exc), parent=self.root)
                return
            self.status.set(f"Saved {path.name}")

    def _clear_log(self) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)

    def _write_log(self, text: str, tag: str = "info") -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text, tag)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def show_workflow_help(self) -> None:
        messagebox.showinfo(
            "FlipFill workflow",
            "1. Import STEP/BREP/IGES hardware or create primitive proxies.\n\n"
            "2. Position each object numerically. Set hardware to Occupant, port access "
            "volumes to Cutout, bosses/ribs to Additive, and visual-only geometry to Reference.\n\n"
            "3. Fit or manually size the rounded envelope around the stack.\n\n"
            "4. Generate. FlipFill computes (envelope + additives) - cavities - cutouts, "
            "validates cavity intersections, and optionally slices the body into named pieces.\n\n"
            "5. Export the generated STEP and the fit-check STEP assembly. Inspect the assembly "
            "in Fusion 360 before printing.",
            parent=self.root,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "About FlipFill CAD",
            "FlipFill CAD 0.1.0\n\n"
            "A clearance-first inverse-fill enclosure generator built on CadQuery/OpenCascade "
            "with a Tk/VTK desktop interface.\n\n"
            "Project files are plain JSON. Generated solids export as STEP for final engineering "
            "in Fusion 360, FreeCAD, or another BRep CAD system.",
            parent=self.root,
        )

    def on_close(self) -> None:
        if self._confirm_discard():
            self.root.destroy()


def run_app(initial_project: str | None = None) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Could not start the GUI: {exc}", file=sys.stderr)
        return 1
    FlipFillApp(root, initial_project)
    root.mainloop()
    return 0
