from __future__ import annotations

import tkinter as tk
from collections.abc import Callable


class Tooltip:
    """A small delayed hover label for icon-only buttons and other compact controls.

    ``palette_source`` is called lazily on each show so the tooltip picks up
    the live theme dict rather than a snapshot taken at construction time.
    """

    def __init__(self, widget: tk.Widget, text: str, palette_source: Callable[[], dict]) -> None:
        self.widget = widget
        self.text = text
        self.palette_source = palette_source
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text

    def _schedule(self, _event: object = None) -> None:
        self._after_id = self.widget.after(450, self._show)

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        p = self.palette_source()
        label = tk.Label(
            tip,
            text=self.text,
            background=p["panel_3"],
            foreground=p["text"],
            font=("Segoe UI", 8),
            padx=8,
            pady=4,
            highlightthickness=1,
            highlightbackground=p["border"],
        )
        label.pack()
        tip.update_idletasks()
        tip.wm_geometry(f"+{x - tip.winfo_width() // 2}+{y}")
        self._tip = tip

    def _hide(self, _event: object = None) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
