package com.apero.color.number.iceors

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Horizontal palette strip. Each swatch is a 48dp circle filled with the
 * palette color, ringed by a progress arc that mirrors how many regions of
 * that color the user has filled. Once a bucket is fully done, the digit is
 * replaced with ✓ and the swatch becomes non-interactive — same UX as the
 * SYCB-style flood-fill view.
 *
 * @param palette ordered list of palette entries
 * @param progress map of `paletteIndex → IntArray(done, total)`; missing keys
 *                 are treated as `0/?` (untouched).
 * @param activeIndex currently selected palette index (or -1)
 * @param onPick fired when the user taps a non-completed swatch
 */
@Composable
fun IceorsPalette(
    palette: List<IceorsAsset.PaletteEntry>,
    progress: Map<Int, IntArray>,
    activeIndex: Int,
    onPick: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyRow(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(palette, key = { it.index }) { entry ->
            val counts = progress[entry.index]
            val done = counts?.getOrNull(0) ?: 0
            val total = counts?.getOrNull(1) ?: 0
            val completed = total in 1..done
            val ratio = if (total == 0) 0f else done.toFloat() / total
            PaletteSwatch(
                entry = entry,
                ratio = ratio,
                done = done,
                total = total,
                completed = completed,
                isActive = entry.index == activeIndex,
                onClick = { if (!completed) onPick(entry.index) },
            )
        }
    }
}

@Composable
private fun PaletteSwatch(
    entry: IceorsAsset.PaletteEntry,
    ratio: Float,
    done: Int,
    total: Int,
    completed: Boolean,
    isActive: Boolean,
    onClick: () -> Unit,
) {
    val swatchColor = Color(entry.color)
    // Pick contrasting label color from the palette color luminance.
    val labelColor = if (swatchColor.luminance() < 0.55f) Color.White else Color(0xFF333333)
    val ringTrack = Color(0x33000000)
    val ringDone = if (completed) Color(0xFF2E7D32) else Color(0xFF1976D2)

    Column(
        modifier = Modifier.size(56.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Box(
            modifier = Modifier.size(48.dp).clickable(enabled = !completed, onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            // Progress ring drawn under the swatch.
            Canvas(modifier = Modifier.fillMaxSize()) {
                val stroke = 4.dp.toPx()
                val inset = stroke / 2f
                val arcSize = Size(size.width - stroke, size.height - stroke)
                val topLeft = Offset(inset, inset)
                drawArc(
                    color = ringTrack,
                    startAngle = -90f,
                    sweepAngle = 360f,
                    useCenter = false,
                    topLeft = topLeft,
                    size = arcSize,
                    style = Stroke(width = stroke),
                )
                if (ratio > 0f) {
                    drawArc(
                        color = ringDone,
                        startAngle = -90f,
                        sweepAngle = 360f * ratio.coerceIn(0f, 1f),
                        useCenter = false,
                        topLeft = topLeft,
                        size = arcSize,
                        style = Stroke(width = stroke),
                    )
                }
            }

            // Inner color disc (slightly smaller so the ring is visible).
            Box(
                modifier = Modifier
                    .size(38.dp)
                    .clip(CircleShape)
                    .background(if (completed) swatchColor.copy(alpha = 0.45f) else swatchColor),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = if (completed) "✓" else entry.index.toString(),
                    color = labelColor,
                    fontWeight = if (isActive) FontWeight.Bold else FontWeight.Medium,
                    fontSize = if (entry.index >= 100) 11.sp else 14.sp,
                )
            }

            // Active outline drawn on top so it's visible regardless of color.
            if (isActive && !completed) {
                Canvas(modifier = Modifier.fillMaxSize()) {
                    val stroke = 2.dp.toPx()
                    val arcSize = Size(size.width - stroke, size.height - stroke)
                    val topLeft = Offset(stroke / 2f, stroke / 2f)
                    drawArc(
                        color = Color.Black,
                        startAngle = 0f,
                        sweepAngle = 360f,
                        useCenter = false,
                        topLeft = topLeft,
                        size = arcSize,
                        style = Stroke(width = stroke),
                    )
                }
            }
        }
        if (total > 0) {
            Text(
                text = if (completed) "" else "$done/$total",
                fontSize = 9.sp,
                color = Color.Gray,
            )
        }
    }
}
