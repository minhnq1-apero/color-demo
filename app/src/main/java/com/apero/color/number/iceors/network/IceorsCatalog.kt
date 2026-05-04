package com.apero.color.number.iceors.network

import org.json.JSONArray
import org.json.JSONObject

/**
 * Strongly-typed view over the catalog JSON returned by
 * `POST https://coloring.galaxyaura.com/coloringbook` (and bundled at
 * `assets/cc` inside the original APK). Only the fields used by the UI/loader
 * are surfaced — the rest stay in [raw] for callers that need them.
 */
data class IceorsCatalog(
    val version: Int,
    val collections: List<Collection>,
    val raw: JSONObject,
) {
    data class Collection(
        val name: String,
        val displayName: String,
        val themeColor: String?,
        val info1: String?,
        val endDate: String?,
        val type: Int,
        val pics: List<Picture>,
    )

    data class Picture(
        val key: String,
        val type: String,
        val picGameType: Int,
        val version: Int,
        val expectedVersion: Int,
    )

    companion object {
        fun fromJson(json: JSONObject): IceorsCatalog {
            val cb = json.optJSONObject("collectionBean") ?: JSONObject()
            val collections = cb.optJSONArray("collection")?.let(::parseCollections).orEmpty()
            return IceorsCatalog(
                version = json.optInt("version"),
                collections = collections,
                raw = json,
            )
        }

        private fun parseCollections(array: JSONArray): List<Collection> = buildList {
            for (i in 0 until array.length()) {
                val obj = array.optJSONObject(i) ?: continue
                add(
                    Collection(
                        name = obj.optString("name"),
                        displayName = obj.optString("displayName", obj.optString("name")),
                        themeColor = obj.optString("themeColor").ifBlank { null },
                        info1 = obj.optString("info1").ifBlank { null },
                        endDate = obj.optString("endDate").ifBlank { null },
                        type = obj.optInt("type", 0),
                        pics = obj.optJSONArray("pics")?.let(::parsePics).orEmpty(),
                    )
                )
            }
        }

        private fun parsePics(array: JSONArray): List<Picture> = buildList {
            for (i in 0 until array.length()) {
                val obj = array.optJSONObject(i) ?: continue
                val key = obj.optString("key").ifBlank { continue }
                add(
                    Picture(
                        key = key,
                        type = obj.optString("type"),
                        picGameType = obj.optInt("picGameType", 0),
                        version = obj.optInt("version", 0),
                        expectedVersion = obj.optInt("expectedVersion", 0),
                    )
                )
            }
        }
    }
}

object IceorsCatalogClient {

    /**
     * Fetches the live catalog from the API. Body is a tiny preference bean —
     * the original app sends client preference flags here, but the server
     * returns the full catalog regardless of body content.
     */
    fun fetch(): IceorsCatalog {
        // Field names come from UnionRequestBean (com/iceors/colorbook/network/requestbean).
        // "cv" = catalog version the client already has (0 = no cache, get full catalog).
        // "tz" = timezone offset. Other flags default 0.
        val body = """{"cv":0,"tz":0,"banner":0,"cl":0,"dy":0,"dy2":0,"fev":0}"""
        val resp = IceorsHttp.postJson(IceorsCdn.CATALOG_URL, body)
        when (resp) {
            is IceorsHttp.Result.Ok -> {
                val json = JSONObject(String(resp.value, Charsets.UTF_8))
                return IceorsCatalog.fromJson(json)
            }

            is IceorsHttp.Result.NotFound -> error("catalog endpoint returned 404/403")
            is IceorsHttp.Result.Err -> error("catalog HTTP ${resp.code}: ${resp.message}")
        }
    }

    /** Parse a catalog already on disk (e.g. the bundled `assets/cc` snapshot). */
    fun parse(json: String): IceorsCatalog =
        IceorsCatalog.fromJson(JSONObject(json))
}
