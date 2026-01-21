"""
Manufacturing Rules - Apply formulas to calculate component dimensions
"""
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class ManufacturingRules:
    """Apply manufacturing rules to calculate cutting list components"""
    
    # Constants
    GABLE_HEIGHT = 720  # Standard base cabinet height
    GABLE_THICKNESS = 18  # mm
    BACK_THICKNESS = 6  # mm
    BRACE_HEIGHT = 100  # mm
    
    WIDTH_ADJUSTMENT = 36  # Subtract from width (2 × 18mm gables)
    DEPTH_ADJUSTMENT = 40  # Subtract from depth (back clearance)
    
    END_PANEL_HEIGHT = 900  # Includes toe kick
    
    def __init__(self):
        pass
    
    def calculate_components(self, section: Dict) -> List[Dict]:
        """
        Calculate all components for a cabinet section
        
        Args:
            section: Dict with:
                - width_mm: int
                - depth_mm: int
                - cabinet_type: str
                - shelves: int
                - drawers: int
                - index: int
                
        Returns:
            List of component dicts
        """
        
        width = section['width_mm']
        depth = section.get('depth_mm', 560)
        cabinet_type = section.get('cabinet_type', 'straight')
        shelves = section.get('shelves', 1)
        index = section.get('index', 1)
        
        logger.info(f"⚙️ Calculating components for section {index}: "
                   f"{width}mm × {depth}mm, type: {cabinet_type}")
        
        components = []
        
        # Route to appropriate calculator based on type
        if cabinet_type == 'filler':
            components = self._calculate_filler_components(width, depth, index)
        elif cabinet_type == 'corner':
            components = self._calculate_corner_components(width, depth, shelves, index)
        elif cabinet_type == 'drawer':
            components = self._calculate_drawer_components(width, depth, section.get('drawers', 3), index)
        else:  # straight
            components = self._calculate_straight_components(width, depth, shelves, index)
        
        logger.info(f"   ✓ Generated {len(components)} components")
        
        return components
    
    def _calculate_straight_components(self, width: int, depth: int, 
                                      shelves: int, index: int) -> List[Dict]:
        """Calculate components for standard straight cabinet"""
        
        internal_width = width - self.WIDTH_ADJUSTMENT
        internal_depth = depth - self.DEPTH_ADJUSTMENT
        
        components = []
        
        # GABLES (2 per cabinet)
        components.append({
            'component_type': 'GABLE',
            'part_name': f'Side Panel (Section {index})',
            'section_index': index,
            'unit_width': width,
            'width': depth,  # ← CRITICAL: Gable width = cabinet depth
            'height': self.GABLE_HEIGHT,
            'depth': None,
            'quantity': 2,
            'thickness': self.GABLE_THICKNESS,
            'edge_banding': 'Front + Top/Bottom'
        })
        
        # BASE (always 1)
        components.append({
            'component_type': 'S/H',
            'part_name': f'Base Panel (Section {index})',
            'section_index': index,
            'unit_width': width,
            'width': internal_width,
            'height': None,
            'depth': internal_depth,
            'quantity': 1,
            'thickness': self.GABLE_THICKNESS,
            'edge_banding': 'Front only'
        })
        
        # SHELVES (variable)
        for i in range(shelves):
            components.append({
                'component_type': 'S/H',
                'part_name': f'Shelf {i+1} (Section {index})',
                'section_index': index,
                'unit_width': width,
                'width': internal_width,
                'height': None,
                'depth': internal_depth,
                'quantity': 1,
                'thickness': self.GABLE_THICKNESS,
                'edge_banding': 'Front only'
            })
        
        # BACK (1 per cabinet, may need splitting if wide)
        if internal_width > 900:
            # Split into multiple panels
            num_panels = (internal_width // 900) + 1
            panel_width = internal_width // num_panels
            
            for i in range(num_panels):
                components.append({
                    'component_type': 'BACKS',
                    'part_name': f'Back Panel {i+1} (Section {index})',
                    'section_index': index,
                    'unit_width': width,
                    'width': panel_width,
                    'height': self.GABLE_HEIGHT,
                    'depth': None,
                    'quantity': 1,
                    'thickness': self.BACK_THICKNESS,
                    'edge_banding': 'None'
                })
        else:
            components.append({
                'component_type': 'BACKS',
                'part_name': f'Back Panel (Section {index})',
                'section_index': index,
                'unit_width': width,
                'width': internal_width,
                'height': self.GABLE_HEIGHT,
                'depth': None,
                'quantity': 1,
                'thickness': self.BACK_THICKNESS,
                'edge_banding': 'None'
            })
        
        # BRACES (2 per cabinet)
        components.append({
            'component_type': 'BRACES',
            'part_name': f'Top Rail (Section {index})',
            'section_index': index,
            'unit_width': width,
            'width': internal_width,
            'height': self.BRACE_HEIGHT,
            'depth': None,
            'quantity': 2,
            'thickness': self.GABLE_THICKNESS,
            'edge_banding': 'None'
        })
        
        return components
    
    def _calculate_corner_components(self, width: int, depth: int, 
                                    shelves: int, index: int) -> List[Dict]:
        """Calculate components for L-corner cabinet"""
        
        # Corner cabinets often have multiple depths
        # For now, treat similarly to straight but note it's a corner
        
        components = self._calculate_straight_components(width, depth, shelves, index)
        
        # Add T/B panels for corner stability
        internal_width = width - self.WIDTH_ADJUSTMENT
        internal_depth = depth - self.DEPTH_ADJUSTMENT
        
        components.append({
            'component_type': 'T/B',
            'part_name': f'Top Panel (Corner, Section {index})',
            'section_index': index,
            'unit_width': width,
            'width': internal_width,
            'height': None,
            'depth': internal_depth,
            'quantity': 1,
            'thickness': self.GABLE_THICKNESS,
            'edge_banding': 'Front only'
        })
        
        components.append({
            'component_type': 'T/B',
            'part_name': f'Bottom Panel (Corner, Section {index})',
            'section_index': index,
            'unit_width': width,
            'width': internal_width,
            'height': None,
            'depth': internal_depth,
            'quantity': 1,
            'thickness': self.GABLE_THICKNESS,
            'edge_banding': 'Front only'
        })
        
        return components
    
    def _calculate_drawer_components(self, width: int, depth: int, 
                                    num_drawers: int, index: int) -> List[Dict]:
        """Calculate components for drawer unit"""
        
        # Base components
        components = self._calculate_straight_components(width, depth, 0, index)
        
        # Add drawer dividers
        internal_width = width - self.WIDTH_ADJUSTMENT
        internal_depth = depth - self.DEPTH_ADJUSTMENT
        
        for i in range(num_drawers - 1):  # Dividers between drawers
            components.append({
                'component_type': 'S/H',
                'part_name': f'Drawer Divider {i+1} (Section {index})',
                'section_index': index,
                'unit_width': width,
                'width': internal_width,
                'height': None,
                'depth': internal_depth,
                'quantity': 1,
                'thickness': self.GABLE_THICKNESS,
                'edge_banding': 'Front only'
            })
        
        # Add drawer faces (simplified - actual drawers need more detail)
        drawer_height = (self.GABLE_HEIGHT - (num_drawers - 1) * 18) // num_drawers
        
        for i in range(num_drawers):
            components.append({
                'component_type': 'DRAWER_FACES',
                'part_name': f'Drawer Face {i+1} (Section {index})',
                'section_index': index,
                'unit_width': width,
                'width': width - 4,  # 2mm gap each side
                'height': drawer_height - 4,  # 2mm gap top/bottom
                'depth': None,
                'quantity': 1,
                'thickness': self.GABLE_THICKNESS,
                'edge_banding': 'All edges'
            })
        
        return components
    
    def _calculate_filler_components(self, width: int, depth: int, index: int) -> List[Dict]:
        """Calculate components for filler panel"""
        
        # Fillers are usually just end panels or infills
        return [{
            'component_type': 'END_PANEL',
            'part_name': f'Filler Panel (Section {index})',
            'section_index': index,
            'unit_width': width,
            'width': depth,
            'height': self.END_PANEL_HEIGHT,
            'depth': None,
            'quantity': 1,
            'thickness': self.GABLE_THICKNESS,
            'edge_banding': 'All visible edges'
        }]
    
    def add_end_panels(self, all_components: List[Dict], 
                      total_sections: int) -> List[Dict]:
        """
        Add end panels for first and last sections
        
        Args:
            all_components: Existing components
            total_sections: Total number of cabinet sections
            
        Returns:
            Components with end panels added
        """
        
        # Find first and last sections
        first_section = None
        last_section = None
        
        for comp in all_components:
            if comp.get('section_index') == 1 and comp['component_type'] == 'GABLE':
                first_section = comp
            if comp.get('section_index') == total_sections and comp['component_type'] == 'GABLE':
                last_section = comp
        
        if first_section:
            all_components.append({
                'component_type': 'END_PANEL',
                'part_name': 'End Panel (Left)',
                'section_index': 1,
                'unit_width': None,
                'width': first_section['width'],  # Depth of first cabinet
                'height': self.END_PANEL_HEIGHT,
                'depth': None,
                'quantity': 1,
                'thickness': self.GABLE_THICKNESS,
                'edge_banding': 'All visible edges'
            })
        
        if last_section:
            all_components.append({
                'component_type': 'END_PANEL',
                'part_name': 'End Panel (Right)',
                'section_index': total_sections,
                'unit_width': None,
                'width': last_section['width'],  # Depth of last cabinet
                'height': self.END_PANEL_HEIGHT,
                'depth': None,
                'quantity': 1,
                'thickness': self.GABLE_THICKNESS,
                'edge_banding': 'All visible edges'
            })
        
        return all_components