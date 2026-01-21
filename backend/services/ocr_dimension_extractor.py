"""
OCR Dimension Extraction - Updated to use modular pipeline
"""
from PIL import Image
import io
import re
import base64
import os
import json
from typing import List, Dict
import logging

from services.cutting_list_builder import CuttingListBuilder

logger = logging.getLogger('OCRExtractor')


class OCRDimensionExtractor:
    """Extract dimensions and generate cutting lists from technical drawings"""
    
    def __init__(self):
        """Initialize OCR service"""
        self.qwen_available = False
        self.openai_available = False
        
        # Try to load Qwen2.5-VL (PRIMARY)
        try:
            from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
            from qwen_vl_utils import process_vision_info
            import torch
            
            logger.info("🔄 Loading Qwen2.5-VL model (PRIMARY)...")
            
            model_name = "Qwen/Qwen2-VL-2B-Instruct"
            
            self.qwen_model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_name,
                torch_dtype=torch.float16,
                device_map="auto"
            )
            self.qwen_processor = AutoProcessor.from_pretrained(model_name)
            self.process_vision_info = process_vision_info
            
            self.qwen_available = True
            logger.info("✅ Qwen2.5-VL loaded successfully (PRIMARY)")
            
        except Exception as e:
            logger.warning(f"⚠️ Qwen2.5-VL not available: {e}")
        
        # Initialize pipeline
        self.pipeline = CuttingListBuilder(qwen_extractor=self)
    
    def extract_dimensions(self, image_bytes: bytes) -> Dict:
        """
        Main entry point: Extract dimensions and generate cutting list
        
        Args:
            image_bytes: Raw image bytes
            
        Returns:
            Dict with cutting list and metadata
        """
        
        # Use the new pipeline
        result = self.pipeline.build_cutting_list(image_bytes)
        
        return result
    
    def _query_qwen(self, image: Image.Image, prompt: str) -> str:
        """Query Qwen2.5-VL with image and prompt"""
        
        if not self.qwen_available:
            raise RuntimeError("Qwen not available")
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt}
                ]
            }
        ]
        
        text = self.qwen_processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        image_inputs, video_inputs = self.process_vision_info(messages)
        
        inputs = self.qwen_processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt"
        )
        
        inputs = inputs.to(self.qwen_model.device)
        
        import torch
        with torch.no_grad():
            generated_ids = self.qwen_model.generate(
                **inputs,
                max_new_tokens=1000,
                temperature=0.1,
                do_sample=False
            )
        
        generated_ids_trimmed = [
            out_ids[len(in_ids):] 
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        
        output_text = self.qwen_processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]
        
        return output_text