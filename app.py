# app.py - Updated with Flask-Migrate for database migrations

from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
import os
from database import db, init_db





def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
    
    # Configure CORS
    CORS(app, origins="*")
    
    # Database configuration
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "database.db")}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
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
    
    # Import and register blueprints (after app is created)
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
    
    return app

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
    app.run(debug=True)