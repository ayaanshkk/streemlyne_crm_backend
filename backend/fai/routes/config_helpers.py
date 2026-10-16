"""
backend/routes/config_helpers.py

Shared configuration and database helpers.

Training stages are tenant-specific when configured. Tenant mapping rows are
ordered through Preceding_Stage_ID, which references the mapping row ID. The
stage_id exposed to existing API consumers remains Pipeline_Stage_Master ID.
If a tenant has no mappings, stages fall back to Pipeline_Stage_Master rows
where stage_type = 2.
"""

import os
import re

from flask import current_app, request
from sqlalchemy import text

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def cfg(key, cast=str):
    """Read a required setting from Flask config or environment."""
    value = current_app.config.get(key, os.environ.get(key))
    if value is None or str(value).strip() == "":
        raise RuntimeError(
            f"Missing required configuration '{key}'. "
            "Set it in app.config or as an environment variable."
        )
    return cast(value)


def schema():
    """Return the configured PostgreSQL schema after validating its name."""
    value = cfg("DB_SCHEMA")
    if not _IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(
            "DB_SCHEMA must contain only letters, numbers, and underscores."
        )
    return value


def T(table_name):
    """Return a safely quoted table reference in the configured schema."""
    if not _IDENTIFIER_RE.fullmatch(table_name):
        raise ValueError("Invalid table name.")
    return f'"{schema()}"."{table_name}"'


def _normalized_name(value):
    """Normalize a stage name for semantic matching."""
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


class TrainingStageContext:
    """Resolved training stages in board order."""

    def __init__(self, ordered, awaiting_id, default_id, po_received_id):
        self.ordered = ordered
        self.names = [stage["stage_name"] for stage in ordered]

        # A master stage may be mapped to multiple tenant-specific stages
        # (for example, FAI maps master stage 11 to PTI/Certificate/Invoice).
        # Therefore, do not use a single stage_id -> name dictionary.
        def first_by_master_id(stage_id):
            return next(
                (stage for stage in ordered if stage["stage_id"] == stage_id),
                None,
            )

        def first_by_name(*needles):
            for stage in ordered:
                name = _normalized_name(stage["stage_name"])
                if any(needle in name for needle in needles):
                    return stage
            return None

        # Prefer the configured master ID when it resolves. If tenant mappings
        # use a different workflow, fall back to the tenant's stage names/order.
        awaiting = first_by_master_id(awaiting_id) or first_by_name(
            "awaiting scheduling", "awaiting schedule"
        ) or ordered[0]

        default = first_by_master_id(default_id) or first_by_name(
            "training scheduled", "scheduled"
        )
        if default is None:
            default = ordered[1] if len(ordered) > 1 else ordered[0]

        po_received = first_by_master_id(po_received_id) or first_by_name(
            "po received", "purchase order received", "pti created"
        )

        self.awaiting = awaiting["stage_name"]
        self.default = default["stage_name"]
        self.po_received = po_received["stage_name"] if po_received else None

        if po_received:
            po_index = ordered.index(po_received)
            self.po_required = self.names[po_index:]
        else:
            # No PO-related stage is configured or recognizable for this
            # tenant, so do not incorrectly mark every stage as PO-required.
            self.po_required = []


def _order_stages(rows, id_key, name_key, predecessor_key):
    """Order stage rows by following predecessor links."""
    if not rows:
        raise RuntimeError("No training stages were found.")

    by_id = {row[id_key]: row for row in rows}
    if len(by_id) != len(rows):
        raise RuntimeError("Training stage mapping IDs are not unique.")

    starts = [row for row in rows if row[predecessor_key] is None]
    if len(starts) != 1:
        raise RuntimeError(
            "Training stages must have exactly one first stage "
            "(a row with no predecessor)."
        )

    next_of = {}
    for row in rows:
        predecessor = row[predecessor_key]
        if predecessor is None:
            continue
        if predecessor not in by_id:
            raise RuntimeError(
                f"Training stage predecessor {predecessor} does not exist "
                "in the configured stages."
            )
        if predecessor in next_of:
            raise RuntimeError("Two training stages share the same predecessor.")
        next_of[predecessor] = row

    ordered = []
    seen = set()
    current = starts[0]

    while current is not None:
        current_id = current[id_key]
        if current_id in seen:
            raise RuntimeError("A cycle exists in the training stage order.")

        seen.add(current_id)
        ordered.append(
            {
                # Keep master IDs for compatibility with existing API responses
                # and the current Services_Master_archive.stage values.
                "stage_id": current["stage_id"],
                "stage_name": current[name_key],
            }
        )
        current = next_of.get(current_id)

    if len(ordered) != len(rows):
        raise RuntimeError(
            "Training stage ordering is broken: one or more stages are "
            "disconnected from the first stage."
        )

    return ordered


def load_training_stage_context(session, tenant_id=None):
    """Load tenant-specific training stages, with a master-stage fallback."""
    if tenant_id is None:
        tenant_id = request.current_user.tenant_id

    awaiting_id = cfg("STAGE_ID_AWAITING_SCHEDULING", int)
    default_id = cfg("STAGE_ID_TRAINING_DEFAULT", int)
    po_received_id = cfg("STAGE_ID_PO_RECEIVED", int)

    tenant_rows = session.execute(
        text(
            f"""
            SELECT
                m."Tenant_Pipeline_Stage_Mapping_id" AS mapping_id,
                m."Pipeline_Stage_ID" AS stage_id,
                COALESCE(NULLIF(BTRIM(m."Stage_Name"), ''), p.stage_name)
                    AS stage_name,
                m."Preceding_Stage_ID" AS preceding_id
            FROM {T("Tenant_Pipeline_Stage_Mapping")} AS m
            JOIN {T("Pipeline_Stage_Master")} AS p
                ON p.stage_id = m."Pipeline_Stage_ID"
            WHERE m."Tenant_ID" = :tenant_id
              AND p.stage_type = 2
            ORDER BY m."Tenant_Pipeline_Stage_Mapping_id"
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()

    if tenant_rows:
        for row in tenant_rows:
            if row["stage_id"] is None or not row["stage_name"]:
                raise RuntimeError(
                    "Each tenant training-stage mapping must reference a "
                    "valid Pipeline_Stage_Master row or provide a stage name."
                )

        ordered = _order_stages(
            [
                {
                    "mapping_id": row["mapping_id"],
                    "stage_id": row["stage_id"],
                    "stage_name": row["stage_name"],
                    "preceding_id": row["preceding_id"],
                }
                for row in tenant_rows
            ],
            id_key="mapping_id",
            name_key="stage_name",
            predecessor_key="preceding_id",
        )
    else:
        master_rows = session.execute(
            text(
                f"""
                SELECT
                    stage_id,
                    stage_name,
                    preceding_stage_id AS preceding_id
                FROM {T("Pipeline_Stage_Master")}
                WHERE stage_type = 2
                ORDER BY stage_id
                """
            )
        ).mappings().all()

        ordered = _order_stages(
            [
                {
                    "stage_id": row["stage_id"],
                    "stage_name": row["stage_name"],
                    "preceding_id": row["preceding_id"],
                }
                for row in master_rows
            ],
            id_key="stage_id",
            name_key="stage_name",
            predecessor_key="preceding_id",
        )

    return TrainingStageContext(
        ordered=ordered,
        awaiting_id=awaiting_id,
        default_id=default_id,
        po_received_id=po_received_id,
    )
