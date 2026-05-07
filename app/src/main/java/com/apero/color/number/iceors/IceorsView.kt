package com.apero.color.number.iceors

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Shader
import android.util.AttributeSet
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View

/**
 * Mini port of Iceors' `DrawSurfaceViewNew` for the SP / SVG path format.
 *
 * Render order (mirrors `E1/a.java`):
 *   1. White background
 *   2. Fillable regions: gray placeholder if not done, palette color if done
 *   3. Active-palette highlight: tiled translucent squares over not-yet-done
 *      regions matching the selected palette color (mirrors `E1/a.java:138`
 *      where a `BitmapShader` with `TileMode.REPEAT` paints the candidates)
 *   4. Decorations:
 *        - STROKE_LINE → stroked path with the region's `strokeWidth`
 *        - BLACK_FILL  → solid black path
 *   5. Palette-index numbers at each region's `(labelX, labelY)`. Only drawn
 *      if the region's `fontSize × currentZoom` is at least [MIN_LABEL_PX]
 *      (mirrors the screen-space size check in `E1/b.java:78`).
 *
 * Hit-testing currently uses geometric `Region.contains` per fillable region.
 * The original app rasterises every region into an index bitmap with negative
 * pixel values (`E1/a.java:208-219`) and reads `(-2) - getPixel(x,y)` on tap
 * — that's an O(1) lookup vs our O(n) scan. Swap-in is a future optimisation.
 */
class IceorsView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyle: Int = 0,
) : View(context, attrs, defStyle) {

    companion object {
        /** Pattern tile size in canvas pixels. 16×16 with 4×4 cells gives a clear checker. */
        private const val TILE_SIZE = 16
        private const val TILE_CELL = 4

        /**
         * Visibility gate: a label only draws when the region's data-defined
         * `fontSize` would render to at least this many on-screen dp. So
         * `fontSize` controls *whether* a digit shows, not how big it is.
         */
        private const val MIN_LABEL_SCREEN_DP = 12f

        /**
         * Lower bound (dp) for digit height — used when a region is so small
         * its inscribed circle would render text below this size. Combined
         * with [MIN_LABEL_SCREEN_DP] it sets a readable floor at high zoom.
         */
        private const val LABEL_MIN_DP = 8f

        /** Upper bound (dp) so labels in big regions don't render absurdly large. */
        private const val LABEL_MAX_DP = 28f

        /**
         * Fraction of the inscribed-circle diameter used as the digit text
         * size. ~0.9× the radius keeps both tall ("9") and wide two-digit
         * labels comfortably inside the inscribed circle.
         */
        private const val LABEL_RADIUS_FACTOR = 0.9f

        /** Max zoom multiplier above the fit-to-view scale; pinch-in saturates here. */
        private const val MAX_ZOOM_FACTOR = 8f

        /** Min zoom multiplier; pinch-out can't go below the fit-to-view scale. */
        private const val MIN_ZOOM_FACTOR = 1f

        /** Hint focus aims for at least this multiple of fit-to-view so the region is comfortably visible. */
        private const val HINT_FOCUS_FACTOR = 2f
    }

    private val matrixView = Matrix()
    private val tmpMatrix = Matrix()
    private var asset: IceorsAsset.Loaded? = null
    private var activePaletteIndex: Int = -1
    private var activePaletteColor: Int = 0
    private val minLabelScreenPx = MIN_LABEL_SCREEN_DP * resources.displayMetrics.density
    private val labelMinScreenPx = LABEL_MIN_DP * resources.displayMetrics.density
    private val labelMaxScreenPx = LABEL_MAX_DP * resources.displayMetrics.density

    /** Fit-to-view scale, recomputed in [fitToView] so zoom clamps stay correct. */
    private var fitScale: Float = 1f

    private val placeholderColor = 0xFFE6E6E6.toInt()

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.BLACK
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    /**
     * "Reveal" fill paint: when an asset ships a finished image (`<key>c`),
     * completed regions are filled with that bitmap clipped to the region's
     * path instead of a flat palette color. This mirrors the original app's
     * `E1.a.o(Bitmap, scale)` setting a `BitmapShader` on the FILL paint —
     * for oil pics the bitmap holds the textured/photographic content the
     * user "uncovers" by coloring; for non-oil SPV pics the bitmap is just a
     * flat-color image so the visual matches solid palette fill anyway.
     */
    private val revealPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        isFilterBitmap = true
    }
    private var revealBitmap: Bitmap? = null
    private val blackFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.BLACK
    }
    private val numberPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.DKGRAY
        textAlign = Paint.Align.CENTER
    }

    /** Repeating-tile paint used to highlight regions of the active palette. */
    private val activePatternPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        isFilterBitmap = false
        style = Paint.Style.FILL
    }
    private var activePatternBitmap: Bitmap? = null

    /** Currently flashing hint region, with the timestamp the flash started. */
    private var hintRegion: IceorsRegion? = null
    private var hintStartMs: Long = 0L
    private val hintFlashMs = 900L
    private val hintFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
    }
    private val hintStrokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = 0xFFFFC107.toInt() // amber
    }

    var onProgressChanged: ((completed: Int, total: Int) -> Unit)? = null

    /** Fires after every fill (and on initial load) with `paletteIndex → done/total` per bucket. */
    var onPaletteProgressChanged: ((Map<Int, IntArray>) -> Unit)? = null

    /** If false, touch events (pan/zoom/tap) are ignored. Used during replay. */
    var isInteractionEnabled: Boolean = true

    private val scaleListener = object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
        override fun onScale(detector: ScaleGestureDetector): Boolean {
            if (!isInteractionEnabled) return false
            val current = currentZoom()
            val proposed = current * detector.scaleFactor
            val minScale = fitScale * MIN_ZOOM_FACTOR
            val maxScale = fitScale * MAX_ZOOM_FACTOR
            val effectiveFactor = when {
                proposed < minScale -> if (current > 0f) minScale / current else 1f
                proposed > maxScale -> if (current > 0f) maxScale / current else 1f
                else -> detector.scaleFactor
            }
            matrixView.postScale(effectiveFactor, effectiveFactor, detector.focusX, detector.focusY)
            invalidate()
            return true
        }
    }
    private val gestureListener = object : GestureDetector.SimpleOnGestureListener() {
        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
            if (!isInteractionEnabled) return false
            matrixView.postTranslate(-dx, -dy)
            invalidate()
            return true
        }

        override fun onSingleTapUp(e: MotionEvent): Boolean {
            if (!isInteractionEnabled) return false
            handleTap(e.x, e.y)
            return true
        }
    }

    private var replayAnimator: android.animation.ValueAnimator? = null

    /**
     * Resets all regions to un-completed and animates them being filled
     * sequentially over [durationMs]. Interaction is disabled during replay.
     */
    fun startReplay(durationMs: Long, onFinish: (() -> Unit)? = null) {
        val a = asset ?: return
        replayAnimator?.cancel()
        isInteractionEnabled = false
        
        // 1. Reset all
        val fills = a.fillables
        for (r in fills) r.completed = false
        
        // 2. Sort regions for a natural-feeling replay (by palette index, then position)
        val sorted = fills.sortedWith(compareBy({ it.paletteIndex }, { it.labelY }, { it.labelX }))
        
        // 3. Animate
        replayAnimator = android.animation.ValueAnimator.ofFloat(0f, 1f).apply {
            duration = durationMs
            interpolator = android.view.animation.LinearInterpolator()
            addUpdateListener { anim ->
                val progress = anim.animatedValue as Float
                val targetCount = (progress * sorted.size).toInt()
                
                var changed = false
                for (i in 0 until targetCount) {
                    if (!sorted[i].completed) {
                        sorted[i].completed = true
                        changed = true
                    }
                }
                if (changed) {
                    invalidate()
                }
            }
            addListener(object : android.animation.AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: android.animation.Animator) {
                    isInteractionEnabled = true
                    notifyProgress()
                    onFinish?.invoke()
                    replayAnimator = null
                }
            })
            start()
        }
    }

    private val scaleDetector = ScaleGestureDetector(context, scaleListener)
    private val gestureDetector = GestureDetector(context, gestureListener)

    fun setAsset(loaded: IceorsAsset.Loaded) {
        this.asset = loaded
        val first = loaded.palette.firstOrNull()
        if (first != null) {
            activePaletteIndex = first.index
            updateActivePattern(first.color)
        } else {
            activePaletteIndex = -1
        }
        // Re-bind any previously-set reveal bitmap to the new asset's canvas
        // size — the shader matrix depends on canvasSize / bitmap.width.
        revealBitmap?.let { rebuildRevealShader(it) }
        fitToView()
        notifyProgress()
        invalidate()
    }

    /**
     * Provide the per-asset finished bitmap (`<key>c`) used as the source
     * texture for completed regions. Pass null to clear (e.g. V pics that
     * don't ship one — those keep solid palette fill). Recycled bitmaps stay
     * the caller's responsibility; we only hold a reference.
     *
     * [revealDecorations] mirrors the original's `E1.d` (oil) override of
     * `o(Bitmap, scale)`: it ALSO routes the bitmap shader through the
     * stroke / black-fill paints, so line decorations and solid-black
     * accents render as the underlying image instead of opaque black —
     * giving oil pics their textured "transparent line" look. For non-oil
     * SPV pics (`E1.c`) the original leaves the stroke paint plain-black,
     * so we do the same when the flag is false.
     */
    @JvmOverloads
    fun setRevealBitmap(bitmap: Bitmap?, revealDecorations: Boolean = false) {
        revealBitmap = bitmap
        val shader = bitmap?.let { buildRevealShader(it) }
        revealPaint.shader = shader
        // Strokes / black-fill decorations: shader-on iff caller asked
        // (i.e. oil mode). Otherwise restore the solid colors so non-oil
        // assets keep their crisp black outlines.
        if (shader != null && revealDecorations) {
            strokePaint.shader = shader
            blackFillPaint.shader = shader
        } else {
            strokePaint.shader = null
            strokePaint.color = Color.BLACK
            blackFillPaint.shader = null
            blackFillPaint.color = Color.BLACK
        }
        invalidate()
    }

    private fun rebuildRevealShader(bitmap: Bitmap) {
        revealPaint.shader = buildRevealShader(bitmap)
    }

    private fun buildRevealShader(bitmap: Bitmap): BitmapShader {
        val canvasSize = asset?.canvasSize ?: bitmap.width.toFloat()
        val shader = BitmapShader(bitmap, Shader.TileMode.CLAMP, Shader.TileMode.CLAMP)
        // Map bitmap (sized bitmap.width × bitmap.height) to the canvas's
        // canvasSize × canvasSize coordinate space — same as the original's
        // `matrix.preScale(1/f7, 1/f7)` where f7 = bitmap.width / canvasSize.
        val mtx = Matrix()
        val s = canvasSize / bitmap.width.toFloat()
        mtx.preScale(s, s)
        shader.setLocalMatrix(mtx)
        return shader
    }

    /**
     * Auto-fills one un-completed region from the active palette after a
     * short flashing animation so the user can see which region the hint
     * picked. Returns false when there's nothing left to hint at — caller
     * can then disable / decrement its hint counter.
     */
    fun requestHint(): Boolean {
        val a = asset ?: return false
        val candidates = a.fillables.filter {
            !it.completed && (activePaletteIndex < 0 || it.paletteIndex == activePaletteIndex)
        }
        if (candidates.isEmpty()) return false
        val target = candidates.random()
        focusOn(target)
        hintRegion = target
        hintStartMs = System.currentTimeMillis()
        invalidate()
        postDelayed({
            target.completed = true
            hintRegion = null
            notifyProgress()
            invalidate()
        }, hintFlashMs)
        return true
    }

    /** Mark every fillable region as painted. */
    fun completeAll() {
        val a = asset ?: return
        var changed = false
        for (region in a.fillables) {
            if (!region.completed) {
                region.completed = true
                changed = true
            }
        }
        if (changed) {
            notifyProgress()
            invalidate()
        }
    }

    /**
     * Render the asset to a bitmap at canvas resolution (default 2048×2048).
     * Uses palette colors (or the reveal bitmap if set) for completed regions;
     * uncompleted regions are left white. Decorations are drawn on top.
     */
    fun exportBitmap(): Bitmap? {
        val a = asset ?: return null
        val size = a.canvasSize.toInt().coerceAtLeast(1)
        val bm = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val c = Canvas(bm)
        c.drawColor(Color.WHITE)
        val hasReveal = revealBitmap != null
        for (region in a.fillables) {
            if (!region.completed) continue
            if (hasReveal) {
                c.drawPath(region.path, revealPaint)
            } else {
                fillPaint.color = region.color
                c.drawPath(region.path, fillPaint)
            }
        }
        for (deco in a.decorations) {
            when (deco.kind) {
                IceorsRegion.Kind.STROKE_LINE -> {
                    strokePaint.strokeWidth = deco.strokeWidth.coerceAtLeast(0.5f)
                    c.drawPath(deco.path, strokePaint)
                }
                IceorsRegion.Kind.BLACK_FILL -> c.drawPath(deco.path, blackFillPaint)
                IceorsRegion.Kind.FILLABLE -> Unit
            }
        }
        return bm
    }

    /** True when there's at least one un-completed region for the active palette. */
    fun hasHintCandidate(): Boolean {
        val a = asset ?: return false
        return a.fillables.any {
            !it.completed && (activePaletteIndex < 0 || it.paletteIndex == activePaletteIndex)
        }
    }

    /** Selects the palette bucket the user is currently coloring. */
    fun selectPaletteIndex(index: Int) {
        if (activePaletteIndex == index) return
        activePaletteIndex = index
        val color = asset?.palette?.firstOrNull { it.index == index }?.color
        if (color != null) updateActivePattern(color)
        invalidate()
    }

    /** @deprecated Use [selectPaletteIndex]. */
    @Deprecated("renamed", ReplaceWith("selectPaletteIndex(index)"))
    fun selectLevel(index: Int) = selectPaletteIndex(index)

    private fun updateActivePattern(color: Int) {
        if (color == activePaletteColor && activePatternBitmap != null) return
        activePaletteColor = color
        val bm = Bitmap.createBitmap(TILE_SIZE, TILE_SIZE, Bitmap.Config.ARGB_8888)
        // 25% alpha tint of the palette color in a 4×4 checkerboard layout.
        val tinted = (color and 0x00FFFFFF) or 0x55000000
        val transparent = 0
        for (y in 0 until TILE_SIZE) {
            for (x in 0 until TILE_SIZE) {
                val on = (x / TILE_CELL + y / TILE_CELL) % 2 == 0
                bm.setPixel(x, y, if (on) tinted else transparent)
            }
        }
        activePatternBitmap = bm
        activePatternPaint.shader = BitmapShader(bm, Shader.TileMode.REPEAT, Shader.TileMode.REPEAT)
    }

    private fun fitToView() {
        val a = asset ?: return
        if (width == 0 || height == 0) return
        val scale = minOf(width / a.canvasSize, height / a.canvasSize)
        fitScale = scale
        matrixView.reset()
        matrixView.setScale(scale, scale)
        matrixView.postTranslate(
            (width - a.canvasSize * scale) / 2f,
            (height - a.canvasSize * scale) / 2f,
        )
    }

    /**
     * Animate-free pan + optional zoom-in so a target region sits roughly at
     * the centre of the view. Used by [requestHint] so the user can see which
     * region the hint picked even if they were zoomed in elsewhere.
     */
    private fun focusOn(region: IceorsRegion) {
        if (width == 0 || height == 0) return
        val current = currentZoom()
        val targetScale = fitScale * HINT_FOCUS_FACTOR
        // Bump zoom in only when the user is currently zoomed out further
        // than HINT_FOCUS_FACTOR — never shrink them in.
        if (current < targetScale) {
            val factor = (targetScale / current).coerceAtMost(
                fitScale * MAX_ZOOM_FACTOR / current.coerceAtLeast(0.0001f)
            )
            matrixView.postScale(factor, factor, width / 2f, height / 2f)
        }
        val pts = floatArrayOf(region.bounds.centerX(), region.bounds.centerY())
        matrixView.mapPoints(pts)
        matrixView.postTranslate(width / 2f - pts[0], height / 2f - pts[1])
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        super.onSizeChanged(w, h, ow, oh)
        fitToView()
    }

    private fun handleTap(screenX: Float, screenY: Float) {
        val a = asset ?: return
        if (activePaletteIndex < 0) return

        val pts = floatArrayOf(screenX, screenY)
        matrixView.invert(tmpMatrix)
        tmpMatrix.mapPoints(pts)
        val tx = pts[0].toInt()
        val ty = pts[1].toInt()

        for (region in a.fillables) {
            if (region.completed) continue
            if (region.paletteIndex != activePaletteIndex) continue
            if (region.contains(tx, ty)) {
                region.completed = true
                notifyProgress()
                invalidate()
                return
            }
        }
    }

    private fun notifyProgress() {
        val a = asset ?: return
        val fills = a.fillables
        val done = fills.count { it.completed }
        onProgressChanged?.invoke(done, fills.size)

        val perPalette = HashMap<Int, IntArray>(a.palette.size)
        for (entry in a.palette) perPalette[entry.index] = intArrayOf(0, 0)
        for (region in fills) {
            val arr = perPalette[region.paletteIndex] ?: continue
            arr[1] += 1
            if (region.completed) arr[0] += 1
        }
        onPaletteProgressChanged?.invoke(perPalette)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val a = asset ?: return
        canvas.drawColor(Color.WHITE)
        canvas.save()
        canvas.concat(matrixView)
        val zoom = currentZoom()

        // 1. Fillable regions
        //    - Unpainted: solid placeholder gray.
        //    - Painted + reveal bitmap available: shader-fill from the
        //      finished image clipped to the region's path (oil-style reveal).
        //    - Painted + no reveal bitmap: solid palette color.
        val hasReveal = revealBitmap != null
        for (region in a.fillables) {
            if (!region.completed) {
                fillPaint.color = placeholderColor
                canvas.drawPath(region.path, fillPaint)
            } else if (hasReveal) {
                canvas.drawPath(region.path, revealPaint)
            } else {
                fillPaint.color = region.color
                canvas.drawPath(region.path, fillPaint)
            }
        }

        // 2. Active-palette highlight (translucent tiled squares)
        if (activePaletteIndex >= 0 && activePatternBitmap != null) {
            for (region in a.fillables) {
                if (region.completed) continue
                if (region.paletteIndex != activePaletteIndex) continue
                canvas.drawPath(region.path, activePatternPaint)
            }
        }

        // 3. Decorations on top of fills
        for (deco in a.decorations) {
            when (deco.kind) {
                IceorsRegion.Kind.STROKE_LINE -> {
                    strokePaint.strokeWidth = deco.strokeWidth.coerceAtLeast(0.5f)
                    canvas.drawPath(deco.path, strokePaint)
                }
                IceorsRegion.Kind.BLACK_FILL -> canvas.drawPath(deco.path, blackFillPaint)
                IceorsRegion.Kind.FILLABLE -> Unit
            }
        }

        // 4. Hint flash — brief amber pulse over the region the user asked for.
        hintRegion?.let { r ->
            val elapsed = System.currentTimeMillis() - hintStartMs
            if (elapsed < hintFlashMs) {
                // Two-cycle sin pulse: alpha oscillates 0 → ~80% → 0 → ~80%.
                val phase = (elapsed.toFloat() / hintFlashMs) * 2f * Math.PI.toFloat()
                val pulse = (kotlin.math.sin(phase).coerceAtLeast(0f))
                val alpha = (pulse * 200).toInt().coerceIn(0, 255)
                hintFillPaint.color = ((alpha shl 24) or 0x00FFC107).toInt()
                canvas.drawPath(r.path, hintFillPaint)
                hintStrokePaint.strokeWidth = (4f / zoom).coerceAtLeast(1f)
                hintStrokePaint.alpha = (200 + alpha / 5).coerceIn(0, 255)
                canvas.drawPath(r.path, hintStrokePaint)
                postInvalidateOnAnimation()
            }
        }

        // 5. Region numbers — drawn at each region's pole-of-inaccessibility
        //    (the geometric most-central interior point). Text size scales
        //    with the region's inscribed-circle radius so big areas get
        //    readable digits and tiny ones don't overflow, with a screen-dp
        //    floor and ceiling so zoom doesn't make digits unreadable or
        //    cartoonishly large. The data-file `fontSize` is still used as
        //    the visibility gate: regions whose `fontSize × zoom` is below
        //    the on-screen threshold stay hidden until the user zooms in.
        val minCanvasFont = minLabelScreenPx / zoom
        val minScreenCanvas = labelMinScreenPx / zoom
        val maxScreenCanvas = labelMaxScreenPx / zoom
        val rect = Rect()
        if (isInteractionEnabled) {
            for (region in a.fillables) {
                if (region.completed) continue
                if (region.fontSize < minCanvasFont) continue
                val text = region.paletteIndex.toString()
                // Two-digit labels need to fit horizontally too — narrow that side.
                val widthBudget = region.labelInscribedRadius * 2f / text.length.coerceAtLeast(1)
                val heightBudget = region.labelInscribedRadius * 2f
                val canvasFont = (minOf(widthBudget, heightBudget) * LABEL_RADIUS_FACTOR)
                    .coerceIn(minScreenCanvas, maxScreenCanvas)
                numberPaint.textSize = canvasFont
                numberPaint.color = region.labelColor ?: Color.DKGRAY
                numberPaint.getTextBounds(text, 0, text.length, rect)
                canvas.drawText(
                    text,
                    region.labelCenterX,
                    region.labelCenterY + rect.height() / 2f,
                    numberPaint,
                )
            }
        }
        canvas.restore()
    }

    private fun currentZoom(): Float {
        val v = FloatArray(9)
        matrixView.getValues(v)
        return minOf(v[Matrix.MSCALE_X], v[Matrix.MSCALE_Y])
    }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        scaleDetector.onTouchEvent(event)
        gestureDetector.onTouchEvent(event)
        return true
    }
}
