import cv2
import numpy as np
from image_to_colorbynumber import process_array

# Tạo ảnh test đơn giản có hình tròn (kiểm tra đường cong mượt)
img = np.ones((512, 512, 3), dtype=np.uint8) * 255
cv2.circle(img, (256, 256), 150, (200, 100, 50), -1)
cv2.circle(img, (220, 230), 20, (0, 0, 0), -1)  # eye
cv2.circle(img, (290, 230), 20, (0, 0, 0), -1)  # eye

lines, _, _ = process_array(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), n_colors=3, kmeans_size=512)

# Check output
print(f"Total lines: {len(lines)}")
sample = lines[0][:120] if lines else "NO LINES"
print(f"Sample path (first 120 chars): {sample}")
has_C = any("C" in l.split("|")[0] for l in lines)
has_L = any("L" in l.split("|")[0] for l in lines)
print(f"Uses Bézier curves (C): {has_C}")
print(f"Uses straight lines (L): {has_L}")
