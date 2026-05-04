package com.apero.color.number.iceors.network

import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Thin HTTP helper. Uses [HttpURLConnection] to avoid pulling in OkHttp.
 *
 * The CDN treats missing keys as 403, so callers should not log those — handle
 * with [Result.NotFound] and continue.
 */
internal object IceorsHttp {
    private const val CONNECT_TIMEOUT_MS = 15_000
    private const val READ_TIMEOUT_MS = 30_000

    sealed interface Result<out T> {
        data class Ok<T>(val value: T) : Result<T>
        data object NotFound : Result<Nothing>
        data class Err(val code: Int, val message: String) : Result<Nothing>
    }

    fun <T> get(url: String, body: (InputStream, contentLength: Long) -> T): Result<T> {
        val conn = openConnection(url, "GET", null)
        return try {
            conn.connect()
            when (val code = conn.responseCode) {
                in 200..299 -> {
                    val len = conn.contentLengthLong
                    Result.Ok(conn.inputStream.use { body(it, len) })
                }

                403, 404 -> Result.NotFound
                else -> Result.Err(code, conn.responseMessage.orEmpty())
            }
        } catch (e: IOException) {
            Result.Err(0, e.message.orEmpty())
        } finally {
            conn.disconnect()
        }
    }

    fun postJson(url: String, jsonBody: String): Result<ByteArray> {
        val conn = openConnection(url, "POST", "text/plain; charset=utf-8")
        return try {
            conn.doOutput = true
            conn.outputStream.use { it.write(jsonBody.toByteArray(Charsets.UTF_8)) }
            when (val code = conn.responseCode) {
                in 200..299 -> Result.Ok(conn.inputStream.use { it.readBytes() })
                403, 404 -> Result.NotFound
                else -> Result.Err(code, conn.responseMessage.orEmpty())
            }
        } catch (e: IOException) {
            Result.Err(0, e.message.orEmpty())
        } finally {
            conn.disconnect()
        }
    }

    private fun openConnection(url: String, method: String, contentType: String?): HttpURLConnection {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = CONNECT_TIMEOUT_MS
        conn.readTimeout = READ_TIMEOUT_MS
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("User-Agent", IceorsCdn.USER_AGENT)
        conn.setRequestProperty("Cache-Control", "no-cache, max-age=0")
        if (contentType != null) conn.setRequestProperty("Content-Type", contentType)
        return conn
    }
}
