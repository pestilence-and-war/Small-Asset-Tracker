"""A script to initialize and seed the database.

This script should be run once to set up the database schema and populate it
with essential data like unit conversions.
"""
from app.database import init_db, seed_db

print("Initializing and seeding the database...")
init_db()
seed_db()
print("Database initialized and seeded.")
