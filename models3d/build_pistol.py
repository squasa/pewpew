"""Build an original 3D tactical pistol in Blender; render & export:
  models3d/pistol_beauty.png   3/4 studio shot
  models3d/pistol.blend        editable Blender scene
  models3d/pistol.glb          runtime glTF binary for moderngl (named `slide_*` parts animate recoil)

Local Blender coordinates:
  Origin (0, 0, 0): center of hand grip web
  Barrel forward:   -Y (exports to +Z_glb in glTF Y-up)
  Top of slide/sights: +Z (exports to +Y_glb in glTF Y-up)
  Right side:       +X (exports to +X_glb in glTF Y-up)

Run headless:
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python-exit-code 1 -P models3d/build_pistol.py
"""
import sys
from pathlib import Path

import bpy

SKILL_SCRIPTS = "/Users/rmclol/.local/share/muse/skills/bundled/muse-core--exact-minimal-literal-tests~v1/skills/blender/scripts"
sys.path.insert(0, SKILL_SCRIPTS)
import bpy_helpers as H  # noqa: E402

ROOT = Path(__file__).parent.parent
OUT3D = ROOT / "models3d"
OUT3D.mkdir(exist_ok=True)


def build_pistol_scene(render_beauty: bool = True) -> list:
    H.reset_scene()

    gunmetal = H.material_preset("gunmetal slide", "brushed_metal", "#4E5560", scale=12)
    steel = H.material_preset("stainless barrel", "steel", "#C4CAD2", scale=12)
    dark_steel = H.material("dark steel", "#24282E", roughness=0.38, metallic=0.95)
    polymer = H.material_preset("polymer frame", "plastic", "#1B1E23", scale=14, roughness=0.62)
    rubber = H.material_preset("grip rubber", "rubber", "#121417", scale=14)
    brass = H.material_preset("brass accent", "brass", "#C9963C", scale=12)
    bore_mat = H.material("bore interior", "#050608", roughness=0.9, metallic=0.1)
    fiber_cyan = H.emission_material("fiber sight cyan", "#4BE8FF", 3.5)
    fiber_pink = H.emission_material("fiber sight pink", "#FF5488", 2.5)

    parts: list = []

    def add(obj):
        parts.append(obj)
        return obj

    # --- Lower Polymer Frame + Grip (fixed relative to hand) ---
    # Ergonomic swept grip (~15 deg tilt along +Y as Z goes negative), tucked flush into rail tang
    add(H.add_box(
        "frame_grip",
        size=(0.025, 0.042, 0.118),
        location=(0.0, 0.014, -0.034),
        rotation=(-15.0, 0.0, 0.0),
        mat=polymer,
        bevel=0.0035,
    ))
    add(H.add_box(
        "frame_grip_panel_r",
        size=(0.0275, 0.029, 0.078),
        location=(0.0, 0.015, -0.040),
        rotation=(-15.0, 0.0, 0.0),
        mat=rubber,
        bevel=0.0022,
    ))
    # Ribbed finger grooves on frontstrap
    for i in range(4):
        gz = -0.016 - i * 0.018
        gy = -0.006 + i * 0.0048
        add(H.add_cylinder(
            f"frame_strap_rib_{i}",
            radius=0.0022,
            depth=0.019,
            location=(0.0, gy, gz),
            rotation=(0.0, 90.0, 0.0),
            mat=rubber,
        ))
    # Flared magwell baseplate (flush to swept grip bottom)
    add(H.add_box(
        "frame_magplate",
        size=(0.0285, 0.044, 0.010),
        location=(0.0, 0.025, -0.092),
        rotation=(-15.0, 0.0, 0.0),
        mat=dark_steel,
        bevel=0.002,
    ))
    # Lower dustcover & rail body (slightly recessed back from slide nose)
    add(H.add_box(
        "frame_rail",
        size=(0.026, 0.172, 0.024),
        location=(0.0, -0.048, 0.021),
        mat=polymer,
        bevel=0.0025,
    ))
    # Picatinny underbarrel rail slots
    for i in range(4):
        ry = -0.082 - i * 0.014
        add(H.add_box(
            f"frame_picrail_{i}",
            size=(0.020, 0.008, 0.006),
            location=(0.0, ry, 0.008),
            mat=dark_steel,
            bevel=0.0008,
        ))
    # Beavertail tang seamlessly bridging grip into rear rail
    add(H.add_box(
        "frame_beavertail",
        size=(0.023, 0.044, 0.020),
        location=(0.0, 0.026, 0.022),
        rotation=(-8.0, 0.0, 0.0),
        mat=polymer,
        bevel=0.003,
    ))
    # Trigger guard assembly
    add(H.add_box(
        "frame_tguard_bot",
        size=(0.010, 0.050, 0.0055),
        location=(0.0, -0.024, -0.014),
        mat=polymer,
        bevel=0.0012,
    ))
    add(H.add_box(
        "frame_tguard_front",
        size=(0.010, 0.006, 0.029),
        location=(0.0, -0.048, -0.001),
        rotation=(14.0, 0.0, 0.0),
        mat=polymer,
        bevel=0.0012,
    ))
    # Curved trigger + brass frame controls (slide lock / mag release)
    add(H.add_box(
        "frame_trigger",
        size=(0.0055, 0.007, 0.022),
        location=(0.0, -0.020, 0.002),
        rotation=(-22.0, 0.0, 0.0),
        mat=brass,
        bevel=0.0012,
    ))
    add(H.add_cylinder(
        "frame_mag_release",
        radius=0.0038,
        depth=0.0285,
        location=(0.0, 0.002, 0.002),
        rotation=(0.0, 90.0, 0.0),
        mat=brass,
    ))
    add(H.add_box(
        "frame_slide_stop",
        size=(0.0295, 0.024, 0.005),
        location=(0.0, -0.004, 0.031),
        mat=dark_steel,
        bevel=0.001,
    ))

    # --- Fixed Stainless Barrel & Guide Rod ---
    add(H.add_cylinder(
        "barrel_tube",
        radius=0.0086,
        depth=0.184,
        location=(0.0, -0.072, 0.047),
        rotation=(90.0, 0.0, 0.0),
        mat=steel,
        bevel=0.0012,
    ))
    add(H.add_cylinder(
        "barrel_bore",
        radius=0.0052,
        depth=0.018,
        location=(0.0, -0.1552, 0.047),
        rotation=(90.0, 0.0, 0.0),
        mat=bore_mat,
    ))
    add(H.add_cylinder(
        "barrel_guide_rod",
        radius=0.0044,
        depth=0.106,
        location=(0.0, -0.101, 0.031),
        rotation=(90.0, 0.0, 0.0),
        mat=dark_steel,
        bevel=0.0008,
    ))

    # --- Reciprocating Slide Assembly (`slide_*` prefix animated on shot recoil) ---
    add(H.add_box(
        "slide_main",
        size=(0.0285, 0.200, 0.028),
        location=(0.0, -0.056, 0.048),
        mat=gunmetal,
        bevel=0.0038,
    ))
    # Top slide ridge chamfer
    add(H.add_box(
        "slide_top_rib",
        size=(0.019, 0.194, 0.006),
        location=(0.0, -0.056, 0.061),
        mat=dark_steel,
        bevel=0.0015,
    ))
    # Stainless chamber hood & brass extractor accent visible in ejection port
    add(H.add_box(
        "slide_chamber",
        size=(0.020, 0.036, 0.015),
        location=(0.0055, -0.026, 0.056),
        mat=steel,
        bevel=0.0018,
    ))
    add(H.add_box(
        "slide_extractor",
        size=(0.003, 0.026, 0.005),
        location=(0.0145, -0.004, 0.050),
        mat=brass,
        bevel=0.0006,
    ))
    # Rear & front slide serration ribs
    for i in range(6):
        sy = 0.036 - i * 0.0065
        add(H.add_box(
            f"slide_serr_r_{i}",
            size=(0.0298, 0.0032, 0.019),
            location=(0.0, sy, 0.048),
            mat=dark_steel,
            bevel=0.0006,
        ))
    for i in range(4):
        sy = -0.122 - i * 0.0065
        add(H.add_box(
            f"slide_serr_f_{i}",
            size=(0.0295, 0.0032, 0.017),
            location=(0.0, sy, 0.047),
            mat=dark_steel,
            bevel=0.0006,
        ))

    # Iron Sights (slide-mounted, also named `slide_*` so sights recoil with slide)
    add(H.add_box(
        "slide_sight_front",
        size=(0.0045, 0.011, 0.0075),
        location=(0.0, -0.145, 0.066),
        mat=dark_steel,
        bevel=0.0008,
    ))
    add(H.add_sphere(
        "slide_sight_front_dot",
        radius=0.0018,
        location=(0.0, -0.141, 0.067),
        mat=fiber_cyan,
    ))
    for sx_idx, sx in enumerate((-0.0062, 0.0062)):
        add(H.add_box(
            f"slide_sight_rear_{sx_idx}",
            size=(0.005, 0.010, 0.0075),
            location=(sx, 0.033, 0.066),
            mat=dark_steel,
            bevel=0.0008,
        ))
        add(H.add_sphere(
            f"slide_sight_rear_dot_{sx_idx}",
            radius=0.0014,
            location=(sx, 0.0382, 0.0665),
            mat=fiber_pink,
        ))

    if render_beauty:
        H.world_color("#161A22", 0.55)
        H.studio_lighting(target=parts, key_azimuth=-42, key_elevation=40, intensity=1.1, contrast=0.55, softness=0.5)
        cam = H.add_camera("cam_beauty", (0.28, -0.32, 0.14), (0.0, -0.05, 0.01), lens=55)
        bpy.context.scene.camera = cam
        _floor = bpy.data.objects.get("Floor")
        if _floor:
            _floor.hide_render = True
        H.set_render(engine="CYCLES", resolution=(960, 680), samples=48, transparent=False,
                     view_transform="Khronos PBR Neutral")
        H.render_still(str(OUT3D / "pistol_beauty.png"))
        print("rendered pistol_beauty.png")

    H.save_blend(str(OUT3D / "pistol.blend"))
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(OUT3D / "pistol.glb"), export_format="GLB", use_selection=True)
    print("saved pistol.blend + pistol.glb")
    return parts


if __name__ == "__main__":
    build_pistol_scene(render_beauty=True)
    H.report()
