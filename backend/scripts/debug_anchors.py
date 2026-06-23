"""debug_anchors.py — inspect how question-number anchors are encoded."""
import os, re, sys
import fitz

DOWNLOADS = os.path.expanduser(r"~/Downloads")
pdf = sys.argv[1] if len(sys.argv) > 1 else "0580_w22_qp_42.pdf"
pages = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None

doc = fitz.open(os.path.join(DOWNLOADS, pdf))
for pi in range(len(doc)):
    if pages is not None and pi not in pages:
        continue
    page = doc[pi]
    print(f"\n=== page index {pi} (printed p{pi+1}) ===")
    d = page.get_text("dict")
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                x0, y0 = span["bbox"][0], span["bbox"][1]
                txt = span["text"]
                # left-margin candidates below the header band
                if x0 < 85 and y0 > 55:
                    print(f"  x0={x0:6.1f} y0={y0:6.1f} font={span['font']:<22} "
                          f"size={span['size']:4.1f} flags={span['flags']} text={txt!r}")
