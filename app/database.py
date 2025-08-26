import sqlite3

def get_db_connection():
    conn = sqlite3.connect('pantry.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            quantity REAL NOT NULL DEFAULT 0,
            unit TEXT
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
            FOREIGN KEY (meal_id) REFERENCES meals (id),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients (id)
        )
    ''')
    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if meals table is empty before seeding
    cursor.execute("SELECT COUNT(*) FROM meals")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    # Seed Ingredients
    ingredients_to_seed = [
        ('flour', 1000, 'g'), ('sugar', 1000, 'g'), ('eggs', 12, 'unit'),
        ('milk', 2000, 'ml'), ('butter', 500, 'g'), ('salt', 500, 'g'),
        ('baking powder', 100, 'g'), ('vanilla extract', 100, 'ml')
    ]
    cursor.executemany("INSERT INTO ingredients (name, quantity, unit) VALUES (?, ?, ?)", ingredients_to_seed)

    # Seed Meals
    cursor.execute("INSERT INTO meals (name) VALUES (?)", ('pancakes',))
    pancakes_id = cursor.lastrowid

    # Seed Meal-Ingredient Mappings
    meal_ingredients_to_seed = [
        (pancakes_id, 'flour', 200), (pancakes_id, 'milk', 300),
        (pancakes_id, 'eggs', 2), (pancakes_id, 'sugar', 25),
        (pancakes_id, 'baking powder', 10), (pancakes_id, 'salt', 5),
        (pancakes_id, 'butter', 50)
    ]

    for meal_id, ingredient_name, quantity in meal_ingredients_to_seed:
        cursor.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient_name,))
        ingredient_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity) VALUES (?, ?, ?)",
            (meal_id, ingredient_id, quantity)
        )

    conn.commit()
    conn.close()
