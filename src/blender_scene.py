"""Blender 3D renderer for one structured scene specification.

Usage:
    blender -b -t 2 --python src/blender_scene.py -- <scene.json> <out.mp4> <index> <total> <seconds>

The renderer is a parameterised template engine, not a keyword matcher: the
scene spec is validated by scene_spec.py (shared with the pipeline), and the
subject builder and action program are chosen by *typed* dispatch. Every scene
therefore renders a recognisable subject with real keyframed object motion.

Before rendering, the animated result is measured from Blender's evaluated
scene state (world transforms, projected screen positions, scales, rotations)
and written to `<out>.visual.json`. The QA layer compares those measurements to
the action's declared requirement, so "the subject actually moved" is verified
from the animation data instead of being asserted in metadata.
"""

import json
import math
import os
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_spec  # noqa: E402  (Blender entry point; import after sys.path setup)

RENDER_W, RENDER_H, RENDER_FPS = 540, 960, 24
SAMPLES = 10

# --- palette ---------------------------------------------------------------
PALETTE = {
    "cyan": (0.035, 0.46, 0.86),
    "gold": (0.86, 0.56, 0.16),
    "steel": (0.34, 0.42, 0.52),
    "navy": (0.028, 0.062, 0.135),
    "copper": (0.72, 0.34, 0.13),
    "ivory": (0.90, 0.93, 0.97),
    "red": (0.74, 0.10, 0.10),
}
ENV_TINTS = {
    "studio_plinth": (0.012, 0.020, 0.040),
    "workbench": (0.026, 0.020, 0.016),
    "chip_cavity": (0.008, 0.026, 0.030),
    "open_terrain": (0.020, 0.024, 0.016),
    "shelf_wall": (0.018, 0.014, 0.026),
    "phone_bench": (0.010, 0.016, 0.030),
    "clamp_rig": (0.020, 0.018, 0.024),
    "grid_floor": (0.010, 0.014, 0.026),
}
LIGHTING = {
    "cool": ((0.38, 0.66, 1.0), (0.18, 0.40, 1.0), (0.55, 0.72, 1.0)),
    "warm": ((1.0, 0.72, 0.42), (1.0, 0.44, 0.16), (1.0, 0.80, 0.60)),
    "clinical": ((0.86, 0.93, 1.0), (0.70, 0.86, 1.0), (1.0, 1.0, 1.0)),
    "dramatic": ((0.90, 0.85, 0.78), (0.95, 0.30, 0.10), (0.30, 0.45, 0.85)),
}

args = sys.argv[sys.argv.index("--") + 1:]
brief_path, output_path, scene_index, scene_total, duration_arg = args
scene = bpy.context.scene
index = int(scene_index)
shot_seconds = max(float(duration_arg), 2.0)
spec = json.loads(Path(brief_path).read_text(encoding="utf-8"))
frame_start = 1
frame_end = max(24, int(round(shot_seconds * RENDER_FPS)))


def configure_scene():
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except (TypeError, AttributeError):
        scene.render.engine = "BLENDER_EEVEE"
    # CI has no GPU: keep the per-frame cost bounded but still cinematic.
    for attr, value in (
        ("taa_render_samples", SAMPLES),
        ("use_gtao", True),
        ("use_ssr", False),          # screen-space reflections are very costly on llvmpipe
        ("use_raytracing", False),   # EEVEE Next equivalent
        ("use_bloom", True),
    ):
        try:
            setattr(scene.eevee, attr, value)
        except (AttributeError, TypeError):
            pass
    try:
        scene.render.use_persistent_data = True
    except (AttributeError, TypeError):
        pass
    for transform in ("AgX", "Filmic", "Standard"):
        try:
            scene.view_settings.view_transform = transform
            break
        except (TypeError, AttributeError):
            continue
    scene.render.resolution_x = RENDER_W
    scene.render.resolution_y = RENDER_H
    scene.render.resolution_percentage = 100
    scene.render.fps = RENDER_FPS
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.ffmpeg.gopsize = 12
    scene.render.film_transparent = False
    scene.render.filepath = str(Path(output_path).resolve().with_suffix(""))


# --- material + primitive helpers -------------------------------------------
def material(name, color, metallic=0.1, roughness=0.4, emission=0.0,
             alpha=1.0, transmission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, alpha)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    for key in ("Emission Color", "Emission"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = (*color, 1.0)
            break
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = emission
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = transmission
            break
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0 or transmission > 0.0:
        for attr, value in (("blend_method", "BLEND"), ("show_transparent_back", False)):
            try:
                setattr(mat, attr, value)
            except (AttributeError, TypeError):
                pass
    return mat


class Studio:
    """Builds named objects and remembers them for measurement."""

    def __init__(self):
        self.groups = {}
        self.objects = []
        self.world = bpy.context.scene.world
        if self.world is None:
            self.world = bpy.data.worlds.new("Digital Edge World")
            bpy.context.scene.world = self.world
        try:
            self.world.use_nodes = True
            bg = self.world.node_tree.nodes.get("Background")
            if bg:
                bg.inputs[0].default_value = (0.004, 0.007, 0.016, 1.0)
                bg.inputs[1].default_value = 1.0
        except (AttributeError, TypeError, IndexError):
            self.world.color = (0.004, 0.007, 0.016)

    # primitives -----------------------------------------------------------
    def _finish(self, obj, name, mat, bevel=0.0):
        obj.name = name
        if mat is not None:
            obj.data.materials.append(mat)
        if bevel > 0 and obj.type == "MESH":
            mod = obj.modifiers.new("Soft edges", "BEVEL")
            mod.width, mod.segments = bevel, 2
        self.objects.append(obj)
        return obj

    def box(self, name, loc, dims, mat, bevel=0.03, rot=(0, 0, 0)):
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
        obj = bpy.context.object
        obj.scale = (dims[0], dims[1], dims[2])
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.rotation_euler = rot
        return self._finish(obj, name, mat, bevel)

    def sphere(self, name, loc, radius, mat, segments=32):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=max(8, segments // 2),
                                             radius=radius, location=loc)
        obj = bpy.context.object
        bpy.ops.object.shade_smooth()
        return self._finish(obj, name, mat, 0.0)

    def cyl(self, name, loc, radius, depth, mat, vertices=32, rot=(0, 0, 0)):
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                            location=loc, rotation=rot)
        obj = bpy.context.object
        bpy.ops.object.shade_smooth()
        return self._finish(obj, name, mat, 0.0)

    def cone(self, name, loc, r1, r2, depth, mat, vertices=32, rot=(0, 0, 0)):
        bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=r1, radius2=r2,
                                        depth=depth, location=loc, rotation=rot)
        obj = bpy.context.object
        bpy.ops.object.shade_smooth()
        return self._finish(obj, name, mat, 0.0)

    def torus(self, name, loc, major, minor, mat, rot=(0, 0, 0)):
        bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor,
                                         major_segments=48, minor_segments=10,
                                         location=loc, rotation=rot)
        obj = bpy.context.object
        bpy.ops.object.shade_smooth()
        return self._finish(obj, name, mat, 0.0)

    def plane(self, name, loc, size, mat, rot=(0, 0, 0)):
        bpy.ops.mesh.primitive_plane_add(size=size, location=loc, rotation=rot)
        return self._finish(bpy.context.object, name, mat, 0.0)

    def label(self, name, body, loc, size, mat, rot=(math.radians(90), 0, 0)):
        bpy.ops.object.text_add(location=loc, rotation=rot)
        obj = bpy.context.object
        obj.data.body = str(body)[:34].upper()
        obj.data.size = size
        obj.data.extrude = 0.006
        obj.data.align_x = "CENTER"
        obj.data.align_y = "CENTER"
        return self._finish(obj, name, mat, 0.0)

    def group(self, part_name, objs):
        self.groups.setdefault(part_name, []).extend(objs)


def base_materials(subject):
    color = PALETTE[subject["color"]]
    return {
        "main": material(f"Primary {subject['material']}", color,
                         metallic={"metal": 0.85, "glass": 0.2, "stone": 0.05}.get(subject["material"], 0.35),
                         roughness={"glass": 0.1, "metal": 0.25, "voxel": 0.45}.get(subject["material"], 0.38),
                         emission=0.35 if subject["material"] == "emissive" else 0.0,
                         alpha=0.55 if subject["material"] == "glass" else 1.0,
                         transmission=0.65 if subject["material"] == "glass" else 0.0),
        "accent": material("Electric accent", PALETTE["cyan"], 0.3, 0.2, 2.4),
        "warm": material("Warm metal", PALETTE["gold"], 0.8, 0.3),
        "steel": material("Machined steel", PALETTE["steel"], 0.75, 0.28),
        "dark": material("Deep ceramic", PALETTE["navy"], 0.25, 0.45),
        "ivory": material("Ivory legend", PALETTE["ivory"], 0.0, 0.6, 0.25),
        "alert": material("Warning red", PALETTE["red"], 0.2, 0.3, 1.6),
    }


# --- environment ------------------------------------------------------------
def build_environment(studio, scene_env, mats):
    kind = scene_env["kind"]
    floor_mat = material(f"Stage {kind}", ENV_TINTS.get(kind, (0.012, 0.02, 0.04)),
                         0.2, 0.5)
    studio.box("stage_floor", (0, 0, -0.26), (22, 22, 0.5), floor_mat, 0.02)
    studio.box("stage_backdrop", (0, 4.2, 2.2), (22, 0.4, 9.0), floor_mat, 0.02)

    if kind == "grid_floor":
        for i in range(-4, 5):
            studio.box(f"env_grid_x{i + 4}", (i * 0.9, 0.6, -0.005), (0.02, 7.0, 0.02), mats["accent"], 0)
            studio.box(f"env_grid_y{i + 4}", (0, i * 0.9 + 0.6, -0.005), (7.0, 0.02, 0.02), mats["accent"], 0)
    elif kind == "workbench":
        studio.box("env_bench", (0, 0.6, 0.02), (6.0, 2.4, 0.3), mats["warm"], 0.04)
        for j in range(3):
            studio.box(f"env_tool{j}", (-2.0 + j * 2.0, 1.2, 0.28), (0.5, 0.3, 0.16), mats["steel"], 0.02)
    elif kind == "chip_cavity":
        studio.box("env_die_frame", (0, 0.5, 0.02), (6.2, 3.4, 0.28), mats["dark"], 0.03)
        for i in range(6):
            studio.box(f"env_trace_v{i}", (-2.4 + i * 0.96, 0.2, 0.18), (0.03, 3.0, 0.02),
                       mats["accent"] if i % 2 else mats["warm"], 0)
    elif kind == "open_terrain":
        for j in range(9):
            row, col = divmod(j, 3)
            studio.cone(f"env_ridge{j}", ((col - 1) * 1.9, 1.6 + row * 0.5, 0.1),
                        0.5 + 0.18 * (j % 3), 0.02, 1.4 + 0.5 * (j % 2), mats["dark"], 10)
    elif kind == "shelf_wall":
        for row in range(3):
            studio.box(f"env_shelf{row}", (0, 1.9, 0.6 + row * 0.95), (5.6, 0.5, 0.1), mats["warm"], 0.02)
            for col in range(5):
                studio.box(f"env_volume{row}{col}", (-2.1 + col * 1.05, 1.85, 0.78 + row * 0.95),
                           (0.5, 0.42, 0.34), mats["steel"] if (row + col) % 2 else mats["dark"], 0.02)
    elif kind == "phone_bench":
        studio.box("env_desk", (0, 0.8, -0.02), (7.0, 4.0, 0.2), mats["dark"], 0.03)
        studio.box("env_desk_inlay", (0, 0.8, 0.09), (3.4, 2.2, 0.02), mats["steel"], 0.01)
    elif kind == "clamp_rig":
        studio.box("env_rail", (0, 0.9, 0.05), (7.4, 0.28, 0.14), mats["steel"], 0.02)
        for side in (-1, 1):
            studio.cyl(f"env_post{side}", (side * 2.5, 1.5, 1.1), 0.12, 2.2, mats["steel"])
    else:  # studio_plinth
        studio.cyl("env_plinth", (0, 0.2, 0.02), 2.1, 0.24, mats["dark"], vertices=48)
        studio.torus("env_plinth_ring", (0, 0.2, 0.16), 2.05, 0.02, mats["accent"])


# --- subject builders -------------------------------------------------------
# Each builder returns (hero, mover, parts) where `hero` is the recognisable
# principal subject, `mover` is the object that carries the story motion, and
# `parts` maps the registry's part names to the objects that were created.
def build_glass_sphere(studio, subject, mats):
    hero = studio.sphere("sphere_core", (0, 0, 1.62), 0.92, mats["main"])
    rim = studio.torus("sphere_rim", (0, 0, 1.62), 0.94, 0.035, mats["accent"],
                       rot=(math.radians(72), 0, 0))
    for j in range(14):
        a = j * math.tau / 14
        studio.sphere(f"sphere_node{j}", (0.66 * math.cos(a), -0.42, 1.62 + 0.66 * math.sin(a)),
                      0.045, mats["accent"])
    return hero, hero, {"sphere_core": [hero], "sphere_rim": [rim]}


def build_metal_sphere(studio, subject, mats):
    hero = studio.sphere("sphere_core", (0, 0, 1.62), 0.9, mats["warm"])
    rim = studio.torus("sphere_rim", (0, 0, 1.62), 1.0, 0.03, mats["steel"],
                       rot=(math.radians(90), 0, 0))
    return hero, hero, {"sphere_core": [hero], "sphere_rim": [rim]}


def build_voxel_sphere(studio, subject, mats):
    cells = []
    layers = [(0, 2), (1, 4), (2, 4), (1, 4), (0, 2)]
    for row, (half, count) in enumerate(layers):
        for col in range(count):
            x = (col - (count - 1) / 2) * 0.46
            z = 0.85 + row * 0.44
            cells.append(studio.box(f"voxel_cell_{row}_{col}", (x, 0, z),
                                    (0.42, 0.42, 0.40), mats["main"], 0.02))
    frame = studio.torus("voxel_frame", (0, 0, 1.72), 1.30, 0.02, mats["accent"],
                         rot=(math.radians(90), 0, 0))
    return cells[len(cells) // 2], cells[len(cells) // 2], {
        "voxel_cell": cells, "voxel_frame": [frame], "_movers": cells}


def build_dial(studio, subject, mats):
    body = studio.cyl("dial_body", (0, 0, 1.55), 1.15, 0.34, mats["dark"],
                      rot=(math.radians(90), 0, 0))
    needle = studio.box("dial_needle", (0, -0.22, 1.55), (0.08, 0.05, 0.92), mats["accent"],
                        bevel=0.01)
    ticks = []
    for j in range(24):
        a = j * math.tau / 24
        ticks.append(studio.box(f"dial_ticks_{j}",
                                (0.94 * math.cos(a), -0.20, 1.55 + 0.94 * math.sin(a)),
                                (0.05, 0.04, 0.16 if j % 3 == 0 else 0.09),
                                mats["ivory"] if j % 3 == 0 else mats["steel"], 0.005,
                                rot=(0, -a, 0)))
    studio.box("dial_sweep_marker", (0, -0.30, 2.62), (0.5, 0.05, 0.05), mats["warm"], 0.005)
    return body, needle, {"dial_body": [body], "dial_needle": [needle], "dial_ticks": ticks}


def build_clamp(studio, subject, mats):
    upper = studio.box("clamp_jaw_upper", (0, 0, 2.42), (2.1, 1.1, 0.42), mats["steel"], 0.05)
    lower = studio.box("clamp_jaw_lower", (0, 0, 0.62), (2.1, 1.1, 0.42), mats["steel"], 0.05)
    screw = studio.cyl("clamp_screw", (0, 0.9, 1.52), 0.16, 2.0, mats["warm"],
                       rot=(math.radians(90), 0, 0))
    studio.torus("clamp_wheel", (0, 1.85, 1.52), 0.42, 0.06, mats["warm"],
                 rot=(math.radians(90), 0, 0))
    for side in (-1, 1):
        studio.box(f"clamp_post{side}", (side * 1.15, 0.4, 1.52), (0.18, 0.7, 2.4),
                   mats["steel"], 0.03)
    return screw, upper, {"clamp_jaw_upper": [upper], "clamp_jaw_lower": [lower],
                          "clamp_screw": [screw]}


def build_smartphone(studio, subject, mats):
    chassis = studio.box("phone_chassis", (0, 0, 1.5), (1.5, 0.22, 2.85), mats["steel"], 0.09)
    screen = studio.box("phone_screen", (0, -0.12, 1.5), (1.32, 0.02, 2.6), mats["dark"], 0.05)
    notch = studio.box("phone_notch", (0, -0.14, 2.66), (0.42, 0.03, 0.10), mats["steel"], 0.02)
    studio.box("phone_ui_bar", (0, -0.15, 2.30), (1.0, 0.01, 0.12), mats["accent"], 0.005)
    return chassis, chassis, {"phone_chassis": [chassis], "phone_screen": [screen],
                              "phone_notch": [notch]}


def build_mountain_pair(studio, subject, mats):
    smooth = studio.cone("mountain_smooth", (-0.95, 0, 1.0), 1.05, 0.03, 1.9,
                         mats["main"], vertices=48)
    voxels = []
    for row in range(5):
        count = 5 - row
        for col in range(count):
            x = 0.95 + (col - (count - 1) / 2) * 0.46
            voxels.append(studio.box(f"mountain_voxel_{row}_{col}",
                                     (x, 0, 0.45 + row * 0.38),
                                     (0.44, 0.44, 0.36), mats["warm"], 0.015))
    studio.box("mountain_base", (0, 0, 0.14), (4.4, 1.5, 0.2), mats["dark"], 0.03)
    return smooth, voxels[0], {"mountain_smooth": [smooth], "mountain_voxel": voxels}


def build_pipe_bundle(studio, subject, mats):
    pipes = []
    for j in range(4):
        pipes.append(studio.cyl(f"pipe_{j + 1}", (-0.78 + j * 0.52, 0, 1.42), 0.19, 2.6,
                                mats["warm"], rot=(math.radians(90), 0, 0)))
    merged = studio.cyl("pipe_merged", (0, -1.5, 1.42), 0.42, 1.5, mats["accent"],
                        rot=(math.radians(90), 0, 0))
    studio.torus("pipe_collar", (0, -0.55, 1.42), 0.9, 0.07, mats["steel"],
                 rot=(math.radians(90), 0, 0))
    return pipes[0], merged, {"pipe_1": [pipes[0]], "pipe_2": [pipes[1]],
                              "pipe_3": [pipes[2]], "pipe_4": [pipes[3]],
                              "pipe_merged": [merged], "_all_pipes": pipes}


def build_chip_die(studio, subject, mats):
    substrate = studio.box("chip_substrate", (0, 0, 0.4), (3.4, 2.2, 0.34), mats["dark"], 0.03)
    cores = []
    for j, (x, z) in enumerate(((-0.95, 0.95), (0.95, 0.95), (0, 1.6))):
        cores.append(studio.box(f"chip_core_{'abc'[j]}", (x, 0, z), (0.9, 0.9, 0.55),
                                mats["main"] if j == 0 else mats["steel"], 0.03))
    for j in range(7):
        studio.box(f"chip_trace{j}", (-1.4 + j * 0.46, -0.4, 0.6), (0.05, 1.4, 0.03), mats["accent"], 0)
    return cores[0], cores[0], {"chip_substrate": [substrate], "chip_core_a": [cores[0]],
                                "chip_core_b": [cores[1]], "chip_core_c": [cores[2]]}


def build_weight_grid(studio, subject, mats):
    cells = []
    for row in range(3):
        for col in range(4):
            cells.append(studio.box(f"weight_cell_{row}{col}",
                                    (-1.35 + col * 0.9, 0, 0.75 + row * 0.85),
                                    (0.78, 0.5, 0.72),
                                    mats["main"] if (row + col) % 3 else mats["steel"], 0.02))
    studio.box("weight_backplate", (0, 0.42, 1.6), (4.4, 0.14, 3.0), mats["dark"], 0.02)
    return cells[0], cells[0], {
        "weight_cell_a": [cells[0]], "weight_cell_b": [cells[1]],
        "weight_cell_c": [cells[4]], "weight_cell_d": [cells[5]], "_movers": cells}


def build_block_pair(studio, subject, mats):
    a = studio.box("block_a", (-1.25, 0, 1.5), (1.0, 0.8, 0.9), mats["warm"], 0.05)
    b = studio.box("block_b", (1.25, 0, 1.5), (1.0, 0.8, 0.9), mats["main"], 0.05)
    link = studio.box("block_link", (0, -0.1, 1.5), (1.6, 0.14, 0.14), mats["accent"], 0.01)
    studio.label("block_label_a", "A", (-1.25, -0.45, 1.5), 0.42, mats["ivory"])
    studio.label("block_label_b", "B", (1.25, -0.45, 1.5), 0.42, mats["ivory"])
    return b, b, {"block_a": [a], "block_b": [b], "block_link": [link]}


def build_glass_slab(studio, subject, mats):
    left = studio.box("slab_left", (-0.9, 0, 1.6), (0.9, 0.18, 2.2), mats["main"], 0.02)
    right = studio.box("slab_right", (0.9, 0, 1.6), (0.9, 0.18, 2.2), mats["steel"], 0.02)
    for j in range(5):
        studio.box(f"slab_etch{j}", (-0.9, -0.12, 0.85 + j * 0.34), (0.6, 0.02, 0.03), mats["accent"], 0)
    return left, left, {"slab_left": [left], "slab_right": [right]}


def build_network_node(studio, subject, mats):
    core = studio.sphere("node_core", (0, 0, 1.62), 0.62, mats["main"])
    links = []
    for j in range(6):
        a = j * math.tau / 6
        links.append(studio.cyl(f"node_link_{j}", (0.9 * math.cos(a), -0.1, 1.62 + 0.9 * math.sin(a)),
                                0.045, 1.1, mats["accent"], vertices=12,
                                rot=(math.radians(90), 0, -a)))
        studio.sphere(f"node_satellite{j}", (1.45 * math.cos(a), -0.1, 1.62 + 1.45 * math.sin(a)),
                      0.13, mats["steel"])
    return core, core, {"node_core": [core], "node_link_a": [links[0]], "node_link_b": [links[3]]}


def build_bookshelf(studio, subject, mats):
    frame = studio.box("shelf_frame", (0, 0.5, 1.5), (3.4, 0.9, 2.6), mats["warm"], 0.03)
    for row in range(3):
        for col in range(4):
            studio.box(f"shelf_volume{row}{col}", (-1.1 + col * 0.75, 0.62, 0.65 + row * 0.75),
                       (0.34, 0.5, 0.6), mats["dark"] if (row + col) % 2 else mats["steel"], 0.01)
    hero = studio.box("book_hero", (0, -0.42, 1.42), (0.42, 0.7, 0.94), mats["main"], 0.02)
    studio.box("book_pages", (0, -0.44, 1.42), (0.36, 0.66, 0.84), mats["ivory"], 0.01)
    return hero, hero, {"shelf_frame": [frame], "book_hero": [hero]}


def build_compass(studio, subject, mats):
    body = studio.cyl("compass_body", (0, 0, 1.5), 1.05, 0.26, mats["warm"],
                      rot=(math.radians(90), 0, 0))
    studio.cyl("compass_dial", (0, -0.16, 1.5), 0.92, 0.04, mats["dark"],
               rot=(math.radians(90), 0, 0))
    needle = studio.box("compass_needle", (0, -0.24, 1.5), (0.1, 0.04, 1.42), mats["accent"], 0.01)
    studio.box("compass_needle_tail", (0, -0.24, 1.5), (0.1, 0.04, 0.5), mats["alert"], 0.01)
    return body, needle, {"compass_body": [body], "compass_needle": [needle]}


def build_lens(studio, subject, mats):
    ring = studio.torus("lens_ring", (0, -0.5, 1.62), 0.85, 0.08, mats["warm"],
                        rot=(math.radians(90), 0, 0))
    glass = studio.cyl("lens_glass", (0, -0.5, 1.62), 0.82, 0.04, mats["main"],
                       rot=(math.radians(90), 0, 0))
    studio.cyl("lens_handle", (1.05, -0.45, 0.75), 0.09, 1.1, mats["steel"],
               rot=(0, math.radians(38), 0))
    studio.box("lens_target", (0, 0.15, 1.62), (0.9, 0.14, 0.9), mats["dark"], 0.02)
    return ring, ring, {"lens_ring": [ring], "lens_glass": [glass]}


def build_balance_scale(studio, subject, mats):
    beam = studio.box("scale_beam", (0, 0, 2.1), (3.0, 0.16, 0.16), mats["warm"], 0.02)
    studio.cyl("scale_column", (0, 0, 1.15), 0.1, 2.0, mats["steel"])
    left = studio.cyl("scale_pan_left", (-1.35, 0, 1.72), 0.52, 0.07, mats["steel"])
    right = studio.cyl("scale_pan_right", (1.35, 0, 1.72), 0.52, 0.07, mats["steel"])
    for side, x in ((-1, -1.35), (1, 1.35)):
        studio.cyl(f"scale_chain{side}", (x, 0, 1.95), 0.02, 0.5, mats["steel"])
    studio.cyl("scale_base", (0, 0, 0.16), 0.8, 0.2, mats["dark"])
    return beam, left, {"scale_beam": [beam], "scale_pan_left": [left],
                        "scale_pan_right": [right]}


def build_data_block(studio, subject, mats):
    block = studio.box("block_core", (0, 0, 1.5), (1.7, 1.2, 1.5), mats["main"], 0.07)
    for j in range(3):
        studio.box(f"block_stripe{j}", (0, -0.62, 1.05 + j * 0.45), (1.2, 0.02, 0.08),
                   mats["accent"], 0.005)
    return block, block, {"block_core": [block]}


def build_plinth_stack(studio, subject, mats):
    base = studio.cyl("plinth_base", (0, 0, 0.3), 1.5, 0.36, mats["dark"])
    lower = studio.box("stack_lower", (0, 0, 0.92), (2.1, 1.4, 0.7), mats["main"], 0.04)
    upper = studio.box("stack_upper", (0, 0, 1.72), (1.5, 1.0, 0.62), mats["steel"], 0.04)
    return upper, upper, {"plinth_base": [base], "stack_lower": [lower], "stack_upper": [upper]}


def build_generic_cube(studio, subject, mats):
    cube = studio.box("cube_core", (0, 0, 1.5), (1.5, 1.5, 1.5), mats["main"], 0.05)
    return cube, cube, {"cube_core": [cube]}


BUILDERS = {
    "glass_sphere": build_glass_sphere,
    "metal_sphere": build_metal_sphere,
    "voxel_sphere": build_voxel_sphere,
    "dial": build_dial,
    "clamp": build_clamp,
    "smartphone": build_smartphone,
    "mountain_pair": build_mountain_pair,
    "pipe_bundle": build_pipe_bundle,
    "chip_die": build_chip_die,
    "weight_grid": build_weight_grid,
    "block_pair": build_block_pair,
    "glass_slab": build_glass_slab,
    "network_node": build_network_node,
    "bookshelf": build_bookshelf,
    "compass": build_compass,
    "lens": build_lens,
    "balance_scale": build_balance_scale,
    "data_block": build_data_block,
    "plinth_stack": build_plinth_stack,
    "generic_cube": build_generic_cube,
}


# --- action programs --------------------------------------------------------
def key(obj, data_path, frame, value=None):
    if value is not None:
        setattr(obj, data_path, value)
    obj.keyframe_insert(data_path=data_path, frame=frame)
    return obj


class Ctx:
    def __init__(self, studio, spec, hero, mover, parts, mats):
        self.studio = studio
        self.spec = spec
        self.hero = hero
        self.mover = mover
        self.parts = parts
        self.mats = mats
        self.intensity = spec["action"]["intensity"]
        self.start = frame_start
        self.end = frame_end
        self.mid = (frame_start + frame_end) // 2
        self.extras = []

    def add(self, obj, part=None):
        self.extras.append(obj)
        if part:
            self.parts.setdefault(part, []).append(obj)
        return obj

    def extra(self, name):
        for obj in self.extras:
            if obj.name.startswith(name):
                return obj
        return None


def act_spin(ctx):
    hero = ctx.mover
    base = hero.rotation_euler.copy()
    key(hero, "rotation_euler", ctx.start, (base.x, base.y, base.z))
    key(hero, "rotation_euler", ctx.mid,
        (base.x, base.y + math.tau * 0.5, base.z + math.tau * 0.12))
    key(hero, "rotation_euler", ctx.end,
        (base.x, base.y + math.tau * 1.05, base.z + math.tau * 0.24))
    # A dial's needle sweeps around the dial face (the disc's own axis is Y).
    needle = ctx.parts.get("dial_needle", [None])[0]
    if needle is not None and needle is not hero:
        clockwise = -1 if index % 2 else 1
        key(needle, "rotation_euler", ctx.start, (0, 0, 0))
        key(needle, "rotation_euler", ctx.mid, (0, clockwise * math.tau * 0.9, 0))
        key(needle, "rotation_euler", ctx.end, (0, clockwise * math.tau * 2.1, 0))
        ctx.mover = needle
    compass = ctx.parts.get("compass_needle", [None])[0]
    if compass is not None and compass is not hero:
        key(compass, "rotation_euler", ctx.start, (0, 0, 0))
        key(compass, "rotation_euler", ctx.end, (0, math.tau * 2.4, 0))
        ctx.mover = compass


def act_compress(ctx):
    hero = ctx.mover
    s = hero.scale.copy()
    target = 0.42 if ctx.intensity > 0.6 else 0.58
    key(hero, "scale", ctx.start, (s.x, s.y, s.z))
    key(hero, "scale", ctx.mid, (s.x * 0.92, s.y * 0.92, s.z * 0.86))
    key(hero, "scale", ctx.end, (s.x * target, s.y * target, s.z * 0.66))
    key(hero, "location", ctx.end, (hero.location.x, hero.location.y, hero.location.z - 0.18))


def act_expand(ctx):
    hero = ctx.mover
    s = hero.scale.copy()
    key(hero, "scale", ctx.start, (s.x * 0.72, s.y * 0.72, s.z * 0.72))
    key(hero, "scale", ctx.end, (s.x * 1.75, s.y * 1.75, s.z * 1.75))
    key(hero, "rotation_euler", ctx.end, (0, 0, math.radians(40)))


def act_squeeze(ctx):
    upper = ctx.parts.get("clamp_jaw_upper", [None])[0]
    lower = ctx.parts.get("clamp_jaw_lower", [None])[0]
    screw = ctx.parts.get("clamp_screw", [None])[0]
    # A visibly deformable sample is held between the jaws.
    slug = ctx.add(ctx.studio.sphere("squeezed_sample", (0, 0, 1.5), 0.62, ctx.mats["main"]),
                   part=None)
    for jaw, direction, start_z, end_z in ((upper, -1, 2.42, 1.66), (lower, 1, 0.62, 1.34)):
        if jaw is None:
            continue
        key(jaw, "location", ctx.start, (jaw.location.x, jaw.location.y, start_z))
        key(jaw, "location", ctx.mid, (jaw.location.x, jaw.location.y,
                                       (start_z + end_z) / 2))
        key(jaw, "location", ctx.end, (jaw.location.x, jaw.location.y, end_z))
    if screw is not None:
        key(screw, "rotation_euler", ctx.start, (0, 0, 0))
        key(screw, "rotation_euler", ctx.end, (0, math.tau * 2.5, 0))
    key(slug, "scale", ctx.start, (1, 1, 1))
    key(slug, "scale", ctx.end, (1.16, 1.16, 0.38))
    ctx.parts["_squeezed"] = [slug]
    ctx.mover = upper if upper is not None else ctx.mover


def act_descend(ctx):
    hero = ctx.hero
    mass = ctx.add(ctx.studio.box("descending_mass", (0, -0.05, 3.5), (1.5, 1.1, 1.1),
                                 ctx.mats["warm"], 0.06), part=None)
    traces = [ctx.add(ctx.studio.box(f"descending_trace{j}", (-0.45 + j * 0.45, -0.66, 3.55),
                                    (0.04, 0.02, 0.8), ctx.mats["accent"], 0), part=None)
              for j in range(3)]
    for obj in [mass] + traces:
        offset = 3.55 if obj is mass else 3.57
        key(obj, "location", ctx.start, (obj.location.x, obj.location.y, offset))
        key(obj, "location", ctx.mid, (obj.location.x, obj.location.y, offset - 0.80))
        key(obj, "location", ctx.end, (obj.location.x, obj.location.y, offset - 1.45))
    key(mass, "rotation_euler", ctx.end, (0, 0, math.radians(12)))
    flare = ctx.add(ctx.studio.torus("impact_flare", (0, -0.2, 1.62), 0.4, 0.03, ctx.mats["alert"],
                              rot=(math.radians(90), 0, 0)), part=None)
    key(flare, "scale", ctx.start, (0.3, 0.3, 0.3))
    key(flare, "scale", ctx.mid, (0.9, 0.9, 0.9))
    key(flare, "scale", ctx.end, (1.6, 1.6, 1.6))
    ctx.mover = mass


def act_fall(ctx):
    hero = ctx.mover
    start_z = hero.location.z
    key(hero, "location", ctx.start, (hero.location.x, hero.location.y, start_z + 1.9))
    key(hero, "location", int(ctx.end * 0.62), (hero.location.x, hero.location.y, start_z + 0.05))
    key(hero, "location", int(ctx.end * 0.74), (hero.location.x, hero.location.y, start_z + 0.42))
    key(hero, "location", ctx.end, (hero.location.x, hero.location.y, start_z))
    key(hero, "rotation_euler", ctx.end, (math.radians(14), 0, math.radians(24)))
    ctx.add(ctx.studio.torus("impact_ring", (hero.location.x, hero.location.y + 0.1, start_z - 0.4),
                      0.6, 0.03, ctx.mats["accent"], rot=(math.radians(90), 0, 0)), part=None)


def act_collide(ctx):
    hero = ctx.mover
    others = [o for o in ctx.studio.objects
              if o is not hero and o.name.startswith(("block_a", "slab_right", "mountain_voxel",
                                                       "pipe_merged", "node_satellite"))]
    partner = others[0] if others else None
    if partner is None:
        # Every collision needs a visible reaction: build the target it hits.
        partner = ctx.add(ctx.studio.box(
            "collision_target", (hero.location.x * 0.35, hero.location.y,
                                 hero.location.z), (1.1, 0.9, 1.0),
            ctx.mats["steel"], 0.05), part=None)
    start = hero.location.copy()
    key(hero, "location", ctx.start, (start.x * 1.9, start.y, start.z))
    key(hero, "location", int(ctx.end * 0.55), (start.x * 0.95, start.y, start.z))
    key(hero, "location", ctx.end, (start.x * 0.55, start.y, start.z))
    if partner is not None:
        pstart = partner.location.copy()
        key(partner, "location", int(ctx.end * 0.6), (pstart.x, pstart.y, pstart.z))
        key(partner, "location", int(ctx.end * 0.75), (pstart.x + 0.22, pstart.y, pstart.z))
        key(partner, "location", ctx.end, (pstart.x + 0.06, pstart.y, pstart.z))
        key(partner, "rotation_euler", ctx.end, (0, 0, math.radians(-9)))
    spark = ctx.add(ctx.studio.sphere("collision_spark", (0, -0.5, 1.55), 0.16, ctx.mats["accent"]), part=None)
    key(spark, "scale", ctx.start, (0.1, 0.1, 0.1))
    key(spark, "scale", int(ctx.end * 0.62), (0.1, 0.1, 0.1))
    key(spark, "scale", int(ctx.end * 0.74), (1.5, 1.5, 1.5))
    key(spark, "scale", ctx.end, (0.0, 0.0, 0.0))


def act_snap_to_grid(ctx):
    hero = ctx.mover
    base = hero.location.copy()
    steps = 6
    for step in range(steps + 1):
        frame = ctx.start + int((ctx.end - ctx.start) * step / steps)
        angle = (math.tau / 12) * step
        key(hero, "rotation_euler", frame, (0, 0, angle))
        key(hero, "location", frame, (base.x + 0.16 * (step % 2) * (1 if step % 3 else -1),
                                      base.y, base.z + 0.10 * (step % 2)))
        for fcurve in hero.animation_data.action.fcurves:
            for kp in fcurve.keyframe_points:
                kp.interpolation = "CONSTANT"
    # Discrete cells appear one by one as the value quantises.
    cells = ctx.parts.get("voxel_cell") or ctx.parts.get("_movers") or []
    for j, cell in enumerate(cells[:8]):
        key(cell, "scale", ctx.start, (0, 0, 0))
        key(cell, "scale", ctx.start + int((ctx.end - ctx.start) * (0.15 + 0.08 * j)),
            (0.42, 0.42, 0.40))


def act_dissolve(ctx):
    victims = ctx.parts.get("_all_pipes") or ctx.parts.get("voxel_cell") or []
    victims = [v for v in victims if v is not ctx.mover]
    if len(victims) < 2:
        raise RuntimeError(
            f"dissolve is not filmable for subject {ctx.spec['subject']['kind']}: "
            "no parallel parts to remove"
        )
    for j, victim in enumerate(victims[:3]):
        key(victim, "scale", ctx.start + int((ctx.end - ctx.start) * 0.2 * j), (1, 1, 1))
        key(victim, "scale", ctx.start + int((ctx.end - ctx.start) * (0.5 + 0.15 * j)),
            (0.02, 0.02, 0.02))
        key(victim, "location", ctx.end,
            (victim.location.x, victim.location.y - 0.8, victim.location.z))
    hero = ctx.mover
    key(hero, "scale", ctx.start, (1, 1, 1))
    key(hero, "scale", ctx.end, (1.35, 1.35, 1.35))


def act_collapse_to_one(ctx):
    pipes = ctx.parts.get("_all_pipes") or []
    merged = ctx.parts.get("pipe_merged", [None])[0]
    if not pipes:
        # A chip die collapses its cores instead of pipes.
        pipes = [p for p in (ctx.parts.get("chip_core_b", [None])[0],
                             ctx.parts.get("chip_core_c", [None])[0]) if p is not None]
        merged = ctx.parts.get("chip_core_a", [None])[0]
    if not pipes or merged is None:
        raise RuntimeError(
            f"collapse_to_one is not filmable for subject {ctx.spec['subject']['kind']}"
        )
    for j, pipe in enumerate(pipes):
        key(pipe, "location", ctx.start, (pipe.location.x, pipe.location.y, pipe.location.z))
        key(pipe, "location", int(ctx.end * 0.65),
            (pipe.location.x * 0.42, pipe.location.y - 0.4, 1.42 - 0.12 * j))
        key(pipe, "scale", ctx.start, (1, 1, 1))
        key(pipe, "scale", int(ctx.end * 0.8), (0.25, 0.25, 0.25))
        key(pipe, "scale", ctx.end, (0.02, 0.02, 0.02))
    if merged is not None:
        key(merged, "scale", ctx.start, (0.05, 0.05, 0.05))
        key(merged, "scale", int(ctx.end * 0.7), (1.0, 1.0, 1.0))
        key(merged, "scale", ctx.end, (1.45, 1.45, 1.45))
        key(merged, "location", ctx.start, (0, 0.9, 1.42))
        key(merged, "location", ctx.end, (0, -1.35, 1.42))
        ctx.mover = merged


def act_assemble(ctx):
    movers = ctx.parts.get("_movers") or [ctx.mover]
    for j, obj in enumerate(movers[:6]):
        start = obj.location.copy()
        key(obj, "location", ctx.start, (start.x * 1.7, start.y + 0.4, start.z + 0.5))
        key(obj, "location", ctx.end, (start.x, start.y, start.z))
        key(obj, "rotation_euler", ctx.start, (math.radians(18 * (j % 3)), 0,
                                               math.radians(24 * (j % 2))))
        key(obj, "rotation_euler", ctx.end, (0, 0, 0))
    ctx.mover = movers[0]


def act_flow(ctx):
    hero = ctx.hero
    target_x = -hero.location.x if abs(hero.location.x) > 0.05 else 1.4
    packets = []
    for j in range(3):
        packets.append(ctx.add(ctx.studio.sphere(f"flow_packet{j}", (-2.2, -0.55, 1.5), 0.13,
                                          ctx.mats["accent"]), part=None))
    for j, packet in enumerate(packets):
        offset = j * 0.16
        key(packet, "location", ctx.start, (-2.2 if target_x > 0 else 2.2, -0.55, 1.5))
        key(packet, "location", ctx.end - int(offset * (ctx.end - ctx.start)),
            (target_x, -0.35, 1.62 + 0.2 * (j - 1)))
    ctx.mover = packets[0]
    link = ctx.parts.get("block_link") or ctx.parts.get("node_link_a")
    if link:
        key(link[0], "scale", ctx.start, (1, 1, 1))
        key(link[0], "scale", ctx.end, (1.3, 1.6, 1.3))


def act_sweep(ctx):
    beam = ctx.add(ctx.studio.box("sweep_beam", (-1.7, -0.75, 1.62), (0.05, 0.05, 2.3),
                                  ctx.mats["accent"], 0.0), part=None)
    key(beam, "location", ctx.start, (-1.7, -0.75, 1.62))
    key(beam, "location", ctx.mid, (0, -0.75, 1.62))
    key(beam, "location", ctx.end, (1.7, -0.75, 1.62))
    hero = ctx.mover
    key(hero, "rotation_euler", ctx.start, (0, 0, 0))
    key(hero, "rotation_euler", ctx.end, (0, 0, math.radians(28)))
    ctx.mover = beam


def act_scan(ctx):
    ring = ctx.parts.get("lens_ring", [ctx.mover])[0]
    start = ring.location.copy()
    key(ring, "location", ctx.start, (start.x - 0.9, start.y, start.z + 0.5))
    key(ring, "location", ctx.mid, (start.x + 0.2, start.y, start.z))
    key(ring, "location", ctx.end, (start.x + 0.95, start.y, start.z - 0.45))
    glass = ctx.parts.get("lens_glass", [None])[0]
    if glass is not None:
        key(glass, "location", ctx.start, (start.x - 0.9, start.y, start.z + 0.5))
        key(glass, "location", ctx.end, (start.x + 0.95, start.y, start.z - 0.45))
    reveal = ctx.add(ctx.studio.box("scan_reveal_panel", (0, -0.3, 1.35), (1.0, 0.02, 0.7),
                             ctx.mats["accent"], 0.0), part=None)
    key(reveal, "scale", ctx.start, (0.05, 1, 0.05))
    key(reveal, "scale", ctx.end, (1.0, 1, 1.0))
    ctx.mover = ring


def act_reveal(ctx):
    occluders = [o for o in ctx.studio.objects
                 if o.name.startswith(("slab_right", "shelf_frame", "book_hero"))]
    hero = ctx.mover
    occluder = next((o for o in occluders if o is not hero), None)
    if occluder is not None:
        start = occluder.location.copy()
        key(occluder, "location", ctx.start, (start.x, start.y, start.z))
        key(occluder, "location", ctx.end, (start.x + 1.6, start.y, start.z))
        key(occluder, "rotation_euler", ctx.end, (0, 0, math.radians(-18)))
    key(hero, "location", ctx.start, (hero.location.x, hero.location.y, hero.location.z))
    key(hero, "location", ctx.end, (hero.location.x, hero.location.y - 0.75,
                                    hero.location.z + 0.12))
    key(hero, "rotation_euler", ctx.end, (math.radians(12), 0, math.radians(18)))
    ctx.mover = occluder or hero


def act_transform(ctx):
    hero = ctx.mover
    second = ctx.add(ctx.studio.box("transform_target", (hero.location.x + 1.35, hero.location.y,
                                                  hero.location.z),
                             (0.95, 0.8, 1.15), ctx.mats["steel"], 0.05), part=None)
    key(second, "scale", ctx.start, (0.02, 0.02, 0.02))
    key(second, "scale", ctx.end, (1.0, 1.0, 1.0))
    key(second, "rotation_euler", ctx.start, (0, 0, math.radians(-40)))
    key(second, "rotation_euler", ctx.end, (0, 0, 0))
    key(hero, "scale", ctx.start, (1, 1, 1))
    key(hero, "scale", ctx.end, (0.55, 0.55, 0.55))
    key(hero, "rotation_euler", ctx.end, (0, 0, math.radians(65)))
    key(hero, "location", ctx.end, (hero.location.x - 0.3, hero.location.y, hero.location.z))


def act_pulse(ctx):
    hero = ctx.mover
    key(hero, "scale", ctx.start, (1, 1, 1))
    key(hero, "scale", int(ctx.end * 0.3), (1.28, 1.28, 1.28))
    key(hero, "scale", int(ctx.end * 0.55), (0.96, 0.96, 0.96))
    key(hero, "scale", int(ctx.end * 0.8), (1.34, 1.34, 1.34))
    key(hero, "scale", ctx.end, (1.05, 1.05, 1.05))
    for j, radius in enumerate((1.0, 1.35, 1.7)):
        ring = ctx.add(ctx.studio.torus(f"pulse_ring{j}", (hero.location.x, hero.location.y, hero.location.z),
                                 radius, 0.025, ctx.mats["accent"],
                                 rot=(math.radians(90), 0, 0)), part=None)
        key(ring, "scale", ctx.start + int((ctx.end - ctx.start) * 0.15 * j),
            (0.25, 0.25, 0.25))
        key(ring, "scale", ctx.end, (1.9, 1.9, 1.9))


def act_compare_pan(ctx):
    left = ctx.parts.get("mountain_smooth", [None])[0]
    right = ctx.parts.get("mountain_voxel", [None])
    right_obj = right[0] if right else None
    if left is None or right_obj is None:
        # The balance scale compares two pans instead of two terrains.
        left = ctx.parts.get("scale_pan_left", [None])[0]
        right_obj = ctx.parts.get("scale_pan_right", [None])[0]
        beam = ctx.parts.get("scale_beam", [None])[0]
        if beam is not None:
            key(beam, "rotation_euler", ctx.start, (0, 0, 0))
            key(beam, "rotation_euler", ctx.end, (0, math.radians(14), 0))
    for obj, sign in ((left, -1), (right_obj, 1)):
        if obj is None:
            continue
        start = obj.location.copy()
        key(obj, "location", ctx.start, (start.x, start.y, start.z))
        key(obj, "location", int(ctx.end * 0.35), (start.x + 0.18 * sign, start.y, start.z + 0.2))
        key(obj, "location", ctx.end, (start.x + 0.34 * sign, start.y, start.z + 0.05))
        key(obj, "rotation_euler", ctx.end, (0, 0, math.radians(16 * sign)))
    ctx.mover = right_obj or left or ctx.mover


ACTION_PROGRAMS = {
    "spin": act_spin,
    "compress": act_compress,
    "expand": act_expand,
    "squeeze": act_squeeze,
    "descend": act_descend,
    "fall": act_fall,
    "collide": act_collide,
    "snap_to_grid": act_snap_to_grid,
    "dissolve": act_dissolve,
    "collapse_to_one": act_collapse_to_one,
    "assemble": act_assemble,
    "flow": act_flow,
    "sweep": act_sweep,
    "scan": act_scan,
    "reveal": act_reveal,
    "transform": act_transform,
    "pulse": act_pulse,
    "compare_pan": act_compare_pan,
}


# --- camera + lighting ------------------------------------------------------
FRAMING = {
    "extreme_close_up": {"distance": 3.1, "height": 0.35, "lens": 62},
    "close_up": {"distance": 4.4, "height": 0.55, "lens": 55},
    "medium": {"distance": 6.4, "height": 1.0, "lens": 50},
    "wide": {"distance": 8.6, "height": 1.7, "lens": 42},
}


def setup_camera(spec, focus_center, hero):
    framing = FRAMING[spec["camera"]["framing"]]
    distance = framing["distance"]
    base = Vector((0.9 if index % 2 else -0.9, -distance, focus_center.z + framing["height"]))
    bpy.ops.object.camera_add(location=base)
    camera = bpy.context.object
    camera.name = "hero_camera"
    camera.data.lens = framing["lens"]
    scene.camera = camera
    look = (focus_center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.rotation_euler = look
    camera.keyframe_insert(data_path="location", frame=frame_start)
    camera.keyframe_insert(data_path="rotation_euler", frame=frame_start)

    move = spec["camera"]["move"]
    end_loc = base.copy()
    if move == "push_in":
        end_loc.y += distance * 0.34
    elif move == "pull_out":
        end_loc.y -= distance * 0.30
    elif move == "pan_left":
        end_loc.x -= distance * 0.24
    elif move == "pan_right":
        end_loc.x += distance * 0.24
    elif move == "tilt_up":
        end_loc.z += distance * 0.18
    elif move == "orbit":
        end_loc.x = base.x * -1.15
        end_loc.y = base.y * 0.82
    end_loc.z += 0.12
    camera.location = end_loc
    camera.rotation_euler = (focus_center - end_loc).to_track_quat("-Z", "Y").to_euler()
    camera.keyframe_insert(data_path="location", frame=frame_end)
    camera.keyframe_insert(data_path="rotation_euler", frame=frame_end)
    for fcurve in camera.animation_data.action.fcurves:
        for kp in fcurve.keyframe_points:
            kp.interpolation = "BEZIER"
    scene.camera.data.dof.use_dof = True
    scene.camera.data.dof.focus_object = hero
    scene.camera.data.dof.aperture_fstop = 3.2 if spec["camera"]["framing"] in (
        "extreme_close_up", "close_up") else 5.0
    return camera


def setup_lighting(mood):
    key_color, rim_color, fill_color = LIGHTING.get(mood, LIGHTING["cool"])
    specs = (
        ("key_light", (4.2, -5.0, 5.4), 1500, key_color, 5.0),
        ("rim_light", (-4.6, 1.6, 3.6), 1900, rim_color, 3.0),
        ("fill_light", (0.0, 3.6, 5.2), 850, fill_color, 4.5),
    )
    for name, loc, power, color, size in specs:
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.name = name
        light.data.energy = power
        light.data.color = color
        light.data.shape = "DISK"
        light.data.size = size
        light.rotation_euler = (Vector((0, 0, 1.5)) - light.location).to_track_quat("-Z", "Y").to_euler()


# --- measurement ------------------------------------------------------------
def world_center(objs):
    points = [o.matrix_world.translation for o in objs if o is not None]
    if not points:
        return Vector((0, 0, 1.4))
    total = Vector((0, 0, 0))
    for point in points:
        total += point
    return total / len(points)


def screen_point(camera, point):
    co = world_to_camera_view(scene, camera, point)
    return Vector((co.x * RENDER_W, (1.0 - co.y) * RENDER_H))


def object_corners(obj):
    """World-space points that move when the object rotates, moves or deforms."""
    try:
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    except Exception:  # noqa: BLE001 - a text object without geometry must not abort QA
        corners = [obj.matrix_world.translation.copy()]
    # Keep a stable, deterministic subset of the eight bounding-box corners.
    return [corners[i] for i in (0, 2, 5, 6)] if len(corners) >= 7 else corners


def measure(camera, tracked):
    """Sample the real animated transforms from Blender's animation system."""
    frames = [frame_start + int((frame_end - frame_start) * t)
              for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    frames = sorted(set(min(frame_end, max(frame_start, f)) for f in frames))
    samples = {}
    for name, objs in tracked.items():
        objs = [o for o in objs if o is not None]
        if not objs:
            continue
        series = []
        for frame in frames:
            scene.frame_set(frame)
            points, screen = [], []
            for obj in objs:
                for corner in object_corners(obj):
                    points.append([round(corner.x, 4), round(corner.y, 4), round(corner.z, 4)])
                    sp = screen_point(camera, corner)
                    screen.append([round(sp.x, 3), round(sp.y, 3)])
            xs = [p[0] for p in points] or [0.0]
            ys = [p[1] for p in points] or [0.0]
            zs = [p[2] for p in points] or [0.0]
            quat = objs[0].rotation_euler.to_quaternion()
            series.append({
                "frame": frame,
                "points": points,
                "screen": screen,
                "centroid": [round(v, 4) for v in world_center(objs)],
                "extent": [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4),
                           round(max(zs) - min(zs), 4)],
                "scale": round(sum(o.scale.length for o in objs) / len(objs), 4),
                "quaternion": [round(v, 6) for v in quat],
            })
        samples[name] = series
    scene.frame_set(frame_start)
    return frames, samples


def _quat_angle_degrees(a, b):
    from mathutils import Quaternion
    qa = Quaternion((a[0], a[1], a[2], a[3]))
    qb = Quaternion((b[0], b[1], b[2], b[3]))
    return math.degrees(qa.rotation_difference(qb).angle)


def summarize(series):
    """Reduce a sampled series to measured motion quantities."""
    if not series:
        return {}
    first, last = series[0], series[-1]
    count = min(len(first["points"]), *(len(s["points"]) for s in series)) if series else 0
    displacement = 0.0
    screen_delta = 0.0
    for k in range(count):
        p0 = first["points"][k]
        s0 = first["screen"][k]
        for sample in series:
            displacement = max(displacement, math.dist(p0, sample["points"][k]))
            screen_delta = max(screen_delta, math.dist(s0, sample["screen"][k]))
    drop = 0.0
    for k in range(count):
        start_z = first["points"][k][2]
        lowest = min(sample["points"][k][2] for sample in series)
        drop = max(drop, start_z - lowest)
    rotation = 0.0
    for prev, cur in zip(series, series[1:]):
        rotation += _quat_angle_degrees(prev["quaternion"], cur["quaternion"])
    first_scale = first["scale"] or 1.0
    distinct = len({(round(s["centroid"][0], 2), round(s["centroid"][2], 2))
                    for s in series})
    first_extent = first.get("extent") or [1.0, 1.0, 1.0]
    height_ratio = min((s.get("extent") or first_extent)[2] for s in series) / \
        (first_extent[2] or 1.0)
    return {
        "displacement": round(displacement, 4),
        "centroid_displacement": round(max(math.dist(first["centroid"], s["centroid"])
                                           for s in series), 4),
        "translate_down": round(drop, 4),
        "screen_pixels": round(screen_delta, 2),
        "scale_ratio_max": round(max(s["scale"] for s in series) / first_scale, 4),
        "scale_ratio_min": round(min(s["scale"] for s in series) / first_scale, 4),
        "height_ratio_min": round(height_ratio, 4),
        "rotation_degrees": round(rotation, 2),
        "distinct_positions": distinct,
        "final_scale": round(last["scale"], 4),
        "first_scale": round(first["scale"], 4),
        "start_world": first["centroid"],
        "end_world": last["centroid"],
    }


# --- build ------------------------------------------------------------------
configure_scene()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
for block in list(bpy.data.meshes):
    if block.users == 0:
        bpy.data.meshes.remove(block)

studio = Studio()
mats = base_materials(spec["subject"])
build_environment(studio, spec["environment"], mats)

builder = BUILDERS[spec["subject"]["kind"]]
hero, mover, parts = builder(studio, spec["subject"], mats)

ctx = Ctx(studio, spec, hero, mover, parts, mats)
ACTION_PROGRAMS[spec["action"]["kind"]](ctx)

# Idle life for the whole set: tiny amplitude only, so it can never be mistaken
# for the scene's action, and never a substitute for subject animation.
for obj in list(scene.objects):
    if obj.type in {"MESH", "CURVE", "FONT"} and not obj.animation_data:
        base_rot = obj.rotation_euler.copy()
        key(obj, "rotation_euler", frame_start, (base_rot.x, base_rot.y, base_rot.z))
        key(obj, "rotation_euler", frame_end,
            (base_rot.x, base_rot.y, base_rot.z + math.radians(2.0)))

tracked = {"hero": [hero], "mover": [ctx.mover]}
for name, objs in parts.items():
    tracked[name] = objs
for j, obj in enumerate(ctx.extras):
    tracked[f"extra_{j}"] = [obj]

scene.frame_set(frame_start)
focus_parts = tracked.get("mover") or [hero]
focus_center = world_center(focus_parts)
camera = setup_camera(spec, focus_center, hero)
setup_lighting(spec["lighting"]["mood"])

# Scene statement stays short and readable on a phone.
title = spec.get("on_screen_text") or spec["subject"].get("label") or ""
if title:
    studio.label("scene_title", title, (0, -0.9, 0.32), 0.17, mats["ivory"])

for action in bpy.data.actions:
    for fcurve in action.fcurves:
        for kp in fcurve.keyframe_points:
            if kp.interpolation != "CONSTANT":
                kp.interpolation = "BEZIER"

frames, samples = measure(camera, tracked)
summary = summarize(samples.get("mover", []))
hero_summary = summarize(samples.get("hero", []))
part_reports = {}
for name, series in samples.items():
    if name in {"hero", "mover"} or name.startswith("_"):
        continue
    part_reports[name] = summarize(series)
squeezed = samples.get("_squeezed")
squeezed_summary = summarize(squeezed) if squeezed else None

moving_parts = sum(1 for name, report in part_reports.items()
                   if report.get("displacement", 0) >= 0.08
                   or report.get("scale_ratio_max", 1) >= 1.08
                   or report.get("scale_ratio_min", 1) <= 0.92)
removed_parts = sum(1 for name, report in part_reports.items()
                    if report.get("final_scale", 1) <= 0.35 * max(report.get("first_scale", 1), 1e-6))
hero_travel = 0.0
if samples.get("hero"):
    hero_series = samples["hero"]
    hero_travel = max(math.dist(hero_series[0]["centroid"], s["centroid"])
                      for s in hero_series)

trace = {
    "scene_index": index,
    "scene_total": int(scene_total),
    "schema_version": scene_spec.SCHEMA_VERSION,
    "template": scene_spec.template_id(spec),
    "subject": spec["subject"],
    "action": spec["action"],
    "environment": spec["environment"],
    "camera": spec["camera"],
    "lighting": spec["lighting"],
    "hero_object": hero.name if hero else None,
    "mover_object": ctx.mover.name if ctx.mover else None,
    "parts": {name: [o.name for o in objs if o is not None]
              for name, objs in parts.items() if not name.startswith("_")},
    "required_parts": scene_spec.required_parts(spec),
    "built_parts": sorted(name for name in parts if not name.startswith("_")),
    "extra_objects": [o.name for o in ctx.extras],
    "frames": {"start": frame_start, "end": frame_end, "fps": RENDER_FPS,
               "samples": frames},
    "measured": {
        "mover": summary,
        "hero": hero_summary,
        "hero_tracked_travel": round(hero_travel, 4),
        "parts_moved": moving_parts,
        "parts_removed": removed_parts,
        "moving_part_names": sorted(name for name, report in part_reports.items()
                                    if report.get("displacement", 0) >= 0.08
                                    or report.get("scale_ratio_max", 1) >= 1.08
                                    or report.get("scale_ratio_min", 1) <= 0.92),
        "subject_dominates_camera": bool(
            summary.get("displacement", 0) >= scene_spec.MIN_SUBJECT_DISPLACEMENT_UNITS),
        "parts": part_reports,
        "squeezed_part": squeezed_summary,
    },
    "requirement": scene_spec.motion_requirement(spec),
    "degraded": bool(spec.get("degraded", False)),
    "brief": {
        "subject": spec["subject"]["kind"],
        "action": spec["action"]["kind"],
        "from_state": spec.get("from_state", ""),
        "to_state": spec.get("to_state", ""),
    },
}
trace_path = Path(output_path).with_name(Path(output_path).stem + ".visual.json")
trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")

scene.frame_set(frame_start)
bpy.ops.render.render(animation=True)
