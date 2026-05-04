package com.apero.color.number

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.apero.color.number.coloring.ResultHolder
import com.apero.color.number.ui.theme.ColorByNumberTheme

class ResultActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ColorByNumberTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { padding ->
                    ResultScreen(padding)
                }
            }
        }
    }
}

@Composable
private fun ResultScreen(padding: PaddingValues) {
    val context = LocalContext.current
    val bitmap = ResultHolder.bitmap

    Column(
        modifier = Modifier.fillMaxSize().padding(padding).background(Color.White),
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().weight(1f),
            contentAlignment = Alignment.Center,
        ) {
            if (bitmap != null) {
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = "Result",
                    modifier = Modifier.fillMaxSize().padding(16.dp),
                    contentScale = ContentScale.Fit,
                )
            } else {
                Text("No result")
            }
        }
        Button(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            onClick = {
                ResultHolder.bitmap = null
                (context as? android.app.Activity)?.finish()
            },
        ) {
            Text("Back")
        }
    }
}
