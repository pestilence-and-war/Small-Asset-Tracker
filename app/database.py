import sqlite3

def get_db_connection():
    conn = sqlite3.connect('pantry.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # Drop existing tables for a clean slate during development.
    # Consider a more robust migration strategy for production.
    conn.execute('DROP TABLE IF EXISTS meal_ingredients')
    conn.execute('DROP TABLE IF EXISTS ingredients')
    conn.execute('DROP TABLE IF EXISTS meals')
    conn.execute('DROP TABLE IF EXISTS unit_conversions')
    conn.execute('DROP TABLE IF EXISTS ingredient_conversions')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            quantity REAL NOT NULL DEFAULT 0,
            base_unit TEXT, -- e.g., 'g', 'ml', 'unit'
            base_unit_type TEXT -- e.g., 'mass', 'volume', 'count'
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
    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if DB is already seeded
    cursor.execute("SELECT COUNT(*) FROM meals")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    # Seed Ingredients
    ingredients_to_seed = [
        ('flour', 1000, 'g', 'mass'), ('sugar', 1000, 'g', 'mass'),
        ('eggs', 12, 'unit', 'count'), ('milk', 2000, 'ml', 'volume'),
        ('butter', 500, 'g', 'mass'), ('salt', 500, 'g', 'mass'),
        ('baking powder', 100, 'g', 'mass'), ('vanilla extract', 100, 'ml', 'volume')
    ]
    cursor.executemany(
        "INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)",
        ingredients_to_seed
    )

    # Seed Unit Conversions (example: 1 cup of flour is 120g)
    # Standard conversions
    unit_conversions_to_seed = [
        ('lb', 'g', 453.592), ('kg', 'g', 1000),
        ('oz', 'g', 28.3495), ('gallon', 'ml', 3785.41),
        ('quart', 'ml', 946.353), ('pint', 'ml', 473.176),
        ('cup', 'ml', 236.588), ('tbsp', 'ml', 14.7868),
        ('tsp', 'ml', 4.92892)
    ]
    cursor.executemany(
        "INSERT INTO unit_conversions (from_unit, to_unit, factor) VALUES (?, ?, ?)",
        unit_conversions_to_seed
    )

    # Seed Ingredient-Specific Conversions (mass to volume)
    # We need ingredient IDs for this
    cursor.execute("SELECT id FROM ingredients WHERE name = 'flour'")
    flour_id = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
        (flour_id, 'cup', 'g', 120) # 1 cup of flour = 120g
    )

    # Seed Meals
    cursor.execute("INSERT INTO meals (name) VALUES (?)", ('pancakes',))
    pancakes_id = cursor.lastrowid

    # Seed Meal-Ingredient Mappings
    meal_ingredients_to_seed = [
        (pancakes_id, 'flour', 1.5, 'cup'), (pancakes_id, 'milk', 1.25, 'cup'),
        (pancakes_id, 'eggs', 2, 'unit'), (pancakes_id, 'sugar', 2, 'tbsp'),
        (pancakes_id, 'baking powder', 2, 'tsp'), (pancakes_id, 'salt', 0.5, 'tsp'),
        (pancakes_id, 'butter', 3, 'tbsp')
    ]

    for meal_id, ingredient_name, quantity, unit in meal_ingredients_to_seed:
        cursor.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient_name,))
        ingredient_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity, unit) VALUES (?, ?, ?, ?)",
            (meal_id, ingredient_id, quantity, unit)
        )

    conn.commit()
    conn.close()
