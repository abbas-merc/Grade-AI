"""montage.py — tile all extracted diagram crops into per-paper contact sheets
so every match can be eyeballed at once for gross errors."""
import json, os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "diagram_out")

manifest = json.load(open(os.path.join(OUT, "_manifest.json"), encoding="utf-8"))
by_paper = {}
for m in manifest:
    by_paper.setdefault(m["paperCode"], []).append(m)

THUMB_W, THUMB_H, PADX, PADY, LABEL_H, COLS = 250, 320, 12, 30, 18, 4

for code, items in by_paper.items():
    items.sort(key=lambda m: m["qNo"])
    rows = (len(items) + COLS - 1) // COLS
    cell_w = THUMB_W + PADX
    cell_h = THUMB_H + LABEL_H + PADY
    sheet = Image.new("RGB", (cell_w * COLS, cell_h * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for i, m in enumerate(items):
        cx = (i % COLS) * cell_w + PADX // 2
        cy = (i // COLS) * cell_h + PADY // 2
        label = f"Q{m['qNo']}  {m['status']}  r={m.get('nRegions',0)}"
        draw.text((cx, cy), label, fill="black")
        if m["status"] == "OK":
            im = Image.open(os.path.join(HERE, m["png"])).convert("RGB")
            im.thumbnail((THUMB_W, THUMB_H))
            sheet.paste(im, (cx, cy + LABEL_H))
            draw.rectangle(
                [cx - 2, cy + LABEL_H - 2, cx + im.width + 2, cy + LABEL_H + im.height + 2],
                outline="#cccccc",
            )
        else:
            draw.rectangle([cx, cy + LABEL_H, cx + THUMB_W, cy + THUMB_H], outline="red")
            draw.text((cx + 10, cy + LABEL_H + 40), "NO FIGURE\n(no diagram\nin source)", fill="red")
    tag = code.replace("/", "_")
    path = os.path.join(OUT, f"_sheet_{tag}.png")
    sheet.save(path)
    print(path)
