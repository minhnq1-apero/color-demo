package com.apero.color.number

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.apero.color.number.coloring.ResultHolder
import com.apero.color.number.iceors.BitmapExporter
import com.apero.color.number.iceors.IceorsAsset
import com.apero.color.number.iceors.IceorsPalette
import com.apero.color.number.iceors.IceorsView
import com.apero.color.number.iceors.network.IceorsRepository
import com.apero.color.number.ui.theme.ColorByNumberTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Draws a CDN-downloaded picture using its extracted `<key>b` path-data file.
 * Companion to [IceorsDrawActivity], which loads from APK assets instead.
 *
 * Expects the picture to already be cached locally — caller should run
 * [IceorsRepository.ensurePicture] before launching.
 */
class CdnDrawActivity : ComponentActivity() {

    companion object {
        private const val EXTRA_KEY = "pic_key"
        private const val EXTRA_TITLE = "pic_title"

        fun intent(context: Context, key: String, title: String? = null): Intent =
            Intent(context, CdnDrawActivity::class.java)
                .putExtra(EXTRA_KEY, key)
                .putExtra(EXTRA_TITLE, title)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val key = intent.getStringExtra(EXTRA_KEY)
        val title = intent.getStringExtra(EXTRA_TITLE) ?: key.orEmpty()
        if (key.isNullOrBlank()) {
            finish()
            return
        }
        setContent {
            ColorByNumberTheme {
                CdnDrawScreen(picKey = key, title = title, onBack = { finish() })
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CdnDrawScreen(picKey: String, title: String, onBack: () -> Unit) {
    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(title) },
                navigationIcon = {
                    Text(
                        "←",
                        modifier = Modifier
                            .padding(12.dp)
                            .clickable { onBack() },
                    )
                },
            )
        },
    ) { padding ->
        CdnDrawBody(padding, picKey)
    }
}

@Composable
private fun CdnDrawBody(padding: PaddingValues, picKey: String) {
    val context = LocalContext.current
    var loaded by remember { mutableStateOf<IceorsAsset.Loaded?>(null) }
    var revealBitmap by remember { mutableStateOf<Bitmap?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var activeIndex by remember { mutableIntStateOf(-1) }
    var done by remember { mutableIntStateOf(0) }
    var total by remember { mutableIntStateOf(0) }
    var paletteProgress by remember { mutableStateOf<Map<Int, IntArray>>(emptyMap()) }
    var view by remember { mutableStateOf<IceorsView?>(null) }
    var hintsUsed by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(picKey) {
        val repo = IceorsRepository(context)
        runCatching {
            withContext(Dispatchers.IO) {
                val asset = repo.loadCachedAsset(picKey)
                // `<key>c` only ships in SP/SPV/SSPV zips. For oil pics it
                // holds the textured "finished" image revealed by coloring;
                // for plain SPV it's just a flat-colored render. V pics ship
                // no c file, in which case bitmap stays null and the view
                // falls back to solid palette fill.
                val finishedFile = repo.cache.finishedImageFile(picKey)
                val bitmap = if (finishedFile.exists() && finishedFile.length() > 0) {
                    BitmapFactory.decodeFile(finishedFile.absolutePath)
                } else null
                asset to bitmap
            }
        }.onSuccess { (l, bm) ->
            loaded = l
            revealBitmap = bm
            total = l.regions.size
            activeIndex = l.palette.firstOrNull()?.index ?: -1
        }.onFailure { error = it.message ?: "load failed" }
    }

    LaunchedEffect(done, total) {
        if (total > 0 && done >= total) {
            delay(800)
            ResultHolder.iceorsAsset = loaded
            ResultHolder.revealBitmap = revealBitmap
            ResultHolder.isOil = picKey.contains("oil")
            context.startActivity(Intent(context, IceorsResultActivity::class.java))
            (context as? Activity)?.finish()
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(padding)) {
        when {
            error != null -> {
                Box(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    contentAlignment = Alignment.Center,
                ) { Text("Load error: $error") }
            }

            loaded == null -> {
                Box(
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    contentAlignment = Alignment.Center,
                ) { Text("Loading regions…") }
            }

            else -> {
                Box(
                    modifier = Modifier.fillMaxWidth().weight(1f).background(Color.White),
                ) {
                    // Mirrors the original app's `key.contains("oil")` test
                    // (`C1.u#k0:783`): oil pics route the reveal bitmap onto
                    // stroke / black-fill paints too, so line decorations
                    // render textured ("transparent") instead of solid black.
                    val isOil = picKey.contains("oil")
                    AndroidView(
                        modifier = Modifier.fillMaxSize(),
                        factory = { ctx ->
                            IceorsView(ctx).also { v ->
                                view = v
                                v.setAsset(loaded!!)
                                v.setRevealBitmap(revealBitmap, revealDecorations = isOil)
                                v.selectPaletteIndex(activeIndex)
                                v.onProgressChanged = { d, t -> done = d; total = t }
                                v.onPaletteProgressChanged = { paletteProgress = it }
                            }
                        },
                        update = { v ->
                            v.setRevealBitmap(revealBitmap, revealDecorations = isOil)
                            v.selectPaletteIndex(activeIndex)
                        },
                    )
                    // Floating action buttons — top-right of the canvas.
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
                                        val name = "iceors_${picKey}_${System.currentTimeMillis()}.png"
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
                Text("CDN-downloaded")
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
