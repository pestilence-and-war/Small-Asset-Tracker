from flask import render_template, request, make_response, jsonify
from app import app
from app.database import get_db_connection
from thefuzz import process
from app.units import (
    convert_to_base, needs_conversion_prompt, get_conversion_prompt_html,
    get_base_unit_type, get_base_unit, get_new_ingredient_conversion_prompt_html,
    convert_units, format_fraction, convert_from_base, parse_quantity
)

def get_all_units():
    # These are hardcoded for consistency in the UI
    mass_units = ['g', 'kg', 'lb', 'oz']
    volume_units = ['ml', 'l', 'cc', 'cup', 'tbsp', 'tsp', 'gallon', 'quart', 'pint']
    return mass_units, volume_units

def get_all_ingredients(view_name='pantry'):
    conn = get_db_connection()
    # Join with ingredient_view_units to get the preferred display unit
    query = f"""
        SELECT
            i.id, i.name, i.quantity, i.base_unit, i.base_unit_type,
            ivu.unit as display_unit
        FROM ingredients i
        LEFT JOIN ingredient_view_units ivu ON i.id = ivu.ingredient_id AND ivu.view_name = ?
        ORDER BY i.name
    """
    ingredients_raw = conn.execute(query, (view_name,)).fetchall()

    processed_ingredients = []
    mass_units, volume_units = get_all_units()

    for item in ingredients_raw:
        item_dict = dict(item)
        display_unit = item_dict['display_unit'] or item_dict['base_unit']
        item_dict['display_unit'] = display_unit

        # Determine compatible units for the dropdown
        if item_dict['base_unit_type'] == 'mass':
            item_dict['compatible_units'] = mass_units + volume_units
        elif item_dict['base_unit_type'] == 'volume':
            item_dict['compatible_units'] = volume_units + mass_units
        else: # count
            item_dict['compatible_units'] = ['unit']


        # Convert the base quantity to the display quantity
        try:
            base_quantity = item_dict['quantity']
            base_unit = item_dict['base_unit']
            if base_unit == display_unit:
                item_dict['display_quantity'] = base_quantity
            else:
                item_dict['display_quantity'] = convert_units(base_quantity, base_unit, display_unit, item_dict['id'])
        except ValueError as e:
            print(f"Conversion error for {item_dict['name']}: {e}")
            # If conversion fails, display the base quantity and a special unit
            item_dict['display_quantity'] = item_dict['quantity']
            item_dict['display_unit'] = item_dict['base_unit']
            item_dict['conversion_error'] = True


        processed_ingredients.append(item_dict)

    conn.close()
    return processed_ingredients

def get_all_meals():
    conn = get_db_connection()
    meals = conn.execute('SELECT * FROM meals ORDER BY name').fetchall()
    conn.close()
    return meals

@app.route('/')
def index():
    ingredients = get_all_ingredients()
    meals = get_all_meals()
    if 'HX-Request' in request.headers:
        return render_template('_home_content.html', ingredients=ingredients, meals=meals)
    return render_template('index.html', ingredients=ingredients, meals=meals)

@app.route('/pantry')
def pantry():
    ingredients = get_all_ingredients()
    return render_template('pantry.html', ingredients=ingredients)

@app.route('/add_ingredient', methods=['POST'])
def add_ingredient():
    ingredient_name = request.form['ingredient_name'].strip().lower()
    try:
        quantity = parse_quantity(request.form.get('quantity', '0'))
    except (ValueError, TypeError):
        quantity = 0
    unit = request.form.get('unit', '').strip().lower()

    if not ingredient_name or not unit:
        return render_template('_ingredients_list.html', ingredients=get_all_ingredients())

    conn = get_db_connection()
    try:
        # --- Fuzzy Matching Start ---
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}

        ingredient = None
        if all_ingredients_map:
            best_match = process.extractOne(ingredient_name, all_ingredients_map.keys())
            if best_match and best_match[1] > 85:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[best_match[0]],)).fetchone()
            else:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE name = ?", (ingredient_name,)).fetchone()
        # --- Fuzzy Matching End ---

        if ingredient:
            # Ingredient exists
            if needs_conversion_prompt(unit, ingredient['id'], conn=conn):
                # This path doesn't modify the DB, so we can just return the prompt.
                # The form in the prompt will post to a different route.
                return make_response(get_conversion_prompt_html(ingredient['id'], quantity, unit, 0))

            converted_quantity, _, _ = convert_to_base(quantity, unit, ingredient['id'], conn=conn)
            conn.execute("UPDATE ingredients SET quantity = quantity + ? WHERE id = ?", (converted_quantity, ingredient['id']))
        else:
            # New ingredient
            base_unit_type = get_base_unit_type(unit)
            if not base_unit_type:
                raise ValueError(f"Cannot determine type for unit '{unit}'.")

            if base_unit_type in ['mass', 'volume']:
                # This path also doesn't modify the DB. It returns a prompt to another route.
                response = make_response(get_new_ingredient_conversion_prompt_html(ingredient_name, quantity, unit))
                response.headers['HX-Retarget'] = '#user-prompts'
                response.headers['HX-Reswap'] = 'innerHTML'
                return response

            base_unit = get_base_unit(base_unit_type)
            converted_quantity, _, _ = convert_to_base(quantity, unit, conn=conn)
            conn.execute(
                'INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)',
                (ingredient_name, converted_quantity, base_unit, base_unit_type)
            )

        conn.commit()

    except (ValueError, TypeError) as e:
        print(f"Error in add_ingredient: {e}")
        # On error, rollback any changes and don't save.
        if conn: conn.rollback()
        # We can also return an error message to the user here.
        # For now, just returning the latest ingredient list.
    finally:
        if conn: conn.close()

    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)

@app.route('/search')
def search():
    query = request.args.get('q', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}

        # Use thefuzz to find best matches
        # We extract tuples of (name, score)
        matches = process.extract(query, all_ingredients_map.keys(), limit=5)

        # Get the full ingredient object for each match
        conn = get_db_connection()
        for name, score in matches:
            if score > 50: # Set a threshold to avoid very irrelevant matches
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
        conn.close()

    return render_template('_search_results.html', ingredients=ingredients)

@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    ingredient_id = request.form['id']
    view_name = request.form.get('view_name', 'pantry')

    conn = get_db_connection()
    try:
        with conn:
            change = float(request.form['change'])
            display_unit = request.form['unit']

            # The 'change' is in the current display unit. We need to convert it to the base unit.
            change_in_base_unit, _, _ = convert_to_base(change, display_unit, ingredient_id, conn=conn)

            conn.execute(
                "UPDATE ingredients SET quantity = quantity + ? WHERE id = ?",
                (change_in_base_unit, ingredient_id)
            )
    except (ValueError, TypeError) as e:
        print(f"Error in update_quantity: {e}")
        # Rollback is handled by the 'with' statement.
    finally:
        if conn: conn.close()

    # Fetch the updated ingredient to send back, with the correct display unit
    ingredient = get_ingredient_by_id(ingredient_id, view_name)
    if not ingredient:
        return "Ingredient not found", 404

    return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

@app.route('/add_conversion', methods=['POST'])
def add_conversion():
    ingredient_id = request.form['ingredient_id']
    from_unit = request.form['from_unit']
    to_unit = request.form['to_unit']
    factor = float(request.form['factor'])
    original_quantity = float(request.form['quantity_to_add'])
    original_unit = request.form['unit_to_add']

    conn = get_db_connection()
    try:
        with conn:
            # Save the new conversion factor
            conn.execute(
                "INSERT INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                (ingredient_id, from_unit, to_unit, factor)
            )

            # Now that the conversion is saved, add the original quantity again.
            # No new connection is needed as we are in the same transaction.
            converted_quantity, _, _ = convert_to_base(original_quantity, original_unit, ingredient_id, conn=conn)
            conn.execute(
                "UPDATE ingredients SET quantity = quantity + ? WHERE id = ?",
                (converted_quantity, ingredient_id)
            )
    except Exception as e:
        print(f"Error in add_conversion: {e}")
        # Rollback is handled by 'with conn:'.
    finally:
        if conn: conn.close()

    # Return the updated ingredient list
    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)

@app.route('/add_new_ingredient_with_density', methods=['POST'])
def add_new_ingredient_with_density():
    ingredient_name = request.form['ingredient_name'].strip().lower()
    original_quantity = float(request.form['original_quantity'])
    original_unit = request.form['original_unit']
    density_g_ml = float(request.form['density_g_ml'])

    conn = get_db_connection()
    try:
        with conn: # Use 'with' statement for automatic transaction handling (commit/rollback)
            # 1. Create the new ingredient.
            base_unit = 'g'
            base_unit_type = 'mass'

            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, density_g_ml) VALUES (?, ?, ?, ?, ?)',
                (ingredient_name, 0, base_unit, base_unit_type, density_g_ml)
            )
            ingredient_id = cursor.lastrowid

            # 2. Convert the original quantity to the base quantity.
            # The new ingredient is visible within the same transaction, so no need for a new connection.
            converted_quantity, _, _ = convert_to_base(original_quantity, original_unit, ingredient_id, conn=conn)

            # 3. Update the ingredient with the correct converted quantity.
            conn.execute(
                "UPDATE ingredients SET quantity = ? WHERE id = ?",
                (converted_quantity, ingredient_id)
            )
            # The 'with' block will commit here if no exceptions were raised.

    except Exception as e:
        print(f"Error in add_new_ingredient_with_density: {e}")
        # The 'with' block will roll back on exception.
        # Optionally handle error, e.g., by returning an error message to the user.
    finally:
        if conn: conn.close()

    # Return the updated ingredient list, which also clears the prompt.
    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)

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

    # Get ingredients for the meal, including their preferred display unit for 'cooking' view
    meal_ingredients_raw = conn.execute("""
        SELECT
            i.id, i.name, i.quantity as pantry_quantity, i.base_unit, i.base_unit_type,
            mi.quantity as recipe_quantity, mi.unit as recipe_unit,
            ivu.unit as display_unit
        FROM ingredients i
        JOIN meal_ingredients mi ON i.id = mi.ingredient_id
        LEFT JOIN ingredient_view_units ivu ON i.id = ivu.ingredient_id AND ivu.view_name = 'cooking'
        WHERE mi.meal_id = ?
    """, (meal_id,)).fetchall()

    recipe_items = []
    missing_conversions = []
    for item_raw in meal_ingredients_raw:
        item = dict(item_raw)
        try:
            required_quantity_recipe_unit = item['recipe_quantity'] * portion
            required_quantity_base, _, _ = convert_to_base(required_quantity_recipe_unit, item['recipe_unit'], item['id'])

            # Determine the best unit for display. Priority: cooking preference > recipe unit > base unit.
            display_unit = item['display_unit'] or item['recipe_unit'] or item['base_unit']

            # Convert required quantity and pantry quantity to the display unit for the UI
            display_quantity_required = convert_units(required_quantity_base, item['base_unit'], display_unit, item['id'])
            display_quantity_pantry = convert_units(item['pantry_quantity'], item['base_unit'], display_unit, item['id'])

            recipe_items.append({
                "ingredient": {
                    "id": item['id'],
                    "name": item['name'],
                    "display_unit": display_unit
                },
                "display_quantity_required": display_quantity_required,
                "display_quantity_pantry": display_quantity_pantry,
                "required_quantity_base": required_quantity_base, # For pantry deduction
                "pantry_quantity_base": item['pantry_quantity'], # For stock status logic
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

def get_ingredient_by_id(ingredient_id, view_name='pantry', for_editing=False):
    # This is a bit redundant with get_all_ingredients, but it's for a single item.
    # In a larger app, you'd refactor this.
    conn = get_db_connection()
    query = f"""
        SELECT
            i.id, i.name, i.quantity, i.base_unit, i.base_unit_type, i.density_g_ml,
            ivu.unit as display_unit
        FROM ingredients i
        LEFT JOIN ingredient_view_units ivu ON i.id = ivu.ingredient_id AND ivu.view_name = ?
        WHERE i.id = ?
    """
    item = conn.execute(query, (view_name, ingredient_id)).fetchone()

    if not item:
        conn.close()
        return None

    item_dict = dict(item)
    display_unit = item_dict['display_unit'] or item_dict['base_unit']
    item_dict['display_unit'] = display_unit

    mass_units, volume_units = get_all_units()
    if for_editing:
        # For the edit form, we want to show all possible units
        item_dict['compatible_units'] = mass_units + volume_units + ['unit']
    else:
        # For display, only show compatible units
        if item_dict['base_unit_type'] == 'mass':
            item_dict['compatible_units'] = mass_units + volume_units
        elif item_dict['base_unit_type'] == 'volume':
            item_dict['compatible_units'] = volume_units + mass_units
        else: # count
            item_dict['compatible_units'] = ['unit']

    try:
        base_quantity = item_dict['quantity']
        base_unit = item_dict['base_unit']
        if base_unit == display_unit:
            item_dict['display_quantity'] = base_quantity
        else:
            item_dict['display_quantity'] = convert_units(base_quantity, base_unit, display_unit, item_dict['id'])
    except ValueError as e:
        print(f"Conversion error for {item_dict['name']}: {e}")
        item_dict['display_quantity'] = item_dict['quantity']
        item_dict['display_unit'] = item_dict['base_unit']
        item_dict['conversion_error'] = True

    conn.close()
    return item_dict

@app.route('/update_ingredient_display_unit/<int:ingredient_id>', methods=['POST'])
def update_ingredient_display_unit(ingredient_id):
    new_unit = request.form.get('unit')
    view_name = request.form.get('view_name', 'pantry')

    if not new_unit:
        # Handle error
        return "No unit provided", 400

    conn = get_db_connection()
    try:
        # Use INSERT OR REPLACE to either create a new preference or update an existing one
        conn.execute("""
            INSERT INTO ingredient_view_units (ingredient_id, view_name, unit)
            VALUES (?, ?, ?)
            ON CONFLICT(ingredient_id, view_name) DO UPDATE SET unit = excluded.unit
        """, (ingredient_id, view_name, new_unit))
        conn.commit()
    except Exception as e:
        print(f"Error updating display unit: {e}")
        conn.close()
        # Handle error
        return "Error updating preference", 500
    finally:
        if conn: conn.close()

    # Fetch the updated ingredient data and return the rendered partial
    ingredient = get_ingredient_by_id(ingredient_id, view_name)
    return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)


@app.route('/ingredient/<int:ing_id>')
def get_ingredient(ing_id):
    # This route might be deprecated by the new get_ingredient_by_id, but we'll keep it for now.
    ingredient = get_ingredient_by_id(ing_id)
    return render_template('_ingredient_item.html', ingredient=ingredient)

@app.route('/edit_ingredient_form/<int:ing_id>')
def edit_ingredient_form(ing_id):
    view_name = request.args.get('view_name', 'pantry')
    ingredient = get_ingredient_by_id(ing_id, view_name, for_editing=True)
    return render_template('_edit_ingredient_form.html', ingredient=ingredient, view_name=view_name)

@app.route('/edit_ingredient/<int:ing_id>', methods=['POST'])
def edit_ingredient(ing_id):
    view_name = request.form.get('view_name', 'pantry')
    new_name = request.form.get('name', '').strip().lower()
    new_quantity_str = request.form.get('quantity', '0')
    new_unit = request.form.get('unit')

    if not new_name or not new_unit:
        ingredient = get_ingredient_by_id(ing_id, view_name)
        return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

    conn = get_db_connection()
    try:
        with conn:
            current_ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
            if not current_ingredient:
                return "Ingredient not found", 404

            current_base_unit_type = current_ingredient['base_unit_type']
            new_quantity = parse_quantity(new_quantity_str)
            new_unit_type = get_base_unit_type(new_unit)

            if not new_unit_type:
                raise ValueError(f"Invalid unit provided: {new_unit}")

            # Scenario 1: Unit type isn't changing significantly (or changing to 'count')
            if new_unit_type == current_base_unit_type or new_unit_type == 'count':
                if new_unit_type != current_base_unit_type:
                    quantity_in_base, final_base_unit, final_base_unit_type = convert_to_base(new_quantity, new_unit, conn=conn)
                    conn.execute(
                        "UPDATE ingredients SET name = ?, quantity = ?, base_unit = ?, base_unit_type = ? WHERE id = ?",
                        (new_name, quantity_in_base, final_base_unit, final_base_unit_type, ing_id)
                    )
                else:
                    quantity_in_base, _, _ = convert_to_base(new_quantity, new_unit, ing_id, conn=conn)
                    conn.execute("UPDATE ingredients SET name = ?, quantity = ? WHERE id = ?", (new_name, quantity_in_base, ing_id))

                conn.execute("""
                    INSERT INTO ingredient_view_units (ingredient_id, view_name, unit) VALUES (?, ?, ?)
                    ON CONFLICT(ingredient_id, view_name) DO UPDATE SET unit = excluded.unit
                """, (ing_id, view_name, new_unit))

            # Scenario 2: Unit type is changing between mass/volume and density is required
            else:
                if not current_ingredient['density_g_ml']:
                    # The 'with conn' block will close the connection, so we can safely return a prompt here.
                    # No changes have been committed.
                    return render_template(
                        '_update_density_prompt.html',
                        ingredient=dict(current_ingredient), new_name=new_name,
                        new_quantity=new_quantity, new_unit=new_unit, view_name=view_name
                    )
                else: # Density exists
                    quantity_in_base, final_base_unit, final_base_unit_type = convert_to_base(new_quantity, new_unit, ing_id, conn=conn)
                    conn.execute(
                        "UPDATE ingredients SET name = ?, quantity = ?, base_unit = ?, base_unit_type = ? WHERE id = ?",
                        (new_name, quantity_in_base, final_base_unit, final_base_unit_type, ing_id)
                    )
                    conn.execute("""
                        INSERT INTO ingredient_view_units (ingredient_id, view_name, unit) VALUES (?, ?, ?)
                        ON CONFLICT(ingredient_id, view_name) DO UPDATE SET unit = excluded.unit
                    """, (ing_id, view_name, new_unit))

    except (ValueError, TypeError) as e:
        print(f"Error in edit_ingredient: {e}")
        # Rollback is handled by the 'with' statement.
    finally:
        if conn: conn.close()

    ingredient = get_ingredient_by_id(ing_id, view_name)
    return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

@app.route('/update_ingredient_details/<int:ing_id>', methods=['POST'])
def update_ingredient_details(ing_id):
    view_name = request.form.get('view_name', 'pantry')
    new_name = request.form.get('new_name', '').strip().lower()
    new_quantity_str = request.form.get('new_quantity', '0')
    new_unit = request.form.get('new_unit')
    density_g_ml_str = request.form.get('density_g_ml')

    if not all([new_name, new_unit, density_g_ml_str]):
        return "Error: Missing required fields.", 400

    conn = get_db_connection()
    try:
        with conn:
            new_quantity = parse_quantity(new_quantity_str)
            density_g_ml = float(density_g_ml_str)
            new_unit_type = get_base_unit_type(new_unit)
            new_base_unit = get_base_unit(new_unit_type)

            current_ingredient = conn.execute("SELECT base_unit_type FROM ingredients WHERE id = ?", (ing_id,)).fetchone()
            current_base_unit_type = current_ingredient['base_unit_type'] if current_ingredient else None

            # Scenario: Changing a 'count' ingredient to a 'mass' or 'volume' one.
            if current_base_unit_type == 'count' and new_unit_type in ['mass', 'volume']:
                quantity_in_base, _, _ = convert_to_base(new_quantity, new_unit, conn=conn)
                conn.execute(
                    """UPDATE ingredients
                       SET name = ?, quantity = ?, base_unit = ?, base_unit_type = ?, density_g_ml = ?
                       WHERE id = ?""",
                    (new_name, quantity_in_base, new_base_unit, new_unit_type, density_g_ml, ing_id)
                )
            else:
                # Standard flow: The ingredient is already a mass/volume type.
                conn.execute("UPDATE ingredients SET density_g_ml = ? WHERE id = ?", (density_g_ml, ing_id))
                quantity_in_base, _, _ = convert_to_base(new_quantity, new_unit, ing_id, conn=conn)
                conn.execute(
                    "UPDATE ingredients SET name = ?, quantity = ?, base_unit = ?, base_unit_type = ? WHERE id = ?",
                    (new_name, quantity_in_base, new_base_unit, new_unit_type, ing_id)
                )

            # Always update the preferred display unit for the current view
            conn.execute("""
                INSERT INTO ingredient_view_units (ingredient_id, view_name, unit) VALUES (?, ?, ?)
                ON CONFLICT(ingredient_id, view_name) DO UPDATE SET unit = excluded.unit
            """, (ing_id, view_name, new_unit))

    except (ValueError, TypeError) as e:
        print(f"Error in update_ingredient_details: {e}")
        # Rollback is handled by 'with conn:'.
    finally:
        if conn: conn.close()

    ingredient = get_ingredient_by_id(ing_id, view_name)
    return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)


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

@app.route('/batch_add_ingredients', methods=['POST'])
def batch_add_ingredients():
    ingredients_list_str = request.form.get('ingredients_list', '')
    if not ingredients_list_str:
        ingredients = get_all_ingredients()
        return render_template('_ingredients_list.html', ingredients=ingredients)

    ingredient_names = [name.strip().lower() for name in ingredients_list_str.split(',') if name.strip()]

    conn = get_db_connection()
    try:
        with conn:
            for name in ingredient_names:
                # Check if ingredient already exists
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM ingredients WHERE name = ?", (name,))
                if cursor.fetchone() is None:
                    # If not, insert it with default values
                    cursor.execute(
                        "INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)",
                        (name, 0, 'unit', 'count')
                    )
    except Exception as e:
        print(f"Error in batch_add_ingredients: {e}")
    finally:
        if conn: conn.close()

    # Return the full, updated ingredient list to be swapped into the DOM
    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)

@app.route('/search_for_converter', methods=['POST'])
def search_for_converter():
    query = request.form.get('ingredient_name', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5)

        conn = get_db_connection()
        for name, score in matches:
            if score > 50:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
        conn.close()

    return render_template('_search_results_for_converter.html', ingredients=ingredients)

@app.route('/calculate_conversion', methods=['POST'])
def calculate_conversion():
    try:
        from_quantity = float(request.form['from_quantity'])
        from_unit = request.form['from_unit']
        to_unit = request.form['to_unit']
        ingredient_id = request.form.get('ingredient_id')

        if not ingredient_id:
            return "<p class='error'>Please select an ingredient first.</p>"

        result = convert_units(from_quantity, from_unit, to_unit, int(ingredient_id))
        # Use format_fraction for a nicer display if the result is a number
        formatted_result = format_fraction(result)

        return f"<p>{from_quantity} {from_unit} is approximately <strong>{formatted_result} {to_unit}</strong></p>"
    except ValueError as e:
        return f"<p class='error'>Error: {e}</p>"
    except Exception as e:
        return f"<p class='error'>An unexpected error occurred: {e}</p>"

@app.route('/calculate_density', methods=['POST'])
def calculate_density():
    try:
        vol_qty = float(request.form['vol_qty'])
        vol_unit = request.form['vol_unit']
        mass_qty = float(request.form['mass_qty'])
        mass_unit = request.form['mass_unit']

        # To calculate density in g/ml, we need to convert both quantities to g and ml
        # We can use our conversion functions, but we don't have an ingredient context.
        # So we'll do it manually based on the unit_conversions table.
        conn = get_db_connection()

        # Convert volume to ml
        vol_in_ml = vol_qty
        if vol_unit != 'ml':
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'ml'", (vol_unit,)).fetchone()
            if not res:
                conn.close()
                raise ValueError(f"No conversion factor for {vol_unit} to ml")
            vol_in_ml = vol_qty * res['factor']

        # Convert mass to g
        mass_in_g = mass_qty
        if mass_unit != 'g':
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'g'", (mass_unit,)).fetchone()
            if not res:
                conn.close()
                raise ValueError(f"No conversion factor for {mass_unit} to g")
            mass_in_g = mass_qty * res['factor']

        conn.close()

        if vol_in_ml == 0:
            raise ValueError("Volume cannot be zero.")

        density = mass_in_g / vol_in_ml

        return f"""
            <p>Calculated Density: <strong>{density:.4f} g/ml</strong></p>
            <button type="button" class="button-secondary" onclick="useDensity({density:.4f})">Use this density</button>
        """
    except ValueError as e:
        return f"<p class='error'>Error: {e}</p>"
    except Exception as e:
        return f"<p class='error'>An unexpected error occurred: {e}</p>"

def get_meal_ingredients(meal_id, view_name='recipe'):
    conn = get_db_connection()
    meal_ingredients_raw = conn.execute("""
        SELECT
            i.id as ingredient_id,
            i.name,
            i.base_unit,
            i.base_unit_type,
            i.density_g_ml,
            mi.quantity,
            mi.unit,
            mi.id as meal_ingredient_id,
            ivu.unit as display_unit
        FROM meal_ingredients mi
        JOIN ingredients i ON mi.ingredient_id = i.id
        LEFT JOIN ingredient_view_units ivu ON i.id = ivu.ingredient_id AND ivu.view_name = ?
        WHERE mi.meal_id = ?
        ORDER BY i.name
    """, (view_name, meal_id)).fetchall()

    processed_ingredients = []
    mass_units, volume_units = get_all_units()

    for item in meal_ingredients_raw:
        item_dict = dict(item)

        # The 'unit' from meal_ingredients is the one specified in the recipe.
        # The 'display_unit' is the user's preference for viewing.
        # For recipes, we should probably default to the recipe's unit if no preference is set.
        display_unit = item_dict['display_unit'] or item_dict['unit']
        item_dict['display_unit'] = display_unit

        # Determine compatible units for the dropdown
        if item_dict['base_unit_type'] == 'mass':
            item_dict['compatible_units'] = mass_units + volume_units
        elif item_dict['base_unit_type'] == 'volume':
            item_dict['compatible_units'] = volume_units + mass_units
        else: # count
            item_dict['compatible_units'] = ['unit']

        # Convert the recipe quantity to the display quantity
        try:
            recipe_quantity = item_dict['quantity']
            recipe_unit = item_dict['unit']
            if recipe_unit == display_unit:
                item_dict['display_quantity'] = recipe_quantity
            else:
                # We need to convert from the recipe unit to the display unit
                item_dict['display_quantity'] = convert_units(recipe_quantity, recipe_unit, display_unit, item_dict['ingredient_id'])
        except ValueError as e:
            print(f"Conversion error for {item_dict['name']} in recipe: {e}")
            item_dict['display_quantity'] = item_dict['quantity']
            item_dict['display_unit'] = item_dict['unit'] # Fallback to recipe unit
            item_dict['conversion_error'] = True

        processed_ingredients.append(item_dict)

    conn.close()
    return processed_ingredients

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
            ingredient_quantity = parse_quantity(quantity)
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

@app.route('/update_recipe_ingredient_unit/<int:meal_id>/<int:ingredient_id>', methods=['POST'])
def update_recipe_ingredient_unit(meal_id, ingredient_id):
    new_unit = request.form.get('unit')
    view_name = 'recipe' # Hardcoded for this route

    if not new_unit:
        return "No unit provided", 400

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO ingredient_view_units (ingredient_id, view_name, unit)
            VALUES (?, ?, ?)
            ON CONFLICT(ingredient_id, view_name) DO UPDATE SET unit = excluded.unit
        """, (ingredient_id, view_name, new_unit))
        conn.commit()
    except Exception as e:
        print(f"Error updating display unit for recipe: {e}")
    finally:
        if conn: conn.close()

    # Re-fetch the meal and ingredients and return the list partial
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
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5)

        conn = get_db_connection()
        for name, score in matches:
            if score > 50:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
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
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5)

        conn = get_db_connection()
        for name, score in matches:
            if score > 50:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
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
