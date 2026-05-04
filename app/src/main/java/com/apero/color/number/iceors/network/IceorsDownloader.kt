package com.apero.color.number.iceors.network

import java.io.File
import java.io.InputStream
import java.util.zip.ZipInputStream

/**
 * Downloads collection covers and per-picture assets from the doodle-mobile
 * CDN, mirroring `crawl/crawl.py`. Pure JVM — call from a background
 * dispatcher.
 *
 * Resume-safe: if the expected output already exists with non-zero size, the
 * fetch is skipped. The `_b.zip` is skipped once `<key>b` is on disk — that's
 * the only entry guaranteed to ship in every variant (SPV zips also ship
 * `<key>c` and `sp_new_paint_flag`; V zips ship just the path data).
 */
class IceorsDownloader(private val cache: IceorsCache) {

    sealed interface Outcome {
        data object Ok : Outcome
        data object Skip : Outcome
        data object Miss : Outcome
        data class Err(val code: Int, val message: String) : Outcome
    }

    data class Progress(val done: Int, val total: Int, val key: String, val outcome: Outcome)

    /** Download the small lineart PNG (`pictures/<key>/<key>`). */
    fun downloadLineart(key: String): Outcome =
        downloadToFile(IceorsCdn.pictureLineart(key), cache.lineartFile(key))

    /** Download the 512×512 mid-preview (`pictures/<key>/<key>_mid`). */
    fun downloadMidPreview(key: String): Outcome =
        downloadToFile(IceorsCdn.pictureMidPreview(key), cache.midPreviewFile(key))

    /**
     * Fetch and unpack the gameplay zip (`zips/<key>_b.zip`) into the picture
     * directory. The zip is deleted after extraction unless [keepZip] is true.
     */
    fun downloadGameZip(key: String, keepZip: Boolean = false): Outcome {
        if (cache.isPictureReady(key)) return Outcome.Skip

        val zipFile = File(cache.pictureDir(key), "${key}_b.zip")
        val downloadOutcome = downloadToFile(IceorsCdn.pictureGameZip(key), zipFile)
        if (downloadOutcome is Outcome.Err || downloadOutcome is Outcome.Miss) return downloadOutcome

        try {
            extractZip(zipFile, cache.pictureDir(key))
        } catch (e: Exception) {
            return Outcome.Err(0, "extract failed: ${e.message}")
        } finally {
            if (!keepZip) zipFile.delete()
        }
        return Outcome.Ok
    }

    /**
     * One-shot per-picture fetch: lineart preview + mid preview + gameplay zip.
     * Returns the worst outcome (Err > Miss > Ok > Skip).
     */
    fun downloadPicture(key: String, keepZip: Boolean = false): Outcome {
        val outcomes = listOf(
            downloadLineart(key),
            downloadMidPreview(key),
            downloadGameZip(key, keepZip),
        )
        return summarize(outcomes)
    }

    fun downloadCollectionCovers(collectionName: String): Outcome {
        val cover = downloadToFile(IceorsCdn.collectionCover(collectionName), cache.coverFile(collectionName))
        val corner = downloadToFile(IceorsCdn.collectionCornerBg(collectionName), cache.cornerBgFile(collectionName))
        return summarize(listOf(cover, corner))
    }

    /**
     * Download an entire collection with optional progress callbacks. Runs the
     * pictures sequentially — wrap in a coroutine and dispatch parallel calls
     * across keys if you want concurrency.
     */
    fun downloadCollection(
        collection: IceorsCatalog.Collection,
        keepZip: Boolean = false,
        onProgress: (Progress) -> Unit = {},
    ) {
        downloadCollectionCovers(collection.name)
        val total = collection.pics.size
        collection.pics.forEachIndexed { index, pic ->
            val outcome = downloadPicture(pic.key, keepZip)
            onProgress(Progress(done = index + 1, total = total, key = pic.key, outcome = outcome))
        }
    }

    private fun downloadToFile(url: String, dest: File): Outcome {
        if (dest.exists() && dest.length() > 0) return Outcome.Skip

        dest.parentFile?.mkdirs()
        @Suppress("DEPRECATION") // Thread.id is deprecated in JDK 19, but threadId() needs API 35+
        val tid = Thread.currentThread().id
        val tmp = File(dest.parentFile, "${dest.name}.part.${android.os.Process.myPid()}.$tid")

        val result = IceorsHttp.get(url) { input, _ ->
            tmp.outputStream().use { out -> input.copyTo(out) }
        }
        return when (result) {
            is IceorsHttp.Result.Ok -> {
                if (tmp.length() == 0L) {
                    tmp.delete(); Outcome.Err(204, "empty body")
                } else {
                    if (!tmp.renameTo(dest)) {
                        tmp.copyTo(dest, overwrite = true); tmp.delete()
                    }
                    Outcome.Ok
                }
            }

            is IceorsHttp.Result.NotFound -> {
                tmp.delete(); Outcome.Miss
            }

            is IceorsHttp.Result.Err -> {
                tmp.delete(); Outcome.Err(result.code, result.message)
            }
        }
    }

    private fun extractZip(zipFile: File, target: File) {
        target.mkdirs()
        zipFile.inputStream().use { fis ->
            ZipInputStream(fis).use { zis ->
                while (true) {
                    val entry = zis.nextEntry ?: break
                    if (entry.isDirectory) continue
                    val out = File(target, entry.name)
                    if (!out.canonicalPath.startsWith(target.canonicalPath)) continue // zip-slip guard
                    out.parentFile?.mkdirs()
                    out.outputStream().use { dst -> (zis as InputStream).copyTo(dst) }
                }
            }
        }
    }

    private fun summarize(outcomes: List<Outcome>): Outcome {
        outcomes.firstOrNull { it is Outcome.Err }?.let { return it }
        if (outcomes.any { it is Outcome.Miss }) return Outcome.Miss
        if (outcomes.any { it is Outcome.Ok }) return Outcome.Ok
        return Outcome.Skip
    }
}
