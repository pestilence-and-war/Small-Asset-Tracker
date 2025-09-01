import sqlite3
import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import init_db, seed_db, get_db_connection
from app.units import parse_quantity, get_base_unit_type, get_base_unit

# Mock Flask's request object for testing purposes
class MockForm(dict):
    def getlist(self, key):
        return super().get(key, [])

    def get(self, key, default=None):
        value = super().get(key)
        if isinstance(value, list) and value:
            return value[0]
        return value if value is not None else default

class MockRequest:
    def __init__(self, form_data):
        self.form = MockForm(form_data)

def save_imported_recipe_logic(request):
    """
    This function replicates the logic of the /save_imported_recipe route
    for testing purposes, without the Flask-specific response objects.
    """
    conn = get_db_connection()
    meal_id = None
    try:
        with conn:
            recipe_name = request.form.get('recipe_name')
            instructions = request.form.get('instructions')
            if not recipe_name:
                raise ValueError("Recipe name is required.")

            cursor = conn.cursor()
            cursor.execute("INSERT INTO meals (name, instructions) VALUES (?, ?)", (recipe_name, instructions))
            meal_id = cursor.lastrowid

            ingredient_ids = request.form.getlist('ingredient_id')
            quantities = request.form.getlist('ingredient_quantity')
            units = request.form.getlist('ingredient_unit')

            for i in range(len(ingredient_ids)):
                ing_id_val = ingredient_ids[i]
                quantity_str = quantities[i]
                unit = units[i].strip().lower()

                try:
                    quantity = parse_quantity(quantity_str)
                except ValueError:
                    continue

                final_ingredient_id = None
                if ing_id_val.startswith('_new_'):
                    new_ing_name = ing_id_val[5:].strip().lower()
                    existing = conn.execute("SELECT id FROM ingredients WHERE name = ?", (new_ing_name,)).fetchone()
                    if existing:
                        final_ingredient_id = existing['id']
                    else:
                        density_field_name = f"density_{new_ing_name.replace(' ', '_')}"
                        density_str = request.form.get(density_field_name)

                        base_unit_type = get_base_unit_type(unit) or 'count'
                        base_unit = get_base_unit(base_unit_type)
                        density_to_save = None

                        if density_str:
                            try:
                                density_to_save = float(density_str)
                                base_unit_type = 'mass'
                                base_unit = 'g'
                            except (ValueError, TypeError):
                                density_to_save = None

                        cursor.execute(
                            "INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, density_g_ml) VALUES (?, ?, ?, ?, ?)",
                            (new_ing_name, 0, base_unit, base_unit_type, density_to_save)
                        )
                        final_ingredient_id = cursor.lastrowid
                else:
                    final_ingredient_id = int(ing_id_val)

                if final_ingredient_id:
                    conn.execute(
                        "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity, unit) VALUES (?, ?, ?, ?)",
                        (meal_id, final_ingredient_id, quantity, unit)
                    )
        return meal_id, None
    except Exception as e:
        print(f"Error in save_imported_recipe_logic: {e}")
        return None, str(e)
    finally:
        if conn:
            conn.close()

def main():
    DB_FILE = 'pantry.db'
    print("--- Starting Test ---")

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    init_db()
    seed_db()
    print("Database initialized and seeded.")

    conn = get_db_connection()
    conn.execute("INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)", ('salt', 100, 'g', 'mass'))
    conn.execute("INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)", ('egg', 12, 'unit', 'count'))
    conn.commit()
    salt_id = conn.execute("SELECT id FROM ingredients WHERE name = 'salt'").fetchone()['id']
    egg_id = conn.execute("SELECT id FROM ingredients WHERE name = 'egg'").fetchone()['id']
    conn.close()
    print(f"Pre-seeded ingredients: salt (id={salt_id}), egg (id={egg_id})")

    # Mock form data, including density for new ingredients that need it
    mock_form_data = {
        'recipe_name': 'Chocolate Chip Cookies',
        'instructions': 'Mix and bake.',
        'ingredient_id': [
            '_new_all-purpose flour',
            '_new_baking soda', # This is a powder, let's give it a density
            str(salt_id),
            '_new_unsalted butter',
            str(egg_id),
        ],
        'ingredient_quantity': ['1', '0.5', '0.5', '0.5', '1'],
        'ingredient_unit': ['cup', 'tsp', 'tsp', 'cup', 'unit'],
        'density_all-purpose_flour': '0.53', # g/ml
        'density_baking_soda': '0.96', # g/ml
        'density_unsalted_butter': '0.911' # g/ml
    }
    mock_request = MockRequest(mock_form_data)
    print("Mock request data created with densities.")

    print("Running save logic...")
    new_meal_id, error = save_imported_recipe_logic(mock_request)

    if error:
        print(f"TEST FAILED: Logic returned an error: {error}")
        return

    print(f"Save logic executed. New meal ID: {new_meal_id}")

    print("Verifying database state...")
    conn = get_db_connection()

    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (new_meal_id,)).fetchone()
    assert meal is not None, "FAIL: Meal was not created."
    assert meal['name'] == 'Chocolate Chip Cookies', f"FAIL: Meal name is incorrect."
    print("✅ Meal created successfully.")

    meal_ingredients = conn.execute("SELECT * FROM meal_ingredients WHERE meal_id = ?", (new_meal_id,)).fetchall()
    assert len(meal_ingredients) == 5, f"FAIL: Expected 5 meal ingredients, but found {len(meal_ingredients)}."
    print(f"✅ Correct number of meal ingredients created ({len(meal_ingredients)}).")

    # Verification for new ingredient with density
    flour_ing = conn.execute("SELECT * FROM ingredients WHERE name = 'all-purpose flour'").fetchone()
    assert flour_ing is not None, "FAIL: 'all-purpose flour' was not created."
    assert flour_ing['base_unit_type'] == 'mass', "FAIL: Flour base_unit_type should be 'mass'."
    assert flour_ing['base_unit'] == 'g', "FAIL: Flour base_unit should be 'g'."
    assert flour_ing['density_g_ml'] == 0.53, f"FAIL: Flour density is incorrect. Got {flour_ing['density_g_ml']}"
    print("✅ New ingredient 'all-purpose flour' created correctly with density.")

    # Verification for another new ingredient with density
    butter_ing = conn.execute("SELECT * FROM ingredients WHERE name = 'unsalted butter'").fetchone()
    assert butter_ing is not None, "FAIL: 'unsalted butter' was not created."
    assert butter_ing['density_g_ml'] == 0.911, f"FAIL: Butter density is incorrect. Got {butter_ing['density_g_ml']}"
    print("✅ New ingredient 'unsalted butter' created correctly with density.")

    # Verification for existing ingredient
    salt_meal_ing = conn.execute("SELECT * FROM meal_ingredients WHERE meal_id = ? AND ingredient_id = ?", (new_meal_id, salt_id)).fetchone()
    assert salt_meal_ing is not None, "FAIL: Salt not linked to meal."
    print("✅ Existing ingredient 'salt' correctly linked to meal.")

    conn.close()
    print("\n--- TEST SUCCEEDED ---")

if __name__ == '__main__':
    main()
