# C:\streemlyne_crm_backend\backend\models\legacy\core_documents_legacy.py
"""
Legacy Document Models - Only OpportunityDocument remains unique

NOTE: Activity, OpportunityNote, DocumentTemplate, FormSubmission, etc.
are now defined in core_documents.py to avoid table name conflicts.
Import those from the main models package instead.
"""

import uuid
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


# ============================================================
# OPPORTUNITY DOCUMENTS (Legacy - unique to this file)
# ============================================================

class OpportunityDocument(db.Model):
    """Documents attached to opportunities (Legacy model)"""
    __tablename__ = 'opportunity_documents'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)
    
    # File Info
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    category = db.Column(db.String(50))
    
    # Audit
    uploaded_by = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    opportunity = db.relationship('Opportunity', back_populates='documents')
    tenant = db.relationship('Tenant')

    def __repr__(self):
        return f'<OpportunityDocument {self.filename}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'opportunity_id': self.opportunity_id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'category': self.category,
            'uploaded_by': self.uploaded_by,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================================
# NOTE: The following models are now defined in core_documents.py
# to avoid table name conflicts. They are imported by legacy/__init__.py
# from core_documents for backward compatibility:
# 
# - Activity
# - OpportunityNote
# - DocumentTemplate
# - FormSubmission
# - CustomerFormData
# - DataImport
# - AuditLog
# - VersionedSnapshot
# - ChatConversation
# - ChatMessage
# - ChatHistory
# ============================================================