# config.py - Configuration constants for a Generic B2B CRM

import os
from datetime import timedelta

# ----------------------------------
# Flask/App Configuration
# ----------------------------------

class Config:
    """Base configuration settings"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a_very_secret_and_complex_key_for_crm_app'
    
    # Database Configuration (Assuming SQLite for development as per logs)
    # The database file must be present in the project root or specified path
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///streemlyne_crm.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # JWT Configuration (for user authentication)
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'your-jwt-auth-secret'
    JWT_TOKEN_LOCATION = ['headers']
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24) # Example: 24 hours

# ----------------------------------
# File Upload Configuration
# ----------------------------------

# Standard document/attachment file types
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xlsx', 'xls', 'txt', 'png', 'jpg', 'jpeg', 'zip'}
UPLOAD_FOLDER = 'uploads' # Directory where files will be stored

# ----------------------------------
# CRM Data/Form Configuration
# ----------------------------------

# Core fields used for dynamic customer/lead forms (B2B focus)
FORM_COLUMNS = [
    'customer_name', 'company_name', 'customer_phone', 'customer_email', 
    'customer_address', 'industry', 'company_size', 'lead_source',
    'estimated_project_value', 'salesperson_assigned', 'preferred_contact_method', 
    'budget_range', 'preferred_completion_date'
]

# Structure for organizing CRM forms (e.g., Lead Qualification Form)
FORM_SECTIONS = [
    {
        'title': 'Primary Contact Information',
        'fields': ['customer_name', 'customer_phone', 'customer_email', 'customer_address']
    },
    {
        'title': 'Business Details', 
        'fields': ['company_name', 'industry', 'company_size', 'lead_source']
    },
    {
        'title': 'Opportunity Overview',
        'fields': ['estimated_project_value', 'budget_range', 'preferred_completion_date']
    },
    {
        'title': 'Internal Assignment',
        'fields': ['salesperson_assigned', 'preferred_contact_method']
    }
]

# Checkbox/Boolean fields for special handling
CHECKBOX_FIELDS = [
    'marketing_opt_in',
    'nda_signed'
]

# ----------------------------------
# AI Configuration (if using)
# ----------------------------------
# Kept generic AI settings as they were standard
OPENAI_MODEL = "gpt-4o" # Updated to a more recent general-purpose model
OPENAI_MAX_TOKENS = 1000

# ----------------------------------
# Helper Functions (Retained)
# ----------------------------------

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_form_field_display_name(field_name):
    """Convert field name to display name"""
    return field_name.replace('_', ' ').title()


# Initialize the configuration class instance
# This is what init_db.py will import if you update the import statement
app_config = Config()