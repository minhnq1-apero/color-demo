"""
Manual drawing mode — user clicks on the image to add polygon vertices.
Each closed polygon = one fill region; the color is auto-detected from
the median RGB of pixels inside the polygon.

Uses streamlit-image-coordinates for clicks (works with all Streamlit
versions, unlike streamlit-drawable-canvas which depends on a removed
internal API).
"""

from __future__ import annotations

import io
import zipfile

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates

from image_to_colorbynumber import OUTPUT_CANVAS, FONT_SIZE, rgb_to_hex

LINE_SEP = "\r\n"
SP_FLAG = b"111\r\n"
DISPLAY_SIZE = 800


# ── Session state helpers ─────────────────────────────────────────────────────

def _ss(key: str, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def _to_jpeg(img_rgb: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(
        ".jpg", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    return buf.tobytes() if ok else b""


def _dominant_color(img_rgb: np.ndarray, mask: np.ndarray) -> tuple[int, int, int]:
    pixels = img_rgb[mask > 0]
    if len(pixels) == 0:
        return (128, 128, 128)
    med = np.median(pixels, axis=0).astype(np.uint8)
    return int(med[0]), int(med[1]), int(med[2])


def _polygon_svg(pts_canvas: list[tuple[float, float]]) -> str:
    if len(pts_canvas) < 3:
        return ""
    p0 = pts_canvas[0]
    parts = [f"M{p0[0]:.1f},{p0[1]:.1f}"]
    for p in pts_canvas[1:]:
        parts.append(f"L{p[0]:.1f},{p[1]:.1f}")
    parts.append("Z")
    return "".join(parts)


def _draw_overlay(
    base: Image.Image,
    current_pts: list[tuple[int, int]],
    completed: list[dict],
) -> Image.Image:
    """Render base image + completed polygons (filled, low alpha) + current points."""
    img = base.copy().convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for poly in completed:
        pts = poly["pts_display"]
        if len(pts) >= 3:
            c = poly["color"]
            draw.polygon(pts, fill=(c[0], c[1], c[2], 110), outline=(255, 255, 255, 220))

    if current_pts:
        # connect current vertices with a red polyline
        if len(current_pts) >= 2:
            draw.line(current_pts, fill=(255, 0, 0, 255), width=2)
        # mark each vertex with a red dot
        for x, y in current_pts:
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 0, 0, 255))

    return Image.alpha_composite(img, overlay).convert("RGB")


# ── Main ──────────────────────────────────────────────────────────────────────

def render_manual_mode() -> None:
    st.header("Manual mode — click từng điểm để vẽ polygon")
    st.caption(
        "Click vào ảnh để thêm vertex (chấm đỏ), nhấn **Close polygon** để khép kín. "
        "Mỗi polygon = 1 fill region, màu tự detect từ pixels gốc bên trong."
    )

    with st.sidebar:
        uploaded = st.file_uploader(
            "Upload image", type=["jpg", "jpeg", "png", "webp", "bmp"],
            key="m_upload",
        )
        asset_key = st.text_input("Asset key", value="asset", key="m_key")

        st.markdown("---")
        st.markdown("**Output**")
        include_strokes = st.toggle(
            "Vẽ nét đen từ polygon", value=True, key="m_strokes",
            help="Mỗi polygon đồng thời tạo 1 STROKE_LINE đen viền theo nó.",
        )
        stroke_width_out = st.slider(
            "Stroke width", 0.5, 4.0, 1.5, 0.5,
            key="m_sw", disabled=not include_strokes,
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

    pil_display = Image.fromarray(img_arr).resize(
        (DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS,
    )

    # Reset state if user uploads a new image
    upload_token = uploaded.name + str(uploaded.size)
    if st.session_state.get("m_token") != upload_token:
        st.session_state["m_token"] = upload_token
        st.session_state["m_current"] = []
        st.session_state["m_completed"] = []
        st.session_state["m_last_click"] = None

    current_pts: list[tuple[int, int]] = _ss("m_current", [])
    completed: list[dict] = _ss("m_completed", [])

    # ── Toolbar ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    if c1.button("Close polygon", type="primary", disabled=len(current_pts) < 3,
                 use_container_width=True):
        # Compute color from interior of polygon
        scale_disp_to_img = side / DISPLAY_SIZE
        scale_disp_to_canvas = OUTPUT_CANVAS / DISPLAY_SIZE

        pts_img = np.array(
            [[p[0] * scale_disp_to_img, p[1] * scale_disp_to_img] for p in current_pts],
            dtype=np.int32,
        )
        mask = np.zeros((side, side), dtype=np.uint8)
        cv2.fillPoly(mask, [pts_img], 255)
        if mask.sum() > 0:
            color = _dominant_color(img_arr, mask)
            pts_canvas = [
                (p[0] * scale_disp_to_canvas, p[1] * scale_disp_to_canvas)
                for p in current_pts
            ]
            completed.append({
                "pts_display": list(current_pts),
                "pts_canvas": pts_canvas,
                "color": color,
                "label_x": int(np.mean([p[0] for p in pts_canvas])),
                "label_y": int(np.mean([p[1] for p in pts_canvas])),
            })
        st.session_state["m_current"] = []
        st.rerun()

    if c2.button("Undo last point", disabled=not current_pts, use_container_width=True):
        st.session_state["m_current"] = current_pts[:-1]
        st.rerun()

    if c3.button("Cancel polygon", disabled=not current_pts, use_container_width=True):
        st.session_state["m_current"] = []
        st.rerun()

    if c4.button("Clear ALL polygons", use_container_width=True):
        st.session_state["m_current"] = []
        st.session_state["m_completed"] = []
        st.rerun()

    st.caption(
        f"Current polygon: {len(current_pts)} vertices  ·  "
        f"Completed polygons: {len(completed)}"
    )

    # ── Click canvas ────────────────────────────────────────────────────────
    overlay = _draw_overlay(pil_display, current_pts, completed)
    coords = streamlit_image_coordinates(overlay, key="m_canvas")

    # streamlit-image-coordinates returns the same dict on every rerun until a
    # new click happens. Track the last click and only act on new ones.
    if coords is not None:
        click_key = (coords["x"], coords["y"])
        if st.session_state.get("m_last_click") != click_key:
            st.session_state["m_last_click"] = click_key
            current_pts.append(click_key)
            st.session_state["m_current"] = current_pts
            st.rerun()

    if not completed:
        st.info("Click lên ảnh để thêm vertex. Khi đủ ≥3 điểm, nhấn **Close polygon**.")
        return

    # ── Show palette ────────────────────────────────────────────────────────
    st.subheader(f"Regions ({len(completed)})")
    per_row = 10
    rows = (len(completed) + per_row - 1) // per_row
    for r in range(rows):
        cols = st.columns(per_row)
        for i in range(per_row):
            idx = r * per_row + i
            if idx >= len(completed):
                break
            c = completed[idx]["color"]
            hex_c = f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"
            cols[i].markdown(
                f"<div style='background:{hex_c};width:100%;height:40px;"
                f"border-radius:4px;border:1px solid #888'></div>"
                f"<div style='font-size:10px;text-align:center'>{idx+1}: {hex_c}</div>",
                unsafe_allow_html=True,
            )

    # ── Build Iceors output ────────────────────────────────────────────────
    fill_lines: list[str] = []
    stroke_lines_out: list[str] = []
    for poly in completed:
        c = poly["color"]
        hex_c = rgb_to_hex(c[0], c[1], c[2])
        svg = _polygon_svg(poly["pts_canvas"])
        if not svg:
            continue
        label_pos = poly["label_y"] * OUTPUT_CANVAS + poly["label_x"]
        fill_lines.append(f"{svg}|{hex_c}|0|{label_pos}|{FONT_SIZE}")
        if include_strokes:
            stroke_lines_out.append(f"{svg}|0|{stroke_width_out}|0|0")

    all_lines = fill_lines + stroke_lines_out

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Fill regions", len(fill_lines))
    s2.metric("Stroke lines", len(stroke_lines_out))
    s3.metric("Total", len(all_lines))
    s4.metric("Canvas", f"{OUTPUT_CANVAS}px")

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
        data=make_zip(False), file_name=f"{key}_b.zip",
        mime="application/zip", use_container_width=True,
    )
    d2.download_button(
        f"⬇️  Data + Image  ({key}b + {key}c + flag)",
        data=make_zip(True), file_name=f"{key}_b.zip",
        mime="application/zip", use_container_width=True, type="primary",
    )
