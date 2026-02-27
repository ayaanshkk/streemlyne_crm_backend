# C:\streemlyne_crm_backend\backend\models\modules\education.py
"""
Education Module Models for StreemLyne CRM
Handles test results, certificates, training batches, and PTI forms

SCHEMA: StreemLyne_MT
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import db


# ============================================================
# TEST GRADING SYSTEM
# ============================================================

class TestResult(db.Model):
    """
    AI-powered test grading results

    SCHEMA: StreemLyne_MT.education_test_results
    """
    __tablename__ = 'education_test_results'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))

    participant_name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255))
    date = db.Column(db.String(100))
    place = db.Column(db.String(255))
    test_type = db.Column(db.String(100))
    mhe_type = db.Column(db.String(50), nullable=False)
    total_marks_obtained = db.Column(db.Integer, nullable=False)
    total_marks = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    answers_json = db.Column(db.Text)
    details_json = db.Column(db.Text)
    image_base64 = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='education_test_results')
    instructor = db.relationship('EmployeeMaster', backref='graded_test_results')
    client = db.relationship('ClientMaster', backref='test_results')

    def __repr__(self):
        return f'<TestResult {self.id} - {self.participant_name} - {self.mhe_type} - {self.grade}>'

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'employee_id': self.employee_id,
            'instructor_name': self.instructor.employee_name if self.instructor else None,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'participant_name': self.participant_name,
            'company': self.company,
            'date': self.date,
            'place': self.place,
            'test_type': self.test_type,
            'mhe_type': self.mhe_type,
            'total_marks_obtained': self.total_marks_obtained,
            'total_marks': self.total_marks,
            'percentage': self.percentage,
            'grade': self.grade,
            'answers': json.loads(self.answers_json) if self.answers_json else {},
            'details': json.loads(self.details_json) if self.details_json else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# CERTIFICATE MANAGEMENT
# ============================================================

class Certificate(db.Model):
    """
    Certificate tracking for training completion

    SCHEMA: StreemLyne_MT.education_certificates
    """
    __tablename__ = 'education_certificates'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))
    test_result_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.education_test_results.id'))

    certificate_number = db.Column(db.String(100), unique=True)
    certificate_type = db.Column(db.String(100))
    issue_date = db.Column(db.DateTime)
    valid_until = db.Column(db.DateTime)
    status = db.Column(db.String(50))
    dispatch_date = db.Column(db.DateTime)
    dispatch_method = db.Column(db.String(50))
    recipient = db.Column(db.String(255))
    tracking_number = db.Column(db.String(100))
    certificate_data = db.Column(db.JSON)
    certificate_url = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='education_certificates')
    client = db.relationship('ClientMaster', backref='certificates')
    test_result = db.relationship('TestResult', backref='certificates')

    def __repr__(self):
        return f'<Certificate {self.certificate_number} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'test_result_id': self.test_result_id,
            'certificate_number': self.certificate_number,
            'certificate_type': self.certificate_type,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'status': self.status,
            'dispatch_date': self.dispatch_date.isoformat() if self.dispatch_date else None,
            'dispatch_method': self.dispatch_method,
            'recipient': self.recipient,
            'tracking_number': self.tracking_number,
            'certificate_data': self.certificate_data,
            'certificate_url': self.certificate_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# BATCH TRAINING MANAGEMENT
# ============================================================

class TrainingBatch(db.Model):
    """
    Training batch management for group training sessions

    SCHEMA: StreemLyne_MT.education_training_batches
    """
    __tablename__ = 'education_training_batches'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)

    batch_number = db.Column(db.String(100), unique=True)
    batch_name = db.Column(db.String(255))
    course_type = db.Column(db.String(100))
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    duration_days = db.Column(db.Integer)
    max_participants = db.Column(db.Integer)
    enrolled_count = db.Column(db.Integer, default=0)
    instructor_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    venue = db.Column(db.String(255))
    venue_address = db.Column(db.Text)
    status = db.Column(db.String(50))
    batch_data = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='education_training_batches')
    instructor = db.relationship('EmployeeMaster', backref='training_batches')

    def __repr__(self):
        return f'<TrainingBatch {self.batch_number} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'batch_number': self.batch_number,
            'batch_name': self.batch_name,
            'course_type': self.course_type,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'duration_days': self.duration_days,
            'max_participants': self.max_participants,
            'enrolled_count': self.enrolled_count,
            'instructor_id': self.instructor_id,
            'instructor_name': self.instructor.employee_name if self.instructor else None,
            'venue': self.venue,
            'venue_address': self.venue_address,
            'status': self.status,
            'batch_data': self.batch_data,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# PTI FORMS
# ============================================================

class PTIForm(db.Model):
    """
    Practical Training Instructor forms

    SCHEMA: StreemLyne_MT.education_pti_forms
    """
    __tablename__ = 'education_pti_forms'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))

    pti_number = db.Column(db.String(100), unique=True)
    participant_name = db.Column(db.String(255))
    company = db.Column(db.String(255))
    equipment_type = db.Column(db.String(100))
    training_date = db.Column(db.DateTime)
    training_hours = db.Column(db.Float)
    practical_assessment = db.Column(db.JSON)
    instructor_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    instructor_signature = db.Column(db.Text)
    sign_off_date = db.Column(db.DateTime)
    status = db.Column(db.String(50))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = db.relationship('TenantMaster', backref='education_pti_forms')
    client = db.relationship('ClientMaster', backref='pti_forms')
    instructor = db.relationship('EmployeeMaster', backref='pti_forms')

    def __repr__(self):
        return f'<PTIForm {self.pti_number} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'client_id': self.client_id,
            'client_name': self.client.client_company_name if self.client else None,
            'pti_number': self.pti_number,
            'participant_name': self.participant_name,
            'company': self.company,
            'equipment_type': self.equipment_type,
            'training_date': self.training_date.isoformat() if self.training_date else None,
            'training_hours': self.training_hours,
            'practical_assessment': self.practical_assessment,
            'instructor_id': self.instructor_id,
            'instructor_name': self.instructor.employee_name if self.instructor else None,
            'sign_off_date': self.sign_off_date.isoformat() if self.sign_off_date else None,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }