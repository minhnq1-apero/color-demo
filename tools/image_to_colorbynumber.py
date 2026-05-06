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
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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


# ── Potrace stroke helpers ────────────────────────────────────────────────────

_POTRACE = shutil.which('potrace') or '/opt/homebrew/bin/potrace'


def _save_pbm(path: str, mask: np.ndarray) -> None:
    h, w = mask.shape
    pad = np.zeros((h, ((w + 7) // 8) * 8), dtype=bool)
    pad[:, :w] = mask > 0
    packed = np.packbits(pad, axis=1)
    with open(path, 'wb') as f:
        f.write(f"P4\n{w} {h}\n".encode())
        f.write(packed.tobytes())


def _transform_potrace_path(
    path_d: str, kmeans_size: int, scale: float
) -> tuple[str, list[tuple[float, float]]]:
    """
    Parse potrace SVG path (M/m/L/l/C/c/Z/z), transform coordinates:
        canvas_x = potrace_x / 10 * scale
        canvas_y = (kmeans_size - potrace_y / 10) * scale
    Returns (transformed_path_d, list_of_canvas_coords).
    """
    tokens = re.findall(
        r'[MLCSZmlcsz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', path_d
    )
    result: list[str] = []
    coords: list[tuple[float, float]] = []
    cx = cy = sx = sy = 0.0
    cmd: str | None = None
    i = 0

    def to_cv(px: float, py: float) -> tuple[float, float]:
        return px / 10 * scale, (kmeans_size - py / 10) * scale

    while i < len(tokens):
        tok = tokens[i]
        if tok in 'MLCSZmlcsz':
            cmd = tok
            i += 1
            continue
        # Collect all numbers until the next command
        nums: list[float] = []
        while i < len(tokens) and tokens[i] not in 'MLCSZmlcsz':
            nums.append(float(tokens[i]))
            i += 1
        j = 0
        while True:
            if cmd == 'M':
                if j + 1 >= len(nums): break
                cx, cy = nums[j], nums[j + 1]; j += 2
                sx, sy = cx, cy
                nx, ny = to_cv(cx, cy); coords.append((nx, ny))
                result.append(f"M{nx:.1f},{ny:.1f}"); cmd = 'L'
            elif cmd == 'm':
                if j + 1 >= len(nums): break
                cx += nums[j]; cy += nums[j + 1]; j += 2
                sx, sy = cx, cy
                nx, ny = to_cv(cx, cy); coords.append((nx, ny))
                result.append(f"M{nx:.1f},{ny:.1f}"); cmd = 'l'
            elif cmd == 'L':
                if j + 1 >= len(nums): break
                cx, cy = nums[j], nums[j + 1]; j += 2
                nx, ny = to_cv(cx, cy); coords.append((nx, ny))
                result.append(f"L{nx:.1f},{ny:.1f}")
            elif cmd == 'l':
                if j + 1 >= len(nums): break
                cx += nums[j]; cy += nums[j + 1]; j += 2
                nx, ny = to_cv(cx, cy); coords.append((nx, ny))
                result.append(f"L{nx:.1f},{ny:.1f}")
            elif cmd == 'C':
                if j + 5 >= len(nums): break
                x1, y1 = nums[j], nums[j+1]; x2, y2 = nums[j+2], nums[j+3]
                cx, cy = nums[j+4], nums[j+5]; j += 6
                p1 = to_cv(x1, y1); p2 = to_cv(x2, y2); pe = to_cv(cx, cy)
                coords.extend([p1, p2, pe])
                result.append(f"C{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {pe[0]:.1f},{pe[1]:.1f}")
            elif cmd == 'c':
                if j + 5 >= len(nums): break
                x1, y1 = cx + nums[j], cy + nums[j+1]
                x2, y2 = cx + nums[j+2], cy + nums[j+3]
                cx, cy = cx + nums[j+4], cy + nums[j+5]; j += 6
                p1 = to_cv(x1, y1); p2 = to_cv(x2, y2); pe = to_cv(cx, cy)
                coords.extend([p1, p2, pe])
                result.append(f"C{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {pe[0]:.1f},{pe[1]:.1f}")
            elif cmd in ('Z', 'z'):
                cx, cy = sx, sy
                result.append('Z')
                break
            else:
                break
    return ''.join(result), coords


def _stroke_lines_potrace(
    label_map_small: np.ndarray,
    kmeans_size: int,
    stroke_width: float,
    min_fill_area: float,
    log=print,
) -> list[str]:
    """
    Per-color: run potrace on binary mask → smooth cubic Bézier outlines.
    Filters paths touching canvas edge (avoids square-frame artifact).
    Requires `potrace` CLI (brew install potrace on macOS).
    """
    if not _POTRACE or not os.path.exists(_POTRACE):
        log("  [potrace] not found — install with: brew install potrace")
        return []

    n_colors = int(label_map_small.max()) + 1
    scale = OUTPUT_CANVAS / kmeans_size
    margin = OUTPUT_CANVAS * 0.015   # ~30px border exclusion zone
    # min area in kmeans_size pixel² (same filter used for fill contours)
    min_area_small = min_fill_area / (scale ** 2)

    def process_color(idx: int) -> list[str]:
        mask = ((label_map_small == idx) * 255).astype(np.uint8)
        if mask.sum() == 0:
            return []

        # Remove connected components smaller than min_area_small (same filter as fill)
        n_lbl, lbl_img, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        filtered = np.zeros_like(mask)
        for lbl in range(1, n_lbl):
            if stats[lbl, cv2.CC_STAT_AREA] >= min_area_small:
                filtered[lbl_img == lbl] = 255
        if filtered.sum() == 0:
            return []
        mask = filtered

        # Fill internal holes so potrace only traces the outer boundary.
        # Without this, potrace also traces hole-boundaries (eyes, mouth, etc.)
        # which appear as black lines INSIDE the fill region.
        inv = cv2.copyMakeBorder(255 - mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=255)
        cv2.floodFill(inv, None, (0, 0), 128)   # 128 = background (reachable from outside)
        inv = inv[1:-1, 1:-1]                   # crop padding back
        mask = mask | ((inv == 255).astype(np.uint8) * 255)  # merge in holes

        with tempfile.TemporaryDirectory() as d:
            pbm = os.path.join(d, 'c.pbm')
            svg = os.path.join(d, 'c.svg')
            _save_pbm(pbm, mask)
            r = subprocess.run(
                [_POTRACE, '--svg', '-o', svg, pbm],
                capture_output=True, timeout=30,
            )
            if r.returncode != 0:
                return []
            svg_txt = open(svg).read()

        lines = []
        for d_attr in re.findall(r'\sd="([^"]+)"', svg_txt):
            transformed, cvcoords = _transform_potrace_path(d_attr, kmeans_size, scale)
            if not cvcoords:
                continue
            xs = [c[0] for c in cvcoords]
            ys = [c[1] for c in cvcoords]
            # Skip paths that touch/cross the canvas boundary (square-frame artifact)
            if (min(xs) < margin or min(ys) < margin or
                    max(xs) > OUTPUT_CANVAS - margin or
                    max(ys) > OUTPUT_CANVAS - margin):
                continue
            lines.append(f"{transformed}|0|{stroke_width}|0|0")
        return lines

    result: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, n_colors)) as ex:
        for color_lines in ex.map(process_color, range(n_colors)):
            result.extend(color_lines)

    log(f"  [potrace] → {len(result)} stroke paths")
    return result


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

        # Mask trực tiếp từ label_map — K-means đảm bảo mọi pixel thuộc đúng 1 cluster
        mask = ((label_map_small == idx).astype(np.uint8) * 255)

        # Bỏ noise: filter connected components < min_fill_area TRƯỚC khi dilate.
        # Nếu để dilate trước, các đốm 4-5 pixel sẽ phình lên đủ qua filter → spam.
        n_lbl, lbl_img, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        clean = np.zeros_like(mask)
        for lbl in range(1, n_lbl):
            if stats[lbl, cv2.CC_STAT_AREA] >= min_fill_area_small:
                clean[lbl_img == lbl] = 255
        if clean.sum() == 0:
            continue
        mask = clean

        # Dilate 1px: fill mở rộng ra ~0.5-1px ngoài boundary thật.
        # Catmull-Rom Bézier có xu hướng co contour vào trong → khe trắng
        # giữa fill và stroke. Dilate cho fill phủ qua boundary, stroke (vẽ
        # trên cùng) sẽ che phần overlap → không còn khe trắng.
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

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

    # Sort: lớn trước → nhỏ sau.
    fill_entries.sort(key=lambda e: e[0], reverse=True)
    fill_lines = [line for _, line in fill_entries]

    # ── Bước 4: Strokes via potrace ──────────────────────────────────────
    if include_strokes:
        log("[3/3] Generating smooth outlines via potrace…")
        stroke_lines = _stroke_lines_potrace(
            label_map_small, kmeans_size, stroke_width, min_fill_area, log
        )
    else:
        log("[3/3] Skipping outlines.")

    # Preview: quantized + boundary overlay
    preview = quantized.copy()
    h_diff = (label_map_small[:-1, :] != label_map_small[1:, :]).astype(np.uint8)
    v_diff = (label_map_small[:, :-1] != label_map_small[:, 1:]).astype(np.uint8)
    boundary_small = np.zeros((kmeans_size, kmeans_size), np.uint8)
    boundary_small[:-1, :] = np.maximum(boundary_small[:-1, :], h_diff * 255)
    boundary_small[:, :-1] = np.maximum(boundary_small[:, :-1], v_diff * 255)
    boundary_large = cv2.resize(boundary_small, (OUTPUT_CANVAS, OUTPUT_CANVAS), interpolation=cv2.INTER_NEAREST)
    preview[boundary_large > 0] = (0, 0, 0)

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
