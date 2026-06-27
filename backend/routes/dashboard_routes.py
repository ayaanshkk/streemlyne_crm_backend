"""
Dashboard Routes
GET /api/dashboard/summary  — single endpoint returning all stats
                              needed by the frontend dashboard.

Data sources (tenant-scoped):
  - ClientMaster        → total clients, new this month, recent list
  - Opportunity         → pipeline value, active jobs, stage breakdown
  - Proposal            → proposals sent this month
  - Invoice             → revenue (paid invoices)
"""

from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from flask import Blueprint, g, jsonify
from sqlalchemy import func

from database import db
from middleware import auth_required
from models import ClientMaster, OpportunityDetails, ProposalMaster, InvoiceMaster

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/summary", methods=["GET"])
@auth_required
def get_dashboard_summary():
    tid = str(g.tenant_id)
    today = date.today()
    month_start = today.replace(day=1)
    last_month_start = (month_start - relativedelta(months=1))
    last_month_end = month_start

    # ── Clients ──────────────────────────────────────────────────────────────
    total_clients = (
        ClientMaster.query
        .filter_by(tenant_id=tid)
        .count()
    )
    new_clients_this_month = (
        ClientMaster.query
        .filter(
            ClientMaster.tenant_id == tid,
            func.date(ClientMaster.created_at) >= month_start,
        )
        .count()
    )
    new_clients_last_month = (
        ClientMaster.query
        .filter(
            ClientMaster.tenant_id == tid,
            func.date(ClientMaster.created_at) >= last_month_start,
            func.date(ClientMaster.created_at) < last_month_end,
        )
        .count()
    )

    # Recent clients for table
    recent_clients = (
        ClientMaster.query
        .filter_by(tenant_id=tid)
        .order_by(ClientMaster.created_at.desc())
        .limit(10)
        .all()
    )

    # ── Opportunities / Pipeline ──────────────────────────────────────────────
    all_opps = (
        OpportunityDetails.query
        .filter_by(tenant_id=tid)
        .all()
    )
    pipeline_value = sum(
        float(o.estimated_value) for o in all_opps if o.estimated_value
    )
    
    active_jobs = len([
        o for o in all_opps
        if o.stage and o.stage.stage_name not in ("Won", "Lost", "Cancelled")
    ])
    won_jobs = len([
        o for o in all_opps
        if o.stage and o.stage.stage_name == "Won"
    ])

    stage_breakdown = {}
    for o in all_opps:
        stage = o.stage or "Unknown"
        stage_breakdown[stage] = stage_breakdown.get(stage, 0) + 1

    # ── Proposals ────────────────────────────────────────────────────────────
    proposals_this_month = 0
    proposals_last_month = 0
    try:
        proposals_this_month = (
            ProposalMaster.query
            .filter(
                ProposalMaster.client_id.in_(
                    [c.client_id for c in ClientMaster.query.filter_by(tenant_id=tid).all()]
                ),
                func.date(ProposalMaster.created_at) >= month_start,
            )
            .count()
        )
        proposals_last_month = (
            ProposalMaster.query
            .filter(
                ProposalMaster.client_id.in_(
                    [c.client_id for c in ClientMaster.query.filter_by(tenant_id=tid).all()]
                ),
                func.date(ProposalMaster.created_at) >= last_month_start,
                func.date(ProposalMaster.created_at) < last_month_end,
            )
            .count()
        )

    except Exception:
        pass

    # ── Revenue (paid invoices) ───────────────────────────────────────────────
    revenue_this_month = 0.0
    revenue_last_month = 0.0
    revenue_last_6_months = 0.0
    monthly_revenue_chart = []
    try:
        paid_invoices = (
            InvoiceMaster.query
            .filter(
                InvoiceMaster.client_id.in_(
                    [c.client_id for c in ClientMaster.query.filter_by(tenant_id=tid).all()]
                ),
                InvoiceMaster.payment_status == "Paid",
            )
            .all()
        )

        for inv in paid_invoices:
            inv_date = inv.created_at.date() if inv.created_at else None
            if not inv_date:
                continue
            amount = float(inv.total_amount or 0)
            if inv_date >= month_start:
                revenue_this_month += amount
            if last_month_start <= inv_date < last_month_end:
                revenue_last_month += amount
            if inv_date >= (today - relativedelta(months=6)):
                revenue_last_6_months += amount

        # Build 6-month chart data
        for i in range(5, -1, -1):
            m_start = (today - relativedelta(months=i)).replace(day=1)
            m_end = m_start + relativedelta(months=1)
            m_revenue = sum(
                float(inv.amount_paid or 0)
                for inv in paid_invoices
                if inv.paid_date and m_start <= inv.paid_date < m_end.date()
            )
            monthly_revenue_chart.append({
                "month": m_start.strftime("%b %Y"),
                "revenue": round(m_revenue, 2),
            })
    except Exception:
        pass

    # ── Delta helpers ─────────────────────────────────────────────────────────
    def _pct_change(current, previous):
        if previous == 0:
            return None
        return round(((current - previous) / previous) * 100, 1)

    # ── Recent clients formatted for table ────────────────────────────────────
    recent_leads_table = [
        {
            "id":      str(c.client_id),
            "name":    c.client_contact_name or c.client_company_name or "—",
            "company": c.client_company_name or "—",
            "email":   c.client_email,
            "phone":   c.client_phone,
            "stage":   c.stage or "Prospect",
            "source":  "—",
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in recent_clients
    ]

    return jsonify({
        "clients": {
            "total":            total_clients,
            "new_this_month":   new_clients_this_month,
            "new_last_month":   new_clients_last_month,
            "pct_change":       _pct_change(new_clients_this_month, new_clients_last_month),
        },
        "pipeline": {
            "total_value":      round(pipeline_value, 2),
            "active_jobs":      active_jobs,
            "won_jobs":         won_jobs,
            "stage_breakdown":  stage_breakdown,
        },
        "proposals": {
            "this_month":       proposals_this_month,
            "last_month":       proposals_last_month,
            "pct_change":       _pct_change(proposals_this_month, proposals_last_month),
        },
        "revenue": {
            "this_month":       round(revenue_this_month, 2),
            "last_month":       round(revenue_last_month, 2),
            "last_6_months":    round(revenue_last_6_months, 2),
            "pct_change":       _pct_change(revenue_this_month, revenue_last_month),
            "monthly_chart":    monthly_revenue_chart,
        },
        "recent_leads":         recent_leads_table,
    }), 200