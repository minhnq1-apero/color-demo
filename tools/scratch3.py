import cv2
import numpy as np

# Draw a jagged circle to simulate jagged boundary
boundary = np.zeros((200, 200), np.uint8)
cv2.circle(boundary, (100, 100), 50, 255, 1)

# houghlines
segments = cv2.HoughLinesP(boundary, rho=1, theta=np.pi/180, threshold=10, minLineLength=5, maxLineGap=2)
print("HoughLinesP count:", len(segments) if segments is not None else 0)

# findContours
contours, _ = cv2.findContours(boundary, cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)
strokes = []
for c in contours:
    if cv2.arcLength(c, False) < 20: continue
    c_s = cv2.approxPolyDP(c, 0.8, False)
    strokes.append(c_s)
print("findContours count:", len(strokes))
