package com.apero.color.number.iceors.network

import java.net.URLEncoder

/**
 * CDN/API endpoints used by Iceors Coloring Book v3.7.8.
 *
 * Strings copied from `apktool_out/res/values/strings.xml`. The doodle-mobile
 * S3 bucket returns 403 (not 404) for missing keys because it has list-deny on,
 * so a 403 just means "this variant doesn't exist for this asset".
 */
object IceorsCdn {
    const val CATALOG_URL = "https://coloring.galaxyaura.com/coloringbook"

    private const val CDN_ROOT = "http://zhangxiaobog.cdn-doodlemobile.com/color_book"

    fun collectionCover(name: String): String =
        "$CDN_ROOT/collection/${urlSafe(name)}.jpg"

    fun collectionCornerBg(name: String): String =
        "$CDN_ROOT/collection/${urlSafe(name)}_corner_bg.jpg"

    fun pictureLineart(key: String): String =
        "$CDN_ROOT/pictures/${pathEncode(key)}/${pathEncode(key)}"

    fun pictureMidPreview(key: String): String =
        "$CDN_ROOT/pictures/${pathEncode(key)}/${pathEncode(key)}_mid"

    fun pictureGameZip(key: String): String =
        "$CDN_ROOT/zips/${pathEncode(key)}_b.zip"

    /** Default User-Agent matching the original app — the CDN does not require it but Retrofit/OkHttp sent it. */
    const val USER_AGENT =
        "Mozilla/5.0 (Linux; Android 14; sdk_gphone64_arm64 Build/UPB5.230623.003) ColoringBook/3.7.8"

    private fun urlSafe(name: String): String = name.replace(' ', '_').replace('/', '_')

    /**
     * Percent-encode characters that are reserved or unsafe in URL path
     * segments. Keys for "oil"-format pics include `&` (e.g.
     * `oilSPV&character147898`) which `java.net.URL` happens to pass through
     * literally, but proxies and `HttpURLConnection`'s underlying parsers
     * sometimes mis-treat it as the query separator. Encoding is safe — the
     * S3 bucket accepts both `&` and `%26` in the path.
     */
    private fun pathEncode(segment: String): String =
        URLEncoder.encode(segment, "UTF-8").replace("+", "%20")
}
