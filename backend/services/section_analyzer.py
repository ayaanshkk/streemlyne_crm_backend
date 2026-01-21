"""
Section Analysis - Analyze individual cabinet sections for depth, type, features
"""
from PIL import Image
import cv2
import numpy as np
from typing import Dict, Optional
import logging
import re
import json

logger = logging.getLogger(__name__)


class SectionAnalyzer:
    """Analyze individual cabinet sections"""
    
    def __init__(self, qwen_extractor=None):
        """
        Args:
            qwen_extractor: OCRDimensionExtractor instance (for Qwen queries)
        """
        self.qwen_extractor = qwen_extractor
    
    def analyze_section(self, section: Dict) -> Dict:
        """
        Analyze one cabinet section
        
        Args:
            section: Section dict with 'cropped_array', 'width_mm', 'index'
            
        Returns:
            Dict with analysis results:
                - depth_mm: int
                - cabinet_type: str
                - shelves: int
                - drawers: int
                - doors: int
                - confidence: str
        """
        
        width_mm = section['width_mm']
        index = section['index']
        cropped_array = section['cropped_array']
        
        logger.info(f"🔍 Analyzing section {index}: {width_mm}mm wide")
        
        # Convert to PIL Image for Qwen
        cropped_pil = Image.fromarray(cv2.cvtColor(cropped_array, cv2.COLOR_BGR2RGB))
        
        # Try AI analysis first
        if self.qwen_extractor:
            try:
                ai_result = self._analyze_with_ai(cropped_pil, width_mm, index)
                
                if ai_result['confidence'] != 'failed':
                    logger.info(f"   ✓ AI analysis: {ai_result['cabinet_type']}, depth: {ai_result['depth_mm']}mm")
                    return ai_result
                    
            except Exception as e:
                logger.warning(f"AI analysis failed for section {index}: {e}")
        
        # Fallback to rule-based analysis
        logger.info(f"   Using rule-based analysis for section {index}")
        return self._analyze_rule_based(width_mm, cropped_array)
    
    def _analyze_with_ai(self, section_image: Image.Image, 
                        width_mm: int, index: int) -> Dict:
        """Analyze section using Qwen2.5-VL"""
        
        # Check if Qwen is available
        if self.qwen_extractor is None or not self.qwen_extractor.qwen_available:
            logger.warning(f"⚠️ Qwen not available for section {index}, using rule-based")
            # Return immediately to use rule-based fallback
            return {
                'depth_mm': 560,
                'cabinet_type': 'straight',
                'shelves': 1,
                'drawers': 0,
                'doors': 1,
                'confidence': 'failed'
            }
        
        prompt = f"""You are analyzing ONE cabinet section from a kitchen layout drawing.

    **THIS SECTION**:
    - Width: {width_mm}mm (already known)
    - Position: Section #{index} in the layout

    **YOUR TASK**: Extract the DEPTH dimension and features for THIS SECTION ONLY.

    **WHAT TO EXTRACT**:
    1. **Depth** (front-to-back dimension in mm) - Look for depth measurements
    2. **Cabinet type**:
    - "straight" = normal straight cabinet
    - "corner" = L-shaped, usually depth > 700mm
    - "filler" = narrow panel, width < 200mm
    - "drawer" = has drawer divisions visible
    - "tall" = tall unit, depth > 1200mm

    3. **Features** (count what you see):
    - Number of shelves (horizontal lines inside)
    - Number of drawers (if visible)
    - Number of doors (if indicated)

    **LOOK CAREFULLY** at this specific section's measurements and internal divisions.

    **OUTPUT FORMAT** - Return ONLY this JSON:
    {{
    "depth_mm": 560,
    "cabinet_type": "straight",
    "shelves": 1,
    "drawers": 0,
    "doors": 1,
    "confidence": "high"
    }}

    Analyze now:"""

        try:
            result_text = self.qwen_extractor._query_qwen(section_image, prompt)
            
            logger.debug(f"Section {index} AI result: {result_text}")
            
            # Parse JSON
            json_match = re.search(r'\{[^}]+\}', result_text, re.DOTALL)
            
            if json_match:
                data = json.loads(json_match.group())
                
                # Validate and extract
                depth = int(data.get('depth_mm', 560))
                cabinet_type = data.get('cabinet_type', 'straight')
                
                # Sanity checks
                if depth < 200 or depth > 2000:
                    logger.warning(f"Unusual depth {depth}mm, using default 560mm")
                    depth = 560
                
                return {
                    'depth_mm': depth,
                    'cabinet_type': cabinet_type,
                    'shelves': int(data.get('shelves', 1)),
                    'drawers': int(data.get('drawers', 0)),
                    'doors': int(data.get('doors', 1)),
                    'confidence': data.get('confidence', 'medium')
                }
            
            # Fallback parsing
            depth_match = re.search(r'(\d{3,4})\s*mm', result_text)
            if depth_match:
                depth = int(depth_match.group(1))
                
                return {
                    'depth_mm': depth,
                    'cabinet_type': self._infer_cabinet_type(width_mm, depth),
                    'shelves': 1,
                    'drawers': 0,
                    'doors': 1,
                    'confidence': 'medium'
                }
                
        except Exception as e:
            logger.error(f"AI analysis error for section {index}: {e}")
        
        # Return failed so rule-based takes over
        return {
            'depth_mm': 560,
            'cabinet_type': 'straight',
            'shelves': 1,
            'drawers': 0,
            'doors': 1,
            'confidence': 'failed'
        }
    
    def _analyze_rule_based(self, width_mm: int, cropped_array: np.ndarray) -> Dict:
        """
        Rule-based analysis as fallback
        Uses heuristics based on width and visual features
        """
        
        # Infer type from width
        if width_mm < 200:
            cabinet_type = 'filler'
            depth = 560
        elif width_mm > 1000:
            cabinet_type = 'corner'
            depth = 900  # Likely a corner
        else:
            cabinet_type = 'straight'
            depth = 560  # Standard depth
        
        # Try to detect horizontal lines (shelves)
        gray = cv2.cvtColor(cropped_array, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50, minLineLength=30, maxLineGap=10)
        
        horizontal_lines = 0
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                
                if angle < 10:  # Horizontal
                    horizontal_lines += 1
        
        shelves = min(horizontal_lines // 2, 3)  # Estimate shelves
        
        return {
            'depth_mm': depth,
            'cabinet_type': cabinet_type,
            'shelves': shelves if shelves > 0 else 1,
            'drawers': 0,
            'doors': 1,
            'confidence': 'low'
        }
    
    def _infer_cabinet_type(self, width_mm: int, depth_mm: int) -> str:
        """Infer cabinet type from dimensions"""
        
        if width_mm < 200:
            return 'filler'
        elif depth_mm > 700:
            return 'corner'
        elif depth_mm > 1200:
            return 'tall'
        else:
            return 'straight'