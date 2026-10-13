import os
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from fai.db import SessionLocal


class TenantOnboardingError(Exception):
    pass


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _find_col(columns: Dict[str, str], candidates: Tuple[str, ...], required: bool = False) -> Optional[str]:
    for candidate in candidates:
        col = columns.get(candidate.lower())
        if col:
            return col
    if required:
        raise TenantOnboardingError(f"Required column not found. Tried: {', '.join(candidates)}")
    return None


def _qualified_table(schema_name: str, table_name: str) -> str:
    return f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"


def _resolve_tenant_table(session) -> Tuple[str, str]:
    env_schema = (os.getenv("TENANT_TABLE_SCHEMA") or "StreamLyne_MT").strip()
    env_table = (os.getenv("TENANT_TABLE_NAME") or "Tenant_Master").strip()
    schema_candidates = [env_schema, "public"]
    table_candidates = [env_table, "tenant_master"]

    rows = session.execute(
        text(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND lower(table_name) = 'tenant_master'
            """
        )
    ).fetchall()

    if not rows:
        raise TenantOnboardingError("Tenant master table was not found.")

    ranked: Dict[Tuple[str, str], int] = {}
    for row in rows:
        schema_name, table_name = row[0], row[1]
        rank = 100
        if schema_name in schema_candidates:
            rank -= 50
            rank += schema_candidates.index(schema_name)
        if table_name in table_candidates:
            rank -= 40
            rank += table_candidates.index(table_name)
        ranked[(schema_name, table_name)] = rank

    chosen = sorted(ranked, key=ranked.get)[0]
    return chosen[0], chosen[1]


def _tenant_table_columns(session, schema_name: str, table_name: str) -> Dict[str, str]:
    rows = session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema_name
              AND table_name = :table_name
            """
        ),
        {"schema_name": schema_name, "table_name": table_name},
    ).fetchall()

    if not rows:
        raise TenantOnboardingError(
            f"Table {_qualified_table(schema_name, table_name)} has no readable columns."
        )

    return {row[0].lower(): row[0] for row in rows}


def _parse_iso_date(value: Any, field_name: str) -> date:
    if value in (None, ""):
        return datetime.utcnow().date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TenantOnboardingError(f"{field_name} must be in YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TenantOnboardingError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def _parse_bool(value: Any, field_name: str) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise TenantOnboardingError(f"{field_name} must be true or false.")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "y"):
            return True
        if normalized in ("false", "0", "no", "n"):
            return False
    raise TenantOnboardingError(f"{field_name} must be true or false.")


def _validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise TenantOnboardingError("JSON payload is required.")

    tenant_company_name = (
        payload.get("tenant_company_name")
        or payload.get("tenant_name")
        or ""
    ).strip()
    if not tenant_company_name:
        raise TenantOnboardingError("tenant_company_name is required.")

    tenant_contact_name = (payload.get("tenant_contact_name") or "").strip() or None
    onboarding_date = _parse_iso_date(payload.get("onboarding_date"), "onboarding_date")
    is_active = _parse_bool(payload.get("is_active"), "is_active")

    return {
        "tenant_company_name": tenant_company_name,
        "tenant_contact_name": tenant_contact_name,
        "onboarding_date": onboarding_date,
        "is_active": is_active,
    }


def _find_existing_tenant_id(session, table_ref: str, id_col: str, name_col: str, tenant_name: str):
    return session.execute(
        text(
            f"""
            SELECT {_quote_ident(id_col)}
            FROM {table_ref}
            WHERE LOWER(COALESCE({_quote_ident(name_col)}::text, '')) = LOWER(:tenant_company_name)
            LIMIT 1
            """
        ),
        {"tenant_company_name": tenant_name},
    ).scalar()


def create_tenant(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _validate_payload(payload)
    session = SessionLocal()
    try:
        schema_name, table_name = _resolve_tenant_table(session)
        table_ref = _qualified_table(schema_name, table_name)
        cols = _tenant_table_columns(session, schema_name, table_name)

        id_col = _find_col(cols, ("Tenant_id", "tenant_id", "TenantId", "tenantid"), required=True)
        name_col = _find_col(cols, ("tenant_company_name", "tenant_name", "tenantname", "name"), required=True)
        contact_col = _find_col(cols, ("tenant_contact_name", "contact_name", "contactperson"))
        onboarding_col = _find_col(cols, ("onboarding_date", "onboardingdate"))
        is_active_col = _find_col(cols, ("is_active", "active"))
        created_col = _find_col(cols, ("created_at", "createdon", "created_on"))
        updated_col = _find_col(cols, ("updated_at", "updatedon", "updated_on"))

        existing_id = _find_existing_tenant_id(
            session=session,
            table_ref=table_ref,
            id_col=id_col,
            name_col=name_col,
            tenant_name=data["tenant_company_name"],
        )
        if existing_id is not None:
            raise TenantOnboardingError(
                f"Tenant '{data['tenant_company_name']}' already exists with {id_col}={existing_id}."
            )

        insert_cols = [id_col, name_col]
        select_vals = [f"COALESCE(MAX({_quote_ident(id_col)}), 0) + 1", ":tenant_company_name"]
        params = {"tenant_company_name": data["tenant_company_name"]}

        if contact_col:
            insert_cols.append(contact_col)
            select_vals.append(":tenant_contact_name")
            params["tenant_contact_name"] = data["tenant_contact_name"]
        if onboarding_col:
            insert_cols.append(onboarding_col)
            select_vals.append(":onboarding_date")
            params["onboarding_date"] = data["onboarding_date"]
        if is_active_col:
            insert_cols.append(is_active_col)
            select_vals.append(":is_active")
            params["is_active"] = data["is_active"]

        now = datetime.utcnow()
        if created_col:
            insert_cols.append(created_col)
            select_vals.append(":created_at")
            params["created_at"] = now
        if updated_col:
            insert_cols.append(updated_col)
            select_vals.append(":updated_at")
            params["updated_at"] = now

        insert_cols_sql = ", ".join(_quote_ident(col) for col in insert_cols)
        select_vals_sql = ", ".join(select_vals)

        inserted = None
        for attempt in range(2):
            try:
                inserted = session.execute(
                    text(
                        f"""
                        INSERT INTO {table_ref} ({insert_cols_sql})
                        SELECT {select_vals_sql}
                        FROM {table_ref}
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM {table_ref}
                            WHERE LOWER(COALESCE({_quote_ident(name_col)}::text, '')) = LOWER(:tenant_company_name)
                        )
                        RETURNING {_quote_ident(id_col)}
                        """
                    ),
                    params,
                ).first()
                session.commit()
                break
            except IntegrityError:
                session.rollback()
                existing_id = _find_existing_tenant_id(
                    session=session,
                    table_ref=table_ref,
                    id_col=id_col,
                    name_col=name_col,
                    tenant_name=data["tenant_company_name"],
                )
                if existing_id is not None:
                    raise TenantOnboardingError(
                        f"Tenant '{data['tenant_company_name']}' already exists with {id_col}={existing_id}."
                    )
                if attempt == 1:
                    raise TenantOnboardingError("Tenant insert failed due to concurrent writes.")

        if not inserted:
            raise TenantOnboardingError(f"Tenant '{data['tenant_company_name']}' already exists.")

        return {
            "tenant_id": int(inserted[0]),
            "tenant_company_name": data["tenant_company_name"],
            "tenant_contact_name": data["tenant_contact_name"],
            "onboarding_date": data["onboarding_date"].isoformat(),
            "is_active": data["is_active"],
            "message": (
                "Inserted into Tenant_Master only. Existing tenants were not modified."
            ),
        }
    except TenantOnboardingError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise TenantOnboardingError(f"Failed to create tenant: {exc}") from exc
    finally:
        session.close()


def resolve_tenant_context(
    tenant_id: Optional[int] = None,
    tenant_name: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    effective_name = tenant_name or tenant_slug
    session = SessionLocal()
    try:
        schema_name, table_name = _resolve_tenant_table(session)
        table_ref = _qualified_table(schema_name, table_name)
        cols = _tenant_table_columns(session, schema_name, table_name)

        id_col = _find_col(cols, ("Tenant_id", "tenant_id", "TenantId", "tenantid"), required=True)
        name_col = _find_col(cols, ("tenant_company_name", "tenant_name", "tenantname", "name"), required=True)
        active_col = _find_col(cols, ("is_active", "active"))

        conditions = []
        params: Dict[str, Any] = {}
        if tenant_id is not None:
            conditions.append(f"{_quote_ident(id_col)} = :tenant_id")
            params["tenant_id"] = tenant_id
        elif effective_name:
            conditions.append(f"LOWER(COALESCE({_quote_ident(name_col)}::text, '')) = LOWER(:tenant_name)")
            params["tenant_name"] = effective_name
        else:
            return None

        where_sql = " AND ".join(conditions)
        row = session.execute(
            text(
                f"""
                SELECT {_quote_ident(id_col)} AS tenant_id,
                       {_quote_ident(name_col)} AS tenant_name
                FROM {table_ref}
                WHERE {where_sql}
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()

        if not row:
            return None

        if active_col:
            active = session.execute(
                text(
                    f"""
                    SELECT {_quote_ident(active_col)}
                    FROM {table_ref}
                    WHERE {_quote_ident(id_col)} = :tenant_id
                    """
                ),
                {"tenant_id": row["tenant_id"]},
            ).scalar_one()
            if active is False:
                return None

        return {
            "tenant_id": int(row["tenant_id"]) if row["tenant_id"] is not None else None,
            "tenant_name": row["tenant_name"],
        }
    finally:
        session.close()
