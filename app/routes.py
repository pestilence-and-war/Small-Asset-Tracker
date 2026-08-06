import time
from flask import render_template, request, make_response, jsonify
from app import app
from app.database import get_db_connection
from thefuzz import process, fuzz
from app.units import (
    convert_to_base, needs_conversion_prompt, get_conversion_prompt_html,
    get_base_unit_type, get_base_unit, get_new_ingredient_conversion_prompt_html,
    convert_units, format_fraction, convert_from_base, parse_quantity,
    parse_quantity_and_unit, get_category_density
)
import os
from werkzeug.utils import secure_filename
from app.importer_service import import_recipe_from_text, import_recipe_from_image
from app.api_clients.off_client import OpenFoodFactsClient

off_client = OpenFoodFactsClient()

def get_all_units():
    """Returns lists of mass and volume units.

    These are hardcoded for consistency in the UI.

    Returns:
        tuple: A tuple containing two lists:
            - list: Mass units.
            - list: Volume units.
    """
    mass_units = ['g', 'kg', 'lb', 'oz']
    volume_units = ['ml', 'l', 'cc', 'cup', 'tbsp', 'tsp', 'gallon', 'quart', 'pint']
    return mass_units, volume_units


def get_all_categories():
    """Returns a list of all available ingredient categories.

    Returns:
        list: A list of category names.
    """
    return [
        'Alcohol', 'Bakery & Bread', 'Baking', 'Beverages', 'Breakfast & Cereal',
        'Candy', 'Canned Goods', 'Condiments', 'Dairy & Eggs', 'Deli', 'Dips & Cheeseballs', 'Dry Goods',
        'Fresh Produce', 'Frozen Foods', 'Meat & Seafood',
        'Other', 'Pantry', 'Snacks', 'Soups and Chili mixes', 'Spices'
    ]


def get_all_ingredients(view_name='pantry', search_query=None):
    """Fetches all ingredients from the database, grouped by category.

    Args:
        view_name (str, optional): The view for which to fetch the ingredients.
            This affects the display unit. Defaults to 'pantry'.
        search_query (str, optional): A search term to filter ingredients by name.

    Returns:
        dict: A dictionary of ingredients, with categories as keys and lists
            of ingredient dictionaries as values.
    """
    conn = get_db_connection()
    # Join with ingredient_view_units to get the preferred display unit
    sql = f"""
        SELECT
            i.id, i.name, i.category, i.quantity, i.base_unit, i.base_unit_type, i.image_url,
            ivu.unit as display_unit
        FROM ingredients i
        LEFT JOIN ingredient_view_units ivu ON i.id = ivu.ingredient_id AND ivu.view_name = ?
    """
    params = [view_name]
    
    if search_query:
        sql += " WHERE i.name LIKE ?"
        params.append(f"%{search_query}%")
        
    sql += " ORDER BY i.category, i.name"
    
    ingredients_raw = conn.execute(sql, tuple(params)).fetchall()

    ingredients_by_category = {}
    mass_units, volume_units = get_all_units()

    for item in ingredients_raw:
        item_dict = dict(item)
        display_unit = item_dict['display_unit'] or item_dict['base_unit']
        item_dict['display_unit'] = display_unit

        # Determine compatible units for the dropdown
        if item_dict['base_unit_type'] == 'mass':
            item_dict['compatible_units'] = mass_units + volume_units + ['unit']
        elif item_dict['base_unit_type'] == 'volume':
            item_dict['compatible_units'] = volume_units + mass_units + ['unit']
        else: # count
            item_dict['compatible_units'] = ['unit'] + mass_units + volume_units


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

        category = item_dict['category']
        if category not in ingredients_by_category:
            ingredients_by_category[category] = []
        ingredients_by_category[category].append(item_dict)


    conn.close()
    return ingredients_by_category


def get_all_meals():
    """Fetches all meals from the database.

    Returns:
        list: A list of meal dictionaries.
    """
    conn = get_db_connection()
    meals = conn.execute('SELECT * FROM meals ORDER BY name').fetchall()
    conn.close()
    return meals

@app.route('/')
def index():
    """Renders the main page.

    If the request is an HTMX request, it returns only the home content partial.
    Otherwise, it returns the full index page.
    """
    ingredients = get_all_ingredients()
    meals = get_all_meals()
    if 'HX-Request' in request.headers:
        return render_template('_home_content.html', ingredients=ingredients, meals=meals)
    return render_template('index.html', ingredients=ingredients, meals=meals)


@app.route('/scanner')
def scanner():
    """Renders the barcode scanner page."""
    if 'HX-Request' in request.headers:
        return render_template('scanner.html')
    return render_template('index.html', page_content=render_template('scanner.html'))


@app.route('/api/add_item_by_upc', methods=['POST'])
def add_item_by_upc():
    """Handles adding an ingredient to the pantry via a UPC barcode code.

    Receives JSON {'upc': '...'}. Looks up local `upc_data` first, then Open Food Facts.
    Saves barcode mapping into `upc_data` table for instant future scans.
    """
    data = request.get_json()
    if not data or 'upc' not in data:
        return jsonify({'status': 'error', 'message': 'Invalid request. Missing UPC barcode.'}), 400

    upc = str(data['upc']).strip()
    conn = get_db_connection()
    try:
        with conn:
            upc_item = conn.execute("SELECT * FROM upc_data WHERE upc = ?", (upc,)).fetchone()

            brand = None
            image_url = None

            if not upc_item:
                # Query Open Food Facts API
                off_data = off_client.get_product_by_barcode(upc)
                if not off_data:
                    return jsonify({
                        'status': 'not_found',
                        'upc': upc,
                        'message': f'Barcode {upc} not recognized. Add details below to save it for future scans.'
                    }), 200

                item_name = off_data['name'].strip().lower()
                category = off_data.get('category', 'Other')
                image_url = off_data.get('image_url')
                brand = off_data.get('brand')

                cat_map = {
                    "Beverages": "Beverages", "Sodas": "Beverages", "Waters": "Beverages", "Fruit Juices": "Beverages",
                    "Canned Foods": "Canned Goods", "Plant Based Foods": "Fresh Produce",
                    "Groceries": "Pantry", "Snacks": "Snacks", "Condiments": "Condiments", "Baking": "Baking"
                }
                local_category = cat_map.get(category, "Other")

                item_quantity = 1.0
                item_unit = 'unit'
                if off_data.get('quantity_str'):
                    parsed_qty, parsed_unit = parse_quantity_and_unit(off_data['quantity_str'])
                    if parsed_qty is not None and parsed_unit:
                        item_quantity = parsed_qty
                        item_unit = parsed_unit

                if not item_name:
                    return jsonify({'status': 'not_found', 'upc': upc, 'message': f'Barcode {upc} found but missing item name.'}), 200

            else:
                item_name = upc_item['name'].strip().lower()
                item_quantity = upc_item['quantity'] if upc_item['quantity'] is not None else 1.0
                item_unit = upc_item['unit'].strip().lower() if upc_item['unit'] else 'unit'
                local_category = "Other"
                brand = upc_item['brand'] if 'brand' in upc_item.keys() else None
                image_url = upc_item['image_url'] if 'image_url' in upc_item.keys() else None

            # Find matching ingredient in pantry
            ingredient = conn.execute("SELECT * FROM ingredients WHERE name = ?", (item_name,)).fetchone()
            if not ingredient:
                # Try fuzzy/substring match
                ingredient = conn.execute("SELECT * FROM ingredients WHERE name LIKE ?", (f"%{item_name}%",)).fetchone()

            if ingredient:
                ingredient_id = ingredient['id']
                item_name = ingredient['name']
                quantity_to_add_in_base, _, _ = convert_to_base(item_quantity, item_unit, ingredient_id=ingredient_id, conn=conn)
                conn.execute("UPDATE ingredients SET quantity = quantity + ? WHERE id = ?", (quantity_to_add_in_base, ingredient_id))

                if image_url and not ingredient['image_url']:
                    conn.execute("UPDATE ingredients SET image_url = ? WHERE id = ?", (image_url, ingredient_id))

                message = f"Added {item_quantity} {item_unit} to {item_name.title()}."

            else:
                # Create new ingredient
                base_unit_type = get_base_unit_type(item_unit)
                base_unit = get_base_unit(base_unit_type)
                density = get_category_density(local_category)

                converted_quantity, _, _ = convert_to_base(item_quantity, item_unit, density_g_ml=density, conn=conn)

                cursor = conn.execute(
                    'INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, category, density_g_ml, image_url) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (item_name, converted_quantity, base_unit, base_unit_type, local_category, density, image_url)
                )
                ingredient_id = cursor.lastrowid
                message = f"Added new item: {item_name.title()} ({item_quantity} {item_unit})."

            # Save/update barcode mapping in upc_data
            conn.execute(
                "INSERT OR REPLACE INTO upc_data (upc, name, brand, quantity, unit, ingredient_id, image_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (upc, item_name, brand, item_quantity, item_unit, ingredient_id, image_url)
            )

            return jsonify({
                'status': 'success',
                'message': message,
                'name': item_name.title(),
                'brand': brand,
                'quantity': item_quantity,
                'unit': item_unit,
                'image_url': image_url,
                'upc': upc
            })

    except Exception as e:
        print(f"Error in add_item_by_upc: {e}")
        return jsonify({'status': 'error', 'message': f"Could not add item: {str(e)}"}), 200


@app.route('/api/link_upc', methods=['POST'])
def link_upc():
    """Manually maps an unrecognized UPC barcode to an ingredient."""
    data = request.get_json()
    if not data or 'upc' not in data or 'name' not in data:
        return jsonify({'status': 'error', 'message': 'Missing UPC or ingredient name.'}), 400

    upc = str(data['upc']).strip()
    name = str(data['name']).strip().lower()
    quantity = float(data.get('quantity', 1.0))
    unit = str(data.get('unit', 'unit')).strip().lower()
    category = str(data.get('category', 'Other')).strip()

    conn = get_db_connection()
    try:
        with conn:
            ingredient = conn.execute("SELECT * FROM ingredients WHERE name = ?", (name,)).fetchone()
            if ingredient:
                ingredient_id = ingredient['id']
                qty_base, _, _ = convert_to_base(quantity, unit, ingredient_id=ingredient_id, conn=conn)
                conn.execute("UPDATE ingredients SET quantity = quantity + ? WHERE id = ?", (qty_base, ingredient_id))
            else:
                base_unit_type = get_base_unit_type(unit)
                base_unit = get_base_unit(base_unit_type)
                density = get_category_density(category)
                qty_base, _, _ = convert_to_base(quantity, unit, density_g_ml=density, conn=conn)

                cursor = conn.execute(
                    "INSERT INTO ingredients (name, quantity, base_unit, base_unit_type, category, density_g_ml) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, qty_base, base_unit, base_unit_type, category, density)
                )
                ingredient_id = cursor.lastrowid

            conn.execute(
                "INSERT OR REPLACE INTO upc_data (upc, name, quantity, unit, ingredient_id) VALUES (?, ?, ?, ?, ?)",
                (upc, name, quantity, unit, ingredient_id)
            )

        return jsonify({'status': 'success', 'message': f"Mapped barcode {upc} to {name.title()}!"})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500



@app.route('/pantry')
def pantry():
    """Renders the pantry page or the filtered ingredients list."""
    query = request.args.get('q')
    ingredients = get_all_ingredients(search_query=query)
    
    if 'HX-Request' in request.headers and query is not None:
        return render_template('_ingredients_list.html', ingredients=ingredients, show_edit_buttons=True)
        
    return render_template('pantry.html', ingredients=ingredients)


@app.route('/add_ingredient', methods=['POST'])
def add_ingredient():
    """Adds a new ingredient or updates the quantity of an existing one.

    This route handles the form submission for adding ingredients to the pantry.
    It can trigger a conversion prompt if necessary.
    """
    ingredient_name = request.form['q'].strip().lower()
    try:
        quantity = parse_quantity(request.form.get('quantity', '0'))
    except (ValueError, TypeError):
        quantity = 0
    unit = request.form.get('unit', '').strip().lower()

    if not ingredient_name or not unit:
        return render_template('_ingredients_list.html', ingredients=get_all_ingredients())

    conn = get_db_connection()
    try:
        # Check for an exact match for an existing ingredient.
        ingredient = conn.execute("SELECT * FROM ingredients WHERE name = ?", (ingredient_name,)).fetchone()

        if ingredient:
            # Ingredient exists, update its quantity.
            if needs_conversion_prompt(unit, ingredient['id'], conn=conn):
                prompt_html = get_conversion_prompt_html(ingredient['id'], quantity, unit, 0)
                ingredients = get_all_ingredients()
                list_html = render_template('_ingredients_list.html', ingredients=ingredients)
                return list_html + prompt_html

            converted_quantity, _, _ = convert_to_base(quantity, unit, ingredient['id'], conn=conn)
            conn.execute("UPDATE ingredients SET quantity = quantity + ? WHERE id = ?", (converted_quantity, ingredient['id']))
        else:
            # New ingredient. Add it without prompting for density.
            base_unit_type = get_base_unit_type(unit)
            if not base_unit_type:
                # If the unit is unknown, treat it as a 'count' type.
                base_unit_type = 'count'
                base_unit = 'unit'
                # The quantity is as-is since the unit is just 'unit'.
                converted_quantity = quantity
            else:
                 base_unit = get_base_unit(base_unit_type)
                 # For a new ingredient, there's no ingredient_id yet.
                 converted_quantity, _, _ = convert_to_base(quantity, unit, conn=conn)

            conn.execute(
                'INSERT INTO ingredients (name, quantity, base_unit, base_unit_type) VALUES (?, ?, ?, ?)',
                (ingredient_name, converted_quantity, base_unit, base_unit_type)
            )

        conn.commit()

    except (ValueError, TypeError) as e:
        print(f"Error in add_ingredient: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

    ingredients = get_all_ingredients()
    return render_template('_ingredients_list.html', ingredients=ingredients)


@app.route('/search')
def search():
    """Searches for ingredients based on a query string.

    Uses fuzzy matching to find the best matches.
    """
    query = request.args.get('q', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}

        # Use thefuzz to find best matches
        # We extract tuples of (name, score)
        matches = process.extract(query, all_ingredients_map.keys(), limit=5, scorer=fuzz.token_set_ratio)

        # Get the full ingredient object for each match
        conn = get_db_connection()
        for name, score in matches:
            if score > 50: # Set a threshold to avoid very irrelevant matches
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
        conn.close()

    return render_template('_search_results.html', ingredients=ingredients)

@app.route('/search_pantry_ingredients')
def search_pantry_ingredients():
    """Searches for ingredients and includes an option to add a new one.

    Similar to `/search`, but tailored for the pantry view, offering to
    create a new ingredient if no good match is found.
    """
    query = request.args.get('q', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5, scorer=fuzz.token_set_ratio)

        conn = get_db_connection()

        # Keep track of names to avoid duplicates
        found_names = set()

        for name, score in matches:
            if score > 50 and name not in found_names:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                # append as dict
                ingredients.append(dict(ingredient))
                found_names.add(name)

        # Add an option to create the typed ingredient if it's not in the suggestions
        if query not in found_names:
            ingredients.append({'name': query, 'is_new': True})

        conn.close()

    return render_template('_ingredient_search_results.html', ingredients=ingredients, query=query)


@app.route('/update_quantity', methods=['POST'])
def update_quantity():
    """Updates the quantity of an ingredient by a given amount.

    This is used for the + and - buttons in the pantry view.
    The change amount is converted from the display unit to the base unit
    before updating the database.
    """
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
    """Adds a new ingredient-specific unit conversion.

    This is triggered by the conversion prompt when adding an ingredient
    with a unit that requires a new conversion factor.
    """
    ingredient_id = request.form['ingredient_id']
    from_unit = request.form['from_unit']
    to_unit = request.form['to_unit']
    original_quantity = float(request.form['quantity_to_add'])
    original_unit = request.form['unit_to_add']
    
    if request.form.get('is_total_conversion') == 'true':
        total_target_quantity = float(request.form['total_target_quantity'])
        factor = total_target_quantity / original_quantity
    else:
        factor = float(request.form['factor'])

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
            
            # Update ingredient quantity
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

@app.route('/delete_conversion/<int:conversion_id>', methods=['DELETE'])
def delete_conversion(conversion_id):
    """Deletes an ingredient-specific unit conversion."""
    ingredient_id = request.args.get('ingredient_id')
    view_name = request.args.get('view_name', 'pantry')
    
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM ingredient_conversions WHERE id = ?", (conversion_id,))
        conn.commit()
    except Exception as e:
        print(f"Error deleting conversion: {e}")
    finally:
        conn.close()

    # Re-render the edit form
    return edit_ingredient_form(int(ingredient_id))

@app.route('/add_conversion_manual', methods=['POST'])
def add_conversion_manual():
    """Adds a manual ingredient-specific unit conversion and returns the edit form."""
    ingredient_id = request.form['ingredient_id']
    from_unit = request.form['from_unit'].strip().lower()
    to_unit = request.form['to_unit']
    factor = float(request.form['factor'])
    view_name = request.form.get('view_name', 'pantry')

    conn = get_db_connection()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                (ingredient_id, from_unit, to_unit, factor)
            )
    except Exception as e:
        print(f"Error in add_conversion_manual: {e}")
    finally:
        conn.close()

    return edit_ingredient_form(int(ingredient_id))

@app.route('/add_new_ingredient_with_density', methods=['POST'])
def add_new_ingredient_with_density():
    """Adds a new ingredient with a specified density.

    This is used when a new ingredient is added with a mass or volume unit,
    requiring a density for future conversions.
    """
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
    """Starts a new cooking session for a selected meal.

    It calculates the required ingredients based on the portion size and
    checks them against the pantry inventory.
    """
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

            # Fetch available options (parent and children)
            options_raw = conn.execute("""
                SELECT id, name, quantity, base_unit 
                FROM ingredients 
                WHERE id = ? OR parent_id = ?
            """, (item['id'], item['id'])).fetchall()
            
            available_options = []
            for opt in options_raw:
                # Convert stock to display unit
                try:
                    stock_display = convert_units(opt['quantity'], opt['base_unit'], display_unit, opt['id'], conn=conn)
                    stock_text = f"{stock_display:.2f} {display_unit} available"
                except ValueError:
                    stock_text = f"{opt['quantity']:.2f} {opt['base_unit']} available (conversion error)"
                
                available_options.append({
                    "id": opt['id'],
                    "name": opt['name'],
                    "stock_text": stock_text,
                    "quantity_base": opt['quantity'],
                    "selected": opt['id'] == item['id']
                })

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
                "in_stock": item['pantry_quantity'] >= required_quantity_base,
                "available_options": available_options
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

    if 'HX-Request' in request.headers:
        return render_template('cooking_mode.html', meal=meal, portion=portion, recipe_items=recipe_items, missing_conversions=missing_conversions)
    return render_template('index.html', page_content=render_template('cooking_mode.html', meal=meal, portion=portion, recipe_items=recipe_items, missing_conversions=missing_conversions))


def get_ingredient_by_id(ingredient_id, view_name='pantry', for_editing=False):
    """Fetches a single ingredient by its ID, with display unit handling.

    Args:
        ingredient_id (int): The ID of the ingredient to fetch.
        view_name (str, optional): The view context, affecting the display unit.
            Defaults to 'pantry'.
        for_editing (bool, optional): If True, provides all possible units for
            editing forms. Defaults to False.

    Returns:
        dict or None: A dictionary of the ingredient's data, or None if not found.
    """
    conn = get_db_connection()
    query = f"""
        SELECT
            i.id, i.name, i.category, i.quantity, i.base_unit, i.base_unit_type, i.density_g_ml, i.parent_id, i.image_url,
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
        # Fetch ingredient-specific conversions
        item_dict['conversions'] = [dict(r) for r in conn.execute("SELECT * FROM ingredient_conversions WHERE ingredient_id = ?", (ingredient_id,)).fetchall()]
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
    """Updates the preferred display unit for an ingredient in a specific view."""
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
    """Fetches and renders a single ingredient item.

    Note: This might be deprecated by more specific rendering routes.
    """
    ingredient = get_ingredient_by_id(ing_id)
    return render_template('_ingredient_item.html', ingredient=ingredient)


@app.route('/edit_ingredient_form/<int:ing_id>')
def edit_ingredient_form(ing_id):
    """Renders the form for editing an ingredient."""
    view_name = request.args.get('view_name', 'pantry')
    ingredient = get_ingredient_by_id(ing_id, view_name, for_editing=True)
    categories = get_all_categories()
    
    conn = get_db_connection()
    potential_parents = conn.execute("SELECT id, name FROM ingredients WHERE id != ? AND parent_id IS NULL ORDER BY name", (ing_id,)).fetchall()
    conn.close()
    
    return render_template('_edit_ingredient_form.html', ingredient=ingredient, view_name=view_name, categories=categories, potential_parents=potential_parents)


@app.route('/edit_ingredient/<int:ing_id>', methods=['POST'])
def edit_ingredient(ing_id):
    """Handles the submission of the ingredient edit form.

    This route manages changes to an ingredient's properties and now
    handles density and optional custom conversions in a single step.
    """
    view_name = request.form.get('view_name', 'pantry')
    new_name = request.form.get('name', '').strip().lower()
    new_quantity_str = request.form.get('quantity', '0')
    new_unit = request.form.get('unit')
    new_category = request.form.get('category')
    parent_id = request.form.get('parent_id')
    density_g_ml_str = request.form.get('density_g_ml')
    
    # Optional manual conversion fields (mapped from template IDs to names)
    manual_from = request.form.get('manual_from_unit', '').strip().lower()
    manual_factor = request.form.get('manual_factor')
    manual_to = request.form.get('manual_to_unit')

    if not new_name or not new_unit:
        ingredient = get_ingredient_by_id(ing_id, view_name)
        return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

    conn = get_db_connection()
    try:
        with conn:
            # 1. Parse values
            new_quantity = parse_quantity(new_quantity_str)
            density_g_ml = float(density_g_ml_str) if (density_g_ml_str and density_g_ml_str.strip()) else None
            
            # 2. Update metadata and density first
            conn.execute(
                "UPDATE ingredients SET name = ?, category = ?, parent_id = ?, density_g_ml = ? WHERE id = ?",
                (new_name, new_category, int(parent_id) if parent_id else None, density_g_ml, ing_id)
            )

            # 3. Update quantity (smart convert_to_base now uses updated density/parent)
            quantity_in_base, final_base_unit, final_base_unit_type = convert_to_base(new_quantity, new_unit, ing_id, conn=conn)
            conn.execute(
                "UPDATE ingredients SET quantity = ?, base_unit = ?, base_unit_type = ? WHERE id = ?",
                (quantity_in_base, final_base_unit, final_base_unit_type, ing_id)
            )

            # 4. Save display unit preference
            conn.execute("""
                INSERT INTO ingredient_view_units (ingredient_id, view_name, unit) VALUES (?, ?, ?)
                ON CONFLICT(ingredient_id, view_name) DO UPDATE SET unit = excluded.unit
            """, (ing_id, view_name, new_unit))

            # 5. Optional manual conversion addition
            if manual_from and manual_factor and manual_to:
                conn.execute(
                    "INSERT OR REPLACE INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                    (ing_id, manual_from, manual_to, float(manual_factor))
                )

    except (ValueError, TypeError) as e:
        print(f"Error in edit_ingredient: {e}")
    finally:
        if conn: conn.close()

    ingredient = get_ingredient_by_id(ing_id, view_name)
    return render_template('_ingredient_item.html', ingredient=ingredient, show_edit_buttons=True, view_name=view_name)

@app.route('/update_ingredient_details/<int:ing_id>', methods=['POST'])
def update_ingredient_details(ing_id):
    """Updates ingredient details, including density.

    This route is used after a density prompt to update an ingredient's
    properties, including its name, quantity, unit, and density.
    """
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
    """Deletes an ingredient from the database.

    Also removes any references to the ingredient in meals.
    """
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


@app.route('/meal-plan/export')
def meal_plan_export():
    """Exports the current shopping list to JSON."""
    conn = get_db_connection()
    meal_plan = conn.execute("SELECT * FROM meal_plans WHERE name = 'default'").fetchone()
    if not meal_plan:
        conn.close()
        return jsonify({"error": "No meal plan found."}), 404

    meal_plan_id = meal_plan['id']
    shopping_list = generate_shopping_list(meal_plan_id)
    conn.close()

    return jsonify(shopping_list)


@app.route('/meal-plan/remove/<int:item_id>', methods=['DELETE'])
def remove_meal_plan_item(item_id):
    """Removes an item from the meal plan."""
    conn = get_db_connection()
    conn.execute("DELETE FROM meal_plan_items WHERE id = ?", (item_id,))
    conn.commit()

    # After removing, re-render ONLY the meal plan content.
    # To do this, we need to fetch the data required by the partial template.
    meal_plan = conn.execute("SELECT * FROM meal_plans WHERE name = 'default'").fetchone()
    meal_plan_id = meal_plan['id'] if meal_plan else 0

    # Fetch data needed for the template context
    meals = get_all_meals()
    meal_plan_items_raw = conn.execute("""
        SELECT
            mpi.id, mpi.multiplier, m.name as meal_name
        FROM meal_plan_items mpi
        JOIN meals m ON mpi.meal_id = m.id
        WHERE mpi.meal_plan_id = ?
    """, (meal_plan_id,)).fetchall()
    meal_plan_items = [dict(row) for row in meal_plan_items_raw]
    conn.close()

    shopping_list = generate_shopping_list(meal_plan_id)

    # Render the partial template with the updated context
    return render_template('_meal_plan_content.html', meals=meals, meal_plan_items=meal_plan_items, shopping_list=shopping_list)


@app.route('/meal-plan', methods=['GET', 'POST'])
def meal_plan():
    """Renders the meal planning page and handles adding meals to the plan."""
    conn = get_db_connection()

    # For simplicity, we'll use a single, default meal plan.
    # Check if a default meal plan exists, if not, create one.
    meal_plan = conn.execute("SELECT * FROM meal_plans WHERE name = 'default'").fetchone()
    if not meal_plan:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO meal_plans (name) VALUES ('default')")
        conn.commit()
        meal_plan_id = cursor.lastrowid
    else:
        meal_plan_id = meal_plan['id']

    # This block handles the form submission for adding a meal to the plan
    if request.method == 'POST':
        meal_id = request.form.get('meal_id')
        try:
            multiplier = float(request.form.get('multiplier', 1.0))
        except (ValueError, TypeError):
            multiplier = 1.0

        if meal_id:
            # Add the selected meal to the meal plan
            conn.execute(
                "INSERT INTO meal_plan_items (meal_plan_id, meal_id, multiplier) VALUES (?, ?, ?)",
                (meal_plan_id, meal_id, multiplier)
            )
            conn.commit()
        
        # After adding, re-render ONLY the content partial with the updated data.
        meals = get_all_meals()
        meal_plan_items_raw = conn.execute("""
            SELECT
                mpi.id, mpi.multiplier, m.name as meal_name
            FROM meal_plan_items mpi
            JOIN meals m ON mpi.meal_id = m.id
            WHERE mpi.meal_plan_id = ?
        """, (meal_plan_id,)).fetchall()
        meal_plan_items = [dict(row) for row in meal_plan_items_raw]
        conn.close()

        shopping_list = generate_shopping_list(meal_plan_id)
        
        return render_template('_meal_plan_content.html', meals=meals, meal_plan_items=meal_plan_items, shopping_list=shopping_list)

    # This block now only handles GET requests
    # Fetch all meals for the dropdown
    meals = get_all_meals()

    # Fetch the current meal plan items to display
    meal_plan_items_raw = conn.execute("""
        SELECT
            mpi.id, mpi.multiplier, m.name as meal_name
        FROM meal_plan_items mpi
        JOIN meals m ON mpi.meal_id = m.id
        WHERE mpi.meal_plan_id = ?
    """, (meal_plan_id,)).fetchall()
    meal_plan_items = [dict(row) for row in meal_plan_items_raw]
    conn.close()

    # Generate the shopping list
    shopping_list = generate_shopping_list(meal_plan_id)

    if 'HX-Request' in request.headers:
        # For HTMX GET requests (e.g., navigating from another page), render the full component
        return render_template('meal_plan.html', meals=meals, meal_plan_items=meal_plan_items, shopping_list=shopping_list)
    
    # For a full browser page load, render the index with the component
    return render_template('index.html', page_content=render_template('meal_plan.html', meals=meals, meal_plan_items=meal_plan_items, shopping_list=shopping_list))

def _process_recipe_ingredients_for_import(recipe_data, conn):
    """Processes recipe ingredients for import.

    This function matches ingredients from a recipe with existing pantry
    ingredients, and identifies conflicts for density and unit conversions.

    Args:
        recipe_data (dict): The recipe data parsed from the import source.
        conn (sqlite3.Connection): The database connection.

    Returns:
        dict: The processed recipe data with added conflict flags.
    """
    all_ingredients_raw = conn.execute("SELECT id, name, base_unit_type, base_unit FROM ingredients").fetchall()
    all_ingredients_map = {ing['name']: ing for ing in all_ingredients_raw}
    all_ingredient_names = list(all_ingredients_map.keys())

    for ingredient in recipe_data.get('ingredients', []):
        if not ingredient:
            continue
        ingredient_name = ingredient.get('name', '').lower()
        best_match_record = None

        # 1. Fuzzy match against existing ingredients
        if ingredient_name and all_ingredient_names:
            best_match_tuple = process.extractOne(ingredient_name, all_ingredient_names)
            if best_match_tuple and best_match_tuple[1] > 80:
                best_match_record = all_ingredients_map[best_match_tuple[0]]
                ingredient['suggestion_id'] = best_match_record['id']
            else:
                ingredient['suggestion_id'] = None
        else:
            ingredient['suggestion_id'] = None

        # 2. Check for unit conversion conflicts (e.g., recipe says "1 onion" but pantry has onions in "g")
        ingredient['needs_unit_conversion_prompt'] = False
        recipe_unit = (ingredient.get('unit') or '').strip().lower()
        # A "unit" recipe item for a pantry item tracked by mass/volume needs a conversion
        if best_match_record and (recipe_unit == 'unit' or not get_base_unit_type(recipe_unit)):
            pantry_base_type = best_match_record['base_unit_type']
            if pantry_base_type in ['mass', 'volume']:
                ingredient['needs_unit_conversion_prompt'] = True
                ingredient['pantry_base_unit'] = best_match_record['base_unit']

        # 3. Check if a density prompt will be needed for a new ingredient
        ingredient['needs_density_prompt'] = False
        if not ingredient['suggestion_id']:  # It's a potential new ingredient
            unit_type = get_base_unit_type(recipe_unit)
            if unit_type in ['mass', 'volume']:
                ingredient['needs_density_prompt'] = True

    return recipe_data


@app.route('/import_recipe_from_image', methods=['POST'])
def import_recipe_from_image_route():
    """Handles the import of a recipe from an uploaded image.

    This route saves the uploaded image, calls the importer service to
    extract recipe data, processes the ingredients for import, and
    renders the review page.
    """
    if 'recipe_image' not in request.files:
        return "No image file provided.", 400

    file = request.files['recipe_image']
    if file.filename == '':
        return "No selected file.", 400

    if file:
        filename = secure_filename(file.filename)
        upload_folder = os.path.join(app.root_path, 'static', 'uploads')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        image_path = os.path.join(upload_folder, filename)
        file.save(image_path)

        recipe_data = import_recipe_from_image(image_path)
        if not recipe_data:
            return "Could not parse recipe from image.", 500

        conn = get_db_connection()
        try:
            recipe_data = _process_recipe_ingredients_for_import(recipe_data, conn)
            all_ingredients_for_dropdown = conn.execute("SELECT id, name FROM ingredients ORDER BY name").fetchall()
        finally:
            conn.close()

        return render_template(
            'recipe_import_review.html',
            recipe_data=recipe_data,
            all_ingredients=all_ingredients_for_dropdown
        )

@app.route('/filter_meals', methods=['POST'])
def filter_meals():
    """Filters meals based on selected ingredients.

    Returns a list of meals that contain all of the selected ingredients.
    """
    ingredient_ids = request.form.getlist('ingredient_ids')
    if not ingredient_ids or 'any' in ingredient_ids:
        meals = get_all_meals()
        return render_template('_meals_list.html', meals=meals)

    conn = get_db_connection()
    
    placeholders = ','.join('?' for _ in ingredient_ids)
    query = f"""
        SELECT m.id, m.name
        FROM meals m
        JOIN meal_ingredients mi ON m.id = mi.meal_id
        WHERE mi.ingredient_id IN ({placeholders})
        GROUP BY m.id, m.name
        HAVING COUNT(DISTINCT mi.ingredient_id) = ?
    """
    
    params = ingredient_ids + [len(ingredient_ids)]
    meals = conn.execute(query, params).fetchall()
    
    conn.close()
    
    return render_template('_meals_list.html', meals=meals)


@app.route('/batch_add_ingredients', methods=['POST'])
def batch_add_ingredients():
    """Adds multiple ingredients to the pantry from a comma-separated list."""
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
    """Searches for ingredients for the unit converter tool."""
    query = request.form.get('ingredient_name', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5, scorer=fuzz.token_set_ratio)

        conn = get_db_connection()
        for name, score in matches:
            if score > 50:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
        conn.close()

    return render_template('_search_results_for_converter.html', ingredients=ingredients)


@app.route('/calculate_conversion', methods=['POST'])
def calculate_conversion():
    """Calculates a unit conversion for a given ingredient."""
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
    """Calculates the density of an ingredient in g/ml."""
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
    """Fetches all ingredients for a given meal.

    Args:
        meal_id (int): The ID of the meal.
        view_name (str, optional): The view context. Defaults to 'recipe'.

    Returns:
        list: A list of processed ingredient dictionaries for the meal.
    """
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
            item_dict['compatible_units'] = mass_units + volume_units + ['unit']
        elif item_dict['base_unit_type'] == 'volume':
            item_dict['compatible_units'] = volume_units + mass_units + ['unit']
        else: # count
            item_dict['compatible_units'] = ['unit'] + mass_units + volume_units

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
    """Renders the recipe editor page for a given meal."""
    conn = get_db_connection()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    conn.close()
    meal_ingredients = get_meal_ingredients(meal_id)
    if 'HX-Request' in request.headers:
        return render_template('recipe_editor.html', meal=meal, meal_ingredients=meal_ingredients)
    return render_template('index.html', page_content=render_template('recipe_editor.html', meal=meal, meal_ingredients=meal_ingredients))

@app.route('/update_instructions/<int:meal_id>', methods=['POST'])
def update_instructions(meal_id):
    """Updates the instructions for a given meal."""
    instructions = request.form.get('instructions')
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE meals SET instructions = ? WHERE id = ?", (instructions, meal_id))
    except Exception as e:
        print(f"Error updating instructions: {e}")
        return "Error updating instructions", 500
    finally:
        if conn: conn.close()
    return "", 204


@app.route('/add_ingredient_to_meal/<int:meal_id>', methods=['POST'])
def add_ingredient_to_meal(meal_id):
    """Adds an ingredient to a meal's recipe."""
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
    """Updates the display unit for an ingredient within a recipe view."""
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
    """Removes an ingredient from a meal's recipe."""
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
    """Searches for ingredients to add to a recipe."""
    query = request.form.get('q', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5, scorer=fuzz.token_set_ratio)

        conn = get_db_connection()
        for name, score in matches:
            if score > 50:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
        conn.close()

    return render_template('_search_results_for_recipe.html', ingredients=ingredients, meal_id=meal_id)

@app.route('/select_ingredient', methods=['POST'])
def select_ingredient():
    """Handles the selection of an ingredient from search results.

    This route updates the search input with the selected ingredient name
    and clears the search results.
    """
    ingredient_name = request.form['ingredient_name']
    meal_id = request.form['meal_id']
    # The main returned element replaces the search input.
    # The div with hx-swap-oob will be swapped "out of band", clearing the search results.
    return f'''<input id="ingredient-search-input" type="search" name="q" value="{ingredient_name}"
                   placeholder="Search for an ingredient to add..."
                   hx-post="/search_ingredients_for_recipe/{meal_id}"
                   hx-trigger="keyup changed delay:500ms, search"
                   hx-target="#search-results-for-recipe"
                   hx-swap="innerHTML">
               <div id="search-results-for-recipe" hx-swap-oob="true"></div>'''


@app.route('/meal/<int:meal_id>')
def meal_page(meal_id):
    """Renders the page for a single meal."""
    conn = get_db_connection()
    meal = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    conn.close()
    meal_ingredients = get_meal_ingredients(meal_id)
    if 'HX-Request' in request.headers:
        return render_template('meal.html', meal=meal, meal_ingredients=meal_ingredients)
    return render_template('index.html', page_content=render_template('meal.html', meal=meal, meal_ingredients=meal_ingredients))

@app.route('/search_ingredients_for_cooking', methods=['POST'])
def search_ingredients_for_cooking():
    """Searches for ingredients within the cooking session context."""
    query = request.form.get('q', '').strip().lower()
    ingredients = []
    if query:
        conn = get_db_connection()
        all_ingredients_raw = conn.execute("SELECT id, name FROM ingredients").fetchall()
        conn.close()

        all_ingredients_map = {ing['name']: ing['id'] for ing in all_ingredients_raw}
        matches = process.extract(query, all_ingredients_map.keys(), limit=5, scorer=fuzz.token_set_ratio)

        conn = get_db_connection()
        for name, score in matches:
            if score > 50:
                ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (all_ingredients_map[name],)).fetchone()
                ingredients.append(ingredient)
        conn.close()

    return render_template('_search_results_for_cooking.html', ingredients=ingredients)


@app.route('/add_ingredient_to_cooking_session', methods=['POST'])
def add_ingredient_to_cooking_session():
    """Adds an ingredient to the cooking session display."""
    ingredient_id = request.form['ingredient_id']
    quantity = request.form['quantity']
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    conn.close()
    return render_template('_cooking_session_ingredient.html', ingredient=ingredient, quantity=quantity)

@app.route('/update_pantry', methods=['POST'])
def update_pantry():
    """Updates the pantry by deducting the quantities of ingredients used in a cooking session."""
    # A list of strings like "ingredient_id_quantity_to_deduct" from extra additions
    ingredients_used = request.form.getlist('ingredient_used')
    # A list of recipe ingredient IDs that were checked
    recipe_items_used = request.form.getlist('recipe_items_used')

    if not ingredients_used and not recipe_items_used:
        return "Nothing to update."

    conn = get_db_connection()
    try:
        with conn: # Use a transaction
            # Process extra items added on the fly
            for item in ingredients_used:
                ingredient_id, quantity_to_deduct = item.split('_')
                conn.execute(
                    "UPDATE ingredients SET quantity = quantity - ? WHERE id = ?",
                    (float(quantity_to_deduct), int(ingredient_id))
                )
            
            # Process dynamic recipe items
            for recipe_ing_id in recipe_items_used:
                deduct_ing_id = request.form.get(f'ingredient_id_to_deduct_for_{recipe_ing_id}')
                deduct_qty_str = request.form.get(f'ingredient_qty_for_{recipe_ing_id}')
                deduct_unit = request.form.get(f'ingredient_unit_for_{recipe_ing_id}')
                
                if deduct_ing_id and deduct_qty_str and deduct_unit:
                    try:
                        deduct_qty = float(deduct_qty_str)
                        if deduct_qty > 0:
                            # Convert from the display unit back to the chosen ingredient's base unit
                            qty_in_base, _, _ = convert_to_base(deduct_qty, deduct_unit, int(deduct_ing_id), conn=conn)
                            conn.execute(
                                "UPDATE ingredients SET quantity = quantity - ? WHERE id = ?",
                                (qty_in_base, int(deduct_ing_id))
                            )
                    except ValueError as e:
                        print(f"Error converting dynamic recipe item {recipe_ing_id}: {e}")

        response = make_response()
        response.headers['HX-Redirect'] = '/'
        return response
    except Exception as e:
        print(f"Error updating pantry: {e}")
        return f"<h4>Error: {e}</h4><p>Could not update pantry.</p>"
    finally:
        if conn: conn.close()


@app.route('/import_recipe_process', methods=['POST'])
def import_recipe_process():
    """Processes a recipe from text input for import review."""
    recipe_text = request.form.get('recipe_text', '')
    if not recipe_text:
        return "No recipe text provided.", 400

    recipe_data = import_recipe_from_text(recipe_text)
    if not recipe_data:
        return "Could not parse recipe. Please check the format.", 500

    conn = get_db_connection()
    try:
        recipe_data = _process_recipe_ingredients_for_import(recipe_data, conn)
        all_ingredients_for_dropdown = conn.execute("SELECT id, name FROM ingredients ORDER BY name").fetchall()
    finally:
        conn.close()

    return render_template(
        'recipe_import_review.html',
        recipe_data=recipe_data,
        all_ingredients=all_ingredients_for_dropdown
    )

@app.route('/save_imported_recipe', methods=['POST'])
def save_imported_recipe():
    """Saves a new recipe from the import review page.

    This complex route handles creating a new meal, creating new ingredients
    (with or without density), associating existing ingredients, saving new
    unit conversions, and finally associating all ingredients with the new meal.
    """
    conn = get_db_connection()
    try:
        with conn:
            # 1. Create the new meal
            recipe_name = request.form.get('recipe_name')
            instructions = request.form.get('instructions')
            if not recipe_name:
                return "Recipe name is required.", 400

            cursor = conn.cursor()
            cursor.execute("INSERT INTO meals (name, instructions) VALUES (?, ?)", (recipe_name, instructions))
            meal_id = cursor.lastrowid

            # 2. Process ingredients
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
                    continue # Skip invalid quantities

                final_ingredient_id = None
                if ing_id_val.startswith('_new_'):
                    new_ing_name = ing_id_val[5:].strip().lower()
                    existing = conn.execute("SELECT id FROM ingredients WHERE name = ?", (new_ing_name,)).fetchone()
                    if existing:
                        final_ingredient_id = existing['id']
                    else:
                        # This is a new ingredient, check for density data
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
                    # Check for and save a submitted unit conversion factor
                    conversion_factor_str = request.form.get(f'unit_conversion_factor_{final_ingredient_id}')
                    if conversion_factor_str:
                        try:
                            factor = float(conversion_factor_str)
                            from_unit = request.form.get(f'unit_conversion_from_{final_ingredient_id}')
                            to_unit = request.form.get(f'unit_conversion_to_{final_ingredient_id}')

                            if from_unit and to_unit and factor > 0:
                                conn.execute(
                                    "INSERT OR REPLACE INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                                    (final_ingredient_id, from_unit, to_unit, factor)
                                )
                                conn.execute(
                                    "INSERT OR REPLACE INTO ingredient_conversions (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)",
                                    (final_ingredient_id, to_unit, from_unit, 1/factor)
                                )
                        except (ValueError, TypeError, ZeroDivisionError):
                            pass # Ignore invalid or zero factors

                # 3. Add to meal_ingredients
                if final_ingredient_id:
                    conn.execute(
                        "INSERT INTO meal_ingredients (meal_id, ingredient_id, quantity, unit) VALUES (?, ?, ?, ?)",
                        (meal_id, final_ingredient_id, quantity, unit)
                    )

        # Redirect to the new recipe's editor page
        response = make_response()
        response.headers['HX-Redirect'] = f'/recipe/{meal_id}'
        return response

    except Exception as e:
        print(f"Error saving imported recipe: {e}")
        return "Error saving recipe.", 500
    finally:
        if conn:
            conn.close()


@app.route('/recipes')
def recipes():
    """Renders the main recipe manager page."""
    meals = get_all_meals()
    ingredients_by_category = get_all_ingredients()
    return render_template('recipe_manager.html', meals=meals, ingredients_by_category=ingredients_by_category)


@app.route('/add_meal', methods=['POST'])
def add_meal():
    """Adds a new, empty meal."""
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


def generate_shopping_list(meal_plan_id):
    """Generates a shopping list for a given meal plan."""
    conn = get_db_connection()

    # Get all meal plan items
    meal_plan_items = conn.execute(
        "SELECT meal_id, multiplier FROM meal_plan_items WHERE meal_plan_id = ?",
        (meal_plan_id,)
    ).fetchall()

    required_ingredients = {}
    for item in meal_plan_items:
        meal_id = item['meal_id']
        multiplier = item['multiplier']

        # Get all ingredients for the meal
        meal_ingredients = conn.execute(
            "SELECT ingredient_id, quantity, unit FROM meal_ingredients WHERE meal_id = ?",
            (meal_id,)
        ).fetchall()

        for mi in meal_ingredients:
            ingredient_id = mi['ingredient_id']

            # Convert recipe quantity to base unit
            try:
                base_quantity, _, _ = convert_to_base(mi['quantity'], mi['unit'], ingredient_id, conn)
                required_quantity = base_quantity * multiplier

                if ingredient_id in required_ingredients:
                    required_ingredients[ingredient_id] += required_quantity
                else:
                    required_ingredients[ingredient_id] = required_quantity
            except ValueError as e:
                print(f"Skipping shopping list item for meal {meal_id}, ingredient {ingredient_id}: {e}")
                continue

    shopping_list = {}
    for ingredient_id, total_required in required_ingredients.items():
        # Get parent ingredient info
        ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
        if not ingredient: continue
        
        # 1. Start with parent stock
        total_available_in_parent_base = ingredient['quantity']
        
        # 2. Add all children stock
        children = conn.execute("SELECT id, quantity, base_unit FROM ingredients WHERE parent_id = ?", (ingredient_id,)).fetchall()
        for child in children:
            try:
                # Convert child's current stock to parent's base unit
                # This uses the new hierarchical lookup (child specific rule -> parent default -> density)
                child_qty_in_parent_base = convert_units(child['quantity'], child['base_unit'], ingredient['base_unit'], child['id'], conn=conn)
                total_available_in_parent_base += child_qty_in_parent_base
            except ValueError:
                # If conversion fails, ignore this specific child's contribution
                pass

        needed = total_required - total_available_in_parent_base
        if needed > 0:
            # Get display unit preference
            display_unit_row = conn.execute(
                "SELECT unit FROM ingredient_view_units WHERE ingredient_id = ? AND view_name = 'pantry'",
                (ingredient_id,)
            ).fetchone()
            display_unit = display_unit_row['unit'] if display_unit_row else ingredient['base_unit']

            # Convert needed quantity to display unit
            try:
                display_quantity = convert_units(needed, ingredient['base_unit'], display_unit, ingredient_id, conn)
            except ValueError:
                display_quantity = needed # Fallback to base if display unit fails

            category = ingredient['category']
            if category not in shopping_list:
                shopping_list[category] = []

            shopping_list[category].append({
                'name': ingredient['name'],
                'quantity': display_quantity,
                'unit': display_unit
            })

    conn.close()
    return shopping_list


@app.route('/data')
def data_view():
    """Renders a comprehensive data view table for ingredients and recipes."""
    conn = get_db_connection()
    
    # 1. Fetch Ingredients with Parent names and Child counts
    ingredients_raw = conn.execute("""
        SELECT 
            i.id, i.name, i.category, i.quantity, i.base_unit, i.base_unit_type, i.density_g_ml, i.parent_id, i.image_url,
            p.name as parent_name,
            (SELECT COUNT(*) FROM ingredients WHERE parent_id = i.id) as child_count
        FROM ingredients i
        LEFT JOIN ingredients p ON i.parent_id = p.id
        ORDER BY i.name
    """).fetchall()
    
    ingredients = []
    for row in ingredients_raw:
        item = dict(row)
        # Fetch custom conversions for this ingredient
        conversions = conn.execute("SELECT from_unit, to_unit, factor FROM ingredient_conversions WHERE ingredient_id = ?", (item['id'],)).fetchall()
        item['conversions'] = [dict(c) for c in conversions]
        ingredients.append(item)

    # 2. Fetch Meals with their ingredients
    meals_raw = conn.execute("SELECT id, name, instructions FROM meals ORDER BY name").fetchall()
    meals = []
    for row in meals_raw:
        meal = dict(row)
        # Fetch ingredients for this meal
        meal_ing_raw = conn.execute("""
            SELECT mi.quantity, mi.unit, i.name 
            FROM meal_ingredients mi
            JOIN ingredients i ON mi.ingredient_id = i.id
            WHERE mi.meal_id = ?
        """, (meal['id'],)).fetchall()
        meal['ingredients'] = [dict(mi) for mi in meal_ing_raw]
        meals.append(meal)

    conn.close()
    
    if 'HX-Request' in request.headers:
        return render_template('data_view.html', ingredients=ingredients, meals=meals)
    return render_template('index.html', page_content=render_template('data_view.html', ingredients=ingredients, meals=meals))

@app.route('/delete_meal/<int:meal_id>', methods=['DELETE'])
def delete_meal(meal_id):
    """Deletes a meal and all its associated recipe ingredients."""
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
