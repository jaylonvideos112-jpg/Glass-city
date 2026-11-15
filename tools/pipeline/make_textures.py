"""Procedural low-poly-friendly textures (512px, tileable) for the city."""
import sys, os, random
from PIL import Image, ImageDraw, ImageFilter
import numpy as np

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
S = 512
rng = np.random.default_rng(7)

def noise(img, amt):
    a = np.asarray(img).astype(np.int16)
    n = rng.integers(-amt, amt + 1, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a + n, 0, 255).astype(np.uint8))

WIN = []   # window glass boxes drawn since the last save -> night emission mask "<name>_emit.png"
_mrng = random.Random(11)

def save(img, name):
    img.convert("RGB").save(os.path.join(OUT, name + ".png"))
    if WIN:
        # night-lights mask: about 55% of windows lit, each a slightly different warmth/brightness
        m = Image.new("RGB", (S, S), (0, 0, 0)); md = ImageDraw.Draw(m)
        few = len(WIN) <= 4   # a house texture with 1-4 windows: light them all, or every such house is dark
        for box in WIN:
            if few or _mrng.random() < 0.55:
                v = 0.55 + 0.45 * _mrng.random(); w = _mrng.random()
                md.rectangle(box, fill=(int(255 * v), int((200 + 40 * w) * v), int((120 + 90 * w) * v)))
        m.save(os.path.join(OUT, name + "_emit.png"))
    WIN.clear()

def windows(d, cols, rows, frame, glass, inset=(0.25, 0.22), lit=0.04):
    cw, rh = S / cols, S / rows
    for r in range(rows):
        for c in range(cols):
            x0 = c * cw + cw * inset[0]; x1 = (c + 1) * cw - cw * inset[0]
            y0 = r * rh + rh * inset[1]; y1 = (r + 1) * rh - rh * 0.12
            d.rectangle([x0 - 5, y0 - 5, x1 + 5, y1 + 5], fill=frame)
            g = (225, 205, 150) if random.random() < lit else glass
            d.rectangle([x0, y0, x1, y1], fill=g); WIN.append([x0, y0, x1, y1])
            d.line([(x0 + x1) / 2, y0, (x0 + x1) / 2, y1], fill=frame, width=4)
            d.line([x0, (y0 + y1) / 2, x1, (y0 + y1) / 2], fill=frame, width=3)
            d.rectangle([x0 - 8, y1 + 4, x1 + 8, y1 + 12], fill=(200, 195, 185))  # sill

random.seed(3)

# Brick facade: 2 windows x 2 floors per tile
def brick(base, mortar, name, glass=(60, 75, 90)):
    img = Image.new("RGB", (S, S), mortar); d = ImageDraw.Draw(img)
    bh, bw = 12, 32
    for row in range(S // bh):
        off = (bw // 2) * (row % 2)
        for col in range(-1, S // bw + 1):
            x = col * bw + off; y = row * bh
            v = random.randint(-22, 22)
            c = tuple(max(0, min(255, base[i] + v)) for i in range(3))
            d.rectangle([x + 1, y + 1, x + bw - 2, y + bh - 2], fill=c)
    windows(d, 2, 2, (40, 35, 32), glass)
    save(noise(img, 8), name)

brick((140, 62, 45), (170, 160, 150), "brick_red", (38, 50, 62))
brick((115, 70, 50), (150, 140, 130), "brick_brown")
brick((175, 150, 115), (190, 185, 175), "brick_tan")

# Warehouse brick: big arched-ish industrial windows, 3 x 2
img = Image.new("RGB", (S, S), (150, 140, 130)); d = ImageDraw.Draw(img)
for row in range(S // 12):
    off = 16 * (row % 2)
    for col in range(-1, S // 32 + 1):
        v = random.randint(-25, 18)
        d.rectangle([col * 32 + off + 1, row * 12 + 1, col * 32 + off + 30, row * 12 + 10], fill=(125 + v, 55 + v // 2, 40 + v // 2))
for r in range(2):
    for c in range(3):
        x0 = c * S / 3 + 30; x1 = (c + 1) * S / 3 - 30; y0 = r * S / 2 + 50; y1 = (r + 1) * S / 2 - 30
        d.rectangle([x0, y0, x1, y1], fill=(45, 50, 50)); WIN.append([x0, y0, x1, y1])
        for gx in range(4):
            for gy in range(5):
                gw = (x1 - x0) / 4; gh = (y1 - y0) / 5
                d.rectangle([x0 + gx * gw + 3, y0 + gy * gh + 3, x0 + (gx + 1) * gw - 3, y0 + (gy + 1) * gh - 3],
                            fill=(80, 95, 100) if random.random() > 0.1 else (30, 30, 30))
        d.rectangle([x0 - 6, y0 - 14, x1 + 6, y0 - 4], fill=(180, 170, 155))
save(noise(img, 8), "warehouse")

# Glass curtain wall
img = Image.new("RGB", (S, S), (70, 95, 120)); d = ImageDraw.Draw(img)
a = np.zeros((S, S, 3), np.float32)
for y in range(S):
    a[y, :, :] = np.array([60, 88, 118]) + 40 * (y / S)
img = Image.fromarray(a.astype(np.uint8)); d = ImageDraw.Draw(img)
for i in range(0, S, S // 4):
    d.rectangle([i, 0, i + 6, S], fill=(160, 165, 170))
for j in range(0, S, S // 4):
    d.rectangle([0, j, S, j + 10], fill=(150, 155, 160))
    for i in range(0, S, S // 4):
        if random.random() < 0.15:
            d.rectangle([i + 8, j + 12, i + S // 4 - 2, j + S // 4 - 2], fill=(200, 190, 140))
save(noise(img, 4), "glass")

# Concrete office: horizontal window bands
img = Image.new("RGB", (S, S), (190, 185, 172)); d = ImageDraw.Draw(img)
for r in range(3):
    y0 = r * S / 3 + 40; y1 = (r + 1) * S / 3 - 30
    d.rectangle([0, y0, S, y1], fill=(55, 70, 85))
    for c in range(6):
        x = c * S / 6
        d.rectangle([x, y0, x + 8, y1], fill=(170, 168, 160))
        if random.random() < 0.15:
            d.rectangle([x + 10, y0 + 2, x + S / 6 - 2, y1 - 2], fill=(220, 205, 150))
save(noise(img, 6), "concrete")

# Clapboard siding with one window per 4m tile (white; tinted in-engine)
img = Image.new("RGB", (S, S), (235, 235, 230)); d = ImageDraw.Draw(img)
for y in range(0, S, 16):
    d.rectangle([0, y + 13, S, y + 15], fill=(185, 185, 180))
for (x0, y0) in [(150, 120)]:
    d.rectangle([x0 - 14, y0 - 14, x0 + 214, y0 + 254], fill=(250, 250, 250))
    d.rectangle([x0, y0, x0 + 200, y0 + 240], fill=(55, 65, 75))
    d.line([x0 + 100, y0, x0 + 100, y0 + 240], fill=(250, 250, 250), width=8)
    d.line([x0, y0 + 120, x0 + 200, y0 + 120], fill=(250, 250, 250), width=8)
    d.rectangle([x0 - 40, y0, x0 - 10, y0 + 240], fill=(60, 60, 60))
    d.rectangle([x0 + 210, y0, x0 + 240, y0 + 240], fill=(60, 60, 60))
save(noise(img, 5), "siding")

def flat(base, amt, name, blur=0):
    img = Image.new("RGB", (S, S), base)
    img = noise(img, amt)
    if blur: img = img.filter(ImageFilter.GaussianBlur(blur))
    save(img, name)

flat((58, 58, 62), 14, "asphalt")
flat((92, 92, 90), 18, "roof")
flat((76, 120, 58), 22, "grass", 1)
flat((70, 70, 72), 12, "parking")
flat((60, 55, 50), 18, "riverbed", 1)
flat((105, 95, 85), 16, "rail")

img = Image.new("RGB", (S, S), (175, 172, 165)); d = ImageDraw.Draw(img)
for i in range(0, S, 128):
    d.line([i, 0, i, S], fill=(130, 128, 122), width=3); d.line([0, i, S, i], fill=(130, 128, 122), width=3)
save(noise(img, 8), "sidewalk")

img = Image.new("RGB", (S, S), (150, 145, 135)); d = ImageDraw.Draw(img)
for row in range(S // 64):
    off = 64 * (row % 2)
    for col in range(-1, 5):
        d.rectangle([col * 128 + off + 2, row * 64 + 2, col * 128 + off + 125, row * 64 + 61], fill=(140 + random.randint(-12, 12),) * 3)
save(noise(img, 8), "seawall")
print("textures done")

# Asphalt shingles (pitched house roofs)
img = Image.new("RGB", (S, S), (70, 66, 64)); d = ImageDraw.Draw(img)
for row in range(S // 32):
    off = 24 * (row % 2)
    for col in range(-1, S // 48 + 1):
        v = random.randint(-14, 14)
        d.rectangle([col * 48 + off + 1, row * 32 + 1, col * 48 + off + 46, row * 32 + 29], fill=(78 + v, 72 + v, 70 + v))
    d.line([0, row * 32 + 30, S, row * 32 + 30], fill=(40, 38, 36), width=3)
save(noise(img, 6), "shingle")

# Corrugated metal industrial siding with a band of clerestory windows
img = Image.new("RGB", (S, S), (165, 170, 172)); d = ImageDraw.Draw(img)
for x in range(0, S, 16):
    d.rectangle([x, 0, x + 7, S], fill=(140, 146, 150))
d.rectangle([0, 60, S, 120], fill=(60, 72, 80))
for x in range(0, S, 64):
    d.rectangle([x, 60, x + 4, 120], fill=(150, 150, 150))
save(noise(img, 6), "metal")
flat((92, 82, 60), 22, "forest_floor", 1)
flat((118, 115, 108), 16, "industrial")

# ---------------- landmark & detail textures
def grid_facade(name, bg, win, cols, rows, frame, mull_w=6, band=None, lit=0.03, vert_fins=None):
    img = Image.new("RGB", (S, S), bg); d = ImageDraw.Draw(img)
    cw, rh = S / cols, S / rows
    for r in range(rows):
        for c_ in range(cols):
            x0, y0 = c_ * cw + mull_w, r * rh + (band or mull_w)
            x1, y1 = (c_ + 1) * cw - mull_w, (r + 1) * rh - mull_w
            col = (220, 200, 150) if random.random() < lit else win
            d.rectangle([x0, y0, x1, y1], fill=col); WIN.append([x0, y0, x1, y1])
    if vert_fins:
        for c_ in range(cols + 1):
            d.rectangle([c_ * cw - vert_fins // 2, 0, c_ * cw + vert_fins // 2, S], fill=frame)
    save(noise(img, 5), name)

# Storefront ground floor: display glass, door, sign band and striped awnings
img = Image.new("RGB", (S, S), (120, 60, 45)); d = ImageDraw.Draw(img)
awn = [(150, 30, 30), (30, 80, 50), (40, 60, 120), (160, 120, 40)]
for k in range(2):
    x0 = k * S / 2
    d.rectangle([x0 + 10, 40, x0 + S / 2 - 10, 120], fill=(35, 35, 38))        # sign band
    a = awn[random.randint(0, 3)]
    for j in range(0, int(S / 2) - 20, 24):
        d.rectangle([x0 + 10 + j, 120, x0 + 22 + j, 175], fill=a)
        d.rectangle([x0 + 22 + j, 120, x0 + 34 + j, 175], fill=(235, 230, 220))
    d.rectangle([x0 + 18, 185, x0 + S / 2 - 18, S - 20], fill=(30, 40, 48))     # display glass
    d.rectangle([x0 + S / 4 - 30, 230, x0 + S / 4 + 30, S - 20], fill=(70, 50, 35))  # door
    for j in range(3):
        d.rectangle([x0 + 18 + j * 80, 185, x0 + 22 + j * 80, S - 20], fill=(80, 80, 82))
save(noise(img, 6), "storefront")

grid_facade("intl_dark", (190, 192, 195), (28, 30, 34), 3, 3, (205, 208, 212), mull_w=4, band=26, vert_fins=14)  # Fiberglas Tower
grid_facade("glass_oneseagate", (45, 70, 78), (55, 95, 110), 4, 3, (30, 50, 58), mull_w=3, band=40, lit=0.02)      # One SeaGate
grid_facade("yamasaki", (232, 230, 222), (40, 48, 60), 6, 3, (232, 230, 222), mull_w=16, band=30)                 # Gov Center slits
grid_facade("glass_dark", (60, 52, 45), (38, 34, 32), 4, 4, (60, 52, 45), mull_w=4, band=22)
grid_facade("glass_blue", (110, 140, 165), (55, 85, 120), 4, 4, (180, 190, 200), mull_w=4, band=18)
# Limestone / terracotta / sandstone masonry with punched windows
for nm_, base_ in (("limestone", (206, 198, 178)), ("terracotta", (226, 222, 210)), ("sandstone", (176, 140, 100))):
    img = Image.new("RGB", (S, S), base_); d = ImageDraw.Draw(img)
    for y in range(0, S, 32): d.line([0, y, S, y], fill=tuple(max(0, v - 25) for v in base_), width=2)
    windows(d, 3, 3, tuple(max(0, v - 70) for v in base_), (40, 48, 56))
    save(noise(img, 6), nm_)
img = Image.new("RGB", (S, S), (24, 24, 26)); d = ImageDraw.Draw(img)
d.rectangle([140, 60, 372, S], fill=(18, 20, 24))
save(noise(img, 8), "granite_black")
flat((236, 234, 228), 8, "marble")
flat((110, 165, 205), 10, "bridge_blue")
flat((232, 232, 236), 4, "cable")
flat((150, 225, 215), 6, "glass_lit")
img = Image.new("RGB", (S, S), (30, 70, 140)); d = ImageDraw.Draw(img)
for y in range(0, S, 32): d.rectangle([0, y + 22, S, y + 31], fill=(60, 60, 64))
save(noise(img, 10), "seats")
flat((238, 236, 230), 6, "porch")
flat((96, 150, 120), 10, "copper_green")
img = Image.new("RGB", (S, S), (120, 45, 38)); d = ImageDraw.Draw(img)
for row in range(S // 32):
    d.line([0, row * 32 + 30, S, row * 32 + 30], fill=(70, 28, 24), width=3)
save(noise(img, 8), "shingle_red")

# ---------------- bar themes
# Shooters: dark brick with blacked-out windows glowing with beer neons
img = Image.new("RGB", (S, S), (40, 36, 34)); d = ImageDraw.Draw(img)
for row in range(S // 12):
    off = 16 * (row % 2)
    for col in range(-1, S // 32 + 1):
        v = random.randint(-10, 10)
        d.rectangle([col * 32 + off + 1, row * 12 + 1, col * 32 + off + 30, row * 12 + 10], fill=(70 + v, 34 + v, 30 + v))
for c_ in range(2):
    x0 = 40 + c_ * 256; d.rectangle([x0, 150, x0 + 180, 360], fill=(12, 12, 14))
    d.rectangle([x0 + 30, 200, x0 + 150, 230], fill=(230, 40, 50)); d.rectangle([x0 + 50, 260, x0 + 130, 290], fill=(40, 120, 240))
save(noise(img, 6), "bar_shooters")
# Rusty Anchor: weathered gray clapboard with round portholes
img = Image.new("RGB", (S, S), (128, 132, 130)); d = ImageDraw.Draw(img)
for y in range(0, S, 20):
    d.rectangle([0, y + 16, S, y + 19], fill=(80, 84, 82))
    for k in range(6): d.line([random.randint(0, S), y + random.randint(2, 14), random.randint(0, S), y + random.randint(2, 14)], fill=(110, 112, 108), width=1)
for c_ in range(2):
    cx = 128 + c_ * 256; d.ellipse([cx - 70, 180, cx + 70, 320], fill=(150, 90, 50)); d.ellipse([cx - 55, 195, cx + 55, 305], fill=(40, 90, 95))
    d.ellipse([cx - 50, 200, cx - 20, 230], fill=(150, 200, 195))
for k in range(30):  # rust streaks
    x = random.randint(0, S); d.line([x, 320, x + random.randint(-4, 4), 320 + random.randint(20, 80)], fill=(140, 80, 45), width=2)
save(noise(img, 10), "bar_anchor")
# Cardboard Club: corrugated cardboard with tape seams
img = Image.new("RGB", (S, S), (176, 132, 82)); d = ImageDraw.Draw(img)
for x in range(0, S, 8): d.line([x, 0, x, S], fill=(158, 116, 70), width=3)
for y in (0, 255): d.rectangle([0, y, S, y + 26], fill=(196, 170, 120))
d.rectangle([60, 120, 220, 230], fill=(30, 26, 22)); d.rectangle([300, 120, 460, 230], fill=(30, 26, 22))
save(noise(img, 8), "bar_cardboard")
# Easy Pour: warm vertical wood with big taproom windows
img = Image.new("RGB", (S, S), (150, 96, 58)); d = ImageDraw.Draw(img)
for x in range(0, S, 32):
    v = random.randint(-18, 18); d.rectangle([x + 1, 0, x + 30, S], fill=(150 + v, 96 + v // 2, 58 + v // 3))
    d.line([x, 0, x, S], fill=(90, 56, 32), width=2)
for c_ in range(2):
    x0 = 30 + c_ * 256; d.rectangle([x0, 90, x0 + 200, 400], fill=(60, 50, 40)); d.rectangle([x0 + 10, 100, x0 + 190, 390], fill=(240, 200, 130))
    for j in range(1, 4): d.line([x0 + 10 + j * 45, 100, x0 + 10 + j * 45, 390], fill=(60, 50, 40), width=6)
save(noise(img, 6), "bar_easypour")
# interior materials
img = Image.new("RGB", (S, S), (92, 60, 38)); d = ImageDraw.Draw(img)
for y in range(0, S, 32):
    off = random.randint(0, S)
    d.line([0, y, S, y], fill=(50, 32, 20), width=2); d.line([off, y, off, y + 32], fill=(50, 32, 20), width=2)
save(noise(img, 10), "wood_floor")
flat((48, 34, 26), 14, "wood_dark")
flat((28, 34, 30), 6, "chalkboard")
flat((30, 110, 60), 10, "felt")
img = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
for k in range(0, S, 32):
    d.line([k, 0, k + 64, S], fill=(170, 150, 110, 255), width=3); d.line([k, S, k + 64, 0], fill=(170, 150, 110, 255), width=3)
img.save(os.path.join(OUT, "net.png"))

# ---------------- big bars, round 2
# Velvet Mile: glossy black panels, purple-lit frosted glass, gold trim
img = Image.new("RGB", (S, S), (18, 14, 22)); d = ImageDraw.Draw(img)
for x in range(0, S, 64): d.line([x, 0, x, S], fill=(170, 135, 60), width=3)
for c_ in range(4):
    x0 = 10 + c_ * 128; d.rectangle([x0 + 8, 160, x0 + 110, 380], fill=(120, 50, 170)); d.rectangle([x0 + 20, 172, x0 + 98, 368], fill=(160, 90, 210))
d.rectangle([0, 120, S, 128], fill=(200, 160, 70))
save(noise(img, 4), "bar_velvet")
# Lakefront Lounge: white beach-house boards, blue awning stripes, bamboo posts, round lake windows
img = Image.new("RGB", (S, S), (226, 228, 222)); d = ImageDraw.Draw(img)
for y in range(0, S, 20): d.line([0, y, S, y], fill=(190, 194, 190), width=2)
for x in range(0, S, 48): d.rectangle([x, 90, x + 24, 150], fill=(30, 110, 180))
d.rectangle([0, 150, S, 158], fill=(20, 80, 140))
for x in (0, 250, 500): d.rectangle([x, 160, x + 12, S], fill=(190, 160, 90))
for c_ in range(2):
    x0 = 70 + c_ * 256; d.rectangle([x0, 200, x0 + 130, 360], fill=(60, 140, 190)); d.rectangle([x0 + 8, 208, x0 + 122, 352], fill=(140, 210, 230))
save(noise(img, 5), "bar_lakefront")
# Neon Coyote: sand adobe stucco, timber vigas, neon cactus windows
img = Image.new("RGB", (S, S), (204, 160, 110)); d = ImageDraw.Draw(img)
for k in range(400):
    x = random.randint(0, S); y = random.randint(0, S); v = random.randint(-20, 10); d.point((x, y), fill=(204 + v, 160 + v, 110 + v))
for x in range(20, S, 85): d.rectangle([x, 60, x + 20, 80], fill=(90, 60, 36))
for c_ in range(2):
    x0 = 70 + c_ * 256; d.rectangle([x0, 170, x0 + 130, 340], fill=(30, 22, 30))
    cx = x0 + 65; d.rectangle([cx - 8, 200, cx + 8, 320], fill=(60, 240, 120)); d.rectangle([cx - 40, 240, cx - 8, 252], fill=(60, 240, 120))
    d.rectangle([cx - 40, 210, cx - 30, 252], fill=(60, 240, 120)); d.rectangle([cx + 8, 260, cx + 38, 272], fill=(255, 80, 180)); d.rectangle([cx + 28, 225, cx + 38, 272], fill=(255, 80, 180))
save(noise(img, 6), "bar_coyote")
# Alligator Club: swamp-green tin shack, bamboo trim, yellow-eye windows
img = Image.new("RGB", (S, S), (62, 96, 52)); d = ImageDraw.Draw(img)
for x in range(0, S, 16): d.line([x, 0, x, S], fill=(48, 78, 40), width=5)
for k in range(60):
    x = random.randint(0, S); y = random.randint(0, S); d.ellipse([x, y, x + 10, y + 6], fill=(110, 80, 40))
for x in range(0, S, 22): d.rectangle([x, 0, x + 16, 30], fill=(190, 170, 100))
for c_ in range(2):
    x0 = 80 + c_ * 256; d.ellipse([x0, 190, x0 + 100, 260], fill=(230, 200, 40)); d.rectangle([x0 + 44, 195, x0 + 56, 255], fill=(20, 20, 10))
save(noise(img, 10), "bar_gator")
# cheap generic dives: painted cinder block, glass-block window, lit box sign band
DIVE = {"dive_bar": (150, 30, 30), "dive_twobuck": (200, 170, 40), "dive_cornertap": (40, 90, 60), "dive_lastcall": (40, 40, 60),
        "dive_happyhour": (210, 110, 40), "dive_tipsytom": (60, 90, 150), "dive_dollar": (70, 110, 70)}
for nm, col in DIVE.items():
    img = Image.new("RGB", (S, S), col); d = ImageDraw.Draw(img)
    for row in range(S // 32):
        off = 32 * (row % 2)
        for c2 in range(-1, S // 64 + 1):
            d.rectangle([c2 * 64 + off, row * 32, c2 * 64 + off + 62, row * 32 + 30], outline=tuple(max(0, v - 30) for v in col), width=2)
    d.rectangle([150, 180, 362, 320], fill=(200, 210, 215))
    for gx in range(150, 362, 26): d.line([gx, 180, gx, 320], fill=(150, 160, 165), width=3)
    for gy in range(180, 320, 26): d.line([150, gy, 362, gy], fill=(150, 160, 165), width=3)
    save(noise(img, 9), nm)
# interior extras
flat((70, 20, 90), 6, "velvet_cloth"); flat((24, 24, 26), 8, "rubber_floor"); flat((90, 120, 70), 10, "swamp_floor"); flat((222, 200, 150), 10, "sand")

# ---------------- house facades by real wall material and era (county records)
# One tile = one storey. Siding variants are near-white and tinted in-engine per house.
def lap(d, step, line, base_shadow):
    for y in range(0, S, step):
        d.rectangle([0, y + step - 3, S, y + step - 1], fill=line)
        d.line([0, y + 1, S, y + 1], fill=base_shadow)

def win(d, x0, y0, w, h, trim=(250, 250, 248), glass=(52, 62, 74), mull=2, arch=False, shutters=None, sill=True, tw=12):
    d.rectangle([x0 - tw, y0 - tw - (18 if arch else 0), x0 + w + tw, y0 + h + tw], fill=trim)
    if arch: d.pieslice([x0 - tw, y0 - tw - 40, x0 + w + tw, y0 + tw + 20], 180, 360, fill=trim)
    d.rectangle([x0, y0, x0 + w, y0 + h], fill=glass); WIN.append([x0, y0, x0 + w, y0 + h])
    if mull >= 1: d.line([x0, y0 + h * 0.48, x0 + w, y0 + h * 0.48], fill=trim, width=7)
    if mull >= 2: d.line([x0 + w / 2, y0, x0 + w / 2, y0 + h], fill=trim, width=5)
    if sill: d.rectangle([x0 - tw - 8, y0 + h + tw - 2, x0 + w + tw + 8, y0 + h + tw + 10], fill=(230, 228, 222))
    if shutters:
        d.rectangle([x0 - tw - 44, y0 - 4, x0 - tw - 6, y0 + h + 4], fill=shutters)
        d.rectangle([x0 + w + tw + 6, y0 - 4, x0 + w + tw + 44, y0 + h + 4], fill=shutters)

# old (pre-1915): narrow clapboard, tall narrow 2-over-2 window with heavy trim
img = Image.new("RGB", (S, S), (236, 234, 228)); d = ImageDraw.Draw(img); lap(d, 12, (190, 188, 182), (248, 247, 243))
win(d, 186, 95, 140, 300, arch=False, mull=1, tw=18); save(noise(img, 5), "h_clap_old")
# mid (1915-45 bungalow/foursquare): medium clapboard, paired double-hung windows
img = Image.new("RGB", (S, S), (236, 234, 228)); d = ImageDraw.Draw(img); lap(d, 16, (190, 188, 182), (248, 247, 243))
win(d, 110, 130, 130, 250, mull=1, tw=14); win(d, 272, 130, 130, 250, mull=1, tw=14); save(noise(img, 5), "h_clap_mid")
# post-war (1946-79 ranch/cape): wide vinyl/aluminum lap, wide picture window with shutters
img = Image.new("RGB", (S, S), (238, 237, 232)); d = ImageDraw.Draw(img); lap(d, 22, (196, 195, 190), (250, 249, 245))
win(d, 150, 150, 212, 200, mull=2, shutters=(70, 74, 72), tw=10); save(noise(img, 4), "h_clap_post")
# new (1980+): vinyl, window with grilles and shutters, higher sill
img = Image.new("RGB", (S, S), (240, 239, 235)); d = ImageDraw.Draw(img); lap(d, 20, (200, 199, 194), (252, 251, 248))
win(d, 186, 120, 140, 230, mull=2, shutters=(52, 58, 66), tw=10)
for k in range(3): d.line([186, 120 + 57 * (k + 1), 326, 120 + 57 * (k + 1)], fill=(250, 250, 248), width=3)
save(noise(img, 4), "h_clap_new")

def brickwall(base, var, mortar, h=12, w=34):
    img = Image.new("RGB", (S, S), mortar); d = ImageDraw.Draw(img)
    for row in range(S // h + 1):
        off = (w // 2) * (row % 2)
        for col in range(-1, S // w + 2):
            v = random.randint(-var, var)
            c = tuple(max(0, min(255, base[i] + v + random.randint(-6, 6))) for i in range(3))
            d.rectangle([col * w + off + 1, row * h + 1, col * w + off + w - 2, row * h + h - 2], fill=c)
    return img, d
img, d = brickwall((128, 52, 40), 18, (170, 160, 148)); win(d, 186, 100, 140, 290, trim=(222, 214, 198), mull=1, arch=True, tw=16)
save(noise(img, 5), "h_brick_old")
img, d = brickwall((140, 72, 50), 16, (180, 170, 156)); win(d, 110, 130, 130, 250, trim=(238, 234, 226), mull=1); win(d, 272, 130, 130, 250, trim=(238, 234, 226), mull=1)
save(noise(img, 5), "h_brick_mid")
img, d = brickwall((176, 112, 72), 22, (200, 192, 180), h=10, w=40); win(d, 150, 150, 212, 200, mull=2, shutters=(60, 64, 62), tw=10)
save(noise(img, 5), "h_brick_post")
img, d = brickwall((120, 84, 66), 14, (176, 168, 158)); win(d, 186, 120, 140, 230, mull=2, shutters=(40, 46, 54), tw=10)
save(noise(img, 4), "h_brick_new")
# stucco (1920s revival / some later)
img = Image.new("RGB", (S, S), (222, 210, 186)); d = ImageDraw.Draw(img); win(d, 150, 130, 212, 240, trim=(120, 92, 66), mull=2, tw=10)
img = noise(img, 14).filter(ImageFilter.GaussianBlur(0.6)); save(img, "h_stucco")
# stone
img = Image.new("RGB", (S, S), (150, 146, 138)); d = ImageDraw.Draw(img)
y = 0
while y < S:
    hh = random.randint(26, 48); x = -random.randint(0, 40)
    while x < S:
        ww = random.randint(40, 90); v = random.randint(-28, 22)
        d.rectangle([x + 2, y + 2, x + ww - 2, y + hh - 2], fill=(160 + v, 152 + v, 140 + v)); x += ww
    y += hh
win(d, 170, 130, 172, 240, trim=(232, 228, 218), mull=1); save(noise(img, 6), "h_stone")
# concrete block
img, d = brickwall((168, 166, 160), 8, (140, 138, 132), h=40, w=80); win(d, 196, 170, 120, 120, trim=(200, 200, 196), mull=1, tw=8)
save(noise(img, 6), "h_block")
img = Image.new("RGB", (S, S), (238, 237, 232)); d = ImageDraw.Draw(img); lap(d, 22, (196, 195, 190), (250, 249, 245)); save(noise(img, 4), "h_lap_plain")
