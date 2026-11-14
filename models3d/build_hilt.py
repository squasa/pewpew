"""Build a 3D lightsaber hilt in Blender; render:
  assets/hilt_side.png   transparent ortho side view (app sprite, emitter up)
  models3d/hilt_beauty.png  3/4 studio shot with blade ignited
  models3d/hilt.blend + hilt.glb
Run: blender -b --factory-startup --python-exit-code 1 -P models3d/build_hilt.py
"""
import sys
from pathlib import Path

import bpy

SKILL_SCRIPTS = "/Users/rmclol/.local/share/muse/skills/bundled/muse-core--exact-minimal-literal-tests~v1/skills/blender/scripts"
sys.path.insert(0, SKILL_SCRIPTS)
import bpy_helpers as H  # noqa: E402

ROOT = Path(__file__).parent.parent
OUT3D = ROOT / "models3d"
ASSETS = ROOT / "assets"
OUT3D.mkdir(exist_ok=True)
ASSETS.mkdir(exist_ok=True)

H.reset_scene()

steel = H.material_preset("brushed steel", "brushed_metal", "#B8BCC2", scale=10)
dark_steel = H.material("dark steel", "#3A3E44", roughness=0.35, metallic=1.0)
black_metal = H.material("black metal", "#17181A", roughness=0.45, metallic=0.9)
rubber = H.material_preset("grip rubber", "rubber", "#1D1E20", scale=10)
gold = H.material_preset("brass accent", "brass", "#C9963C", scale=10)
red_btn = H.material("red button", "#A01822", roughness=0.3, metallic=0.2)

hilt = []

def add(obj):
    hilt.append(obj)
    return obj

# --- hilt along +Z, pommel at z=0, emitter top ~z=0.256 (blade dir +Z) ---
add(H.add_lathe("pommel", [(0.001, 0.0), (0.015, 0.0), (0.019, 0.004),
                           (0.019, 0.018), (0.017, 0.023)], mat=dark_steel))
add(H.add_cylinder("grip", 0.0175, 0.122, location=(0, 0, 0.084), mat=rubber))
for i in range(6):  # grip rings
    z = 0.036 + i * 0.019
    add(H.add_torus(f"grip_ring_{i}", 0.0174, 0.0021, location=(0, 0, z), mat=dark_steel))
add(H.add_cylinder("body", 0.019, 0.052, location=(0, 0, 0.171), mat=steel))
add(H.add_cylinder("gold_ring", 0.0202, 0.010, location=(0, 0, 0.193), mat=gold))
add(H.add_cylinder("neck", 0.0155, 0.018, location=(0, 0, 0.207), mat=black_metal))
add(H.add_lathe("emitter", [(0.0155, 0.214), (0.019, 0.225), (0.022, 0.240),
                            (0.023, 0.252), (0.0205, 0.257)], mat=dark_steel))
add(H.add_cylinder("emitter_mouth", 0.0125, 0.004, location=(0, 0, 0.2565), mat=black_metal))
# activation switch housing + button on the -Y (camera) side
add(H.add_box("switch_box", size=(0.013, 0.007, 0.030), location=(0, -0.0205, 0.170),
              mat=dark_steel, bevel=0.0015))
add(H.add_cylinder("switch_btn", 0.0038, 0.005, location=(0, -0.0245, 0.173),
                   rotation=(90, 0, 0), mat=red_btn))
add(H.add_cylinder("aux_btn", 0.0028, 0.004, location=(0, -0.0240, 0.160),
                   rotation=(90, 0, 0), mat=gold))
# emitter clamp screws (front)
for x in (-0.011, 0.011):
    add(H.add_cylinder("clamp_screw", 0.0022, 0.003, location=(x, -0.0215, 0.243),
                       rotation=(90, 0, 0), mat=steel))

# --- blade (beauty render only) ---
blade_glow = H.emission_material("blade glow", "#7FD4FF", 3.0)
blade_core = H.emission_material("blade core", "#FFFFFF", 6.0)
blade = [
    H.add_cylinder("blade_outer", 0.0115, 0.86, location=(0, 0, 0.257 + 0.43), mat=blade_glow),
    H.add_cylinder("blade_inner", 0.0070, 0.86, location=(0, 0, 0.257 + 0.43), mat=blade_core),
    H.add_sphere("blade_tip", 0.0115, location=(0, 0, 0.257 + 0.86), mat=blade_glow),
]

H.world_color("#232428", 0.6)
H.studio_lighting(target=hilt, key_azimuth=-40, key_elevation=45, intensity=1.0,
                  contrast=0.55, softness=0.5)

# --- sprite render: ortho side view, hilt only, transparent ---
cam_side = H.add_camera("cam_side", (0, -0.6, 0.128), (0, 0, 0.128), lens=50)
cam_side.data.type = "ORTHO"
cam_side.data.ortho_scale = 0.335
bpy.context.scene.camera = cam_side
for b in blade:
    b.hide_render = True
_floor = bpy.data.objects.get("Floor")  # shadow catcher pollutes sprite alpha
if _floor:
    _floor.hide_render = True
H.set_render(engine="CYCLES", resolution=(640, 640), samples=48, transparent=True,
             view_transform="Khronos PBR Neutral")
H.render_still(str(ASSETS / "hilt_side.png"))
print("rendered hilt_side.png")

# --- beauty render: 3/4 view, blade ignited, dark backdrop ---
for b in blade:
    b.hide_render = False
if _floor:
    _floor.hide_render = False
cam_beauty = H.add_camera("cam_beauty", (0.85, -1.15, 0.62), (0, 0, 0.52), lens=48)
bpy.context.scene.camera = cam_beauty
H.world_color("#0B0C10", 0.35)
H.set_render(engine="CYCLES", resolution=(720, 900), samples=64, transparent=False)
H.render_still(str(OUT3D / "hilt_beauty.png"))
print("rendered hilt_beauty.png")

# --- save + export (hilt only in GLB; blade stays as separate objects) ---
H.save_blend(str(OUT3D / "hilt.blend"))
bpy.ops.object.select_all(action="DESELECT")
for o in hilt:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT3D / "hilt.glb"), export_format="GLB",
                          use_selection=True)
print("saved hilt.blend + hilt.glb")
H.report()
