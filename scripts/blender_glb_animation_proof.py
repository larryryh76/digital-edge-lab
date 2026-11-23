#!/usr/bin/env python3
"""Blender GLB rig/action import proof renderer. Run with Blender -- <GLB> <output.mp4>."""
from pathlib import Path
import json, sys, bpy
from mathutils import Vector

args=sys.argv[sys.argv.index("--")+1:]
if len(args)!=2: raise SystemExit("expected input GLB and output MP4")
source,output=map(Path,args)
if not source.is_file(): raise SystemExit(f"GLB not found: {source}")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
rigs=[o for o in bpy.context.scene.objects if o.type=="ARMATURE"]
actions=[a for a in bpy.data.actions if a.frame_range[1]>a.frame_range[0]]
if not rigs: raise SystemExit("GLB import yielded no armature")
if not actions: raise SystemExit("GLB import yielded no actions; motionless asset rejected")
rig=max(rigs,key=lambda o:len(o.pose.bones))
action=max(actions,key=lambda a:a.frame_range[1]-a.frame_range[0])
rig.animation_data_create(); rig.animation_data.action=action

# Verify the imported action changes evaluated pose transforms, not just that an
# Action datablock exists. Sample the whole clip at bounded intervals.
def pose_motion_trace(armature, first, last, max_samples=48):
    span=max(1,last-first)
    count=min(max_samples,span+1)
    frames=sorted(set(int(round(first+i*span/max(1,count-1))) for i in range(count)))
    per_bone={}
    scene=bpy.context.scene
    for bone in armature.pose.bones:
        translations=[]; rotations=[]
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            matrix=bone.matrix.copy()
            translations.append(matrix.translation.copy())
            rotations.append(matrix.to_quaternion().copy())
        displacement=max((a-b).length for a in translations for b in translations)
        angular=max((a.rotation_difference(b).angle for a in rotations for b in rotations),default=0.0)
        per_bone[bone.name]={"max_translation":float(displacement),"max_rotation_radians":float(angular)}
    scene.frame_set(first); bpy.context.view_layer.update()
    best=max(per_bone.items(),key=lambda item:max(item[1]["max_translation"],item[1]["max_rotation_radians"]),default=(None,{}))
    return {"sampled_frames":frames,"bone_count":len(per_bone),"most_moving_bone":best[0],
            "max_translation":best[1].get("max_translation",0.0),
            "max_rotation_radians":best[1].get("max_rotation_radians",0.0),
            "bones":per_bone}

motion_trace=pose_motion_trace(rig,start,end)
if motion_trace["max_translation"] < 0.01 and motion_trace["max_rotation_radians"] < 0.05:
    raise SystemExit("selected GLB action does not visibly animate any rig bone; rejected")
start,end=map(int,action.frame_range); end=max(start+2,end)
bpy.context.view_layer.update()
mesh_objs=[o for o in bpy.context.scene.objects if o.type=="MESH"]
verts=[o.matrix_world @ Vector(c) for o in mesh_objs for c in o.bound_box]
if not verts: raise SystemExit("Imported GLB has no mesh geometry")
zmin,zmax=min(v.z for v in verts),max(v.z for v in verts)
height=max(zmax-zmin,0.01); factor=3.0/height
rig.scale=(factor,)*3; rig.location.z=-zmin*factor
bpy.context.view_layer.update()
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-0.04))
bpy.context.object.name="ProofGround"
def aim(obj,point): obj.rotation_euler=(Vector(point)-obj.location).to_track_quat("-Z","Y").to_euler()
world=bpy.data.worlds.new("ProofWorld"); bpy.context.scene.world=world; world.use_nodes=True
world.node_tree.nodes["Background"].inputs[0].default_value=(0.025,0.03,0.04,1)
world.node_tree.nodes["Background"].inputs[1].default_value=0.6
bpy.ops.object.camera_add(location=(6,-9,4.5)); cam=bpy.context.object; aim(cam,(0,0,1.4)); cam.data.lens=45; bpy.context.scene.camera=cam
for loc,power,size in [((4,-4,7),900,5),((-4,-1,4),650,4),((0,5,5),800,3)]:
 bpy.ops.object.light_add(type="AREA",location=loc); l=bpy.context.object; l.data.energy=power; l.data.shape="DISK"; l.data.size=size; aim(l,(0,0,1.4))
scene=bpy.context.scene
try: scene.render.engine="BLENDER_EEVEE_NEXT"
except: scene.render.engine="BLENDER_EEVEE"
scene.render.resolution_x=540; scene.render.resolution_y=960; scene.render.resolution_percentage=100; scene.render.fps=24
scene.frame_start=start; scene.frame_end=min(end,start+120)
scene.render.image_settings.file_format="FFMPEG"; scene.render.ffmpeg.format="MPEG4"; scene.render.ffmpeg.codec="H264"; scene.render.ffmpeg.constant_rate_factor="MEDIUM"; scene.render.filepath=str(output.with_suffix(""))
scene.view_settings.view_transform="AgX"; scene.frame_set(start); bpy.ops.render.render(animation=True)
report={"status":"proof_rendered","source_glb":str(source),"armatures":[o.name for o in rigs],"selected_rig":rig.name,"selected_action":action.name,"action_frame_range":[start,end],"render_frame_range":[scene.frame_start,scene.frame_end],"evaluated_rig_motion":motion_trace,"output":str(output)}
output.with_suffix(".json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report,indent=2))
