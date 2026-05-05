import cv2
import numpy as np

def chaikin_smooth(pts, iterations=1):
    for _ in range(iterations):
        smoothed = []
        num_pts = len(pts)
        for i in range(num_pts):
            p0 = pts[i]
            p1 = pts[(i + 1) % num_pts]
            
            # Tính 2 điểm mới cách p0 25% và 75%
            q = 0.75 * p0 + 0.25 * p1
            r = 0.25 * p0 + 0.75 * p1
            
            smoothed.append(q)
            smoothed.append(r)
        pts = np.array(smoothed)
    return pts

c = np.array([[[0,0]], [[10,0]], [[10,10]], [[0,10]]], dtype=np.float32)
smoothed = chaikin_smooth(c, 2)
print("Original:", len(c))
print("Smoothed:", len(smoothed))
