package com.apero.color.number.iceors

import android.graphics.Path
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Region

/**
 * One parsed line from a `<key>b` data file. Mirrors `A1.c` in the original
 * APK (`jadx_out/sources/A1/c.java`). Field names match what each pipe slot
 * actually means in `C1/u.java:825-832`:
 *
 * ```
 * path | colorHex | strokeWidth | labelPosPacked | fontSize | [labelHex]
 *  [0]      [1]         [2]            [3]          [4]        [5]
 * ```
 *
 * `labelPosPacked` encodes the label's draw position as `y * canvasW + x` in
 * canvas pixels — see `C1/u.java:347` (`f125h % canvasWidth`, `f125h /
 * canvasWidth`).
 *
 * [kind] is computed by [IceorsAsset] using the rules from `A1.c.a()`:
 *   - `color == 0xFFFFFFFF` and `strokeWidth == 0`     → drop entirely
 *   - `strokeWidth != 0`                               → STROKE_LINE
 *   - `(color & 0xFFFFFF) == 0` (pure black RGB)       → BLACK_FILL
 *   - otherwise                                        → FILLABLE
 */
class IceorsRegion(
    val color: Int,
    val strokeWidth: Float,
    val fontSize: Int,
    val labelColor: Int?,
    val labelX: Float,
    val labelY: Float,
    val path: Path,
    val kind: Kind,
) {
    enum class Kind { FILLABLE, STROKE_LINE, BLACK_FILL }

    /** Assigned by [IceorsAsset] after grouping fills by color. -1 for non-fills. */
    var paletteIndex: Int = -1

    val bounds: RectF = RectF().also { path.computeBounds(it, true) }

    private val region: Region by lazy {
        val clip = Rect(
            bounds.left.toInt() - 1,
            bounds.top.toInt() - 1,
            bounds.right.toInt() + 1,
            bounds.bottom.toInt() + 1,
        )
        Region().apply { setPath(path, Region(clip)) }
    }

    var completed: Boolean = false

    fun contains(x: Int, y: Int): Boolean {
        if (!bounds.contains(x.toFloat(), y.toFloat())) return false
        return region.contains(x, y)
    }
}
