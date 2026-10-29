"""
Test Grading Routes for StreemLyne CRM
Using Claude (Anthropic API) for vision-based answer extraction
Claude is more accurate at spatial reasoning and following detailed instructions
"""

import json
import base64
import re
import traceback
import os
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from sqlalchemy import text
from typing import Dict
import anthropic
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter
import io

from .auth_helpers import token_required   # shared decorator
from ..db import SessionLocal

test_grading_bp = Blueprint("test_grading", __name__, url_prefix="/test-grading")

# Initialize Anthropic client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ==================== CONSTANTS ====================
CONTACT_METHOD_TEST_RESULT = 5  # Valid Contact_Method_Master value: Other
SCHEMA = "streemLyne_mt_dev2"
TEST_RESULT_MARKER = '%"record_type": "test_result"%'

# Answer keys - CORRECTED
ANSWER_KEYS = {
    "BOPT": {
        "total_questions": 20,
        "format": "standard",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE",  "7": "TRUE",  "8": "FALSE", "9": "TRUE",  "10": "TRUE",
            "11": "TRUE", "12": "FALSE", "13": "FALSE", "14": "FALSE", "15": "FALSE",
            "16": "TRUE","17": "FALSE", "18": "TRUE", "19": "TRUE", "20": "FALSE"
        }
    },
    "REACH_TRUCK": {
        "total_questions": 24,
        "format": "standard",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE",  "7": "TRUE",  "8": "TRUE",  "9": "TRUE",  "10": "FALSE",
            "11": "TRUE", "12": "FALSE", "13": "FALSE", "14": "FALSE", "15": "FALSE",
            "16": "TRUE", "17": "TRUE", "18": "FALSE", "19": "TRUE", "20": "TRUE",
            "21": "FALSE", "22": "FALSE","23": "TRUE", "24": "TRUE"
        }
    },
    "FORKLIFT": {
        "total_questions": 24,
        "format": "special",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE",  "7": "TRUE",  "8": "TRUE",  "9": "TRUE",  "10": "TRUE",
            "11": "FALSE",  "12": "FALSE", "13": "FALSE",  "14": "FALSE","15": "FALSE",
            "16": "TRUE","17": "FALSE", "18": "TRUE","19": "FALSE", "20": "TRUE",
            "21": "FALSE","22": "TRUE", "23": "FALSE", "24": "BALANCE"
        }
    },
    "STACKER": {
        "total_questions": 24,
        "format": "standard",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE",  "7": "TRUE",  "8": "FALSE",  "9": "TRUE",  "10": "FALSE",
            "11": "TRUE","12": "TRUE","13": "TRUE","14": "FALSE","15": "TRUE",
            "16": "FALSE","17": "FALSE", "18": "FALSE", "19": "FALSE","20": "TRUE",
            "21": "TRUE", "22": "FALSE", "23": "TRUE","24": "TRUE"
        }
    },
        "TOW TRUCK": {
            "total_questions": 24,
            "format": "special",
            "answers": {
                "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
                "6": "TRUE",  "7": "TRUE",  "8": "TRUE",  "9": "TRUE",  "10": "TRUE",
                "11": "FALSE",  "12": "FALSE", "13": "FALSE",  "14": "FALSE","15": "FALSE",
                "16": "TRUE","17": "FALSE", "18": "TRUE","19": "FALSE", "20": "TRUE",
                "21": "FALSE","22": "TRUE", "23": "FALSE", "24": "BALANCE"
            }

    },
            "VNA": {
                "total_questions": 24,
                "format": "special",
                "answers": {
                    "1": "FALSE", "2": "FALSE", "3": "TRUE", "4": "TRUE", "5": "FALSE",
                    "6": "TRUE",  "7": "TRUE",  "8": "FALSE",  "9": "TRUE",  "10": "TRUE",
                    "11": "FALSE",  "12": "TRUE", "13": "FALSE",  "14": "FALSE","15": "FALSE",
                    "16": "TRUE","17": "TRUE", "18": "TRUE","19": "FALSE", "20": "TRUE",
                    "21": "TRUE","22": "FALSE", "23": "FALSE", "24": "TRUE"
                }
            
    }
}


# ─────────────────────────────────────────────
# META HELPERS
# ─────────────────────────────────────────────

def pack_meta(meta: dict) -> str:
    return f"__meta__{json.dumps(meta)}__end_meta__"


def unpack_meta(notes: str) -> dict:
    if not notes or '__meta__' not in notes:
        return {}
    try:
        meta_str = notes.split('__meta__')[1].split('__end_meta__')[0]
        return json.loads(meta_str)
    except Exception:
        return {}


def serialize_result(row) -> dict:
    """Convert a Client_Interactions test result row to the frontend dict."""
    meta = unpack_meta(row.notes)
    return {
        "id":                   row.interaction_id,
        "participant_name":     meta.get('participant_name', 'Unknown'),
        "company":              meta.get('company', 'Unknown'),
        "date":                 meta.get('date', 'Unknown'),
        "place":                meta.get('place', 'Unknown'),
        "test_type":            meta.get('test_type', 'Unknown'),
        "mhe_type":             meta.get('mhe_type', 'Unknown'),
        "answers":              meta.get('answers', {}),
        "total_marks_obtained": meta.get('total_marks_obtained', 0),
        "total_marks":          meta.get('total_marks', 0),
        "percentage":           meta.get('percentage', 0.0),
        "grade":                meta.get('grade', 'Fail'),
        "details":              meta.get('details', []),
        "image_base64":         meta.get('image_base64', ''),
        "created_at":           row.created_at.isoformat() if row.created_at else None,
        "employee_id":          row.next_steps,   # next_steps holds employee_id
    }


# ─────────────────────────────────────────────
# IMAGE PROCESSING HELPERS
# ─────────────────────────────────────────────

def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        page = pdf[0]
        bitmap = page.render(scale=600/72, rotation=0)
        pil_image = bitmap.to_pil()
        buf = io.BytesIO()
        pil_image.convert('RGB').save(buf, format='JPEG', quality=95, subsampling=0)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        raise Exception(f"PDF conversion error: {str(e)}")


def enhance_image_quality(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        width, height = img.size
        
        # ✅ Cap at 1600px wide, not 2400 — Claude doesn't need more
        MAX_WIDTH = 1600
        if width < MAX_WIDTH:
            scale = MAX_WIDTH / width
            new_w = int(width * scale)
            new_h = int(height * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        elif width > MAX_WIDTH:
            # ✅ Also shrink if already too large
            scale = MAX_WIDTH / width
            new_w = int(width * scale)
            new_h = int(height * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)

        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)

        img = img.filter(ImageFilter.EDGE_ENHANCE)

        buf = io.BytesIO()
        # ✅ Lower quality slightly to reduce payload size
        img.save(buf, format='JPEG', quality=85, subsampling=0)
        buf.seek(0)
        result = buf.read()
        
        # ✅ Log final size so you can monitor it
        current_app.logger.info(f"📸 Enhanced image size: {len(result) / 1024:.1f} KB")
        return result
    except Exception:
        return image_bytes


def process_uploaded_file(file_bytes: bytes, content_type: str) -> bytes:
    if content_type == 'application/pdf':
        return convert_pdf_to_image(file_bytes)
    elif content_type.startswith('image/'):
        return enhance_image_quality(file_bytes)
    raise Exception("Unsupported file type. Only PDF and images are supported.")


# ─────────────────────────────────────────────
# AI EXTRACTION USING CLAUDE
# ─────────────────────────────────────────────

def extract_answers_with_claude(image_bytes: bytes) -> Dict:
    size_kb = len(image_bytes) / 1024
    current_app.logger.info(f"📤 Sending image to Claude: {size_kb:.1f} KB")
    if size_kb > 4000:
        current_app.logger.warning(f"⚠️ Image very large ({size_kb:.1f} KB)")

    base64_image = base64.b64encode(image_bytes).decode('utf-8')

    prompt = """You are reading a test answer sheet from "Forklift Academy of India". The sheet may be in Hindi/Marathi or in English.

## FORM STRUCTURE

The table has these columns (left to right). Hindi/Marathi headers and their English equivalents:
- न. / No. (Question number)
- Question text
- हाँ / True  ← this column header means YES / TRUE
- ना / False  ← this column header means NO / FALSE
- पता नहीं / Don't Know  ← this column header means DON'T KNOW
- टिप्पणी / Remarks (usually blank)

## YOUR TASK

For each question row, find which checkbox column contains a pen mark.

**Mapping rule:**
- Mark is under the "हाँ" / "True" column header → Answer = **TRUE**
- Mark is under the "ना" / "False" column header → Answer = **FALSE**
- Mark is under the "पता नहीं" / "Don't Know" column header → Answer = **Don't Know**
- No visible mark anywhere → Answer = **BLANK**

## HOW TO LOCATE THE MARK

1. Read the column headers at the top
2. Note the x-position of each header on the page
3. For each question row, look along that row for any pen mark (tick ✓, slash /, line, etc.)
4. Determine which column's x-position the mark falls under

**Critical**: Do NOT count boxes from the left edge of the row. Instead, look at which named column the mark is directly below.

## NUMBERING RULE — DO NOT USE THE PRINTED NUMBER

IGNORE the printed number in the left "No." / "न." column when deciding the JSON key. Instead, number every checkbox row by its VERTICAL POSITION in the table: the first row with checkboxes is key "1", the next row down is key "2", and so on — top to bottom, whether or not that row has a printed number next to it.

This matters because some English-language forms (especially the Forklift paper) group several sub-items under a single printed number, like:

    1  Forklift truck can be used:
         - For Outdoor applications
         - As a tow-truck for trailers
         - To tow other trucks
         - To transport / lift passengers
         - For Driving on gravel or grass
    2  While lifting and lowering Load I shall apply Parking Brake
    ...

Each indented sub-item ABOVE has its own checkbox row but NO printed number of its own. Treat each one as a SEPARATE row and give it its own sequential key — so the 5 sub-items become keys "1" through "5" — and then keep counting sequentially for every row after that block, even though the form's own printed numbers continue from "2". By the time you reach the printed "2" row, its JSON key should be "6", not "2". Continue this same top-to-bottom row count all the way to the bottom of the table.

If a form has no such grouped sub-items (every row already has its own printed number, one item per row — this is the normal case for the Hindi/Marathi papers), the row-position count and the printed number will naturally match — just keep counting rows top to bottom either way.

## HEADER INFO TO EXTRACT

From the top of the form extract:
- Participant name (नाम / Name)
- Company name (कंपनी का नाम / Company)
- Date (तारीख / Date)
- Place (पता / Place)
- Whether this is Pre test or Post test

## IMPORTANT — DO NOT STOP AT 20

This form may have MORE than 20 checkbox rows once sub-items are counted individually (see NUMBERING RULE above). Before writing your answer, count the actual number of checkbox rows in the table using the row-position method. Your "answers" object MUST contain exactly one key per row that exists on the sheet — if there are 24 rows, output keys "1" through "24". Never stop at 20 just because the example below shows 20. Missing a row is a critical error.

## OUTPUT FORMAT

Return ONLY valid JSON with no markdown, no code blocks, no explanation text before or after:

{
    "mhe_type": "BOPT or STACKER or REACH_TRUCK or FORKLIFT",
    "participant_name": "name from form",
    "company": "company from form",
    "date": "date from form",
    "place": "place from form",
    "test_type": "Post test or Pre test",
    "total_questions": <count the actual checkbox rows, using the row-position method>,
    "answers": {
        "1": "TRUE or FALSE or Don't Know or BLANK",
        "2": "TRUE or FALSE or Don't Know or BLANK",
        "3": "TRUE or FALSE or Don't Know or BLANK",
        "4": "TRUE or FALSE or Don't Know or BLANK",
        "5": "TRUE or FALSE or Don't Know or BLANK",
        "6": "TRUE or FALSE or Don't Know or BLANK",
        "7": "TRUE or FALSE or Don't Know or BLANK",
        "8": "TRUE or FALSE or Don't Know or BLANK",
        "9": "TRUE or FALSE or Don't Know or BLANK",
        "10": "TRUE or FALSE or Don't Know or BLANK",
        "11": "TRUE or FALSE or Don't Know or BLANK",
        "12": "TRUE or FALSE or Don't Know or BLANK",
        "13": "TRUE or FALSE or Don't Know or BLANK",
        "14": "TRUE or FALSE or Don't Know or BLANK",
        "15": "TRUE or FALSE or Don't Know or BLANK",
        "16": "TRUE or FALSE or Don't Know or BLANK",
        "17": "TRUE or FALSE or Don't Know or BLANK",
        "18": "TRUE or FALSE or Don't Know or BLANK",
        "19": "TRUE or FALSE or Don't Know or BLANK",
        "20": "TRUE or FALSE or Don't Know or BLANK",
        "21": "TRUE or FALSE or Don't Know or BLANK",
        "22": "TRUE or FALSE or Don't Know or BLANK",
        "23": "TRUE or FALSE or Don't Know or BLANK",
        "24": "TRUE or FALSE or Don't Know or BLANK"
    }
}

If the sheet has fewer than 24 questions, only include keys up to the actual last row number — do not invent extra rows."""

    retry_prompt = """Re-examine the test sheet. Return ONLY a JSON object — no explanation text before or after it.

Remember the NUMBERING RULE: number checkbox rows by their top-to-bottom VERTICAL POSITION in the table, NOT by the printed number in the "No." column. If Question 1 has several indented, unnumbered sub-items (each with its own checkboxes — common on the English Forklift form), each sub-item is its own row and gets its own sequential key (e.g. the 5 sub-items become keys "1" to "5"), and the row printed as "2" on the form then becomes key "6", and so on. Keep counting every checkbox row top to bottom to the end of the table.

The answers field MUST be a flat object with string keys like this:
{"1": "FALSE", "2": "TRUE", ...}

NOT a list. NOT nested objects.

Return ONLY valid JSON starting with { and ending with }:

{
    "mhe_type": "BOPT or STACKER or REACH_TRUCK or FORKLIFT",
    "participant_name": "...",
    "company": "...",
    "date": "...",
    "place": "...",
    "test_type": "Pre test or Post test",
    "total_questions": <count the actual rows using the row-position method>,
    "answers": {
        "1": "TRUE or FALSE or Don't Know or BLANK",
        "2": "TRUE or FALSE or Don't Know or BLANK",
        ...continue for every row on the sheet, up to "24" if there are 24 questions. Do not stop at 20.
    }
}"""

    max_retries = 2

    for attempt in range(max_retries):
        try:
            current_prompt = prompt if attempt == 0 else retry_prompt
            current_app.logger.info(f"🔄 Extraction attempt {attempt + 1}/{max_retries}")

            message = anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": base64_image,
                                },
                            },
                            {
                                "type": "text",
                                "text": current_prompt
                            }
                        ],
                    }
                ],
            )

            # ── debug: log everything about the response ──────────────────
            current_app.logger.info(f"STOP REASON: {message.stop_reason}")
            current_app.logger.info(f"CONTENT BLOCKS: {len(message.content)}")
            for i, block in enumerate(message.content):
                block_text = getattr(block, 'text', '') or ''
                current_app.logger.info(f"BLOCK {i}: type={block.type} text_len={len(block_text)} preview={repr(block_text[:300])}")
            # ─────────────────────────────────────────────────────────────

            if not message.content:
                current_app.logger.error(f"❌ Empty content list. Stop reason: {message.stop_reason}")
                continue

            block_text = getattr(message.content[0], 'text', '') or ''

            if not block_text.strip():
                current_app.logger.error(f"❌ First content block is empty. Stop: {message.stop_reason}")
                continue

            result_text = block_text.strip()

            # Extract JSON object — strip any preamble/postamble Claude adds
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if not json_match:
                current_app.logger.error(f"❌ No JSON object found in response")
                current_app.logger.error(f"❌ Full response: {repr(result_text[:500])}")
                continue

            result_text = json_match.group(0).strip()
            current_app.logger.info(f"RAW JSON EXTRACTED (first 300):\n{result_text[:300]}")

            extracted_data = json.loads(result_text)

            # Normalise answers if Claude returned a list instead of a dict
            answers_raw = extracted_data.get("answers", {})
            if isinstance(answers_raw, list):
                extracted_data["answers"] = {
                    str(item.get("q", i + 1)): item.get("answer", "BLANK")
                    for i, item in enumerate(answers_raw)
                }
                current_app.logger.warning("⚠️ Normalised list-format answers to dict")

            answers = extracted_data.get("answers", {})
            true_count  = sum(1 for v in answers.values() if v == 'TRUE')
            false_count = sum(1 for v in answers.values() if v == 'FALSE')
            dk_count    = sum(1 for v in answers.values() if v == "Don't Know")
            blank_count = sum(1 for v in answers.values() if v == 'BLANK')

            current_app.logger.info(
                f"✅ Extracted {len(answers)} answers — "
                f"TRUE:{true_count} FALSE:{false_count} DK:{dk_count} BLANK:{blank_count}"
            )

            # Retry if suspiciously uniform (all same value)
            all_same = (
                (false_count == len(answers)) or
                (true_count  == len(answers)) or
                (dk_count    == len(answers))
            )
            if all_same and len(answers) >= 18 and attempt < max_retries - 1:
                current_app.logger.warning("⚠️ All answers identical — retrying")
                continue

            return extracted_data

        except json.JSONDecodeError as e:
            current_app.logger.error(f"❌ JSON parse failed on attempt {attempt + 1}: {e}")
            current_app.logger.error(f"❌ result_text was: {repr(result_text) if 'result_text' in locals() else 'NOT SET'}")
            if attempt == max_retries - 1:
                raise Exception(f"Claude Vision error after {max_retries} attempts: {str(e)}")

        except Exception as e:
            current_app.logger.error(f"❌ Attempt {attempt + 1} failed: {e}", exc_info=True)
            if attempt == max_retries - 1:
                raise Exception(f"Claude Vision error after {max_retries} attempts: {str(e)}")

    raise Exception("Extraction failed after all retries")

# ─────────────────────────────────────────────
# GRADING ENGINE
# ─────────────────────────────────────────────

def normalize_mhe_type(value) -> str:
    """Map any MHE name (MHE_Master: 'Towtruck', 'Reach Truck', 'VNA' ...) to an
    ANSWER_KEYS key. Unknown or empty values fall back to BOPT."""
    key = re.sub(r"[^A-Z]", "", str(value or "").upper())
    if "REACH" in key:
        return "REACH_TRUCK"
    if "FORK" in key:
        return "FORKLIFT"
    if "STACKER" in key:
        return "STACKER"
    if "TOW" in key:
        return "TOW TRUCK"
    if "VNA" in key or "NARROW" in key:
        return "VNA"
    return "BOPT"
def grade_test_internal(extracted_data: Dict) -> Dict:
    mhe_type = normalize_mhe_type(extracted_data.get("mhe_type", "BOPT"))

    if mhe_type not in ANSWER_KEYS:
        raise Exception(f"Unknown MHE type: {mhe_type}")

    answer_key_data = ANSWER_KEYS[mhe_type]
    answer_key      = answer_key_data["answers"]
    total_questions = answer_key_data["total_questions"]
    answers         = extracted_data.get("answers", {})

    details              = []
    total_marks_obtained = 0

    for question_key, correct_answer in answer_key.items():
        student_answer = answers.get(question_key, "BLANK")
        is_correct     = (
            student_answer.upper().strip() == correct_answer.upper().strip()
            if correct_answer.isalpha() and len(correct_answer) > 4
            else student_answer == correct_answer
        )
        if is_correct:
            total_marks_obtained += 1
        details.append({
            "question_number": question_key,
            "student_answer":  student_answer,
            "correct_answer":  correct_answer,
            "is_correct":      is_correct,
            "remark":          "Correct" if is_correct else "Wrong",
            "marks_obtained":  1 if is_correct else 0
        })

    percentage = (total_marks_obtained / total_questions) * 100

    return {
        "participant_name":     extracted_data.get("participant_name", "Unknown"),
        "company":              extracted_data.get("company", "Unknown"),
        "date":                 extracted_data.get("date", "Unknown"),
        "place":                extracted_data.get("place", "Unknown"),
        "test_type":            extracted_data.get("test_type", "Unknown"),
        "mhe_type":             mhe_type,
        "answers":              answers,
        "total_marks_obtained": total_marks_obtained,
        "total_marks":          total_questions,
        "percentage":           round(percentage, 2),
        "grade":                "Pass" if percentage >= 70 else "Fail",
        "details":              details
    }


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /api/test-grading/health
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status":        "healthy",
        "message":       "Test grading system is running (Claude-powered)",
        "supported_mhe": list(ANSWER_KEYS.keys()),
        "ai_model":      "Claude Sonnet 4"
    }), 200


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /api/test-grading/answer-keys
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/answer-keys", methods=["GET"])
@token_required
def get_answer_keys():
    return jsonify({"answer_keys": ANSWER_KEYS}), 200


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /api/test-grading/extract-answers
# Step 1: AI extraction — returns data for manual review, nothing saved yet
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/extract-answers", methods=["POST"])
@token_required
def extract_answers():
    current_app.logger.info("=" * 80)
    current_app.logger.info("🚀 EXTRACT ANSWERS ROUTE CALLED")
    current_app.logger.info("=" * 80)
    
    try:
        current_app.logger.info("📋 Step 1: Checking for file in request...")
        if 'file' not in request.files:
            current_app.logger.error("❌ No file in request.files")
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        current_app.logger.info(f"✅ File found: {file.filename}")
        
        if not file.filename:
            current_app.logger.error("❌ No filename")
            return jsonify({"error": "No file selected"}), 400

        current_app.logger.info(f"📋 File content type: {file.content_type}")
        
        if not (file.content_type.startswith('image/') or file.content_type == 'application/pdf'):
            current_app.logger.error(f"❌ Invalid file type: {file.content_type}")
            return jsonify({"error": "File must be an image or PDF"}), 400

        current_app.logger.info("📋 Step 2: Reading file bytes...")
        file_bytes   = file.read()
        current_app.logger.info(f"✅ Read {len(file_bytes)} bytes")
        
        current_app.logger.info("📋 Step 3: Processing image...")
        image_bytes  = process_uploaded_file(file_bytes, file.content_type)
        current_app.logger.info(f"✅ Processed image: {len(image_bytes)} bytes")
        
        current_app.logger.info("📋 Step 4: Calling Claude Vision API...")
        current_app.logger.info(f"🔍 Extracting answers with Claude Vision API...")
        
        extracted    = extract_answers_with_claude(image_bytes)
        
        current_app.logger.info("📋 Step 5: Encoding image to base64...")
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        current_app.logger.info(f"✅ Base64 encoded: {len(image_base64)} chars")

        current_app.logger.info(f"✅ Extracted {len(extracted.get('answers', {}))} answers for {extracted.get('mhe_type')}")
        
        result = {
            "mhe_type":        extracted.get("mhe_type", "BOPT"),
            "participant_name": extracted.get("participant_name", ""),
            "company":         extracted.get("company", ""),
            "date":            extracted.get("date", ""),
            "place":           extracted.get("place", ""),
            "test_type":       extracted.get("test_type", ""),
            "total_questions": extracted.get("total_questions", 20),
            "answers":         extracted.get("answers", {}),
            "image_base64":    image_base64
        }
        
        current_app.logger.info("📋 Step 6: Returning response...")
        current_app.logger.info(f"✅ Response prepared with {len(result['answers'])} answers")
        current_app.logger.info("=" * 80)
        
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error("=" * 80)
        current_app.logger.error(f"❌ FATAL ERROR in extract_answers route:")
        current_app.logger.exception(e)
        current_app.logger.error("=" * 80)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /api/test-grading/grade-training-paper
# NEW: one-shot auto-grade for a single Training Batch participant's
# pre-test/post-test paper (see page.tsx: runAutoGrade). Unlike
# /grade-with-corrections below, this does NOT write to Client_Interactions
# — a training-record score belongs to one participant's one training
# record inside Training_Details.participants JSON, not to the client-wide
# test-results log that Client_Interactions powers. The frontend takes this
# route's response, lets staff review/correct it (calling /regrade below as
# they edit), then persists the FINAL confirmed result itself via the
# existing PATCH /clients/<id>/training/<id>/participants endpoint in
# customer_routes.py — no new persistence route was needed for that part.
# ═════════════════════════════════════════════════════════════════════════════
@test_grading_bp.route("/grade-training-paper", methods=["POST"])
@token_required
def grade_training_paper():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({"error": "No file selected"}), 400

        if not (file.content_type.startswith('image/') or file.content_type == 'application/pdf'):
            return jsonify({"error": "File must be an image or PDF"}), 400

        file_bytes  = file.read()
        image_bytes = process_uploaded_file(file_bytes, file.content_type)

        current_app.logger.info("🔍 Auto-grading training paper with Claude Vision...")
        extracted = extract_answers_with_claude(image_bytes)

        # The training record's MHE type is chosen by staff in the UI
        # dropdown BEFORE the paper is even uploaded (see page.tsx's
        # "MHE Type" select on each Training Record). That staff selection
        # is authoritative — trust it over whatever Claude Vision guesses
        # from the scanned image, since a guess is only a fallback for
        # when no hint was supplied at all.
        mhe_type_hint    = (request.form.get("mhe_type_hint") or "").strip()
        detected_mhe_type = extracted.get("mhe_type", "")
        if mhe_type_hint:
            mhe_type_hint = normalize_mhe_type(mhe_type_hint)
            extracted["mhe_type"] = mhe_type_hint

        result = grade_test_internal(extracted)
        # Surface any mismatch so the frontend can flag it quietly (e.g. a
        # small note in the review list) without blocking the grade —
        # staff already picked the MHE type deliberately, so it wins.
        result["detected_mhe_type"] = detected_mhe_type
        result["mhe_type_mismatch"] = bool(
            mhe_type_hint and detected_mhe_type and
            mhe_type_hint != detected_mhe_type.upper().strip()
        )

        current_app.logger.info(
            f"✅ Auto-graded training paper: {result['mhe_type']} — "
            f"{result['total_marks_obtained']}/{result['total_marks']} "
            f"({result['percentage']}%) — {result['grade']}"
        )

        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error auto-grading training paper: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /api/test-grading/regrade
# NEW: recomputes score/pass-fail from a (possibly staff-corrected) answers
# dict, WITHOUT calling Claude Vision again. Powers the editable per-question
# dropdown review list in the participant popup — every time staff changes
# one answer, the frontend calls this to get the updated score live, no
# image processing involved, so it's cheap enough to call on every edit.
# ═════════════════════════════════════════════════════════════════════════════
@test_grading_bp.route("/regrade", methods=["POST"])
@token_required
def regrade_training_paper():
    try:
        data      = request.get_json(silent=True) or {}
        mhe_type  = normalize_mhe_type(data.get("mhe_type"))
        answers   = data.get("answers") or {}
        if mhe_type not in ANSWER_KEYS:
            return jsonify({"error": f"Invalid mhe_type. Must be one of {list(ANSWER_KEYS.keys())}"}), 400

        result = grade_test_internal({"mhe_type": mhe_type, "answers": answers})
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error regrading: {e}")
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: POST /api/test-grading/grade-with-corrections
# Step 2: Grade with human-corrected answers and persist to Client_Interactions
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/grade-with-corrections", methods=["POST"])
@token_required
def grade_with_corrections():
    session = SessionLocal()

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        extracted_data = data.get("extracted_data", {})
        corrected_answers = data.get("corrected_answers", {})
        image_base64 = extracted_data.get("image_base64", "")

        # Use corrected answers for grading
        extracted_data["answers"] = corrected_answers
        result = grade_test_internal(extracted_data)

        employee_id = getattr(request.current_user, "employee_id", None)
        user_id = getattr(request.current_user, "user_id", None)
        tenant_id = getattr(request.current_user, "tenant_id", None)

        # Auto-match client by company name in the new DB
        company_name = result.get("company", "").strip()
        client_id = None

        if company_name:
            client_id = find_client_by_company(
                session,
                company_name,
                tenant_id,
                SCHEMA
            )

            if client_id:
                current_app.logger.info(
                    f"✅ Matched company '{company_name}' to client_id: {client_id}"
                )
            else:
                current_app.logger.warning(
                    f"⚠️ No client found for company: '{company_name}'"
                )

        # Allow manual override from frontend
        if data.get("client_id"):
            client_id = data.get("client_id")

        # Determine test type
        test_type = extracted_data.get("test_type", "").lower()

        if "pre" in test_type:
            test_type_clean = "pre"
        elif "post" in test_type:
            test_type_clean = "post"
        else:
            test_type_clean = "unknown"

        # Store test-result metadata inside notes.
        meta = {
            "record_type":          "test_result",
            "participant_name":     result["participant_name"],
            "company":              result["company"],
            "date":                 result["date"],
            "place":                result["place"],
            "test_type":            test_type_clean,
            "original_test_type":   result["test_type"],
            "mhe_type":             result["mhe_type"],
            "answers":              result["answers"],
            "total_marks_obtained": result["total_marks_obtained"],
            "total_marks":          result["total_marks"],
            "percentage":           result["percentage"],
            "grade":                result["grade"],
            "details":              result["details"],
            "image_base64":         image_base64,
            "graded_by_user_id":    user_id,
            "graded_by_employee_id": employee_id,
        }

        current_app.logger.info(
            f"💾 Saving test result: client_id={client_id}, "
            f"test_type={test_type_clean}"
        )

        insert_result = session.execute(
            text(f"""
                INSERT INTO "{SCHEMA}"."Client_Interactions"
                    (client_id, contact_date, contact_method,
                     notes, next_steps, created_at)
                VALUES
                    (:client_id, :contact_date, :contact_method,
                     :notes, :next_steps, :created_at)
                RETURNING interaction_id
            """),
            {
                "client_id": client_id,
                "contact_date": datetime.utcnow().date(),
                "contact_method": CONTACT_METHOD_TEST_RESULT,
                "notes": pack_meta(meta),
                "next_steps": str(employee_id) if employee_id else str(user_id),
                "created_at": datetime.utcnow()
            }
        )

        new_id = insert_result.fetchone().interaction_id
        session.commit()

        result["id"] = new_id
        result["client_id"] = client_id
        result["test_type"] = test_type_clean
        result["created_at"] = datetime.utcnow().isoformat()

        current_app.logger.info(
            f"✅ Test result saved: id={new_id}, client_id={client_id}, "
            f"grade={result['grade']} ({result['percentage']}%)"
        )

        return jsonify(result), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error grading test: {e}")
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__
        }), 500

    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /api/test-grading/results
# Returns all test results for the current employee
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/results", methods=["GET"])
@token_required
def get_test_results():
    session = SessionLocal()

    try:
        skip = request.args.get("skip", 0, type=int)
        limit = request.args.get("limit", 50, type=int)

        employee_id = getattr(request.current_user, "employee_id", None)
        user_id = getattr(request.current_user, "user_id", None)
        next_steps_val = str(employee_id) if employee_id else str(user_id)

        rows = session.execute(
            text(f"""
                SELECT *
                FROM "{SCHEMA}"."Client_Interactions"
                WHERE contact_method = :cm
                  AND next_steps = :emp_id
                  AND notes LIKE :marker
                ORDER BY created_at DESC
            """),
            {
                "cm": CONTACT_METHOD_TEST_RESULT,
                "emp_id": next_steps_val,
                "marker": TEST_RESULT_MARKER,
            },
        ).fetchall()

        rows = rows[skip:skip + limit]

        current_app.logger.info(
            f"📊 Test results - New DB: {len(rows)} returned"
        )

        return jsonify([
            serialize_result(row)
            for row in rows
        ]), 200

    except Exception as e:
        current_app.logger.exception(
            f"❌ Error fetching test results: {e}"
        )
        return jsonify({"error": str(e)}), 500

    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: GET /api/test-grading/results/<result_id>
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/results/<int:result_id>", methods=["GET"])
@token_required
def get_test_result(result_id):
    session = SessionLocal()

    try:
        employee_id = getattr(request.current_user, "employee_id", None)
        user_id = getattr(request.current_user, "user_id", None)
        next_steps_val = str(employee_id) if employee_id else str(user_id)

        row = session.execute(
            text(f"""
                SELECT *
                FROM "{SCHEMA}"."Client_Interactions"
                WHERE interaction_id = :iid
                  AND contact_method = :cm
                  AND next_steps = :emp_id
                  AND notes LIKE :marker
            """),
            {
                "iid": result_id,
                "cm": CONTACT_METHOD_TEST_RESULT,
                "emp_id": next_steps_val,
                "marker": TEST_RESULT_MARKER,
            },
        ).fetchone()

        if not row:
            return jsonify({
                "error": "Test result not found"
            }), 404

        return jsonify(serialize_result(row)), 200

    except Exception as e:
        current_app.logger.exception(
            f"❌ Error fetching test result: {e}"
        )
        return jsonify({"error": str(e)}), 500

    finally:
        session.close()


# ═════════════════════════════════════════════════════════════════════════════
# ROUTE: DELETE /api/test-grading/results/<result_id>
# ═════════════════════════════════════════════════════════════════════════════

@test_grading_bp.route("/results/<int:result_id>", methods=["DELETE"])
@token_required
def delete_test_result(result_id):
    session = SessionLocal()

    try:
        employee_id = getattr(request.current_user, "employee_id", None)
        user_id = getattr(request.current_user, "user_id", None)
        next_steps_val = str(employee_id) if employee_id else str(user_id)

        row = session.execute(
            text(f"""
                SELECT interaction_id
                FROM "{SCHEMA}"."Client_Interactions"
                WHERE interaction_id = :iid
                  AND contact_method = :cm
                  AND next_steps = :emp_id
                  AND notes LIKE :marker
            """),
            {
                "iid": result_id,
                "cm": CONTACT_METHOD_TEST_RESULT,
                "emp_id": next_steps_val,
                "marker": TEST_RESULT_MARKER,
            },
        ).fetchone()

        if not row:
            return jsonify({
                "error": "Test result not found"
            }), 404

        session.execute(
            text(
                f'DELETE FROM "{SCHEMA}"."Client_Interactions" '
                f'WHERE interaction_id = :iid'
            ),
            {"iid": result_id},
        )

        session.commit()

        current_app.logger.info(
            f"✅ Test result deleted: id={result_id}, database={SCHEMA}"
        )

        return jsonify({
            "message": "Test result deleted successfully"
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(
            f"❌ Error deleting test result: {e}"
        )
        return jsonify({"error": str(e)}), 500

    finally:
        session.close()


def find_client_by_company(
    session,
    company_name: str,
    tenant_id: int,
    schema: str,
) -> int | None:
    """
    Find client_id by matching company name.
    Searches Client_Master.client_company_name (case-insensitive)
    """
    if not company_name or not company_name.strip():
        return None
    
    try:
        result = session.execute(
            text(f"""
                SELECT client_id 
                FROM "{schema}"."Client_Master"
                WHERE tenant_id = :tenant_id
                AND LOWER(client_company_name) = LOWER(:company_name)
                LIMIT 1
            """),
            {
                "tenant_id": tenant_id,
                "company_name": company_name.strip()
            }
        ).fetchone()
        
        return result.client_id if result else None
    except Exception as e:
        current_app.logger.error(f"Error finding client by company name: {e}")
        return None