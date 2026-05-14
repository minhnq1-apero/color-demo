#!/usr/bin/env python3
"""
Streamlit web UI — SVG → Iceors Color-by-Number converter.

Upload a vector SVG; all shapes are parsed into Iceors lines.

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
    st.markdown("**Raster Line Extraction (OpenCV)**")
    use_raster = st.toggle(
        "Lấy nét đen từ ảnh grayscale (OpenCV)", value=False,
        help="Render SVG thành ảnh xám rồi dùng OpenCV quét nét. "
             "Dùng khi SVG có nét đen mờ hoặc không đồng nhất.",
    )
    raster_threshold = st.slider(
        "Raster threshold", 50, 250, 200, 5,
        disabled=not use_raster,
        help="Giá trị thấp hơn = lấy nét đậm hơn.",
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
        use_raster_lines=use_raster,
        raster_threshold=raster_threshold,
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

import re

def _clean_svg_for_preview(svg_str: str) -> str:
    """
    Ensure the SVG scales correctly:
    1. Find existing width/height/viewBox.
    2. If no viewBox, try to create one from width/height.
    3. Remove width/height attributes so it's responsive.
    """
    # Try to find viewBox
    vb_match = re.search(r'viewBox\s*=\s*["\']([^"\']+)["\']', svg_str, re.I)
    w_match = re.search(r'\swidth\s*=\s*["\']([^"\'%]+)["\']', svg_str, re.I)
    h_match = re.search(r'\sheight\s*=\s*["\']([^"\'%]+)["\']', svg_str, re.I)

    new_svg = svg_str
    if not vb_match and w_match and h_match:
        # Create viewBox from width and height if missing
        w, h = w_match.group(1), h_match.group(1)
        # Clean numeric values (remove px, etc.)
        w_num = re.sub(r'[^\d.]', '', w)
        h_num = re.sub(r'[^\d.]', '', h)
        if w_num and h_num:
            new_svg = re.sub(r'(<svg[^>]*?)', rf'\1 viewBox="0 0 {w_num} {h_num}"', new_svg, count=1, flags=re.I)

    # Strip width and height from the root <svg> tag
    new_svg = re.sub(r'(<svg[^>]*?)\s+width="[^"]*"', r'\1', new_svg, flags=re.I)
    new_svg = re.sub(r'(<svg[^>]*?)\s+height="[^"]*"', r'\1', new_svg, flags=re.I)
    
    # Ensure it has an xmlns if missing (required for data URI)
    if 'xmlns="http://www.w3.org/2000/svg"' not in new_svg:
        new_svg = new_svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
        
    return new_svg

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _path_d_bbox(d: str) -> tuple[float, float, float, float] | None:
    """
    Quick & approximate bbox of a path d string by scanning every numeric pair.
    Includes Bézier control points (so it overestimates), which is exactly
    what we want for a safe-fit viewBox.
    """
    nums = [float(m.group()) for m in _NUM_RE.finditer(d)]
    if len(nums) < 2:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _lines_to_preview_svg(lines: list[str], only_black: bool = False) -> str:
    """Render Iceors lines back to an SVG string with a fit-to-content viewBox."""
    body: list[str] = []
    bx0 = by0 = float("inf")
    bx1 = by1 = float("-inf")

    for line in lines:
        cols = line.split("|")
        if len(cols) < 3:
            continue
        d, color, sw = cols[0], cols[1], cols[2]
        is_black = color.strip() == "000000" or color.strip() == "0"

        if only_black and not is_black and sw.strip() == "0":
            continue

        bb = _path_d_bbox(d)
        if bb is not None:
            x0, y0, x1, y1 = bb
            if x0 < bx0: bx0 = x0
            if y0 < by0: by0 = y0
            if x1 > bx1: bx1 = x1
            if y1 > by1: by1 = y1

        if sw.strip() == "0":
            body.append(f'<path d="{d}" fill="#{color}" fill-rule="evenodd"/>')
        else:
            body.append(
                f'<path d="{d}" fill="none" stroke="black" stroke-width="{sw}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>'
            )

    # Fit viewBox to the union of (canvas, path bbox) so nothing gets clipped
    # even if paths extend beyond [0, OUTPUT_CANVAS] for any reason.
    if bx0 == float("inf"):
        vx, vy, vw, vh = 0.0, 0.0, float(OUTPUT_CANVAS), float(OUTPUT_CANVAS)
    else:
        vx = min(0.0, bx0)
        vy = min(0.0, by0)
        vw = max(float(OUTPUT_CANVAS), bx1) - vx
        vh = max(float(OUTPUT_CANVAS), by1) - vy

    header = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}">'
        f'<rect x="0" y="0" width="{OUTPUT_CANVAS}" height="{OUTPUT_CANVAS}" fill="white"/>'
    )
    return header + "".join(body) + "</svg>"


def _render_inline_svg(svg_str: str) -> str:
    """Wrap SVG in a responsive container so browsers render it at column width."""
    cleaned = _clean_svg_for_preview(svg_str)
    # Force the SVG to fill its container width while keeping aspect via viewBox.
    cleaned = re.sub(
        r'<svg\b',
        '<svg style="width:100%;height:auto;display:block"',
        cleaned, count=1,
    )
    return (
        '<div style="background:#fff;padding:8px;border:1px solid #ddd;'
        'border-radius:8px">' + cleaned + '</div>'
    )

# ── Preview ───────────────────────────────────────────────────────────────────
st.subheader("Preview")
col_orig, col_render, col_black = st.columns(3)

# Prepare SVG strings
orig_svg_str = svg_bytes.decode("utf-8", errors="ignore")
render_svg_str = _lines_to_preview_svg(lines)
black_svg_str = _lines_to_preview_svg(lines, only_black=True)

# Diagnostic: report path bbox so we can spot overflow vs the canvas
_all_x: list[float] = []
_all_y: list[float] = []
for _line in lines:
    _cols = _line.split("|")
    if len(_cols) >= 1:
        _bb = _path_d_bbox(_cols[0])
        if _bb is not None:
            _all_x.extend([_bb[0], _bb[2]])
            _all_y.extend([_bb[1], _bb[3]])
if _all_x and _all_y:
    _x0, _x1 = min(_all_x), max(_all_x)
    _y0, _y1 = min(_all_y), max(_all_y)
    log.append(
        f"path bbox: x=[{_x0:.1f}, {_x1:.1f}] y=[{_y0:.1f}, {_y1:.1f}] "
        f"vs canvas [0, {OUTPUT_CANVAS}]"
    )
    if _x0 < -1 or _y0 < -1 or _x1 > OUTPUT_CANVAS + 1 or _y1 > OUTPUT_CANVAS + 1:
        st.warning(
            f"⚠️ Paths overflow canvas: x=[{_x0:.0f}, {_x1:.0f}] "
            f"y=[{_y0:.0f}, {_y1:.0f}] (canvas = {OUTPUT_CANVAS}). "
            "Preview viewBox auto-expanded; cần fix bake transform trong "
            "svg_to_colorbynumber.py."
        )

with col_orig:
    st.caption("Original SVG")
    st.markdown(_render_inline_svg(orig_svg_str), unsafe_allow_html=True)

with col_render:
    st.caption("Full Preview")
    st.markdown(_render_inline_svg(render_svg_str), unsafe_allow_html=True)

with col_black:
    st.caption("Black Outlines (Fixed)")
    st.markdown(_render_inline_svg(black_svg_str), unsafe_allow_html=True)

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

    # SVG aspect (paths được pad theo cái này). Phải dùng svg.width/height
    # giống bake transform trong svg_to_colorbynumber — svgelements bake outer
    # viewBox→width transform vào path coords, nên paths nằm trong
    # `svg.width × svg.height` pixel space, không phải viewBox space.
    parsed = _SVG.parse(io.BytesIO(svg_bytes))
    sw = float(parsed.width) if parsed.width else 0.0
    sh = float(parsed.height) if parsed.height else 0.0
    if sw <= 0 or sh <= 0:
        if parsed.viewbox is not None:
            sw = float(parsed.viewbox.width)
            sh = float(parsed.viewbox.height)
        else:
            sw = sh = float(OUTPUT_CANVAS)

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

dl3, dl4 = st.columns(2)
try:
    import cairosvg
    with dl3:
        full_preview_png = cairosvg.svg2png(bytestring=render_svg_str.encode("utf-8"))
        st.download_button(
            "🖼️  Export Full Preview (PNG)",
            data=full_preview_png,
            file_name=f"{key}_full_preview.png",
            mime="image/png",
            use_container_width=True,
        )
    with dl4:
        black_preview_png = cairosvg.svg2png(bytestring=black_svg_str.encode("utf-8"))
        st.download_button(
            "🖼️  Export Black Outlines (PNG)",
            data=black_preview_png,
            file_name=f"{key}_outlines.png",
            mime="image/png",
            use_container_width=True,
        )
except Exception as e:
    st.error(f"Không thể export PNG: {e}")

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

