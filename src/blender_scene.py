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

# Interpret each generated brief into a concrete, distinct 3D story treatment.
# Each branch creates named, inspectable hero objects; generic network geometry is only fallback.
story_treatment = "technical_fallback"
laser_obj = None
hero_focus = None
copper = material("Brushed warm copper", (0.62, 0.27, 0.095), 0.88, 0.22)
ivory = material("Warm ivory typography", (0.92, 0.94, 0.98), 0.05, 0.32, 0.15)
token_cyan = material("Token cyan enamel", (0.025, 0.46, 0.78), 0.62, 0.2, 0.35)
spark_mat = material("Laser sparks", (0.15, 0.78, 1.0), 0.15, 0.16, 3.0)

def label(body, loc, size, mat=ivory):
    obj = text_obj(body, loc, size, mat)
    obj.name = "Hero label: " + body[:24]
    return obj

def block_label(body, x, z, size=0.22):
    return label(body, (x, -0.315, z), size, ivory)

if "strawberry" in brief_text and ("laser" in brief_text or "sweeps" in brief_text):
    story_treatment = "copper_strawberry_word_laser"
    # A large, legible, extruded copper word is the hero—not a network visualization.
    hero_focus = label("STRAWBERRY", (0, -0.55, 2.05), 0.48, copper)
    hero_focus.data.extrude = 0.035
    hero_focus.data.bevel_depth = 0.008
    hero_focus.data.bevel_resolution = 2
    hero_focus.data.align_y = "CENTER"
    floor = cube("Reflective midnight plinth", (0, 0.1, 0.0), (7.5, 3.5, 0.22), navy, 0.12)
    cube("Copper word pedestal trim", (0, -0.05, 0.13), (5.8, 0.08, 0.025), gold, 0.01)
    # A bright horizontal laser bar visibly travels from left to right across the letters.
    laser_obj = cube("Cyan laser sweep", (-1.25, -0.78, 2.18), (2.35, 0.035, 0.035), glow, 0.008)
    laser_obj.name = "Cyan laser sweep"
    for j in range(18):
        sphere("Copper dust mote", ((j-9)*0.34, 0.45+(j%3)*0.13, 1.0+(j%5)*0.33),
               (0.025,0.025,0.025), gold if j%2 else token_cyan)
elif ("straw" in brief_text and any(k in brief_text for k in ("block", "token", "split", "separate"))
      and not any(k in brief_text for k in ("misaligned", "snap back", "gaps", "token gap", "sparks"))):
    story_treatment = "three_token_blocks"
    for j,(word,x) in enumerate((("[STRAW]",-1.22),("[BER]",0.0),("[RY]",1.22))):
        obj=cube("Token block "+word,(x,0.0,1.65),(1.02,0.55,0.78),
                 copper if j==0 else token_cyan,0.09)
        obj.rotation_euler[1] = math.radians((-7,3,8)[j])
        block_label(word,(x),1.67,0.20)
        torus("Token edge ring "+str(j),(x,-0.30,1.65),0.39,0.018,glow)
elif any(k in brief_text for k in ("4921","serial number","macro shot","etched")):
    story_treatment = "macro_serial_number_reveal"
    hero_focus=cube("Macro token ingot",(0,0,1.55),(2.7,0.75,1.35),copper,0.15)
    label("4921",(0,-0.405,1.43),0.68,glow)
    for j in range(5):
        cube("Ingot machining groove",(-0.95+j*0.48,-0.39,2.05),(0.018,0.025,0.15),gold,0.004)
    torus("Macro reveal halo",(0,0.2,1.55),1.65,0.025,token_cyan).rotation_euler[0]=math.radians(70)
elif "lens" in brief_text or "through the lens" in brief_text:
    story_treatment = "tokenization_lens_reveal"
    # The glass lens frames the transformation from a smooth sentence into chunky units.
    for j,(word,x) in enumerate((("THE", -1.45),("SENTENCE",-0.45),("CHANGES",0.75))):
        label(word,(x,-0.18,1.15+(j%2)*0.18),0.18,copper if j==1 else ivory)
    ring=torus("Oversized digital lens",(0,-0.25,1.7),1.08,0.075,glow)
    ring.rotation_euler[0]=math.radians(90)
    ring.scale=(1.0,1.0,1.0)
    for j in range(5):
        cube("Jagged token unit",(-1.55+j*0.75,-0.02,2.2+(j%2)*0.12),(0.58,0.38,0.34),token_cyan if j%2 else copper,0.045)
elif "3.14159" in brief_text or "pi" in brief_text or "decimal" in brief_text:
    story_treatment = "pi_sphere_compression"
    hero_focus=sphere("Pi metallic sphere",(0,0,1.8),(1.15,1.15,1.15),copper)
    label("3.14159",(0,-1.02,1.72),0.32,ivory)
    laser_obj=cube("Cyan compression beam",(-1.7,-0.1,1.8),(1.0,0.035,0.035),glow,0.006)
    for j in range(8):
        a=j*math.tau/8
        sphere("Pi orbit marker",(1.55*math.cos(a),0.25,1.8+1.55*math.sin(a)),
               (0.055,0.055,0.055),token_cyan)
elif any(k in brief_text for k in ("misaligned","snap back","gaps","token gap","sparks")):
    story_treatment = "misaligned_token_reassembly"
    for j,(word,x,z) in enumerate((("[STRAW]",-1.22,1.75),("[BER]",0.0,1.95),("[RY]",1.22,1.62))):
        obj=cube("Misaligned token "+word,(x,0,z),(1.0,0.52,0.7),copper if j==0 else token_cyan,0.08)
        obj.rotation_euler[1]=math.radians((-8,5,11)[j])
        block_label(word,x,z-0.02,0.19)
    for j in range(12):
        x=-0.75+j*0.14
        sphere("Gap spark",(x,-0.45,1.8+(j%3)*0.13),(0.035,0.035,0.035),spark_mat)
elif "logo" in brief_text or "digital edge lab" in brief_text or "perfect metallic cube" in brief_text:
    story_treatment = "brand_cube_reveal"
    hero_focus=cube("Digital Edge Lab hero cube",(0,0,1.65),(1.6,1.6,1.6),steel,0.1)
    torus("Brand orbit",(0,0.25,1.65),1.45,0.025,glow).rotation_euler[0]=math.radians(65)
    label("DIGITAL EDGE LAB",(0,-0.91,0.55),0.25,glow)
    label("EDGE / 001",(0,-0.86,2.3),0.17,ivory)
elif any(k in brief_text for k in ("sphere", "metallic cube", "compress", "cube")):
    story_treatment = "metallic_object_transformation"
    hero_focus=sphere("Metallic transformation sphere",(0,0,1.7),(0.95,0.95,0.95),copper)
    cube("Transformation destination",(1.2,0.1,1.7),(0.75,0.75,0.75),token_cyan,0.07)
    for j in range(8):
        a=j*math.tau/8
        sphere("Transformation particle",(1.45*math.cos(a),-0.15,1.7+1.45*math.sin(a)),
               (0.05,0.05,0.05),glow)
elif historical:
    if any(k in brief_text for k in ("socrates", "philosoph", "athens", "thinker")):
        story_treatment = "historical_philosopher_bust"
        cylinder("Pedestal", (0, 0.1, 0.15), 1.12, 0.3, stone)
        cylinder("Bronze pedestal rim", (0, 0.1, 0.33), 1.0, 0.06, gold)
        hero_focus=sphere("Philosopher head", (0, 0, 1.72), (0.68, 0.59, 0.82), stone)
        sphere("Beard", (0, -0.43, 1.22), (0.48, 0.23, 0.43), stone)
        for side in (-1, 1):
            sphere("Eye", (side*0.24, -0.535, 1.83), (0.07,0.035,0.045), gold)
        for j in range(5):
            cube("Library column", ((j-2)*1.05, 1.7, 1.1), (0.12,0.15,2.5), stone, 0.025)
    else:
        story_treatment = "historical_artifact"
        cylinder("Bust plinth", (0, 0.1, 0.15), 1.18, 0.32, stone)
        hero_focus=sphere("Historical artifact", (0,0,1.6),(0.75,0.6,0.9),steel)
        torus("Artifact halo", (0, 0.3, 1.58), 1.35, 0.025, gold)
else:
    variant = index % 4
    if variant == 0:
        story_treatment = "semantic_vector_field"
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
        story_treatment = "searchable_record_drawers"
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
        story_treatment = "hybrid_retrieval_modules"
        for j, x in enumerate((-1.7, -0.85, 0, 0.85, 1.7)):
            z = 0.85 + (j % 2) * 0.7
            cube("Pipeline module", (x, 0, z), (0.62, 0.5, 0.58),
                 gold if j in (0, 1) else glow, 0.09)
            sphere("Pipeline indicator", (x, -0.31, z), (0.11, 0.05, 0.11), steel if j != 4 else gold)
    else:
        story_treatment = "compute_core"
        cylinder("Reactor base", (0, 0, 0.08), 1.3, 0.24, navy)
        torus("Energy ring one", (0, 0, 1.2), 1.12, 0.045, glow).rotation_euler[0] = math.radians(62)
        torus("Energy ring two", (0, 0, 1.2), 1.38, 0.035, accent).rotation_euler[1] = math.radians(62)
        hero_focus=sphere("Core", (0, -0.04, 1.2), (0.42, 0.42, 0.42), glow)
# Background architectural ribs add parallax and cinematic depth.
for j in range(5):
    x = (j-4)*0.78
    cube("Backdrop rib", (x, 2.5, 1.5), (0.035,0.08,4.0), accent if j%3==0 else steel, 0.01)

# Floating title plaque; concise scene phrase is part of the set dressing.
title = str(brief.get("on_screen_text", brief.get("visual", "THE HIDDEN MECHANISM"))).strip()[:28]
if story_treatment in {"copper_strawberry_word_laser", "three_token_blocks",
                        "macro_serial_number_reveal", "tokenization_lens_reveal",
                        "pi_sphere_compression", "misaligned_token_reassembly",
                        "brand_cube_reveal"}:
    label(title, (0, -0.72, 3.05), 0.18, ivory)
else:
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

if story_treatment in {"copper_strawberry_word_laser", "three_token_blocks",
                        "macro_serial_number_reveal", "tokenization_lens_reveal",
                        "pi_sphere_compression", "misaligned_token_reassembly",
                        "brand_cube_reveal"}:
    camera_location, camera_target, lens = (0,-9.2,2.35), (0,0,1.75), 48
    if story_treatment == "macro_serial_number_reveal":
        camera_location, camera_target, lens = (0,-6.4,1.85), (0,0,1.55), 62
else:
    camera_location, camera_target, lens = (4.6,-9.5,4.2), (0,0,1.25), 48
bpy.ops.object.camera_add(location=camera_location)
camera = bpy.context.object
camera.rotation_euler = (Vector(camera_target)-camera.location).to_track_quat("-Z","Y").to_euler()
camera.data.lens = lens
scene.camera = camera
scene.render.image_settings.color_mode = "RGB"
scene.render.filepath = str(Path(output_path).resolve().with_suffix(""))
scene.camera.data.dof.use_dof = story_treatment not in {
    "copper_strawberry_word_laser", "three_token_blocks", "macro_serial_number_reveal",
    "tokenization_lens_reveal", "pi_sphere_compression", "misaligned_token_reassembly",
    "brand_cube_reveal"
}
scene.camera.data.dof.focus_object = hero_focus
scene.camera.data.dof.aperture_fstop = 5.6
scene.render.resolution_percentage = 100
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
scene.render.filepath = str(Path(output_path).resolve().with_suffix(""))

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
if laser_obj is not None:
    # The laser/beam has a deliberately visible travel path, not merely a static glow.
    start_x = -1.15 if story_treatment == "copper_strawberry_word_laser" else -1.6
    end_x = 1.15 if story_treatment == "copper_strawberry_word_laser" else 1.6
    laser_obj.location.x = start_x
    laser_obj.keyframe_insert(data_path="location", frame=start_frame)
    laser_obj.location.x = 0.0
    laser_obj.keyframe_insert(data_path="location", frame=(start_frame+end_frame)//2)
    laser_obj.location.x = end_x
    laser_obj.keyframe_insert(data_path="location", frame=end_frame)
for action in bpy.data.actions:
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "BEZIER"
scene.render.filepath = str(Path(output_path).resolve().with_suffix(""))
# Emit a small machine-readable trace to make the visual treatment auditable.
Path(output_path).with_name(Path(output_path).stem + ".visual.json").write_text(
    json.dumps({"scene_index": index, "treatment": story_treatment,
                "hero_object": hero_focus.name if hero_focus else None,
                "laser_action": bool(laser_obj), "brief": brief.get("visual", "")}, indent=2),
    encoding="utf-8")
bpy.ops.render.render(animation=True)
