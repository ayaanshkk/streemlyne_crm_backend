"""
backend/routes/config_helpers.py

Shared helpers for route files:
- cfg()   read a required setting from app.config / environment
- T()     schema-qualified table name
- load_training_stage_context()
          training stages read from Stage_Master, in board order

Nothing environment-specific is hardcoded here. A missing setting raises a
RuntimeError (fail fast) instead of silently using a default.
"""

import os
import re

from flask import current_app
from sqlalchemy import text

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def cfg(key, cast=str):
    """Read a required setting from app.config or the environment."""
    value = current_app.config.get(key, os.environ.get(key))
    if value is None or str(value).strip() == "":
        raise RuntimeError(
            f"Missing required configuration '{key}'. "
            f"Set it in app.config or as an environment variable."
        )
    return cast(value)


def schema():
    """Configured schema, validated because it is interpolated into SQL."""
    value = cfg("DB_SCHEMA")
    if not _IDENTIFIER_RE.match(value):
        raise RuntimeError(f"Invalid DB_SCHEMA value: {value!r}")
    return value


def T(table_name):
    """Prefix a table with the configured schema."""
    return f'"{schema()}"."{table_name}"'


class TrainingStageContext:
    """
    Training stages as stored in Stage_Master.

    ordered      list of {"stage_id", "stage_name"} in board order, built by
                 following preceding_stage_id from the first stage.
    names        stage names in board order.
    awaiting     name of the derived "awaiting scheduling" stage.
    default      name used when a batch has no stage saved.
    po_received  name of the stage where a PO becomes mandatory.
    po_required  names of po_received and every stage after it.
    """

    def __init__(self, ordered, awaiting_id, default_id, po_received_id):
        by_id = {s["stage_id"]: s["stage_name"] for s in ordered}
        for label, sid in (
            ("STAGE_ID_AWAITING_SCHEDULING", awaiting_id),
            ("STAGE_ID_TRAINING_DEFAULT", default_id),
            ("STAGE_ID_PO_RECEIVED", po_received_id),
        ):
            if sid not in by_id:
                raise RuntimeError(
                    f"{label}={sid} is not a training stage in Stage_Master."
                )

        self.ordered = ordered
        self.names = [s["stage_name"] for s in ordered]
        self.awaiting = by_id[awaiting_id]
        self.default = by_id[default_id]
        self.po_received = by_id[po_received_id]

        ids_in_order = [s["stage_id"] for s in ordered]
        po_index = ids_in_order.index(po_received_id)
        self.po_required = self.names[po_index:]


def load_training_stage_context(session):
    """Read the training stages from Stage_Master and put them in order."""
    rows = session.execute(
        text(
            f"""
            SELECT stage_id, stage_name, preceding_stage_id
            FROM {T("Stage_Master")}
            WHERE stage_type = :stage_type
            """
        ),
        {"stage_type": cfg("STAGE_TYPE_TRAINING", int)},
    ).fetchall()

    if not rows:
        raise RuntimeError("Stage_Master has no training stages.")

    starts = [r for r in rows if r.preceding_stage_id is None]
    if len(starts) != 1:
        raise RuntimeError(
            "Stage_Master training stages need exactly one first stage "
            "(preceding_stage_id NULL); found %d." % len(starts)
        )

    next_of = {}
    for r in rows:
        if r.preceding_stage_id is not None:
            if r.preceding_stage_id in next_of:
                raise RuntimeError(
                    "Two training stages share the same preceding_stage_id "
                    f"({r.preceding_stage_id}) in Stage_Master."
                )
            next_of[r.preceding_stage_id] = r

    ordered = []
    seen = set()
    current = starts[0]
    while current is not None and current.stage_id not in seen:
        seen.add(current.stage_id)
        ordered.append(
            {"stage_id": current.stage_id, "stage_name": current.stage_name}
        )
        current = next_of.get(current.stage_id)

    if len(ordered) != len(rows):
        raise RuntimeError(
            "Stage_Master training stage order is broken: "
            "preceding_stage_id does not form one chain."
        )

    return TrainingStageContext(
        ordered,
        cfg("STAGE_ID_AWAITING_SCHEDULING", int),
        cfg("STAGE_ID_TRAINING_DEFAULT", int),
        cfg("STAGE_ID_PO_RECEIVED", int),
    )