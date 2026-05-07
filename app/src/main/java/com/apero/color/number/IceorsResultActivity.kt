package com.apero.color.number

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.apero.color.number.coloring.ResultHolder
import com.apero.color.number.iceors.IceorsView
import com.apero.color.number.ui.theme.ColorByNumberTheme
import kotlinx.coroutines.delay

class IceorsResultActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ColorByNumberTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    IceorsResultScreen(padding)
                }
            }
        }
    }
}

@Composable
private fun IceorsResultScreen(padding: PaddingValues) {
    val context = LocalContext.current
    val asset = ResultHolder.iceorsAsset
    var isReplaying by remember { mutableStateOf(false) }
    var isDone by remember { mutableStateOf(false) }
    var view by remember { mutableStateOf<IceorsView?>(null) }

    LaunchedEffect(Unit) {
        if (asset == null) return@LaunchedEffect
        
        // Initial delay to show the "finished image" as requested
        delay(1500)
        
        isReplaying = true
        view?.startReplay(5000L) {
            isReplaying = false
            isDone = true
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(padding)
            .background(Color.White),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
            contentAlignment = Alignment.Center,
        ) {
            if (asset != null) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { ctx ->
                        IceorsView(ctx).also { v ->
                            view = v
                            v.setAsset(asset)
                            v.setRevealBitmap(ResultHolder.revealBitmap, revealDecorations = ResultHolder.isOil)
                            v.isInteractionEnabled = false
                            // Ensure it starts as "all completed" to show the final image initially
                            asset.fillables.forEach { it.completed = true }
                        }
                    }
                )
            } else {
                Text("No result data")
            }
            
            if (isReplaying) {
                Text(
                    text = "Replaying...",
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 16.dp),
                    color = Color.Gray
                )
            }
        }

        Button(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            enabled = !isReplaying,
            onClick = {
                ResultHolder.iceorsAsset = null
                (context as? android.app.Activity)?.finish()
            },
        ) {
            Text(if (isDone) "Finish" else "Back")
        }
    }
}
