"""
Manual drawing mode — user traces each fill region as a polygon, the dominant
color inside the polygon is auto-detected from the original image pixels.

Drawing tool:
- polygon: click each vertex, double-click to close
- freedraw: continuous pen
"""

from __future__ import annotations

import base64
import io
import zipfile

import cv2
import numpy as np
import streamlit as st
from PIL import Image

# ── Compat shim ───────────────────────────────────────────────────────────────
# streamlit-drawable-canvas 0.9.3 uses streamlit.elements.image.image_to_url,
# removed in Streamlit ≥1.30. Re-add a working replacement before importing it.
import streamlit.elements.image as _st_image  # noqa: E402

if not hasattr(_st_image, "image_to_url"):
    def _image_to_url(image, width=-1, clamp=False, channels="RGB",
                      output_format="auto", image_id="", allow_emoji=False):
        # Encode image to PNG bytes
        if isinstance(image, bytes):
            data, mime = image, "image/png"
        elif isinstance(image, np.ndarray):
            buf = io.BytesIO()
            Image.fromarray(image).save(buf, format="PNG")
            data, mime = buf.getvalue(), "image/png"
        elif hasattr(image, "save"):
            buf = io.BytesIO()
            fmt = (output_format or "PNG").upper()
            if fmt == "AUTO":
                fmt = "PNG"
            image.save(buf, format=fmt)
            data, mime = buf.getvalue(), f"image/{fmt.lower()}"
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")

        # Register with Streamlit's MediaFileManager → returns /media/<hash>.png URL
        # (data URLs are too long and can break the canvas component)
        try:
            from streamlit.runtime import Runtime
            runtime = Runtime.instance()
            return runtime.media_file_mgr.add(
                data, mime, image_id or f"img_{id(image)}",
            )
        except Exception:
            return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    _st_image.image_to_url = _image_to_url

from streamlit_drawable_canvas import st_canvas  # noqa: E402

from image_to_colorbynumber import OUTPUT_CANVAS, FONT_SIZE, rgb_to_hex

LINE_SEP = "\r\n"
SP_FLAG = b"111\r\n"
DISPLAY_SIZE = 800


def _to_jpeg(img_rgb: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(
        ".jpg", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    return buf.tobytes() if ok else b""


def _fabric_to_points(obj: dict) -> list[tuple[float, float]]:
    """
    Extract absolute (x, y) coords from a fabric.js drawn object.
    Handles polygon, path (freedraw), and rect/ellipse.
    """
    t = obj.get("type")
    left = obj.get("left", 0)
    top = obj.get("top", 0)
    sx = obj.get("scaleX", 1)
    sy = obj.get("scaleY", 1)

    if t == "polygon":
        pts = obj.get("points", [])
        # fabric polygon points are relative to the object's pathOffset
        # (which is roughly the centroid of the points). To get absolute coords,
        # use left/top + point - pathOffset.
        po = obj.get("pathOffset", {"x": 0, "y": 0})
        return [
            (left + (p["x"] - po["x"]) * sx, top + (p["y"] - po["y"]) * sy)
            for p in pts
        ]

    if t == "path":
        path_data = obj.get("path", [])
        out: list[tuple[float, float]] = []
        for cmd in path_data:
            if not cmd:
                continue
            head = cmd[0]
            if head in ("M", "L") and len(cmd) >= 3:
                out.append((float(cmd[1]), float(cmd[2])))
            elif head == "Q" and len(cmd) >= 5:
                out.append((float(cmd[3]), float(cmd[4])))
            elif head == "C" and len(cmd) >= 7:
                out.append((float(cmd[5]), float(cmd[6])))
        return out

    if t == "rect":
        w = obj.get("width", 0) * sx
        h = obj.get("height", 0) * sy
        return [(left, top), (left + w, top), (left + w, top + h), (left, top + h)]

    return []


def _dominant_color(img_rgb: np.ndarray, mask: np.ndarray) -> tuple[int, int, int]:
    """Median RGB of pixels under mask. Median is robust to outlier pixels at edges."""
    pixels = img_rgb[mask > 0]
    if len(pixels) == 0:
        return (128, 128, 128)
    med = np.median(pixels, axis=0).astype(np.uint8)
    return int(med[0]), int(med[1]), int(med[2])


def _polygon_to_svg_path(pts_canvas: list[tuple[float, float]]) -> str:
    if len(pts_canvas) < 3:
        return ""
    p0 = pts_canvas[0]
    parts = [f"M{p0[0]:.1f},{p0[1]:.1f}"]
    for p in pts_canvas[1:]:
        parts.append(f"L{p[0]:.1f},{p[1]:.1f}")
    parts.append("Z")
    return "".join(parts)


def render_manual_mode() -> None:
    st.header("Manual mode — vẽ tay từng vùng")
    st.caption(
        "Polygon: click từng đỉnh, double-click để đóng. "
        "Freedraw: kéo chuột vẽ liền nét. "
        "Mỗi shape khép kín = 1 fill region; màu được tự detect từ pixels gốc bên trong shape."
    )

    with st.sidebar:
        uploaded = st.file_uploader(
            "Upload image", type=["jpg", "jpeg", "png", "webp", "bmp"],
            key="manual_upload",
        )
        asset_key = st.text_input("Asset key", value="asset", key="manual_key")

        st.markdown("---")
        st.markdown("**Drawing**")
        drawing_mode = st.radio(
            "Tool", ["polygon", "freedraw", "transform"],
            index=0, key="manual_tool",
            help="polygon = chính xác, freedraw = vẽ tay liền nét, transform = di chuyển/sửa shape đã vẽ",
        )
        pen_size = st.slider("Pen size", 1, 6, 2, key="manual_pen")
        pen_color = st.color_picker("Pen color (hiển thị, ko ảnh hưởng output)",
                                    value="#FF0000", key="manual_pen_color")

        st.markdown("---")
        st.markdown("**Output**")
        include_strokes = st.toggle(
            "Vẽ nét đen từ polygon đã vẽ", value=True, key="manual_strokes",
            help="Mỗi polygon đồng thời cũng tạo ra 1 STROKE_LINE đen viền theo nó.",
        )
        stroke_width_out = st.slider(
            "Stroke width", 0.5, 4.0, 1.5, 0.5,
            key="manual_sw", disabled=not include_strokes,
        )

    if uploaded is None:
        st.info("Upload ảnh ở sidebar để bắt đầu.")
        return

    # ── Load + pad image to square ──────────────────────────────────────────
    pil_in = Image.open(uploaded).convert("RGBA")
    white = Image.new("RGBA", pil_in.size, (255, 255, 255, 255))
    pil_rgb = Image.alpha_composite(white, pil_in).convert("RGB")
    img_arr = np.array(pil_rgb)

    h, w = img_arr.shape[:2]
    side = max(h, w)
    if h != w:
        sq = np.full((side, side, 3), 255, dtype=np.uint8)
        oy, ox = (side - h) // 2, (side - w) // 2
        sq[oy:oy + h, ox:ox + w] = img_arr
        img_arr = sq

    # Display version (DISPLAY_SIZE × DISPLAY_SIZE)
    pil_display = Image.fromarray(img_arr).resize(
        (DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS,
    )

    # ── Canvas ──────────────────────────────────────────────────────────────
    st.subheader("Canvas")
    if st.button("Clear all shapes", key="clear_btn"):
        st.session_state["canvas_key"] = st.session_state.get("canvas_key", 0) + 1
    canvas_key = f"canvas_{st.session_state.get('canvas_key', 0)}"

    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.15)",
        stroke_width=pen_size,
        stroke_color=pen_color,
        background_image=pil_display,
        drawing_mode=drawing_mode,
        width=DISPLAY_SIZE,
        height=DISPLAY_SIZE,
        key=canvas_key,
        update_streamlit=True,
    )

    if not canvas_result.json_data or not canvas_result.json_data.get("objects"):
        st.info("Vẽ polygon (click từng đỉnh, double-click close) hoặc freedraw lên canvas.")
        return

    # ── Process each drawn shape ────────────────────────────────────────────
    scale_disp_to_img = side / DISPLAY_SIZE                 # display → original image
    scale_disp_to_canvas = OUTPUT_CANVAS / DISPLAY_SIZE     # display → 2048 output

    regions: list[dict] = []
    for obj in canvas_result.json_data["objects"]:
        pts_display = _fabric_to_points(obj)
        if len(pts_display) < 3:
            continue

        # Pixel-space mask for color detection
        pts_img = np.array(
            [[p[0] * scale_disp_to_img, p[1] * scale_disp_to_img] for p in pts_display],
            dtype=np.int32,
        )
        mask = np.zeros((side, side), dtype=np.uint8)
        cv2.fillPoly(mask, [pts_img], 255)
        if mask.sum() == 0:
            continue

        color_rgb = _dominant_color(img_arr, mask)

        # Output-canvas-space SVG
        pts_canvas = [
            (p[0] * scale_disp_to_canvas, p[1] * scale_disp_to_canvas)
            for p in pts_display
        ]
        svg = _polygon_to_svg_path(pts_canvas)
        if not svg:
            continue

        cx = float(np.mean([p[0] for p in pts_canvas]))
        cy = float(np.mean([p[1] for p in pts_canvas]))

        regions.append({
            "svg": svg,
            "color": color_rgb,
            "label_x": int(cx),
            "label_y": int(cy),
        })

    if not regions:
        st.warning("Chưa có shape nào hợp lệ (cần ít nhất 3 đỉnh).")
        return

    # ── Show region palette ─────────────────────────────────────────────────
    st.subheader(f"Regions detected ({len(regions)})")
    swatches_per_row = 10
    rows = (len(regions) + swatches_per_row - 1) // swatches_per_row
    for row in range(rows):
        cols = st.columns(swatches_per_row)
        for i in range(swatches_per_row):
            idx = row * swatches_per_row + i
            if idx >= len(regions):
                break
            c = regions[idx]["color"]
            hex_c = f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"
            cols[i].markdown(
                f"<div style='background:{hex_c};width:100%;height:40px;"
                f"border-radius:4px;border:1px solid #888'></div>"
                f"<div style='font-size:10px;text-align:center'>{idx+1}: {hex_c}</div>",
                unsafe_allow_html=True,
            )

    # ── Build Iceors output ─────────────────────────────────────────────────
    fill_lines: list[str] = []
    stroke_lines_out: list[str] = []
    for r in regions:
        c = r["color"]
        hex_c = rgb_to_hex(c[0], c[1], c[2])
        label_pos = r["label_y"] * OUTPUT_CANVAS + r["label_x"]
        fill_lines.append(f"{r['svg']}|{hex_c}|0|{label_pos}|{FONT_SIZE}")
        if include_strokes:
            stroke_lines_out.append(f"{r['svg']}|0|{stroke_width_out}|0|0")

    all_lines = fill_lines + stroke_lines_out

    # Stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fill regions", len(fill_lines))
    c2.metric("Stroke lines", len(stroke_lines_out))
    c3.metric("Total", len(all_lines))
    c4.metric("Canvas", f"{OUTPUT_CANVAS}px")

    # ── ZIP build & download ────────────────────────────────────────────────
    key = (asset_key.strip() or "asset")
    data_bytes = LINE_SEP.join(all_lines).encode("utf-8")

    ref_rgb = cv2.resize(img_arr, (OUTPUT_CANVAS, OUTPUT_CANVAS), interpolation=cv2.INTER_AREA)
    ref_jpeg = _to_jpeg(ref_rgb)

    def make_zip(with_image: bool) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{key}b", data_bytes)
            zf.writestr("sp_new_paint_flag", SP_FLAG)
            if with_image and ref_jpeg:
                zf.writestr(f"{key}c", ref_jpeg)
        return buf.getvalue()

    st.subheader("Download")
    d1, d2 = st.columns(2)
    d1.download_button(
        f"⬇️  Data only  ({key}b + flag)",
        data=make_zip(False),
        file_name=f"{key}_b.zip",
        mime="application/zip",
        use_container_width=True,
    )
    d2.download_button(
        f"⬇️  Data + Image  ({key}b + {key}c + flag)",
        data=make_zip(True),
        file_name=f"{key}_b.zip",
        mime="application/zip",
        use_container_width=True,
        type="primary",
    )
