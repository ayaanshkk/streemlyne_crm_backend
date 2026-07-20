"""
AI Routes - Claude API Agentic CRM Assistant
Runs the full tool-use agentic loop server-side.

Endpoints:
  POST /api/ai/chat   — main agentic chat endpoint
"""

import os
import json
import requests
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from middleware import auth_required
from database import db
from sqlalchemy import text

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
CLAUDE_MODEL      = 'claude-sonnet-4-6'
MAX_TOKENS        = 4096
MAX_TOOL_ITERATIONS = 10

STAGES = [
    "Prospect", "Qualified", "Contact Made", "Meeting Scheduled",
    "Proposal Sent", "Negotiation", "Closed Won", "Closed Lost", "On Hold",
]

# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    # ── Existing tools ────────────────────────────────────────────────────────
    {
        "name": "get_pipeline_status",
        "description": "Get the current sales pipeline status showing count of customers in each stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_details": {"type": "boolean"}
            }
        }
    },
    {
        "name": "list_customers",
        "description": "Get a list of all customers or filter by stage or name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage":      {"type": "string", "enum": STAGES},
                "name_search": {"type": "string"},
                "limit":      {"type": "integer"},
                "sort_by":    {"type": "string", "enum": ["created_at", "name", "stage"]},
                "sort_order": {"type": "string", "enum": ["asc", "desc"]}
            }
        }
    },
    {
        "name": "get_customer_details",
        "description": "Get detailed information about a specific customer by name or ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string"},
                "customer_id": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_customer",
        "description": "Create a new customer. Always check for duplicates first using list_customers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":         {"type": "string"},
                "email":        {"type": "string"},
                "phone":        {"type": "string"},
                "address":      {"type": "string"},
                "postcode":     {"type": "string"},
                "company_name": {"type": "string"},
                "stage":        {"type": "string", "enum": STAGES},
                "notes":        {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_customer",
        "description": "Update an existing customer's information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string"},
                "customer_id": {"type": "string"},
                "updates": {
                    "type": "object",
                    "properties": {
                        "name":         {"type": "string"},
                        "email":        {"type": "string"},
                        "phone":        {"type": "string"},
                        "address":      {"type": "string"},
                        "postcode":     {"type": "string"},
                        "company_name": {"type": "string"},
                        "stage":        {"type": "string"}
                    }
                }
            },
            "required": ["name", "updates"]
        }
    },
    {
        "name": "delete_customer",
        "description": "Permanently delete a customer. Always confirm with the user before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string"},
                "customer_id": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "search_database",
        "description": "Search across customers with flexible text queries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string"},
                "entity_type": {"type": "string", "enum": ["customers", "jobs", "both"]}
            },
            "required": ["query", "entity_type"]
        }
    },
    {
        "name": "create_schedule_assignment",
        "description": "Create a calendar assignment/task/meeting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type":            {"type": "string", "enum": ["meeting", "call", "task", "delivery", "note"]},
                "title":           {"type": "string"},
                "date":            {"type": "string"},
                "staff_name":      {"type": "string"},
                "customer_name":   {"type": "string"},
                "estimated_hours": {"type": "number"},
                "priority":        {"type": "string", "enum": ["Low", "Medium", "High", "Urgent"]},
                "notes":           {"type": "string"}
            },
            "required": ["type", "title", "date", "staff_name"]
        }
    },
    {
        "name": "list_schedule_assignments",
        "description": "Get calendar assignments, optionally filtered by month or staff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month":         {"type": "string"},
                "staff_name":    {"type": "string"},
                "customer_name": {"type": "string"}
            }
        }
    },
    {
        "name": "update_schedule_assignment",
        "description": "Update or reschedule an existing calendar assignment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "assignment_id": {"type": "string"},
                "title":         {"type": "string"},
                "customer_name": {"type": "string"},
                "updates":       {"type": "object"}
            },
            "required": ["updates"]
        }
    },
    {
        "name": "delete_schedule_assignment",
        "description": "Delete/cancel a calendar assignment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "assignment_id": {"type": "string"},
                "title":         {"type": "string"}
            }
        }
    },
    {
        "name": "list_quotes",
        "description": "List quotes, optionally filtered by client name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
                "client_id":   {"type": "integer"}
            }
        }
    },
    {
        "name": "get_quote_status",
        "description": "Get quote statistics: total count and total value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "integer"}
            }
        }
    },

    # ── NEW: Quote generation tools ───────────────────────────────────────────

    {
        "name": "search_pricelist",
        "description": (
            "Search the tenant's price list for items matching keywords or category. "
            "Use this when generating a quote to find pre-set prices. "
            "Returns item names, descriptions, base prices, and units."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Search terms e.g. 'kitchen installation' or 'forklift training'"
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category if known"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10)"
                }
            }
        }
    },
    {
        "name": "get_client_quote_history",
        "description": (
            "Get previous quotes for a client. Use this when generating a new quote "
            "to base it on their last quote — pre-filling the same line items and prices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
                "client_id":   {"type": "integer"},
                "limit": {
                    "type": "integer",
                    "description": "Number of recent quotes to fetch (default 3)"
                }
            }
        }
    },
    {
        "name": "create_quote",
        "description": (
            "Create a quote directly. Call this after presenting the draft to the user "
            "and receiving confirmation. Do NOT call without user confirmation. "
            "Line items come from pricelist search or user input."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name": {
                    "type": "string",
                    "description": "Client name to look up"
                },
                "client_id": {
                    "type": "integer",
                    "description": "Client ID if known"
                },
                "line_items": {
                    "type": "array",
                    "description": "List of line items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity":    {"type": "number"},
                            "unit_price":  {"type": "number"},
                            "pricelist_id": {"type": "integer", "description": "Optional — links to PriceList_Master"}
                        },
                        "required": ["description", "quantity", "unit_price"]
                    }
                },
                "discount_percent": {
                    "type": "number",
                    "description": "Discount percentage (0-100)"
                },
                "vat_rate": {
                    "type": "number",
                    "description": "VAT rate percentage (default 20)"
                },
                "notes": {
                    "type": "string",
                    "description": "Any notes or terms"
                }
            },
            "required": ["line_items"]
        }
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Internal API caller
# ─────────────────────────────────────────────────────────────────────────────

def _internal_api(method: str, path: str, token: str, tenant_id: str, body: dict = None):
    base = os.getenv('INTERNAL_API_URL', 'http://127.0.0.1:5000/api')
    url  = f"{base}{path}"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant-ID':   str(tenant_id),
        'Content-Type':  'application/json',
    }
    try:
        resp = requests.request(method, url, headers=headers, json=body, timeout=30)
        print(f"[INTERNAL API] {method} {url} → {resp.status_code}: {resp.text[:300]}")
        if resp.status_code == 204:
            return {'success': True}
        if resp.status_code in (200, 201):
            try:    return resp.json()
            except: return {'success': True}
        try:    error_body = resp.json()
        except: error_body = {'detail': resp.text[:300]}
        return {
            'error':  f'HTTP {resp.status_code}',
            'detail': error_body.get('error') or error_body.get('message') or resp.text[:300]
        }
    except requests.exceptions.Timeout:
        return {'error': 'Internal API request timed out'}
    except Exception as e:
        return {'error': str(e)}


def _find_customer(clients: list, name: str):
    s = name.lower()
    return next(
        (c for c in clients
         if s in (c.get('client_contact_name') or '').lower()
         or s in (c.get('client_company_name') or '').lower()),
        None
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pricelist search — direct DB query (no API route needed)
# ─────────────────────────────────────────────────────────────────────────────

def _search_pricelist(tenant_id: str, keywords: str = '', category: str = '', limit: int = 10) -> list:
    """
    Full-text + keyword search against PriceList_Master.
    Uses the GIN index on item_name + description for fast search.
    """
    try:
        params = {'tenant_id': tenant_id, 'limit': limit}
        conditions = ["p.tenant_id = :tenant_id"]

        if category:
            conditions.append("LOWER(p.category) LIKE :category")
            params['category'] = f"%{category.lower()}%"

        if keywords:
            # Try full-text search first, fall back to ILIKE
            conditions.append(
                "(to_tsvector('english', p.item_name || ' ' || COALESCE(p.description, '')) "
                " @@ plainto_tsquery('english', :keywords) "
                " OR LOWER(p.item_name) LIKE :kw_like "
                " OR LOWER(COALESCE(p.description, '')) LIKE :kw_like)"
            )
            params['keywords'] = keywords
            params['kw_like']  = f"%{keywords.lower()}%"

        where = " AND ".join(conditions)
        query = text(f"""
            SELECT
                p.pricelist_id,
                p.category,
                p.item_name,
                p.description,
                p.base_price,
                p.unit,
                p.item_code,
                p.brand,
                p.colour
            FROM "StreemLyne_MT"."PriceList_Master" p
            WHERE {where}
            ORDER BY p.category, p.item_name
            LIMIT :limit
        """)

        rows = db.session.execute(query, params).fetchall()
        return [
            {
                'pricelist_id': r.pricelist_id,
                'category':     r.category,
                'item_name':    r.item_name,
                'description':  r.description,
                'base_price':   float(r.base_price) if r.base_price is not None else 0.0,
                'unit':         r.unit or 'each',
                'item_code':    r.item_code,
                'brand':        r.brand,
                'colour':       r.colour,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[StreemAI] Pricelist search error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Tool executor
# ─────────────────────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict, token: str, tenant_id: str) -> dict:
    api = lambda method, path, body=None: _internal_api(method, path, token, tenant_id, body)

    try:

        # ── Pipeline ──────────────────────────────────────────────────────────
        if name == "get_pipeline_status":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients:
                return clients
            pipeline = {s: {'count': 0, 'customers': []} for s in STAGES}
            for c in clients:
                stage = c.get('stage') or 'Prospect'
                if stage in pipeline:
                    pipeline[stage]['count'] += 1
                    if args.get('include_details'):
                        pipeline[stage]['customers'].append(
                            c.get('client_contact_name') or c.get('client_company_name'))
            total = len(clients)
            won   = pipeline.get('Closed Won', {}).get('count', 0)
            return {
                'success': True, 'pipeline': pipeline,
                'summary': {
                    'total_customers': total,
                    'active_deals':    pipeline.get('Negotiation', {}).get('count', 0) +
                                       pipeline.get('Proposal Sent', {}).get('count', 0),
                    'won_deals': won, 'lost_deals': pipeline.get('Closed Lost', {}).get('count', 0),
                    'conversion_rate': f"{(won/total*100):.1f}%" if total > 0 else '0%',
                }
            }

        # ── List customers ────────────────────────────────────────────────────
        elif name == "list_customers":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients: return clients
            if args.get('stage'):
                clients = [c for c in clients if c.get('stage') == args['stage']]
            if args.get('name_search'):
                s = args['name_search'].lower()
                clients = [c for c in clients
                           if s in (c.get('client_contact_name') or '').lower()
                           or s in (c.get('client_company_name') or '').lower()]
            if args.get('limit'): clients = clients[:args['limit']]
            return {'success': True, 'data': clients, 'count': len(clients)}

        # ── Get customer details ──────────────────────────────────────────────
        elif name == "get_customer_details":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients: return clients
            match = _find_customer(clients, args.get('name') or '')
            if not match:
                return {'success': False, 'message': f'No customer found matching "{args.get("name")}"'}
            detail = api('GET', f'/clients/{match["client_id"]}')
            return {'success': True, 'data': detail} if not (isinstance(detail, dict) and 'error' in detail) else detail

        # ── Create customer ───────────────────────────────────────────────────
        elif name == "create_customer":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients: return clients
            existing = _find_customer(clients, args.get('name') or '')
            if existing:
                return {'success': False, 'message': f'Customer "{args["name"]}" already exists.', 'existing': existing}
            result = api('POST', '/clients', {
                'client_contact_name': args.get('name', ''),
                'client_company_name': args.get('company_name', ''),
                'client_email':        args.get('email', ''),
                'client_phone':        args.get('phone', ''),
                'address':             args.get('address', ''),
                'post_code':           args.get('postcode', ''),
                'stage':               args.get('stage', 'Prospect'),
            })
            if isinstance(result, dict) and 'error' in result: return result
            return {'success': True, 'data': result, 'message': f'Created customer: {args["name"]}'}

        # ── Update customer ───────────────────────────────────────────────────
        elif name == "update_customer":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients: return clients
            match = _find_customer(clients, args.get('name') or '')
            if not match:
                return {'success': False, 'message': f'No customer found matching "{args.get("name")}"'}
            updates = args.get('updates', {})
            if not updates: return {'success': False, 'message': 'No updates provided'}
            payload = {}
            if 'name'         in updates: payload['client_contact_name'] = updates['name']
            if 'email'        in updates: payload['client_email']        = updates['email']
            if 'phone'        in updates: payload['client_phone']        = updates['phone']
            if 'address'      in updates: payload['address']             = updates['address']
            if 'postcode'     in updates: payload['post_code']           = updates['postcode']
            if 'company_name' in updates: payload['client_company_name'] = updates['company_name']
            if 'stage'        in updates: payload['stage']               = updates['stage']
            if not payload: return {'success': False, 'message': 'No recognised fields in updates'}
            result = api('PATCH', f'/clients/{match["client_id"]}', payload)
            if isinstance(result, dict) and 'error' in result: return result
            return {'success': True,
                    'message': f'Updated {match.get("client_contact_name") or match.get("client_company_name")}',
                    'data': result}

        # ── Delete customer ───────────────────────────────────────────────────
        elif name == "delete_customer":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients: return clients
            match = _find_customer(clients, args.get('name') or '')
            if not match:
                return {'success': False, 'message': f'No customer found matching "{args.get("name")}"'}
            customer_name = match.get('client_contact_name') or match.get('client_company_name')
            result = api('DELETE', f'/clients/{match["client_id"]}')
            if isinstance(result, dict) and 'error' in result:
                return {'success': False, 'message': f'Failed to delete {customer_name}: {result.get("detail") or result.get("error")}'}
            return {'success': True, 'message': f'Deleted customer: {customer_name}'}

        # ── Search database ───────────────────────────────────────────────────
        elif name == "search_database":
            results = {'customers': [], 'jobs': []}
            sl = (args.get('query') or '').lower()
            if args.get('entity_type') != 'jobs':
                clients = api('GET', '/clients')
                if not isinstance(clients, dict):
                    results['customers'] = [
                        c for c in clients
                        if sl in (c.get('client_contact_name') or '').lower()
                        or sl in (c.get('client_company_name') or '').lower()
                        or sl in (c.get('client_email') or '').lower()
                    ]
            return {'success': True, 'data': results, 'message': f'Found {len(results["customers"])} customer(s)'}

        # ── Schedule tools ────────────────────────────────────────────────────
        elif name == "create_schedule_assignment":
            customer_id = args.get('customer_id')
            if not customer_id and args.get('customer_name'):
                clients = api('GET', '/clients')
                if not isinstance(clients, dict):
                    match = _find_customer(clients, args['customer_name'])
                    if match: customer_id = match['client_id']
            result = api('POST', '/assignments', {
                'type': args.get('type', 'task'), 'title': args.get('title'),
                'date': args.get('date'), 'staff_name': args.get('staff_name'),
                'customer_id': customer_id, 'customer_name': args.get('customer_name'),
                'estimated_hours': args.get('estimated_hours', 1),
                'priority': args.get('priority', 'Medium'), 'status': 'Scheduled',
                'notes': args.get('notes', ''),
            })
            if isinstance(result, dict) and 'error' in result: return result
            return {'success': True, 'data': result,
                    'message': f'Scheduled {args.get("type")} "{args.get("title")}" on {args.get("date")}'}

        elif name == "list_schedule_assignments":
            path = '/assignments'
            if args.get('month'): path += f'?month={args["month"]}'
            assignments = api('GET', path)
            if isinstance(assignments, dict) and 'error' in assignments: return assignments
            if args.get('staff_name'):
                s = args['staff_name'].lower()
                assignments = [a for a in assignments if s in (a.get('staff_name') or '').lower()]
            if args.get('customer_name'):
                s = args['customer_name'].lower()
                assignments = [a for a in assignments if s in (a.get('customer_name') or '').lower()]
            return {'success': True, 'data': assignments, 'count': len(assignments)}

        elif name == "update_schedule_assignment":
            assignments = api('GET', '/assignments')
            if isinstance(assignments, dict) and 'error' in assignments: return assignments
            match = None
            if args.get('assignment_id'):
                match = next((a for a in assignments if str(a.get('id')) == str(args['assignment_id'])), None)
            elif args.get('title'):
                s = args['title'].lower()
                match = next((a for a in assignments if s in (a.get('title') or '').lower()), None)
            elif args.get('customer_name'):
                s = args['customer_name'].lower()
                match = next((a for a in assignments if s in (a.get('customer_name') or '').lower()), None)
            if not match: return {'success': False, 'message': 'Could not find the assignment to update.'}
            result = api('PUT', f'/assignments/{match["id"]}', args.get('updates', {}))
            if isinstance(result, dict) and 'error' in result: return result
            return {'success': True, 'data': result, 'message': f'Updated assignment "{match.get("title")}"'}

        elif name == "delete_schedule_assignment":
            assignments = api('GET', '/assignments')
            if isinstance(assignments, dict) and 'error' in assignments: return assignments
            match = None
            if args.get('assignment_id'):
                match = next((a for a in assignments if str(a.get('id')) == str(args['assignment_id'])), None)
            elif args.get('title'):
                s = args['title'].lower()
                match = next((a for a in assignments if s in (a.get('title') or '').lower()), None)
            if not match: return {'success': False, 'message': 'Could not find the assignment to delete.'}
            result = api('DELETE', f'/assignments/{match["id"]}')
            if isinstance(result, dict) and 'error' in result:
                return {'success': False, 'message': f'Failed to delete: {result.get("detail") or result.get("error")}'}
            return {'success': True, 'message': f'Deleted assignment "{match.get("title")}"'}

        # ── List quotes ───────────────────────────────────────────────────────
        elif name == "list_quotes":
            quotes = api('GET', '/proposals')
            if isinstance(quotes, dict) and 'error' in quotes: return quotes
            if args.get('client_name'):
                s = args['client_name'].lower()
                quotes = [q for q in quotes
                          if s in (q.get('customer_name') or q.get('client_name') or '').lower()]
            return {'success': True, 'data': quotes, 'count': len(quotes)}

        elif name == "get_quote_status":
            quotes = api('GET', '/proposals')
            if isinstance(quotes, dict) and 'error' in quotes: return quotes
            total_value = sum(float(q.get('total_amount') or 0) for q in quotes)
            return {'success': True, 'count': len(quotes), 'total_value': total_value,
                    'average_value': total_value / len(quotes) if quotes else 0}

        # ── NEW: Search pricelist ─────────────────────────────────────────────
        elif name == "search_pricelist":
            items = _search_pricelist(
                tenant_id=tenant_id,
                keywords=args.get('keywords', ''),
                category=args.get('category', ''),
                limit=args.get('limit', 10),
            )
            if not items:
                return {
                    'success': True,
                    'data': [],
                    'message': 'No items found in price list matching that search. The user will need to provide custom pricing.',
                }
            return {
                'success': True,
                'data': items,
                'count': len(items),
                'message': f'Found {len(items)} price list item(s). Use base_price as unit_price in the quote.',
            }

        # ── NEW: Get client quote history ─────────────────────────────────────
        elif name == "get_client_quote_history":
            quotes = api('GET', '/proposals')
            if isinstance(quotes, dict) and 'error' in quotes: return quotes

            # Filter by client
            client_id = args.get('client_id')
            if not client_id and args.get('client_name'):
                clients = api('GET', '/clients')
                if not isinstance(clients, dict):
                    match = _find_customer(clients, args['client_name'])
                    if match: client_id = match['client_id']

            if client_id:
                quotes = [q for q in quotes if q.get('client_id') == client_id]
            elif args.get('client_name'):
                s = args['client_name'].lower()
                quotes = [q for q in quotes
                          if s in (q.get('customer_name') or '').lower()]

            # Sort newest first, take limit
            limit  = args.get('limit', 3)
            quotes = sorted(quotes, key=lambda q: q.get('created_at') or '', reverse=True)[:limit]

            if not quotes:
                return {
                    'success': True,
                    'data': [],
                    'message': 'No previous quotes found for this client. Will need to build from scratch.',
                }

            # Fetch details for the most recent quote to use as template
            most_recent = quotes[0]
            details     = []
            proposal_id = most_recent.get('proposal_id')
            if proposal_id:
                detail_res = api('GET', f'/proposals/{proposal_id}')
                if not isinstance(detail_res, dict) or 'error' not in detail_res:
                    details = detail_res.get('details', []) if isinstance(detail_res, dict) else []

            return {
                'success': True,
                'data': {
                    'recent_quotes': quotes,
                    'last_quote_details': details,
                    'last_quote': most_recent,
                },
                'message': (
                    f'Found {len(quotes)} previous quote(s). '
                    f'Most recent: {most_recent.get("quote_id")} for £{most_recent.get("total_amount", 0):.2f}. '
                    f'It had {len(details)} line item(s) — you can use these as a template.'
                ),
            }

        # ── NEW: Create quote ─────────────────────────────────────────────────
        elif name == "create_quote":
            line_items = args.get('line_items', [])
            if not line_items:
                return {'success': False, 'message': 'No line items provided'}

            # Resolve client
            client_id = args.get('client_id')
            if not client_id and args.get('client_name'):
                clients = api('GET', '/clients')
                if not isinstance(clients, dict):
                    match = _find_customer(clients, args['client_name'])
                    if match: client_id = match['client_id']

            if not client_id:
                return {'success': False, 'message': 'Could not find the client. Please specify a valid client name.'}

            # Calculate totals
            vat_rate        = float(args.get('vat_rate', 20))
            discount_pct    = float(args.get('discount_percent', 0))
            sub_total       = sum(float(i['quantity']) * float(i['unit_price']) for i in line_items)
            discount_amount = (sub_total * discount_pct / 100) if discount_pct else 0
            after_discount  = sub_total - discount_amount
            tax_amount      = (after_discount * vat_rate / 100)
            total_amount    = after_discount + tax_amount

            # Get default tax_id
            taxes  = api('GET', '/master/taxes')
            tax_id = None  # send null if no tax configured — proposal_routes handles it
            if isinstance(taxes, list) and taxes:
                tax_id = taxes[0].get('tax_id')
            elif isinstance(taxes, dict) and taxes.get('taxes'):
                tax_id = taxes['taxes'][0].get('tax_id')
            elif isinstance(taxes, dict) and taxes.get('taxes'):
                tax_id = taxes['taxes'][0].get('tax_id', 1)

            payload = {
                'client_id':        client_id,
                'sub_total':        round(sub_total, 2),
                'discount_percent': discount_pct if discount_pct else None,
                'discount_amount':  round(discount_amount, 2) if discount_amount else None,
                'tax_id':           tax_id,
                'total_amount':     round(total_amount, 2),
                'notes':            args.get('notes', ''),
                'details': [
                    {
                        'service_name': item['description'],
                        'service_id':   None,   # optional link
                        'quantity':     float(item['quantity']),
                        'amount':       float(item['unit_price']),
                        'uom_id':       None,
                    }
                    for item in line_items
                ],
            }

            result = api('POST', '/proposals', payload)
            if isinstance(result, dict) and 'error' in result:
                return result

            quote_id    = result.get('quote_id') or f"#{result.get('proposal_id')}"
            proposal_id = result.get('proposal_id')

            return {
                'success':     True,
                'quote_id':    quote_id,
                'proposal_id': proposal_id,
                'total':       round(total_amount, 2),
                'view_url':    f'/dashboard/quotes/{proposal_id}/view',
                'message':     f'Quote {quote_id} created successfully for £{total_amount:.2f}.',
            }

        else:
            return {'success': False, 'message': f'Unknown tool: {name}'}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Main endpoint
# ─────────────────────────────────────────────────────────────────────────────

@ai_bp.route('/chat', methods=['POST'])
@auth_required
def chat():
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on the server.'}), 500

    data         = request.get_json() or {}
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'error': 'message is required'}), 400

    token     = request.headers.get('Authorization', '').replace('Bearer ', '') or request.cookies.get('auth_token', '')
    tenant_id = str(g.tenant_id)

    today        = datetime.utcnow()
    tomorrow     = today + timedelta(days=1)
    today_str    = today.strftime('%Y-%m-%d')
    tomorrow_str = tomorrow.strftime('%Y-%m-%d')
    today_long   = today.strftime('%A, %B') + ' ' + str(today.day) + ', ' + str(today.year)

    system_prompt = (
        "You are StreemAI, an intelligent CRM assistant for StreemLyne.\n"
        "You help manage customers, schedules, quotes, and pipeline.\n\n"
        f"TODAY: {today_str} ({today_long})\n"
        f"TOMORROW: {tomorrow_str}\n"
        f"Current month: {today.strftime('%Y-%m')}\n\n"
        "RULES:\n"
        "- ALWAYS use tools to fetch or create real data. Never invent names, IDs, or results.\n"
        "- Before creating a customer, always call list_customers first to check for duplicates.\n"
        "- When the user says 'update', 'change', 'rename', 'set', or 'edit' a customer field, "
        "ALWAYS call update_customer.\n"
        "- Output dates as YYYY-MM-DD. Never schedule in the past.\n"
        "- Be concise, warm, and direct.\n"
        "- For delete operations: confirm the customer was found before saying it was deleted.\n"
        f"- Valid pipeline stages: {', '.join(STAGES)}\n\n"
        "QUOTE GENERATION RULES:\n"
        "- When asked to generate/create a quote, follow this exact flow:\n"
        "  1. Find the client using list_customers.\n"
        "  2. Call get_client_quote_history to check if they have previous quotes to use as template.\n"
        "  3. Call search_pricelist with relevant keywords to find pre-set prices.\n"
        "  4. If pricelist items are found, use their base_price as unit_price — do NOT ask the user for prices that are already in the pricelist.\n"
        "  5. If pricelist has no matches, ask the user for description, quantity, and unit price.\n"
        "  6. Present a COMPLETE quote draft showing all line items, subtotal, VAT, and total BEFORE creating it.\n"
        "  7. Ask 'Shall I create this quote?' and wait for confirmation.\n"
        "  8. Only call create_quote AFTER the user confirms.\n"
        "- After creating a quote, always share the quote number and a direct link: /dashboard/quotes/{proposal_id}/view\n"
        "- If the user says 'use last quote' or 'same as before', base it on get_client_quote_history results.\n"
        "- You can pre-fill up to 80% of a quote from pricelist + history. The user only needs to confirm or adjust."
    )

    history  = data.get('conversation_history', [])
    messages = [*history, {"role": "user", "content": user_message}]

    req_headers = {
        'x-api-key':         ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type':      'application/json',
    }

    iterations = 0
    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1

        payload = {
            'model':      CLAUDE_MODEL,
            'max_tokens': MAX_TOKENS,
            'system':     system_prompt,
            'tools':      TOOLS,
            'messages':   messages,
        }

        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers=req_headers,
                json=payload,
                timeout=60,
            )
        except requests.exceptions.Timeout:
            return jsonify({'error': 'Claude API timed out. Please try again.'}), 504
        except requests.exceptions.RequestException as e:
            return jsonify({'error': f'Failed to reach Claude API: {str(e)}'}), 500

        if resp.status_code != 200:
            return jsonify({'error': f'Claude API error {resp.status_code}', 'detail': resp.text[:500]}), 500

        result      = resp.json()
        stop_reason = result.get('stop_reason')
        content     = result.get('content', [])
        messages.append({"role": "assistant", "content": content})

        if stop_reason == 'end_turn':
            final_text = ' '.join(
                block.get('text', '') for block in content if block.get('type') == 'text'
            ).strip()
            return jsonify({
                'response':             final_text or "Done.",
                'conversation_history': messages,
            }), 200

        if stop_reason == 'tool_use':
            tool_results = []
            for block in content:
                if block.get('type') != 'tool_use': continue
                tool_name   = block['name']
                tool_input  = block.get('input', {})
                tool_use_id = block['id']
                print(f"[StreemAI] Tool call: {tool_name}({json.dumps(tool_input)[:300]})")
                result_data = execute_tool(tool_name, tool_input, token, tenant_id)
                print(f"[StreemAI] Tool result: {json.dumps(result_data)[:300]}")
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tool_use_id,
                    "content":     json.dumps(result_data),
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    return jsonify({'error': 'Reached maximum tool iterations without a final response.'}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Legacy endpoint
# ─────────────────────────────────────────────────────────────────────────────

@ai_bp.route('/chat/completions', methods=['POST'])
@auth_required
def chat_completions_legacy():
    return jsonify({
        'error':     'This endpoint is deprecated. Use POST /api/ai/chat instead.',
        'migration': 'Send { message, conversation_history } to /api/ai/chat'
    }), 410