import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

BLENDER = shutil.which('blender')
FFPROBE = shutil.which('ffprobe')
if not BLENDER or not FFPROBE:
    raise SystemExit('FAIL: blender and ffprobe are required for this smoke test')
script = r'''import bpy, math, sys
from mathutils import Vector
out = sys.argv[sys.argv.index('--') + 1]
s = bpy.context.scene
s.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items.keys() else 'BLENDER_EEVEE'
s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = 180, 320, 100
s.render.fps = 8
s.frame_start, s.frame_end = 1, 16
s.render.image_settings.file_format = 'FFMPEG'
s.render.ffmpeg.format = 'MPEG4'; s.render.ffmpeg.codec = 'H264'
s.render.filepath = str(__import__('pathlib').Path(out).with_suffix(''))
s.render.use_file_extension = True
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, location=(0,0,0))
o = bpy.context.object
o.keyframe_insert(data_path='location', frame=1); o.location.x = 1.0; o.keyframe_insert(data_path='location', frame=16)
bpy.ops.object.camera_add(location=(4,-7,3)); cam = bpy.context.object
cam.rotation_euler = (Vector((0,0,0))-cam.location).to_track_quat('-Z','Y').to_euler(); s.camera = cam
bpy.ops.object.light_add(type='AREA', location=(2,-3,4)); bpy.context.object.data.energy = 500
s.render.image_settings.color_mode = 'RGB'
bpy.ops.render.render(animation=True)
'''
with tempfile.TemporaryDirectory(prefix='del-blender-smoke-') as td:
    output = Path(td) / 'smoke.mp4'
    scene = Path(td) / 'smoke.py'
    scene.write_text(script, encoding='utf-8')
    started = time.monotonic()
    run = subprocess.run([BLENDER, '-b', '-t', '2', '--python', str(scene), '--', str(output)], capture_output=True, text=True, timeout=120)
    elapsed = time.monotonic() - started
    print(f'Blender smoke elapsed_seconds={elapsed:.2f} exit={run.returncode}')
    if run.returncode:
        print((run.stdout + run.stderr)[-8000:])
        raise SystemExit('FAIL: Blender smoke render process failed')
    import re
    suffix_pattern = re.compile(r"^" + re.escape(output.stem) + r"\d{4,6}-\d{4,6}\.mp4$")
    candidates = sorted(p for p in output.parent.glob(output.stem + "*.mp4")
                        if p.is_file() and (p == output or suffix_pattern.fullmatch(p.name)))
    print('Blender MP4 candidates:', [(p.name, p.stat().st_size) for p in candidates])
    if not output.exists() and len(candidates) == 1:
        # Same strict frame-range suffix normalization contract used by src/pipeline.py.
        candidates[0].replace(output)
    if not output.exists() or output.stat().st_size < 1000:
        print('Expected output:', str(output))
        print('Configured Blender filepath:', str(output.with_suffix('')))
        print('Blender stdout/stderr tail:\\n' + (run.stdout + run.stderr)[-12000:])
        print('All output files:', [(str(p), p.stat().st_size) for p in output.parent.rglob('*') if p.is_file()])
        raise SystemExit('FAIL: smoke MP4 missing or empty; see actual Blender output paths above')
    probe = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'stream=codec_type,codec_name,width,height,nb_frames,r_frame_rate', '-show_entries', 'format=duration', '-of', 'json', str(output)], capture_output=True, text=True, timeout=20)
    if probe.returncode:
        raise SystemExit('FAIL: ffprobe rejected smoke MP4: ' + probe.stderr[-1000:])
    data = json.loads(probe.stdout)
    streams = data.get('streams', [])
    video = [s for s in streams if s.get('codec_type') == 'video']
    if (not video or video[0].get('codec_name') != 'h264' or video[0].get('width') != 180 or video[0].get('height') != 320 or float(data['format']['duration']) < 1 or not video[0].get('nb_frames')):
        raise SystemExit('FAIL: smoke MP4 did not meet expected codec/duration')
    print('PASS: animated H.264 MP4 verified by ffprobe')
