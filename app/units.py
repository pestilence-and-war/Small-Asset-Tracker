from app.database import get_db_connection

def get_base_unit_type(unit):
    """
    Determines if a unit is for mass, volume, or count.
    This is a simplified mapping.
    """
    # Mass
    if unit in ['g', 'kg', 'lb', 'oz']:
        return 'mass'
    # Volume
    if unit in ['ml', 'l', 'cup', 'tbsp', 'tsp', 'gallon', 'quart', 'pint']:
        return 'volume'
    # Count
    if unit in ['unit', 'units']:
        return 'count'
    return None

def get_base_unit(unit_type):
    """Returns the base unit for a given type."""
    if unit_type == 'mass':
        return 'g'
    if unit_type == 'volume':
        return 'ml'
    if unit_type == 'count':
        return 'unit'
    return None

def convert_to_base(quantity, unit, ingredient_id=None):
    """
    Converts a given quantity and unit to its base unit quantity.
    Returns (converted_quantity, base_unit, base_unit_type)
    """
    unit = unit.lower().strip()
    conn = get_db_connection()

    target_base_unit = None
    target_base_unit_type = None

    # If we are converting in the context of a specific ingredient, use its base unit as the target.
    if ingredient_id:
        ingredient = conn.execute("SELECT base_unit, base_unit_type FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
        if ingredient:
            target_base_unit = ingredient['base_unit']
            target_base_unit_type = ingredient['base_unit_type']

    # If there's no ingredient context, infer the base unit from the provided unit.
    if not target_base_unit:
        target_base_unit_type = get_base_unit_type(unit)
        if not target_base_unit_type:
            conn.close()
            raise ValueError(f"Unknown unit type for '{unit}'")
        target_base_unit = get_base_unit(target_base_unit_type)

    if unit == target_base_unit:
        conn.close()
        return (quantity, target_base_unit, target_base_unit_type)

    # First, try ingredient-specific conversions (e.g., cup of flour to grams)
    if ingredient_id:
        # Direct
        res = conn.execute(
            "SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?",
            (ingredient_id, unit, target_base_unit)
        ).fetchone()
        if res:
            conn.close()
            return (quantity * res['factor'], target_base_unit, target_base_unit_type)
        # Reverse
        res = conn.execute(
            "SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?",
            (ingredient_id, target_base_unit, unit)
        ).fetchone()
        if res:
            conn.close()
            return (quantity / res['factor'], target_base_unit, target_base_unit_type)

    # Second, try standard unit conversions
    # Direct
    res = conn.execute(
        "SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?",
        (unit, target_base_unit)
    ).fetchone()
    if res:
        conn.close()
        return (quantity * res['factor'], target_base_unit, target_base_unit_type)
    # Reverse
    res = conn.execute(
        "SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?",
        (target_base_unit, unit)
    ).fetchone()
    if res:
        conn.close()
        return (quantity / res['factor'], target_base_unit, target_base_unit_type)

    conn.close()
    raise ValueError(f"No conversion factor found for '{unit}' to '{target_base_unit}'")

def needs_conversion_prompt(unit, ingredient_id):
    """
    Checks if we need to prompt the user for a mass-to-volume conversion.
    This happens when a user enters a unit of a different type than the stored
    base unit type for an ingredient (e.g., adding 'cups' to 'flour' which is stored in 'g').
    """
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()

    if not ingredient:
        conn.close()
        return False

    current_base_type = ingredient['base_unit_type']
    new_unit_type = get_base_unit_type(unit)

    # If types are different and one is mass and one is volume, we need a conversion
    if current_base_type != new_unit_type and {current_base_type, new_unit_type} == {'mass', 'volume'}:
        # Before prompting, check if a conversion already exists
        base_unit = ingredient['base_unit']
        # Direct
        res = conn.execute(
            "SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?",
            (ingredient_id, unit, base_unit)
        ).fetchone()
        if res:
            conn.close()
            return False # Conversion exists
        # Reverse
        res = conn.execute(
            "SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?",
            (ingredient_id, base_unit, unit)
        ).fetchone()
        if res:
            conn.close()
            return False # Conversion exists

        conn.close()
        return True # Conversion needed

    conn.close()
    return False

def get_conversion_prompt_html(ingredient_id, original_quantity, original_unit, pending_quantity):
    """
    Generates HTML for a conversion prompt.
    `pending_quantity` is the amount in the base unit that we couldn't convert.
    """
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    conn.close()

    if not ingredient:
        return "Error: Ingredient not found."

    return f"""
    <div id="conversion-prompt" class="conversion-prompt">
        <h4>Conversion Needed</h4>
        <p>How many grams are in 1 {original_unit} of {ingredient['name']}?</p>
        <form hx-post="/add_conversion" hx-target="#ingredient-list-container" hx-swap="innerHTML">
            <input type="hidden" name="ingredient_id" value="{ingredient_id}">
            <input type="hidden" name="from_unit" value="{original_unit}">
            <input type="hidden" name="to_unit" value="{ingredient['base_unit']}">
            <input type="hidden" name="quantity_to_add" value="{original_quantity}">
            <input type="hidden" name="unit_to_add" value="{original_unit}">

            1 {original_unit} = <input type="number" name="factor" step="any" required> {ingredient['base_unit']}
            <button type="submit">Save & Add</button>
        </form>
    </div>
    """

def get_new_ingredient_conversion_prompt_html(ingredient_name, original_quantity, original_unit):
    """
    Generates HTML for a conversion prompt for a NEW ingredient.
    """
    # For new ingredients, we standardize on 'g' as the base unit for anything that needs a density conversion.
    to_unit = 'g'

    return f"""
    <div id="conversion-prompt" class="conversion-prompt">
        <h4>New Ingredient: Density Needed</h4>
        <p>You're adding '{ingredient_name}' with a volume unit ('{original_unit}'). To store it accurately, please provide its density.</p>
        <p>How many grams (g) are in 1 {original_unit} of {ingredient_name}?</p>
        <form hx-post="/add_new_ingredient_with_conversion" hx-target="#ingredient-list-container" hx-swap="innerHTML">
            <input type="hidden" name="ingredient_name" value="{ingredient_name}">
            <input type="hidden" name="original_quantity" value="{original_quantity}">
            <input type="hidden" name="original_unit" value="{original_unit}">
            <input type="hidden" name="to_unit" value="{to_unit}">

            1 {original_unit} = <input type="number" name="factor" step="any" required> {to_unit}
            <button type="submit">Save & Add Ingredient</button>
        </form>
    </div>
    """
