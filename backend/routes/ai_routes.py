"""
AI Routes - Claude API Agentic CRM Assistant
Runs the full tool-use agentic loop server-side.

Endpoints:
  POST /api/ai/chat   — main agentic chat endpoint
"""

import openai
import os
import json
import requests
from datetime import datetime
from flask import Blueprint, g, jsonify, request
from middleware import auth_required
from models import (
    ClientMaster, EmployeeMaster,
    ClientInteractions, ContactMethodMaster,
)
from limiter import limiter
from services.usage_service import check_ai_limit, record_ai_message
from database import db
from sqlalchemy import func, case

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

# ── Constants ─────────────────────────────────────────────────────────────────

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"
MAX_TOKENS     = 8096
MAX_ITERATIONS = 5

STAGES = [
    "Lead", "Qualified", "Contact Made", "Meeting Scheduled",
    "Quote Sent", "Negotiation", "Closed Won", "Closed Lost", "On Hold",
]

# ── Tools definition ──────────────────────────────────────────────────────────

def get_tools():
    return [
        {
            "name": "create_customer",
            "description": "Create a new customer/client record in the CRM",
            "input_schema": {
                "type": "object",
                "properties": {
                    "client_contact_name": {"type": "string", "description": "Full name of the contact person"},
                    "client_company_name": {"type": "string", "description": "Company or business name"},
                    "client_email":        {"type": "string", "description": "Email address"},
                    "client_phone":        {"type": "string", "description": "Phone number"},
                    "address":             {"type": "string", "description": "Street address"},
                    "post_code":           {"type": "string", "description": "Postcode"},
                    "stage": {
                        "type": "string",
                        "enum": STAGES,
                        "description": "Pipeline stage. Always default to 'Lead' unless user specifies."
                    },
                    "notes": {"type": "string", "description": "Additional notes"},
                },
                "required": [],
            },
        },
        {
            "name": "get_customer_details",
            "description": "Get full details of a specific customer by name or ID",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_term": {"type": "string", "description": "Customer name, company, email or phone to search for"},
                    "client_id":   {"type": "integer", "description": "Specific client ID if known"},
                },
                "required": [],
            },
        },
        {
            "name": "list_customers",
            "description": "List customers with optional filters",
            "input_schema": {
                "type": "object",
                "properties": {
                    "stage":       {"type": "string", "enum": STAGES, "description": "Filter by pipeline stage"},
                    "search_term": {"type": "string", "description": "Search by name, company, email or phone"},
                    "limit":       {"type": "integer", "description": "Max number of results (default 20)"},
                },
                "required": [],
            },
        },
        {
            "name": "update_customer",
            "description": "Update an existing customer's details",
            "input_schema": {
                "type": "object",
                "properties": {
                    "client_id":           {"type": "integer", "description": "ID of customer to update"},
                    "search_term":         {"type": "string",  "description": "Search term to find customer if ID unknown"},
                    "client_contact_name": {"type": "string",  "description": "Updated contact name"},
                    "client_company_name": {"type": "string",  "description": "Updated company name"},
                    "client_email":        {"type": "string",  "description": "Updated email"},
                    "client_phone":        {"type": "string",  "description": "Updated phone"},
                    "address":             {"type": "string",  "description": "Updated address"},
                    "post_code":           {"type": "string",  "description": "Updated postcode"},
                    "notes":               {"type": "string",  "description": "Updated notes"},
                },
                "required": [],
            },
        },
        {
            "name": "update_customer_stage",
            "description": "Update a customer's pipeline stage",
            "input_schema": {
                "type": "object",
                "properties": {
                    "client_id":   {"type": "integer", "description": "ID of customer"},
                    "search_term": {"type": "string",  "description": "Search term to find customer if ID unknown"},
                    "stage":       {"type": "string",  "enum": STAGES, "description": "New pipeline stage"},
                },
                "required": ["stage"],
            },
        },
        {
            "name": "get_pipeline_summary",
            "description": "Get a summary of all customers by pipeline stage with counts and conversion rate",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "get_calendar_events",
            "description": "Get calendar events/meetings within a date range",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "end_date":   {"type": "string", "description": "End date in YYYY-MM-DD format"},
                    "limit":      {"type": "integer", "description": "Max results (default 20)"},
                },
                "required": [],
            },
        },
        {
            "name": "create_calendar_event",
            "description": "Create a new calendar event or meeting",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title":       {"type": "string", "description": "Event title"},
                    "start_date":  {"type": "string", "description": "Start date/time in YYYY-MM-DD or YYYY-MM-DDTHH:MM format"},
                    "end_date":    {"type": "string", "description": "End date/time (optional)"},
                    "description": {"type": "string", "description": "Event description or notes"},
                    "client_id":   {"type": "integer","description": "Associated customer ID (optional)"},
                },
                "required": ["title", "start_date"],
            },
        },
        {
            "name": "search_pricelist",
            "description": "Search the product/service pricelist",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_term": {"type": "string", "description": "Product or service name to search for"},
                },
                "required": ["search_term"],
            },
        },
        {
            "name": "create_quote",
            "description": "Create a new quote/proposal for a customer",
            "input_schema": {
                "type": "object",
                "properties": {
                    "client_id":   {"type": "integer", "description": "Customer ID to create quote for"},
                    "search_term": {"type": "string",  "description": "Search term to find customer if ID unknown"},
                    "items": {
                        "type": "array",
                        "description": "List of items in the quote",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "quantity":    {"type": "number"},
                                "unit_price":  {"type": "number"},
                            },
                        },
                    },
                    "notes": {"type": "string", "description": "Additional notes for the quote"},
                },
                "required": [],
            },
        },
        {
            "name": "get_quotes",
            "description": "Get quotes/proposals, optionally filtered by customer",
            "input_schema": {
                "type": "object",
                "properties": {
                    "client_id":   {"type": "integer", "description": "Filter by customer ID"},
                    "search_term": {"type": "string",  "description": "Search by customer name"},
                    "limit":       {"type": "integer", "description": "Max results (default 20)"},
                },
                "required": [],
            },
        },
    ]


# ── Tool execution ────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, args: dict) -> dict:
    tenant_id = str(g.tenant_id)

    def find_client(args):
        client_id = args.get('client_id')
        if client_id:
            return ClientMaster.query.filter_by(client_id=client_id, tenant_id=tenant_id).first()
        search = args.get('search_term', '')
        if search:
            return ClientMaster.query.filter(
                ClientMaster.tenant_id == tenant_id,
                db.or_(
                    ClientMaster.client_contact_name.ilike(f'%{search}%'),
                    ClientMaster.client_company_name.ilike(f'%{search}%'),
                    ClientMaster.client_email.ilike(f'%{search}%'),
                    ClientMaster.client_phone.ilike(f'%{search}%'),
                )
            ).first()
        return None

    def client_to_dict(c):
        return {
            'client_id':           c.client_id,
            'client_contact_name': getattr(c, 'client_contact_name', None),
            'client_company_name': getattr(c, 'client_company_name', None),
            'client_email':        getattr(c, 'client_email', None),
            'client_phone':        getattr(c, 'client_phone', None),
            'address':             getattr(c, 'address', None),
            'post_code':           getattr(c, 'post_code', None),
            'stage':               getattr(c, 'stage', None),
            'notes':               getattr(c, 'notes', None),
            'created_at':          c.created_at.strftime('%Y-%m-%d at %H:%M') if getattr(c, 'created_at', None) else None,
            'stage_updated_at':    c.stage_updated_at.strftime('%Y-%m-%d at %H:%M') if getattr(c, 'stage_updated_at', None) else None,
        }

    # ── create_customer ───────────────────────────────────────────────────────
    if tool_name == 'create_customer':
        client = ClientMaster(
            tenant_id=              tenant_id,
            client_contact_name=    args.get('client_contact_name'),
            client_company_name=    args.get('client_company_name') or args.get('client_contact_name') or 'Unknown',
            client_email=           args.get('client_email'),
            client_phone=           args.get('client_phone'),
            address=                args.get('address'),
            post_code=              args.get('post_code'),
            stage=                  args.get('stage', 'Lead'),
            created_at=             datetime.utcnow(),
            created_by_employee_id= getattr(g, 'employee_id', None),
        )
        db.session.add(client)
        db.session.commit()
        return {
            'success': True,
            'message': f"Created customer {client.client_contact_name or client.client_company_name}",
            'data':    client_to_dict(client),
        }

    # ── get_customer_details ──────────────────────────────────────────────────
    if tool_name == 'get_customer_details':
        client = find_client(args)
        if not client:
            return {'success': False, 'message': 'Customer not found'}
        interactions = ClientInteractions.query.filter_by(client_id=client.client_id)\
            .order_by(ClientInteractions.created_at.desc()).limit(5).all()
        interaction_list = [{
            'date':        i.contact_date.strftime('%Y-%m-%d') if i.contact_date else None,
            'call_status': i.next_steps,
            'notes':       i.notes,
        } for i in interactions]
        data = client_to_dict(client)
        data['recent_interactions'] = interaction_list
        return {'success': True, 'data': data}

    # ── list_customers ────────────────────────────────────────────────────────
    if tool_name == 'list_customers':
        query = ClientMaster.query.filter_by(tenant_id=tenant_id)
        if args.get('stage'):
            query = query.filter_by(stage=args['stage'])
        if args.get('search_term'):
            s = args['search_term']
            query = query.filter(db.or_(
                ClientMaster.client_contact_name.ilike(f'%{s}%'),
                ClientMaster.client_company_name.ilike(f'%{s}%'),
                ClientMaster.client_email.ilike(f'%{s}%'),
                ClientMaster.client_phone.ilike(f'%{s}%'),
            ))
        limit   = min(args.get('limit', 20), 50)
        clients = query.order_by(ClientMaster.created_at.desc()).limit(limit).all()
        return {'success': True, 'count': len(clients), 'data': [client_to_dict(c) for c in clients]}

    # ── update_customer ───────────────────────────────────────────────────────
    if tool_name == 'update_customer':
        client = find_client(args)
        if not client:
            return {'success': False, 'message': 'Customer not found'}
        for field in ['client_contact_name','client_company_name','client_email','client_phone','address','post_code','notes']:
            if args.get(field) is not None:
                setattr(client, field, args[field])
        db.session.commit()
        return {'success': True, 'message': 'Customer updated', 'data': client_to_dict(client)}

    # ── update_customer_stage ─────────────────────────────────────────────────
    if tool_name == 'update_customer_stage':
        client = find_client(args)
        if not client:
            return {'success': False, 'message': 'Customer not found'}
        new_stage = args.get('stage')
        if new_stage not in STAGES:
            return {'success': False, 'message': f'Invalid stage. Must be one of: {STAGES}'}
        client.stage = new_stage
        if hasattr(client, 'stage_updated_at'):
            client.stage_updated_at = datetime.utcnow()
        db.session.commit()
        name = client.client_contact_name or client.client_company_name or f'Client {client.client_id}'
        return {'success': True, 'message': f"Updated {name}'s stage to {new_stage}", 'data': client_to_dict(client)}

    # ── get_pipeline_summary ──────────────────────────────────────────────────
    if tool_name == 'get_pipeline_summary':
        clients = ClientMaster.query.filter_by(tenant_id=tenant_id).all()
        total   = len(clients)
        by_stage = {stage: sum(1 for c in clients if c.stage == stage) for stage in STAGES}
        closed_won   = by_stage.get('Closed Won', 0)
        closed_lost  = by_stage.get('Closed Lost', 0)
        total_closed = closed_won + closed_lost
        conversion_rate = round((closed_won / total_closed * 100), 1) if total_closed > 0 else 0
        return {
            'success':         True,
            'total_customers': total,
            'by_stage':        by_stage,
            'closed_won':      closed_won,
            'closed_lost':     closed_lost,
            'conversion_rate': f'{conversion_rate}%',
        }

    # ── get_calendar_events ───────────────────────────────────────────────────
    if tool_name == 'get_calendar_events':
        from models import TasksMaster
        query = TasksMaster.query.filter_by(tenant_id=tenant_id)
        if args.get('start_date'):
            try:
                start = datetime.strptime(args['start_date'], '%Y-%m-%d')
                query = query.filter(TasksMaster.due_date >= start)
            except (ValueError, AttributeError):
                pass
        if args.get('end_date'):
            try:
                end = datetime.strptime(args['end_date'], '%Y-%m-%d')
                query = query.filter(TasksMaster.due_date <= end)
            except (ValueError, AttributeError):
                pass
        limit = min(args.get('limit', 20), 50)
        try:
            tasks = query.order_by(TasksMaster.due_date.asc()).limit(limit).all()
            return {
                'success': True,
                'count':   len(tasks),
                'data': [{
                    'task_id':   t.task_id,
                    'title':     getattr(t, 'task_title', None) or getattr(t, 'title', None),
                    'due_date':  t.due_date.strftime('%Y-%m-%d') if getattr(t, 'due_date', None) else None,
                    'status':    getattr(t, 'status', None),
                    'client_id': getattr(t, 'client_id', None),
                } for t in tasks],
            }
        except Exception:
            return {'success': True, 'count': 0, 'data': [], 'message': 'No calendar data available'}

    # ── create_calendar_event ─────────────────────────────────────────────────
    if tool_name == 'create_calendar_event':
        from models import TasksMaster
        title     = args.get('title', 'Meeting')
        start_str = args.get('start_date', '')
        try:
            if 'T' in start_str or ' ' in start_str:
                due_date = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M').date()
            else:
                due_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        except ValueError:
            due_date = datetime.utcnow().date()
        try:
            task = TasksMaster(
                tenant_id=  tenant_id,
                task_title= title,
                due_date=   due_date,
                notes=      args.get('description'),
                client_id=  args.get('client_id'),
                created_at= datetime.utcnow(),
            )
            db.session.add(task)
            db.session.commit()
            return {'success': True, 'message': f"Scheduled: {title} on {due_date}", 'task_id': task.task_id}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': f'Could not create event: {str(e)}'}

    # ── search_pricelist ──────────────────────────────────────────────────────
    if tool_name == 'search_pricelist':
        search = args.get('search_term', '')
        try:
            from models import ServicesMaster
            items = ServicesMaster.query.filter(
                ServicesMaster.tenant_id == tenant_id,
                ServicesMaster.service_title.ilike(f'%{search}%'),
            ).limit(20).all()
            return {
                'success': True,
                'count':   len(items),
                'data': [{'item_id': i.service_id, 'item_name': i.service_title, 'price': float(i.service_rate) if i.service_rate else 0, 'unit': None} for i in items],
            }
        except Exception as e:
            return {'success': False, 'message': f'Pricelist search failed: {str(e)}'}

    # ── create_quote ──────────────────────────────────────────────────────────
    if tool_name == 'create_quote':
        from models import Quotation, QuotationItem
        client = find_client(args)
        if not client:
            return {'success': False, 'message': 'Customer not found. Please specify a valid customer.'}
        items_data = args.get('items', [])
 
        # Auto-generate reference number
        from sqlalchemy import text as sa_text
        row = db.session.execute(
            sa_text("""
                SELECT reference_number FROM "StreemLyne_MT"."Quotations"
                WHERE tenant_id = :tid
                ORDER BY quotation_id DESC LIMIT 1
            """),
            {'tid': tenant_id}
        ).fetchone()
        if row and row[0] and row[0].startswith('QT-'):
            try:
                ref = f"QT-{int(row[0].split('-')[1]) + 1:05d}"
            except Exception:
                ref = 'QT-00001'
        else:
            ref = 'QT-00001'
 
        quotation = Quotation(
            tenant_id=        tenant_id,
            client_id=        client.client_id,
            reference_number= ref,
            status=           'Draft',
            notes=            args.get('notes'),
            vat_percentage=   20,
            customer_name=    client.client_contact_name or client.client_company_name,
            customer_email=   client.client_email,
            customer_phone=   client.client_phone,
            customer_address= client.address,
        )
        db.session.add(quotation)
        db.session.flush()
 
        sub_total = 0
        for item in items_data:
            qty   = float(item.get('quantity', 1))
            price = float(item.get('unit_price', 0))
            qi = QuotationItem(
                quotation_id= quotation.quotation_id,
                item_name=    item.get('description', 'Item'),
                quantity=     int(qty),
                amount=       price,
                source=       'manual',
            )
            db.session.add(qi)
            sub_total += qty * price
 
        from decimal import Decimal
        quotation.total = Decimal(str(sub_total * 1.2))  # 20% VAT
        db.session.commit()
 
        client_name = client.client_contact_name or client.client_company_name or 'Customer'
        return {
            'success':      True,
            'message':      f'Quote {ref} created for {client_name}',
            'quotation_id': quotation.quotation_id,
            'reference':    ref,
            'total':        float(quotation.total),
            'view_url':     f'/dashboard/quotes/{quotation.quotation_id}/view',
        }
 
    # ── get_quotes ────────────────────────────────────────────────────────────
    if tool_name == 'get_quotes':
        from models import Quotation
        query = Quotation.query.join(
            ClientMaster, Quotation.client_id == ClientMaster.client_id
        ).filter(ClientMaster.tenant_id == tenant_id)
 
        if args.get('client_id'):
            query = query.filter(Quotation.client_id == args['client_id'])
        if args.get('search_term'):
            s = args['search_term']
            client_ids = [c.client_id for c in ClientMaster.query.filter(
                ClientMaster.tenant_id == tenant_id,
                db.or_(
                    ClientMaster.client_contact_name.ilike(f'%{s}%'),
                    ClientMaster.client_company_name.ilike(f'%{s}%'),
                )
            ).all()]
            if client_ids:
                query = query.filter(Quotation.client_id.in_(client_ids))
 
        limit      = min(args.get('limit', 20), 50)
        quotations = query.order_by(Quotation.created_at.desc()).limit(limit).all()
        results    = []
        for q in quotations:
            client      = ClientMaster.query.filter_by(client_id=q.client_id).first()
            client_name = (client.client_contact_name or client.client_company_name or 'Unknown') if client else 'Unknown'
            results.append({
                'quotation_id':    q.quotation_id,
                'reference':       q.reference_number,
                'client_name':     client_name,
                'total':           float(q.total) if q.total else 0,
                'status':          q.status or 'Draft',
                'created_at':      q.created_at.strftime('%Y-%m-%d') if q.created_at else None,
                'view_url':        f'/dashboard/quotes/{q.quotation_id}/view',
            })
        return {'success': True, 'count': len(results), 'data': results}

    return {'error': f'Unknown tool: {tool_name}'}



# ── OpenAI chat for free plan ─────────────────────────────────────────────────

def _chat_with_openai(message: str, history: list) -> dict:
    """Lightweight GPT-4o-mini response for free plan demo users."""
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    system_prompt = (
        "You are StreemAI, a helpful CRM assistant for StreemLyne. "
        "You can answer questions about CRM best practices, sales pipeline management, "
        "customer relationships, and help users understand how to use the platform. "
        "You are in demo mode — you cannot perform actions like creating customers, "
        "updating records, or accessing live data in this mode. "
        "Keep responses concise and helpful. Always suggest upgrading to a paid plan "
        "if the user wants to perform real actions in their CRM.\n\n"
        f"Today's date is {datetime.now().strftime('%A, %d %B %Y')}."
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Include last 6 turns of history to keep costs low
    for turn in history[-6:]:
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant"):
            content = turn.get("content", "")
            if isinstance(content, str):
                messages.append({"role": turn["role"], "content": content})
            elif isinstance(content, list):
                # Claude format — extract text blocks only
                text = " ".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                if text:
                    messages.append({"role": turn["role"], "content": text})

    messages.append({"role": "user", "content": message})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        reply = response.choices[0].message.content or "I'm not sure how to help with that."
    except Exception as e:
        print(f"[OPENAI] Error: {e}")
        reply = "I'm having trouble connecting right now. Please try again."

    updated_history = list(history) + [
        {"role": "user",      "content": message},
        {"role": "assistant", "content": reply},
    ]

    return {
        "response":             reply,
        "conversation_history": updated_history,
        "action_metadata":      None,
    }

# ── Chat route ────────────────────────────────────────────────────────────────

@ai_bp.route('/chat', methods=['POST'])
@auth_required
@limiter.limit("20 per hour")
def chat():
    data    = request.get_json() or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Message is required'}), 400

    # ── AI usage limit check ──────────────────────────────────────────────────
    limit_err = check_ai_limit(str(g.tenant_id))
    if limit_err:
        return jsonify({
            'error':         limit_err,
            'limit_reached': True,
            'resource':      'ai_messages',
        }), 403

    conversation_history = data.get('conversation_history', [])

    # ── Determine plan and route to correct AI ────────────────────────────────
    use_claude = False
    try:
        from services.subscription_service import SubscriptionService
        from models import SubscriptionPlan
        sub = SubscriptionService().get_active_subscription(str(g.tenant_id))
        if sub:
            plan = db.session.get(SubscriptionPlan, sub.subscription_id)
            if plan:
                plan_code = (plan.subscription_code or "FREE").upper()
                use_claude = plan_code in ("STARTER", "PRO", "CUSTOM")
    except Exception as e:
        print(f"[AI] Plan check failed, defaulting to OpenAI: {e}")
        use_claude = False

    # ── Free plan — OpenAI demo response ─────────────────────────────────────
    if not use_claude:
        try:
            result = _chat_with_openai(message, conversation_history)
            try:
                record_ai_message(
                    tenant_id=str(g.tenant_id),
                    user_id=getattr(g, 'user_id', None),
                )
            except Exception as e:
                print(f"[USAGE] Failed to record AI message: {e}")
            return jsonify(result), 200
        except Exception as e:
            print(f"[OPENAI] Chat failed: {e}")
            return jsonify({'error': 'AI service unavailable. Please try again.'}), 500

    # ── Paid plan — Claude agentic response ───────────────────────────────────

    # ── System prompt ─────────────────────────────────────────────────────────
    system_prompt = (
        "You are StreemAI, an intelligent CRM assistant for StreemLyne. "
        "You help sales teams manage customers, track pipeline stages, schedule meetings, "
        "create quotes, and analyse performance data.\n\n"

        "## Your Capabilities\n"
        "You have access to tools that let you:\n"
        "- Create, update, and retrieve customer records\n"
        "- Manage pipeline stages and track deal progress\n"
        "- Schedule and retrieve calendar events/meetings\n"
        "- Search the customer database\n"
        "- Create and retrieve quotes/proposals\n"
        "- Search the product/service pricelist\n"
        "- Analyse conversion rates and pipeline performance\n\n"

        "## Pipeline Stages\n"
        f"Valid pipeline stages (in order): {', '.join(STAGES)}\n"
        "- Always default new customers to 'Lead' unless the user specifies otherwise\n"
        "- Never use 'Prospect' — the correct first stage is 'Lead'\n\n"

        "## Guided Actions\n"
        "After EVERY response where you complete an action or show data, suggest 2-3 "
        "specific next steps the user can take. Format each suggestion on its own line "
        "starting with '→ ' (arrow + space). Make suggestions specific to the actual "
        "data — use real customer names, stages, and amounts.\n\n"
        "Examples:\n"
        "- After creating a customer named John: '→ Add a phone number for John Smith'\n"
        "- After showing pipeline: '→ Update Zainab Shaikh from Qualified to Contact Made'\n"
        "- After showing a customer: '→ Log a call interaction with [name]'\n"
        "- After creating a quote: '→ Schedule a follow-up meeting to discuss the quote'\n\n"

        "## Response Style\n"
        "- Always call the appropriate tool to fetch fresh data — never use cached results from earlier in the conversation\n"
        "- Be concise and action-oriented\n"
        "- Use the customer's actual name in responses and suggestions\n"
        "- Format data in clear tables when showing lists\n"
        "- Always confirm what action was taken before suggesting next steps\n"
        "- Never say you cannot do something if you have a tool for it\n\n"

        f"Today's date is {datetime.now().strftime('%A, %d %B %Y')}.\n"
        f"Tenant ID: {g.tenant_id}\n"
    )

    # ── Headers ───────────────────────────────────────────────────────────────
    from flask import current_app
    api_key = current_app.config.get('ANTHROPIC_API_KEY') or \
              os.environ.get('ANTHROPIC_API_KEY')
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }

    tools      = get_tools()
    messages   = list(conversation_history)
    messages.append({"role": "user", "content": message})
    iterations = 0

    action_metadata = {
        'customer_ids':     [],
        'quote_ids':        [],
        'created_customer': None,
        'created_quote':    None,
    }

    # ── Main agentic loop ─────────────────────────────────────────────────────
    while iterations < MAX_ITERATIONS:
        iterations += 1

        payload = {
            "model":      CLAUDE_MODEL,
            "max_tokens": MAX_TOKENS,
            "system":     system_prompt,
            "tools":      tools,
            "messages":   messages,
        }

        try:
            response = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=60)
        except requests.exceptions.RequestException as e:
            print(f"[CLAUDE] Request failed: {e}")
            return jsonify({'error': f'Failed to reach Claude API: {str(e)}'}), 500

        if response.status_code != 200:
            error_body = response.text
            print(f"[CLAUDE] ERROR {response.status_code}: {error_body}")
            return jsonify({'error': f'Claude API error {response.status_code}', 'detail': error_body}), 500

        resp_data   = response.json()
        stop_reason = resp_data.get('stop_reason')
        content     = resp_data.get('content', [])

        messages.append({'role': 'assistant', 'content': content})

        # ── End turn ──────────────────────────────────────────────────────────
        if stop_reason == 'end_turn':
            final_text = ' '.join(
                block.get('text', '') for block in content if block.get('type') == 'text'
            ).strip()

            for msg in reversed(messages):
                if msg.get('role') != 'user':
                    continue
                content_blocks = msg.get('content', [])
                if not isinstance(content_blocks, list):
                    continue
                if not any(b.get('type') == 'tool_result' for b in content_blocks):
                    continue
                for block in content_blocks:
                    if block.get('type') != 'tool_result':
                        continue
                    try:
                        result_data = json.loads(block.get('content', '{}'))
                    except Exception:
                        continue
                    if not isinstance(result_data, dict):
                        continue
                    if result_data.get('success') and result_data.get('data'):
                        d = result_data['data']
                        if isinstance(d, dict):
                            cid = d.get('client_id') or d.get('id')
                            if cid and cid not in action_metadata['customer_ids']:
                                action_metadata['customer_ids'].append(cid)
                                msg_text = result_data.get('message') or ''
                                if 'Created customer' in msg_text:
                                    action_metadata['created_customer'] = {
                                        'client_id': cid,
                                        'name': d.get('client_contact_name') or d.get('name') or 'Customer',
                                    }
                                elif not action_metadata['created_customer']:
                                    action_metadata['created_customer'] = {
                                        'client_id': cid,
                                        'name': d.get('client_contact_name') or d.get('client_company_name') or d.get('name') or 'Customer',
                                    }
                        elif isinstance(d, list):
                            for item in d:
                                if not isinstance(item, dict):
                                    continue
                                cid = item.get('client_id') or item.get('id')
                                if cid and cid not in action_metadata['customer_ids']:
                                    action_metadata['customer_ids'].append(cid)
                    if result_data.get('proposal_id'):
                        pid = result_data['proposal_id']
                        if pid not in action_metadata['quote_ids']:
                            action_metadata['quote_ids'].append(pid)
                            action_metadata['created_quote'] = {
                                'proposal_id': pid,
                                'quote_id':    result_data.get('quote_id'),
                                'total':       result_data.get('total'),
                                'view_url':    f'/dashboard/quotes/{pid}/view',
                            }

            try:
                record_ai_message(
                    tenant_id=str(g.tenant_id),
                    user_id=getattr(g, 'user_id', None),
                )
            except Exception as e:
                print(f"[USAGE] Failed to record AI message: {e}")

            if action_metadata['customer_ids'] and not action_metadata['created_customer']:
                cid = action_metadata['customer_ids'][0]
                c = ClientMaster.query.filter_by(client_id=cid, tenant_id=str(g.tenant_id)).first()
                if c:
                    action_metadata['created_customer'] = {
                        'client_id': cid,
                        'name': getattr(c, 'client_contact_name', None) or getattr(c, 'client_company_name', None) or 'Customer',
                    }

            return jsonify({
                'response':             final_text or "Done.",
                'conversation_history': messages,
                'action_metadata':      action_metadata,
            }), 200

        # ── Tool use ──────────────────────────────────────────────────────────
        if stop_reason == 'tool_use':
            tool_results = []
            for block in content:
                if block.get('type') != 'tool_use':
                    continue
                tool_name   = block.get('name')
                tool_input  = block.get('input', {})
                tool_use_id = block.get('id')
                print(f"[TOOL] {tool_name}: {tool_input}")
                try:
                    result = execute_tool(tool_name, tool_input)
                except Exception as e:
                    import traceback
                    print(f"[TOOL ERROR] {tool_name}: {traceback.format_exc()}")
                    result = {'error': str(e)}
                tool_results.append({
                    'type':        'tool_result',
                    'tool_use_id': tool_use_id,
                    'content':     json.dumps(result),
                })
            messages.append({'role': 'user', 'content': tool_results})
            continue

        print(f"[CLAUDE] Unexpected stop_reason: {stop_reason}")
        break

    return jsonify({'error': 'Reached maximum tool iterations without a final response.'}), 500

# ── Legacy endpoint ───────────────────────────────────────────────────────────

@ai_bp.route('/chat/completions', methods=['POST'])
@auth_required
def chat_completions_legacy():
    return jsonify({
        'error':     'This endpoint is deprecated. Use POST /api/ai/chat instead.',
        'migration': 'Send { message, conversation_history } to /api/ai/chat'
    }), 410