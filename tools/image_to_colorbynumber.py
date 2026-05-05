#!/usr/bin/env python3
"""
image_to_colorbynumber.py — Image → Iceors Color-by-Number format.

Pipeline (quantize-first):
  1. K-means quantize (có thể chạy ở resolution nhỏ hơn để nhanh)
  2. Scale label map lên OUTPUT_CANVAS_SIZE (2048) để contour đúng tọa độ
  3. Mỗi màu: binary mask → findContours → SVG paths (FILLABLE)
  4. Canny → STROKE_LINE (nét sketch overlay)
  5. Xuất pipe-delimited file với CRLF

OUTPUT CANVAS SIZE LUÔN LÀ 2048 — phải khớp với Android IceorsAsset canvasSize
(default 2048f trong loadFromFile). Nếu paths ở tọa độ 1024 mà Android load
với 2048, paths sẽ nằm sai vị trí → hit-test sai → tô không được.

Output format (IceorsAsset.parseLines):
    {svgPath}|{colorHex}|{strokeWidth}|{labelPosPacked}|{fontSize}

Classification (IceorsAsset.classify):
    strokeWidth != 0              → STROKE_LINE  (nét đen decoration, luôn vẽ trên fill)
    (colorRGB & 0xFFFFFF) == 0   → BLACK_FILL   (solid black, không tô được)
    color == 0xFFFFFFFF & sw==0  → DROPPED      (white + no stroke → bị bỏ)
    otherwise                    → FILLABLE      (user tô màu)
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import cv2
import numpy as np
from sklearn.cluster import KMeans

OUTPUT_CANVAS   = 2048   # KHÔNG THAY ĐỔI — phải match Android IceorsAsset canvasSize
MIN_FILL_AREA   = 300
MIN_STROKE_AREA = 80
FILL_EPSILON    = 1.5
STROKE_EPSILON  = 0.8
OUTLINE_SW      = 1.5
FONT_SIZE       = 12
CANNY_LOW       = 50
CANNY_HIGH      = 150


# ── Color helpers ──────────────────────────────────────────────────────────────

def rgb_to_hex(r: int, g: int, b: int) -> str:
    """
    Bump các màu bị app classify sai:
    - (0,0,0)       → BLACK_FILL (solid black, không tô được) → bump lên (1,1,1)
    - (255,255,255) → DROPPED nếu strokeWidth==0 → bump xuống (254,254,254)
    """
    if r == 0 and g == 0 and b == 0:
        r, g, b = 1, 1, 1
    elif r == 255 and g == 255 and b == 255:
        r, g, b = 254, 254, 254
    return f"{r:02X}{g:02X}{b:02X}"


# ── SVG helpers ───────────────────────────────────────────────────────────────

def contour_to_svg(contour: np.ndarray, closed: bool) -> Optional[str]:
    """
    Chuyển contour thành SVG path string với Cubic Bézier curves.
    Catmull-Rom spline → Cubic Bézier, clamp control points trong canvas.
    """
    pts = contour.squeeze().astype(np.float64)
    if pts.ndim < 2 or len(pts) < 3:
        return None

    n = len(pts)
    # Giới hạn canvas để clamp control points
    lo, hi = -5.0, OUTPUT_CANVAS + 5.0
    path = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"

    for i in range(n if closed else n - 1):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n]

        cp1x = max(lo, min(hi, p1[0] + (p2[0] - p0[0]) / 6.0))
        cp1y = max(lo, min(hi, p1[1] + (p2[1] - p0[1]) / 6.0))
        cp2x = max(lo, min(hi, p2[0] - (p3[0] - p1[0]) / 6.0))
        cp2y = max(lo, min(hi, p2[1] - (p3[1] - p1[1]) / 6.0))

        path += f"C{cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {p2[0]:.1f},{p2[1]:.1f}"

    if closed:
        path += "Z"
    return path


def centroid(contour: np.ndarray) -> tuple[int, int]:
    M = cv2.moments(contour)
    if M["m00"] == 0:
        x, y, w, h = cv2.boundingRect(contour)
        return x + w // 2, y + h // 2
    return int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])


# ── K-means ───────────────────────────────────────────────────────────────────

def quantize(img_rgb: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (label_map HxW int, centers Nx3 uint8).
    Chạy trên img ở bất kỳ resolution nào — label_map sẽ được scale riêng.
    """
    h, w = img_rgb.shape[:2]
    pixels = img_rgb.reshape(-1, 3).astype(np.float32)
    km = KMeans(n_clusters=n, random_state=42, n_init=10, max_iter=300)
    labels = km.fit_predict(pixels)
    centers = np.clip(km.cluster_centers_, 0, 255).astype(np.uint8)
    return labels.reshape(h, w), centers


# ── Core processing ───────────────────────────────────────────────────────────

def process_array(
    img_rgb: np.ndarray,
    n_colors: int = 20,
    kmeans_size: int = OUTPUT_CANVAS,   # resolution chạy K-means (1024=nhanh, 2048=full)
    canny_low: int = CANNY_LOW,
    canny_high: int = CANNY_HIGH,
    min_fill_area: int = MIN_FILL_AREA,
    stroke_width: float = OUTLINE_SW,
    include_strokes: bool = True,
    log=print,
) -> tuple[list[str], np.ndarray, list[tuple[int, int, int]]]:
    """
    Parameters
    ----------
    img_rgb      : (H,W,3) uint8 RGB, bất kỳ resolution
    n_colors     : số màu palette
    kmeans_size  : resolution K-means (1024 nhanh hơn ~4x, chất lượng vẫn tốt)
                   OUTPUT paths luôn ở tọa độ OUTPUT_CANVAS=2048 bất kể giá trị này.
    """
    # ── Bước 1: K-means ở kmeans_size ────────────────────────────────────
    log(f"[1/3] K-means {n_colors} colors @ {kmeans_size}px…")
    img_small = cv2.resize(img_rgb, (kmeans_size, kmeans_size), interpolation=cv2.INTER_AREA)
    label_map_small, centers = quantize(img_small, n_colors)

    # ── Bước 2: Preview Image ──────────────────────────────────────────────
    # Quantized preview ở OUTPUT_CANVAS (chỉ dùng để hiển thị UI)
    quantized_small = centers[label_map_small]
    if kmeans_size != OUTPUT_CANVAS:
        quantized = cv2.resize(quantized_small, (OUTPUT_CANVAS, OUTPUT_CANVAS), interpolation=cv2.INTER_NEAREST)
    else:
        quantized = quantized_small

    # ── Bước 3: Fill regions (và Outline strokes) ─────────────────────────
    log("[2/3] Extracting regions and outlines…")
    fill_entries: list[tuple[float, str]] = []
    stroke_lines: list[str] = []
    
    scale_factor = OUTPUT_CANVAS / kmeans_size
    # min_fill_area đang tính theo OUTPUT_CANVAS, phải scale xuống cho mask nhỏ
    min_fill_area_small = min_fill_area / (scale_factor ** 2)

    for idx, color in enumerate(centers):
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        hex_color = rgb_to_hex(r, g, b)

        # Tạo mask trên ảnh gốc nhỏ
        mask = ((label_map_small == idx).astype(np.uint8) * 255)

        # 1. GaussianBlur: bo tròn biên pixel (loại bỏ răng cưa gốc)
        mask = cv2.GaussianBlur(mask, (5, 5), 1.5)
        _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)

        # 2. Dilate 1px: mở rộng vùng để lấp khe trắng giữa các fill
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)

        # RETR_CCOMP: 2 cấp hierarchy
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
        if hierarchy is None:
            continue
        hierarchy = hierarchy[0]

        for ci, c in enumerate(contours):
            parent = hierarchy[ci][3]

            # Skip hole contours (depth 1)
            if parent != -1:
                grandparent = hierarchy[parent][3]
                if grandparent == -1:
                    continue

            area_small = cv2.contourArea(c)
            if area_small < min_fill_area_small:
                continue

            # approxPolyDP giảm điểm, Catmull-Rom Bézier sẽ bo tròn trong contour_to_svg
            c_s = cv2.approxPolyDP(c, FILL_EPSILON, closed=True)
            c_s_scaled = c_s.astype(np.float32) * scale_factor
            svg = contour_to_svg(c_s_scaled, closed=True)
            if not svg:
                continue

            # Ghép hole contours vào path để khoét lỗ
            child_idx = hierarchy[ci][2]
            while child_idx != -1:
                hole_c = contours[child_idx]
                hole_s = cv2.approxPolyDP(hole_c, FILL_EPSILON, closed=True)
                hole_scaled = hole_s.astype(np.float32) * scale_factor
                hole_svg = contour_to_svg(hole_scaled, closed=True)
                if hole_svg:
                    svg += hole_svg
                child_idx = hierarchy[child_idx][0]

            area_real = area_small * (scale_factor ** 2)
            cx, cy = centroid(c_s_scaled)
            fill_entries.append((area_real, f"{svg}|{hex_color}|0|{int(cy) * OUTPUT_CANVAS + int(cx)}|{FONT_SIZE}"))

            # Stroke chỉ dùng outer path
            if include_strokes:
                outer_svg = contour_to_svg(c_s_scaled, closed=True)
                stroke_lines.append(f"{outer_svg}|0|{stroke_width}|0|0")

    # Sort: lớn trước → nhỏ sau.
    fill_entries.sort(key=lambda e: e[0], reverse=True)
    fill_lines = [line for _, line in fill_entries]

    # Preview overlay (vẽ stroke để user xem)
    preview = quantized.copy()
    if include_strokes:
        h_diff = (label_map_small[:-1, :] != label_map_small[1:, :]).astype(np.uint8)
        v_diff = (label_map_small[:, :-1] != label_map_small[:, 1:]).astype(np.uint8)
        boundary_small = np.zeros((kmeans_size, kmeans_size), np.uint8)
        boundary_small[:-1, :] = np.maximum(boundary_small[:-1, :], h_diff * 255)
        boundary_small[:, :-1] = np.maximum(boundary_small[:, :-1], v_diff * 255)
        if scale_factor != 1.0:
            boundary_large = cv2.resize(boundary_small, (OUTPUT_CANVAS, OUTPUT_CANVAS), interpolation=cv2.INTER_NEAREST)
            preview[boundary_large > 0] = (0, 0, 0)
        else:
            preview[boundary_small > 0] = (0, 0, 0)

    palette = [(int(c[0]), int(c[1]), int(c[2])) for c in centers]
    all_lines = fill_lines + stroke_lines
    log(f"  → {len(fill_lines)} fill, {len(stroke_lines)} stroke | canvas {OUTPUT_CANVAS}px")
    return all_lines, preview, palette


def build_lines(img_path: str, n_colors: int, kmeans_size: int = OUTPUT_CANVAS, **kw) -> list[str]:
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        raise FileNotFoundError(f"Cannot read: {img_path}")
    lines, _, _ = process_array(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB), n_colors, kmeans_size, **kw)
    return lines


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--colors",    type=int,   default=20)
    ap.add_argument("--fast",      action="store_true", help="K-means ở 1024px (nhanh hơn ~4x)")
    ap.add_argument("--canny-low", type=int,   default=CANNY_LOW)
    ap.add_argument("--canny-high",type=int,   default=CANNY_HIGH)
    ap.add_argument("--min-area",  type=int,   default=MIN_FILL_AREA)
    ap.add_argument("--no-strokes",action="store_true")
    args = ap.parse_args()

    try:
        lines = build_lines(
            args.input, args.colors,
            kmeans_size=1024 if args.fast else OUTPUT_CANVAS,
            canny_low=args.canny_low, canny_high=args.canny_high,
            min_fill_area=args.min_area,
            include_strokes=not args.no_strokes,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines))
    print(f"Done — {len(lines)} lines → {args.output} (canvas {OUTPUT_CANVAS}px)")


if __name__ == "__main__":
    main()
