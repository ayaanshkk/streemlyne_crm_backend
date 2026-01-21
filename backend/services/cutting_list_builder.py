"""
Cutting List Builder - Main orchestrator for the entire pipeline
"""
from typing import Dict, List
import logging

from services.preprocessing import ImagePreprocessor
from services.section_detector import SectionDetector
from services.section_analyzer import SectionAnalyzer
from services.manufacturing_rules import ManufacturingRules

logger = logging.getLogger(__name__)


class CuttingListBuilder:
    """
    Main pipeline orchestrator
    Coordinates all steps from image to cutting list
    """
    
    def __init__(self, qwen_extractor=None):
        """
        Args:
            qwen_extractor: OCRDimensionExtractor instance for AI queries
        """
        self.preprocessor = ImagePreprocessor()
        self.section_detector = SectionDetector(qwen_extractor)
        self.section_analyzer = SectionAnalyzer(qwen_extractor)
        self.manufacturing_rules = ManufacturingRules()
    
    def build_cutting_list(self, image_bytes: bytes) -> Dict:
        """
        Main entry point: Convert image to cutting list
        
        Args:
            image_bytes: Raw image bytes
            
        Returns:
            Dict with complete cutting list and metadata
        """
        
        logger.info("=" * 70)
        logger.info("🚀 STARTING CUTTING LIST GENERATION PIPELINE")
        logger.info("=" * 70)
        
        try:
            # STEP 1: Preprocess image
            logger.info("\n📸 STEP 1: Preprocessing image...")
            processed_image, preprocess_meta = self.preprocessor.process(image_bytes)
            
            if not preprocess_meta['validation']['valid']:
                logger.warning("⚠️ Image validation warnings:")
                for warning in preprocess_meta['validation']['warnings']:
                    logger.warning(f"   - {warning}")
            
            # STEP 2: Extract dimension line and detect sections
            logger.info("\n📏 STEP 2: Extracting dimensions and detecting sections...")
            dimension_result = self.section_detector.extract_dimension_line(processed_image)
            
            if not dimension_result['cabinet_widths']:
                logger.error("❌ Failed to extract cabinet widths")
                return self._generate_error_response("Failed to extract dimensions")
            
            logger.info(f"   ✓ Found {len(dimension_result['cabinet_widths'])} cabinets: "
                       f"{dimension_result['cabinet_widths']}")
            
            sections = self.section_detector.detect_sections(processed_image, dimension_result)
            
            if not sections:
                logger.error("❌ Failed to detect cabinet sections")
                return self._generate_error_response("Failed to detect sections")
            
            logger.info(f"   ✓ Detected {len(sections)} sections")
            
            # STEP 3: Analyze each section
            logger.info("\n🔍 STEP 3: Analyzing each section...")
            analyzed_sections = []
            
            for section in sections:
                analysis = self.section_analyzer.analyze_section(section)
                section.update(analysis)
                analyzed_sections.append(section)
                
                logger.info(f"   ✓ Section {section['index']}: {section['cabinet_type']}, "
                          f"depth: {section['depth_mm']}mm")
            
            # STEP 4: Apply manufacturing rules
            logger.info("\n⚙️ STEP 4: Applying manufacturing rules...")
            all_components = []
            
            for section in analyzed_sections:
                components = self.manufacturing_rules.calculate_components(section)
                all_components.extend(components)
            
            # Add end panels
            all_components = self.manufacturing_rules.add_end_panels(
                all_components, 
                len(analyzed_sections)
            )
            
            logger.info(f"   ✓ Generated {len(all_components)} total components")
            
            # STEP 5: Format output
            logger.info("\n📊 STEP 5: Formatting output...")
            
            # Calculate totals
            total_pieces = sum(comp['quantity'] for comp in all_components)
            total_area = self._calculate_total_area(all_components)
            
            # Calculate confidence
            confidence = self._calculate_confidence(analyzed_sections, dimension_result)
            
            # Generate markdown table
            table_markdown = self._format_markdown_table(all_components)
            
            # Generate CSV data
            table_data = self._format_table_data(all_components)
            
            result = {
                'success': True,
                'method': 'dimension_driven_hybrid',
                'confidence': confidence,
                'preprocessing': preprocess_meta,
                'dimension_extraction': dimension_result,
                'sections': self._serialize_sections(analyzed_sections),
                'components': all_components,
                'table_markdown': table_markdown,
                'table_data': table_data,
                'summary': {
                    'total_cabinets': len(analyzed_sections),
                    'total_components': len(all_components),
                    'total_pieces': total_pieces,
                    'total_area_m2': total_area
                }
            }
            
            logger.info("\n" + "=" * 70)
            logger.info("✅ PIPELINE COMPLETE")
            logger.info(f"📦 Cabinets: {len(analyzed_sections)}, Components: {len(all_components)}, "
                       f"Pieces: {total_pieces}")
            logger.info(f"🎯 Confidence: {confidence:.1%}")
            logger.info("=" * 70)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
            return self._generate_error_response(str(e))
    
    def _serialize_sections(self, sections: List[Dict]) -> List[Dict]:
        """Remove non-serializable fields from sections"""
        serialized = []
        
        for section in sections:
            serialized.append({
                'index': section['index'],
                'width_mm': section['width_mm'],
                'depth_mm': section.get('depth_mm'),
                'cabinet_type': section.get('cabinet_type'),
                'shelves': section.get('shelves'),
                'drawers': section.get('drawers'),
                'doors': section.get('doors'),
                'confidence': section.get('confidence')
            })
        
        return serialized
    
    def _calculate_total_area(self, components: List[Dict]) -> float:
        """Calculate total area in square meters"""
        total_area_mm2 = 0
        
        for comp in components:
            width = comp.get('width')
            height = comp.get('height')
            depth = comp.get('depth')
            qty = comp.get('quantity', 1)
            
            # Calculate area based on what dimensions are available
            if width and height:
                total_area_mm2 += width * height * qty
            elif width and depth:
                total_area_mm2 += width * depth * qty
        
        return total_area_mm2 / 1_000_000  # Convert to m²
    
    def _calculate_confidence(self, sections: List[Dict], dimension_result: Dict) -> float:
        """Calculate overall confidence score"""
        
        # Base confidence from dimension extraction
        dim_confidence_map = {'high': 0.9, 'medium': 0.7, 'low': 0.5, 'failed': 0.0}
        dim_confidence = dim_confidence_map.get(dimension_result.get('confidence', 'medium'), 0.7)
        
        # Average section confidence
        section_confidences = []
        conf_map = {'high': 0.9, 'medium': 0.7, 'low': 0.5, 'failed': 0.3}
        
        for section in sections:
            section_conf = conf_map.get(section.get('confidence', 'medium'), 0.7)
            section_confidences.append(section_conf)
        
        avg_section_conf = sum(section_confidences) / len(section_confidences) if section_confidences else 0.5
        
        # Weighted average
        overall = (dim_confidence * 0.4) + (avg_section_conf * 0.6)
        
        return overall
    
    def _format_markdown_table(self, components: List[Dict]) -> str:
        """Format components as markdown table"""
        
        lines = [
            "| Component Type | Part Name | Unit Width (mm) | Width (mm) | Height (mm) | Depth (mm) | Qty | Thickness (mm) | Edge Banding |",
            "|:---|:---|:---|:---|:---|:---|:---|:---|:---|"
        ]
        
        for comp in components:
            row = [
                comp.get('component_type', 'N/A'),
                comp.get('part_name', 'N/A'),
                str(comp.get('unit_width', 'N/A')),
                str(comp.get('width', 'N/A')),
                str(comp.get('height', 'N/A')),
                str(comp.get('depth', 'N/A')),
                str(comp.get('quantity', 1)),
                str(comp.get('thickness', 18)),
                comp.get('edge_banding', 'None')
            ]
            lines.append('| ' + ' | '.join(row) + ' |')
        
        return '\n'.join(lines)
    
    def _format_table_data(self, components: List[Dict]) -> List[List[str]]:
        """Format components as 2D array for CSV"""
        
        table_data = [[
            'Component Type', 'Part Name', 'Unit Width (mm)', 'Width (mm)',
            'Height (mm)', 'Depth (mm)', 'Qty', 'Thickness (mm)', 'Edge Banding'
        ]]
        
        for comp in components:
            row = [
                comp.get('component_type', 'N/A'),
                comp.get('part_name', 'N/A'),
                str(comp.get('unit_width', 'N/A')),
                str(comp.get('width', 'N/A')),
                str(comp.get('height', 'N/A')),
                str(comp.get('depth', 'N/A')),
                str(comp.get('quantity', 1)),
                str(comp.get('thickness', 18)),
                comp.get('edge_banding', 'None')
            ]
            table_data.append(row)
        
        return table_data
    
    def _generate_error_response(self, error_message: str) -> Dict:
        """Generate error response"""
        
        return {
            'success': False,
            'error': error_message,
            'method': 'failed',
            'confidence': 0.0,
            'components': [],
            'table_markdown': '',
            'table_data': [],
            'summary': {
                'total_cabinets': 0,
                'total_components': 0,
                'total_pieces': 0,
                'total_area_m2': 0.0
            }
        }