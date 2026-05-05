import cv2
import numpy as np

boundary = np.zeros((100, 100), np.uint8)
cv2.rectangle(boundary, (10, 10), (90, 90), 255, 1)

contours, _ = cv2.findContours(boundary, cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)
for c in contours:
    print(f"Contour shape: {c.shape}, arcLength (closed=True): {cv2.arcLength(c, True)}")
