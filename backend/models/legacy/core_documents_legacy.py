"""
Legacy Document Models — Default Schema (No StreemLyne_MT prefix)

Only OpportunityDocument remains unique to this file.
All other legacy document models (Activity, OpportunityNote, etc.) were
consolidated into core_documents.py to eliminate table-name conflicts.

If you need the old versions, see models/legacy/core_legacy.py.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db


__all__ = ['OpportunityDocument']


# ============================================================
# OPPORTUNITY DOCUMENTS (Legacy)
# ============================================================

class OpportunityDocument(db.Model):
    """
    Files attached to legacy Opportunity records.
    New equivalent: CaseDocuments (StreemLyne_MT.Case_Documents)

    NOTE: This model remains in the legacy schema because CaseDocuments
    uses client_id + opportunity_id FKs to the new schema tables, while
    this model references the legacy UUID-based opportunities table.
    Migrate outstanding rows to CaseDocuments before retiring this model.
    """
    __tablename__ = 'opportunity_documents'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(36), db.ForeignKey('tenants.id'), nullable=False, index=True)
    opportunity_id = db.Column(db.String(36), db.ForeignKey('opportunities.id'), nullable=False)

    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)            # Bytes
    mime_type = db.Column(db.String(100))
    category = db.Column(db.String(50))

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
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }