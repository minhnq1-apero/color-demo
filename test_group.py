from svgelements import SVG, Group, Path, Shape
import io
svg_data = b"""
<svg viewBox="0 0 100 100">
  <g fill="red">
     <path d="M0,0 L10,0 L10,10 Z"/>
     <path d="M10,0 L20,0 L20,10 Z"/>
  </g>
</svg>
"""
svg = SVG.parse(io.BytesIO(svg_data))
for elem in svg.elements():
    print(type(elem), elem)
