"""One-off generator for og-image.png. Re-run manually if the hero copy or company count changes meaningfully."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = "#0b1220"
ACCENT = "#a8541c"
INK = "#f2f5f7"
DIM = "#97a2b0"

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

georgia_bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia Bold.ttf", 64)
mono = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 22)
mono_small = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 20)
georgia = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 30)

pad = 90

# accent square + R mark (mirrors the favicon)
d.rounded_rectangle([pad, 70, pad + 56, 126], radius=10, fill=ACCENT)
d.text((pad + 28, 98), "R", font=georgia_bold, fill="white", anchor="mm")

d.text((pad + 74, 98), "Robotics.xyz", font=georgia, fill=INK, anchor="lm")

d.text((pad, 230), "Every robot builder,", font=georgia_bold, fill=INK)
d.text((pad, 305), "mapped in one place", font=georgia_bold, fill=INK)

d.text((pad, 400), "A self-updating market map of the robotics industry —", font=mono_small, fill=DIM)
d.text((pad, 432), "companies, funding, open roles, and news, synced daily.", font=mono_small, fill=DIM)

# stat chips
chips = [("88+", "Companies"), ("Daily", "Data sync"), ("Claude", "Agent-researched")]
x = pad
y = 510
for value, label in chips:
    d.text((x, y), value, font=mono, fill=ACCENT)
    d.text((x, y + 32), label, font=mono_small, fill=DIM)
    x += 260

img.save("og-image.png")
print("wrote og-image.png", img.size)
