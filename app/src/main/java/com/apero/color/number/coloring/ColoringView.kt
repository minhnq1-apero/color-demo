package com.apero.color.number.coloring

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Point
import android.util.AttributeSet
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import com.apero.color.number.model.Coordinate
import com.apero.color.number.model.Level

/**
 * Mini port of SYCB_KKView. Draws layered bitmaps and reveals colored regions
 * underneath when the user taps inside a region of the currently selected level.
 *
 * Layer stack (bottom → top):
 *   mBoard  : fill.png  — fully colored answer image
 *   mStock  : stock.png — white canvas with line-art + numbers
 *   numbers : drawn live by Canvas.drawText for incomplete coords
 */
class ColoringView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyle: Int = 0,
) : View(context, attrs, defStyle) {

    private val matrixView = Matrix()
    private var mBoard: Bitmap? = null
    private var mStock: Bitmap? = null
    private var floodFill: FloodFill? = null

    private var levels: List<Level> = emptyList()
    private var activeLevel: Level? = null

    private val numberPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFF000000.toInt()
    }

    var onRegionFilled: (() -> Unit)? = null
    var onLevelCompleted: ((Level) -> Unit)? = null

    private val scaleListener = object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(detector: ScaleGestureDetector): Boolean {
            matrixView.postScale(detector.scaleFactor, detector.scaleFactor, detector.focusX, detector.focusY)
            invalidate()
            return true
        }
    }
    private val gestureListener = object : GestureDetector.SimpleOnGestureListener() {
        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
            matrixView.postTranslate(-dx, -dy)
            invalidate()
            return true
        }

        override fun onSingleTapUp(e: MotionEvent): Boolean {
            handleTap(e.x, e.y)
            return true
        }
    }
    private val scaleDetector = ScaleGestureDetector(context, scaleListener)
    private val gestureDetector = GestureDetector(context, gestureListener)

    fun setData(board: Bitmap, stock: Bitmap, levels: List<Level>) {
        mBoard = board
        mStock = stock
        floodFill = FloodFill(stock)
        this.levels = levels

        val ff = floodFill!!
        for (level in levels) {
            for (coord in level.coordinates) {
                coord.points = ff.regionPixels(Point(coord.x, coord.y))
            }
        }
        fitToView()
        invalidate()
    }

    fun selectLevel(level: Level) {
        activeLevel = level
        invalidate()
    }

    /** Composite (board + stock) into a fresh ARGB_8888 bitmap. */
    fun snapshot(): Bitmap? {
        val board = mBoard ?: return null
        val stock = mStock ?: return null
        val out = Bitmap.createBitmap(board.width, board.height, Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        c.drawBitmap(board, 0f, 0f, null)
        c.drawBitmap(stock, 0f, 0f, null)
        return out
    }

    private fun fitToView() {
        val board = mBoard ?: return
        if (width == 0 || height == 0) return
        val scale = minOf(width / board.width.toFloat(), height / board.height.toFloat())
        matrixView.setScale(scale, scale)
        matrixView.postTranslate(
            (width - board.width * scale) / 2f,
            (height - board.height * scale) / 2f,
        )
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        super.onSizeChanged(w, h, ow, oh)
        fitToView()
    }

    private fun handleTap(screenX: Float, screenY: Float) {
        val level = activeLevel ?: return
        val flood = floodFill ?: return
        val stock = mStock ?: return

        val pts = floatArrayOf(screenX, screenY)
        val inv = Matrix()
        matrixView.invert(inv)
        inv.mapPoints(pts)
        val tx = pts[0].toInt()
        val ty = pts[1].toInt()
        if (tx < 0 || ty < 0) return

        val tap = Point(tx, ty)
        for (coord in level.coordinates) {
            if (coord.completed) continue
            val region = coord.points ?: continue
            if (region.contains(tap)) {
                mStock = flood.erasePoints(stock, tap)
                coord.completed = true
                onRegionFilled?.invoke()
                if (level.isCompleted) onLevelCompleted?.invoke(level)
                invalidate()
                return
            }
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.save()
        canvas.concat(matrixView)
        mBoard?.takeIf { !it.isRecycled }?.let { canvas.drawBitmap(it, 0f, 0f, null) }
        mStock?.takeIf { !it.isRecycled }?.let { canvas.drawBitmap(it, 0f, 0f, null) }

        val zoom = currentZoom()
        val limit = textLimitFor(zoom)
        for (level in levels) {
            for (coord in level.coordinates) {
                if (coord.completed) continue
                if (coord.textSize < limit) continue
                drawNumber(canvas, coord, level.level)
            }
        }
        canvas.restore()
    }

    private fun currentZoom(): Float {
        val m = FloatArray(9)
        matrixView.getValues(m)
        return minOf(m[Matrix.MSCALE_X], m[Matrix.MSCALE_Y])
    }

    private fun textLimitFor(zoom: Float): Int = when {
        zoom <= 1f -> 25
        zoom <= 1.5f -> 21
        zoom <= 2f -> 15
        zoom <= 3f -> 9
        zoom <= 4f -> 5
        else -> 0
    }

    private fun drawNumber(canvas: Canvas, coord: Coordinate, value: Int) {
        numberPaint.textSize = coord.textSize.toFloat()
        val text = value.toString()
        val w = numberPaint.measureText(text)
        val fm = numberPaint.fontMetrics
        val tx = coord.x - w / 2f
        val ty = coord.y + (fm.bottom - fm.top) / 2f - fm.bottom
        canvas.drawText(text, tx, ty, numberPaint)
    }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        scaleDetector.onTouchEvent(event)
        gestureDetector.onTouchEvent(event)
        return true
    }

    fun release() {
        mBoard?.takeIf { !it.isRecycled }?.recycle()
        mStock?.takeIf { !it.isRecycled }?.recycle()
        mBoard = null
        mStock = null
    }
}
