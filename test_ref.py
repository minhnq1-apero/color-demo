import io
from PIL import Image as _PILImage

OUTPUT_CANVAS = 2048

def _to_square_jpeg(pil_img, sw: float, sh: float) -> bytes:
    side = max(sw, sh) or 1
    scale = OUTPUT_CANVAS / side
    target_w = max(1, int(round(sw * scale)))
    target_h = max(1, int(round(sh * scale)))
    fit = pil_img.resize((target_w, target_h), _PILImage.LANCZOS)
    square = _PILImage.new("RGB", (OUTPUT_CANVAS, OUTPUT_CANVAS), (255, 255, 255))
    square.paste(fit, ((OUTPUT_CANVAS - target_w) // 2, (OUTPUT_CANVAS - target_h) // 2))
    buf = io.BytesIO()
    square.save(buf, format="JPEG", quality=92)
    return buf.getvalue()

try:
    ref_pil = _PILImage.new("RGBA", (1024, 768), (255, 0, 0, 255))
    sw, sh = float(ref_pil.width), float(ref_pil.height)
    white_bg = _PILImage.new("RGBA", ref_pil.size, (255, 255, 255, 255))
    composed = _PILImage.alpha_composite(white_bg, ref_pil).convert("RGB")
    ref_jpeg = _to_square_jpeg(composed, sw, sh)
    print("Success:", len(ref_jpeg))
except Exception as e:
    print("Error:", e)
