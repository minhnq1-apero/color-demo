package com.apero.color.number.model

import android.graphics.Point

class Coordinate(
    val x: Int,
    val y: Int,
    val textSize: Int,
) {
    var points: List<Point>? = null
    var completed: Boolean = false
}
