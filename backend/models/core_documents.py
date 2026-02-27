# C:\streemlyne_crm_backend\backend\models\core_documents.py
"""
Document and Activity Models for StreemLyne CRM
Handles documents, activities, notes, templates, forms, and audit logs

SCHEMA: StreemLyne_MT

NOTE: The tables defined here (activities, opportunity_notes, audit_logs, etc.)
are application-level tables that do not appear in the base schema DDL.
They must be created via Alembic migration or db.create_all().
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================
# ACTIVITIES
# ============================================================

class Activity(db.Model):
    """SCHEMA: StreemLyne_MT.activities"""
    __tablename__ = 'activities'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # meeting, call, email, task
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    scheduled_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='Scheduled')  # Scheduled, Completed, Cancelled
    assigned_to = db.Column(db.String(200))
    created_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='activities')
    opportunity = db.relationship('OpportunityDetails', backref='activities')

    def __repr__(self):
        return f'<Activity {self.title}>'

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
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


# ============================================================
# OPPORTUNITY NOTES
# ============================================================

class OpportunityNote(db.Model):
    """SCHEMA: StreemLyne_MT.opportunity_notes"""
    __tablename__ = 'opportunity_notes'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    opportunity_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Opportunity_Details.opportunity_id'), nullable=False)
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
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# DOCUMENT TEMPLATES
# ============================================================

class DocumentTemplate(db.Model):
    """SCHEMA: StreemLyne_MT.document_templates"""
    __tablename__ = 'document_templates'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    template_type = db.Column(db.String(50), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    merge_fields = db.Column(db.JSON)
    uploaded_by = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='document_templates')

    def __repr__(self):
        return f'<DocumentTemplate {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'name': self.name,
            'template_type': self.template_type,
            'file_path': self.file_path,
            'merge_fields': self.merge_fields,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None
        }


# ============================================================
# FORM SUBMISSIONS
# ============================================================

class FormSubmission(db.Model):
    """SCHEMA: StreemLyne_MT.form_submissions"""
    __tablename__ = 'form_submissions'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
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
            'processed_at': self.processed_at.isoformat() if self.processed_at else None
        }


# ============================================================
# CUSTOMER FORM DATA
# ============================================================

class CustomerFormData(db.Model):
    """SCHEMA: StreemLyne_MT.customer_form_data"""
    __tablename__ = 'customer_form_data'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=False)
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
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None
        }


# ============================================================
# DATA IMPORT
# ============================================================

class DataImport(db.Model):
    """SCHEMA: StreemLyne_MT.data_imports"""
    __tablename__ = 'data_imports'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
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
        return f'<DataImport {self.filename} ({self.status})>'

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
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


# ============================================================
# AUDIT LOG
# ============================================================

class AuditLog(db.Model):
    """SCHEMA: StreemLyne_MT.audit_logs"""
    __tablename__ = 'audit_logs'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.SmallInteger, nullable=False)
    action = db.Column(db.String(20), nullable=False)  # create, update, delete
    changed_by = db.Column(db.String(200))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    change_summary = db.Column(db.JSON)
    previous_snapshot = db.Column(db.JSON)
    new_snapshot = db.Column(db.JSON)

    tenant = db.relationship('TenantMaster', backref='audit_logs')

    def __repr__(self):
        return f'<AuditLog {self.entity_type} {self.entity_id} {self.action}>'

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
            'new_snapshot': self.new_snapshot
        }


# ============================================================
# VERSIONED SNAPSHOT
# ============================================================

class VersionedSnapshot(db.Model):
    """SCHEMA: StreemLyne_MT.versioned_snapshots"""
    __tablename__ = 'versioned_snapshots'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=True, index=True)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.SmallInteger, nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255))
    snapshot = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(200))

    tenant = db.relationship('TenantMaster', backref='versioned_snapshots')

    def __repr__(self):
        return f'<VersionedSnapshot {self.entity_type} v{self.version_number}>'

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
            'created_by': self.created_by
        }


# ============================================================
# CHAT CONVERSATIONS
# ============================================================

class ChatConversation(db.Model):
    """SCHEMA: StreemLyne_MT.chat_conversations"""
    __tablename__ = 'chat_conversations'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    user_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), nullable=False, index=True)
    title = db.Column(db.String(255), default='New Conversation')
    session_id = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='chat_conversations')
    user = db.relationship('UserMaster', backref='chat_conversations')
    # cascade delete-orphan: deleting a conversation deletes its messages
    messages = db.relationship('ChatMessage', back_populates='conversation', lazy=True, cascade='all, delete-orphan')

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
            # FIX: messages is not a dynamic relationship — len() not .count()
            'message_count': len(self.messages) if self.messages else 0
        }


# ============================================================
# CHAT MESSAGES
# ============================================================

class ChatMessage(db.Model):
    """SCHEMA: StreemLyne_MT.chat_messages"""
    __tablename__ = 'chat_messages'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    user_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), nullable=False, index=True)
    conversation_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.chat_conversations.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
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
            'role': self.role,
            'content': self.content,
            'function_calls': self.function_calls,
            'tool_results': self.tool_results,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# CHAT HISTORY (Simplified blob storage)
# ============================================================

class ChatHistory(db.Model):
    """SCHEMA: StreemLyne_MT.chat_history"""
    __tablename__ = 'chat_history'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    user_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.User_Master.user_id'), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, index=True)
    messages = db.Column(db.JSON, nullable=False)
    title = db.Column(db.String(255))
    context = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='chat_history')
    user = db.relationship('UserMaster', backref='chat_history')

    def __repr__(self):
        return f'<ChatHistory {self.id} - Session: {self.session_id}>'

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
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }