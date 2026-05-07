package com.apero.color.number

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.apero.color.number.iceors.BitmapExporter
import com.apero.color.number.iceors.IceorsAsset
import com.apero.color.number.iceors.IceorsPalette
import com.apero.color.number.iceors.IceorsView
import com.apero.color.number.ui.theme.ColorByNumberTheme
import android.widget.Toast
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.runtime.rememberCoroutineScope
import android.content.Intent
import android.app.Activity
import com.apero.color.number.coloring.ResultHolder
import kotlinx.coroutines.delay

class IceorsDrawActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ColorByNumberTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    IceorsScreen(padding)
                }
            }
        }
    }
}

@Composable
private fun IceorsScreen(padding: PaddingValues) {
    val context = LocalContext.current
    var loaded by remember { mutableStateOf<IceorsAsset.Loaded?>(null) }
    var activeIndex by remember { mutableIntStateOf(-1) }
    var done by remember { mutableIntStateOf(0) }
    var total by remember { mutableIntStateOf(0) }
    var paletteProgress by remember { mutableStateOf<Map<Int, IntArray>>(emptyMap()) }
    var view by remember { mutableStateOf<IceorsView?>(null) }
    var hintsUsed by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        val l = withContext(Dispatchers.Default) {
            IceorsAsset.load(context, "iceors/paths.txt", canvasSize = 2048f)
        }
        loaded = l
        total = l.regions.size
        activeIndex = l.palette.firstOrNull()?.index ?: -1
    }

    LaunchedEffect(done, total) {
        if (total > 0 && done >= total) {
            delay(800)

            ResultHolder.iceorsAsset = loaded
            ResultHolder.revealBitmap = null
            ResultHolder.isOil = false
            context.startActivity(Intent(context, IceorsResultActivity::class.java))
            // We finish DrawActivity so the user "progresses" to result.
            // They can go back to gallery from the result screen.
            (context as? Activity)?.finish()
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(padding),
    ) {
        if (loaded == null) {
            Box(
                modifier = Modifier.fillMaxWidth().weight(1f),
                contentAlignment = Alignment.Center,
            ) { Text("Loading regions…") }
        } else {
            Box(
                modifier = Modifier.fillMaxWidth().weight(1f).background(Color.White),
            ) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { ctx ->
                        IceorsView(ctx).also { v ->
                            view = v
                            v.setAsset(loaded!!)
                            v.selectPaletteIndex(activeIndex)
                            v.onProgressChanged = { d, t -> done = d; total = t }
                            v.onPaletteProgressChanged = { paletteProgress = it }
                        }
                    },
                    update = { v -> v.selectPaletteIndex(activeIndex) },
                )
                Column(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(Color(0xFFFFC107))
                            .clickable {
                                if (view?.requestHint() == true) hintsUsed++
                            }
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = "💡 Hint" + if (hintsUsed > 0) " ($hintsUsed)" else "",
                            color = Color.Black,
                        )
                    }
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(Color(0xFF4CAF50))
                            .clickable { view?.completeAll() }
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(text = "🎨 Fill all", color = Color.White)
                    }
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(Color(0xFF2196F3))
                            .clickable {
                                val v = view ?: return@clickable
                                scope.launch {
                                    val bm = withContext(Dispatchers.Default) { v.exportBitmap() }
                                    if (bm == null) {
                                        Toast.makeText(context, "Export failed (asset not loaded)",
                                            Toast.LENGTH_SHORT).show()
                                        return@launch
                                    }
                                    val name = "iceors_${System.currentTimeMillis()}.png"
                                    val path = withContext(Dispatchers.IO) {
                                        BitmapExporter.save(context, bm, name)
                                    }
                                    Toast.makeText(
                                        context,
                                        if (path != null) "Saved → Pictures/ColorByNumber/$name"
                                        else "Save failed",
                                        Toast.LENGTH_LONG,
                                    ).show()
                                }
                            }
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(text = "💾 Export", color = Color.White)
                    }
                }
            }
        }

        if (total > 0) {
            LinearProgressIndicator(
                progress = { done / total.toFloat() },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            )
            Row(
                modifier = Modifier.fillMaxWidth().padding(8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("$done / $total")
                Text("Iceors-style (SVG)")
            }
        }

        loaded?.let { l ->
            IceorsPalette(
                palette = l.palette,
                progress = paletteProgress,
                activeIndex = activeIndex,
                onPick = { activeIndex = it },
            )
        }
    }
}
