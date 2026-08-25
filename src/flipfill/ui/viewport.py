from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import ImageTk

from flipfill.geometry.generator import GenerationResult
from flipfill.geometry.importers import GeometryRepository
from flipfill.model import Project
from flipfill.rendering import SceneRenderer


class CadViewport(tk.Frame):
    """VTK CAD viewport rendered into a normal Tk canvas.

    The common VTK wheels do not consistently ship the optional native
    ``libvtkRenderingTk`` bridge. This viewport instead wraps a
    :class:`flipfill.rendering.SceneRenderer`, which renders VTK off-screen,
    and converts each frame into a Pillow image for display in Tk. Scene
    building, tessellation, and camera framing all live in ``SceneRenderer``
    so the desktop viewport and the headless ``flipfill render`` CLI command
    draw identical scenes from the same code path. Camera interaction and
    picking remain fully local and require no web browser or platform-specific
    GUI extension.
    """

    def __init__(
        self,
        master: tk.Misc,
        on_select: Callable[[str | None], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_select = on_select
        self._photo: ImageTk.PhotoImage | None = None
        self._canvas_image: int | None = None
        self._render_pending = False
        self._drag_origin: tuple[int, int] | None = None
        self._drag_last: tuple[int, int] | None = None
        self._drag_distance = 0.0
        self._drag_mode = "orbit"

        self.canvas = tk.Canvas(
            self,
            background="#11151c",
            highlightthickness=0,
            cursor="fleur",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._left_press)
        self.canvas.bind("<B1-Motion>", self._left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._left_release)
        self.canvas.bind("<ButtonPress-2>", self._pan_press)
        self.canvas.bind("<B2-Motion>", self._pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._drag_release)
        self.canvas.bind("<ButtonPress-3>", self._pan_press)
        self.canvas.bind("<B3-Motion>", self._pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._drag_release)
        self.canvas.bind("<MouseWheel>", self._mouse_wheel)
        self.canvas.bind("<Button-4>", lambda event: self._zoom(1.12))
        self.canvas.bind("<Button-5>", lambda event: self._zoom(1 / 1.12))
        self.canvas.bind("<Double-Button-1>", lambda event: self.fit_camera())

        self.scene = SceneRenderer(width=900, height=700)

    # ------------------------------------------------------------------
    # Scene building
    # ------------------------------------------------------------------
    def clear_scene(self) -> None:
        self.scene.clear_scene()

    def refresh(
        self,
        project: Project,
        repository: GeometryRepository,
        generated: GenerationResult | None = None,
        show_envelope: bool = True,
    ) -> list[str]:
        errors = self.scene.refresh(project, repository, generated, show_envelope)
        self.request_render()
        return errors

    # ------------------------------------------------------------------
    # Rendering and image conversion
    # ------------------------------------------------------------------
    def request_render(self) -> None:
        if self._render_pending:
            return
        self._render_pending = True
        self.after_idle(self._render_to_canvas)

    def _render_to_canvas(self) -> None:
        self._render_pending = False
        width = max(32, self.canvas.winfo_width())
        height = max(32, self.canvas.winfo_height())
        image = self.scene.render_to_image(width, height)
        self._photo = ImageTk.PhotoImage(image=image)
        if self._canvas_image is None:
            self._canvas_image = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self._photo
            )
        else:
            self.canvas.itemconfigure(self._canvas_image, image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def _on_resize(self, _event=None) -> None:
        self.request_render()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def select(self, object_id: str | None) -> None:
        self.scene.select(object_id)
        self.request_render()

    # ------------------------------------------------------------------
    # Camera interaction
    # ------------------------------------------------------------------
    def _left_press(self, event: tk.Event) -> None:
        self._drag_origin = (event.x, event.y)
        self._drag_last = (event.x, event.y)
        self._drag_distance = 0.0
        self._drag_mode = "pan" if (event.state & 0x0001) else "orbit"

    def _left_drag(self, event: tk.Event) -> None:
        if self._drag_last is None:
            return
        dx = event.x - self._drag_last[0]
        dy = event.y - self._drag_last[1]
        self._drag_distance += math.hypot(dx, dy)
        self._drag_last = (event.x, event.y)
        if self._drag_mode == "pan":
            self._pan_pixels(dx, dy)
        else:
            camera = self.scene.renderer.GetActiveCamera()
            camera.Azimuth(-dx * 0.45)
            camera.Elevation(dy * 0.45)
            camera.OrthogonalizeViewUp()
            self.scene.renderer.ResetCameraClippingRange()
            self.request_render()

    def _left_release(self, event: tk.Event) -> None:
        if self._drag_origin is not None and self._drag_distance < 4.0:
            width = max(1, self.canvas.winfo_width())
            height = max(1, self.canvas.winfo_height())
            selected = self.scene.pick(event.x, event.y, width, height)
            self.select(selected)
            if self._on_select is not None:
                self._on_select(selected)
        self._drag_release(event)

    def _pan_press(self, event: tk.Event) -> None:
        self._drag_last = (event.x, event.y)
        self._drag_distance = 0.0
        self._drag_mode = "pan"

    def _pan_drag(self, event: tk.Event) -> None:
        if self._drag_last is None:
            return
        dx = event.x - self._drag_last[0]
        dy = event.y - self._drag_last[1]
        self._drag_last = (event.x, event.y)
        self._drag_distance += math.hypot(dx, dy)
        self._pan_pixels(dx, dy)

    def _pan_pixels(self, dx: float, dy: float) -> None:
        camera = self.scene.renderer.GetActiveCamera()
        position = np.asarray(camera.GetPosition(), dtype=float)
        focal = np.asarray(camera.GetFocalPoint(), dtype=float)
        view_up = np.asarray(camera.GetViewUp(), dtype=float)
        direction = focal - position
        distance = np.linalg.norm(direction)
        if distance <= 1.0e-9:
            return
        direction /= distance
        view_up /= max(np.linalg.norm(view_up), 1.0e-9)
        right = np.cross(direction, view_up)
        right /= max(np.linalg.norm(right), 1.0e-9)
        true_up = np.cross(right, direction)
        world_per_pixel = distance * 0.0018
        delta = (-dx * right + dy * true_up) * world_per_pixel
        camera.SetPosition(*(position + delta))
        camera.SetFocalPoint(*(focal + delta))
        self.scene.renderer.ResetCameraClippingRange()
        self.request_render()

    def _drag_release(self, _event=None) -> None:
        self._drag_origin = None
        self._drag_last = None
        self._drag_distance = 0.0

    def _mouse_wheel(self, event: tk.Event) -> None:
        self._zoom(1.12 if event.delta > 0 else 1 / 1.12)

    def _zoom(self, factor: float) -> None:
        camera = self.scene.renderer.GetActiveCamera()
        camera.Dolly(float(factor))
        self.scene.renderer.ResetCameraClippingRange()
        self.request_render()

    def fit_camera(self) -> None:
        self.scene.fit_camera()
        self.request_render()

    def camera_isometric(self) -> None:
        self.scene.camera_isometric()
        self.request_render()

    def camera_top(self) -> None:
        self.scene.camera_top()
        self.request_render()

    def camera_front(self) -> None:
        self.scene.camera_front()
        self.request_render()

    def camera_side(self) -> None:
        self.scene.camera_side()
        self.request_render()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def save_screenshot(self, path: str | Path) -> Path:
        width = max(320, self.canvas.winfo_width())
        height = max(240, self.canvas.winfo_height())
        output = self.scene.save_screenshot(path, width=width * 2, height=height * 2)
        self.scene.render_window.SetSize(width, height)
        self.request_render()
        return output
