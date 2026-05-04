package com.apero.color.number.model

import android.graphics.Color
import org.json.JSONObject

class Level(
    val level: Int,
    val color: Int,
    val textColor: Int,
    val coordinates: List<Coordinate>,
) {
    val isCompleted: Boolean
        get() = coordinates.all { it.completed }

    companion object {
        fun parseAll(json: String): List<Level> {
            val root = JSONObject(json)
            val arr = root.getJSONArray("levels")
            return List(arr.length()) { i ->
                val obj = arr.getJSONObject(i)
                val coordsArr = obj.getJSONArray("coordinates")
                val coords = List(coordsArr.length()) { j ->
                    val c = coordsArr.getJSONObject(j)
                    Coordinate(
                        x = c.getInt("x"),
                        y = c.getInt("y"),
                        textSize = c.getInt("textSize"),
                    )
                }
                Level(
                    level = obj.getInt("level"),
                    color = Color.parseColor(obj.getString("color")),
                    textColor = Color.parseColor(obj.getString("textColor")),
                    coordinates = coords,
                )
            }
        }
    }
}
