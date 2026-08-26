"""
Gafbros — Product Routes
/api/products
/api/products/<product_id>
/api/products/<product_id>/variants
/api/products/<product_id>/variants/<variant_id>
"""

from flask import Blueprint, request, jsonify, g
from backend.db import SessionLocal
from backend.middleware.auth_middleware import require_tenant
from sqlalchemy import text
import json

product_bp = Blueprint("products", __name__)


# ─────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────

@product_bp.route("/api/products", methods=["GET"])
@require_tenant
def get_products():
    """List all products for this tenant, with variant count."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                pm.product_id,
                pm.tenant_id,
                pm.sku,
                pm.name,
                pm.description,
                pm.category,
                pm.active,
                pm.created_at,
                COUNT(pv.variant_id) AS variant_count
            FROM "StreemLyne_MT"."Product_Master" pm
            LEFT JOIN "StreemLyne_MT"."Product_Variant" pv
                ON pv.product_id = pm.product_id AND pv.active = TRUE
            WHERE pm.tenant_id = :tenant_id
              AND pm.active = TRUE
            GROUP BY pm.product_id
            ORDER BY pm.name ASC
        """), {"tenant_id": g.tenant_id}).mappings().all()

        return jsonify([dict(r) for r in rows]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products/<int:product_id>", methods=["GET"])
@require_tenant
def get_product(product_id):
    """Get a single product with all its variants."""
    db = SessionLocal()
    try:
        product = db.execute(text("""
            SELECT
                product_id, tenant_id, sku, name,
                description, category, active, created_at
            FROM "StreemLyne_MT"."Product_Master"
            WHERE product_id = :product_id
              AND tenant_id  = :tenant_id
        """), {"product_id": product_id, "tenant_id": g.tenant_id}).mappings().first()

        if not product:
            return jsonify({"error": "Product not found"}), 404

        variants = db.execute(text("""
            SELECT
                variant_id, product_id, sku_variant, variant_label,
                dimensions, material_type, material_grade, gsm_thickness,
                print_colors, multi_side, print_size, treatments,
                active, created_at
            FROM "StreemLyne_MT"."Product_Variant"
            WHERE product_id = :product_id
              AND active = TRUE
            ORDER BY variant_label ASC
        """), {"product_id": product_id}).mappings().all()

        result = dict(product)
        result["variants"] = [dict(v) for v in variants]

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products", methods=["POST"])
@require_tenant
def create_product():
    """Create a new product."""
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    db = SessionLocal()
    try:
        row = db.execute(text("""
            INSERT INTO "StreemLyne_MT"."Product_Master" (
                tenant_id, sku, name, description, category, active
            ) VALUES (
                :tenant_id, :sku, :name, :description, :category, :active
            )
            RETURNING product_id
        """), {
            "tenant_id":   g.tenant_id,
            "sku":         data.get("sku"),
            "name":        data["name"],
            "description": data.get("description"),
            "category":    data.get("category"),
            "active":      data.get("active", True),
        }).mappings().first()

        db.commit()
        return jsonify({"product_id": row["product_id"], "message": "Product created"}), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products/<int:product_id>", methods=["PATCH"])
@require_tenant
def update_product(product_id):
    """Update a product."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed = ["sku", "name", "description", "category", "active"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({"error": "No valid fields to update"}), 400

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["product_id"] = product_id
    fields["tenant_id"] = g.tenant_id

    db = SessionLocal()
    try:
        result = db.execute(text(f"""
            UPDATE "StreemLyne_MT"."Product_Master"
            SET {set_clause}, updated_at = NOW()
            WHERE product_id = :product_id
              AND tenant_id  = :tenant_id
        """), fields)

        if result.rowcount == 0:
            return jsonify({"error": "Product not found"}), 404

        db.commit()
        return jsonify({"message": "Product updated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products/<int:product_id>", methods=["DELETE"])
@require_tenant
def delete_product(product_id):
    """Soft delete a product."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE "StreemLyne_MT"."Product_Master"
            SET active = FALSE, updated_at = NOW()
            WHERE product_id = :product_id
              AND tenant_id  = :tenant_id
        """), {"product_id": product_id, "tenant_id": g.tenant_id})

        if result.rowcount == 0:
            return jsonify({"error": "Product not found"}), 404

        db.commit()
        return jsonify({"message": "Product deactivated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─────────────────────────────────────────────
# PRODUCT VARIANTS
# ─────────────────────────────────────────────

@product_bp.route("/api/products/<int:product_id>/variants", methods=["GET"])
@require_tenant
def get_variants(product_id):
    """List all variants for a product."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                variant_id, product_id, sku_variant, variant_label,
                dimensions, material_type, material_grade, gsm_thickness,
                print_colors, multi_side, print_size, treatments,
                active, created_at
            FROM "StreemLyne_MT"."Product_Variant"
            WHERE product_id = :product_id
              AND active = TRUE
            ORDER BY variant_label ASC
        """), {"product_id": product_id}).mappings().all()

        return jsonify([dict(r) for r in rows]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products/<int:product_id>/variants", methods=["POST"])
@require_tenant
def create_variant(product_id):
    """Create a variant for a product."""
    data = request.get_json()
    if not data or not data.get("variant_label"):
        return jsonify({"error": "variant_label is required"}), 400

    db = SessionLocal()
    try:
        # Verify product belongs to this tenant
        product = db.execute(text("""
            SELECT product_id FROM "StreemLyne_MT"."Product_Master"
            WHERE product_id = :product_id AND tenant_id = :tenant_id
        """), {"product_id": product_id, "tenant_id": g.tenant_id}).first()

        if not product:
            return jsonify({"error": "Product not found"}), 404

        row = db.execute(text("""
            INSERT INTO "StreemLyne_MT"."Product_Variant" (
                product_id, sku_variant, variant_label,
                dimensions, material_type, material_grade, gsm_thickness,
                print_colors, multi_side, print_size, treatments, active
            ) VALUES (
                :product_id, :sku_variant, :variant_label,
                :dimensions, :material_type, :material_grade, :gsm_thickness,
                :print_colors, :multi_side, :print_size, :treatments, :active
            )
            RETURNING variant_id
        """), {
            "product_id":     product_id,
            "sku_variant":    data.get("sku_variant"),
            "variant_label":  data["variant_label"],
            "dimensions":     json.dumps(data.get("dimensions")) if data.get("dimensions") else None,
            "material_type":  data.get("material_type"),
            "material_grade": data.get("material_grade"),
            "gsm_thickness":  data.get("gsm_thickness"),
            "print_colors":   data.get("print_colors"),
            "multi_side":     data.get("multi_side", False),
            "print_size":     data.get("print_size"),
            "treatments":     json.dumps(data.get("treatments")) if data.get("treatments") else None,
            "active":         data.get("active", True),
        }).mappings().first()

        db.commit()
        return jsonify({"variant_id": row["variant_id"], "message": "Variant created"}), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products/<int:product_id>/variants/<int:variant_id>", methods=["PATCH"])
@require_tenant
def update_variant(product_id, variant_id):
    """Update a product variant."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed = [
        "sku_variant", "variant_label", "dimensions", "material_type",
        "material_grade", "gsm_thickness", "print_colors", "multi_side",
        "print_size", "treatments", "active"
    ]
    fields = {k: v for k, v in data.items() if k in allowed}

    # Serialise JSONB fields
    for jsonb_field in ["dimensions", "treatments"]:
        if jsonb_field in fields and isinstance(fields[jsonb_field], (dict, list)):
            fields[jsonb_field] = json.dumps(fields[jsonb_field])

    if not fields:
        return jsonify({"error": "No valid fields to update"}), 400

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["variant_id"] = variant_id
    fields["product_id"] = product_id

    db = SessionLocal()
    try:
        result = db.execute(text(f"""
            UPDATE "StreemLyne_MT"."Product_Variant"
            SET {set_clause}, updated_at = NOW()
            WHERE variant_id = :variant_id
              AND product_id = :product_id
        """), fields)

        if result.rowcount == 0:
            return jsonify({"error": "Variant not found"}), 404

        db.commit()
        return jsonify({"message": "Variant updated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@product_bp.route("/api/products/<int:product_id>/variants/<int:variant_id>", methods=["DELETE"])
@require_tenant
def delete_variant(product_id, variant_id):
    """Soft delete a product variant."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE "StreemLyne_MT"."Product_Variant"
            SET active = FALSE, updated_at = NOW()
            WHERE variant_id = :variant_id
              AND product_id = :product_id
        """), {"variant_id": variant_id, "product_id": product_id})

        if result.rowcount == 0:
            return jsonify({"error": "Variant not found"}), 404

        db.commit()
        return jsonify({"message": "Variant deactivated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─────────────────────────────────────────────
# UTILITY — all variants flat (for dropdowns)
# ─────────────────────────────────────────────

@product_bp.route("/api/products/variants/all", methods=["GET"])
@require_tenant
def get_all_variants():
    """Return all active variants across all products for this tenant.
    Used in supplier price list and quotation item pickers."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                pv.variant_id,
                pv.product_id,
                pv.sku_variant,
                pv.variant_label,
                pv.dimensions,
                pv.material_type,
                pv.material_grade,
                pv.gsm_thickness,
                pv.print_colors,
                pv.multi_side,
                pv.print_size,
                pv.treatments,
                pm.name     AS product_name,
                pm.sku      AS product_sku,
                pm.category AS product_category
            FROM "StreemLyne_MT"."Product_Variant" pv
            JOIN "StreemLyne_MT"."Product_Master"  pm ON pm.product_id = pv.product_id
            WHERE pm.tenant_id = :tenant_id
              AND pm.active    = TRUE
              AND pv.active    = TRUE
            ORDER BY pm.name ASC, pv.variant_label ASC
        """), {"tenant_id": g.tenant_id}).mappings().all()

        return jsonify([dict(r) for r in rows]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()