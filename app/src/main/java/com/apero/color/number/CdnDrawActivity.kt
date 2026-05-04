package com.apero.color.number

import android.content.Context
import android.content.Intent
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
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.apero.color.number.iceors.IceorsAsset
import com.apero.color.number.iceors.IceorsPalette
import com.apero.color.number.iceors.IceorsView
import com.apero.color.number.iceors.network.IceorsRepository
import com.apero.color.number.ui.theme.ColorByNumberTheme
import kotlinx.coroutines.Dispatchers
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
    var error by remember { mutableStateOf<String?>(null) }
    var activeIndex by remember { mutableIntStateOf(-1) }
    var done by remember { mutableIntStateOf(0) }
    var total by remember { mutableIntStateOf(0) }
    var paletteProgress by remember { mutableStateOf<Map<Int, IntArray>>(emptyMap()) }
    var view by remember { mutableStateOf<IceorsView?>(null) }
    var hintsUsed by remember { mutableIntStateOf(0) }

    LaunchedEffect(picKey) {
        runCatching {
            withContext(Dispatchers.IO) {
                IceorsRepository(context).loadCachedAsset(picKey)
            }
        }.onSuccess { l ->
            loaded = l
            total = l.regions.size
            activeIndex = l.palette.firstOrNull()?.index ?: -1
        }.onFailure { error = it.message ?: "load failed" }
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
                    // Hint floating button — top-right of the canvas, like the reference app.
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(12.dp)
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
