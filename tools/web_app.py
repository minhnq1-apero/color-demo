#!/usr/bin/env python3
"""
Streamlit web UI — Image → Color-by-Number converter.

Run:
    cd tools/
    .venv/bin/streamlit run web_app.py
"""

from __future__ import annotations

import io
import zipfile

import cv2
import numpy as np
import streamlit as st
from PIL import Image

from image_to_colorbynumber import OUTPUT_CANVAS, process_array

SP_FLAG = b"111\r\n"
LINE_SEP = "\r\n"

st.set_page_config(page_title="Image → Color by Number", page_icon="🎨", layout="wide")
st.title("🎨 Image → Color by Number")
st.caption(
    f"Output paths luôn ở tọa độ **{OUTPUT_CANVAS}px** — "
    "match Android `IceorsAsset canvasSize` mặc định."
)

# ── Mode selector ─────────────────────────────────────────────────────────────
mode = st.sidebar.radio(
    "Mode", ["Auto (K-means)", "Manual (vẽ tay)"],
    index=0, key="app_mode",
    help="Auto: tự động chia màu bằng K-means. Manual: vẽ tay từng vùng, màu auto-detect.",
)
st.sidebar.markdown("---")

if mode.startswith("Manual"):
    from manual_mode import render_manual_mode
    render_manual_mode()
    st.stop()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")

    uploaded = st.file_uploader("Upload image", type=["jpg", "jpeg", "png", "webp", "bmp", "svg"])

    asset_key = st.text_input("Asset key", value="asset",
        help="Tên file bên trong ZIP: {key}b, {key}c. Không dùng dấu cách.")

    st.markdown("---")
    st.markdown("**Palette**")
    n_colors = st.slider("Số màu", 10, 40, 20)

    quality = st.radio(
        "Quality / Tốc độ",
        ["Fast (K-means @ 1024px, ~15s)", "Full (K-means @ 2048px, ~60s)"],
        index=0,
        help="Output paths LUÔN ở 2048px bất kể chọn gì. "
             "Fast: K-means chạy trên ảnh 1024px (nhanh hơn ~4x), "
             "rồi scale label map lên 2048 để lấy contour.",
    )
    kmeans_size = 1024 if quality.startswith("Fast") else OUTPUT_CANVAS

    st.markdown("---")
    st.markdown("**Sketch outlines**")
    include_strokes = st.toggle("Thêm nét sketch (STROKE_LINE)", value=True)
    canny_low  = st.slider("Canny low",  10, 150, 50,  disabled=not include_strokes)
    canny_high = st.slider("Canny high", 50, 300, 150, disabled=not include_strokes)
    stroke_width = st.slider("Stroke width", 0.5, 4.0, 1.5, 0.5, disabled=not include_strokes)

    st.markdown("---")
    st.markdown("**Regions**")
    min_area = st.number_input("Min fill area (px²)", 0, 2000, 300, 50,
        help="Vùng nhỏ hơn số này bị bỏ qua. Tăng lên nếu quá nhiều fill regions.")

    generate = st.button("Convert", type="primary", use_container_width=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def palette_strip(colors: list[tuple[int,int,int]], h: int = 48) -> Image.Image:
    n = len(colors)
    sw = max(28, min(60, 640 // n))
    arr = np.zeros((h, sw * n, 3), dtype=np.uint8)
    for i, (r, g, b) in enumerate(colors):
        arr[:, i*sw:(i+1)*sw] = (r, g, b)
    return Image.fromarray(arr)


def count(lines: list[str]) -> tuple[int, int]:
    fill = stroke = 0
    for l in lines:
        p = l.split("|")
        if len(p) >= 3:
            (fill := fill + 1) if p[2].strip() == "0" else (stroke := stroke + 1)
    return fill, stroke


def make_zip(key: str, data: bytes, ref_jpeg: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{key}b", data)
        zf.writestr("sp_new_paint_flag", SP_FLAG)
        if ref_jpeg:
            zf.writestr(f"{key}c", ref_jpeg)
    return buf.getvalue()


def to_jpeg(img_rgb: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR),
                           [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


def _parse_svg_to_points(svg: str) -> list[list[float]]:
    """Parse SVG path (M, L, C, Z) thành danh sách điểm, sampling Bézier curves."""
    import re
    pts = []
    # Tách thành các token: M/L/C/Z + toạ độ
    tokens = re.findall(r'[MLCZ]|[-+]?\d*\.?\d+', svg)
    i = 0
    cx, cy = 0.0, 0.0
    while i < len(tokens):
        cmd = tokens[i]
        if cmd == 'M':
            cx, cy = float(tokens[i+1]), float(tokens[i+2])
            pts.append([cx, cy])
            i += 3
        elif cmd == 'L':
            cx, cy = float(tokens[i+1]), float(tokens[i+2])
            pts.append([cx, cy])
            i += 3
        elif cmd == 'C':
            # Cubic Bézier: cp1, cp2, end
            cp1x, cp1y = float(tokens[i+1]), float(tokens[i+2])
            cp2x, cp2y = float(tokens[i+3]), float(tokens[i+4])
            ex, ey = float(tokens[i+5]), float(tokens[i+6])
            # Sample curve thành 8 đoạn nhỏ
            for t_i in range(1, 9):
                t = t_i / 8.0
                u = 1 - t
                x = u*u*u*cx + 3*u*u*t*cp1x + 3*u*t*t*cp2x + t*t*t*ex
                y = u*u*u*cy + 3*u*u*t*cp1y + 3*u*t*t*cp2y + t*t*t*ey
                pts.append([x, y])
            cx, cy = ex, ey
            i += 7
        elif cmd == 'Z':
            i += 1
        else:
            i += 1
    return pts


def _split_svg_subpaths(svg: str) -> list[str]:
    """Tách composite SVG path thành các sub-path riêng biệt (tại mỗi lệnh M)."""
    import re
    # Tách tại mỗi 'M' nhưng giữ lại 'M'
    parts = re.split(r'(?=M)', svg)
    return [p for p in parts if p.strip()]


def draw_android_preview(lines: list[str], canvas_size: int = 2048) -> np.ndarray:
    """Simulates Android IceorsView drawing logic by parsing and rendering the SVG lines."""
    img = np.ones((canvas_size, canvas_size, 3), dtype=np.uint8) * 255
    for line in lines:
        parts = line.split("|")
        if len(parts) < 3: continue
        svg = parts[0]
        color_hex = parts[1]
        stroke_width = float(parts[2])
        is_closed = "Z" in svg

        if stroke_width == 0:
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            # Tách sub-paths (outer + holes) để fillPoly khoét lỗ đúng
            sub_paths = _split_svg_subpaths(svg)
            contours = []
            for sp in sub_paths:
                pts = _parse_svg_to_points(sp)
                if pts:
                    contours.append(np.array(pts, dtype=np.int32))
            if contours:
                cv2.fillPoly(img, contours, (r, g, b))
        else:
            pts = _parse_svg_to_points(svg)
            if not pts: continue
            pts_arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(img, [pts_arr], isClosed=is_closed, color=(0,0,0), thickness=max(1, int(stroke_width)))
    return img


# ── Main ──────────────────────────────────────────────────────────────────────

if uploaded is None:
    st.info("Upload ảnh ở sidebar để bắt đầu.")
    st.stop()

# Xử lý SVG: render thành PNG trước khi process
filename = uploaded.name.lower()
if filename.endswith(".svg"):
    import cairosvg
    svg_bytes = uploaded.read()
    png_bytes = cairosvg.svg2png(bytestring=svg_bytes, output_width=2048, output_height=2048)
    pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
else:
    pil_img = Image.open(uploaded).convert("RGBA")

# Nền trong suốt → trắng
white_bg = Image.new("RGBA", pil_img.size, (255, 255, 255, 255))
pil_img = Image.alpha_composite(white_bg, pil_img).convert("RGB")

# Pad thành hình vuông (center, nền trắng) — canvas luôn là 1:1
w, h = pil_img.size
if w != h:
    side = max(w, h)
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(pil_img, ((side - w) // 2, (side - h) // 2))
    pil_img = square

img_rgb = np.array(pil_img)

col_orig, col_preview = st.columns(2)

with col_orig:
    st.subheader("Original")
    st.image(img_rgb, use_container_width=True)

if not generate:
    with col_preview:
        st.subheader("Preview")
        st.markdown(
            "<div style='height:260px;display:flex;align-items:center;"
            "justify-content:center;background:#f0f0f0;border-radius:8px;"
            "color:#888'>Nhấn Convert để xử lý</div>",
            unsafe_allow_html=True,
        )
    st.stop()

# ── Processing ────────────────────────────────────────────────────────────────
log: list[str] = []

with st.spinner(f"Đang xử lý… (K-means @ {kmeans_size}px)"):
    lines, _, palette = process_array(
        img_rgb,
        n_colors=n_colors,
        kmeans_size=kmeans_size,
        canny_low=canny_low,
        canny_high=canny_high,
        min_fill_area=int(min_area),
        stroke_width=stroke_width,
        include_strokes=include_strokes,
        log=log.append,
    )
    
    # Sinh ảnh preview mô phỏng chính xác cách Android IceorsView vẽ các SVG lines
    android_preview = draw_android_preview(lines, OUTPUT_CANVAS)

with col_preview:
    st.subheader("Preview (Android View)")
    st.image(android_preview, use_container_width=True)
    st.caption("Ảnh này mô phỏng chính xác 100% cách Android app vẽ file output.txt")

# ── Palette ───────────────────────────────────────────────────────────────────
st.subheader("Palette")
st.image(palette_strip(palette), use_container_width=True)
st.caption("  ·  ".join(f"#{r:02X}{g:02X}{b:02X}" for r, g, b in palette))

# ── Stats ─────────────────────────────────────────────────────────────────────
fill_n, stroke_n = count(lines)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Fill regions",    fill_n)
c2.metric("Stroke lines",    stroke_n)
c3.metric("Total",           len(lines))
c4.metric("Output canvas",   f"{OUTPUT_CANVAS}px")

# ── Build ZIP artifacts ───────────────────────────────────────────────────────
key = asset_key.strip() or "asset"
data_bytes = LINE_SEP.join(lines).encode("utf-8")

ref_rgb  = cv2.resize(img_rgb, (OUTPUT_CANVAS, OUTPUT_CANVAS), interpolation=cv2.INTER_AREA)
ref_jpeg = to_jpeg(ref_rgb)

zip_data_only  = make_zip(key, data_bytes)
zip_with_image = make_zip(key, data_bytes, ref_jpeg)

# ── Download ──────────────────────────────────────────────────────────────────
st.subheader("Download")
dl1, dl2 = st.columns(2)

with dl1:
    st.download_button(
        f"⬇️  Data only  ({key}b + flag)",
        data=zip_data_only,
        file_name=f"{key}_b.zip",
        mime="application/zip",
        use_container_width=True,
        help=f"ZIP: {key}b + sp_new_paint_flag",
    )

with dl2:
    st.download_button(
        f"⬇️  Data + Image  ({key}b + {key}c + flag)",
        data=zip_with_image,
        file_name=f"{key}_b.zip",
        mime="application/zip",
        use_container_width=True,
        help=f"ZIP: {key}b + {key}c (JPEG {OUTPUT_CANVAS}×{OUTPUT_CANVAS}) + sp_new_paint_flag",
    )

with st.expander("ZIP structure"):
    st.code(
        f"{key}_b.zip\n"
        f"├── {key}b              ← path data  ({len(data_bytes):,} bytes, CRLF)\n"
        f"├── {key}c              ← JPEG {OUTPUT_CANVAS}×{OUTPUT_CANVAS} ({len(ref_jpeg):,} bytes)\n"
        f"└── sp_new_paint_flag   ← \"111\\r\\n\"",
        language="text",
    )

with st.expander("Log"):
    st.text("\n".join(log))
