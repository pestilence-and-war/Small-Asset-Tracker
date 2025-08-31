import sqlite3

def get_db_connection():
    conn = sqlite3.connect('pantry.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # The 'IF NOT EXISTS' clause in the CREATE TABLE statements ensures that
    # we don't try to recreate tables that are already present, making this
    # function safe to run multiple times without destroying data.

    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL DEFAULT 'other',
            quantity REAL NOT NULL DEFAULT 0,
            base_unit TEXT, -- e.g., 'g', 'ml', 'unit'
            base_unit_type TEXT, -- e.g., 'mass', 'volume', 'count'
            density_g_ml REAL -- Grams per milliliter, for mass-volume conversion
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS meal_ingredients (
            id INTEGER PRIMARY KEY,
            meal_id INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL, -- The unit used in the recipe, e.g., 'cup'
            FOREIGN KEY (meal_id) REFERENCES meals (id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS unit_conversions (
            id INTEGER PRIMARY KEY,
            from_unit TEXT NOT NULL,
            to_unit TEXT NOT NULL,
            factor REAL NOT NULL,
            UNIQUE(from_unit, to_unit)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredient_conversions (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL,
            from_unit TEXT NOT NULL,
            to_unit TEXT NOT NULL,
            factor REAL NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients (id),
            UNIQUE(ingredient_id, from_unit, to_unit)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredient_view_units (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL,
            view_name TEXT NOT NULL, -- e.g., 'pantry', 'recipe_manager'
            unit TEXT NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients (id),
            UNIQUE(ingredient_id, view_name)
        )
    ''')
    # Add category column to ingredients if it doesn't exist
    try:
        conn.execute('SELECT category FROM ingredients LIMIT 1').fetchall()
    except sqlite3.OperationalError:
        print("Adding 'category' column to 'ingredients' table.")
        conn.execute('ALTER TABLE ingredients ADD COLUMN category TEXT NOT NULL DEFAULT "other"')

    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if the unit_conversions table is already seeded
    cursor.execute("SELECT COUNT(*) FROM unit_conversions")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    # Seed Unit Conversions - this is essential for the app's functionality.
    unit_conversions_to_seed = [
        ('lb', 'g', 453.592), ('kg', 'g', 1000),
        ('oz', 'g', 28.3495),
        ('gallon', 'ml', 3785.41),
        ('quart', 'ml', 946.353),
        ('pint', 'ml', 473.176),
        ('cup', 'ml', 236.588),
        ('tbsp', 'ml', 14.7868), ('tablespoon', 'ml', 14.7868),
        ('tsp', 'ml', 4.92892), ('teaspoon', 'ml', 4.92892),
        ('l', 'ml', 1000),
        ('cc', 'ml', 1)
    ]
    cursor.executemany(
        "INSERT INTO unit_conversions (from_unit, to_unit, factor) VALUES (?, ?, ?)",
        unit_conversions_to_seed
    )

    conn.commit()
    conn.close()
