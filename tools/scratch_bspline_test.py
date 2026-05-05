import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Tạo ảnh test
img = np.ones((512, 512, 3), dtype=np.uint8) * 255
cv2.circle(img, (256, 256), 150, (200, 100, 50), -1)
cv2.circle(img, (220, 230), 20, (0, 0, 0), -1)
cv2.circle(img, (290, 230), 20, (0, 0, 0), -1)

lines, preview, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=512)
print(f"Total lines: {len(lines)}")
sample = lines[0][:150] if lines else "NONE"
print(f"Sample: {sample}")
has_C = any("C" in l.split("|")[0] for l in lines)
print(f"Bézier curves: {has_C}")
print("OK!")
