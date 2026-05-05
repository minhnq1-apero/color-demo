import cv2
import numpy as np
from image_to_colorbynumber import process_array

def draw_android_preview(lines: list[str], canvas_size: int = 2048) -> np.ndarray:
    img = np.ones((canvas_size, canvas_size, 3), dtype=np.uint8) * 255
    for line in lines:
        parts = line.split("|")
        if len(parts) < 3: continue
        svg = parts[0]
        color_hex = parts[1]
        stroke_width = float(parts[2])
        
        is_closed = "Z" in svg
        svg = svg.replace("M", "").replace("Z", "")
        pts_str = svg.split("L")
        pts = []
        for p in pts_str:
            if not p.strip(): continue
            x, y = p.split(",")
            pts.append([float(x), float(y)])
        
        if not pts: continue
        pts = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
        
        if stroke_width == 0:
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            cv2.fillPoly(img, [pts], (r, g, b))
        else:
            cv2.polylines(img, [pts], isClosed=is_closed, color=(0,0,0), thickness=max(1, int(stroke_width)))
    return img

img = np.ones((1024, 1024, 3), dtype=np.uint8) * 255
cv2.circle(img, (512, 512), 300, (200, 220, 255), -1)
cv2.circle(img, (400, 450), 30, (0, 0, 0), -1)

lines, _, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=1024)

preview = draw_android_preview(lines, 2048)
print("Preview shape:", preview.shape)
cv2.imwrite("test_android_preview.png", cv2.cvtColor(preview, cv2.COLOR_RGB2BGR))
