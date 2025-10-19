import os
from google.cloud import vision
import io
import re

def extract_text_from_image(image_path):
    """
    Extract text from an image using Google Cloud Vision API
    
    Args:
        image_path (str): Path to the image file
        
    Returns:
        str: Extracted text from the image
    """
    try:
        # Initialize the Vision API client
        client = vision.ImageAnnotatorClient()
        
        # Read the image file
        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()
        
        # Create image object
        image = vision.Image(content=content)
        
        # Perform text detection
        response = client.text_detection(image=image)
        
        # Check for errors
        if response.error.message:
            raise Exception(f'Vision API error: {response.error.message}')
        
        # Extract text annotations
        texts = response.text_annotations
        
        if texts:
            # Return the full text description (first annotation contains all text)
            return texts[0].description
        else:
            return ""
            
    except Exception as e:
        print(f"Error in text extraction: {str(e)}")
        raise e

def extract_form_data_from_image(image_path):
    """
    Extract structured form data from image with conservative checkbox handling
    
    Args:
        image_path (str): Path to the image file
        
    Returns:
        dict: Structured form data with checkboxes defaulted to False
    """
    try:
        # Get the raw text from the image
        extracted_text = extract_text_from_image(image_path)
        
        # Initialize structured data with ALL checkboxes as False
        structured_data = initialize_form_fields()
        
        # Extract text fields only (not checkboxes)
        structured_data.update(extract_text_fields_from_text(extracted_text))
        
        # Debug logging
        print("=== VISION.PY DEBUG ===")
        print(f"Raw extracted text: {extracted_text[:500]}...")
        print("Checkbox detection DISABLED to prevent false positives from printed form elements")
        print(f"All checkboxes set to False by default")
        print("=== END DEBUG ===")
        
        return structured_data
        
    except Exception as e:
        print(f"Error in form data extraction: {str(e)}")
        raise e

def initialize_form_fields():
    """
    Initialize all form fields with default values
    CRITICAL: All checkboxes default to False to prevent false positives
    """
    return {
        # Customer Information
        "customer_name": "",
        "address": "",
        "room": "",
        "tel_mob_number": "",
        
        # Important Dates
        "survey_date": "",
        "appt_date": "",
        "pro_inst_date": "",
        "comp_chk_date": "",
        "date_deposit_paid": "",
        
        # Style & Colors
        "fitting_style": "",
        "door_style": "",
        "door_colour": "",
        "end_panel_colour": "",
        "plinth_filler_colour": "",
        "worktop_colour": "",
        "cabinet_colour": "",
        "handles_code_qty_size": "",
        
        # Bedside Cabinets - ALL FALSE by default
        "bedside_cabinets_floating": False,
        "bedside_cabinets_fitted": False,
        "bedside_cabinets_freestand": False,
        "bedside_cabinets_qty": "",
        
        # Dresser/Desk - ALL FALSE by default
        "dresser_desk_yes": False,
        "dresser_desk_no": False,
        "dresser_desk_qty_size": "",
        
        # Internal Mirror - ALL FALSE by default
        "internal_mirror_yes": False,
        "internal_mirror_no": False,
        "internal_mirror_qty_size": "",
        
        # Mirror Options - ALL FALSE by default
        "mirror_silver": False,
        "mirror_bronze": False,
        "mirror_grey": False,
        "mirror_qty": "",
        
        # Soffit Lights - ALL FALSE by default
        "soffit_lights_spot": False,
        "soffit_lights_strip": False,
        "soffit_lights_colour": "",
        "soffit_lights_cool_white": False,
        "soffit_lights_warm_white": False,
        "soffit_lights_qty": "",
        
        # Gable Lights - ALL FALSE by default
        "gable_lights_colour": "",
        "gable_lights_profile_colour": "",
        "gable_lights_black": False,
        "gable_lights_white": False,
        "gable_lights_qty": "",
        
        # Accessories - ALL FALSE by default
        "carpet_protection": False,
        "floor_tile_protection": False,
        "no_floor": False,
        
        # Terms & Signature
        "date_terms_conditions_given": "",
        "gas_electric_installation_terms_given": "",
        "customer_signature": "",
        "signature_date": "",
    }

def extract_text_fields_from_text(extracted_text):
    """
    Extract text field values from the OCR text
    This function ONLY extracts text, NOT checkboxes
    """
    text_fields = {}
    
    # Define patterns for text fields (not checkboxes!)
    patterns = {
        'customer_name': [
            r'Customer Name[:\s]+([^\n\r]+)',
            r'Name[:\s]+([^\n\r]+)',
        ],
        'address': [
            r'Address[:\s]+([^\n\r]+)',
            r'Customer Address[:\s]+([^\n\r]+)',
        ],
        'room': [
            r'Room[:\s]+([^\n\r]+)',
        ],
        'tel_mob_number': [
            r'Tel[/\s]*Mob[:\s]+([^\n\r]+)',
            r'Phone[:\s]+([^\n\r]+)',
            r'Mobile[:\s]+([^\n\r]+)',
        ],
        'survey_date': [
            r'Survey Date[:\s]+([^\n\r]+)',
        ],
        'appt_date': [
            r'Appt Date[:\s]+([^\n\r]+)',
            r'Appointment Date[:\s]+([^\n\r]+)',
        ],
        'pro_inst_date': [
            r'Pro Inst Date[:\s]+([^\n\r]+)',
            r'Installation Date[:\s]+([^\n\r]+)',
        ],
        'comp_chk_date': [
            r'Comp Chk Date[:\s]+([^\n\r]+)',
            r'Completion Date[:\s]+([^\n\r]+)',
        ],
        'date_deposit_paid': [
            r'Date Deposit Paid[:\s]+([^\n\r]+)',
        ],
        'fitting_style': [
            r'Fitting Style[:\s]+([^\n\r]+)',
        ],
        'door_style': [
            r'Door Style[:\s]+([^\n\r]+)',
        ],
        'door_colour': [
            r'Door Colour[:\s]+([^\n\r]+)',
        ],
        'end_panel_colour': [
            r'End Panel Colour[:\s]+([^\n\r]+)',
        ],
        'plinth_filler_colour': [
            r'Plinth[/\s]*Filler Colour[:\s]+([^\n\r]+)',
        ],
        'worktop_colour': [
            r'Worktop Colour[:\s]+([^\n\r]+)',
        ],
        'cabinet_colour': [
            r'Cabinet Colour[:\s]+([^\n\r]+)',
        ],
        'handles_code_qty_size': [
            r'Handles Code[/\s]*Qty[/\s]*Size[:\s]+([^\n\r]+)',
        ],
    }
    
    # Extract text fields using patterns
    for field_name, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, extracted_text, re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if value and value != "":  # Only set if we found a non-empty value
                    text_fields[field_name] = value
                    break  # Stop at first match for this field
    
    return text_fields

def detect_filled_checkboxes_conservative(image_path, extracted_text):
    """
    DISABLED: Very conservative checkbox detection
    This is disabled because printed form checkmarks cause too many false positives
    
    To re-enable checkbox detection in the future, you would need:
    1. Computer vision to detect the difference between printed and hand-drawn marks
    2. Analysis of checkbox fill patterns (solid fill vs outline)
    3. Detection of handwritten X marks or other clear user indicators
    
    For now, all checkboxes default to False unless manually overridden
    """
    checkbox_updates = {}
    
    # Completely disabled to prevent false positives
    print("Checkbox detection is disabled to prevent false positives from printed form elements")
    
    return checkbox_updates

def enable_manual_checkbox_detection(structured_data, manual_overrides):
    """
    Manually set specific checkboxes to True
    Use this function when you know certain checkboxes should be checked
    
    Args:
        structured_data (dict): The form data
        manual_overrides (dict): Dictionary of field_name: True/False overrides
    
    Returns:
        dict: Updated structured data
    """
    for field_name, value in manual_overrides.items():
        if field_name in structured_data and isinstance(structured_data[field_name], bool):
            structured_data[field_name] = value
            print(f"Manual override: {field_name} = {value}")
    
    return structured_data

def detect_handwritten_marks(extracted_text):
    """
    Look for text patterns that might indicate manually marked checkboxes
    This is very conservative and only looks for clear indicators
    """
    marks = {}
        
    lines = extracted_text.split('\n')
    
    checkbox_fields = {
        'SILVER': 'mirror_silver',
        'BRONZE': 'mirror_bronze', 
        'GREY': 'mirror_grey',
        'SPOT': 'soffit_lights_spot',
        'STRIP': 'soffit_lights_strip',
        'COOL WHITE': 'soffit_lights_cool_white',
        'WARM WHITE': 'soffit_lights_warm_white',
        'BLACK': 'gable_lights_black',
        'WHITE': 'gable_lights_white',
        'CARPET PROTECTION': 'carpet_protection',
        'FLOOR TILE PROTECTION': 'floor_tile_protection',
        'NO FLOOR': 'no_floor',
    }
    
    for line in lines:
        line = line.strip().upper()
        
        # Look for very specific patterns that indicate manual marking
        # This is intentionally very restrictive to avoid false positives
        for field_text, field_name in checkbox_fields.items():
            # Only match if there's a clear X or handwritten mark at the beginning of the line
            if re.match(r'^[X×]\s+' + re.escape(field_text), line):
                marks[field_name] = True
                print(f"Found handwritten mark for {field_name}: {line}")
    
    return marks

def detect_checkbox_symbols(image_path):
    """
    DEPRECATED: This function was causing false positives
    The form has printed checkmarks that were being detected as user input
    """
    # This function is disabled to prevent false positives
    return {}

def get_text_position(annotation):
    """
    Get the center position of a text annotation
    """
    vertices = annotation.bounding_poly.vertices
    center_x = sum(vertex.x for vertex in vertices) / len(vertices)
    center_y = sum(vertex.y for vertex in vertices) / len(vertices)
    return (center_x, center_y)

def find_closest_field_to_symbol(symbol_pos, text_annotations, field_mapping):
    """
    Find the closest field label to a checkbox symbol
    """
    closest_field = None
    min_distance = float('inf')
    max_distance = 100  # Maximum distance to consider
    
    symbol_x, symbol_y = symbol_pos
    
    for annotation in text_annotations:
        text = annotation.description.strip().upper()
        
        # Check if this text matches any of our field labels
        if text in field_mapping:
            label_pos = get_text_position(annotation)
            label_x, label_y = label_pos
            
            # Calculate distance
            distance = ((symbol_x - label_x) ** 2 + (symbol_y - label_y) ** 2) ** 0.5
            
            # Only consider if it's close enough and closer than previous matches
            if distance < max_distance and distance < min_distance:
                min_distance = distance
                closest_field = field_mapping[text]
    
    return closest_field

# Backward compatibility - keep your original function
def extract_text_from_image_legacy(image_path):
    """
    Legacy function for backward compatibility
    """
    return extract_text_from_image(image_path)