"""Generate pewpew assets: pistol.png, muzzle_flash.png, gunshot.wav.

Run once:  .venv/bin/python make_assets.py
The pistol is drawn procedurally (side profile, muzzle pointing +x) at 3x
supersampling. Anchors in the final 1000x600 image:
  GRAB   = (270, 400)  centre of the grip (where the hand holds it)
  MUZZLE = (945, 178)  muzzle tip / flash + tracer origin
These constants are duplicated in app.py.
"""
import math
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "assets"
OUT.mkdir(exist_ok=True)

S = 3  # supersampling
W, H = 1000 * S, 600 * S


def sc(v):
    """Scale a scalar or sequence of coords by S."""
    if isinstance(v, (list, tuple)):
        return [sc(x) for x in v]
    return v * S


def make_pistol() -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    slide = (38, 41, 46, 255)
    slide_hi = (74, 80, 88, 255)
    slide_dark = (22, 24, 27, 255)
    frame = (46, 50, 55, 255)
    frame_dark = (30, 32, 36, 255)
    steel = (138, 144, 153, 255)
    steel_dark = (96, 101, 108, 255)
    black = (14, 15, 17, 255)
    grip_c = (29, 31, 34, 255)
    wood = (96, 66, 44, 255)
    wood_dark = (70, 46, 30, 255)

    # --- grip (drawn first, frame overlaps its top) ---
    grip = sc([(398, 262), (218, 252), (138, 518), (302, 546)])
    d.polygon(grip, fill=grip_c)
    # wood grip panel (inset)
    panel = sc([(372, 296), (244, 288), (182, 488), (288, 508)])
    d.polygon(panel, fill=wood)
    # grip checkering: diagonal texture lines clipped roughly to panel
    for i in range(14):
        y = 300 + i * 15
        d.line(sc([(250 - i * 4, y), (360 - i * 4, y + 26)]), fill=wood_dark, width=sc(3))
    # panel screws
    for cx, cy in [(292, 330), (252, 462)]:
        d.ellipse(sc([cx - 9, cy - 9, cx + 9, cy + 9]), fill=steel_dark)
        d.ellipse(sc([cx - 4, cy - 4, cx + 4, cy + 4]), fill=black)
    # magazine baseplate
    d.polygon(sc([(138, 518), (302, 546), (296, 566), (132, 538)]), fill=frame_dark)

    # --- frame / dust cover ---
    d.polygon(sc([(168, 212), (884, 212), (884, 278), (398, 278), (398, 262), (218, 252), (200, 278), (168, 278)]), fill=frame)
    d.rectangle(sc([168, 258, 884, 278]), fill=frame_dark)
    # accessory rail slots under the front
    for x in (700, 752, 804):
        d.rectangle(sc([x, 246, x + 16, 272]), fill=black)

    # --- trigger guard (thick arc) + trigger ---
    guard_pts = []
    for t in range(0, 31):
        a = math.pi * t / 30  # 0..pi
        guard_pts.append((545 + 112 * math.cos(a), 278 + 74 * math.sin(a)))
    d.line(sc(guard_pts), fill=frame, width=sc(17), joint="curve")
    trig_pts = [(528 + 10 * math.sin(t / 6), 280 + t * 2.4) for t in range(0, 21)]
    d.line(sc(trig_pts), fill=steel_dark, width=sc(11), joint="curve")

    # --- slide ---
    d.rounded_rectangle(sc([148, 138, 924, 216]), radius=sc(10), fill=slide)
    d.rectangle(sc([148, 138, 924, 160]), fill=slide_hi)  # top sheen
    d.rectangle(sc([148, 198, 924, 216]), fill=slide_dark)  # lower shadow
    # rear + front cocking serrations
    for x0 in range(176, 242, 13):
        d.line(sc([(x0, 150), (x0 - 6, 204)]), fill=black, width=sc(5))
    for x0 in range(798, 864, 13):
        d.line(sc([(x0, 150), (x0 - 6, 204)]), fill=black, width=sc(5))
    # ejection port with barrel visible inside
    d.rounded_rectangle(sc([478, 152, 644, 200]), radius=sc(6), fill=black)
    d.rectangle(sc([492, 164, 630, 190]), fill=steel)
    d.rectangle(sc([492, 182, 630, 190]), fill=steel_dark)
    # sights
    d.rectangle(sc([162, 114, 208, 140]), fill=slide_dark)  # rear sight
    d.rectangle(sc([178, 104, 192, 116]), fill=slide_dark)
    d.rectangle(sc([862, 118, 876, 140]), fill=slide_dark)  # front post
    # slide-stop + safety pins
    for cx, cy, r in [(452, 244, 10), (268, 238, 8)]:
        d.ellipse(sc([cx - r, cy - r, cx + r, cy + r]), fill=steel_dark)
    d.rectangle(sc([428, 232, 500, 246]), fill=steel_dark)  # slide stop lever

    # --- hammer (rear, above beavertail) ---
    d.polygon(sc([(150, 150), (122, 176), (128, 214), (158, 216)]), fill=steel_dark)
    d.ellipse(sc([126, 168, 146, 188]), fill=black)
    d.polygon(sc([(148, 212), (118, 232), (150, 262), (176, 252)]), fill=frame_dark)  # beavertail

    # --- muzzle / barrel bushing ---
    d.ellipse(sc([896, 152, 948, 204]), fill=steel)
    d.ellipse(sc([908, 162, 938, 194]), fill=steel_dark)
    d.ellipse(sc([916, 169, 932, 187]), fill=black)  # bore

    # edge highlight along slide top
    d.line(sc([(154, 140), (918, 140)]), fill=(255, 255, 255, 90), width=sc(3))

    img = img.resize((1000, 600), Image.LANCZOS)
    img.save(OUT / "pistol.png")
    print("pistol.png", img.size)


def make_flash() -> None:
    w, h = 480, 360
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    ox, oy = 40, h // 2  # muzzle attach point (left-centre)
    # glow halo
    gd.ellipse([ox - 30, oy - 90, ox + 190, oy + 90], fill=(255, 140, 30, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(28))
    img.alpha_composite(glow)

    d = ImageDraw.Draw(img)
    orange = (255, 122, 26, 235)
    yellow = (255, 205, 60, 245)
    white = (255, 248, 220, 255)
    # main horizontal flame (long, jagged)
    d.polygon([(ox, oy - 26), (300, oy - 12), (468, oy), (300, oy + 12), (ox, oy + 26)], fill=orange)
    d.polygon([(ox, oy - 16), (260, oy - 7), (410, oy), (260, oy + 7), (ox, oy + 16)], fill=yellow)
    d.polygon([(ox, oy - 8), (200, oy - 3), (320, oy), (200, oy + 3), (ox, oy + 8)], fill=white)
    # side spikes
    for ang, ln, wd, col in [(-52, 150, 17, orange), (52, 150, 17, orange),
                             (-30, 190, 11, yellow), (30, 190, 11, yellow),
                             (-72, 95, 9, yellow), (72, 95, 9, yellow)]:
        a = math.radians(ang)
        tx, ty = ox + ln * math.cos(a), oy + ln * math.sin(a)
        px, py = -math.sin(a) * wd, math.cos(a) * wd
        d.polygon([(ox + px, oy + py), (tx, ty), (ox - px, oy - py)], fill=col)
    # hot core at muzzle
    d.ellipse([ox - 22, oy - 30, ox + 46, oy + 30], fill=white)
    img.save(OUT / "muzzle_flash.png")
    print("muzzle_flash.png", img.size)


def make_gunshot() -> None:
    sr = 48000
    dur = 0.45
    n = int(sr * dur)
    t = np.arange(n) / sr
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    # crack: fast-decaying bright noise
    crack = noise * np.exp(-t * 90) * 1.0
    # body: smoothed (low-passed) noise, slower decay -> boom
    k = 220
    body = np.convolve(noise, np.ones(k) / k, mode="same") * np.exp(-t * 14) * 2.4
    # sub thump: pitch-dropping sine
    freq = 130 * np.exp(-t * 22) + 38
    phase = np.cumsum(2 * np.pi * freq / sr)
    thump = np.sin(phase) * np.exp(-t * 16) * 0.8
    sig = crack + body + thump
    sig /= (np.max(np.abs(sig)) + 1e-9)
    sig *= 0.92
    pcm = (sig * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(OUT / "gunshot.wav"), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(stereo.tobytes())
    print("gunshot.wav", sr, "Hz", dur, "s")


if __name__ == "__main__":
    make_pistol()
    make_flash()
    make_gunshot()
