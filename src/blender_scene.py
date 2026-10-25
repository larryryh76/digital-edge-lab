import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# Usage: blender -b -t 2 --python src/blender_scene.py -- scene.json frame.png index total
args = sys.argv[sys.argv.index("--") + 1:]
brief_path, output_path, scene_index, scene_total, duration_arg = args
brief = json.loads(Path(brief_path).read_text())
index, total = int(scene_index), int(scene_total)
shot_seconds = max(float(duration_arg), 2.0)
scene = bpy.context.scene
try:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
except Exception:
    scene.render.engine = "BLENDER_EEVEE"

scene.render.resolution_x = 360
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
try:
    scene.eevee.taa_render_samples = 8
except Exception:
    pass
scene.render.fps = 8
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
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
        mod.width, mod.segments = bevel, 1
        obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return obj

def sphere(name, loc, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.shade_smooth()
    return apply_mat(obj, mat)

def cylinder(name, loc, radius, depth, mat, vertices=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    apply_mat(obj, mat)
    bevel = obj.modifiers.new("Edge highlights", "BEVEL")
    bevel.width, bevel.segments = 0.04, 1
    obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return obj

def torus(name, loc, major, minor, mat):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=32, minor_segments=8, location=loc)
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
    if any(k in brief_text for k in ("socrates", "philosoph", "athens", "thinker")):
        cylinder("Pedestal", (0, 0.1, 0.15), 1.12, 0.3, stone)
        cylinder("Bronze pedestal rim", (0, 0.1, 0.33), 1.0, 0.06, gold)
        sphere("Philosopher head", (0, 0, 1.72), (0.68, 0.59, 0.82), stone)
        sphere("Beard", (0, -0.43, 1.22), (0.48, 0.23, 0.43), stone)
        for side in (-1, 1):
            sphere("Eye", (side*0.24, -0.535, 1.83), (0.07,0.035,0.045), gold)
            for j in range(3):
                sphere("Hair curl", (side*(0.36+j*0.07), -0.25, 2.15-j*0.12), (0.13,0.13,0.13), stone)
        for j in range(3):
            cube("Ancient scroll", (-1.2+j*0.22, -0.05, 0.55+j*0.07), (0.16,0.55,0.12), gold, 0.045)
        for j in range(5):
            cube("Library column", ((j-2)*1.05, 1.7, 1.1), (0.12,0.15,2.5), stone, 0.025)
    elif any(k in brief_text for k in ("shield", "formation", "battle", "soldier", "legion", "war")):
        cylinder("Bust plinth", (0, 0.1, 0.15), 1.18, 0.32, stone)
        for row in range(2):
            for col in range(3):
                x = (col-1)*0.86 + (0.42 if row else 0)
                z = 0.95 + row*0.85
                cube("Roman shield", (x, -0.1+row*0.28, z), (0.76,0.16,0.92), red if (col+row)%2 else steel, 0.12)
                sphere("Shield boss", (x, -0.22+row*0.28, z), (0.16,0.07,0.16), gold)
        for j in range(5):
            cube("Distant column", ((j-2)*1.15, 1.4, 0.9), (0.12,0.12,1.9), stone, 0.02)
    else:
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
else:
    # Rotate through distinct technical metaphors so adjacent scenes do not repeat one hero object.
    variant = index % 4
    if variant == 0:
        # Semantic-vector field: points in a searchable spatial cloud.
        for j in range(15):
            a = j * math.tau / 15
            radius = 0.75 + (j % 4) * 0.34
            x, y = math.cos(a) * radius, math.sin(a) * radius
            z = 0.65 + (j % 5) * 0.36
            sphere("Embedding point", (x, y, z), (0.09, 0.09, 0.09), glow if j % 3 == 0 else steel)
            if j:
                prev = (math.cos((j-1)*math.tau/15)*(0.75+((j-1)%4)*0.34),
                        math.sin((j-1)*math.tau/15)*(0.75+((j-1)%4)*0.34),
                        0.65+((j-1)%5)*0.36)
                midpoint = ((x+prev[0])/2, (y+prev[1])/2, (z+prev[2])/2)
                edge = cube("Vector relation", midpoint, (0.025, 0.025, (Vector((x,y,z))-Vector(prev)).length), accent, 0)
                edge.rotation_euler = (Vector((x,y,z))-Vector(prev)).to_track_quat("Z","Y").to_euler()
        cylinder("Vector field plinth", (0, 0, 0.12), 1.7, 0.22, navy)
    elif variant == 1:
        # Exact-match index: searchable drawers and one highlighted record.
        for row in range(4):
            for col in range(3):
                x, z = (col-1)*0.95, 0.65 + row*0.52
                highlighted = row == 2 and col == 1
                cube("Index record", (x, 0, z), (0.78, 0.46, 0.38),
                     glow if highlighted else navy, 0.06)
                cube("Record key", (x, -0.25, z), (0.42, 0.025, 0.045),
                     gold if highlighted else steel, 0.01)
        torus("Index halo", (0, 0.3, 1.6), 1.7, 0.025, glow)
    elif variant == 2:
        # Hybrid retrieval pipeline: keyword and semantic paths merge into one result.
        for j, x in enumerate((-1.7, -0.85, 0, 0.85, 1.7)):
            z = 0.85 + (j % 2) * 0.7
            cube("Pipeline module", (x, 0, z), (0.62, 0.5, 0.58),
                 gold if j in (0, 1) else glow, 0.09)
            sphere("Pipeline indicator", (x, -0.31, z), (0.11, 0.05, 0.11), steel if j != 4 else gold)
        for y in (-0.5, 0.5):
            cylinder("Signal column", (-0.85, y, 1.55), 0.07, 1.2, accent, 20)
            cylinder("Signal column", (0.85, y, 1.55), 0.07, 1.2, glow, 20)
    else:
        # A recognizable AI compute core, reserved for every fourth technical scene.
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
for j in range(5):
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
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.resolution_x, scene.render.resolution_y = 360, 640
scene.render.resolution_percentage = 100
scene.render.image_settings.color_depth = "8"
scene.render.film_transparent = False
scene.camera.data.lens = 55
scene.render.fps = 12
scene.frame_start = 1
scene.frame_end = max(24, int(shot_seconds * scene.render.fps))
scene.render.filepath = str(Path(output_path).resolve())

# Real 3D animation: hero geometry has subtle independent motion, while the camera
# pushes and arcs through the set. This is rendered frame-by-frame, not a still-image zoom.
start_frame, end_frame = scene.frame_start, scene.frame_end
for obj in list(scene.objects):
    if obj.type in {"MESH", "CURVE", "FONT"}:
        base_loc = obj.location.copy()
        base_rot = obj.rotation_euler.copy()
        obj.location.z = base_loc.z - 0.035
        obj.rotation_euler.z = base_rot.z - 0.035
        obj.keyframe_insert(data_path="location", frame=start_frame)
        obj.keyframe_insert(data_path="rotation_euler", frame=start_frame)
        obj.location = base_loc
        obj.rotation_euler = base_rot
        obj.keyframe_insert(data_path="location", frame=(start_frame + end_frame)//2)
        obj.location.z = base_loc.z + 0.055
        obj.rotation_euler.z = base_rot.z + (0.11 if index % 2 == 0 else -0.11)
        obj.keyframe_insert(data_path="location", frame=end_frame)
        obj.keyframe_insert(data_path="rotation_euler", frame=end_frame)

camera = scene.camera
camera_start = camera.location.copy()
camera.rotation_euler = (Vector((0,0,1.25))-camera.location).to_track_quat("-Z","Y").to_euler()
camera.keyframe_insert(data_path="location", frame=start_frame)
camera.keyframe_insert(data_path="rotation_euler", frame=start_frame)
camera.location.x += 0.32 if index % 2 == 0 else -0.32
camera.location.z += 0.12
camera.rotation_euler = (Vector((0,0,1.35))-camera.location).to_track_quat("-Z","Y").to_euler()
camera.keyframe_insert(data_path="location", frame=end_frame)
camera.keyframe_insert(data_path="rotation_euler", frame=end_frame)
for action in bpy.data.actions:
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "BEZIER"
scene.render.filepath = str(Path(output_path).resolve())
bpy.ops.render.render(animation=True)
