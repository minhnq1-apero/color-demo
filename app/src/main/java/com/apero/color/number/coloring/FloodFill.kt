package com.apero.color.number.coloring

import android.graphics.Bitmap
import android.graphics.Point
import java.util.ArrayDeque

/**
 * Port of SYCB_FloodFill — scanline flood fill on a stock bitmap.
 *
 * A pixel is "fillable" iff it isn't a dark grey line. The line-art convention
 * is: R == G == B && R <= 100 → treated as boundary, fill stops there.
 */
class FloodFill(stock: Bitmap) {
    private val width = stock.width
    private val height = stock.height
    private val pixels = IntArray(width * height).also {
        stock.getPixels(it, 0, width, 0, 0, width, height)
    }
    private lateinit var visited: BooleanArray

    fun regionPixels(seed: Point): List<Point> {
        visited = BooleanArray(width * height)
        val out = ArrayList<Point>(1024)
        val queue = ArrayDeque<Point>()
        queue.add(seed)

        while (queue.isNotEmpty()) {
            val p = queue.removeFirst()
            var x = p.x
            val y = p.y

            while (x > 0 && fillable(x - 1, y)) x--
            while (x < width && fillable(x, y)) {
                visited[y * width + x] = true
                out.add(Point(x, y))
                if (y > 0 && fillable(x, y - 1)) queue.add(Point(x, y - 1))
                if (y < height - 1 && fillable(x, y + 1)) queue.add(Point(x, y + 1))
                x++
            }
        }
        return out
    }

    fun erasePoints(bitmap: Bitmap, seed: Point): Bitmap {
        val pts = regionPixels(seed)
        val copy = bitmap.copy(Bitmap.Config.ARGB_8888, true)
        for (p in pts) {
            if (p.x in 0 until copy.width && p.y in 0 until copy.height) {
                copy.setPixel(p.x, p.y, 0)
            }
        }
        return copy
    }

    private fun fillable(x: Int, y: Int): Boolean {
        val idx = y * width + x
        if (idx < 0 || idx >= pixels.size || visited[idx]) return false
        val px = pixels[idx]
        val r = (px shr 16) and 0xff
        val g = (px shr 8) and 0xff
        val b = px and 0xff
        return !(r == g && g == b && r <= 100)
    }
}
