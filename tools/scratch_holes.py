import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Synthetic santa: white bg, red hat, skin face, black eyes.
img = np.ones((500, 500, 3), dtype=np.uint8) * 255
cv2.circle(img, (250, 250), 100, (200, 220, 255), -1) # face
cv2.circle(img, (220, 230), 10, (0, 0, 0), -1) # left eye
cv2.circle(img, (280, 230), 10, (0, 0, 0), -1) # right eye

lines, _, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=500, min_fill_area=50)
fills = [l for l in lines if "|0|" in l.split("|")[2:3]]
print(f"With min_area 50: {len(fills)} fills")

lines, _, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=500, min_fill_area=500)
fills = [l for l in lines if "|0|" in l.split("|")[2:3]]
print(f"With min_area 500: {len(fills)} fills")
