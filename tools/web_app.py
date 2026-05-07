#!/usr/bin/env python3
"""
Streamlit web UI — SVG → Iceors Color-by-Number converter.

Two modes:
  • SVG (auto)  — upload a vector SVG, all shapes parsed into Iceors lines
  • Manual      — click-build polygons over a raster image, color auto-detected

Run:
    cd tools/
    .venv/bin/streamlit run web_app.py
"""

from __future__ import annotations

import io
import zipfile

import streamlit as st

from svg_to_colorbynumber import OUTPUT_CANVAS, svg_to_lines

SP_FLAG = b"111\r\n"
LINE_SEP = "\r\n"

st.set_page_config(page_title="SVG → Color by Number", page_icon="🎨", layout="wide")
st.title("🎨 SVG → Color by Number")
st.caption(
    f"Output paths ở tọa độ **{OUTPUT_CANVAS}px** — match Android "
    "`IceorsAsset canvasSize`. Workflow đề xuất: AI sinh PNG → "
    "[vectorizer.ai](https://vectorizer.ai) → upload SVG ở đây."
)

# ── Mode selector ─────────────────────────────────────────────────────────────
mode = st.sidebar.radio(
    "Mode", ["SVG (auto)", "Manual (vẽ tay từ ảnh raster)"],
    index=0, key="app_mode",
    help="SVG: parse shapes từ file vector. Manual: click polygon trên ảnh.",
)
st.sidebar.markdown("---")

if mode.startswith("Manual"):
    from manual_mode import render_manual_mode
    render_manual_mode()
    st.stop()

# ── SVG mode ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Settings")

    uploaded = st.file_uploader("Upload SVG file", type=["svg"])
    ref_image_file = st.file_uploader(
        "Optional reference image (PNG/JPG)",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        help="Nếu để trống → tool render JPEG từ chính SVG. "
             "Nếu upload riêng (vd: ảnh AI gốc trước khi vectorize) → "
             "ảnh đó sẽ được align center-pad vuông để khớp với paths.",
    )
    asset_key = st.text_input(
        "Asset key", value="asset",
        help="Tên file bên trong ZIP: {key}b. Không dùng dấu cách.",
    )

    st.markdown("---")
    st.markdown("**Outlines**")
    add_outline = st.toggle(
        "Tự động thêm nét đen quanh mỗi vùng fill", value=True,
        help="Mỗi fill region sẽ kèm 1 STROKE_LINE đen viền theo nó. "
             "Giúp nhìn rõ các vùng trong app khi chưa tô.",
    )
    outline_width = st.slider(
        "Outline width (px on 2048 canvas)", 0.5, 5.0, 1.5, 0.5,
        disabled=not add_outline,
    )

    st.markdown("---")
    st.markdown("**Color palette**")
    merge_tolerance = st.slider(
        "Merge similar colors (RGB distance)", 0, 50, 15,
        help="Vectorizer thường output mỗi vùng 1 shade hơi khác nhau "
             "(anti-aliasing). Giá trị > 0 sẽ gộp các shade gần giống thành "
             "1 màu. Lớn hơn = gộp aggressive hơn. Đặt 0 để tắt.",
    )

    st.markdown("---")
    subtract = st.toggle(
        "Subtract overlaps", value=True,
        help="Mỗi vùng chỉ phủ pixels unique của nó (không overlap vùng khác). "
             "Bật cho output cleaner.",
    )

if uploaded is None:
    st.info("Upload file SVG ở sidebar để bắt đầu.")
    st.markdown(
        """
**Tips để có SVG tốt:**
- Mỗi vùng màu → 1 `<path>` / `<polygon>` riêng với `fill` solid (không gradient)
- Nét đen cho coloring book → `<path>` với `stroke="black"` + `stroke-width`
- viewBox nên vuông (1:1) — nếu không, tool sẽ pad vuông tự động
- AI vector tools: [vectorizer.ai](https://vectorizer.ai), [recraft.ai](https://recraft.ai),
  Adobe Illustrator Image Trace, Inkscape (path → trace bitmap)
"""
    )
    st.stop()

# ── Process ───────────────────────────────────────────────────────────────────
log: list[str] = []
svg_bytes = uploaded.read()

try:
    lines, _ = svg_to_lines(
        io.BytesIO(svg_bytes),
        subtract_overlaps=subtract,
        auto_outline_width=outline_width if add_outline else 0.0,
        color_merge_tolerance=float(merge_tolerance),
        log=log.append,
    )
except Exception as e:
    st.error(f"Parse failed: {e}")
    st.stop()

if not lines:
    st.error("Không trích được shape nào từ SVG.")
    st.stop()

# ── Stats ─────────────────────────────────────────────────────────────────────
fill_n = sum(1 for line in lines if line.split("|")[2].strip() == "0")
stroke_n = len(lines) - fill_n

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fill regions", fill_n)
c2.metric("Stroke lines", stroke_n)
c3.metric("Total", len(lines))
c4.metric("Output canvas", f"{OUTPUT_CANVAS}px")

def _lines_to_preview_svg(lines: list[str], only_black: bool = False) -> str:
    """Render Iceors lines back to an SVG for visual diffing."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {OUTPUT_CANVAS} {OUTPUT_CANVAS}" '
        f'width="100%" style="background:white;border:1px solid #ddd;border-radius:8px">'
    ]
    for line in lines:
        cols = line.split("|")
        if len(cols) < 3:
            continue
        d, color, sw = cols[0], cols[1], cols[2]
        is_black = color.strip() == "000000" or color.strip() == "0"
        
        if only_black and not is_black and sw.strip() == "0":
            continue

        if sw.strip() == "0":
            parts.append(f'<path d="{d}" fill="#{color}" fill-rule="evenodd"/>')
        else:
            # Strokes are always black outlines in Iceors
            parts.append(
                f'<path d="{d}" fill="none" stroke="black" stroke-width="{sw}"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


# ── Preview ───────────────────────────────────────────────────────────────────
st.subheader("Preview")
col_orig, col_render, col_black = st.columns(3)
with col_orig:
    st.caption("Original SVG")
    st.markdown(
        f'<div style="background:#fff;padding:12px;border-radius:8px;'
        f'border:1px solid #ddd">{svg_bytes.decode("utf-8", errors="ignore")}</div>',
        unsafe_allow_html=True,
    )
with col_render:
    st.caption("All Layers (Full Preview)")
    st.markdown(_lines_to_preview_svg(lines), unsafe_allow_html=True)
with col_black:
    st.caption("Black Outlines (Non-paintable)")
    st.markdown(_lines_to_preview_svg(lines, only_black=True), unsafe_allow_html=True)

# ── Build ZIP ─────────────────────────────────────────────────────────────────
key = asset_key.strip() or "asset"
data_bytes = LINE_SEP.join(lines).encode("utf-8")


def make_zip(with_image: bool, ref_jpeg: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{key}b", data_bytes)
        zf.writestr("sp_new_paint_flag", SP_FLAG)
        if with_image and ref_jpeg:
            zf.writestr(f"{key}c", ref_jpeg)
    return buf.getvalue()


# ── Reference JPEG ────────────────────────────────────────────────────────────
# Cả paths và image phải share đúng hệ tọa độ:
#   side = max(sw, sh)              ← cạnh hình vuông trong source space
#   scale = OUTPUT_CANVAS / side    ← scale lên 2048
#   image padded center: offset_x = (OUTPUT_CANVAS - rendered_w) / 2 ...
# Nguyên tắc: ảnh nào (SVG render hay user upload) cũng được fit-into-aspect-of-SVG
# rồi center-pad → khớp với pad của paths.
def _to_square_jpeg(pil_img, sw: float, sh: float) -> bytes:
    """
    Stretch `pil_img` về đúng kích thước khung SVG paths trong canvas
    (target_w × target_h), rồi center-pad trắng thành OUTPUT_CANVAS².
    Không letterbox — pixel image phủ kín đúng vùng paths cover.
    """
    from PIL import Image as _PILImage
    side = max(sw, sh) or 1
    scale = OUTPUT_CANVAS / side
    target_w = max(1, int(round(sw * scale)))
    target_h = max(1, int(round(sh * scale)))

    # Stretch về đúng SVG aspect — không giữ aspect ratio gốc của image
    fit = pil_img.resize((target_w, target_h), _PILImage.LANCZOS)

    # Center-pad lên OUTPUT_CANVAS² (chỉ pad nếu SVG aspect không vuông)
    square = _PILImage.new("RGB", (OUTPUT_CANVAS, OUTPUT_CANVAS), (255, 255, 255))
    square.paste(fit, ((OUTPUT_CANVAS - target_w) // 2, (OUTPUT_CANVAS - target_h) // 2))

    buf = io.BytesIO()
    square.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


ref_jpeg: bytes | None = None
try:
    from PIL import Image as _PILImage
    from svgelements import SVG as _SVG

    # SVG aspect (paths được pad theo cái này)
    parsed = _SVG.parse(io.BytesIO(svg_bytes))
    if parsed.viewbox is not None:
        sw = float(parsed.viewbox.width)
        sh = float(parsed.viewbox.height)
    else:
        sw = float(parsed.width or OUTPUT_CANVAS)
        sh = float(parsed.height or OUTPUT_CANVAS)

    if ref_image_file is not None:
        # User upload ảnh riêng — fit vào SVG aspect rồi pad vuông
        pil = _PILImage.open(ref_image_file).convert("RGBA")
        white = _PILImage.new("RGBA", pil.size, (255, 255, 255, 255))
        pil = _PILImage.alpha_composite(white, pil).convert("RGB")
        ref_jpeg = _to_square_jpeg(pil, sw, sh)
        log.append(
            f"reference JPEG: user upload {pil.size}, fit aspect "
            f"{sw:.0f}:{sh:.0f}, pad → {OUTPUT_CANVAS}²"
        )
    else:
        # Render từ chính SVG
        import cairosvg
        side = max(sw, sh) or 1
        scale = OUTPUT_CANVAS / side
        render_w = max(1, int(round(sw * scale)))
        render_h = max(1, int(round(sh * scale)))
        png_bytes = cairosvg.svg2png(
            bytestring=svg_bytes,
            output_width=render_w,
            output_height=render_h,
        )
        pil = _PILImage.open(io.BytesIO(png_bytes)).convert("RGB")
        ref_jpeg = _to_square_jpeg(pil, sw, sh)
        log.append(f"reference JPEG: rendered SVG {render_w}×{render_h} → {OUTPUT_CANVAS}²")
except Exception as exc:
    log.append(f"(no reference JPEG: {exc})")
    try:
        from PIL import Image as _PILImage
        blank = _PILImage.new("RGB", (OUTPUT_CANVAS, OUTPUT_CANVAS), (255, 255, 255))
        jbuf = io.BytesIO()
        blank.save(jbuf, format="JPEG", quality=85)
        ref_jpeg = jbuf.getvalue()
    except Exception:
        ref_jpeg = None

# Debug expander — hiển thị reference JPEG sẽ ghi vào {key}c
with st.expander(f"🔍 Debug: reference JPEG ({key}c trong ZIP)", expanded=False):
    if ref_jpeg:
        st.caption(
            f"Ảnh nhúng vào ZIP làm reveal layer (size {len(ref_jpeg):,} bytes). "
            "Pixel (cx, cy) ở đây phải khớp pixel paths phủ — nếu vùng image "
            "trắng ở đâu, paths ở đó sẽ thấy trắng khi tô."
        )
        # Overlay paths (đỏ semi-transparent) lên image để verify alignment
        overlay_svg = (
            f'<div style="position:relative;width:100%;max-width:600px">'
            f'<img src="data:image/jpeg;base64,'
            + __import__("base64").b64encode(ref_jpeg).decode()
            + f'" style="width:100%;display:block"/>'
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {OUTPUT_CANVAS} {OUTPUT_CANVAS}" '
            f'style="position:absolute;top:0;left:0;width:100%;height:100%;'
            f'opacity:0.5">'
        )
        for line in lines[:200]:   # cap để render nhẹ
            cols = line.split("|")
            if len(cols) < 3 or cols[2].strip() != "0":
                continue
            overlay_svg += f'<path d="{cols[0]}" fill="red" fill-opacity="0.3" stroke="red" stroke-width="1"/>'
        overlay_svg += "</svg></div>"
        st.markdown("**Reference image alone:**")
        st.image(ref_jpeg, use_container_width=True)
        st.markdown("**Image + paths overlay (red = path coverage):**")
        st.markdown(overlay_svg, unsafe_allow_html=True)
    else:
        st.warning("ref_jpeg = None — kiểm tra log")

# ── Download ──────────────────────────────────────────────────────────────────
st.subheader("Download")
dl1, dl2 = st.columns(2)

with dl1:
    st.download_button(
        f"⬇️  Data only  ({key}b + flag)",
        data=make_zip(False),
        file_name=f"{key}_b.zip",
        mime="application/zip",
        use_container_width=True,
        help=f"ZIP: {key}b + sp_new_paint_flag",
    )

with dl2:
    st.download_button(
        f"⬇️  Data + Image  ({key}b + {key}c + flag)",
        data=make_zip(True, ref_jpeg),
        file_name=f"{key}_b.zip",
        mime="application/zip",
        use_container_width=True,
        type="primary",
        disabled=ref_jpeg is None,
        help="Cần `cairosvg` để render reference JPEG. " +
             ("OK." if ref_jpeg else "Chưa cài: `pip install cairosvg`."),
    )

with st.expander("ZIP structure"):
    img_size = len(ref_jpeg) if ref_jpeg else 0
    st.code(
        f"{key}_b.zip\n"
        f"├── {key}b              ← path data ({len(data_bytes):,} bytes, CRLF)\n"
        + (f"├── {key}c              ← JPEG {OUTPUT_CANVAS}×{OUTPUT_CANVAS} ({img_size:,} bytes)\n" if ref_jpeg else "")
        + "└── sp_new_paint_flag   ← \"111\\r\\n\"",
        language="text",
    )

with st.expander("Log"):
    st.text("\n".join(log))
