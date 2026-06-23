"""
Core Routes
Handles: basic health-check, index, and data-view template endpoints.
No direct StreemLyne_MT schema interaction — these are UI / utility endpoints.
"""

from flask import Blueprint, render_template, jsonify
from middleware import auth_required   # use shared middleware, not tenant_middleware directly

# Import app-level config constants with safe fallbacks
try:
    from config import latest_structured_data, FORM_COLUMNS
except ImportError:
    latest_structured_data = {}
    FORM_COLUMNS = []

core_bp = Blueprint('core', __name__, url_prefix='/core')

# ─────────────────────────────────────────
# Health check
# ─────────────────────────────────────────

@core_bp.route('/health', methods=['GET'])
def health_check():
    """
    Lightweight liveness probe — no auth required.
    GET /health
    Returns: { "status": "ok" }
    """
    return jsonify({'status': 'ok'}), 200


# ─────────────────────────────────────────
# Template views
# ─────────────────────────────────────────

@core_bp.route('/')
def index():
    """Serve the main SPA / landing page."""
    return render_template('index.html')


@core_bp.route('/view-data')
def view_data():
    """
    Render a table view of the latest structured data.
    Falls back to an informative error message when no data is available.
    """
    if not latest_structured_data:
        return render_template(
            'table.html',
            columns=FORM_COLUMNS,
            data=None,
            error='No data available — please upload an image first.'
        )
    return render_template(
        'table.html',
        columns=FORM_COLUMNS,
        data=latest_structured_data,
        error=None
    )