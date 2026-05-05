import cv2
import numpy as np

def smooth_contour(pts, iterations=2):
    pts = pts.astype(np.float32).squeeze()
    if pts.ndim < 2 or len(pts) < 3:
        return pts
    for _ in range(iterations):
        smoothed = []
        num_pts = len(pts)
        for i in range(num_pts):
            p0 = pts[i]
            p1 = pts[(i + 1) % num_pts]
            q = 0.75 * p0 + 0.25 * p1
            r = 0.25 * p0 + 0.75 * p1
            smoothed.extend([q, r])
        pts = np.array(smoothed)
    return pts

mask = np.zeros((100, 100), np.uint8)
cv2.rectangle(mask, (20, 20), (80, 80), 255, -1)
cv2.rectangle(mask, (70, 70), (90, 90), 255, -1)

contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_TC89_KCOS)
c = contours[0]

c_s = cv2.approxPolyDP(c, 2.0, True)
c_smooth = smooth_contour(c_s, 2)

img = np.zeros((100, 100, 3), np.uint8)
cv2.drawContours(img, [c_s.astype(np.int32)], -1, (0, 0, 255), 1)
cv2.drawContours(img, [c_smooth.astype(np.int32)], -1, (0, 255, 0), 1)
cv2.imwrite("test_smooth.png", img)
print("Saved test_smooth.png, original points: {}, smooth points: {}".format(len(c_s), len(c_smooth)))
