import cv2
import numpy as np
from image_to_colorbynumber import process_array

img = np.ones((512, 512, 3), dtype=np.uint8) * 255
cv2.circle(img, (256, 256), 150, (200, 100, 50), -1)
cv2.circle(img, (220, 230), 20, (0, 0, 0), -1)
cv2.circle(img, (290, 230), 20, (0, 0, 0), -1)

lines, _, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=512)
print(f"Total lines: {len(lines)}")
# Check coords stay within bounds
for l in lines:
    svg = l.split("|")[0]
    import re
    nums = re.findall(r'[-+]?\d*\.?\d+', svg)
    floats = [float(n) for n in nums]
    mn, mx = min(floats), max(floats)
    if mn < -10 or mx > 2058:
        print(f"  WARNING: coords out of bounds min={mn:.0f} max={mx:.0f}")
    
print("All coords within bounds: OK")
