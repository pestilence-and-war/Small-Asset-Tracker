from flask import render_template, request, make_response
from app import app
from app.database import get_db_connection
from app.units import convert_to_base, needs_conversion_prompt, get_conversion_prompt_html, get_base_unit_type, get_base_unit

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

            base_unit = get_base_unit(base_unit_type)
            # For a new ingredient, we convert to its determined base unit.
            converted_quantity, _, _ = convert_to_base(quantity, unit)

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

    conn.close()

    return render_template('cooking_mode.html', meal=meal, portion=portion, recipe_items=recipe_items)

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
