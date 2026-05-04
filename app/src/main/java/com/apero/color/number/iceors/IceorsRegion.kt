package com.apero.color.number.iceors

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Region
import kotlin.math.max
import kotlin.math.min

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

    /**
     * Pole of inaccessibility + inscribed radius. The pole is the interior
     * point farthest from any boundary — visually the most-central spot, and
     * a natural anchor for the label. The radius is the canvas-space distance
     * from that pole to the nearest boundary, used by callers to size text so
     * large regions get larger digits. Approximated by rasterising the path
     * into a small mask and taking the pixel with maximum 3-4 chamfer
     * distance to the nearest outside pixel.
     */
    private data class LabelGeometry(val x: Float, val y: Float, val radius: Float)
    private val labelGeometry: LabelGeometry by lazy { computePoleOfInaccessibility() }
    val labelCenterX: Float get() = labelGeometry.x
    val labelCenterY: Float get() = labelGeometry.y
    /** Canvas-space radius of the largest circle that fits inside the region, centered at the label anchor. */
    val labelInscribedRadius: Float get() = labelGeometry.radius

    private fun computePoleOfInaccessibility(): LabelGeometry {
        val cxFallback = bounds.centerX()
        val cyFallback = bounds.centerY()
        val bw = bounds.width()
        val bh = bounds.height()
        val fallback = LabelGeometry(cxFallback, cyFallback, min(bw, bh) / 2f)
        if (bw <= 0f || bh <= 0f) return fallback

        // Resolution: cap longer side at MASK_MAX_SIDE px. Adds a 1px border
        // so edge pixels register as "outside" in the distance transform.
        val longer = max(bw, bh)
        val scale = (MASK_MAX_SIDE / longer).coerceAtMost(1f)
        val w = (bw * scale).toInt().coerceAtLeast(2) + 2
        val h = (bh * scale).toInt().coerceAtLeast(2) + 2

        val mask = Bitmap.createBitmap(w, h, Bitmap.Config.ALPHA_8)
        val canvas = Canvas(mask)
        canvas.translate(1f, 1f)
        canvas.scale(scale, scale)
        canvas.translate(-bounds.left, -bounds.top)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            color = Color.BLACK
        }
        canvas.drawPath(path, paint)

        val pixels = IntArray(w * h)
        mask.getPixels(pixels, 0, w, 0, 0, w, h)
        mask.recycle()

        // 3-4 chamfer distance transform. Inside pixels start at INF, outside
        // at 0; two passes propagate min distance.
        val inf = Int.MAX_VALUE / 4
        val dist = IntArray(w * h) { if ((pixels[it] ushr 24) > 0) inf else 0 }

        for (y in 0 until h) {
            for (x in 0 until w) {
                val i = y * w + x
                if (dist[i] == 0) continue
                if (x > 0) dist[i] = min(dist[i], dist[i - 1] + 3)
                if (y > 0) {
                    dist[i] = min(dist[i], dist[i - w] + 3)
                    if (x > 0) dist[i] = min(dist[i], dist[i - w - 1] + 4)
                    if (x < w - 1) dist[i] = min(dist[i], dist[i - w + 1] + 4)
                }
            }
        }
        for (y in h - 1 downTo 0) {
            for (x in w - 1 downTo 0) {
                val i = y * w + x
                if (dist[i] == 0) continue
                if (x < w - 1) dist[i] = min(dist[i], dist[i + 1] + 3)
                if (y < h - 1) {
                    dist[i] = min(dist[i], dist[i + w] + 3)
                    if (x > 0) dist[i] = min(dist[i], dist[i + w - 1] + 4)
                    if (x < w - 1) dist[i] = min(dist[i], dist[i + w + 1] + 4)
                }
            }
        }

        var bestI = -1
        var bestD = 0
        for (i in dist.indices) {
            if (dist[i] > bestD) {
                bestD = dist[i]
                bestI = i
            }
        }
        if (bestI < 0) return fallback

        val mx = bestI % w
        val my = bestI / w
        // Inverse of the canvas transform applied above:
        //   maskX = (canvasX - bounds.left) * scale + 1   →   canvasX = (maskX - 1) / scale + bounds.left
        // Use mx + 0.5 so we anchor at the pixel's center, not its top-left corner.
        val canvasX = (mx + 0.5f - 1f) / scale + bounds.left
        val canvasY = (my + 0.5f - 1f) / scale + bounds.top
        // Chamfer-3 = 1 mask-pixel orthogonal step → divide by 3 for mask px,
        // then by scale for canvas units.
        val canvasRadius = (bestD / 3f) / scale
        return LabelGeometry(canvasX, canvasY, canvasRadius)
    }

    companion object {
        /** Cap on the longer side of the rasterised mask used for label centering. */
        private const val MASK_MAX_SIDE = 96f
    }
}
