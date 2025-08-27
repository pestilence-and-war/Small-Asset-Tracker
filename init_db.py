from app.database import init_db, seed_db

print("Initializing and seeding the database...")
init_db()
seed_db()
print("Database initialized and seeded.")
