package com.apero.color.number.iceors

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File
import java.io.FileOutputStream

/**
 * Saves a bitmap to the device's Pictures/ColorByNumber/ folder via MediaStore
 * on Android Q+, or directly to external storage on older versions.
 *
 * Returns the public URI as a string on success, or null on failure.
 */
object BitmapExporter {

    private const val FOLDER = "ColorByNumber"
    private const val MIME = "image/png"

    fun save(context: Context, bitmap: Bitmap, fileName: String): String? {
        val safeName = if (fileName.endsWith(".png", ignoreCase = true)) fileName else "$fileName.png"

        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            saveScopedStorage(context, bitmap, safeName)
        } else {
            saveLegacy(bitmap, safeName)
        }
    }

    private fun saveScopedStorage(context: Context, bitmap: Bitmap, fileName: String): String? {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, fileName)
            put(MediaStore.Images.Media.MIME_TYPE, MIME)
            put(
                MediaStore.Images.Media.RELATIVE_PATH,
                "${Environment.DIRECTORY_PICTURES}/$FOLDER",
            )
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: return null
        try {
            resolver.openOutputStream(uri)?.use { os ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, os)
            } ?: return null
            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            return uri.toString()
        } catch (t: Throwable) {
            resolver.delete(uri, null, null)
            return null
        }
    }

    @Suppress("DEPRECATION")
    private fun saveLegacy(bitmap: Bitmap, fileName: String): String? {
        val pictures = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES)
        val dir = File(pictures, FOLDER).apply { mkdirs() }
        val file = File(dir, fileName)
        return try {
            FileOutputStream(file).use { fos ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, fos)
            }
            file.absolutePath
        } catch (t: Throwable) {
            null
        }
    }
}
