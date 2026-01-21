"""
Image Preprocessing for Cabinet Drawings
Handles: PDF conversion, deskewing, enhancement, validation
"""
import cv2
import numpy as np
from PIL import Image
import io
from typing import Tuple, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """Preprocess drawings for analysis"""
    
    def __init__(self, max_size: Tuple[int, int] = (4000, 4000)):
        self.max_size = max_size
    
    def process(self, image_bytes: bytes) -> Tuple[np.ndarray, Dict]:
        """
        Main preprocessing pipeline
        
        Args:
            image_bytes: Raw image bytes
            
        Returns:
            Tuple of (processed_image, metadata)
        """
        logger.info("🔄 Starting image preprocessing...")
        
        # Load image
        image = self._load_image(image_bytes)
        original_size = image.shape[:2]
        
        # Resize if needed
        image = self._resize_if_needed(image)
        
        # Deskew
        image, rotation_angle = self._deskew(image)
        
        # Enhance
        image = self._enhance(image)
        
        # Validate quality
        validation = self._validate_quality(image)
        
        metadata = {
            'original_size': original_size,
            'processed_size': image.shape[:2],
            'rotation_angle': rotation_angle,
            'validation': validation
        }
        
        logger.info(f"✅ Preprocessing complete: {image.shape[1]}x{image.shape[0]}")
        
        return image, metadata
    
    def _load_image(self, image_bytes: bytes) -> np.ndarray:
        """Load image from bytes"""
        
        # Try PIL first
        try:
            pil_image = Image.open(io.BytesIO(image_bytes))
            image = np.array(pil_image)
            
            # Convert to BGR if needed (OpenCV format)
            if len(image.shape) == 2:  # Grayscale
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif image.shape[2] == 4:  # RGBA
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            elif image.shape[2] == 3:  # RGB
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            
            return image
            
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            raise
    
    def _resize_if_needed(self, image: np.ndarray) -> np.ndarray:
        """Resize if image is too large"""
        
        h, w = image.shape[:2]
        max_w, max_h = self.max_size
        
        if w > max_w or h > max_h:
            scale = min(max_w / w, max_h / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            logger.info(f"📐 Resizing from {w}x{h} to {new_w}x{new_h}")
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        return image
    
    def _deskew(self, image: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Correct image rotation/skew
        
        Returns:
            Tuple of (deskewed_image, rotation_angle)
        """
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Edge detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        # Detect lines
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
        
        if lines is None:
            logger.debug("No lines detected for deskew")
            return image, 0.0
        
        # Calculate dominant angle
        angles = []
        for line in lines[:50]:  # First 50 lines
            rho, theta = line[0]
            angle = (theta * 180 / np.pi) - 90
            
            # Filter near-horizontal/vertical
            if abs(angle) < 5 or abs(angle - 90) < 5:
                angles.append(angle)
        
        if not angles:
            return image, 0.0
        
        median_angle = np.median(angles)
        
        # Only rotate if significantly skewed
        if abs(median_angle) > 0.5:
            logger.info(f"🔄 Deskewing by {median_angle:.2f}°")
            
            h, w = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            image = cv2.warpAffine(
                image, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
            
            return image, median_angle
        
        return image, 0.0
    
    def _enhance(self, image: np.ndarray) -> np.ndarray:
        """Enhance image quality"""
        
        # Convert to LAB color space
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Apply CLAHE to L channel (contrast enhancement)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        
        # Merge back
        lab = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        
        # Slight sharpening
        kernel = np.array([
            [-1, -1, -1],
            [-1,  9, -1],
            [-1, -1, -1]
        ]) / 1.0
        
        enhanced = cv2.filter2D(enhanced, -1, kernel)
        
        return enhanced
    
    def _validate_quality(self, image: np.ndarray) -> Dict:
        """
        Validate image quality
        
        Returns:
            Dict with validation results and metrics
        """
        
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Calculate metrics
        mean_intensity = float(np.mean(gray))
        std_intensity = float(np.std(gray))
        
        # Edge density
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.sum(edges > 0) / (w * h))
        
        # Validation
        warnings = []
        
        if w < 800 or h < 600:
            warnings.append("Low resolution (<800x600)")
        
        if mean_intensity > 250:
            warnings.append("Image appears mostly blank")
        
        if std_intensity < 20:
            warnings.append("Very low contrast")
        
        if edge_density < 0.01:
            warnings.append("Very few edges - may not be a technical drawing")
        
        is_valid = len(warnings) == 0
        
        return {
            'valid': is_valid,
            'warnings': warnings,
            'metrics': {
                'width': w,
                'height': h,
                'mean_intensity': mean_intensity,
                'contrast': std_intensity,
                'edge_density': edge_density
            }
        }


class PDFConverter:
    """Convert PDF to image"""
    
    @staticmethod
    def convert(pdf_bytes: bytes, dpi: int = 300) -> bytes:
        """
        Convert PDF first page to image bytes
        
        Args:
            pdf_bytes: PDF file bytes
            dpi: Resolution for conversion
            
        Returns:
            Image bytes (PNG format)
        """
        
        try:
            import fitz  # PyMuPDF
            
            logger.info(f"📄 Converting PDF to image at {dpi} DPI...")
            
            # Open PDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc[0]  # First page
            
            # Render at high DPI
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to PNG bytes
            img_bytes = pix.tobytes("png")
            
            doc.close()
            
            logger.info(f"✅ PDF converted: {pix.width}x{pix.height}")
            
            return img_bytes
            
        except ImportError:
            logger.error("PyMuPDF not installed. Install with: pip install PyMuPDF")
            raise
        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            raise