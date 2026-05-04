package com.apero.color.number

import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.apero.color.number.iceors.network.IceorsCatalog
import com.apero.color.number.iceors.network.IceorsDownloader
import com.apero.color.number.iceors.network.IceorsRepository
import com.apero.color.number.ui.theme.ColorByNumberTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Browses the live Iceors catalog and downloads a single picture before
 * handing off to [CdnDrawActivity] to draw it.
 *
 * Also supports importing pictures from local ZIP files via the "Import ZIP"
 * button in the top bar.
 *
 * Catalog source preference:
 *   1. `assets/cc` if the user bundled an offline snapshot
 *   2. live API at https://coloring.galaxyaura.com/coloringbook
 */
class CdnGalleryActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ColorByNumberTheme {
                GalleryRoot(onBack = { finish() })
            }
        }
    }
}

private sealed interface CatalogState {
    data object Loading : CatalogState
    data class Loaded(val catalog: IceorsCatalog) : CatalogState
    data class Failed(val message: String) : CatalogState
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun GalleryRoot(onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repo = remember { IceorsRepository(context) }
    var state by remember { mutableStateOf<CatalogState>(CatalogState.Loading) }
    var selectedCollection by remember { mutableStateOf<IceorsCatalog.Collection?>(null) }
    var importing by remember { mutableStateOf(false) }
    /** Bumped after each import so cached-key lists recompose. */
    var cacheGeneration by remember { mutableIntStateOf(0) }

    // --- ZIP file picker ---------------------------------------------------
    val zipPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        importing = true
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    context.contentResolver.openInputStream(uri)!!.use { stream ->
                        repo.importFromZip(stream)
                    }
                }
            }
            importing = false
            result.onSuccess { keys ->
                cacheGeneration++
                if (keys.isEmpty()) {
                    Toast.makeText(context, "No valid pictures found in ZIP", Toast.LENGTH_SHORT).show()
                } else if (keys.size == 1) {
                    Toast.makeText(context, "Imported: ${keys.first()}", Toast.LENGTH_SHORT).show()
                    context.startActivity(
                        CdnDrawActivity.intent(context, keys.first(), "Imported")
                    )
                } else {
                    Toast.makeText(context, "Imported ${keys.size} pictures", Toast.LENGTH_SHORT).show()
                }
            }.onFailure { err ->
                Toast.makeText(context, "Import failed: ${err.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    LaunchedEffect(Unit) {
        state = withContext(Dispatchers.IO) {
            runCatching {
                runCatching { repo.loadCatalogFromAssets("cc") }.getOrNull()
                    ?: repo.loadCatalogLive()
            }.fold(
                onSuccess = { CatalogState.Loaded(it) },
                onFailure = { CatalogState.Failed(it.message ?: "fetch failed") },
            )
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = {
                    Text(selectedCollection?.displayName ?: "CDN catalog")
                },
                navigationIcon = {
                    Text(
                        "←",
                        modifier = Modifier
                            .padding(12.dp)
                            .clickable {
                                if (selectedCollection != null) selectedCollection = null else onBack()
                            },
                    )
                },
                actions = {
                    if (selectedCollection == null) {
                        TextButton(
                            onClick = {
                                zipPicker.launch(arrayOf(
                                    "application/zip",
                                    "application/x-zip-compressed",
                                    "application/octet-stream",
                                ))
                            },
                            enabled = !importing,
                        ) {
                            Text(if (importing) "Importing…" else "📦 Import ZIP")
                        }
                    }
                },
            )
        },
    ) { padding ->
        if (importing) {
            Centered(padding) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Text("Extracting ZIP…", modifier = Modifier.padding(top = 12.dp))
                }
            }
            return@Scaffold
        }

        when (val s = state) {
            CatalogState.Loading -> Centered(padding) { CircularProgressIndicator() }
            is CatalogState.Failed -> Centered(padding) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Catalog error: ${s.message}")
                    // Even when catalog fails, user can still import from ZIP or
                    // browse previously cached pictures.
                    CachedPicturesList(
                        repo = repo,
                        cacheGeneration = cacheGeneration,
                        modifier = Modifier.padding(top = 16.dp),
                    )
                }
            }
            is CatalogState.Loaded -> {
                val coll = selectedCollection
                if (coll == null) {
                    CollectionList(
                        padding = padding,
                        catalog = s.catalog,
                        repo = repo,
                        cacheGeneration = cacheGeneration,
                        onPick = { selectedCollection = it },
                    )
                } else {
                    PictureList(
                        padding = padding,
                        repo = repo,
                        collection = coll,
                    )
                }
            }
        }
    }
}

@Composable
private fun CollectionList(
    padding: PaddingValues,
    catalog: IceorsCatalog,
    repo: IceorsRepository,
    cacheGeneration: Int,
    onPick: (IceorsCatalog.Collection) -> Unit,
) {
    var query by remember { mutableStateOf("") }
    val filtered = remember(query, catalog) {
        if (query.isBlank()) catalog.collections
        else {
            val q = query.trim().lowercase()
            catalog.collections.filter {
                it.displayName.lowercase().contains(q) || it.name.lowercase().contains(q)
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(padding)) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            singleLine = true,
            placeholder = { Text("Search collections…") },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
        )
        Text(
            "Catalog v${catalog.version} • ${filtered.size} / ${catalog.collections.size}",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            color = Color.Gray,
        )
        HorizontalDivider()
        if (filtered.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center,
            ) { Text("No matches", color = Color.Gray) }
        } else {
            LazyColumn(modifier = Modifier.fillMaxSize()) {
                // --- Cached / imported pictures section ----------------------
                item(key = "__cached_header") {
                    CachedPicturesList(
                        repo = repo,
                        cacheGeneration = cacheGeneration,
                    )
                }

                // --- Catalog collections ------------------------------------
                items(filtered) { coll ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onPick(coll) }
                            .padding(horizontal = 16.dp, vertical = 14.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(coll.displayName, fontWeight = FontWeight.Medium)
                        Text("${coll.pics.size} pics", color = Color.Gray)
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}

/**
 * Compact section listing all locally-cached pictures (from downloads or ZIP imports).
 * Shows nothing when the cache is empty to avoid visual noise.
 */
@Composable
private fun CachedPicturesList(
    repo: IceorsRepository,
    cacheGeneration: Int,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val cachedKeys = remember(cacheGeneration) { repo.listCachedKeys() }

    if (cachedKeys.isEmpty()) return

    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFFFFF3E0))
                .padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "📁 Local cache (${cachedKeys.size})",
                fontWeight = FontWeight.SemiBold,
                color = Color(0xFFE65100),
            )
            Text("Tap to open", color = Color(0xFFBF360C))
        }
        for (key in cachedKeys) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable {
                        context.startActivity(
                            CdnDrawActivity.intent(context, key, "Local")
                        )
                    }
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(key, fontWeight = FontWeight.Medium)
                Text("Cached ✓", color = Color(0xFF2E7D32))
            }
            HorizontalDivider()
        }
        HorizontalDivider(thickness = 2.dp, color = Color(0xFFFFCC80))
    }
}

@Composable
private fun PictureList(
    padding: PaddingValues,
    repo: IceorsRepository,
    collection: IceorsCatalog.Collection,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val downloadingKey = remember { mutableStateOf<String?>(null) }
    val statusByKey = remember { mutableStateOf<Map<String, String>>(emptyMap()) }

    fun setStatus(key: String, msg: String) {
        statusByKey.value = statusByKey.value.toMutableMap().apply { put(key, msg) }
    }

    Column(modifier = Modifier.fillMaxSize().padding(padding)) {
        Text(
            "${collection.pics.size} pictures",
            modifier = Modifier.padding(16.dp),
        )
        HorizontalDivider()
        LazyColumn(modifier = Modifier.fillMaxSize()) {
            items(collection.pics) { pic ->
                val isDownloading = downloadingKey.value == pic.key
                val cached = repo.cache.isPictureReady(pic.key)
                val status = statusByKey.value[pic.key]
                    ?: if (cached) "Cached" else "Tap to download"

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(enabled = !isDownloading) {
                            if (cached) {
                                context.startActivity(
                                    CdnDrawActivity.intent(context, pic.key, collection.displayName)
                                )
                                return@clickable
                            }
                            downloadingKey.value = pic.key
                            setStatus(pic.key, "Downloading…")
                            scope.launch {
                                val outcome = withContext(Dispatchers.IO) {
                                    repo.ensurePicture(pic.key)
                                }
                                downloadingKey.value = null
                                when (outcome) {
                                    is IceorsDownloader.Outcome.Ok,
                                    is IceorsDownloader.Outcome.Skip -> {
                                        setStatus(pic.key, "Ready")
                                        context.startActivity(
                                            CdnDrawActivity.intent(context, pic.key, collection.displayName)
                                        )
                                    }
                                    is IceorsDownloader.Outcome.Miss ->
                                        setStatus(pic.key, "Not on CDN (403/404)")
                                    is IceorsDownloader.Outcome.Err ->
                                        setStatus(pic.key, "Error ${outcome.code}: ${outcome.message}")
                                }
                            }
                        }
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(pic.key, fontWeight = FontWeight.Medium)
                        Text(
                            "${pic.type} • picGameType=${pic.picGameType}",
                            color = Color.Gray,
                        )
                    }
                    Text(status, color = if (cached) Color(0xFF2E7D32) else Color.Gray)
                }
                if (isDownloading) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun Centered(padding: PaddingValues, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier.fillMaxSize().padding(padding).background(Color.White),
        contentAlignment = Alignment.Center,
    ) { content() }
}

@Suppress("unused")
@Composable
private fun Spacer16() {
    Box(modifier = Modifier.height(16.dp))
}
