"""The main entry point for the application.

This script initializes and seeds the database, then starts the Waitress
production server to serve the Flask application.
"""
from waitress import serve
from app import app
from app.database import init_db, seed_db

# Initialize and seed the database
init_db()
seed_db()

serve(app, host="0.0.0.0", port=5000)
