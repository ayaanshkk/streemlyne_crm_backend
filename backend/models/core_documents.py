"""
Document, Activity, Chat, and Audit Models for StreemLyne CRM

These are application-level tables that extend the base schema DDL.
They live in the StreemLyne_MT schema but are NOT part of the core
Supabase DDL — create them via Alembic migration or db.create_all().

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


__all__ = [
    'Activity',
    'OpportunityNote',
    'DocumentTemplate',
    'FormSubmission',
    'CustomerFormData',
    'DataImport',
    'AuditLog',
    'VersionedSnapshot',
    'ChatConversation',
    'ChatMessage',
    'ChatHistory',
]


# ============================================================
# ACTIVITIES
# ============================================================

class Activity(db.Model):
    """
    Scheduled / completed activities linked to an opportunity
    (meetings, calls, emails, tasks).

    status values: 'Scheduled' | 'Completed' | 'Cancelled'
    activity_type values: 'meeting' | 'call' | 'email' | 'task'

    SCHEMA: StreemLyne_MT.activities  (application-level table)
    """
    __tablename__ = 'activities'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    opportunity_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'),
        nullable=False,
    )
    activity_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    scheduled_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='Scheduled')
    assigned_to = db.Column(db.String(200))
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='activities')
    opportunity = db.relationship('OpportunityDetails', backref='activities')

    def __repr__(self):
        return f'<Activity {self.id}: {self.title}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'opportunity_id': self.opportunity_id,
            'activity_type': self.activity_type,
            'title': self.title,
            'description': self.description,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'completed_date': self.completed_date.isoformat() if self.completed_date else None,
            'status': self.status,
            'assigned_to': self.assigned_to,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# OPPORTUNITY NOTES
# ============================================================

class OpportunityNote(db.Model):
    """
    Free-text notes attached to an opportunity.

    SCHEMA: StreemLyne_MT.opportunity_notes  (application-level table)
    """
    __tablename__ = 'opportunity_notes'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    opportunity_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'),
        nullable=False,
    )
    content = db.Column(db.Text, nullable=False)
    note_type = db.Column(db.String(50), default='general')
    author = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='opportunity_notes')
    opportunity = db.relationship('OpportunityDetails', backref='notes')

    def __repr__(self):
        return f'<OpportunityNote {self.id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'opportunity_id': self.opportunity_id,
            'content': self.content,
            'note_type': self.note_type,
            'author': self.author,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# DOCUMENT TEMPLATES
# ============================================================

class DocumentTemplate(db.Model):
    """
    Tenant-owned document templates (DOCX/PDF) used for mail-merge.

    merge_fields is a JSON dict of field_name → description pairs.

    SCHEMA: StreemLyne_MT.document_templates  (application-level table)
    """
    __tablename__ = 'document_templates'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    template_type = db.Column(db.String(50), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    merge_fields = db.Column(db.JSON)
    uploaded_by = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='document_templates')

    def __repr__(self):
        return f'<DocumentTemplate {self.id}: {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'name': self.name,
            'template_type': self.template_type,
            'file_path': self.file_path,
            'merge_fields': self.merge_fields,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


# ============================================================
# FORM SUBMISSIONS
# ============================================================

class FormSubmission(db.Model):
    """
    Raw inbound form submissions from public-facing lead-capture forms.
    tenant_id may be NULL for submissions before tenant resolution.

    SCHEMA: StreemLyne_MT.form_submissions  (application-level table)
    """
    __tablename__ = 'form_submissions'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=True,
        index=True,
    )
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    form_data = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(100))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime)

    tenant = db.relationship('TenantMaster', backref='form_submissions')
    client = db.relationship('ClientMaster', backref='form_submissions')

    def __repr__(self):
        return f'<FormSubmission {self.id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'client_id': self.client_id,
            'form_data': self.form_data,
            'source': self.source,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'processed': self.processed,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }


# ============================================================
# CUSTOMER FORM DATA
# ============================================================

class CustomerFormData(db.Model):
    """
    Structured form submissions from the customer portal (token-authenticated).

    token_used records which one-time link was consumed.

    SCHEMA: StreemLyne_MT.customer_form_data  (application-level table)
    """
    __tablename__ = 'customer_form_data'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=True,
        index=True,
    )
    client_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Client_Master.client_id'),
        nullable=False,
    )
    form_data = db.Column(db.Text, nullable=False)
    token_used = db.Column(db.String(64), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='customer_form_data')
    client = db.relationship('ClientMaster', backref='form_data')

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Client {self.client_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'client_id': self.client_id,
            'form_data': self.form_data,
            'token_used': self.token_used,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }


# ============================================================
# DATA IMPORT
# ============================================================

class DataImport(db.Model):
    """
    Tracks bulk CSV/XLSX import jobs.

    status values: 'processing' | 'completed' | 'failed'

    SCHEMA: StreemLyne_MT.data_imports  (application-level table)
    """
    __tablename__ = 'data_imports'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=True,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
    import_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='processing')
    records_processed = db.Column(db.Integer, default=0)
    records_failed = db.Column(db.Integer, default=0)
    error_log = db.Column(db.Text)
    imported_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    tenant = db.relationship('TenantMaster', backref='data_imports')

    def __repr__(self):
        return f'<DataImport {self.id}: {self.filename} ({self.status})>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'filename': self.filename,
            'import_type': self.import_type,
            'status': self.status,
            'records_processed': self.records_processed,
            'records_failed': self.records_failed,
            'error_log': self.error_log,
            'imported_by': self.imported_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ============================================================
# AUDIT LOG
# ============================================================

class AuditLog(db.Model):
    """
    Immutable audit trail for create/update/delete operations.

    change_summary: high-level dict of {field: {old, new}}
    previous_snapshot / new_snapshot: full to_dict() snapshots

    SCHEMA: StreemLyne_MT.audit_logs  (application-level table)
    """
    __tablename__ = 'audit_logs'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=True,
        index=True,
    )
    entity_type = db.Column(db.String(120), nullable=False)    # e.g. 'ClientMaster'
    entity_id = db.Column(db.SmallInteger, nullable=False)
    action = db.Column(db.String(20), nullable=False)           # 'create' | 'update' | 'delete'
    changed_by = db.Column(db.String(200))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    change_summary = db.Column(db.JSON)
    previous_snapshot = db.Column(db.JSON)
    new_snapshot = db.Column(db.JSON)

    tenant = db.relationship('TenantMaster', backref='audit_logs')

    def __repr__(self):
        return f'<AuditLog {self.entity_type}:{self.entity_id} {self.action}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'action': self.action,
            'changed_by': self.changed_by,
            'changed_at': self.changed_at.isoformat() if self.changed_at else None,
            'change_summary': self.change_summary,
            'previous_snapshot': self.previous_snapshot,
            'new_snapshot': self.new_snapshot,
        }


# ============================================================
# VERSIONED SNAPSHOT
# ============================================================

class VersionedSnapshot(db.Model):
    """
    Point-in-time snapshots for entities that require version history.

    version_number is managed by the caller (increment on each save).

    SCHEMA: StreemLyne_MT.versioned_snapshots  (application-level table)
    """
    __tablename__ = 'versioned_snapshots'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=True,
        index=True,
    )
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.SmallInteger, nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255))
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200))

    tenant = db.relationship('TenantMaster', backref='versioned_snapshots')

    def __repr__(self):
        return f'<VersionedSnapshot {self.entity_type}:{self.entity_id} v{self.version_number}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'version_number': self.version_number,
            'reason': self.reason,
            'snapshot': self.snapshot,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
        }


# ============================================================
# CHAT CONVERSATION
# ============================================================

class ChatConversation(db.Model):
    """
    A named AI-chat session belonging to a user.

    Deleting a conversation cascades to its ChatMessage records.
    message_count in to_dict() loads all messages — avoid calling
    on list endpoints; use a COUNT subquery instead.

    SCHEMA: StreemLyne_MT.chat_conversations  (application-level table)
    """
    __tablename__ = 'chat_conversations'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.User_Master.user_id'),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(255), default='New Conversation')
    session_id = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='chat_conversations')
    user = db.relationship('UserMaster', backref='chat_conversations')
    messages = db.relationship(
        'ChatMessage',
        back_populates='conversation',
        lazy=True,                          # 'select' — loads on access
        cascade='all, delete-orphan',
    )

    def __repr__(self):
        return f'<ChatConversation {self.id}: {self.title}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'user_id': self.user_id,
            'title': self.title,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'message_count': len(self.messages) if self.messages else 0,
        }


# ============================================================
# CHAT MESSAGE
# ============================================================

class ChatMessage(db.Model):
    """
    Individual message within a ChatConversation.

    role values: 'user' | 'assistant'
    function_calls / tool_results store raw JSON from the AI provider.

    SCHEMA: StreemLyne_MT.chat_messages  (application-level table)
    """
    __tablename__ = 'chat_messages'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.User_Master.user_id'),
        nullable=False,
        index=True,
    )
    conversation_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.chat_conversations.id'),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    function_calls = db.Column(db.JSON)
    tool_results = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='chat_messages')
    user = db.relationship('UserMaster', backref='chat_messages')
    conversation = db.relationship('ChatConversation', back_populates='messages')

    def __repr__(self):
        return f'<ChatMessage {self.id}: {self.role}>'

    def to_dict(self):
        return {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'tenant_id': self.tenant_id,
            'user_id': self.user_id,
            'role': self.role,
            'content': self.content,
            'function_calls': self.function_calls,
            'tool_results': self.tool_results,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# CHAT HISTORY (blob / simplified storage)
# ============================================================

class ChatHistory(db.Model):
    """
    Denormalised blob storage of an entire conversation's message list.
    Used when full message-by-message granularity is not required.

    messages: JSON array of {role, content} dicts
    context:  optional JSON dict of contextual state passed back to the LLM

    SCHEMA: StreemLyne_MT.chat_history  (application-level table)
    """
    __tablename__ = 'chat_history'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.SmallInteger,
        db.ForeignKey('StreemLyne_MT.User_Master.user_id'),
        nullable=False,
        index=True,
    )
    session_id = db.Column(db.String(100), nullable=False, index=True)
    title = db.Column(db.String(255))
    messages = db.Column(db.JSON, nullable=False)
    context = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='chat_history')
    user = db.relationship('UserMaster', backref='chat_history')

    def __repr__(self):
        return f'<ChatHistory {self.id} session:{self.session_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'tenant_id': self.tenant_id,
            'user_id': self.user_id,
            'title': self.title,
            'messages': self.messages,
            'context': self.context,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }