from waitress import serve
from app import app
from app.database import init_db, seed_db

# Initialize and seed the database
init_db()
seed_db()

serve(app, host="0.0.0.0", port=5000)
