from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import token_required

pricelist_bp = Blueprint('pricelist', __name__)

SCHEMA = "streemLyne_mt_dev2"
DEFAULT_TENANT_ID = 3


def get_tenant_id():
    """Get tenant_id from request, defaulting to FAI tenant."""
    try:
        return int(request.args.get('tenant_id', DEFAULT_TENANT_ID))
    except (TypeError, ValueError):
        return DEFAULT_TENANT_ID


@pricelist_bp.route('/pricelist/lookup', methods=['GET', 'OPTIONS'])
@token_required
def lookup_pricelist_item():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    item_code = request.args.get('item_code', '').strip().upper()
    tenant_id = get_tenant_id()

    if not item_code:
        return jsonify({'error': 'item_code is required'}), 400

    session = SessionLocal()

    try:
        row = session.execute(
            text(f"""
                SELECT
                    p.item_code,
                    p.item_name,
                    p.description,
                    p.unit,
                    pl.base_price,
                    pl.category,
                    pl.list_type,
                    pl.min_qty,
                    pl.effective_from,
                    pl.effective_to,
                    pl.pricelist_id,
                    pl.product_id,
                    pl.variant_id
                FROM "{SCHEMA}"."PriceList_Master" pl
                JOIN "{SCHEMA}"."Product_Master" p
                    ON p.product_id = pl.product_id
                WHERE UPPER(p.item_code) = :code
                  AND pl.tenant_id = :tid
                  AND p.tenant_id = :tid
                  AND (p.active IS NULL OR p.active = TRUE)
                ORDER BY pl.pricelist_id DESC
                LIMIT 1
            """),
            {
                "code": item_code,
                "tid": tenant_id
            }
        ).fetchone()

        if not row:
            return jsonify({
                'error': f'Item code {item_code} not found'
            }), 404

        return jsonify({
            "pricelist_id": row.pricelist_id,
            "product_id": row.product_id,
            "variant_id": row.variant_id,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "description": row.description or row.item_name,
            "unit_rate": float(row.base_price or 0),
            "unit": row.unit,
            "category": row.category,
            "list_type": row.list_type,
            "min_qty": row.min_qty,
            "effective_from": (
                row.effective_from.isoformat()
                if row.effective_from else None
            ),
            "effective_to": (
                row.effective_to.isoformat()
                if row.effective_to else None
            ),
        }), 200

    except Exception as e:
        current_app.logger.error(
            f"Pricelist lookup error: {e}",
            exc_info=True
        )
        return jsonify({'error': str(e)}), 500

    finally:
        session.close()


@pricelist_bp.route('/pricelist', methods=['GET', 'OPTIONS'])
@token_required
def list_pricelist():
    """List pricelist items for the tenant."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    tenant_id = get_tenant_id()
    search = request.args.get('q', '').strip()

    session = SessionLocal()

    try:
        search_condition = ""
        params = {"tid": tenant_id}

        if search:
            search_condition = """
                AND (
                    p.item_code ILIKE :search
                    OR p.item_name ILIKE :search
                    OR p.description ILIKE :search
                )
            """
            params["search"] = f"%{search}%"

        rows = session.execute(
            text(f"""
                SELECT
                    pl.pricelist_id,
                    pl.product_id,
                    pl.variant_id,
                    pl.tenant_id,
                    pl.category,
                    pl.base_price,
                    pl.list_type,
                    pl.min_qty,
                    pl.effective_from,
                    pl.effective_to,
                    p.item_code,
                    p.item_name,
                    p.description,
                    p.unit
                FROM "{SCHEMA}"."PriceList_Master" pl
                JOIN "{SCHEMA}"."Product_Master" p
                    ON p.product_id = pl.product_id
                WHERE pl.tenant_id = :tid
                  AND p.tenant_id = :tid
                  AND (p.active IS NULL OR p.active = TRUE)
                  {search_condition}
                ORDER BY p.item_code
                LIMIT 100
            """),
            params
        ).fetchall()

        return jsonify([
            {
                "pricelist_id": r.pricelist_id,
                "product_id": r.product_id,
                "variant_id": r.variant_id,
                "item_code": r.item_code,
                "item_name": r.item_name,
                "description": r.description or r.item_name,
                "unit_rate": float(r.base_price or 0),
                "unit": r.unit,
                "category": r.category,
                "list_type": r.list_type,
                "min_qty": r.min_qty,
                "effective_from": (
                    r.effective_from.isoformat()
                    if r.effective_from else None
                ),
                "effective_to": (
                    r.effective_to.isoformat()
                    if r.effective_to else None
                ),
            }
            for r in rows
        ]), 200

    except Exception as e:
        current_app.logger.error(
            f"Pricelist list error: {e}",
            exc_info=True
        )
        return jsonify({'error': str(e)}), 500

    finally:
        session.close()


@pricelist_bp.route('/pricelist', methods=['POST', 'OPTIONS'])
@token_required
def create_pricelist_item():
    """Create a new pricelist entry for an existing product."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data = request.get_json() or {}

    item_code = str(data.get('item_code', '')).strip().upper()
    base_price = float(data.get('base_price') or 0)
    tenant_id = get_tenant_id()

    category = str(
        data.get('category', 'Training')
    ).strip()

    list_type = str(
        data.get('list_type', 'Standard')
    ).strip()

    min_qty = int(data.get('min_qty') or 1)
    product_id = data.get('product_id')
    variant_id = data.get('variant_id')

    if not item_code:
        return jsonify({
            'error': 'item_code is required'
        }), 400

    session = SessionLocal()

    try:
        # Find product using item_code
        product = session.execute(
            text(f"""
                SELECT
                    product_id,
                    item_code,
                    item_name,
                    description,
                    unit
                FROM "{SCHEMA}"."Product_Master"
                WHERE UPPER(item_code) = :code
                  AND tenant_id = :tid
                  AND (active IS NULL OR active = TRUE)
                LIMIT 1
            """),
            {
                "code": item_code,
                "tid": tenant_id
            }
        ).fetchone()

        if not product:
            return jsonify({
                'error': f'Product with item code {item_code} not found'
            }), 404

        product_id = product.product_id

        # Validate variant if supplied
        if variant_id is not None:
            variant = session.execute(
                text(f"""
                    SELECT variant_id
                    FROM "{SCHEMA}"."Product_Variant"
                    WHERE variant_id = :vid
                      AND product_id = :pid
                      AND tenant_id = :tid
                      AND (active IS NULL OR active = TRUE)
                    LIMIT 1
                """),
                {
                    "vid": variant_id,
                    "pid": product_id,
                    "tid": tenant_id
                }
            ).fetchone()

            if not variant:
                return jsonify({
                    'error': 'Invalid variant_id for this product'
                }), 400

        # Check duplicate pricelist entry
        existing = session.execute(
            text(f"""
                SELECT pricelist_id
                FROM "{SCHEMA}"."PriceList_Master"
                WHERE product_id = :pid
                  AND tenant_id = :tid
                  AND (
                      variant_id = :vid
                      OR (variant_id IS NULL AND :vid IS NULL)
                  )
                  AND list_type = :list_type
                LIMIT 1
            """),
            {
                "pid": product_id,
                "tid": tenant_id,
                "vid": variant_id,
                "list_type": list_type
            }
        ).fetchone()

        if existing:
            return jsonify({
                'error': 'Pricelist entry already exists for this product'
            }), 409

        # Generate next pricelist_id
        next_id = session.execute(
            text(f"""
                SELECT COALESCE(MAX(pricelist_id), 0) + 1
                FROM "{SCHEMA}"."PriceList_Master"
            """)
        ).scalar()

        session.execute(
            text(f"""
                INSERT INTO "{SCHEMA}"."PriceList_Master"
                (
                    pricelist_id,
                    tenant_id,
                    category,
                    base_price,
                    list_type,
                    variant_id,
                    min_qty,
                    effective_from,
                    effective_to,
                    product_id
                )
                VALUES
                (
                    :pricelist_id,
                    :tenant_id,
                    :category,
                    :base_price,
                    :list_type,
                    :variant_id,
                    :min_qty,
                    :effective_from,
                    :effective_to,
                    :product_id
                )
            """),
            {
                "pricelist_id": next_id,
                "tenant_id": tenant_id,
                "category": category,
                "base_price": base_price,
                "list_type": list_type,
                "variant_id": variant_id,
                "min_qty": min_qty,
                "effective_from": data.get('effective_from'),
                "effective_to": data.get('effective_to'),
                "product_id": product_id
            }
        )

        session.commit()

        return jsonify({
            "pricelist_id": next_id,
            "product_id": product_id,
            "variant_id": variant_id,
            "item_code": product.item_code,
            "item_name": product.item_name,
            "description": product.description or product.item_name,
            "unit_rate": base_price,
            "unit": product.unit,
            "category": category,
            "list_type": list_type,
            "min_qty": min_qty
        }), 201

    except Exception as e:
        session.rollback()
        current_app.logger.error(
            f"Pricelist create error: {e}",
            exc_info=True
        )
        return jsonify({'error': str(e)}), 500

    finally:
        session.close()


@pricelist_bp.route(
    '/pricelist/<int:pricelist_id>',
    methods=['PUT', 'OPTIONS']
)
@token_required
def update_pricelist_item(pricelist_id):
    """Update an existing pricelist entry."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    data = request.get_json() or {}

    tenant_id = get_tenant_id()

    session = SessionLocal()

    try:
        existing = session.execute(
            text(f"""
                SELECT
                    pl.pricelist_id,
                    pl.product_id,
                    pl.variant_id
                FROM "{SCHEMA}"."PriceList_Master" pl
                WHERE pl.pricelist_id = :pid
                  AND pl.tenant_id = :tid
                LIMIT 1
            """),
            {
                "pid": pricelist_id,
                "tid": tenant_id
            }
        ).fetchone()

        if not existing:
            return jsonify({
                'error': f'Pricelist {pricelist_id} not found'
            }), 404

        allowed_fields = {
            "category": data.get("category"),
            "base_price": data.get("base_price"),
            "list_type": data.get("list_type"),
            "min_qty": data.get("min_qty"),
            "effective_from": data.get("effective_from"),
            "effective_to": data.get("effective_to"),
            "variant_id": data.get("variant_id"),
            "product_id": data.get("product_id")
        }

        updates = []
        params = {
            "pricelist_id": pricelist_id,
            "tenant_id": tenant_id
        }

        for field, value in allowed_fields.items():
            if value is not None:
                updates.append(f"{field} = :{field}")
                params[field] = value

        if not updates:
            return jsonify({
                'error': 'No fields to update'
            }), 400

        session.execute(
            text(f"""
                UPDATE "{SCHEMA}"."PriceList_Master"
                SET {", ".join(updates)},
                    updated_at = CURRENT_TIMESTAMP
                WHERE pricelist_id = :pricelist_id
                  AND tenant_id = :tenant_id
            """),
            params
        )

        session.commit()

        return jsonify({
            "success": True,
            "pricelist_id": pricelist_id
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(
            f"Pricelist update error: {e}",
            exc_info=True
        )
        return jsonify({'error': str(e)}), 500

    finally:
        session.close()


@pricelist_bp.route(
    '/pricelist/<int:pricelist_id>',
    methods=['DELETE', 'OPTIONS']
)
@token_required
def delete_pricelist_item(pricelist_id):
    """Delete a pricelist entry."""
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    tenant_id = get_tenant_id()

    session = SessionLocal()

    try:
        result = session.execute(
            text(f"""
                DELETE FROM "{SCHEMA}"."PriceList_Master"
                WHERE pricelist_id = :pid
                  AND tenant_id = :tid
            """),
            {
                "pid": pricelist_id,
                "tid": tenant_id
            }
        )

        session.commit()

        if result.rowcount == 0:
            return jsonify({
                'error': f'Pricelist {pricelist_id} not found'
            }), 404

        return jsonify({
            'success': True,
            'deleted': pricelist_id
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.error(
            f"Pricelist delete error: {e}",
            exc_info=True
        )
        return jsonify({'error': str(e)}), 500

    finally:
        session.close()