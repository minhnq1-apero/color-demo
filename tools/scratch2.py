import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Create a simple test image (3 colors)
img = np.zeros((100, 100, 3), dtype=np.uint8)
img[:, :33] = [255, 0, 0]
img[:, 33:66] = [0, 255, 0]
img[:, 66:] = [0, 0, 255]

lines, _, _ = process_array(img, n_colors=3, kmeans_size=100, include_strokes=True)
print("Total lines:", len(lines))
fills = [l for l in lines if l.split("|")[2].strip() == "0"]
strokes = [l for l in lines if l.split("|")[2].strip() != "0"]
print("Fills:", len(fills))
print("Strokes:", len(strokes))
print("Sample stroke:", strokes[0] if strokes else "None")
