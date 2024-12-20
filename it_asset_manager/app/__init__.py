from flask import Flask, render_template  # Added render_template import
from flask_sqlalchemy import SQLAlchemy
from config import Config

# Initialize SQLAlchemy instance
db = SQLAlchemy()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    
    with app.app_context():
        @app.route('/')
        def index():
            return render_template('index.html')

        # Import blueprints inside context
        from app.routes import assets_bp, employees_bp, assignments_bp
        
        # Register blueprints
        app.register_blueprint(assets_bp)
        app.register_blueprint(employees_bp)
        app.register_blueprint(assignments_bp)
        
        # Create all database tables
        db.create_all()
    
    return app