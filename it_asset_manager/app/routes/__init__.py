# app/routes/__init__.py
from flask import Blueprint

# Create blueprints
assets_bp = Blueprint('assets', __name__, url_prefix='/assets')
employees_bp = Blueprint('employees', __name__, url_prefix='/employees')
assignments_bp = Blueprint('assignments', __name__, url_prefix='/assignments')

# Import views after blueprints are created
from . import assets, employees, assignments