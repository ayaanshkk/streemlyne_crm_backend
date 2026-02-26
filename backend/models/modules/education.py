# C:\streemlyne_crm_backend\backend\models\modules\education.py
"""
Education Module Models for StreemLyne CRM
Handles test results, certificates, training batches, and PTI forms

SCHEMA: StreemLyne_MT

MAJOR CHANGES FROM OLD SCHEMA:
- All tables now use StreemLyne_MT schema
- UUID tenant/customer/user IDs → SmallInteger references
- Added proper foreign key relationships to new schema tables
- Removed legacy table references
"""

import uuid
import sys
import os
from datetime import datetime

# Add parent directory to path (go up 2 levels: modules/ -> models/ -> backend/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import db


# ============================================================
# TEST GRADING SYSTEM
# ============================================================

class TestResult(db.Model):
    """
    AI-powered test grading results
    Stores student test performance with question-by-question breakdown
    
    SCHEMA: StreemLyne_MT.education_test_results
    
    MIGRATION NOTE:
    - Old: UUID tenant_id, user_id (legacy), customer_id (legacy)
    - New: SmallInteger tenant_id, employee_id (instructor), client_id (student)
    """
    __tablename__ = 'education_test_results'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    employee_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'), nullable=False)  # Instructor who graded
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))  # Student
    
    # Participant Information
    participant_name = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255))
    date = db.Column(db.String(100))
    place = db.Column(db.String(255))
    test_type = db.Column(db.String(100))  # Pre-test, Post-test, Final Exam
    
    # Test Details
    mhe_type = db.Column(db.String(50), nullable=False)  # BOPT, FORKLIFT, REACH_TRUCK, STACKER
    total_marks_obtained = db.Column(db.Integer, nullable=False)
    total_marks = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    grade = db.Column(db.String(20), nullable=False)  # Pass/Fail
    
    # Test Data (JSON)
    answers_json = db.Column(db.Text)  # Student's answers
    details_json = db.Column(db.Text)  # Question-by-question breakdown
    image_base64 = db.Column(db.Text)  # Base64 encoded image of test paper
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    tenant = db.relationship('TenantMaster', backref='education_test_results')
    instructor = db.relationship('EmployeeMaster', backref='graded_test_results')
    client = db.relationship('ClientMaster', backref='test_results')
    
    def __repr__(self):
        return f"<TestResult {self.id} - {self.participant_name} - {self.mhe_type} - {self.grade}>"
    
    def to_dict(self):
        """Convert test result to dictionary"""
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
    Manages certificate generation, dispatch, and validity
    
    SCHEMA: StreemLyne_MT.education_certificates
    """
    __tablename__ = 'education_certificates'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))  # Student
    test_result_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.education_test_results.id'))
    
    # Certificate Details
    certificate_number = db.Column(db.String(100), unique=True)
    certificate_type = db.Column(db.String(100))  # Training Completion, PTI, Safety, etc.
    issue_date = db.Column(db.DateTime)
    valid_until = db.Column(db.DateTime)
    
    # Status Tracking
    status = db.Column(db.String(50))  # Created, Dispatched, Received
    dispatch_date = db.Column(db.DateTime)
    dispatch_method = db.Column(db.String(50))  # Email, Courier, In-person
    recipient = db.Column(db.String(255))
    tracking_number = db.Column(db.String(100))
    
    # Certificate Data
    certificate_data = db.Column(db.JSON)  # Student info, course details, marks
    certificate_url = db.Column(db.String(500))  # PDF storage location
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
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
    Tracks participants, schedule, and batch capacity
    
    SCHEMA: StreemLyne_MT.education_training_batches
    """
    __tablename__ = 'education_training_batches'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    
    # Batch Info
    batch_number = db.Column(db.String(100), unique=True)
    batch_name = db.Column(db.String(255))
    course_type = db.Column(db.String(100))  # Forklift, Reach Truck, BOPT, Stacker
    
    # Schedule
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    duration_days = db.Column(db.Integer)
    
    # Capacity
    max_participants = db.Column(db.Integer)
    enrolled_count = db.Column(db.Integer, default=0)
    
    # Instructor & Venue
    instructor_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    venue = db.Column(db.String(255))
    venue_address = db.Column(db.Text)
    
    # Status
    status = db.Column(db.String(50))  # Scheduled, Ongoing, Completed, Cancelled
    
    # Batch Data (participants list, materials needed, etc.)
    batch_data = db.Column(db.JSON)
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
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
# PTI FORMS (Practical Training Instructor)
# ============================================================

class PTIForm(db.Model):
    """
    Practical Training Instructor forms
    Records practical training assessment and instructor sign-off
    
    SCHEMA: StreemLyne_MT.education_pti_forms
    """
    __tablename__ = 'education_pti_forms'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    id = db.Column(db.SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False, index=True)
    client_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'))  # Student
    
    # PTI Details
    pti_number = db.Column(db.String(100), unique=True)
    participant_name = db.Column(db.String(255))
    company = db.Column(db.String(255))
    equipment_type = db.Column(db.String(100))  # MHE type
    
    # Training Records
    training_date = db.Column(db.DateTime)
    training_hours = db.Column(db.Float)
    practical_assessment = db.Column(db.JSON)  # Checklist items with pass/fail
    
    # Instructor Sign-off
    instructor_id = db.Column(db.SmallInteger, db.ForeignKey('StreemLyne_MT.Employee_Master.employee_id'))
    instructor_signature = db.Column(db.Text)  # Base64 signature image
    sign_off_date = db.Column(db.DateTime)
    
    # Status
    status = db.Column(db.String(50))  # Draft, Approved, Archived
    
    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
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
