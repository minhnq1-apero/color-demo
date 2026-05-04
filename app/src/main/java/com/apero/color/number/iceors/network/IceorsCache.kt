package com.apero.color.number.iceors.network

import android.content.Context
import java.io.File

/**
 * On-disk layout for downloaded Iceors assets.
 *
 * Mirrors the original app's `getExternalFilesDir("data")/<key>/` structure so
 * loaders that ported the parsing logic 1:1 can use the same paths. We point
 * at the app-private files dir instead of external storage to avoid scoped
 * storage permission noise — the contents are not user-visible.
 *
 * Per-picture layout:
 * ```
 * <root>/<key>/
 *     <key>          — 256x256 grayscale lineart PNG
 *     <key>_mid      — 512x512 mid-resolution preview PNG
 *     <key>b         — pipe-delimited region/path data (extracted from _b.zip)
 *     <key>c         — 2048x2048 finished JPEG (extracted from _b.zip)
 *     sp_new_paint_flag
 * ```
 */
class IceorsCache(context: Context) {
    val root: File = File(context.filesDir, "iceors").apply { mkdirs() }

    fun pictureDir(key: String): File = File(root, key).apply { mkdirs() }
    fun lineartFile(key: String): File = File(pictureDir(key), key)
    fun midPreviewFile(key: String): File = File(pictureDir(key), "${key}_mid")
    fun pathDataFile(key: String): File = File(pictureDir(key), "${key}b")
    fun finishedImageFile(key: String): File = File(pictureDir(key), "${key}c")
    fun paintFlagFile(key: String): File = File(pictureDir(key), "sp_new_paint_flag")

    fun coverFile(collectionName: String): File =
        File(root, "_collection_covers/${safe(collectionName)}.jpg").apply { parentFile?.mkdirs() }

    fun cornerBgFile(collectionName: String): File =
        File(root, "_collection_covers/${safe(collectionName)}_corner_bg.jpg").apply { parentFile?.mkdirs() }

    /** True iff a picture's gameplay data is fully present locally. */
    fun isPictureReady(key: String): Boolean =
        pathDataFile(key).existsAndNonEmpty() &&
            finishedImageFile(key).existsAndNonEmpty() &&
            paintFlagFile(key).existsAndNonEmpty()

    fun clear(key: String) {
        pictureDir(key).deleteRecursively()
    }

    private fun safe(name: String): String = name.replace(' ', '_').replace('/', '_')

    private fun File.existsAndNonEmpty() = exists() && length() > 0
}
