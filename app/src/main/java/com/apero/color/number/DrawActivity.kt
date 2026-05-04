package com.apero.color.number

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
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
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
import com.apero.color.number.coloring.ColoringView
import com.apero.color.number.coloring.ResultHolder
import com.apero.color.number.model.Level
import com.apero.color.number.ui.theme.ColorByNumberTheme

class DrawActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ColorByNumberTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    DrawScreen(padding)
                }
            }
        }
    }
}

@Composable
private fun DrawScreen(padding: PaddingValues) {
    val context = LocalContext.current
    val assets = context.assets

    var board by remember { mutableStateOf<Bitmap?>(null) }
    var stock by remember { mutableStateOf<Bitmap?>(null) }
    var levels by remember { mutableStateOf<List<Level>>(emptyList()) }
    var activeLevel by remember { mutableStateOf<Level?>(null) }
    var view by remember { mutableStateOf<ColoringView?>(null) }
    var refreshTick by remember { mutableStateOf(0) }

    LaunchedEffect(Unit) {
        board = BitmapFactory.decodeStream(assets.open("sample/fill.png"))
            .copy(Bitmap.Config.ARGB_8888, true)
        stock = BitmapFactory.decodeStream(assets.open("sample/stock.png"))
            .copy(Bitmap.Config.ARGB_8888, true)
        val json = assets.open("sample/level.json").bufferedReader().use { it.readText() }
        levels = Level.parseAll(json)
        activeLevel = levels.firstOrNull()
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(padding),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().weight(1f).background(Color.White),
        ) {
            val b = board
            val s = stock
            if (b != null && s != null && levels.isNotEmpty()) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { ctx ->
                        ColoringView(ctx).also { v ->
                            view = v
                            v.setData(b, s, levels)
                            activeLevel?.let(v::selectLevel)
                            v.onRegionFilled = { refreshTick++ }
                        }
                    },
                    update = { v ->
                        activeLevel?.let(v::selectLevel)
                    },
                )
            }
        }

        Palette(
            levels = levels,
            active = activeLevel,
            tick = refreshTick,
            onPick = { activeLevel = it },
        )

        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Button(
                modifier = Modifier.weight(1f),
                onClick = {
                    ResultHolder.bitmap = view?.snapshot()
                    context.startActivity(Intent(context, ResultActivity::class.java))
                },
            ) { Text("Done") }
        }
    }
}

@Composable
private fun Palette(
    levels: List<Level>,
    active: Level?,
    tick: Int,
    onPick: (Level) -> Unit,
) {
    @Suppress("UNUSED_EXPRESSION") tick // re-trigger render after fill
    LazyRow(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(levels) { level ->
            val isActive = level == active
            val done = level.isCompleted
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(Color(level.color))
                    .border(
                        width = if (isActive) 3.dp else 1.dp,
                        color = if (isActive) Color.Black else Color.Gray,
                        shape = CircleShape,
                    )
                    .clickable(enabled = !done) { onPick(level) },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = if (done) "✓" else level.level.toString(),
                    color = Color(level.textColor),
                )
            }
        }
    }
}
