import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Tạo ảnh có viền đen bao quanh vùng da mặt (mô phỏng sticker)
img = np.ones((512, 512, 3), dtype=np.uint8) * 255
# Vòng tròn đen lớn (viền)
cv2.circle(img, (256, 256), 200, (40, 40, 40), -1)
# Vùng da mặt (bên trong viền) 
cv2.circle(img, (256, 256), 170, (220, 200, 180), -1)
# Mắt đen (bên trong da mặt)
cv2.circle(img, (210, 230), 20, (40, 40, 40), -1)
cv2.circle(img, (300, 230), 20, (40, 40, 40), -1)

lines, _, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=512)

fills = [l for l in lines if l.split("|")[2] == "0"]
print(f"Total fills: {len(fills)}")
for f in fills:
    svg = f.split("|")[0]
    color = f.split("|")[1]
    has_hole = svg.count("M") > 1
    print(f"  Color: {color}, has_hole: {has_hole}, sub-paths: {svg.count('M')}")
