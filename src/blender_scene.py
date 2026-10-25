import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# Usage: blender -b -t 2 --python src/blender_scene.py -- scene.json frame.png index total
args = sys.argv[sys.argv.index("--") + 1:]
brief_path, output_path, scene_index, scene_total = args
brief = json.loads(Path(brief_path).read_text())
index, total = int(scene_index), int(scene_total)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.render.resolution_x = 720
scene.render.resolution_y = 1280
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.world.color = (0.006, 0.009, 0.02)
scene.render.film_transparent = False
scene.view_settings.view_transform = "AgX"

def material(name, color, metallic=0.0, roughness=0.35, emission=0.0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    return m

navy = material("Midnight blue ceramic", (0.012, 0.035, 0.075), 0.35)
steel = material("Brushed steel", (0.24, 0.34, 0.47), 0.78, 0.24)
gold = material("Aged bronze", (0.55, 0.29, 0.085), 0.72, 0.28)
glow = material("Electric cyan", (0.025, 0.48, 0.9), 0.3, 0.22, 2.0)
stone = material("Ancient limestone", (0.37, 0.32, 0.24), 0.08, 0.8)
red = material("Signal red", (0.55, 0.035, 0.045), 0.25)
floor_mat = material("Dark stage", (0.009, 0.015, 0.03), 0.2, 0.42)

def apply_mat(obj, mat):
    obj.data.materials.append(mat)
    return obj

def cube(name, loc, scale, mat, bevel=0.08):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    apply_mat(obj, mat)
    if bevel:
        mod = obj.modifiers.new("Soft machined edges", "BEVEL")
        mod.width, mod.segments = bevel, 3
        obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return obj

def sphere(name, loc, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.shade_smooth()
    return apply_mat(obj, mat)

def cylinder(name, loc, radius, depth, mat, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    apply_mat(obj, mat)
    bevel = obj.modifiers.new("Edge highlights", "BEVEL")
    bevel.width, bevel.segments = 0.04, 2
    obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return obj

def torus(name, loc, major, minor, mat):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=64, minor_segments=12, location=loc)
    obj = bpy.context.object
    obj.name = name
    bpy.ops.object.shade_smooth()
    return apply_mat(obj, mat)

def text_obj(body, loc, size, mat):
    bpy.ops.object.text_add(location=loc, rotation=(math.radians(90), 0, 0))
    obj = bpy.context.object
    obj.data.body = body[:36].upper()
    obj.data.size = size
    obj.data.extrude = 0.004
    obj.data.align_x = "CENTER"
    apply_mat(obj, mat)
    return obj

# Clear default scene.
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
brief_text = (str(brief.get("visual", "")) + " " + str(brief.get("on_screen_text", ""))).lower()
historical = any(k in brief_text for k in ("rome", "roman", "socrates", "ancient", "soldier", "emperor", "philosoph", "battle", "history", "athens"))
technical = any(k in brief_text for k in ("ai", "data", "network", "computer", "technology", "system", "model", "digital", "robot", "algorithm"))
accent = gold if historical else glow
floor = cube("Infinite stage", (0, 0, -0.24), (16, 16, 0.4), floor_mat, 0.03)

# Build a scene-specific 3D hero object, not a flat graphic.
if historical:
    # Original stylised Roman-inspired helmet bust: procedural geometry, not copied artwork.
    cylinder("Bust plinth", (0, 0.1, 0.15), 1.18, 0.32, stone)
    cylinder("Bronze trim", (0, 0.1, 0.34), 1.05, 0.06, gold)
    sphere("Helmet crown", (0, 0.0, 1.62), (0.9, 0.66, 0.92), steel)
    cube("Helmet brow", (0, -0.58, 1.48), (1.68, 0.18, 0.19), gold, 0.06)
    cube("Nose guard", (0, -0.63, 1.08), (0.16, 0.18, 0.65), steel, 0.04)
    for side in (-1, 1):
        sphere("Helmet cheek guard", (side*0.7, -0.36, 1.0), (0.24, 0.18, 0.48), gold)
        for j in range(3):
            cube("Helmet crest rib", (side*(0.22+j*0.19), -0.05, 2.27-j*0.05), (0.07, 0.08, 0.42-j*0.06), red, 0.02)
    torus("Artifact halo", (0, 0.3, 1.58), 1.35, 0.025, accent)
    for j in range(7):
        a = j * math.tau / 7
        cube("Stone column", (math.cos(a)*2.15, 0.65, 0.75), (0.22, 0.22, 1.9), stone, 0.025)
        cube("Column capital", (math.cos(a)*2.15, 0.65, 1.75), (0.38, 0.34, 0.13), gold, 0.025)
else:
    # Sculptural technology core with orbital rings, nodes and floating data blocks.
    cylinder("Reactor base", (0, 0, 0.08), 1.3, 0.24, navy)
    torus("Energy ring one", (0, 0, 1.2), 1.12, 0.045, glow).rotation_euler[0] = math.radians(62)
    torus("Energy ring two", (0, 0, 1.2), 1.38, 0.035, accent).rotation_euler[1] = math.radians(62)
    sphere("Core", (0, 0, 1.2), (0.65, 0.65, 0.65), navy)
    sphere("Core light", (0, -0.04, 1.2), (0.42, 0.42, 0.42), glow)
    for j in range(8):
        a = j * math.tau / 8
        x, y = math.cos(a)*1.85, math.sin(a)*1.85
        sphere("Orbit node", (x, y, 1.15 + 0.25*math.sin(a*2)), (0.16,0.16,0.16), accent if j%2 else steel)
        cube("Floating data tile", (x*1.22, y*1.22, 0.35+(j%3)*0.27), (0.28,0.12,0.22), navy, 0.035)

# Background architectural ribs add parallax and cinematic depth.
for j in range(9):
    x = (j-4)*0.78
    cube("Backdrop rib", (x, 2.5, 1.5), (0.035,0.08,4.0), accent if j%3==0 else steel, 0.01)

# Floating title plaque; concise scene phrase is part of the set dressing.
title = str(brief.get("on_screen_text", brief.get("visual", "THE HIDDEN MECHANISM"))).strip()[:28]
text_obj(title, (0, -1.28, 3.15), 0.22, material("Title ivory", (0.83,0.89,0.98), 0.0, 0.6, 0.1))

# Cinematic three-point lighting and a subtle ground pool.
def area(name, loc, power, color, size, target=(0,0,1.2)):
    bpy.ops.object.light_add(type="AREA", location=loc)
    light = bpy.context.object
    light.name = name
    light.data.energy = power
    light.data.color = color
    light.data.shape = "DISK"
    light.data.size = size
    light.rotation_euler = (Vector(target)-light.location).to_track_quat("-Z","Y").to_euler()
area("Cool key light", (4,-5,6), 1050, (0.42,0.68,1.0), 5)
area("Warm rim light", (-4,1,4), 1350, (1.0,0.48,0.16) if historical else (0.15,0.38,1.0), 3)
area("Top softbox", (0,3,6), 900, (0.55,0.7,1.0), 4)

bpy.ops.object.camera_add(location=(4.6,-9.5,4.2))
camera = bpy.context.object
camera.rotation_euler = (Vector((0,0,1.25))-camera.location).to_track_quat("-Z","Y").to_euler()
camera.data.lens = 48
scene.camera = camera
scene.render.image_settings.color_mode = "RGB"
scene.render.filepath = str(Path(output_path).resolve())
scene.camera.data.dof.use_dof = True
scene.camera.data.dof.focus_object = bpy.data.objects.get("Core") or bpy.data.objects.get("Helmet crown")
scene.camera.data.dof.aperture_fstop = 5.6
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(Path(output_path).resolve())
scene.render.resolution_x, scene.render.resolution_y = 720, 1280
scene.render.image_settings.color_depth = "8"
scene.render.film_transparent = False
scene.camera.data.lens = 55
scene.render.resolution_percentage = 75 if index % 2 else 100
scene.render.filepath = str(Path(output_path).resolve())
bpy.ops.render.render(write_still=True)
