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
    asset_key = st.text_input(
        "Asset key", value="asset",
        help="Tên file bên trong ZIP: {key}b. Không dùng dấu cách.",
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
    lines, _ = svg_to_lines(io.BytesIO(svg_bytes), log=log.append)
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

def _lines_to_preview_svg(lines: list[str]) -> str:
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
        if sw.strip() == "0":
            parts.append(f'<path d="{d}" fill="#{color}" fill-rule="evenodd"/>')
        else:
            parts.append(
                f'<path d="{d}" fill="none" stroke="black" stroke-width="{sw}"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


# ── Preview ───────────────────────────────────────────────────────────────────
st.subheader("Preview")
col_orig, col_render = st.columns(2)
with col_orig:
    st.caption("Original SVG")
    st.markdown(
        f'<div style="background:#fff;padding:12px;border-radius:8px;'
        f'border:1px solid #ddd">{svg_bytes.decode("utf-8", errors="ignore")}</div>',
        unsafe_allow_html=True,
    )
with col_render:
    st.caption("Iceors output (re-rendered from generated lines)")
    st.markdown(_lines_to_preview_svg(lines), unsafe_allow_html=True)

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


# ── Reference JPEG (rasterize SVG via cairosvg if available) ──────────────────
ref_jpeg: bytes | None = None
try:
    import cairosvg
    from PIL import Image as _PILImage
    png_bytes = cairosvg.svg2png(
        bytestring=svg_bytes,
        output_width=OUTPUT_CANVAS,
        output_height=OUTPUT_CANVAS,
    )
    pil = _PILImage.open(io.BytesIO(png_bytes)).convert("RGB")
    jbuf = io.BytesIO()
    pil.save(jbuf, format="JPEG", quality=92)
    ref_jpeg = jbuf.getvalue()
except Exception as exc:
    log.append(f"(no reference JPEG: {exc})")

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
