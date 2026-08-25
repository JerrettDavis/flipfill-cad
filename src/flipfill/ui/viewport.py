from __future__ import annotations

import math
import tkinter as tk
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageTk

# Importing OpenGL2 registers the render-window factory used by VTK.
from vtkmodules import vtkRenderingOpenGL2  # noqa: F401
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkPropPicker,
    vtkRenderer,
    vtkRenderWindow,
    vtkWindowToImageFilter,
)
from vtkmodules.vtkIOImage import vtkPNGWriter

from flipfill.geometry.generator import GenerationResult
from flipfill.geometry.importers import GeometryRepository, ResolvedGeometry
from flipfill.geometry.tessellation import TriangleMesh, tessellate_shape
from flipfill.model import ObjectRole, Project


_ROLE_COLORS: dict[ObjectRole, tuple[float, float, float]] = {
    ObjectRole.OCCUPANT: (0.96, 0.55, 0.12),
    ObjectRole.CUTOUT: (0.92, 0.18, 0.16),
    ObjectRole.ADDITIVE: (0.16, 0.68, 0.34),
    ObjectRole.REFERENCE: (0.22, 0.48, 0.94),
    ObjectRole.RESULT: (0.76, 0.80, 0.86),
}


class CadViewport(tk.Frame):
    """VTK CAD viewport rendered into a normal Tk canvas.

    The common VTK wheels do not consistently ship the optional native
    ``libvtkRenderingTk`` bridge. This viewport instead renders VTK off-screen,
    converts the framebuffer into a Pillow image, and displays it in Tk. Camera
    interaction and picking remain fully local and require no web browser or
    platform-specific GUI extension.
    """

    def __init__(
        self,
        master: tk.Misc,
        on_select: Callable[[str | None], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_select = on_select
        self._actors: dict[str, vtkActor] = {}
        self._actor_ids: dict[str, str] = {}
        self._selected_id: str | None = None
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

        self.renderer = vtkRenderer()
        self.renderer.SetBackground(0.075, 0.085, 0.105)
        self.renderer.SetBackground2(0.16, 0.18, 0.22)
        self.renderer.GradientBackgroundOn()

        self.render_window = vtkRenderWindow()
        self.render_window.SetOffScreenRendering(1)
        self.render_window.SetMultiSamples(8)
        self.render_window.SetSize(900, 700)
        self.render_window.AddRenderer(self.renderer)

        self._add_ground_grid()
        self._add_world_axes()
        self.camera_isometric()

    @staticmethod
    def _actor_key(actor: vtkActor) -> str:
        return actor.GetAddressAsString("vtkActor")

    def _add_ground_grid(self) -> None:
        extent = 100.0
        step = 10.0
        vertices: list[list[float]] = []
        lines: list[list[int]] = []
        coordinate = -extent
        while coordinate <= extent + 1.0e-6:
            index = len(vertices)
            vertices.extend(
                [
                    [-extent, coordinate, 0.0],
                    [extent, coordinate, 0.0],
                    [coordinate, -extent, 0.0],
                    [coordinate, extent, 0.0],
                ]
            )
            lines.extend([[index, index + 1], [index + 2, index + 3]])
            coordinate += step

        points = np.asarray(vertices, dtype=float)
        line_array = np.asarray(lines, dtype=np.int64)
        poly = vtkPolyData()
        from vtkmodules.vtkCommonCore import vtkPoints

        vtk_points = vtkPoints()
        vtk_points.SetData(numpy_to_vtk(points, deep=True))
        poly.SetPoints(vtk_points)

        cells = vtkCellArray()
        packed = np.column_stack(
            [np.full(len(line_array), 2, dtype=np.int64), line_array]
        ).ravel()
        cells.SetCells(len(line_array), numpy_to_vtkIdTypeArray(packed, deep=True))
        poly.SetLines(cells)

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.33, 0.36, 0.42)
        actor.GetProperty().SetOpacity(0.32)
        actor.GetProperty().SetLineWidth(1.0)
        actor.PickableOff()
        actor.UseBoundsOff()
        self.renderer.AddActor(actor)

    def _add_world_axes(self) -> None:
        axes = vtkAxesActor()
        axes.SetTotalLength(18.0, 18.0, 18.0)
        axes.SetShaftTypeToCylinder()
        axes.SetCylinderRadius(0.015)
        axes.SetXAxisLabelText("")
        axes.SetYAxisLabelText("")
        axes.SetZAxisLabelText("")
        axes.PickableOff()
        axes.UseBoundsOff()
        self.renderer.AddActor(axes)

    # ------------------------------------------------------------------
    # Scene building
    # ------------------------------------------------------------------
    def clear_scene(self) -> None:
        for actor in self._actors.values():
            self.renderer.RemoveActor(actor)
        self._actors.clear()
        self._actor_ids.clear()
        self._selected_id = None

    def refresh(
        self,
        project: Project,
        repository: GeometryRepository,
        generated: GenerationResult | None = None,
        show_envelope: bool = True,
    ) -> list[str]:
        self.clear_scene()
        errors: list[str] = []

        if show_envelope:
            try:
                from flipfill.geometry.generator import envelope_shape

                self.add_brep(
                    "__envelope__",
                    envelope_shape(project),
                    (0.65, 0.69, 0.78),
                    opacity=0.16,
                    wireframe=True,
                    tolerance=project.tessellation_tolerance,
                )
            except Exception as exc:
                errors.append(f"Envelope preview failed: {exc}")

        for scene_object in project.objects:
            if not scene_object.visible:
                continue
            try:
                resolved = repository.resolve(scene_object)
                color = scene_object.color or _ROLE_COLORS[scene_object.role]
                opacity = {
                    ObjectRole.OCCUPANT: 0.56,
                    ObjectRole.CUTOUT: 0.35,
                    ObjectRole.ADDITIVE: 0.62,
                    ObjectRole.REFERENCE: 0.40,
                    ObjectRole.RESULT: 0.85,
                }[scene_object.role]
                self.add_resolved(
                    scene_object.id,
                    resolved,
                    color,
                    opacity,
                    project.tessellation_tolerance,
                )
            except Exception as exc:
                errors.append(f"{scene_object.name}: {exc}")

        if generated is not None:
            try:
                self.add_brep(
                    "__result__",
                    generated.result,
                    _ROLE_COLORS[ObjectRole.RESULT],
                    opacity=0.84,
                    wireframe=False,
                    tolerance=project.tessellation_tolerance,
                )
            except Exception as exc:
                errors.append(f"Generated result preview failed: {exc}")

        self.request_render()
        return errors

    def add_resolved(
        self,
        object_id: str,
        resolved: ResolvedGeometry,
        color: tuple[float, float, float],
        opacity: float,
        tolerance: float,
    ) -> None:
        if resolved.brep is not None:
            self.add_brep(
                object_id,
                resolved.brep,
                color,
                opacity,
                tolerance=tolerance,
            )
            return
        assert resolved.mesh_vertices is not None
        assert resolved.mesh_faces is not None
        self.add_triangle_mesh(
            object_id,
            TriangleMesh(resolved.mesh_vertices, resolved.mesh_faces),
            color,
            opacity,
        )

    def add_brep(
        self,
        object_id: str,
        shape,
        color: tuple[float, float, float],
        opacity: float,
        wireframe: bool = False,
        tolerance: float = 0.15,
    ) -> None:
        mesh = tessellate_shape(shape, tolerance, 0.1)
        self.add_triangle_mesh(object_id, mesh, color, opacity, wireframe)

    def add_triangle_mesh(
        self,
        object_id: str,
        mesh: TriangleMesh,
        color: tuple[float, float, float],
        opacity: float,
        wireframe: bool = False,
    ) -> None:
        poly = self._polydata(mesh)
        normals = vtkPolyDataNormals()
        normals.SetInputData(poly)
        normals.SetFeatureAngle(45.0)
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.SplittingOn()

        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(float(opacity))
        actor.GetProperty().SetInterpolationToPhong()
        actor.GetProperty().SetAmbient(0.20)
        actor.GetProperty().SetDiffuse(0.75)
        actor.GetProperty().SetSpecular(0.18)
        actor.GetProperty().SetSpecularPower(24.0)
        if wireframe:
            actor.GetProperty().SetRepresentationToWireframe()
            actor.GetProperty().SetLineWidth(1.5)

        self.renderer.AddActor(actor)
        self._actors[object_id] = actor
        self._actor_ids[self._actor_key(actor)] = object_id

    @staticmethod
    def _polydata(mesh: TriangleMesh) -> vtkPolyData:
        from vtkmodules.vtkCommonCore import vtkPoints

        points = vtkPoints()
        points.SetData(numpy_to_vtk(np.asarray(mesh.vertices, dtype=float), deep=True))
        cells = vtkCellArray()
        faces = np.asarray(mesh.faces, dtype=np.int64)
        packed = np.column_stack(
            [np.full(len(faces), 3, dtype=np.int64), faces]
        ).ravel()
        cells.SetCells(len(faces), numpy_to_vtkIdTypeArray(packed, deep=True))
        poly = vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(cells)
        return poly

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
        self.render_window.SetSize(width, height)
        self.render_window.Render()

        capture = vtkWindowToImageFilter()
        capture.SetInput(self.render_window)
        capture.ReadFrontBufferOff()
        capture.SetInputBufferTypeToRGB()
        capture.Update()
        image_data = capture.GetOutput()
        dimensions = image_data.GetDimensions()
        scalars = image_data.GetPointData().GetScalars()
        array = vtk_to_numpy(scalars).reshape(dimensions[1], dimensions[0], -1)
        array = np.flipud(array)
        image = Image.fromarray(array[:, :, :3].astype(np.uint8), mode="RGB")
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
    def _pick(self, x: int, y: int) -> str | None:
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self.render_window.SetSize(width, height)
        self.render_window.Render()
        picker = vtkPropPicker()
        picker.Pick(float(x), float(height - y - 1), 0.0, self.renderer)
        actor = picker.GetActor()
        if actor is None:
            return None
        return self._actor_ids.get(self._actor_key(actor))

    def select(self, object_id: str | None) -> None:
        if self._selected_id in self._actors:
            previous = self._actors[self._selected_id]
            previous.GetProperty().EdgeVisibilityOff()
            previous.GetProperty().SetLineWidth(1.0)
        self._selected_id = object_id
        if object_id in self._actors:
            actor = self._actors[object_id]
            actor.GetProperty().EdgeVisibilityOn()
            actor.GetProperty().SetEdgeColor(1.0, 0.86, 0.20)
            actor.GetProperty().SetLineWidth(2.5)
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
            camera = self.renderer.GetActiveCamera()
            camera.Azimuth(-dx * 0.45)
            camera.Elevation(dy * 0.45)
            camera.OrthogonalizeViewUp()
            self.renderer.ResetCameraClippingRange()
            self.request_render()

    def _left_release(self, event: tk.Event) -> None:
        if self._drag_origin is not None and self._drag_distance < 4.0:
            selected = self._pick(event.x, event.y)
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
        camera = self.renderer.GetActiveCamera()
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
        self.renderer.ResetCameraClippingRange()
        self.request_render()

    def _drag_release(self, _event=None) -> None:
        self._drag_origin = None
        self._drag_last = None
        self._drag_distance = 0.0

    def _mouse_wheel(self, event: tk.Event) -> None:
        self._zoom(1.12 if event.delta > 0 else 1 / 1.12)

    def _zoom(self, factor: float) -> None:
        camera = self.renderer.GetActiveCamera()
        camera.Dolly(float(factor))
        self.renderer.ResetCameraClippingRange()
        self.request_render()

    def fit_camera(self) -> None:
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()
        self.request_render()

    def camera_isometric(self) -> None:
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(140.0, -160.0, 120.0)
        camera.SetFocalPoint(0.0, 0.0, 0.0)
        camera.SetViewUp(0.0, 0.0, 1.0)
        self.fit_camera()

    def camera_top(self) -> None:
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(0.0, 0.0, 250.0)
        camera.SetFocalPoint(0.0, 0.0, 0.0)
        camera.SetViewUp(0.0, 1.0, 0.0)
        self.fit_camera()

    def camera_front(self) -> None:
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(0.0, -250.0, 0.0)
        camera.SetFocalPoint(0.0, 0.0, 0.0)
        camera.SetViewUp(0.0, 0.0, 1.0)
        self.fit_camera()

    def camera_side(self) -> None:
        camera = self.renderer.GetActiveCamera()
        camera.SetPosition(250.0, 0.0, 0.0)
        camera.SetFocalPoint(0.0, 0.0, 0.0)
        camera.SetViewUp(0.0, 0.0, 1.0)
        self.fit_camera()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def save_screenshot(self, path: str | Path) -> Path:
        output = Path(path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        width = max(320, self.canvas.winfo_width())
        height = max(240, self.canvas.winfo_height())
        self.render_window.SetSize(width * 2, height * 2)
        self.render_window.Render()
        capture = vtkWindowToImageFilter()
        capture.SetInput(self.render_window)
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtkPNGWriter()
        writer.SetFileName(str(output))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        self.render_window.SetSize(width, height)
        self.request_render()
        return output
