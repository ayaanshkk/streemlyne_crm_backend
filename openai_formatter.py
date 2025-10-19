def structure_data_with_openai(raw_text):
    """
    Use OpenAI API to structure raw text into predefined form columns
    ROBUST handling for blank forms with printed checkmarks
    """
    try:
        print(f"Processing text of length: {len(raw_text)}")
        print(f"Text preview: {raw_text[:300]}...")
        
        # Create the prompt with specific column names
        column_list = ", ".join(FORM_COLUMNS)
        
        prompt = f"""
        Extract data from this bedroom checklist form. Return ONLY valid JSON.

        IMPORTANT: This appears to be a blank form template. All checkmarks (✓) are printed template elements, NOT user selections.

        Rules:
        1. Extract handwritten text for customer info and specifications
        2. Set ALL checkbox fields to null (no user has made selections)
        3. Return only JSON, no explanations

        Fields to extract:
        {column_list}

        Raw text:
        {raw_text}
        """

        # Make API call to OpenAI
        print("Sending request to OpenAI...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": "Extract form data to JSON. This is a blank template - all checkmarks are printed elements, not user input. Set all boolean/checkbox fields to null."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.0,
            max_tokens=1500
        )

        reply = response.choices[0].message.content.strip()
        print(f"OpenAI response: {reply}")
        
        # Clean up the response
        if reply.startswith('```json'):
            reply = reply[7:]
        if reply.endswith('```'):
            reply = reply[:-3]
        reply = reply.strip()

        try:
            structured_data = json.loads(reply)
            print("✓ JSON parsed successfully")
            
            # DEFINITIVE list of checkbox fields that MUST be null for blank forms
            checkbox_fields = [
                'bedside_cabinets_floating', 'bedside_cabinets_fitted', 'bedside_cabinets_freestand',
                'dresser_desk_yes', 'dresser_desk_no', 'internal_mirror_yes', 'internal_mirror_no',
                'mirror_silver', 'mirror_bronze', 'mirror_grey', 'soffit_lights_spot', 'soffit_lights_strip',
                'soffit_lights_cool_white', 'soffit_lights_warm_white', 'gable_lights_black', 'gable_lights_white',
                'carpet_protection', 'floor_tile_protection', 'no_floor'
            ]
            
            # Template labels that should be null
            template_labels = ['QTY', 'SIZE', 'CODE/QTY/SIZE', 'QTY/SIZE', 'COLOUR:', 'PROFILE COLOUR:', 'DATE:', 'Please sign here to confirm.']
            
            print("🔧 Starting post-processing...")
            final_data = {}
            
            for column in FORM_COLUMNS:
                value = structured_data.get(column, None)
                
                if column in checkbox_fields:
                    # FORCE all checkbox fields to null
                    if value is not None:
                        print(f"  🚫 FORCING {column}: '{value}' → null")
                    final_data[column] = None
                else:
                    # Handle text fields
                    if value and isinstance(value, str):
                        # Check if it's a template label
                        if value.strip().upper() in template_labels:
                            print(f"  🏷️  Template label {column}: '{value}' → null")
                            final_data[column] = None
                        else:
                            final_data[column] = value.strip()
                    else:
                        final_data[column] = value
            
            print("\n📋 Final processed data (non-null values only):")
            for k, v in final_data.items():
                if v is not None:
                    print(f"  ✓ {k}: {v}")
            
            print(f"\n📊 Summary: {sum(1 for v in final_data.values() if v is not None)} fields with data, {sum(1 for v in final_data.values() if v is None)} fields null")
            
            # Store the latest structured data
            global latest_structured_data
            latest_structured_data = final_data
            
            return final_data
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {e}")
            print(f"Raw response: {reply}")
            return {
                "error": "Failed to parse JSON response",
                "raw_response": reply,
                "json_error": str(e)
            }
            
    except Exception as e:
        print(f"❌ OpenAI API error: {str(e)}")
        return {
            "error": f"OpenAI API error: {str(e)}",
            "raw_text": raw_text[:500]
        }