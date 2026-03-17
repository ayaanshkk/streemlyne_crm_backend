"""
Assignment model — application-level table for the Schedule feature.

Not part of the original StreemLyne_MT schema dump, but follows the same
pattern as ChatHistory / ChatConversation / ChatMessage: registered at
startup via SQLAlchemy and created via `flask db migrate && flask db upgrade`.

Table: assignments
  assignment_id   — PK
  tenant_id       — FK → Tenant_Master  (row-level tenant isolation)
  type            — meeting | call | task | delivery | note
  title           — display label on the calendar card
  date            — the scheduled date (DATE, not timestamp)
  staff_name      — free-text name of the assigned team member
  project_id      — FK → Project_Details (nullable, the linked job)
  client_id       — FK → Client_Master   (nullable, the linked client)
  estimated_hours — how long the task is expected to take
  notes           — internal notes
  priority        — Low | Medium | High | Urgent
  status          — Scheduled | In Progress | Completed | Cancelled
  created_at      — auto-set on insert
  updated_at      — updated on every PUT
"""

from datetime import datetime, date
from database import db


class Assignment(db.Model):
    __tablename__ = 'assignments'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    assignment_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tenant_id       = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Tenant_Master.tenant_id'), nullable=False)
    type            = db.Column(db.String(50), nullable=False, default='task')
    title           = db.Column(db.String(255), nullable=False)
    date            = db.Column(db.Date, nullable=False)
    staff_name      = db.Column(db.String(150), nullable=True)

    # Optional FK links — project_id = "job" in frontend terminology
    project_id      = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Project_Details.project_id'), nullable=True)
    client_id       = db.Column(db.Integer, db.ForeignKey('StreemLyne_MT.Client_Master.client_id'), nullable=True)

    estimated_hours = db.Column(db.Float, nullable=True)
    notes           = db.Column(db.Text, nullable=True)
    priority        = db.Column(db.String(50), nullable=True, default='Medium')
    status          = db.Column(db.String(50), nullable=True, default='Scheduled')

    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at      = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships (lazy load — avoids N+1 on list queries)
    project = db.relationship('ProjectDetails', backref='assignments', lazy='select', foreign_keys=[project_id])
    client  = db.relationship('ClientMaster',   backref='assignments', lazy='select', foreign_keys=[client_id])

    def __repr__(self):
        return f'<Assignment {self.assignment_id} [{self.type}] {self.date}>'