# # job_routes.py - Flask API endpoints for job management

# from flask import Blueprint, request, jsonify
# from datetime import datetime, date
# from database import db  # Import from database.py instead of models
# from models import (
#     Job, Customer, Team, Fitter, Salesperson, 
#     JobDocument, JobFormLink, FormSubmission, 
#     JobNote, Quotation
# )

# job_bp = Blueprint('jobs', __name__)

# def generate_job_reference():
#     """Generate auto job reference"""
#     now = datetime.now()
#     year = now.year
#     month = str(now.month).zfill(2)
#     day = str(now.day).zfill(2)
#     time = str(now.hour).zfill(2) + str(now.minute).zfill(2)
#     return f"AZT-{year}-{month}{day}-{time}"

# def serialize_job(job):
#     """Serialize job object to dictionary"""
#     return {
#         'id': job.id,
#         'job_reference': job.job_reference,
#         'job_name': job.job_name,
#         'customer_id': job.customer_id,
#         'customer_name': job.customer.name if job.customer else None,
#         'type': job.type,
#         'stage': job.stage,
#         'priority': job.priority,
#         'measure_date': job.measure_date.isoformat() if job.measure_date else None,
#         'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
#         'completion_date': job.completion_date.isoformat() if job.completion_date else None,
#         'quote_id': job.quote_id,
#         'quote_price': float(job.quote_price) if job.quote_price else None,
#         'agreed_price': float(job.agreed_price) if job.agreed_price else None,
#         'deposit_amount': float(job.deposit_amount) if job.deposit_amount else None,
#         'deposit_due_date': job.deposit_due_date.isoformat() if job.deposit_due_date else None,
#         'installation_address': job.installation_address,
#         'assigned_team_id': job.assigned_team_id,
#         'assigned_team_name': job.assigned_team.name if job.assigned_team else None,
#         'primary_fitter_id': job.primary_fitter_id,
#         'primary_fitter_name': job.primary_fitter.name if job.primary_fitter else None,
#         'salesperson_id': job.salesperson_id,
#         'salesperson_name': job.salesperson.name if job.salesperson else None,
#         'tags': job.tags,
#         'notes': job.notes,
#         'has_counting_sheet': job.has_counting_sheet,
#         'has_schedule': job.has_schedule,
#         'has_invoice': job.has_invoice,
#         'created_at': job.created_at.isoformat() if job.created_at else None,
#         'updated_at': job.updated_at.isoformat() if job.updated_at else None,
#     }

# @job_bp.route('/jobs', methods=['GET'])
# def get_jobs():
#     """Get all jobs with optional filtering"""
#     try:
#         customer_id = request.args.get('customer_id')
#         stage = request.args.get('stage')
#         job_type = request.args.get('type')
        
#         query = Job.query
        
#         if customer_id:
#             query = query.filter(Job.customer_id == customer_id)
#         if stage:
#             query = query.filter(Job.stage == stage)
#         if job_type:
#             query = query.filter(Job.type == job_type)
        
#         jobs = query.order_by(Job.created_at.desc()).all()
        
#         return jsonify([serialize_job(job) for job in jobs])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>', methods=['GET'])
# def get_job(job_id):
#     """Get a specific job by ID"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         return jsonify(serialize_job(job))
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs', methods=['POST'])
# def create_job():
#     """Create a new job"""
#     try:
#         data = request.get_json()
#         print("Received data:", data)
        
#         # Validate required fields
#         required_fields = ['customer_id', 'type', 'installation_address']
#         missing_fields = []
        
#         for field in required_fields:
#             if not data.get(field):
#                 missing_fields.append(field)
        
#         if missing_fields:
#             error_msg = f"Missing required fields: {', '.join(missing_fields)}"
#             print("Validation error:", error_msg)
#             return jsonify({'error': error_msg}), 400
        
#         # Validate customer exists
#         customer = Customer.query.get(data['customer_id'])
#         if not customer:
#             return jsonify({'error': 'Customer not found'}), 400
        
#         # Generate job reference if not provided
#         job_reference = data.get('job_reference') or generate_job_reference()
        
#         # Check if job reference is unique
#         existing_job = Job.query.filter_by(job_reference=job_reference).first()
#         if existing_job:
#             return jsonify({'error': 'Job reference already exists'}), 400
        
#         # Parse dates safely
#         def parse_date(date_str):
#             if date_str:
#                 try:
#                     return datetime.strptime(date_str, '%Y-%m-%d').date()
#                 except ValueError:
#                     print(f"Invalid date format: {date_str}")
#                     return None
#             return None
        
#         # Create new job
#         job = Job(
#             job_reference=job_reference,
#             job_name=data.get('job_name'),
#             customer_id=data['customer_id'],
#             type=data['type'],
#             stage=data.get('stage', 'Survey'),
#             priority=data.get('priority', 'Medium'),
#             measure_date=parse_date(data.get('measure_date')),
#             delivery_date=parse_date(data.get('delivery_date')),
#             completion_date=parse_date(data.get('completion_date')),
#             quote_id=data.get('quote_id') if data.get('quote_id') else None,
#             quote_price=data.get('quote_price'),
#             agreed_price=data.get('agreed_price'),
#             deposit_amount=data.get('deposit_amount'),
#             deposit_due_date=parse_date(data.get('deposit_due_date')),
#             installation_address=data['installation_address'],
#             assigned_team_id=data.get('assigned_team') if data.get('assigned_team') else None,
#             primary_fitter_id=data.get('primary_fitter') if data.get('primary_fitter') else None,
#             salesperson_id=data.get('salesperson') if data.get('salesperson') else None,
#             tags=data.get('tags', ''),  # Store as string
#             notes=data.get('notes'),
#             has_counting_sheet=data.get('create_counting_sheet', False),
#             has_schedule=data.get('create_schedule', False),
#             has_invoice=data.get('generate_invoice', False)
#         )
        
#         db.session.add(job)
#         db.session.flush()
        
#         print(f"Created job with ID: {job.id}")
        
#         # Link attached forms if provided
#         attached_forms = data.get('attached_forms', [])
#         for form_id in attached_forms:
#             try:
#                 form_link = JobFormLink(
#                     job_id=job.id,
#                     form_submission_id=form_id,
#                     linked_by=data.get('created_by', 'System')
#                 )
#                 db.session.add(form_link)
#             except Exception as e:
#                 print(f"Error linking form {form_id}: {e}")
        
#         # Create initial note if notes provided
#         if data.get('notes'):
#             try:
#                 initial_note = JobNote(
#                     job_id=job.id,
#                     content=data['notes'],
#                     note_type='general',
#                     author=data.get('created_by', 'System')
#                 )
#                 db.session.add(initial_note)
#             except Exception as e:
#                 print(f"Error creating initial note: {e}")
        
#         db.session.commit()
        
#         return jsonify(serialize_job(job)), 201
        
#     except Exception as e:
#         print(f"Error creating job: {str(e)}")
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>', methods=['PUT'])
# def update_job(job_id):
#     """Update an existing job"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         data = request.get_json()
        
#         # Parse dates helper
#         def parse_date(date_str):
#             if date_str:
#                 try:
#                     return datetime.strptime(date_str, '%Y-%m-%d').date()
#                 except ValueError:
#                     return None
#             return None
        
#         # Update fields
#         updateable_fields = [
#             'job_name', 'type', 'stage', 'priority', 'quote_id', 'quote_price',
#             'agreed_price', 'deposit_amount', 'installation_address',
#             'assigned_team_id', 'primary_fitter_id', 'salesperson_id', 'tags', 'notes'
#         ]
        
#         for field in updateable_fields:
#             if field in data:
#                 setattr(job, field, data[field])
        
#         # Update date fields
#         date_fields = ['measure_date', 'delivery_date', 'completion_date', 'deposit_due_date']
#         for field in date_fields:
#             if field in data:
#                 setattr(job, field, parse_date(data[field]))
        
#         job.updated_at = datetime.utcnow()
        
#         db.session.commit()
        
#         return jsonify(serialize_job(job))
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>', methods=['DELETE'])
# def delete_job(job_id):
#     """Delete a job"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         db.session.delete(job)
#         db.session.commit()
#         return jsonify({'message': 'Job deleted successfully'})
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>/notes', methods=['GET'])
# def get_job_notes(job_id):
#     """Get all notes for a job"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         notes = JobNote.query.filter_by(job_id=job_id).order_by(JobNote.created_at.desc()).all()
        
#         return jsonify([{
#             'id': note.id,
#             'content': note.content,
#             'note_type': note.note_type,
#             'author': note.author,
#             'created_at': note.created_at.isoformat()
#         } for note in notes])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>/notes', methods=['POST'])
# def add_job_note(job_id):
#     """Add a note to a job"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         data = request.get_json()
        
#         if not data.get('content'):
#             return jsonify({'error': 'Note content is required'}), 400
        
#         note = JobNote(
#             job_id=job_id,
#             content=data['content'],
#             note_type=data.get('note_type', 'general'),
#             author=data.get('author', 'System')
#         )
        
#         db.session.add(note)
#         db.session.commit()
        
#         return jsonify({
#             'id': note.id,
#             'content': note.content,
#             'note_type': note.note_type,
#             'author': note.author,
#             'created_at': note.created_at.isoformat()
#         }), 201
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>/documents', methods=['GET'])
# def get_job_documents(job_id):
#     """Get all documents for a job"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         documents = JobDocument.query.filter_by(job_id=job_id).order_by(JobDocument.created_at.desc()).all()
        
#         return jsonify([{
#             'id': doc.id,
#             'filename': doc.filename,
#             'original_filename': doc.original_filename,
#             'file_size': doc.file_size,
#             'mime_type': doc.mime_type,
#             'category': doc.category,
#             'uploaded_by': doc.uploaded_by,
#             'created_at': doc.created_at.isoformat()
#         } for doc in documents])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/<int:job_id>/stage', methods=['PATCH'])
# def update_job_stage(job_id):
#     """Update job stage"""
#     try:
#         job = Job.query.get_or_404(job_id)
#         data = request.get_json()
        
#         if not data.get('stage'):
#             return jsonify({'error': 'Stage is required'}), 400
        
#         old_stage = job.stage
#         job.stage = data['stage']
#         job.updated_at = datetime.utcnow()
        
#         # Add system note about stage change
#         stage_note = JobNote(
#             job_id=job_id,
#             content=f'Stage changed from "{old_stage}" to "{data["stage"]}"',
#             note_type='system',
#             author=data.get('updated_by', 'System')
#         )
#         db.session.add(stage_note)
        
#         db.session.commit()
        
#         return jsonify(serialize_job(job))
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 500

# # Supporting endpoints for form data

# @job_bp.route('/teams', methods=['GET'])
# def get_teams():
#     """Get all active teams"""
#     try:
#         teams = Team.query.filter_by(active=True).order_by(Team.name).all()
#         return jsonify([{
#             'id': team.id,
#             'name': team.name,
#             'specialty': team.specialty
#         } for team in teams])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/fitters', methods=['GET'])
# def get_fitters():
#     """Get all active fitters"""
#     try:
#         fitters = Fitter.query.filter_by(active=True).order_by(Fitter.name).all()
#         return jsonify([{
#             'id': fitter.id,
#             'name': fitter.name,
#             'team_id': fitter.team_id,
#             'team_name': fitter.team.name if fitter.team else None
#         } for fitter in fitters])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/salespeople', methods=['GET'])
# def get_salespeople():
#     """Get all active salespeople"""
#     try:
#         salespeople = Salesperson.query.filter_by(active=True).order_by(Salesperson.name).all()
#         return jsonify([{
#             'id': person.id,
#             'name': person.name,
#             'email': person.email
#         } for person in salespeople])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/forms/unlinked', methods=['GET'])
# def get_unlinked_forms():
#     """Get form submissions not linked to any job"""
#     try:
#         customer_id = request.args.get('customer_id')
        
#         # Subquery to get form IDs that are already linked to jobs
#         linked_form_ids = db.session.query(JobFormLink.form_submission_id).subquery()
        
#         # Query for unlinked forms
#         query = FormSubmission.query.filter(
#             ~FormSubmission.id.in_(linked_form_ids)
#         )
        
#         if customer_id:
#             query = query.filter(FormSubmission.customer_id == customer_id)
        
#         forms = query.order_by(FormSubmission.submitted_at.desc()).all()
        
#         return jsonify([{
#             'id': form.id,
#             'customer_id': form.customer_id,
#             'submitted_at': form.submitted_at.isoformat(),
#             'processed': form.processed,
#             'source': form.source
#         } for form in forms])
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/reference/generate', methods=['GET'])
# def generate_job_reference_endpoint():
#     """Generate a new unique job reference"""
#     try:
#         reference = generate_job_reference()
        
#         # Ensure uniqueness
#         counter = 1
#         while Job.query.filter_by(job_reference=reference).first():
#             reference = f"{generate_job_reference()}-{counter:02d}"
#             counter += 1
        
#         return jsonify({'job_reference': reference})
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @job_bp.route('/jobs/stats', methods=['GET'])
# def get_job_stats():
#     """Get job statistics"""
#     try:
#         stats = {
#             'total_jobs': Job.query.count(),
#             'by_stage': {},
#             'by_type': {},
#             'by_priority': {}
#         }
        
#         # Jobs by stage
#         stage_counts = db.session.query(
#             Job.stage, 
#             db.func.count(Job.id)
#         ).group_by(Job.stage).all()
        
#         for stage, count in stage_counts:
#             stats['by_stage'][stage] = count
        
#         # Jobs by type
#         type_counts = db.session.query(
#             Job.type, 
#             db.func.count(Job.id)
#         ).group_by(Job.type).all()
        
#         for job_type, count in type_counts:
#             stats['by_type'][job_type] = count
        
#         # Jobs by priority
#         priority_counts = db.session.query(
#             Job.priority, 
#             db.func.count(Job.id)
#         ).group_by(Job.priority).all()
        
#         for priority, count in priority_counts:
#             stats['by_priority'][priority] = count
        
#         return jsonify(stats)
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500