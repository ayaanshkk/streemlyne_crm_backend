"""
Gafbros — Supplier Routes
/api/suppliers
/api/suppliers/<supplier_id>
/api/suppliers/<supplier_id>/price-list
/api/suppliers/<supplier_id>/price-list/<spl_id>
"""

from flask import Blueprint, request, jsonify, g
from backend.db import SessionLocal
from backend.middleware.auth_middleware import require_tenant
from sqlalchemy import text
from datetime import datetime

supplier_bp = Blueprint("suppliers", __name__)


# ─────────────────────────────────────────────
# SUPPLIERS
# ─────────────────────────────────────────────

@supplier_bp.route("/api/suppliers", methods=["GET"])
@require_tenant
def get_suppliers():
    """List all suppliers for this tenant."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                supplier_id,
                supplier_company_name,
                supplier_contact_name,
                supplier_email,
                supplier_phone,
                address,
                payment_terms,
                currency,
                active,
                created_at
            FROM "StreemLyne_MT"."Supplier_Master"
            WHERE active = TRUE
            ORDER BY supplier_company_name ASC
        """)).mappings().all()

        return jsonify([dict(r) for r in rows]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers/<int:supplier_id>", methods=["GET"])
@require_tenant
def get_supplier(supplier_id):
    """Get a single supplier by ID."""
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT
                supplier_id,
                supplier_company_name,
                supplier_contact_name,
                supplier_email,
                supplier_phone,
                address,
                payment_terms,
                currency,
                active,
                created_at
            FROM "StreemLyne_MT"."Supplier_Master"
            WHERE supplier_id = :supplier_id
        """), {"supplier_id": supplier_id}).mappings().first()

        if not row:
            return jsonify({"error": "Supplier not found"}), 404

        return jsonify(dict(row)), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers", methods=["POST"])
@require_tenant
def create_supplier():
    """Create a new supplier."""
    data = request.get_json()
    if not data or not data.get("supplier_company_name"):
        return jsonify({"error": "supplier_company_name is required"}), 400

    db = SessionLocal()
    try:
        row = db.execute(text("""
            INSERT INTO "StreemLyne_MT"."Supplier_Master" (
                supplier_company_name,
                supplier_contact_name,
                supplier_email,
                supplier_phone,
                address,
                payment_terms,
                currency,
                active
            ) VALUES (
                :supplier_company_name,
                :supplier_contact_name,
                :supplier_email,
                :supplier_phone,
                :address,
                :payment_terms,
                :currency,
                :active
            )
            RETURNING supplier_id
        """), {
            "supplier_company_name": data["supplier_company_name"],
            "supplier_contact_name": data.get("supplier_contact_name"),
            "supplier_email":        data.get("supplier_email"),
            "supplier_phone":        data.get("supplier_phone"),
            "address":               data.get("address"),
            "payment_terms":         data.get("payment_terms"),
            "currency":              data.get("currency", "GBP"),
            "active":                data.get("active", True),
        }).mappings().first()

        db.commit()
        return jsonify({"supplier_id": row["supplier_id"], "message": "Supplier created"}), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers/<int:supplier_id>", methods=["PATCH"])
@require_tenant
def update_supplier(supplier_id):
    """Update an existing supplier."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed = [
        "supplier_company_name", "supplier_contact_name", "supplier_email",
        "supplier_phone", "address", "payment_terms", "currency", "active"
    ]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({"error": "No valid fields to update"}), 400

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["supplier_id"] = supplier_id

    db = SessionLocal()
    try:
        result = db.execute(text(f"""
            UPDATE "StreemLyne_MT"."Supplier_Master"
            SET {set_clause}
            WHERE supplier_id = :supplier_id
        """), fields)

        if result.rowcount == 0:
            return jsonify({"error": "Supplier not found"}), 404

        db.commit()
        return jsonify({"message": "Supplier updated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers/<int:supplier_id>", methods=["DELETE"])
@require_tenant
def delete_supplier(supplier_id):
    """Soft delete a supplier (sets active = FALSE)."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE "StreemLyne_MT"."Supplier_Master"
            SET active = FALSE
            WHERE supplier_id = :supplier_id
        """), {"supplier_id": supplier_id})

        if result.rowcount == 0:
            return jsonify({"error": "Supplier not found"}), 404

        db.commit()
        return jsonify({"message": "Supplier deactivated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ─────────────────────────────────────────────
# SUPPLIER PRICE LIST
# ─────────────────────────────────────────────

@supplier_bp.route("/api/suppliers/<int:supplier_id>/price-list", methods=["GET"])
@require_tenant
def get_supplier_price_list(supplier_id):
    """Get all price list entries for a supplier, joined with variant + product info."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT
                spl.spl_id,
                spl.supplier_id,
                spl.variant_id,
                spl.unit_cost,
                spl.currency,
                spl.min_qty,
                spl.lead_time_weeks,
                spl.effective_from,
                spl.effective_to,
                spl.notes,
                spl.created_at,
                pv.variant_label,
                pv.sku_variant,
                pm.product_id,
                pm.name  AS product_name,
                pm.sku   AS product_sku,
                pm.category
            FROM "StreemLyne_MT"."Supplier_Price_List" spl
            JOIN "StreemLyne_MT"."Product_Variant" pv ON pv.variant_id = spl.variant_id
            JOIN "StreemLyne_MT"."Product_Master"  pm ON pm.product_id = pv.product_id
            WHERE spl.supplier_id = :supplier_id
            ORDER BY pm.name ASC, pv.variant_label ASC
        """), {"supplier_id": supplier_id}).mappings().all()

        return jsonify([dict(r) for r in rows]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers/<int:supplier_id>/price-list", methods=["POST"])
@require_tenant
def create_supplier_price_list_entry(supplier_id):
    """Add a price list entry for a supplier."""
    data = request.get_json()
    required = ["variant_id", "unit_cost", "effective_from"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    db = SessionLocal()
    try:
        row = db.execute(text("""
            INSERT INTO "StreemLyne_MT"."Supplier_Price_List" (
                supplier_id, variant_id, unit_cost, currency,
                min_qty, lead_time_weeks, effective_from, effective_to, notes
            ) VALUES (
                :supplier_id, :variant_id, :unit_cost, :currency,
                :min_qty, :lead_time_weeks, :effective_from, :effective_to, :notes
            )
            RETURNING spl_id
        """), {
            "supplier_id":     supplier_id,
            "variant_id":      data["variant_id"],
            "unit_cost":       data["unit_cost"],
            "currency":        data.get("currency", "GBP"),
            "min_qty":         data.get("min_qty", 1),
            "lead_time_weeks": data.get("lead_time_weeks"),
            "effective_from":  data["effective_from"],
            "effective_to":    data.get("effective_to"),
            "notes":           data.get("notes"),
        }).mappings().first()

        db.commit()
        return jsonify({"spl_id": row["spl_id"], "message": "Price list entry created"}), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers/<int:supplier_id>/price-list/<int:spl_id>", methods=["PATCH"])
@require_tenant
def update_supplier_price_list_entry(supplier_id, spl_id):
    """Update a supplier price list entry."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed = ["unit_cost", "currency", "min_qty", "lead_time_weeks",
               "effective_from", "effective_to", "notes"]
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({"error": "No valid fields to update"}), 400

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["spl_id"] = spl_id
    fields["supplier_id"] = supplier_id

    db = SessionLocal()
    try:
        result = db.execute(text(f"""
            UPDATE "StreemLyne_MT"."Supplier_Price_List"
            SET {set_clause}
            WHERE spl_id = :spl_id AND supplier_id = :supplier_id
        """), fields)

        if result.rowcount == 0:
            return jsonify({"error": "Entry not found"}), 404

        db.commit()
        return jsonify({"message": "Price list entry updated"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@supplier_bp.route("/api/suppliers/<int:supplier_id>/price-list/<int:spl_id>", methods=["DELETE"])
@require_tenant
def delete_supplier_price_list_entry(supplier_id, spl_id):
    """Delete a supplier price list entry."""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            DELETE FROM "StreemLyne_MT"."Supplier_Price_List"
            WHERE spl_id = :spl_id AND supplier_id = :supplier_id
        """), {"spl_id": spl_id, "supplier_id": supplier_id})

        if result.rowcount == 0:
            return jsonify({"error": "Entry not found"}), 404

        db.commit()
        return jsonify({"message": "Price list entry deleted"}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()