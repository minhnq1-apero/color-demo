import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Create synthetic santa face
img = np.ones((500, 500, 3), dtype=np.uint8) * 255 # White background
cv2.circle(img, (250, 250), 200, (200, 220, 255), -1) # Face (BGR)
cv2.circle(img, (180, 200), 20, (30, 30, 30), -1) # Left eye (dark brown)
cv2.circle(img, (320, 200), 20, (30, 30, 30), -1) # Right eye

# Add some other details like a nose
cv2.circle(img, (250, 280), 30, (50, 50, 255), -1) # Red nose

img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

lines, _, palette = process_array(img_rgb, n_colors=4, kmeans_size=500, include_strokes=True)

print(f"Total lines: {len(lines)}")
fills = [l for l in lines if "|0|" in l.split("|")[2:3]]
print(f"Fill lines: {len(fills)}")

# Let's inspect the fill lines to see if eyes and nose are there
areas = []
for f in fills:
    parts = f.split("|")
    # Area isn't in the string, but we can guess by order. The smallest are at the end.
    print(f"Color: {parts[1]}")
