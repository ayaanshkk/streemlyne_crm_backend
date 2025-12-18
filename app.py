# app.py - Main application file for Flask app with database, CORS, blueprints, and SSE
from flask import Flask, Response
from flask_cors import CORS
from flask_migrate import Migrate
import os
from dotenv import load_dotenv
from database import db, init_db
import json
import time
from queue import Queue
from threading import Lock

# Load environment variables from .env file
load_dotenv()

# Global SSE event queue
sse_clients = []
sse_lock = Lock()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
    
    # Configure CORS
    CORS(app, origins="*")
    
    # Database configuration - Uses DATABASE_URL from .env
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Upload folder configuration
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    
    # Create directories if they don't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('generated_pdfs', exist_ok=True)
    os.makedirs('generated_excel', exist_ok=True)
    
    # Initialize database
    init_db(app)
    
    # Initialize Flask-Migrate
    migrate = Migrate(app, db)
    
    # Import and register blueprints
    from routes.job_routes import job_bp
    from routes.core_routes import core_bp
    from routes.db_routes import db_bp
    from routes.auth_routes import auth_bp
    from routes.form_routes import form_bp
    
    app.register_blueprint(job_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(db_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(form_bp)
    
    # SSE endpoint for real-time updates
    @app.route('/events')
    def sse():
        def event_stream():
            q = Queue()
            with sse_lock:
                sse_clients.append(q)
            
            try:
                while True:
                    msg = q.get()
                    yield f"data: {json.dumps(msg)}\n\n"
            except GeneratorExit:
                with sse_lock:
                    sse_clients.remove(q)
        
        return Response(event_stream(), mimetype='text/event-stream')
    
    return app

# Helper function to broadcast SSE events
def broadcast_sse_event(event_type, data):
    with sse_lock:
        for client_queue in sse_clients:
            try:
                client_queue.put({"type": event_type, "data": data})
            except:
                pass

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        pass
    app.run(debug=True)