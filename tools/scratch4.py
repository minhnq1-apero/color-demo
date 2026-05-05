import cv2
import numpy as np

# Draw a 2x2 staircase simulating a diagonal line
mask = np.zeros((20, 20), dtype=np.uint8)
for i in range(10):
    mask[i*2:(i+1)*2, i*2:(i+1)*2] = 255
    if i > 0:
        mask[i*2:(i+1)*2, (i-1)*2:i*2] = 255

contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
c = contours[0]

for eps in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]:
    c_s = cv2.approxPolyDP(c, eps, closed=True)
    print(f"Epsilon {eps}: {len(c_s)} points")
