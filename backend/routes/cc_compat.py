# FILE LOCATION: routes/cc_compat.py
#
# Compatibility layer so the Company/Contact route files (ported from FAI) run
# inside StreemLyne without rewriting every route body.
#
#   token_required  -> StreemLyne's @auth_required, then exposes the identity the
#                      ported code expects as request.current_user.tenant_id /
#                      .employee_id (taken from flask.g, as in client_routes.py)
#   SessionLocal()  -> a plain SQLAlchemy Session bound to StreemLyne's engine
#                      (the ported code uses raw SQL via session.execute(text(...)),
#                       session.commit(), session.rollback(), session.close())
#   SCHEMA          -> StreemLyne's configured schema (database.DB_SCHEMA), instead
#                      of the hard-coded "streemLyne_mt_dev2"
from functools import wraps
from types import SimpleNamespace

from flask import g, request
from sqlalchemy.orm import Session

from database import db, DB_SCHEMA
from middleware import auth_required

SCHEMA = DB_SCHEMA


def SessionLocal() -> Session:
    return Session(bind=db.engine)


def token_required(fn):
    @wraps(fn)
    def _with_identity(*args, **kwargs):
        request.current_user = SimpleNamespace(
            tenant_id=g.tenant_id,
            employee_id=getattr(g, "employee_id", None),
            user_id=getattr(g, "user_id", None),
        )
        return fn(*args, **kwargs)

    return auth_required(_with_identity)
