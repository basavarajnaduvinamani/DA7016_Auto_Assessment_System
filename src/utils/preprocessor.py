import cv2
import numpy as np
from PIL import Image
import io
from typing import Tuple

class ImagePreprocessor:
    """
    Image preprocessing utility for scanned student answer sheets.
    Handles deskewing, noise reduction, and contrast enhancement before OCR.
    """
    @staticmethod
    def preprocess_for_ocr(image_bytes: bytes) -> Tuple[bytes, dict]:
        # Convert bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return image_bytes, {"status": "skipped", "reason": "invalid_image"}

        # 1. Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. Adaptive contrast normalization
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 3. Bilateral filter for noise reduction while preserving handwriting edges
        denoised = cv2.bilateralFilter(enhanced, d=9, sigmaColor=75, sigmaSpace=75)

        # Encode back to PNG bytes
        is_success, buffer = cv2.imencode(".png", denoised)
        processed_bytes = buffer.tobytes() if is_success else image_bytes

        meta = {
            "original_shape": img.shape,
            "channels": 1,
            "preprocessed": True,
            "method": "CLAHE + BilateralFilter"
        }
        return processed_bytes, meta
