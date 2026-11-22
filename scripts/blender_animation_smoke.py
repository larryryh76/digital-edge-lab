#!/usr/bin/env python3
"""Import a real CC0 GLB, play a humanoid motion clip, measure bone movement, and render review frames.

Run inside Blender:
  blender -b -t 2 --python scripts/blender_animation_smoke.py -- <input.glb> <review-dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


args = sys.argv[sys.argv.index("--") + 1:]
input_path = Path(args[0]).resolve()
review_dir = Path(args[1]).resolve()
review_dir.mkdir(parents=True, exist_ok=True)


def fail(message):
    raise RuntimeError(f"animation smoke failure: {message}")


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(input_path))
armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not armatures or not meshes:
    fail(f"GLB import produced {len(armatures)} armatures and {len(meshes)} meshes")

armature = armatures[0]
actions = list(bpy.data.actions)
candidates = [
    "jog_fwd_loop", "walk_loop", "jog", "walk", "crouch_fwd_loop"
]
action = next(
    (a for term in candidates for a in actions if term in a.name.lower()),
    None,
)
if action is None:
    fail("no supported walk/jog locomotion action found")
armature.animation_data_create()
armature.animation_data.action = action
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
scene.render.resolution_x = 360
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.render.fps = 24
scene.render.filepath = str(review_dir / "frame_start.png")

start, end = map(float, action.frame_range)
if end <= start:
    fail(f"selected action {action.name} has no duration")
sample_frames = [int(round(start)), int(round(start + (end - start) * 0.5)), int(round(end))]


def bone_positions(frame):
    scene.frame_set(frame)
    return {
        bone.name: (armature.matrix_world @ bone.matrix).translation.copy()
        for bone in armature.pose.bones
    }


samples = [bone_positions(frame) for frame in sample_frames]
max_motion = 0.0
max_motion_bone = None
for a, b in ((0, 1), (1, 2), (0, 2)):
    for name in samples[a]:
        if name in samples[b]:
            delta = (samples[b][name] - samples[a][name]).length
            if delta > max_motion:
                max_motion, max_motion_bone = delta, name
if max_motion < 0.015:
    fail(f"locomotion clip has no measurable subject movement ({max_motion:.5f})")

# Render a review image using imported meshes, their real materials, and simple studio lighting.
scene.frame_set(sample_frames[0])
bounds = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
minimum = Vector((min(v.x for v in bounds), min(v.y for v in bounds), min(v.z for v in bounds)))
maximum = Vector((max(v.x for v in bounds), max(v.y for v in bounds), max(v.z for v in bounds)))
center = (minimum + maximum) * 0.5
extent = max((maximum - minimum).length, 1.0)

bpy.ops.mesh.primitive_plane_add(size=extent * 6, location=(center.x, center.y, minimum.z - 0.04))
floor = bpy.context.object
floor.name = "ReviewFloor"
material = bpy.data.materials.new("ReviewFloorMaterial")
material.diffuse_color = (0.045, 0.055, 0.075, 1.0)
floor.data.materials.append(material)

world = bpy.data.worlds.new("ReviewWorld") if scene.world is None else scene.world
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.12, 0.15, 0.20, 1.0)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5

def add_area(name, position, power, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()

add_area("Key", center + Vector((extent, -extent, extent * 1.5)), 900, extent)
add_area("Fill", center + Vector((-extent, -extent * 0.4, extent)), 450, extent * 0.8)
add_area("Rim", center + Vector((0, extent, extent)), 650, extent)

camera_data = bpy.data.cameras.new("ReviewCamera")
camera = bpy.data.objects.new("ReviewCamera", camera_data)
scene.collection.objects.link(camera)
camera.location = center + Vector((extent * 1.2, -extent * 2.5, extent * 0.75))
camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
camera_data.lens = 55
scene.camera = camera

scene.render.image_settings.file_format = "PNG"
for index, frame in enumerate((sample_frames[0], sample_frames[-1])):
    scene.frame_set(frame)
    scene.render.filepath = str(review_dir / f"frame_{index:02d}.png")
    bpy.ops.render.render(write_still=True)

report = {
    "asset": input_path.name,
    "mesh_count": len(meshes),
    "armature_count": len(armatures),
    "bone_count": len(armature.pose.bones),
    "animation_count": len(actions),
    "selected_action": action.name,
    "frame_range": [start, end],
    "sample_frames": sample_frames,
    "max_bone_motion": round(max_motion, 6),
    "max_motion_bone": max_motion_bone,
    "passed": True,
}
(review_dir / "animation-smoke.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print("ANIMATION_SMOKE_REPORT=" + json.dumps(report))
