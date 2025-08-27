from flask import render_template, request, make_response, jsonify
from app import app
from app.database import get_db_connection
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
    view_name = request.form.get('view_name', 'pantry')

    conn = get_db_connection()
    # We first need to get the ingredient to know its base unit for the conversion.
    ingredient_raw = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    if not ingredient_raw:
        conn.close()
        return "Ingredient not found", 404

    # The 'change' is in the current display unit. We need to convert it to the base unit.
    display_unit = request.form['unit']
    change_in_base_unit, _, _ = convert_to_base(change, display_unit, ingredient_id)

    conn.execute(
        "UPDATE ingredients SET quantity = quantity + ? WHERE id = ?",
        (change_in_base_unit, ingredient_id)
    )
    conn.commit()
    conn.close()

    # Fetch the updated ingredient to send back, with the correct display unit
    ingredient = get_ingredient_by_id(ingredient_id, view_name)
    return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

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

def get_ingredient_by_id(ingredient_id, view_name='pantry'):
    # This is a bit redundant with get_all_ingredients, but it's for a single item.
    # In a larger app, you'd refactor this.
    conn = get_db_connection()
    query = f"""
        SELECT
            i.id, i.name, i.quantity, i.base_unit, i.base_unit_type,
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
    ingredient = get_ingredient_by_id(ing_id, view_name)
    return render_template('_edit_ingredient_form.html', ingredient=ingredient, view_name=view_name)

@app.route('/edit_ingredient/<int:ing_id>', methods=['POST'])
def edit_ingredient(ing_id):
    view_name = request.form.get('view_name', 'pantry')
    new_name = request.form.get('name', '').strip().lower()
    new_quantity_str = request.form.get('quantity', '0')
    unit = request.form.get('unit')

    if not new_name or not unit:
        # Handle error
        ingredient = get_ingredient_by_id(ing_id, view_name)
        return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

    conn = get_db_connection()
    try:
        new_quantity = parse_quantity(new_quantity_str)
        # Convert the new quantity from the display unit back to the base unit for storage
        quantity_in_base, _, _ = convert_to_base(new_quantity, unit, ing_id)

        conn.execute("UPDATE ingredients SET name = ?, quantity = ? WHERE id = ?", (new_name, quantity_in_base, ing_id))
        conn.commit()
    except ValueError as e:
        print(f"Error parsing quantity or converting: {e}")
        # On error, just return the un-edited item
    except Exception as e:
        print(f"Error updating ingredient: {e}")
        # Handle other potential DB errors
    finally:
        conn.close()

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

@app.route('/search_for_converter', methods=['POST'])
def search_for_converter():
    query = request.form.get('ingredient_name', '').strip().lower()
    conn = get_db_connection()
    if query:
        ingredients = conn.execute(
            "SELECT * FROM ingredients WHERE name LIKE ? ORDER BY name LIMIT 5",
            (query + '%',)
        ).fetchall()
    else:
        ingredients = []
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
