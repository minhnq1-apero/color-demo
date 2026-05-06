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
import sys
from typing import Optional

from svgelements import (
    SVG, Shape, Path as SvgPath, Matrix,
    Move, Line as PathLine, CubicBezier, QuadraticBezier, Arc, Close,
)

OUTPUT_CANVAS = 2048
FONT_SIZE = 12


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Bump colors that Android's classify() drops or treats as decoration."""
    if r == 0 and g == 0 and b == 0:
        r, g, b = 1, 1, 1
    elif r == 255 and g == 255 and b == 255:
        r, g, b = 254, 254, 254
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


def _path_centroid(path: SvgPath) -> tuple[float, float]:
    """Bounding-box center — good enough for label placement."""
    bb = path.bbox()
    if bb is None:
        return 0.0, 0.0
    x0, y0, x1, y1 = bb
    return (x0 + x1) / 2, (y0 + y1) / 2


def _color_to_rgb(c) -> Optional[tuple[int, int, int]]:
    """
    svgelements.Color → (r, g, b) or None if 'none'/transparent.
    Handles Color, named colors, and 'none' string.
    """
    if c is None:
        return None
    s = str(c).strip().lower()
    if s in ("none", "transparent", ""):
        return None
    try:
        return int(c.red), int(c.green), int(c.blue)
    except AttributeError:
        return None


def svg_to_lines(
    svg_input,
    output_canvas: int = OUTPUT_CANVAS,
    log=print,
) -> tuple[list[str], tuple[int, int, int, int]]:
    """
    Parse an SVG file (path or file-like) into Iceors color-by-number lines.

    Returns (lines, viewport) where viewport = (x, y, width, height) in
    OUTPUT_CANVAS coordinates after squaring + padding.
    """
    svg = SVG.parse(svg_input)

    # Work out source dimensions from viewBox or width/height
    if svg.viewbox is not None:
        sw = float(svg.viewbox.width)
        sh = float(svg.viewbox.height)
        vx = float(svg.viewbox.x)
        vy = float(svg.viewbox.y)
    else:
        sw = float(svg.width or 0)
        sh = float(svg.height or 0)
        vx = vy = 0.0

    if sw <= 0 or sh <= 0:
        raise ValueError("SVG has no usable viewBox/width/height")

    # Pad to square so canvas is 1:1 (Iceors canvas is square)
    side = max(sw, sh)
    offset_x = (side - sw) / 2 - vx
    offset_y = (side - sh) / 2 - vy
    scale = output_canvas / side

    # Affine matrix: viewBox space → OUTPUT_CANVAS pixel space
    bake = Matrix(f"scale({scale}) translate({offset_x}, {offset_y})")

    fill_lines: list[tuple[float, str]] = []   # (area, line) for area-sort
    stroke_lines: list[str] = []

    n_total = 0
    n_skipped = 0
    for elem in svg.elements():
        if not isinstance(elem, Shape):
            continue
        # Convert any shape (Rect, Circle, Polygon, …) to a Path with all
        # parent transforms already applied.
        try:
            path = SvgPath(elem)
        except Exception:
            n_skipped += 1
            continue
        if len(path) == 0:
            continue

        # Apply viewBox→canvas transform — multiply attaches matrix, reify
        # bakes it into the segment coordinates.
        path = path * bake
        path.reify()

        d = _path_to_d(path)
        if not d:
            n_skipped += 1
            continue

        fill_rgb = _color_to_rgb(getattr(elem, "fill", None))
        stroke_rgb = _color_to_rgb(getattr(elem, "stroke", None))
        sw_raw = float(getattr(elem, "stroke_width", 0) or 0)
        # stroke-width is in source space; scale to canvas space.
        stroke_w = sw_raw * scale
        n_total += 1

        # FILL entry — only if fill is set and not 'none'
        if fill_rgb is not None:
            hex_c = rgb_to_hex(*fill_rgb)
            cx, cy = _path_centroid(path)
            label_pos = int(cy) * output_canvas + int(cx)
            try:
                area = abs(path.bbox()[2] - path.bbox()[0]) * abs(path.bbox()[3] - path.bbox()[1])
            except Exception:
                area = 0.0
            fill_lines.append((area, f"{d}|{hex_c}|0|{label_pos}|{FONT_SIZE}"))

        # STROKE entry — only if stroke is set with non-zero width
        if stroke_rgb is not None and stroke_w > 0:
            # Android's IceorsView renders all STROKE_LINE in black anyway,
            # so the stored color isn't important — keep "0" sentinel.
            stroke_lines.append(f"{d}|0|{stroke_w:.2f}|0|0")

    # Sort fills largest-first so smaller details overpaint backgrounds.
    fill_lines.sort(key=lambda t: t[0], reverse=True)
    fill_only = [line for _, line in fill_lines]

    log(f"[svg→cbn] {n_total} shapes parsed, {n_skipped} skipped")
    log(f"  → {len(fill_only)} fill, {len(stroke_lines)} stroke | canvas {output_canvas}px")

    viewport = (0, 0, output_canvas, output_canvas)
    return fill_only + stroke_lines, viewport


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("input", help="Input SVG file")
    ap.add_argument("output", help="Output Iceors data file (`{key}b`)")
    ap.add_argument("--canvas", type=int, default=OUTPUT_CANVAS)
    args = ap.parse_args()

    try:
        lines, _ = svg_to_lines(args.input, output_canvas=args.canvas)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines))
    print(f"Done — {len(lines)} lines → {args.output} (canvas {args.canvas}px)")


if __name__ == "__main__":
    main()
