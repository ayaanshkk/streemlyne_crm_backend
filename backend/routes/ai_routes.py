"""
AI Routes - Claude API Agentic CRM Assistant
Runs the full tool-use agentic loop server-side.
Frontend sends a message + history, gets back a final natural language response.

Endpoints:
  POST /api/ai/chat   — main agentic chat endpoint
"""

import os
import json
import requests
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from middleware import auth_required

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
CLAUDE_MODEL = 'claude-sonnet-4-6'
MAX_TOKENS = 4096
MAX_TOOL_ITERATIONS = 10

STAGES = [
    "Prospect", "Qualified", "Contact Made", "Meeting Scheduled",
    "Proposal Sent", "Negotiation", "Closed Won", "Closed Lost", "On Hold",
]

# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_pipeline_status",
        "description": "Get the current sales pipeline status showing count of customers in each stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_details": {"type": "boolean", "description": "Include customer names per stage"}
            }
        }
    },
    {
        "name": "list_customers",
        "description": "Get a list of all customers or filter by stage or name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": STAGES},
                "name_search": {"type": "string"},
                "limit": {"type": "integer"},
                "sort_by": {"type": "string", "enum": ["created_at", "name", "stage"]},
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
                "name": {"type": "string"},
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
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "address": {"type": "string"},
                "postcode": {"type": "string"},
                "company_name": {"type": "string"},
                "stage": {"type": "string", "enum": STAGES},
                "notes": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_customer",
        "description": "Update an existing customer's information. The 'updates' object can contain: name, email, phone, address, postcode, company_name, stage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Current name to search for the customer"},
                "customer_id": {"type": "string", "description": "client_id if known"},
                "updates": {
                    "type": "object",
                    "description": "Fields to update",
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
        "description": "Permanently delete a customer and all their data. Always confirm with the user before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
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
                "query": {"type": "string"},
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
                "date":            {"type": "string", "description": "YYYY-MM-DD format"},
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
                "month":         {"type": "string", "description": "YYYY-MM format"},
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
                "title":         {"type": "string", "description": "Search by title if no ID"},
                "customer_name": {"type": "string"},
                "updates": {
                    "type": "object",
                    "description": "Fields to update e.g. date, staff_name, notes, priority, status"
                }
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
        "description": "List proposals/quotes, optionally filtered by client name.",
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
        "description": "Get proposal/quote statistics: total count and total value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "integer"}
            }
        }
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Internal API caller
# ─────────────────────────────────────────────────────────────────────────────

def _internal_api(method: str, path: str, token: str, tenant_id: str, body: dict = None):
    """Call our own Flask API internally, passing auth headers."""
    base = os.getenv('INTERNAL_API_URL', 'http://127.0.0.1:5000/api')
    url = f"{base}{path}"
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Tenant-ID': str(tenant_id),
        'Content-Type': 'application/json',
    }
    try:
        resp = requests.request(method, url, headers=headers, json=body, timeout=30)

        print(f"[INTERNAL API] {method} {url} → {resp.status_code}: {resp.text[:300]}")

        # 204 No Content — success with no body (some DELETE routes)
        if resp.status_code == 204:
            return {'success': True}

        # 200 / 201 — parse JSON body
        if resp.status_code in (200, 201):
            try:
                return resp.json()
            except Exception:
                return {'success': True}

        # Any other status — surface the error
        try:
            error_body = resp.json()
        except Exception:
            error_body = {'detail': resp.text[:300]}

        return {
            'error': f'HTTP {resp.status_code}',
            'detail': error_body.get('error') or error_body.get('message') or resp.text[:300]
        }

    except requests.exceptions.Timeout:
        return {'error': 'Internal API request timed out'}
    except Exception as e:
        return {'error': str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Tool executor
# ─────────────────────────────────────────────────────────────────────────────

def _find_customer(clients: list, name: str):
    """Case-insensitive partial match on contact name or company name."""
    s = name.lower()
    return next(
        (c for c in clients
         if s in (c.get('client_contact_name') or '').lower()
         or s in (c.get('client_company_name') or '').lower()),
        None
    )


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
                            c.get('client_contact_name') or c.get('client_company_name')
                        )
            total = len(clients)
            won   = pipeline.get('Closed Won', {}).get('count', 0)
            return {
                'success': True,
                'pipeline': pipeline,
                'summary': {
                    'total_customers': total,
                    'active_deals':    pipeline.get('Negotiation', {}).get('count', 0) +
                                       pipeline.get('Proposal Sent', {}).get('count', 0),
                    'won_deals':       won,
                    'lost_deals':      pipeline.get('Closed Lost', {}).get('count', 0),
                    'conversion_rate': f"{(won/total*100):.1f}%" if total > 0 else '0%',
                }
            }

        # ── List customers ────────────────────────────────────────────────────
        elif name == "list_customers":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients:
                return clients
            if args.get('stage'):
                clients = [c for c in clients if c.get('stage') == args['stage']]
            if args.get('name_search'):
                s = args['name_search'].lower()
                clients = [c for c in clients
                           if s in (c.get('client_contact_name') or '').lower()
                           or s in (c.get('client_company_name') or '').lower()]
            if args.get('limit'):
                clients = clients[:args['limit']]
            return {'success': True, 'data': clients, 'count': len(clients)}

        # ── Get customer details ──────────────────────────────────────────────
        elif name == "get_customer_details":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients:
                return clients
            match = _find_customer(clients, args.get('name') or '')
            if not match:
                return {'success': False, 'message': f'No customer found matching "{args.get("name")}"'}
            detail = api('GET', f'/clients/{match["client_id"]}')
            if isinstance(detail, dict) and 'error' in detail:
                return detail
            return {'success': True, 'data': detail}

        # ── Create customer ───────────────────────────────────────────────────
        elif name == "create_customer":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients:
                return clients
            existing = _find_customer(clients, args.get('name') or '')
            if existing:
                return {
                    'success': False,
                    'message': f'Customer "{args["name"]}" already exists.',
                    'existing': existing
                }
            result = api('POST', '/clients', {
                'client_contact_name': args.get('name', ''),
                'client_company_name': args.get('company_name', ''),
                'client_email':        args.get('email', ''),
                'client_phone':        args.get('phone', ''),
                'address':             args.get('address', ''),
                'post_code':           args.get('postcode', ''),
                'stage':               args.get('stage', 'Prospect'),
            })
            if isinstance(result, dict) and 'error' in result:
                return result
            return {'success': True, 'data': result, 'message': f'Created customer: {args["name"]}'}

        # ── Update customer ───────────────────────────────────────────────────
        elif name == "update_customer":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients:
                return clients
            match = _find_customer(clients, args.get('name') or '')
            if not match:
                return {'success': False, 'message': f'No customer found matching "{args.get("name")}"'}

            updates = args.get('updates', {})
            if not updates:
                return {'success': False, 'message': 'No updates provided'}

            # Map tool field names → backend field names
            payload = {}
            if 'name'         in updates: payload['client_contact_name'] = updates['name']
            if 'email'        in updates: payload['client_email']        = updates['email']
            if 'phone'        in updates: payload['client_phone']        = updates['phone']
            if 'address'      in updates: payload['address']             = updates['address']
            if 'postcode'     in updates: payload['post_code']           = updates['postcode']
            if 'company_name' in updates: payload['client_company_name'] = updates['company_name']
            if 'stage'        in updates: payload['stage']               = updates['stage']

            if not payload:
                return {'success': False, 'message': 'No recognised fields in updates'}

            # Use PATCH so only supplied fields are updated
            result = api('PATCH', f'/clients/{match["client_id"]}', payload)
            if isinstance(result, dict) and 'error' in result:
                return result

            return {
                'success': True,
                'message': f'Updated {match.get("client_contact_name") or match.get("client_company_name")}',
                'data': result
            }

        # ── Delete customer ───────────────────────────────────────────────────
        elif name == "delete_customer":
            clients = api('GET', '/clients')
            if isinstance(clients, dict) and 'error' in clients:
                return clients
            match = _find_customer(clients, args.get('name') or '')
            if not match:
                return {'success': False, 'message': f'No customer found matching "{args.get("name")}"'}

            customer_name = match.get('client_contact_name') or match.get('client_company_name')
            result = api('DELETE', f'/clients/{match["client_id"]}')

            # DELETE returns {'message': 'Client deleted successfully'} on success
            # or {'error': '...'} / {'success': True} from _internal_api
            if isinstance(result, dict) and 'error' in result:
                return {
                    'success': False,
                    'message': f'Failed to delete {customer_name}: {result.get("detail") or result.get("error")}'
                }

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
            return {
                'success': True,
                'data': results,
                'message': f'Found {len(results["customers"])} customer(s)'
            }

        # ── Create schedule assignment ────────────────────────────────────────
        elif name == "create_schedule_assignment":
            customer_id = args.get('customer_id')
            if not customer_id and args.get('customer_name'):
                clients = api('GET', '/clients')
                if not isinstance(clients, dict):
                    match = _find_customer(clients, args['customer_name'])
                    if match:
                        customer_id = match['client_id']

            result = api('POST', '/assignments', {
                'type':            args.get('type', 'task'),
                'title':           args.get('title'),
                'date':            args.get('date'),
                'staff_name':      args.get('staff_name'),
                'customer_id':     customer_id,
                'customer_name':   args.get('customer_name'),
                'estimated_hours': args.get('estimated_hours', 1),
                'priority':        args.get('priority', 'Medium'),
                'status':          'Scheduled',
                'notes':           args.get('notes', ''),
            })
            if isinstance(result, dict) and 'error' in result:
                return result
            return {
                'success': True,
                'data': result,
                'message': f'Scheduled {args.get("type")} "{args.get("title")}" on {args.get("date")}'
            }

        # ── List schedule assignments ─────────────────────────────────────────
        elif name == "list_schedule_assignments":
            path = '/assignments'
            if args.get('month'):
                path += f'?month={args["month"]}'
            assignments = api('GET', path)
            if isinstance(assignments, dict) and 'error' in assignments:
                return assignments
            if args.get('staff_name'):
                s = args['staff_name'].lower()
                assignments = [a for a in assignments if s in (a.get('staff_name') or '').lower()]
            if args.get('customer_name'):
                s = args['customer_name'].lower()
                assignments = [a for a in assignments if s in (a.get('customer_name') or '').lower()]
            return {'success': True, 'data': assignments, 'count': len(assignments)}

        # ── Update schedule assignment ────────────────────────────────────────
        elif name == "update_schedule_assignment":
            assignments = api('GET', '/assignments')
            if isinstance(assignments, dict) and 'error' in assignments:
                return assignments

            match = None
            if args.get('assignment_id'):
                match = next((a for a in assignments
                              if str(a.get('id')) == str(args['assignment_id'])), None)
            elif args.get('title'):
                s = args['title'].lower()
                match = next((a for a in assignments
                              if s in (a.get('title') or '').lower()), None)
            elif args.get('customer_name'):
                s = args['customer_name'].lower()
                match = next((a for a in assignments
                              if s in (a.get('customer_name') or '').lower()), None)

            if not match:
                return {'success': False, 'message': 'Could not find the assignment to update.'}

            result = api('PUT', f'/assignments/{match["id"]}', args.get('updates', {}))
            if isinstance(result, dict) and 'error' in result:
                return result
            return {'success': True, 'data': result,
                    'message': f'Updated assignment "{match.get("title")}"'}

        # ── Delete schedule assignment ────────────────────────────────────────
        elif name == "delete_schedule_assignment":
            assignments = api('GET', '/assignments')
            if isinstance(assignments, dict) and 'error' in assignments:
                return assignments

            match = None
            if args.get('assignment_id'):
                match = next((a for a in assignments
                              if str(a.get('id')) == str(args['assignment_id'])), None)
            elif args.get('title'):
                s = args['title'].lower()
                match = next((a for a in assignments
                              if s in (a.get('title') or '').lower()), None)

            if not match:
                return {'success': False, 'message': 'Could not find the assignment to delete.'}

            result = api('DELETE', f'/assignments/{match["id"]}')
            if isinstance(result, dict) and 'error' in result:
                return {
                    'success': False,
                    'message': f'Failed to delete assignment: {result.get("detail") or result.get("error")}'
                }
            return {'success': True, 'message': f'Deleted assignment "{match.get("title")}"'}

        # ── List quotes ───────────────────────────────────────────────────────
        elif name == "list_quotes":
            quotes = api('GET', '/proposals')
            if isinstance(quotes, dict) and 'error' in quotes:
                return quotes
            if args.get('client_name'):
                s = args['client_name'].lower()
                quotes = [q for q in quotes
                          if s in (q.get('customer_name') or q.get('client_name') or '').lower()]
            return {'success': True, 'data': quotes, 'count': len(quotes)}

        # ── Quote status ──────────────────────────────────────────────────────
        elif name == "get_quote_status":
            quotes = api('GET', '/proposals')
            if isinstance(quotes, dict) and 'error' in quotes:
                return quotes
            total_value = sum(float(q.get('total_amount') or 0) for q in quotes)
            return {
                'success': True,
                'count': len(quotes),
                'total_value': total_value,
                'average_value': total_value / len(quotes) if quotes else 0
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
    """
    Agentic chat endpoint.
    POST /api/ai/chat
    Body: { "message": "...", "conversation_history": [...] }
    Returns: { "response": "...", "conversation_history": [...] }
    """
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured on the server.'}), 500

    data = request.get_json() or {}
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'error': 'message is required'}), 400

    token = (
        request.headers.get('Authorization', '').replace('Bearer ', '') or
        request.cookies.get('auth_token', '')
    )
    tenant_id = str(g.tenant_id)

    today        = datetime.utcnow()
    tomorrow     = today + timedelta(days=1)
    today_str    = today.strftime('%Y-%m-%d')
    tomorrow_str = tomorrow.strftime('%Y-%m-%d')
    today_long   = today.strftime('%A, %B') + ' ' + str(today.day) + ', ' + str(today.year)

    system_prompt = (
        "You are StreemAI, an intelligent CRM assistant for StreemLyne.\n"
        "You help manage customers, schedules, proposals, and pipeline.\n\n"
        f"TODAY: {today_str} ({today_long})\n"
        f"TOMORROW: {tomorrow_str}\n"
        f"Current month: {today.strftime('%Y-%m')}\n\n"
        "RULES:\n"
        "- ALWAYS use tools to fetch or create real data. Never invent names, IDs, or results.\n"
        "- Before creating a customer, always call list_customers first to check for duplicates.\n"
        "- When the user says 'update', 'change', 'rename', 'set', or 'edit' a customer field, "
        "ALWAYS call update_customer — never just list_customers.\n"
        "- When updating a name, put the new name in updates as {\"name\": \"new name\"}, "
        "and use the current name in the top-level 'name' field to find the customer.\n"
        "- Output dates as YYYY-MM-DD. Never schedule in the past.\n"
        "- Be concise, warm, and direct. No bullet-point lists unless the user asks.\n"
        "- If you cannot find something, say so clearly and offer to search differently.\n"
        "- For delete operations: confirm the customer was found before saying it was deleted.\n"
        "- For update operations: only include fields the user explicitly asked to change.\n"
        f"- Valid pipeline stages: {', '.join(STAGES)}"
    )

    history  = data.get('conversation_history', [])
    messages = [*history, {"role": "user", "content": user_message}]

    headers = {
        'x-api-key':          ANTHROPIC_API_KEY,
        'anthropic-version':  '2023-06-01',
        'content-type':       'application/json',
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
                headers=headers,
                json=payload,
                timeout=60,
            )
        except requests.exceptions.Timeout:
            return jsonify({'error': 'Claude API timed out. Please try again.'}), 504
        except requests.exceptions.RequestException as e:
            return jsonify({'error': f'Failed to reach Claude API: {str(e)}'}), 500

        if resp.status_code != 200:
            return jsonify({
                'error': f'Claude API error {resp.status_code}',
                'detail': resp.text[:500]
            }), 500

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
                if block.get('type') != 'tool_use':
                    continue

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