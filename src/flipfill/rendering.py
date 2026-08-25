"""Shared off-screen VTK scene builder used by the desktop viewport and the
headless CLI ``render`` command.

Both entry points must draw an identical scene from the same ``Project`` and
``GenerationResult`` types without re-implementing tessellation, transform, or
color logic. This module owns the VTK actor bookkeeping; it has no
dependency on Tk, so it can run inside plain Python processes (CI, scripts,
agents) as well as inside the desktop shell.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# Importing OpenGL2 registers the render-window factory used by VTK.
from vtkmodules import vtkRenderingOpenGL2  # noqa: F401
from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
from vtkmodules.vtkFiltersCore import vtkPolyDataNormals
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkPropPicker,
    vtkRenderer,
    vtkRenderWindow,
    vtkWindowToImageFilter,
)

from flipfill.geometry.generator import GenerationResult, envelope_shape
from flipfill.geometry.importers import GeometryRepository, ResolvedGeometry
from flipfill.geometry.tessellation import TriangleMesh, tessellate_shape
from flipfill.model import ObjectRole, Project

ROLE_COLORS: dict[ObjectRole, tuple[float, float, float]] = {
    ObjectRole.OCCUPANT: (0.96, 0.55, 0.12),
    ObjectRole.CUTOUT: (0.92, 0.18, 0.16),
    ObjectRole.ADDITIVE: (0.16, 0.68, 0.34),
    ObjectRole.REFERENCE: (0.22, 0.48, 0.94),
    ObjectRole.RESULT: (0.76, 0.80, 0.86),
}

ROLE_OPACITY: dict[ObjectRole, float] = {
    ObjectRole.OCCUPANT: 0.56,
    ObjectRole.CUTOUT: 0.35,
    ObjectRole.ADDITIVE: 0.62,
    ObjectRole.REFERENCE: 0.40,
    ObjectRole.RESULT: 0.85,
}

ENVELOPE_ID = "__envelope__"
RESULT_ID = "__result__"

CameraView = str  # "iso" | "top" | "front" | "side"


class SceneRenderer:
    """Builds and rasterizes a FlipFill scene with an off-screen VTK pipeline.

    This is the single place that turns a ``Project``/``GenerationResult``
    pair into VTK actors. ``flipfill.ui.viewport.CadViewport`` wraps an
    instance of this class for interactive display; ``flipfill render``
    drives it directly with no Tk dependency.
    """

    def __init__(self, width: int = 1280, height: int = 800) -> None:
        self._actors: dict[str, vtkActor] = {}
        self._actor_ids: dict[str, str] = {}
        self._selected_id: str | None = None

        self.renderer = vtkRenderer()
        self.renderer.SetBackground(0.075, 0.085, 0.105)
        self.renderer.SetBackground2(0.16, 0.18, 0.22)
        self.renderer.GradientBackgroundOn()

        self.render_window = vtkRenderWindow()
        self.render_window.SetOffScreenRendering(1)
        self.render_window.SetMultiSamples(8)
        self.render_window.SetSize(max(32, width), max(32, height))
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
                self.add_brep(
                    ENVELOPE_ID,
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
                color = scene_object.color or ROLE_COLORS[scene_object.role]
                opacity = ROLE_OPACITY[scene_object.role]
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
                    RESULT_ID,
                    generated.result,
                    ROLE_COLORS[ObjectRole.RESULT],
                    opacity=0.84,
                    wireframe=False,
                    tolerance=project.tessellation_tolerance,
                )
            except Exception as exc:
                errors.append(f"Generated result preview failed: {exc}")

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
            self.add_brep(object_id, resolved.brep, color, opacity, tolerance=tolerance)
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
    # Selection and picking
    # ------------------------------------------------------------------
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

    def pick(self, x: int, y: int, width: int, height: int) -> str | None:
        self.render_window.SetSize(max(1, width), max(1, height))
        self.render_window.Render()
        picker = vtkPropPicker()
        picker.Pick(float(x), float(height - y - 1), 0.0, self.renderer)
        actor = picker.GetActor()
        if actor is None:
            return None
        return self._actor_ids.get(self._actor_key(actor))

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------
    def fit_camera(self) -> None:
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()

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

    def set_camera_view(self, view: CameraView) -> None:
        {
            "iso": self.camera_isometric,
            "top": self.camera_top,
            "front": self.camera_front,
            "side": self.camera_side,
        }[view]()

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def render_to_image(self, width: int | None = None, height: int | None = None) -> Image.Image:
        if width and height:
            self.render_window.SetSize(max(32, width), max(32, height))
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
        return Image.fromarray(array[:, :, :3].astype(np.uint8), mode="RGB")

    def save_screenshot(
        self, path: str | Path, width: int | None = None, height: int | None = None
    ) -> Path:
        output = Path(path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if width and height:
            self.render_window.SetSize(max(32, width), max(32, height))
        self.render_window.Render()
        capture = vtkWindowToImageFilter()
        capture.SetInput(self.render_window)
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtkPNGWriter()
        writer.SetFileName(str(output))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
        return output


def render_project_to_file(
    project: Project,
    repository: GeometryRepository,
    output: str | Path,
    generated: GenerationResult | None = None,
    view: CameraView = "iso",
    show_envelope: bool = True,
    width: int = 1600,
    height: int = 1000,
) -> tuple[Path, list[str]]:
    """Render a project to a PNG without any Tk/desktop dependency."""

    scene = SceneRenderer(width=width, height=height)
    errors = scene.refresh(project, repository, generated, show_envelope)
    scene.set_camera_view(view)
    scene.fit_camera()
    path = scene.save_screenshot(output, width=width, height=height)
    return path, errors
