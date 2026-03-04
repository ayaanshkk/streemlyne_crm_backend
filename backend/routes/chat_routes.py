"""
Chat Routes
AI chat sessions are application-level data — no corresponding StreemLyne_MT table.
ChatHistory, ChatConversation, ChatMessage are app-managed models (not in core schema).

All logic is unchanged; imports and error handling have been standardised to match
the rest of the refactored route layer.
"""

from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import SQLAlchemyError
from database import db
from models import ChatHistory, ChatConversation, ChatMessage
from middleware import auth_required
from datetime import datetime
import uuid

chat_bp = Blueprint('chat', __name__, url_prefix='/api/chat')


# ─────────────────────────────────────────
# Chat Sessions  (JSON-based, single-table)
# ─────────────────────────────────────────

@chat_bp.route('/sessions', methods=['GET'])
@auth_required
def list_sessions():
    """
    List all chat sessions for the current user / tenant.
    GET /api/chat/sessions
    """
    sessions = (
        ChatHistory.query
        .filter_by(tenant_id=g.tenant_id, user_id=g.user_id)
        .order_by(ChatHistory.updated_at.desc())
        .all()
    )
    return jsonify([s.to_dict() for s in sessions]), 200


@chat_bp.route('/sessions', methods=['POST'])
@auth_required
def create_session():
    """
    Create a new chat session.
    POST /api/chat/sessions
    Body: { "session_id": "...", "title": "...", "messages": [], "context": {} }
    """
    data = request.get_json() or {}

    session = ChatHistory(
        tenant_id=g.tenant_id,
        user_id=g.user_id,
        session_id=data.get('session_id') or str(uuid.uuid4()),
        title=data.get('title', 'New Chat'),
        messages=data.get('messages', []),
        context=data.get('context', {})
    )
    db.session.add(session)
    db.session.commit()
    return jsonify(session.to_dict()), 201


@chat_bp.route('/sessions/<string:session_id>', methods=['GET'])
@auth_required
def get_session(session_id):
    """
    Retrieve a single chat session.
    GET /api/chat/sessions/<session_id>
    """
    session = _get_session_or_404(session_id)
    return jsonify(session.to_dict()), 200


@chat_bp.route('/sessions/<string:session_id>', methods=['PUT'])
@auth_required
def update_session(session_id):
    """
    Update a chat session's messages, title, or context.
    PUT /api/chat/sessions/<session_id>
    """
    session = _get_session_or_404(session_id)
    data = request.get_json() or {}

    if 'messages' in data:
        session.messages = data['messages']
    if 'title' in data:
        session.title = data['title']
    if 'context' in data:
        session.context = data['context']

    session.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(session.to_dict()), 200


@chat_bp.route('/sessions/<string:session_id>', methods=['DELETE'])
@auth_required
def delete_session(session_id):
    """
    Delete a chat session.
    DELETE /api/chat/sessions/<session_id>
    """
    session = _get_session_or_404(session_id)
    db.session.delete(session)
    db.session.commit()
    return jsonify({'message': 'Session deleted'}), 200


# ─────────────────────────────────────────
# Conversations  (structured message model)
# ─────────────────────────────────────────

@chat_bp.route('/conversations', methods=['GET'])
@auth_required
def list_conversations():
    """
    List all conversations for the current user / tenant.
    GET /api/chat/conversations
    """
    conversations = (
        ChatConversation.query
        .filter_by(tenant_id=g.tenant_id, user_id=g.user_id)
        .order_by(ChatConversation.updated_at.desc())
        .all()
    )
    return jsonify([c.to_dict() for c in conversations]), 200


@chat_bp.route('/conversations', methods=['POST'])
@auth_required
def create_conversation():
    """
    Create a new conversation.
    POST /api/chat/conversations
    Body: { "title": "..." }
    """
    data = request.get_json() or {}
    conv = ChatConversation(
        tenant_id=g.tenant_id,
        user_id=g.user_id,
        title=data.get('title', 'New Conversation')
    )
    db.session.add(conv)
    db.session.commit()
    return jsonify(conv.to_dict()), 201


@chat_bp.route('/conversations/<string:conversation_id>', methods=['GET'])
@auth_required
def get_conversation(conversation_id):
    """
    Retrieve a conversation and all its messages, ordered chronologically.
    GET /api/chat/conversations/<conversation_id>
    """
    conv = _get_conversation_or_404(conversation_id)

    messages = (
        ChatMessage.query
        .filter_by(
            conversation_id=conversation_id,
            tenant_id=g.tenant_id,
            user_id=g.user_id
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return jsonify({
        'conversation': conv.to_dict(),
        'messages': [m.to_dict() for m in messages]
    }), 200


@chat_bp.route('/conversations/<string:conversation_id>/messages', methods=['POST'])
@auth_required
def add_message(conversation_id):
    """
    Add a message to a conversation.
    POST /api/chat/conversations/<conversation_id>/messages
    Body: { "role": "user", "content": "...", "function_calls": null, "tool_results": null }
    """
    conv = _get_conversation_or_404(conversation_id)
    data = request.get_json() or {}

    if not data.get('content'):
        return jsonify({'error': 'content is required'}), 400

    message = ChatMessage(
        tenant_id=g.tenant_id,
        user_id=g.user_id,
        conversation_id=conversation_id,
        role=data.get('role', 'user'),
        content=data['content'],
        function_calls=data.get('function_calls'),
        tool_results=data.get('tool_results')
    )
    db.session.add(message)
    conv.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(message.to_dict()), 201


@chat_bp.route('/conversations/<string:conversation_id>', methods=['DELETE'])
@auth_required
def delete_conversation(conversation_id):
    """
    Delete a conversation and all its messages.
    DELETE /api/chat/conversations/<conversation_id>
    """
    conv = _get_conversation_or_404(conversation_id)
    # Cascade-delete messages belonging to this conversation
    ChatMessage.query.filter_by(
        conversation_id=conversation_id,
        tenant_id=g.tenant_id
    ).delete()
    db.session.delete(conv)
    db.session.commit()
    return jsonify({'message': 'Conversation deleted'}), 200


# ─────────────────────────────────────────
# Utility
# ─────────────────────────────────────────

@chat_bp.route('/clear-all', methods=['DELETE'])
@auth_required
def clear_all():
    """
    Delete all chat data (sessions + conversations + messages) for the current user.
    DELETE /api/chat/clear-all
    """
    try:
        # Remove messages first to satisfy any FK constraints
        conv_ids = [
            c.id for c in ChatConversation.query.filter_by(
                tenant_id=g.tenant_id, user_id=g.user_id
            ).with_entities(ChatConversation.id).all()
        ]
        if conv_ids:
            ChatMessage.query.filter(
                ChatMessage.conversation_id.in_(conv_ids)
            ).delete(synchronize_session=False)

        ChatConversation.query.filter_by(
            tenant_id=g.tenant_id, user_id=g.user_id
        ).delete()
        ChatHistory.query.filter_by(
            tenant_id=g.tenant_id, user_id=g.user_id
        ).delete()
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'All chat history cleared'}), 200


# ─────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────

def _get_session_or_404(session_id: str) -> ChatHistory:
    session = ChatHistory.query.filter_by(
        session_id=session_id,
        tenant_id=g.tenant_id,
        user_id=g.user_id
    ).first()
    if not session:
        from flask import abort
        abort(404, description='Session not found')
    return session


def _get_conversation_or_404(conversation_id: str) -> ChatConversation:
    conv = ChatConversation.query.filter_by(
        id=conversation_id,
        tenant_id=g.tenant_id,
        user_id=g.user_id
    ).first()
    if not conv:
        from flask import abort
        abort(404, description='Conversation not found')
    return conv