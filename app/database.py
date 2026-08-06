import sqlite3


def get_db_connection():
    """Establishes a connection to the SQLite database.

    The connection is configured to use the `sqlite3.Row` row factory, which
    allows accessing columns by name. Foreign keys are enabled.

    Returns:
        sqlite3.Connection: A connection object to the database.
    """
    conn = sqlite3.connect('pantry.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column_exists(conn, table_name, column_name, column_definition):
    """Helper to cleanly check and add missing columns using PRAGMA table_info."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def init_db():
    """Initializes the database by creating tables and indexes if they do not already exist.

    Safe to run multiple times. Handles clean migrations via PRAGMA table_info.
    """
    conn = get_db_connection()

    with conn:
        # 1. Ingredients Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL DEFAULT 'Other',
                quantity REAL NOT NULL DEFAULT 0,
                base_unit TEXT, -- e.g., 'g', 'ml', 'unit'
                base_unit_type TEXT, -- e.g., 'mass', 'volume', 'count'
                density_g_ml REAL, -- Grams per milliliter, for mass-volume conversion
                parent_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
                image_url TEXT
            )
        ''')

        # 2. Meals Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                instructions TEXT,
                category TEXT DEFAULT 'Main',
                prep_time INTEGER,
                cook_time INTEGER,
                image_url TEXT
            )
        ''')

        # 3. Meal Ingredients Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS meal_ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_id INTEGER NOT NULL,
                ingredient_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL, -- e.g., 'cup', 'g', 'tbsp'
                FOREIGN KEY (meal_id) REFERENCES meals (id) ON DELETE CASCADE,
                FOREIGN KEY (ingredient_id) REFERENCES ingredients (id) ON DELETE CASCADE
            )
        ''')

        # 4. Standard Unit Conversions Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS unit_conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_unit TEXT NOT NULL,
                to_unit TEXT NOT NULL,
                factor REAL NOT NULL,
                UNIQUE(from_unit, to_unit)
            )
        ''')

        # 5. Ingredient-Specific Conversions Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ingredient_conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredient_id INTEGER NOT NULL,
                from_unit TEXT NOT NULL,
                to_unit TEXT NOT NULL,
                factor REAL NOT NULL,
                FOREIGN KEY (ingredient_id) REFERENCES ingredients (id) ON DELETE CASCADE,
                UNIQUE(ingredient_id, from_unit, to_unit)
            )
        ''')

        # 6. Ingredient View Preference Units Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ingredient_view_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredient_id INTEGER NOT NULL,
                view_name TEXT NOT NULL, -- e.g., 'pantry', 'recipe_manager'
                unit TEXT NOT NULL,
                FOREIGN KEY (ingredient_id) REFERENCES ingredients (id) ON DELETE CASCADE,
                UNIQUE(ingredient_id, view_name)
            )
        ''')

        # 7. Meal Plans Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS meal_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')

        # 8. Meal Plan Items Table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS meal_plan_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_plan_id INTEGER NOT NULL,
                meal_id INTEGER NOT NULL,
                multiplier REAL NOT NULL DEFAULT 1.0,
                FOREIGN KEY (meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE,
                FOREIGN KEY (meal_id) REFERENCES meals (id) ON DELETE CASCADE
            )
        ''')

        # 9. UPC Barcode Data Table (Enhanced)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS upc_data (
                upc TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                brand TEXT,
                quantity REAL,
                unit TEXT,
                ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
                image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Migration helper for existing tables
        _ensure_column_exists(conn, 'ingredients', 'category', "TEXT NOT NULL DEFAULT 'Other'")
        _ensure_column_exists(conn, 'ingredients', 'parent_id', "INTEGER REFERENCES ingredients(id) ON DELETE SET NULL")
        _ensure_column_exists(conn, 'ingredients', 'image_url', "TEXT")
        _ensure_column_exists(conn, 'meals', 'instructions', "TEXT")
        _ensure_column_exists(conn, 'meals', 'category', "TEXT DEFAULT 'Main'")
        _ensure_column_exists(conn, 'meals', 'prep_time', "INTEGER")
        _ensure_column_exists(conn, 'meals', 'cook_time', "INTEGER")
        _ensure_column_exists(conn, 'meals', 'image_url', "TEXT")
        _ensure_column_exists(conn, 'upc_data', 'brand', "TEXT")
        _ensure_column_exists(conn, 'upc_data', 'ingredient_id', "INTEGER REFERENCES ingredients(id) ON DELETE SET NULL")
        _ensure_column_exists(conn, 'upc_data', 'image_url', "TEXT")

        # Create indexes for search and relationship performance
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ingredients_name ON ingredients(name)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ingredients_category ON ingredients(category)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_meal_ingredients_meal ON meal_ingredients(meal_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_meal_ingredients_ingredient ON meal_ingredients(ingredient_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_upc_data_upc ON upc_data(upc)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_upc_ingredient_id ON upc_data(ingredient_id)')

    conn.close()
    seed_db()


def seed_db():
    """Seeds the database with standard unit conversion factors if not already present."""
    conn = get_db_connection()
    with conn:
        # Standard unit conversions
        unit_conversions_to_seed = [
            # Mass conversions to 'g'
            ('lb', 'g', 453.592), ('lbs', 'g', 453.592), ('pound', 'g', 453.592), ('pounds', 'g', 453.592),
            ('kg', 'g', 1000.0), ('kgs', 'g', 1000.0), ('kilogram', 'g', 1000.0), ('kilograms', 'g', 1000.0),
            ('oz', 'g', 28.3495), ('ozs', 'g', 28.3495), ('ounce', 'g', 28.3495), ('ounces', 'g', 28.3495),
            ('mg', 'g', 0.001),
            # Volume conversions to 'ml'
            ('gallon', 'ml', 3785.41), ('gallons', 'ml', 3785.41), ('gal', 'ml', 3785.41), ('gals', 'ml', 3785.41),
            ('quart', 'ml', 946.353), ('quarts', 'ml', 946.353), ('qt', 'ml', 946.353), ('qts', 'ml', 946.353),
            ('pint', 'ml', 473.176), ('pints', 'ml', 473.176), ('pt', 'ml', 473.176), ('pts', 'ml', 473.176),
            ('cup', 'ml', 236.588), ('cups', 'ml', 236.588), ('c', 'ml', 236.588),
            ('fl oz', 'ml', 29.5735), ('fl. oz', 'ml', 29.5735), ('floz', 'ml', 29.5735),
            ('tbsp', 'ml', 14.7868), ('tablespoon', 'ml', 14.7868), ('tablespoons', 'ml', 14.7868), ('tbs', 'ml', 14.7868),
            ('tsp', 'ml', 4.92892), ('teaspoon', 'ml', 4.92892), ('teaspoons', 'ml', 4.92892),
            ('l', 'ml', 1000.0), ('liter', 'ml', 1000.0), ('liters', 'ml', 1000.0),
            ('cc', 'ml', 1.0),
        ]

        for from_u, to_u, factor in unit_conversions_to_seed:
            conn.execute(
                "INSERT OR IGNORE INTO unit_conversions (from_unit, to_unit, factor) VALUES (?, ?, ?)",
                (from_u, to_u, factor)
            )

    conn.close()

