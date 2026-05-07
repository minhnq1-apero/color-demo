from svgelements import SVG
import io
svg_data = b'<svg width="100%" height="100%"><rect width="10" height="10"/></svg>'
parsed = SVG.parse(io.BytesIO(svg_data))
print("width:", type(parsed.width), parsed.width)
try:
    print("float width:", float(parsed.width))
except Exception as e:
    print("Error:", e)
