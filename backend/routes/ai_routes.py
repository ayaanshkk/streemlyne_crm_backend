"""
AI Routes - OpenAI API Proxy
Keeps the OpenAI API key secure on the backend.
All AI chat requests go through this proxy.
"""

from flask import Blueprint, request, jsonify, g
from middleware import auth_required
import os
import requests
import json

ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

# Load OpenAI API key from environment
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

@ai_bp.route('/chat/completions', methods=['POST'])
@auth_required
def chat_completions():
    """
    Proxy OpenAI chat completions to keep API key secure.
    POST /api/ai/chat/completions
    Body: { messages, tools, tool_choice, temperature, ... }
    """
    if not OPENAI_API_KEY:
        return jsonify({'error': 'OpenAI API key not configured'}), 500
    
    data = request.get_json() or {}
    
    # Build OpenAI request payload
    payload = {
        'model': data.get('model', 'gpt-4-turbo-preview'),
        'messages': data.get('messages', []),
        'temperature': data.get('temperature', 0.7),
        'max_tokens': data.get('max_tokens', 2000),
    }
    
    # Convert old-style functions to new tools format
    if 'functions' in data and data['functions']:
        tools = []
        for func in data['functions']:
            tools.append({
                'type': 'function',
                'function': {
                    'name': func['name'],
                    'description': func['description'],
                    'parameters': func['parameters']
                }
            })
        payload['tools'] = tools
        
        # Convert function_call to tool_choice
        if data.get('function_call') == 'auto':
            payload['tool_choice'] = 'auto'
        elif data.get('function_call'):
            payload['tool_choice'] = {
                'type': 'function',
                'function': {'name': data['function_call']}
            }
    
    # Forward request to OpenAI API
    try:
        print(f"🤖 Sending request to OpenAI API...")
        print(f"Model: {payload['model']}")
        print(f"Messages count: {len(payload['messages'])}")
        print(f"Tools count: {len(payload.get('tools', []))}")
        
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=60
        )
        
        # Log response for debugging
        if response.status_code != 200:
            print(f"❌ OpenAI API Error {response.status_code}: {response.text}")
            return jsonify({
                'error': f'OpenAI API returned {response.status_code}',
                'details': response.text
            }), 500
        
        result = response.json()
        
        # Convert new-style tool_calls back to old-style function_call for frontend compatibility
        if result.get('choices') and len(result['choices']) > 0:
            choice = result['choices'][0]
            message = choice.get('message', {})
            
            # If there are tool_calls, convert first one to function_call
            if message.get('tool_calls'):
                tool_call = message['tool_calls'][0]
                if tool_call['type'] == 'function':
                    message['function_call'] = {
                        'name': tool_call['function']['name'],
                        'arguments': tool_call['function']['arguments']
                    }
                    # Remove tool_calls for backward compatibility
                    del message['tool_calls']
        
        print(f"✅ OpenAI API response received successfully")
        return jsonify(result), 200
        
    except requests.exceptions.Timeout:
        print(f"⏱️ OpenAI API timeout")
        return jsonify({
            'error': 'Request to OpenAI API timed out',
            'details': 'The request took too long. Please try again.'
        }), 504
        
    except requests.exceptions.RequestException as e:
        print(f"❌ OpenAI API Error: {e}")
        return jsonify({
            'error': 'Failed to communicate with OpenAI API',
            'details': str(e)
        }), 500