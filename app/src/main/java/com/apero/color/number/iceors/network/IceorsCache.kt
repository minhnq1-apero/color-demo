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
 * The `_b.zip` payload differs by picture format:
 *   - SP / SPV / SSPV pics (`picGameType` 4/5, e.g. `festivalSPV132612`):
 *     `<key>b`, `<key>c`, `sp_new_paint_flag`.
 *   - V pics — "ordinary" / oil / fairy etc. (`picGameType` 3, e.g.
 *     `festivalV101445`): `<key>b` only. No `<key>c`, no flag.
 *
 * Both share the standalone PNG previews (`<key>`, `<key>_mid`).
 *
 * Per-picture layout (only `<key>b` is guaranteed):
 * ```
 * <root>/<key>/
 *     <key>             — 256x256 preview PNG               (always)
 *     <key>_mid         — 512x512 mid-resolution preview    (always)
 *     <key>b            — pipe-delimited region/path data   (always, from zip)
 *     <key>c            — 2048x2048 finished JPEG           (SPV/SSPV only)
 *     sp_new_paint_flag — marker                            (SPV/SSPV only)
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

    /**
     * True iff a picture's gameplay data is present locally. Only the
     * pipe-delimited path-data file is required — `<key>c` and the
     * `sp_new_paint_flag` only ship with SPV/SSPV zips, so requiring them
     * would silently exclude every "V" (ordinary / oil / fairy) picture.
     */
    fun isPictureReady(key: String): Boolean = pathDataFile(key).existsAndNonEmpty()

    fun clear(key: String) {
        pictureDir(key).deleteRecursively()
    }

    private fun safe(name: String): String = name.replace(' ', '_').replace('/', '_')

    private fun File.existsAndNonEmpty() = exists() && length() > 0
}
