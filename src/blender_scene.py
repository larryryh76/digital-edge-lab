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

if "strawberry" in brief_text and ("10 letters" in brief_text or "laser" in brief_text or "sweeps" in brief_text):
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
elif ("straw" in brief_text and "berry" in brief_text and "laser" in brief_text):
    story_treatment = "three_token_blocks"
    # Match the narrated example: two chunks, not an arbitrary three-way split.
    for j,(word,x) in enumerate((("STRAW",-0.82),("BERRY",0.82))):
        obj=cube("Token block "+word,(x,0.0,1.65),(1.38,0.55,0.78),
                 copper if j==0 else token_cyan,0.09)
        obj.rotation_euler[1] = math.radians((-4,4)[j])
        block_label(word,x,1.67,0.22)
        torus("Token edge ring "+str(j),(x,-0.30,1.65),0.47,0.018,glow)
    laser_obj=cube("Vertical cyan split laser",(0,-0.42,1.65),(0.035,0.045,1.25),glow,0.008)
elif ("straw" in brief_text and any(k in brief_text for k in ("block", "token", "split", "separate"))
      and not any(k in brief_text for k in ("misaligned", "snap back", "gaps", "token gap", "sparks"))):
    story_treatment = "three_token_blocks"
    for j,(word,x) in enumerate((("[STRAW]",-1.22),("[BER]",0.0),("[RY]",1.22))):
        obj=cube("Token block "+word,(x,0.0,1.65),(1.02,0.55,0.78),
                 copper if j==0 else token_cyan,0.09)
        obj.rotation_euler[1] = math.radians((-7,3,8)[j])
        block_label(word,x,1.67,0.20)
        torus("Token edge ring "+str(j),(x,-0.30,1.65),0.39,0.018,glow)
elif "38221" in brief_text or "token id" in brief_text:
    story_treatment = "token_id_cube_reveal"
    hero_focus=cube("Token ID cube",(0,0,1.65),(1.55,1.15,1.25),token_cyan,0.12)
    label("38221",(0,-0.59,1.56),0.42,ivory)
    cylinder("Token pedestal",(0,0.05,0.48),1.0,0.22,steel)
    for j in range(8):
        a=j*math.tau/8
        sphere("Cube orbit particle",(1.35*math.cos(a),0.2,1.65+1.35*math.sin(a)),
               (0.045,0.045,0.045),glow)
elif "token library" in brief_text or "massive grid" in brief_text:
    story_treatment = "token_library_grid"
    for row in range(4):
        for col in range(5):
            x=(col-2)*0.72
            z=0.75+row*0.52
            obj=cube("Library token "+str(row)+"-"+str(col),(x,0.55+row*0.22,z),
                     (0.48,0.32,0.34),token_cyan if (row+col)%4==0 else copper,0.045)
            if row==1 and col==2:
                label("TOKEN",(x,-0.05,z),0.12,ivory)
    ring=torus("Library scanning lens",(0,-0.15,1.65),1.1,0.06,glow)
    ring.rotation_euler[0]=math.radians(90)
elif "magnifying glass" in brief_text or "no letters inside" in brief_text:
    story_treatment = "magnifying_lens_cutaway"
    hero_focus=cube("Berry token block",(0,0,1.45),(1.5,0.55,0.8),token_cyan,0.09)
    block_label("BERRY",0,1.45,0.24)
    ring=torus("Magnifying glass lens",(0.2,-0.45,1.62),0.72,0.075,glow)
    ring.rotation_euler[0]=math.radians(90)
    cylinder("Lens handle",(0.75,-0.43,0.9),0.065,0.8,steel)
    cylinder("Lens pedestal",(0,0.1,0.25),1.05,0.2,navy)
    for j in range(7):
        sphere("Abstract subword particle",((j-3)*0.22,-0.52,1.5+(j%2)*0.12),
               (0.055,0.055,0.055),gold if j%2 else glow)
elif (("balance scale" in brief_text or "alphabet beads" in brief_text)
      and "16-bit" not in brief_text
      and not ("floating-point" in brief_text and "weights" in brief_text)):
    # Precision-weight scenes take precedence when a generated brief mentions both
    # a balance metaphor and the explicit high-precision sphere treatment.
    story_treatment = "token_vs_letters_balance"
    cylinder("Scale base",(0,0,0.18),0.72,0.25,steel)
    cylinder("Scale stem",(0,0,1.0),0.09,1.65,gold)
    cylinder("Scale crossbar",(0,0,1.8),0.055,3.2,gold)
    for side in (-1,1):
        x=side*1.05
        cylinder("Scale chain",(x,0,1.42),0.025,0.75,steel)
        cylinder("Scale pan",(x,0,1.02),0.48,0.07,steel)
    for j in range(8):
        x=-1.25+(j%4)*0.17
        z=1.15+(j//4)*0.12
        sphere("Alphabet bead",(x,-0.08,z),(0.07,0.07,0.07),gold)
    cube("Single compressed token",(1.05,-0.03,1.23),(0.6,0.45,0.38),token_cyan,0.07)
    label("LETTERS",( -1.05,-0.55,0.65),0.16,ivory)
    label("TOKEN",(1.05,-0.55,0.65),0.16,ivory)
elif "re-assembles" in brief_text or "flickers between 2 and 3" in brief_text or "blind spot" in brief_text:
    story_treatment = "strawberry_count_reveal"
    for j,(word,x) in enumerate((("STRAW",-0.95),("BERRY",0.95))):
        cube("Reassembled token "+word,(x,0,1.5),(1.45,0.5,0.7),copper if j==0 else token_cyan,0.08)
        block_label(word,x,1.5,0.22)
    label("2  /  3",(0,-0.55,2.5),0.48,ivory)
    laser_obj=cube("Counter glitch spark",(0,-0.48,2.05),(0.85,0.035,0.035),spark_mat,0.005)
elif ("phone" in brief_text or "smartphone" in brief_text) and any(k in brief_text for k in ("massive", "crushing", "heavy", "too big")):
    story_treatment = "phone_overloaded_by_model_cube"
    # Oversized model weight visibly dwarfs a phone: scale contrast is the story.
    phone = cube("Smartphone frame",(0,0.12,0.42),(1.15,0.20,2.15),steel,0.12)
    cube("Phone glass screen",(0,-0.015,0.44),(0.98,0.035,1.92),navy,0.07)
    hero_focus = cube("Oversized circuit model cube",(0,-0.12,2.55),(2.35,1.15,1.35),navy,0.12)
    for j in range(4):
        cube("Glowing cube circuit trace",(-0.75+j*0.5,-0.72,2.58),(0.025,0.025,0.75),glow,0.005)
    label("TOO LARGE FOR PHONE",(0,-0.76,1.55),0.16,ivory)
    # The weight descends toward the phone during the shot.
    hero_focus.location.z += 0.48
    hero_focus.keyframe_insert(data_path="location",frame=1)
    hero_focus.location.z -= 0.48
    hero_focus.keyframe_insert(data_path="location",frame=max(24,int(shot_seconds*12)))
elif "16-bit" in brief_text or ("floating-point" in brief_text and "weights" in brief_text):
    story_treatment = "high_precision_weight_sphere"
    hero_focus = sphere("High precision glass weight sphere",(0,0,1.75),(0.98,0.98,0.98),token_cyan)
    hero_focus.data.materials.clear()
    apply_mat(hero_focus, material("Optical glass weight", (0.13,0.42,0.68), 0.45, 0.12, 0.2))
    for j in range(28):
        a=j*math.tau/28
        x=1.02*math.cos(a); z=1.75+1.02*math.sin(a)
        sphere("Floating precision coordinate",(x,-0.12,z),(0.035,0.035,0.035),gold if j%4==0 else glow)
    for j in range(5):
        label(str((j+1)*3277),(0.0,-0.98,0.65+j*0.24),0.11,ivory)
elif ("4-bit" in brief_text or "coarse" in brief_text or "stepped" in brief_text) and "sphere" in brief_text:
    story_treatment = "quantized_grid_sphere"
    # Discrete brass blocks approximate a sphere, contrasting with continuous precision.
    for row in range(5):
        z=0.65+row*0.43
        half_width=[1,2,3,2,1][row]
        for col in range(half_width):
            x=(col-(half_width-1)/2)*0.48
            cube("Quantized brass sphere cell",(x,0.0,z),(0.43,0.43,0.38),gold,0.035)
    for x in (-1.05,-0.55,0,0.55,1.05):
        cube("Quantization grid line",(x,-0.27,1.55),(0.018,0.025,2.15),glow,0.003)
    hero_focus=sphere("Coarse grid center marker",(0,-0.34,1.55),(0.13,0.08,0.13),glow)
elif ("laser" in brief_text or "beam" in brief_text) and any(k in brief_text for k in ("decimal", "gear", "integer", "rounding", "15-step")):
    story_treatment = "decimal_rounding_gear_track"
    for j in range(12):
        a=j*math.tau/12
        x=1.1*math.cos(a); z=1.45+1.1*math.sin(a)
        tooth=cube("Brass rounding gear tooth",(x,0.05,z),(0.34,0.38,0.18),gold,0.025)
        tooth.rotation_euler[1]=-a
    torus("Notched gear track",(0,0.04,1.45),0.86,0.11,steel)
    hero_focus=cylinder("Integer rounding dial",(0,-0.25,1.45),0.57,0.2,navy)
    for j in range(15):
        a=j*math.tau/15
        sphere("Discrete integer marker",(0.72*math.cos(a),-0.28,1.45+0.72*math.sin(a)),
               (0.045,0.045,0.045),glow if j%3==0 else copper)
    laser_obj=cube("Decimal-to-integer laser",( -1.5,-0.48,1.45),(1.2,0.035,0.035),glow,0.006)
elif ("memory block" in brief_text or "memory" in brief_text) and any(k in brief_text for k in ("collapses", "reducing", "volume", "three-quarters", "75%")):
    story_treatment = "memory_volume_compression"
    hero_focus=cube("Oversized blue memory volume",(0,0,1.65),(2.15,1.0,1.8),token_cyan,0.12)
    for j in range(4):
        cube("Memory volume data stripe",(-0.72+j*0.48,-0.53,1.65),(0.025,0.025,1.3),glow,0.005)
    cube("Compressed gold micro-cube",(0,-0.75,1.65),(0.56,0.42,0.56),gold,0.06)
    label("75% LESS",(0,-0.78,0.78),0.19,ivory)
    hero_focus.scale=(2.15,1.0,1.8)
    hero_focus.keyframe_insert(data_path="scale",frame=1)
    hero_focus.scale=(0.62,0.48,0.58)
    hero_focus.keyframe_insert(data_path="scale",frame=max(24,int(shot_seconds*12)))
elif ("motherboard" in brief_text or "smartphone" in brief_text or "phone frame" in brief_text) and any(k in brief_text for k in ("socket", "local speed", "energy pulse", "device")):
    story_treatment = "phone_socket_hero_reveal"
    cube("Glass smartphone body",(0,0.12,1.35),(1.45,0.25,2.65),steel,0.16)
    cube("Smartphone screen",(0,-0.025,1.35),(1.28,0.035,2.42),navy,0.09)
    hero_focus=cube("Central motherboard socket",(0,-0.11,1.5),(0.72,0.18,0.72),gold,0.07)
    for j in range(8):
        a=j*math.tau/8
        x=0.52*math.cos(a); z=1.5+0.52*math.sin(a)
        cube("Socket contact",(x,-0.24,z),(0.08,0.035,0.08),glow,0.01)
    for radius in (0.85,1.08,1.32):
        torus("Device energy pulse",(0,-0.28,1.5),radius,0.018,glow).rotation_euler[0]=math.radians(90)
elif ("invisible wall" in brief_text or "scatters into" in brief_text) and any(k in brief_text for k in ("laser", "beam")):
    story_treatment = "blocked_reverse_signal"
    cube("Source block B",(-1.05,0.0,1.45),(0.9,0.65,0.75),copper,0.08)
    cube("Destination block A",(1.05,0.0,1.45),(0.9,0.65,0.75),token_cyan,0.08)
    block_label("B",-1.05,1.43,0.32)
    block_label("A",1.05,1.43,0.32)
    cube("Invisible wall barrier",(0,-0.12,1.5),(0.08,0.08,1.55),glow,0.01)
    laser_obj=cube("Rejected reverse laser",(0.0,-0.38,1.5),(1.25,0.035,0.035),spark_mat,0.006)
    for j in range(12):
        a=j*math.tau/12
        sphere("Reverse signal spark",(0.2*math.cos(a),-0.45,1.5+0.2*math.sin(a)),
               (0.045,0.045,0.045),gold if j%2 else spark_mat)
    label("REVERSE BLOCKED",(0,-0.55,2.55),0.19,ivory)
elif ("block" in brief_text and any(k in brief_text for k in ("laser beam", "laser"))) and any(k in brief_text for k in ("shoots from a to b", "from a to b", "tracks the beam", "travels from a to b")):
    story_treatment = "directed_relation_blocks"
    cube("Block A",( -1.05,0.0,1.45),(0.95,0.68,0.78),copper,0.08)
    cube("Block B",(1.05,0.0,1.45),(0.95,0.68,0.78),token_cyan,0.08)
    block_label("A",-1.05,1.43,0.32)
    block_label("B",1.05,1.43,0.32)
    laser_obj=cube("Forward cyan laser",(0,-0.4,1.5),(2.0,0.035,0.035),glow,0.006)
    label("A TO B",(0,-0.55,2.25),0.2,ivory)
elif "glass slabs" in brief_text and any(k in brief_text for k in ("tom cruise", "mary lee", "light pulse", "opaque black")):
    story_treatment = "two_slab_information_barrier"
    left=cube("Tom name glass slab",(-1.0,0.0,1.65),(0.82,0.18,1.85),token_cyan,0.07)
    right=cube("Mary name glass slab",(1.0,0.0,1.65),(0.82,0.18,1.85),steel,0.07)
    block_label("TOM", -1.0,1.62,0.22)
    block_label("MARY",1.0,1.62,0.22)
    laser_obj=sphere("Information pulse",(-1.55,-0.38,1.65),(0.12,0.08,0.12),spark_mat)
    for j in range(4):
        cube("Slab data etching",(-1.0+j*0.12,-0.12,0.95),(0.025,0.025,0.55),glow,0.003)
    label("ONE-WAY ASSOCIATION",(0,-0.45,2.85),0.17,ivory)
elif "neural network node" in brief_text or ("network node" in brief_text and "sphere" in brief_text):
    story_treatment = "neural_node_data_flow"
    hero_focus=sphere("Neural network node",(0,0,1.65),(0.72,0.72,0.72),steel)
    for j in range(6):
        a=j*math.tau/6
        torus("Cyan node vein",(0,0,1.65),0.77,0.025,glow).rotation_euler=(a,0,a*0.5)
        sphere("Network connector",(1.35*math.cos(a),0.1,1.65+1.35*math.sin(a)),
               (0.13,0.13,0.13),token_cyan)
    laser_obj=sphere("Liquid gold data packet",(-1.25,-0.18,1.65),(0.11,0.11,0.11),gold)
elif ("digital library" in brief_text or "shelves" in brief_text) and "book" in brief_text:
    story_treatment = "digital_library_book_reveal"
    for row in range(3):
        for col in range(4):
            x=(col-1.5)*0.78
            z=0.75+row*0.78
            cube("Library shelf",(x,0.65,z),(0.08,0.45,0.68),steel,0.02)
            cube("Library volume",(x+0.23,0.35,z),(0.27,0.22,0.58),copper if (row==1 and col==2) else navy,0.025)
    hero_focus=cube("Flying highlighted book",(0,-0.45,1.75),(0.8,0.12,0.95),gold,0.04)
    cube("Blank book page",(-0.2,-0.54,1.75),(0.32,0.025,0.72),ivory,0.01)
    cube("Text-filled cyan page",(0.2,-0.54,1.75),(0.32,0.025,0.72),token_cyan,0.01)
    for j in range(5):
        cube("Glowing page line",(0.2,-0.56,1.48+j*0.12),(0.22,0.012,0.012),glow,0.002)
elif "compass" in brief_text and "needle" in brief_text:
    story_treatment = "directional_compass_reveal"
    cylinder("Compass brass housing",(0,0,1.35),1.0,0.22,gold)
    cylinder("Compass midnight dial",(0,-0.13,1.35),0.88,0.05,navy)
    torus("Compass rim",(0,-0.17,1.35),0.88,0.045,steel)
    hero_focus=cube("Compass needle",(0,-0.23,1.42),(1.25,0.045,0.075),glow,0.02)
    cube("Compass needle tail",( -0.42,-0.25,1.42),(0.36,0.05,0.09),copper,0.02)
    label("BACKWARD",(0,-0.34,0.3),0.15,ivory)
    label("FORWARD",(0,-0.34,2.35),0.15,glow)
elif ("second" in brief_text and "wire" in brief_text and any(k in brief_text for k in ("connecting b back to a", "circuit glows", "snaps into place"))):
    story_treatment = "bidirectional_circuit_reveal"
    cube("Circuit block A",(-1.2,0.0,1.45),(0.85,0.62,0.72),copper,0.08)
    cube("Circuit block B",(1.2,0.0,1.45),(0.85,0.62,0.72),token_cyan,0.08)
    block_label("A",-1.2,1.43,0.3)
    block_label("B",1.2,1.43,0.3)
    cube("Forward cyan wire",(0,-0.28,1.72),(2.4,0.035,0.035),glow,0.005)
    laser_obj=cube("Returning gold wire",(0,-0.35,1.22),(2.4,0.045,0.045),gold,0.005)
    label("TWO-WAY LINK",(0,-0.55,2.35),0.2,ivory)
elif any(k in brief_text for k in ("4921","serial number","macro shot")):
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
elif "3.14159" in brief_text or "decimal" in brief_text or " pi " in (" " + brief_text + " "):
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
if story_treatment in {"directed_relation_blocks", "blocked_reverse_signal", "two_slab_information_barrier",
                        "neural_node_data_flow", "digital_library_book_reveal", "directional_compass_reveal",
                        "bidirectional_circuit_reveal", "phone_overloaded_by_model_cube",
                        "high_precision_weight_sphere", "quantized_grid_sphere",
                        "decimal_rounding_gear_track", "memory_volume_compression", "phone_socket_hero_reveal",
                        "copper_strawberry_word_laser", "three_token_blocks",
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

if story_treatment in {"phone_overloaded_by_model_cube", "high_precision_weight_sphere",
                        "quantized_grid_sphere", "decimal_rounding_gear_track",
                        "memory_volume_compression", "phone_socket_hero_reveal",
                        "copper_strawberry_word_laser", "three_token_blocks",
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
    "directed_relation_blocks", "blocked_reverse_signal", "two_slab_information_barrier",
    "neural_node_data_flow", "digital_library_book_reveal", "directional_compass_reveal",
    "bidirectional_circuit_reveal", "phone_overloaded_by_model_cube",
    "high_precision_weight_sphere", "quantized_grid_sphere",
    "decimal_rounding_gear_track", "memory_volume_compression", "phone_socket_hero_reveal",
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
# Treatment-specific action: precision is shown as a continuous optical mass,
# with the sphere rotating and expanding while its coordinate markers sweep around it.
if story_treatment == "high_precision_weight_sphere" and hero_focus is not None:
    hero_focus.rotation_euler = (0.0, 0.0, 0.0)
    hero_focus.scale = (0.88, 0.88, 0.88)
    hero_focus.keyframe_insert(data_path="rotation_euler", frame=start_frame)
    hero_focus.keyframe_insert(data_path="scale", frame=start_frame)
    hero_focus.rotation_euler.z = math.tau * 0.72
    hero_focus.rotation_euler.x = math.radians(24)
    hero_focus.scale = (1.08, 1.08, 1.08)
    hero_focus.keyframe_insert(data_path="rotation_euler", frame=(start_frame + end_frame)//2)
    hero_focus.keyframe_insert(data_path="scale", frame=(start_frame + end_frame)//2)
    hero_focus.rotation_euler.z = math.tau * 1.4
    hero_focus.rotation_euler.x = math.radians(-18)
    hero_focus.scale = (0.96, 0.96, 0.96)
    hero_focus.keyframe_insert(data_path="rotation_euler", frame=end_frame)
    hero_focus.keyframe_insert(data_path="scale", frame=end_frame)
    for marker in [o for o in scene.objects if o.name.startswith("Floating precision coordinate")]:
        origin = marker.location.copy()
        marker.keyframe_insert(data_path="location", frame=start_frame)
        marker.location.x = origin.x * math.cos(math.radians(65)) + (origin.z - 1.75) * math.sin(math.radians(65))
        marker.location.z = 1.75 - origin.x * math.sin(math.radians(65)) + (origin.z - 1.75) * math.cos(math.radians(65))
        marker.keyframe_insert(data_path="location", frame=(start_frame + end_frame)//2)
        marker.location.x = -origin.x
        marker.location.z = 3.5 - origin.z
        marker.keyframe_insert(data_path="location", frame=end_frame)
for action in bpy.data.actions:
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "BEZIER"
scene.render.filepath = str(Path(output_path).resolve().with_suffix(""))
# Emit a small machine-readable trace to make the visual treatment auditable.
Path(output_path).with_name(Path(output_path).stem + ".visual.json").write_text(
    json.dumps({"scene_index": index, "treatment": story_treatment,
                "hero_object": hero_focus.name if hero_focus else None,
                "laser_action": bool(laser_obj),
                "treatment_specific_subject_animation": story_treatment == "high_precision_weight_sphere",
                "brief": brief.get("visual", "")}, indent=2),
    encoding="utf-8")
bpy.ops.render.render(animation=True)
