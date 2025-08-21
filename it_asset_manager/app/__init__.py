from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_mail import Mail
from config import Config

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
mail = Mail()
login_manager.login_view = 'users.login'
login_manager.login_message_category = 'info'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    with app.app_context():
        @app.route('/')
        def index():
            return render_template('index.html')

        # Import blueprints inside context
        from app.routes import assets_bp, employees_bp, assignments_bp
        from app.routes.users import users_bp
        from app.routes.settings import settings_bp
        from app.routes.dashboard import dashboard_bp

        # Register blueprints
        app.register_blueprint(assets_bp)
        app.register_blueprint(employees_bp)
        app.register_blueprint(assignments_bp)
        app.register_blueprint(users_bp)
        app.register_blueprint(settings_bp, url_prefix='/settings')
        app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

        # Create all database tables
        db.create_all()

    return app
