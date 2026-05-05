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
    pts = contour.squeeze()
    if pts.ndim < 2 or len(pts) < 3:
        return None
    path = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for p in pts[1:]:
        path += f"L{p[0]:.1f},{p[1]:.1f}"
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

    # ── Bước 2: Scale label map lên OUTPUT_CANVAS ──────────────────────────
    # QUAN TRỌNG: paths phải ở tọa độ OUTPUT_CANVAS (2048) để Android hit-test đúng.
    # Dùng INTER_NEAREST để giữ nguyên cluster index (không nội suy).
    if kmeans_size != OUTPUT_CANVAS:
        label_map = cv2.resize(
            label_map_small.astype(np.uint8),
            (OUTPUT_CANVAS, OUTPUT_CANVAS),
            interpolation=cv2.INTER_NEAREST,
        ).astype(np.int32)
    else:
        label_map = label_map_small.astype(np.int32)

    # Quantized preview ở OUTPUT_CANVAS
    quantized = centers[label_map]   # (OUTPUT_CANVAS, OUTPUT_CANVAS, 3) uint8

    # ── Bước 3: Fill regions ──────────────────────────────────────────────
    log("[2/3] Extracting fill regions…")
    # (area, line) — sẽ sort sau để đảm bảo draw order đúng
    fill_entries: list[tuple[float, str]] = []

    for idx, color in enumerate(centers):
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        hex_color = rgb_to_hex(r, g, b)

        # K-means gán mọi pixel vào đúng 1 cluster → mask KHÔNG có gap → KHÔNG cần MORPH_CLOSE.
        mask = ((label_map == idx).astype(np.uint8) * 255)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_fill_area:
                continue
            c_s = cv2.approxPolyDP(c, FILL_EPSILON, closed=True)
            svg = contour_to_svg(c_s, closed=True)
            if not svg:
                continue
            cx, cy = centroid(c_s)
            fill_entries.append((area, f"{svg}|{hex_color}|0|{cy * OUTPUT_CANVAS + cx}|{FONT_SIZE}"))

    # Sort: lớn trước → nhỏ sau.
    # IceorsView draw theo thứ tự file: region sau đè lên region trước.
    # → background lớn draw trước, detail nhỏ (nến, hoa...) draw sau → detail luôn hiển thị trên cùng.
    fill_entries.sort(key=lambda e: e[0], reverse=True)
    fill_lines = [line for _, line in fill_entries]

    # ── Bước 4: Stroke lines từ COLOR BOUNDARY (optional) ────────────────
    # Dùng label_map để tìm ranh giới giữa các vùng màu (sạch, không noise).
    # Boundary = pixel nằm cạnh pixel khác cluster → không có texture/nhiễu bên trong vùng.
    # Sau đó HoughLinesP detect các đoạn thẳng từ boundary sạch này.
    stroke_lines: list[str] = []
    edges = None
    if include_strokes:
        log("[3/3] Generating outlines from color boundaries…")

        # Tính boundary từ label_map: chỗ 2 pixel liền kề có label khác nhau
        h_diff = (label_map[:-1, :] != label_map[1:, :]).astype(np.uint8)  # dọc
        v_diff = (label_map[:, :-1] != label_map[:, 1:]).astype(np.uint8)  # ngang
        boundary = np.zeros((OUTPUT_CANVAS, OUTPUT_CANVAS), np.uint8)
        boundary[:-1, :] = np.maximum(boundary[:-1, :], h_diff * 255)
        boundary[:, :-1] = np.maximum(boundary[:, :-1], v_diff * 255)
        edges = boundary  # dùng để overlay preview

        contours, _ = cv2.findContours(boundary, cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)
        for c in contours:
            if cv2.arcLength(c, closed=True) < 20:
                continue
            c_s = cv2.approxPolyDP(c, STROKE_EPSILON, closed=True)
            svg = contour_to_svg(c_s, closed=True)
            if not svg:
                continue
            stroke_lines.append(f"{svg}|0|{stroke_width}|0|0")
    else:
        log("[3/3] Skipping outlines.")

    # Preview: quantized + edge overlay
    preview = quantized.copy()
    if edges is not None:
        preview[edges > 0] = (0, 0, 0)

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
