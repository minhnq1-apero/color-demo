import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Create a 1024x1024 image
img = np.ones((1024, 1024, 3), dtype=np.uint8) * 255
# Face
cv2.circle(img, (512, 512), 300, (200, 220, 255), -1)
# Left eye (Radius 30 -> Area ~2800)
cv2.circle(img, (400, 450), 30, (0, 0, 0), -1)
# Right eye
cv2.circle(img, (624, 450), 30, (0, 0, 0), -1)

# Run process
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
lines, _, _ = process_array(img_rgb, n_colors=3, kmeans_size=1024, include_strokes=True)

fills = [l for l in lines if l.split("|")[2] == "0"]
print(f"Total fills: {len(fills)}")
for f in fills:
    area_guess = len(f) # Just to see sizes
    color = f.split("|")[1]
    print(f"Fill Color: {color}, SVG len: {area_guess}")
