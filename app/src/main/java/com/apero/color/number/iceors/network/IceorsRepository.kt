package com.apero.color.number.iceors.network

import android.content.Context
import com.apero.color.number.iceors.IceorsAsset
import java.io.File
import java.io.InputStream
import java.util.zip.ZipInputStream

/**
 * High-level facade around catalog + downloader + on-disk asset loader.
 *
 * Typical usage from a coroutine on Dispatchers.IO:
 * ```
 * val repo = IceorsRepository(context)
 * val catalog = repo.loadCatalogLive()                 // or loadCatalogFromAssets("cc")
 * val collection = catalog.collections.first()
 * repo.ensurePicture(collection.pics.first().key)      // downloads + extracts
 * val loaded = repo.loadCachedAsset(collection.pics.first().key)
 * ```
 *
 * ZIP import (offline):
 * ```
 * val keys = repo.importFromZip(contentResolver.openInputStream(uri)!!)
 * val loaded = repo.loadCachedAsset(keys.first())
 * ```
 */
class IceorsRepository(context: Context) {

    val cache = IceorsCache(context)
    val downloader = IceorsDownloader(cache)
    private val appContext = context.applicationContext

    fun loadCatalogLive(): IceorsCatalog = IceorsCatalogClient.fetch()

    /** Read a catalog snapshot bundled in `assets/<assetPath>` (e.g. `"cc"`). */
    fun loadCatalogFromAssets(assetPath: String): IceorsCatalog {
        val text = appContext.assets.open(assetPath).bufferedReader().use { it.readText() }
        return IceorsCatalogClient.parse(text)
    }

    /**
     * Make sure all gameplay files for [key] exist locally. Returns the final
     * downloader outcome — `Skip` if the picture was already cached.
     */
    fun ensurePicture(key: String, keepZip: Boolean = false): IceorsDownloader.Outcome =
        downloader.downloadPicture(key, keepZip)

    /** Resolve the on-disk path data file produced by extraction. */
    fun pathDataFile(key: String): File = cache.pathDataFile(key)

    /**
     * Load a previously-downloaded picture into [IceorsAsset.Loaded]. Throws
     * [IllegalStateException] if [ensurePicture] hasn't been called yet.
     */
    fun loadCachedAsset(key: String, canvasSize: Float = 2048f): IceorsAsset.Loaded {
        val file = cache.pathDataFile(key)
        check(file.exists() && file.length() > 0) { "picture $key not downloaded yet" }
        return IceorsAsset.loadFromFile(file, canvasSize)
    }

    /**
     * Import one or more pictures from a local ZIP file (e.g. a `<key>_b.zip`
     * exported from the crawler or shared offline).
     *
     * The ZIP is expected to contain flat entries like:
     * ```
     * <key>b              — pipe-delimited path data
     * <key>c              — 2048×2048 finished JPEG
     * sp_new_paint_flag   — marker flag
     * ```
     *
     * If the zip entries sit inside a subdirectory (e.g. `<key>/<key>b`), the
     * leading directory component is used as the key automatically.
     *
     * Returns the list of picture keys that were successfully imported. Caller
     * should run on `Dispatchers.IO`.
     */
    fun importFromZip(inputStream: InputStream): List<String> {
        // 1. Extract everything into a temp dir first so we can discover the key(s).
        val tmpDir = File(cache.root, "_import_tmp_${System.currentTimeMillis()}")
        tmpDir.mkdirs()
        try {
            ZipInputStream(inputStream).use { zis ->
                while (true) {
                    val entry = zis.nextEntry ?: break
                    if (entry.isDirectory) continue
                    val name = entry.name
                    val dest = File(tmpDir, name)
                    // zip-slip guard
                    if (!dest.canonicalPath.startsWith(tmpDir.canonicalPath)) continue
                    dest.parentFile?.mkdirs()
                    dest.outputStream().use { out -> (zis as InputStream).copyTo(out) }
                }
            }

            // 2. Discover picture keys: look for files ending with "b" that
            //    contain pipe-delimited path data (the <key>b file).
            val importedKeys = mutableListOf<String>()
            val allFiles = tmpDir.walkTopDown().filter { it.isFile }.toList()

            // Group by parent directory (handles both flat and nested layouts).
            val groups = allFiles.groupBy { it.parentFile!! }

            for ((dir, files) in groups) {
                // Find the path-data file: name ends with "b" and is NOT "sp_new_paint_flag".
                val pathDataFile = files.firstOrNull {
                    it.name.endsWith("b") && it.name != "sp_new_paint_flag"
                } ?: continue

                val key = pathDataFile.name.removeSuffix("b")
                if (key.isBlank()) continue

                // Move all files for this key into the cache directory.
                val pictureDir = cache.pictureDir(key)
                for (f in files) {
                    val target = File(pictureDir, f.name)
                    f.copyTo(target, overwrite = true)
                }

                // Ensure the paint flag exists (some zips omit it).
                val flagFile = cache.paintFlagFile(key)
                if (!flagFile.exists()) flagFile.writeText("1")

                importedKeys += key
            }

            return importedKeys
        } finally {
            tmpDir.deleteRecursively()
        }
    }

    /** List all picture keys that are fully cached locally. */
    fun listCachedKeys(): List<String> {
        return cache.root.listFiles()
            ?.filter { it.isDirectory && !it.name.startsWith("_") }
            ?.filter { cache.isPictureReady(it.name) }
            ?.map { it.name }
            ?.sorted()
            .orEmpty()
    }

    /**
     * List `*.zip` filenames bundled at `assets/[folder]/`. Used to surface
     * pre-shipped sample pictures (e.g. CDN downloads we couldn't fetch from
     * the device) for one-tap import via [importFromAsset].
     */
    fun listBundledZips(folder: String = "iceors_samples"): List<String> =
        appContext.assets.list(folder)
            ?.filter { it.endsWith("_b.zip") }
            ?.sorted()
            .orEmpty()

    /**
     * Import a single `*_b.zip` from `assets/[folder]/[filename]` into the
     * cache. Returns the imported keys (typically one). Skips work if the
     * picture is already cached. Caller should run on `Dispatchers.IO`.
     */
    fun importFromAsset(filename: String, folder: String = "iceors_samples"): List<String> {
        val expectedKey = filename.removeSuffix("_b.zip")
        if (expectedKey.isNotBlank() && cache.isPictureReady(expectedKey)) {
            return listOf(expectedKey)
        }
        return appContext.assets.open("$folder/$filename").use { importFromZip(it) }
    }
}
