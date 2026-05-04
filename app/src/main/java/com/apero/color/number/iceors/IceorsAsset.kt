package com.apero.color.number.iceors

import android.content.Context
import android.graphics.Path
import androidx.core.graphics.PathParser
import java.io.BufferedReader
import java.io.File
import java.io.FileReader

/**
 * Parses an Iceors `<key>b` file into regions + palette, matching the logic
 * in `C1/u.java:792-868` and `A1/c.java:90-99` from the decompiled APK.
 *
 * Line format (5 or 6 pipe-delimited fields):
 *
 * ```
 * path | colorHex | strokeWidth | fontSize | fontHeight | [labelHex]
 * ```
 *
 * Region classification (see [IceorsRegion.Kind]):
 *   - white + zero stroke → dropped
 *   - non-zero stroke    → STROKE_LINE (decorative outline)
 *   - pure-black color   → BLACK_FILL (decorative solid fill)
 *   - otherwise          → FILLABLE (the user-paintable region)
 *
 * The displayed number on a region is its **palette bucket index** (1-based,
 * in encounter order — same as `E1.a.f1186l[i] = String.valueOf(i+1)`), not
 * any field from the file.
 */
object IceorsAsset {

    data class Loaded(
        val regions: List<IceorsRegion>,
        val palette: List<PaletteEntry>,
        val canvasSize: Float,
    ) {
        /** Convenience: only the regions the user can paint. */
        val fillables: List<IceorsRegion> get() = regions.filter { it.kind == IceorsRegion.Kind.FILLABLE }

        /** Convenience: stroked or filled-black decorations rendered above fills. */
        val decorations: List<IceorsRegion> get() = regions.filter { it.kind != IceorsRegion.Kind.FILLABLE }
    }

    /** A palette bucket — one entry per distinct fillable color. */
    data class PaletteEntry(val index: Int, val color: Int)

    fun load(context: Context, pathFile: String, canvasSize: Float = 2048f): Loaded =
        context.assets.open(pathFile).bufferedReader().use { parseLines(it.lineSequence(), canvasSize) }

    /** Load from a file on disk — typically the `<key>b` produced by [com.apero.color.number.iceors.network.IceorsDownloader]. */
    fun loadFromFile(file: File, canvasSize: Float = 2048f): Loaded =
        BufferedReader(FileReader(file)).use { parseLines(it.lineSequence(), canvasSize) }

    private fun parseLines(lines: Sequence<String>, canvasSize: Float): Loaded {
        val regions = mutableListOf<IceorsRegion>()
        val paletteOrder = LinkedHashMap<Int, Int>()
        val canvasW = canvasSize.toInt().coerceAtLeast(1)

        for (raw in lines) {
            val line = raw.trim().ifEmpty { continue }
            val parts = line.split('|')
            if (parts.size < 5) continue
            val path = parseSvg(parts[0]) ?: continue

            val color = parseHexColor(parts[1]) ?: continue
            val strokeWidth = parts[2].toFloatOrNull() ?: 0f
            val labelPosPacked = parts[3].toIntOrNull() ?: 0
            val fontSize = parts[4].toIntOrNull() ?: 0
            val labelColor = parts.getOrNull(5)?.let(::parseHexColor)

            val kind = classify(color, strokeWidth) ?: continue

            // Decode packed label position: y * canvasW + x (see C1/u.java:347).
            val labelX = (labelPosPacked % canvasW).toFloat()
            val labelY = (labelPosPacked / canvasW).toFloat()

            val region = IceorsRegion(
                color = color,
                strokeWidth = strokeWidth,
                fontSize = fontSize,
                labelColor = labelColor,
                labelX = labelX,
                labelY = labelY,
                path = path,
                kind = kind,
            )
            if (kind == IceorsRegion.Kind.FILLABLE) {
                val idx = paletteOrder.getOrPut(color) { paletteOrder.size + 1 }
                region.paletteIndex = idx
            }
            regions += region
        }

        val palette = paletteOrder.map { (color, idx) -> PaletteEntry(index = idx, color = color) }
        return Loaded(regions, palette, canvasSize)
    }

    /** Returns the kind, or null if the line should be dropped. Matches `A1.c.a()`. */
    private fun classify(color: Int, strokeWidth: Float): IceorsRegion.Kind? {
        // f122e == -1 (white) AND f121d == 0 → invalid, drop
        if (color == -1 && strokeWidth == 0f) return null
        // f121d != 0 → stroked decoration (f132o)
        if (strokeWidth != 0f) return IceorsRegion.Kind.STROKE_LINE
        // (f122e & 0xFFFFFF) == 0 → pure-black filled decoration (f133p)
        if ((color and 0xFFFFFF) == 0) return IceorsRegion.Kind.BLACK_FILL
        return IceorsRegion.Kind.FILLABLE
    }

    /**
     * Parses a color field. The data files use variable-width hex — most
     * fillables are full "RRGGBB" but pure black is often shortened to "0"
     * (and other low values can be 1–5 chars). Mirrors the original
     * `Integer.parseInt(parts[1], 16) | 0xFF000000` in `C1/u.java:826`.
     */
    private fun parseHexColor(hex: String): Int? {
        if (hex.isEmpty() || !hex.all { it.isHex() }) return null
        val rgb = runCatching { hex.toLong(16) }.getOrNull() ?: return null
        if (rgb < 0 || rgb > 0xFFFFFFL) return null
        return rgb.toInt() or 0xFF000000.toInt()
    }

    private fun parseSvg(data: String): Path? = try {
        PathParser.createPathFromPathData(data)
    } catch (_: Throwable) {
        null
    }

    private fun Char.isHex() = this in '0'..'9' || this in 'a'..'f' || this in 'A'..'F'
}
