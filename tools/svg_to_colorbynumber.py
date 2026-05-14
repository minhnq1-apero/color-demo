#!/usr/bin/env python3
"""
svg_to_colorbynumber.py — SVG → Iceors Color-by-Number format.

Pipeline (parse-only, no quantization, no vectorization):
  1. Parse SVG with svgelements (handles all shape types + transforms)
  2. For each <path>/<polygon>/<rect>/<circle>/<ellipse>/<line>:
       - Apply parent transforms + viewBox scale → OUTPUT_CANVAS coords
       - Read fill / stroke / stroke-width
       - Classify FILLABLE / STROKE_LINE
  3. Pad to square if input aspect != 1:1
  4. Output pipe-delimited Iceors lines (CRLF terminated)

Output format (IceorsAsset.parseLines):
    {svgPath}|{colorHex}|{strokeWidth}|{labelPosPacked}|{fontSize}

Why SVG-only:
  - Adjacent fills/strokes share the artist's exact paths → no sub-pixel gaps
  - Smooth Bézier preserved as-authored (no quantize → contour artifacts)
  - User controls quality upstream in Illustrator / Inkscape / vectorizer.ai
"""

from __future__ import annotations

import argparse
import io
import sys
from typing import Optional

import cv2
import numpy as np
import cairosvg

from svgelements import (
    SVG, Shape, Path as SvgPath, Matrix,
    Move, Line as PathLine, CubicBezier, QuadraticBezier, Arc, Close,
)

try:
    from pathops import Path as SkPath, op as sk_op, PathOp
    _HAS_PATHOPS = True
except ImportError:
    _HAS_PATHOPS = False

OUTPUT_CANVAS = 2048
FONT_SIZE = 12


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """
    Convert RGB to Hex.
    - Black/Fixed colors → 000000 (Android treats this as fixed BLACK_FILL).
    - White (255,255,255) → FEFEFE (Android drops pure white without stroke).
    """
    if _is_fixed_color((r, g, b)):
        return "000000"
    if r == 255 and g == 255 and b == 255:
        return "FEFEFE"
    return f"{r:02X}{g:02X}{b:02X}"


def _path_to_d(path: SvgPath) -> str:
    """
    Serialize an svgelements Path into an absolute SVG path d string
    using only commands Android's PathParser supports (M, L, C, Q, A, Z).
    """
    parts: list[str] = []
    for seg in path:
        if isinstance(seg, Move):
            parts.append(f"M{seg.end.x:.2f},{seg.end.y:.2f}")
        elif isinstance(seg, PathLine):
            parts.append(f"L{seg.end.x:.2f},{seg.end.y:.2f}")
        elif isinstance(seg, CubicBezier):
            parts.append(
                f"C{seg.control1.x:.2f},{seg.control1.y:.2f} "
                f"{seg.control2.x:.2f},{seg.control2.y:.2f} "
                f"{seg.end.x:.2f},{seg.end.y:.2f}"
            )
        elif isinstance(seg, QuadraticBezier):
            parts.append(
                f"Q{seg.control.x:.2f},{seg.control.y:.2f} "
                f"{seg.end.x:.2f},{seg.end.y:.2f}"
            )
        elif isinstance(seg, Arc):
            # Approximate arc as cubic Béziers — avoids Arc-attribute API
            # quirks across svgelements versions and is more compatible
            # with PathParser implementations.
            for cubic in seg.as_cubic_curves():
                parts.append(
                    f"C{cubic.control1.x:.2f},{cubic.control1.y:.2f} "
                    f"{cubic.control2.x:.2f},{cubic.control2.y:.2f} "
                    f"{cubic.end.x:.2f},{cubic.end.y:.2f}"
                )
        elif isinstance(seg, Close):
            parts.append("Z")
    return "".join(parts)


def _svgpath_to_skia(svg_path: SvgPath):
    """Convert reified svgelements Path → skia-pathops Path."""
    sk = SkPath()
    for seg in svg_path:
        if isinstance(seg, Move):
            sk.moveTo(seg.end.x, seg.end.y)
        elif isinstance(seg, PathLine):
            sk.lineTo(seg.end.x, seg.end.y)
        elif isinstance(seg, CubicBezier):
            sk.cubicTo(
                seg.control1.x, seg.control1.y,
                seg.control2.x, seg.control2.y,
                seg.end.x, seg.end.y,
            )
        elif isinstance(seg, QuadraticBezier):
            sk.quadTo(seg.control.x, seg.control.y, seg.end.x, seg.end.y)
        elif isinstance(seg, Arc):
            for cubic in seg.as_cubic_curves():
                sk.cubicTo(
                    cubic.control1.x, cubic.control1.y,
                    cubic.control2.x, cubic.control2.y,
                    cubic.end.x, cubic.end.y,
                )
        elif isinstance(seg, Close):
            sk.close()
    return sk


def _skia_to_d(sk) -> str:
    """Skia path → SVG d string (only commands Android PathParser supports)."""
    parts: list[str] = []
    for verb, pts in sk.segments:
        if verb == "moveTo":
            x, y = pts[0]
            parts.append(f"M{x:.2f},{y:.2f}")
        elif verb == "lineTo":
            x, y = pts[0]
            parts.append(f"L{x:.2f},{y:.2f}")
        elif verb == "curveTo":
            (cx1, cy1), (cx2, cy2), (ex, ey) = pts
            parts.append(f"C{cx1:.2f},{cy1:.2f} {cx2:.2f},{cy2:.2f} {ex:.2f},{ey:.2f}")
        elif verb == "qCurveTo":
            # Single quadratic (cp, end). For multi-cp TrueType-style we'd need to expand.
            if len(pts) == 2:
                (cx, cy), (ex, ey) = pts
                parts.append(f"Q{cx:.2f},{cy:.2f} {ex:.2f},{ey:.2f}")
        elif verb == "closePath":
            parts.append("Z")
    return "".join(parts)


def _path_centroid(path: SvgPath) -> tuple[float, float]:
    """Bounding-box center — good enough for label placement."""
    bb = path.bbox()
    if bb is None:
        return 0.0, 0.0
    x0, y0, x1, y1 = bb
    return (x0 + x1) / 2, (y0 + y1) / 2


def _color_to_rgb(c) -> Optional[tuple[int, int, int]]:
    """
    svgelements.Color → (r, g, b) or None if 'none'/transparent/zero-alpha.
    """
    if c is None:
        return None
    s = str(c).strip().lower()
    if s in ("none", "transparent", ""):
        return None
    try:
        # Check alpha/opacity if available
        alpha = getattr(c, "alpha", 255)
        if alpha == 0:
            return None
        return int(c.red), int(c.green), int(c.blue)
    except AttributeError:
        return None


def _is_fixed_color(rgb: Optional[tuple[int, int, int]]) -> bool:
    """Check if color is black OR the specific brown ranges for fixed decorations."""
    if rgb is None:
        return False
    r, g, b = rgb
    
    # 1. Luminance check for Black/Dark gray range
    # Y = 0.299R + 0.587G + 0.114B
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance < 40:
        return True
        
    # 2. Brown range around #843B42 (132, 59, 66)
    if (132-15 < r < 132+15 and 
        59-15 < g < 59+15 and 
        66-15 < b < 66+15):
        return True

    # 3. Dark Brown range around #58242A (88, 36, 42)
    if (88-15 < r < 88+15 and 
        36-15 < g < 36+15 and 
        42-15 < b < 42+15):
        return True
        
    return False


def _merge_similar_colors(
    records: list[dict], tolerance: float, log=print,
) -> None:
    """
    Greedy merge: colors within `tolerance` (Euclidean RGB distance) of an
    already-kept color get rewritten to that color's hex. Larger-area colors
    win — they get to anchor a palette slot first. Mutates `records`.
    """
    if tolerance <= 0 or not records:
        return

    # Aggregate area per color
    by_color: dict[str, float] = {}
    for r in records:
        by_color[r["color_hex"]] = by_color.get(r["color_hex"], 0.0) + r["area"]

    # Process colors largest-area first
    sorted_colors = sorted(by_color.keys(), key=lambda c: by_color[c], reverse=True)

    kept_hex: list[str] = []
    kept_rgb: list[tuple[int, int, int]] = []
    remap: dict[str, str] = {}

    for hex_c in sorted_colors:
        r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
        best = -1
        best_d = tolerance + 1
        for i, (kr, kg, kb) in enumerate(kept_rgb):
            d = ((r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2) ** 0.5
            if d <= tolerance and d < best_d:
                best, best_d = i, d
        if best < 0:
            kept_hex.append(hex_c)
            kept_rgb.append((r, g, b))
            remap[hex_c] = hex_c
        else:
            remap[hex_c] = kept_hex[best]

    if len(kept_hex) < len(by_color):
        log(f"[svg→cbn] color merge: {len(by_color)} → {len(kept_hex)} "
            f"(tolerance={tolerance})")

    for r in records:
        r["color_hex"] = remap[r["color_hex"]]


def _extract_raster_lines(
    svg_input, output_canvas: int, threshold: int = 200, log=print
) -> list[str]:
    """
    Render SVG to grayscale, use OpenCV to find contours of dark areas,
    and return them as fixed black lines (000000 fill).
    """
    log(f"[raster→cbn] Rendering SVG to {output_canvas}px for line extraction...")
    
    # Handle both file paths and file-like objects
    if hasattr(svg_input, "seek") and hasattr(svg_input, "read"):
        svg_input.seek(0)
        svg_bytes = svg_input.read()
    elif isinstance(svg_input, (str, bytes)) and not isinstance(svg_input, bytes):
        try:
            with open(svg_input, "rb") as f:
                svg_bytes = f.read()
        except Exception:
            svg_bytes = str(svg_input).encode("utf-8")
    else:
        svg_bytes = svg_input

    try:
        # Render SVG to PNG in memory
        png_data = cairosvg.svg2png(
            bytestring=svg_bytes,
            output_width=output_canvas,
            output_height=output_canvas,
        )
        
        # Decode to OpenCV image
        nparr = np.frombuffer(png_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        
        if img is None:
            raise ValueError("Failed to decode rendered PNG")

        # Handle alpha channel (blend with white background)
        if len(img.shape) == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3] / 255.0
            for c in range(3):
                img[:, :, c] = (img[:, :, c] * alpha + 255 * (1 - alpha)).astype(np.uint8)
            img = img[:, :, :3]
        elif len(img.shape) == 2:
            # Grayscale already
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Canny Edge Detection (finds outlines instead of just dark areas)
        # 100, 200 are typical hysteresis thresholds
        edges = cv2.Canny(gray, 100, 200)
        
        # Dilate edges slightly to bridge gaps and make them "solid" for contour finding
        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=1)
        
        # Find contours on the edge-detected image
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        lines: list[str] = []
        for cnt in contours:
            # Filter by area: skip tiny noise and skip massive boxes (like background)
            area = cv2.contourArea(cnt)
            if area < 5 or area > (output_canvas * output_canvas * 0.9):
                continue
                
            # Convert contour to SVG path d string
            parts = []
            for i, pt in enumerate(cnt):
                x, y = pt[0]
                cmd = "M" if i == 0 else "L"
                parts.append(f"{cmd}{x:.2f},{y:.2f}")
            parts.append("Z")
            d = "".join(parts)
            
            # Format as fixed black line
            lines.append(f"{d}|000000|0|0|0")
            
        log(f"[raster→cbn] Extracted {len(lines)} contours as black lines.")
        return lines
        
    except Exception as e:
        log(f"[raster→cbn] Error during raster extraction: {e}")
        return []


def svg_to_lines(
    svg_input,
    output_canvas: int = OUTPUT_CANVAS,
    subtract_overlaps: bool = True,
    auto_outline_width: float = 0.0,
    color_merge_tolerance: float = 0.0,
    use_raster_lines: bool = False,
    raster_threshold: int = 200,
    log=print,
) -> tuple[list[str], tuple[int, int, int, int]]:
    """
    Parse an SVG file (path or file-like) into Iceors color-by-number lines.

    Returns (lines, viewport) where viewport = (x, y, width, height) in
    OUTPUT_CANVAS coordinates after squaring + padding.
    """
    # 1. Raster line extraction (optional, using OpenCV)
    # We do this first or separate from the vector parse.
    raster_lines = []
    if use_raster_lines:
        raster_lines = _extract_raster_lines(
            svg_input, output_canvas, threshold=raster_threshold, log=log
        )

    # 2. Vector parse (svgelements)
    if hasattr(svg_input, "seek"):
        svg_input.seek(0)
    svg = SVG.parse(svg_input)

    # svgelements bakes the viewBox→width transform into element coordinates
    # during parse, so path coords arrive in `svg.width × svg.height` pixel
    # space (NOT viewBox space). Using viewbox.width/height here would
    # double-scale when the two differ (e.g. width="600pt" + viewBox="0 0 600 600"
    # gives svg.width=800 but viewbox.width=600 — a 4/3 mismatch).
    sw = float(svg.width) if svg.width else 0.0
    sh = float(svg.height) if svg.height else 0.0
    if sw <= 0 or sh <= 0:
        if svg.viewbox is not None:
            sw = float(svg.viewbox.width)
            sh = float(svg.viewbox.height)
        else:
            raise ValueError("SVG has no usable viewBox/width/height")

    # Pad to square if input aspect != 1:1. Origin offset (vx/vy) is already
    # absorbed by svgelements into element coords, so we don't re-apply it.
    side = max(sw, sh)
    offset_x = (side - sw) / 2
    offset_y = (side - sh) / 2
    scale = output_canvas / side

    # Affine matrix: pixel space → OUTPUT_CANVAS pixel space
    bake = Matrix(f"scale({scale}) translate({offset_x}, {offset_y})")

    # First pass: collect all parsed shapes
    fill_records: list[dict] = []   # {sk, area, color_hex, label_pos}
    stroke_lines: list[str] = []

    n_total = 0
    n_skipped = 0
    for elem in svg.elements():
        if not isinstance(elem, Shape):
            continue
        try:
            path = SvgPath(elem)
        except Exception:
            n_skipped += 1
            continue
        if len(path) == 0:
            continue

        path = path * bake
        path.reify()

        d = _path_to_d(path)
        if not d:
            n_skipped += 1
            continue

        fill_rgb = _color_to_rgb(getattr(elem, "fill", None))
        stroke_rgb = _color_to_rgb(getattr(elem, "stroke", None))
        sw_raw = float(getattr(elem, "stroke_width", 0) or 0)
        stroke_w = sw_raw * scale
        n_total += 1

        if fill_rgb is not None:
            hex_c = rgb_to_hex(*fill_rgb)
            cx, cy = _path_centroid(path)
            label_pos = int(cy) * output_canvas + int(cx)
            try:
                bb = path.bbox()
                area = abs(bb[2] - bb[0]) * abs(bb[3] - bb[1])
            except Exception:
                area = 0.0
            fill_records.append({
                "svg_path": path,           # for skia conversion later
                "d_orig": d,
                "area": area,
                "color_hex": hex_c,
                "label_pos": label_pos,
            })

        if _is_fixed_color(stroke_rgb) and stroke_w > 0:
            stroke_lines.append(f"{d}|0|{stroke_w:.2f}|0|0")

    # Merge similar colors before sorting/subtracting so the palette is clean.
    _merge_similar_colors(fill_records, color_merge_tolerance, log)

    # Sort fills largest-first → fills[0] is bottom layer, fills[-1] is on top
    fill_records.sort(key=lambda r: r["area"], reverse=True)

    # ── Path subtraction: each fill loses pixels covered by anything above it
    # so painted regions never visually overlap.
    fill_only: list[str] = []
    if subtract_overlaps and _HAS_PATHOPS and len(fill_records) > 1:
        log(f"[svg→cbn] subtracting overlaps from {len(fill_records)} fills…")
        # Build skia paths once
        sk_paths = [_svgpath_to_skia(r["svg_path"]) for r in fill_records]

        # Top-to-bottom: for each fill, subtract union of all fills above it.
        above_union: SkPath | None = None
        # We process in REVERSE (top first), so we can accumulate above_union.
        new_d_list: list[str | None] = [None] * len(fill_records)
        for i in range(len(fill_records) - 1, -1, -1):
            current = sk_paths[i]
            if above_union is not None:
                try:
                    current = sk_op(current, above_union, PathOp.DIFFERENCE)
                except Exception as e:
                    log(f"  [warning] pathops DIFFERENCE failed for region {i}, falling back to original: {e}")
                    current = sk_paths[i]  # fallback
            
            new_d_list[i] = _skia_to_d(current)
            
            try:
                if above_union is None:
                    above_union = current
                else:
                    above_union = sk_op(above_union, current, PathOp.UNION)
            except Exception as e:
                log(f"  [warning] pathops UNION failed at region {i}: {e}")
                # if union fails, we just keep the previous union to avoid corrupted state

        for r, new_d in zip(fill_records, new_d_list):
            if not new_d:    # entire region was covered → skip
                continue
            fill_only.append(
                f"{new_d}|{r['color_hex']}|0|{r['label_pos']}|{FONT_SIZE}"
            )
            # Only add auto-outline if the region is black
            if auto_outline_width > 0 and r['color_hex'] == "000000":
                stroke_lines.append(f"{new_d}|0|{auto_outline_width:.2f}|0|0")
    else:
        if subtract_overlaps and not _HAS_PATHOPS:
            log("[svg→cbn] skia-pathops missing → skipping overlap subtraction")
        for r in fill_records:
            fill_only.append(
                f"{r['d_orig']}|{r['color_hex']}|0|{r['label_pos']}|{FONT_SIZE}"
            )
            # Only add auto-outline if the region is black
            if auto_outline_width > 0 and r['color_hex'] == "000000":
                stroke_lines.append(f"{r['d_orig']}|0|{auto_outline_width:.2f}|0|0")

    log(f"[svg→cbn] {n_total} shapes parsed, {n_skipped} skipped")
    log(f"  → {len(fill_only)} fill, {len(stroke_lines)} stroke, {len(raster_lines)} raster | canvas {output_canvas}px")

    viewport = (0, 0, output_canvas, output_canvas)
    return fill_only + stroke_lines + raster_lines, viewport


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("input", help="Input SVG file")
    ap.add_argument("output", help="Output Iceors data file (`{key}b`)")
    ap.add_argument("--canvas", type=int, default=OUTPUT_CANVAS)
    ap.add_argument("--no-subtract", action="store_true",
                    help="Disable overlap subtraction (keep raw paths)")
    ap.add_argument("--outline", type=float, default=0.0,
                    help="Auto-add black stroke of given px width to every fill path "
                         "(0 = off)")
    ap.add_argument("--merge-tolerance", type=float, default=0.0,
                    help="Merge colors within this RGB Euclidean distance "
                         "(typical 10-30; 0 = off)")
    ap.add_argument("--raster-lines", action="store_true",
                    help="Use OpenCV to extract lines from grayscale-rendered SVG "
                         "(more accurate for messy vectors)")
    ap.add_argument("--raster-threshold", type=int, default=200,
                    help="Threshold (0-255) for raster line extraction "
                         "(lower = more aggressive/thicker lines)")
    args = ap.parse_args()

    try:
        lines, _ = svg_to_lines(
            args.input, output_canvas=args.canvas,
            subtract_overlaps=not args.no_subtract,
            auto_outline_width=args.outline,
            color_merge_tolerance=args.merge_tolerance,
            use_raster_lines=args.raster_lines,
            raster_threshold=args.raster_threshold,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines))
    print(f"Done — {len(lines)} lines → {args.output} (canvas {args.canvas}px)")


if __name__ == "__main__":
    main()
