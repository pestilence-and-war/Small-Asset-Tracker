from flask import render_template, request, make_response
from app import app
from app.database import get_db_connection
from app.units import convert_to_base, needs_conversion_prompt, get_conversion_prompt_html, get_base_unit_type, get_base_unit, get_new_ingredient_conversion_prompt_html

def get_all_ingredients():
    conn = get_db_connection()
    ingredients = conn.execute('SELECT * FROM ingredients ORDER BY name').fetchall()
    conn.close()
    return ingredients

def get_all_meals():
    conn = get_db_connection()
    meals = conn.execute('SELECT * FROM meals ORDER BY name').fetchall()
    conn.close()
    return meals

@app.route('/')
def index():
    ingredients = get_all_ingredients()
    meals = get_all_meals()
    return render_template('index.html', ingredients=ingredients, meals=meals)

@app.route('/pantry')
def pantry():
    ingredients = get_all_ingredients()
    return render_template('pantry.html', ingredients=ingredients)

@app.route('/add_ingredient', methods=['POST'])
def add_ingredient():
    ingredient_name = request.form['ingredient_name'].strip().lower()
    try:
        quantity = float(request.form.get('quantity', 0))
    except (ValueError, TypeError):
        quantity = 0
    unit = request.form.get('unit', '').strip().lower()

    if not ingredient_name or not unit:
        ingredients = get_all_ingredients()
        return render_template('_ingredients_list.html', ingredients=ingredients)

    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE name = ?", (ingredient_name,)).fetchone()

    # This will be our final response, can be overridden by a prompt
    response_html = ""

    if ingredient:
        # Ingredient exists
        try:
            if needs_conversion_prompt(unit, ingredient['id']):
                conn.close()
                # Return a prompt instead of the ingredient list
                return make_response(get_conversion_prompt_html(ingredient['id'], quantity, unit, 0))

            converted_quantity, _, _ = convert_to_base(quantity, unit, ingredient['id'])
            conn.execute("UPDATE ingredients SET quantity = quantity + ? WHERE id = ?", (converted_quantity, ingredient['id']))
            conn.commit()
        except ValueError as e:
            print(f"Conversion error for existing ingredient: {e}")
            # Optionally, return an error message to the user here
        finally:
            if conn: conn.close()
    else:
        # New ingredient
        try:
            base_unit_type = get_base_unit_type(unit)
            if not base_unit_type:
                raise ValueError(f"Cannot determine type for unit '{unit}'. Please use a standard unit (e.g., g, ml, oz, cup).")

            # If the user adds a new ingredient that has a mass or volume, we need its density
            # to allow for future conversions. We will standardize on 'g' as the base unit.
            if base_unit_type in ['mass', 'volume']:
                conn.close()
                # We pass the original unit to the prompt function to make it more informative.
                response = make_response(get_new_ingredient_conversion_prompt_html(ingredient_name, quantity, unit))
                response.headers['HX-Retarget'] = '#user-prompts'
                response.headers['HX-Reswap'] = 'innerHTML'
                return response

            # This logic will now only apply to 'count' type ingredients, as mass/volume types
            # are handled by the density prompt and its corresponding route.
            base_unit = get_base_unit(base_unit_type)
            converted_quantity, _, _ = convert_to_base(quantity, unit) # This will just be the quantity itself for 'count'

            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)',
                (ingredient_name, converted_quantity, base_unit, base_unit_type)
            )
            conn.commit()
        except ValueError as e:
            print(f"Error adding new ingredient: {e}")
            # Optionally, return an error message to the user
        finally:
            if conn: conn.close()

    ingredients = get_all_ingredients()
    response_html = render_template('_ingredients_list.html', ingredients=ingredients)
    # This ensures the prompt area is cleared on successful add
    return make_response(response_html)

@app.route('/search')
def search():
    query = request.args.get('q', '').strip().lower()
    conn = get_db_connection()
    if query:
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE name LIKE ? ORDER BY name LIMIT 5",
            (query + '%',)
        ).fetchall()
    else:
        ingredients = []
    conn.close()
    return render_template('_search_results.html', ingredients=ingredients)

@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    ingredient_id = request.form['id']
    change = float(request.form['change'])

    conn = get_db_connection()
    conn.execute(
        "UPDATE ingredients SET quantity = quantity + ? WHERE id = ?",
        (change, ingredient_id)
    )
    conn.commit()

    # Fetch the updated ingredient to send back
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    conn.close()

    return render_template('_ingredient_item.html', ingredient=ingredient)

@app.route('/add_conversion', methods=['POST'])
def add_conversion():
    ingredient_id = request.form['ingredient_id']
    from_unit = request.form['from_unit']
    to_unit = request.form['to_unit']
    factor = float(request.form['factor'])

    # The original quantity and unit the user was trying to add
    original_quantity = float(request.form['quantity_to_add'])
    original_unit = request.form['unit_to_add']

    conn = get_db_connection()
    try:
        # Save the new conversion factor
        conn.execute(
            "INSERT INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
            (ingredient_id, from_unit, to_unit, factor)
        )
        conn.commit()

        # Now that the conversion is saved, try to add the original quantity again
        # We need a new connection for convert_to_base to see the new conversion
        conn.close()
        conn = get_db_connection()

        converted_quantity, _, _ = convert_to_base(original_quantity, original_unit, ingredient_id)
        conn.execute(
            "UPDATE ingredients SET quantity = quantity + ? WHERE id = ?",
            (converted_quantity, ingredient_id)
        )
        conn.commit()

    except Exception as e:
        print(f"Error in add_conversion: {e}")
        # Handle error, maybe return a message
    finally:
        if conn: conn.close()

    # Return the updated ingredient list
    ingredients = get_all_ingredients()
    response_html = render_template('_ingredients_list.html', ingredients=ingredients)
    # This response will replace the #ingredient-list-container, thus clearing the prompt
    return make_response(response_html)

@app.route('/add_new_ingredient_with_density', methods=['POST'])
def add_new_ingredient_with_density():
    ingredient_name = request.form['ingredient_name'].strip().lower()
    original_quantity = float(request.form['original_quantity'])
    original_unit = request.form['original_unit']
    density_g_ml = float(request.form['density_g_ml'])

    conn = get_db_connection()
    try:
        # 1. Create the new ingredient.
        # When adding with a volume unit, we standardize the base unit to 'g'.
        base_unit = 'g'
        base_unit_type = 'mass'

        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, density_g_ml) VALUES (?, ?, ?, ?, ?)',
            (ingredient_name, 0, base_unit, base_unit_type, density_g_ml)
        )
        ingredient_id = cursor.lastrowid
        conn.commit() # Commit the insert to make the ingredient available for conversion

        # 2. Convert the original quantity to the base quantity using the new density.
        # We need a new connection/cursor for convert_to_base to see the new ingredient.
        conn.close()
        conn = get_db_connection()

        converted_quantity, _, _ = convert_to_base(original_quantity, original_unit, ingredient_id)

        # 3. Update the ingredient with the correct converted quantity.
        conn.execute(
            "UPDATE ingredients SET quantity = ? WHERE id = ?",
            (converted_quantity, ingredient_id)
        )
        conn.commit()

    except Exception as e:
        print(f"Error in add_new_ingredient_with_density: {e}")
        # Optionally handle error, e.g., by returning an error message to the user
    finally:
        if conn: conn.close()

    # Return the updated ingredient list, which also clears the prompt
    ingredients = get_all_ingredients()
    response_html = render_template('_ingredients_list.html', ingredients=ingredients)
    return make_response(response_html)

@app.route('/start_cooking_session', methods=['POST'])
def start_cooking_session():
    meal_id = request.form.get('meal_id')
    try:
        portion = float(request.form.get('portion', 1.0))
    except (ValueError, TypeError):
        portion = 1.0

    if not meal_id:
        # Redirect or show error
        return "Error: No meal selected"

    conn = get_db_connection()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()

    # Get ingredients for the meal from meal_ingredients table
    meal_ingredients_raw = conn.execute("""
        SELECT i.id, i.name, i.quantity as pantry_quantity, i.base_unit, mi.quantity as recipe_quantity, mi.unit as recipe_unit
        FROM ingredients i
        JOIN meal_ingredients mi ON i.id = mi.ingredient_id
        WHERE mi.meal_id = ?
    """, (meal_id,)).fetchall()

    recipe_items = []
    missing_conversions = []
    for item in meal_ingredients_raw:
        try:
            required_quantity_base, _, _ = convert_to_base(item['recipe_quantity'] * portion, item['recipe_unit'], item['id'])

            recipe_items.append({
                "ingredient": {
                    "id": item['id'],
                    "name": item['name'],
                    "base_unit": item['base_unit']
                },
                "required_quantity": required_quantity_base,
                "pantry_quantity": item['pantry_quantity'],
                "in_stock": item['pantry_quantity'] >= required_quantity_base
            })
        except ValueError as e:
            print(f"Could not convert {item['name']} for cooking session: {e}")
            # Handle error - maybe skip this ingredient or show an error in the UI
            missing_conversions.append({
                "name": item['name'],
                "unit": item['recipe_unit'],
                "base_unit": item['base_unit']
            })

    conn.close()

    return render_template('cooking_mode.html', meal=meal, portion=portion, recipe_items=recipe_items, missing_conversions=missing_conversions)

@app.route('/ingredient/<int:ing_id>')
def get_ingredient(ing_id):
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
    conn.close()
    return render_template('_ingredient_item.html', ingredient=ingredient)

@app.route('/edit_ingredient_form/<int:ing_id>')
def edit_ingredient_form(ing_id):
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
    conn.close()
    return render_template('_edit_ingredient_form.html', ingredient=ingredient)

@app.route('/edit_ingredient/<int:ing_id>', methods=['POST'])
def edit_ingredient(ing_id):
    conn = get_db_connection()
    new_name = request.form.get('name', '').strip().lower()
    new_quantity = request.form.get('quantity', 0)

    if not new_name:
        # Handle error: name cannot be empty
        # For simplicity, we'll just fetch the original ingredient and return it
        ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
        conn.close()
        return render_template('_ingredient_item.html', ingredient=ingredient)

    try:
        new_quantity = float(new_quantity)
        conn.execute("UPDATE ingredients SET name = ?, quantity = ? WHERE id = ?", (new_name, new_quantity, ing_id))
        conn.commit()
    except ValueError:
        # Handle error: quantity is not a valid float
        pass # For simplicity, we do nothing
    except Exception as e:
        print(f"Error updating ingredient: {e}")
        # Handle other potential DB errors

    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
    conn.close()
    return render_template('_ingredient_item.html', ingredient=ingredient)

@app.route('/delete_ingredient/<int:ing_id>', methods=['DELETE'])
def delete_ingredient(ing_id):
    conn = get_db_connection()
    try:
        # First, delete references in meal_ingredients
        conn.execute("DELETE FROM meal_ingredients WHERE ingredient_id = ?", (ing_id,))
        # Then, delete the ingredient itself
        conn.execute("DELETE FROM ingredients WHERE id = ?", (ing_id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting ingredient: {e}")
        # Optionally, handle the error in the UI
    finally:
        conn.close()

    return "" # Return an empty string as the element will be removed from the DOM

def get_meal_ingredients(meal_id):
    conn = get_db_connection()
    meal_ingredients = conn.execute("""
        SELECT i.name, mi.quantity, mi.unit, mi.id as meal_ingredient_id
        FROM meal_ingredients mi
        JOIN ingredients i ON mi.ingredient_id = i.id
        WHERE mi.meal_id = ?
        ORDER BY i.name
    """, (meal_id,)).fetchall()
    conn.close()
    return meal_ingredients

@app.route('/recipe/<int:meal_id>')
def recipe_editor(meal_id):
    conn = get_db_connection()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    conn.close()
    meal_ingredients = get_meal_ingredients(meal_id)
    return render_template('recipe_editor.html', meal=meal, meal_ingredients=meal_ingredients)

@app.route('/add_ingredient_to_meal/<int:meal_id>', methods=['POST'])
def add_ingredient_to_meal(meal_id):
    ingredient_name = request.form['q'].strip().lower()
    quantity = request.form['quantity']
    unit = request.form['unit'].strip().lower()

    if not all([ingredient_name, quantity, unit]):
        # Handle error: all fields required
        return "All fields are required."

    conn = get_db_connection()
    try:
        # Find ingredient by name
        ingredient = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient_name,)).fetchone()
        if not ingredient:
            # Optionally, create the ingredient if it doesn't exist
            return f"Ingredient '{ingredient_name}' not found in pantry."

        ingredient_id = ingredient['id']
        try:
            ingredient_quantity = float(quantity)
        except ValueError:
            return "Invalid quantity."

        conn.execute(
            "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity, unit) VALUES (?, ?, ?, ?)",
            (meal_id, ingredient_id, ingredient_quantity, unit)
        )
        conn.commit()
    except Exception as e:
        print(f"Error adding ingredient to meal: {e}")
    finally:
        conn.close()

    conn = get_db_connection()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    conn.close()
    meal_ingredients = get_meal_ingredients(meal_id)
    return render_template('_meal_ingredients_list.html', meal=meal, meal_ingredients=meal_ingredients)

@app.route('/remove_ingredient_from_meal/<int:meal_id>/<int:meal_ingredient_id>', methods=['DELETE'])
def remove_ingredient_from_meal(meal_id, meal_ingredient_id):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM meal_ingredients WHERE id = ?", (meal_ingredient_id,))
        conn.commit()
    except Exception as e:
        print(f"Error removing ingredient from meal: {e}")
    finally:
        conn.close()
    return ""

@app.route('/search_ingredients_for_recipe/<int:meal_id>', methods=['POST'])
def search_ingredients_for_recipe(meal_id):
    query = request.form.get('q', '').strip().lower()
    conn = get_db_connection()
    if query:
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE name LIKE ? ORDER BY name LIMIT 5",
            (query + '%',)
        ).fetchall()
    else:
        ingredients = []
    conn.close()
    return render_template('_search_results_for_recipe.html', ingredients=ingredients, meal_id=meal_id)

@app.route('/select_ingredient', methods=['POST'])
def select_ingredient():
    ingredient_name = request.form['ingredient_name']
    meal_id = request.form['meal_id']
    return f'<input id="ingredient-search-input" type="search" name="q" value="{ingredient_name}" placeholder="Search for an ingredient to add..." hx-post="/search_ingredients_for_recipe/{meal_id}" hx-trigger="keyup changed delay:500ms, search" hx-target="#search-results-for-recipe" hx-swap="innerHTML">'

@app.route('/meal/<int:meal_id>')
def meal_page(meal_id):
    conn = get_db_connection()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    conn.close()
    meal_ingredients = get_meal_ingredients(meal_id)
    return render_template('meal.html', meal=meal, meal_ingredients=meal_ingredients)

@app.route('/search_ingredients_for_cooking', methods=['POST'])
def search_ingredients_for_cooking():
    query = request.form.get('q', '').strip().lower()
    conn = get_db_connection()
    if query:
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE name LIKE ? ORDER BY name LIMIT 5",
            (query + '%',)
        ).fetchall()
    else:
        ingredients = []
    conn.close()
    return render_template('_search_results_for_cooking.html', ingredients=ingredients)

@app.route('/add_ingredient_to_cooking_session', methods=['POST'])
def add_ingredient_to_cooking_session():
    ingredient_id = request.form['ingredient_id']
    quantity = request.form['quantity']
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    conn.close()
    return render_template('_cooking_session_ingredient.html', ingredient=ingredient, quantity=quantity)

@app.route('/update_pantry', methods=['POST'])
def update_pantry():
    # A list of strings like "ingredient_id_quantity_to_deduct"
    ingredients_used = request.form.getlist('ingredient_used')

    if not ingredients_used:
        return "Nothing to update."

    conn = get_db_connection()
    try:
        with conn: # Use a transaction
            for item in ingredients_used:
                ingredient_id, quantity_to_deduct = item.split('_')
                conn.execute(
                    "UPDATE ingredients SET quantity = quantity - ? WHERE id = ?",
                    (float(quantity_to_deduct), int(ingredient_id))
                )
        return "<h4>Pantry updated successfully!</h4><p><a href='/'>Back to main page.</a></p>"
    except Exception as e:
        print(f"Error updating pantry: {e}")
        return f"<h4>Error: {e}</h4><p>Could not update pantry.</p>"
    finally:
        if conn: conn.close()

@app.route('/recipes')
def recipes():
    meals = get_all_meals()
    return render_template('recipe_manager.html', meals=meals)

@app.route('/add_meal', methods=['POST'])
def add_meal():
    meal_name = request.form['meal_name'].strip().lower()
    if meal_name:
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO meals (name) VALUES (?)", (meal_name,))
            conn.commit()
        except conn.IntegrityError:
            # Meal already exists
            pass
        finally:
            conn.close()

    meals = get_all_meals()
    return render_template('_meals_list.html', meals=meals)

@app.route('/delete_meal/<int:meal_id>', methods=['DELETE'])
def delete_meal(meal_id):
    conn = get_db_connection()
    try:
        # First, delete references in meal_ingredients
        conn.execute("DELETE FROM meal_ingredients WHERE meal_id = ?", (meal_id,))
        # Then, delete the meal itself
        conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting meal: {e}")
        # Optionally, handle the error in the UI
    finally:
        conn.close()

    return "" # Return an empty string as the element will be removed from the DOM
