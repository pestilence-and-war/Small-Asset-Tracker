from app.database import get_db_connection
import re

def parse_quantity(quantity_str):
    """
    Parses a quantity string that can be a decimal, a fraction, or a mixed number.
    e.g., "1.5", "1/2", "1 1/2"
    """
    if not isinstance(quantity_str, str):
        return float(quantity_str)

    quantity_str = quantity_str.strip()

    # Check for mixed number, e.g., "1 1/2"
    if ' ' in quantity_str:
        parts = quantity_str.split(' ')
        if len(parts) == 2:
            try:
                whole_num = float(parts[0])
                fraction_parts = parts[1].split('/')
                if len(fraction_parts) == 2:
                    numerator = float(fraction_parts[0])
                    denominator = float(fraction_parts[1])
                    if denominator == 0:
                        raise ValueError("Denominator cannot be zero.")
                    return whole_num + (numerator / denominator)
            except (ValueError, IndexError):
                raise ValueError(f"Invalid mixed number format: '{quantity_str}'")

    # Check for a simple fraction, e.g., "1/2"
    if '/' in quantity_str:
        fraction_parts = quantity_str.split('/')
        if len(fraction_parts) == 2:
            try:
                numerator = float(fraction_parts[0])
                denominator = float(fraction_parts[1])
                if denominator == 0:
                    raise ValueError("Denominator cannot be zero.")
                return numerator / denominator
            except ValueError:
                raise ValueError(f"Invalid fraction format: '{quantity_str}'")

    # Otherwise, try to convert to float directly
    try:
        return float(quantity_str)
    except ValueError:
        raise ValueError(f"Could not parse quantity: '{quantity_str}'")

def get_base_unit_type(unit):
    """
    Determines if a unit is for mass, volume, or count.
    This is a simplified mapping.
    """
    # Mass
    if unit in ['g', 'kg', 'lb', 'oz']:
        return 'mass'
    # Volume
    if unit in ['ml', 'l', 'cup', 'tbsp', 'tsp', 'gallon', 'quart', 'pint', 'teaspoon', 'tablespoon', 'cc']:
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

    ingredient = None
    if ingredient_id:
        ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()

    source_unit_type = get_base_unit_type(unit)
    target_base_unit = ingredient['base_unit'] if ingredient else get_base_unit(source_unit_type)
    target_base_unit_type = ingredient['base_unit_type'] if ingredient else source_unit_type

    if not source_unit_type:
        conn.close()
        raise ValueError(f"Unknown unit type for '{unit}'")
    if not target_base_unit_type:
        conn.close()
        raise ValueError(f"Could not determine target unit type.")

    if unit == target_base_unit:
        conn.close()
        return (quantity, target_base_unit, target_base_unit_type)

    # Case 1: Same unit type (e.g., mass to mass, volume to volume)
    if source_unit_type == target_base_unit_type:
        # Direct conversion
        res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, target_base_unit)).fetchone()
        if res:
            conn.close()
            return (quantity * res['factor'], target_base_unit, target_base_unit_type)
        # Reverse conversion
        res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_base_unit, unit)).fetchone()
        if res:
            conn.close()
            return (quantity / res['factor'], target_base_unit, target_base_unit_type)

    # Case 2: Different unit types (mass to volume or volume to mass)
    if source_unit_type != target_base_unit_type and {source_unit_type, target_base_unit_type} == {'mass', 'volume'}:
        if not ingredient or not ingredient['density_g_ml']:
            conn.close()
            # This is the error that the user was seeing.
            raise ValueError(f"Cannot convert between mass and volume for '{ingredient['name'] if ingredient else 'this ingredient'}' without a density.")

        density = ingredient['density_g_ml']

        # Path: Source -> ml -> g -> Target Base Unit
        quantity_in_ml = 0

        # Step 1: Convert source unit to ml
        if source_unit_type == 'volume':
            if unit == 'ml':
                quantity_in_ml = quantity
            else:
                res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'ml'", (unit,)).fetchone()
                if not res:
                    conn.close()
                    raise ValueError(f"No standard conversion factor found for '{unit}' to 'ml'")
                quantity_in_ml = quantity * res['factor']
        elif source_unit_type == 'mass': # We need to get to ml via g and density
             # First convert to 'g'
            quantity_in_g = 0
            if unit == 'g':
                quantity_in_g = quantity
            else:
                res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'g'", (unit,)).fetchone()
                if not res:
                    conn.close()
                    raise ValueError(f"No standard conversion factor found for '{unit}' to 'g'")
                quantity_in_g = quantity * res['factor']
            quantity_in_ml = quantity_in_g / density

        # At this point, we have quantity_in_ml. Now convert to the target base unit.
        if target_base_unit_type == 'volume': # Target is ml
             conn.close()
             return (quantity_in_ml, 'ml', 'volume')
        elif target_base_unit_type == 'mass': # Target is g
            quantity_in_g = quantity_in_ml * density
            conn.close()
            return (quantity_in_g, 'g', 'mass')

    # Fallback for other cases, like ingredient-specific non-density conversions
    if ingredient_id:
        res = conn.execute("SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?", (ingredient_id, unit, target_base_unit)).fetchone()
        if res:
            conn.close()
            return (quantity * res['factor'], target_base_unit, target_base_unit_type)
        res = conn.execute("SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?", (ingredient_id, target_base_unit, unit)).fetchone()
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
    Generates HTML for a density prompt for a NEW ingredient that has mass or volume.
    """
    return f"""
    <div id="conversion-prompt" class="conversion-prompt">
        <h4>New Ingredient: Density Needed</h4>
        <p>To allow for conversions between mass and volume (e.g., cups to grams), please provide the density for <strong>{ingredient_name}</strong>.</p>
        <p class="small-text">Don't know the density in g/ml? <button type="button" class="link-button" onclick="openModalAndTab('Density')">Calculate it here</button>.</p>
        <form hx-post="/add_new_ingredient_with_density" hx-target="#ingredient-list-container" hx-swap="innerHTML" hx-on:htmx:after-request="this.closest('#conversion-prompt').remove()">
            <input type="hidden" name="ingredient_name" value="{ingredient_name}">
            <input type="hidden" name="original_quantity" value="{original_quantity}">
            <input type="hidden" name="original_unit" value="{original_unit}">

            <label for="density">Density (grams per milliliter):</label>
            <input type="number" name="density_g_ml" id="density" step="any" required placeholder="e.g., 1 for water, 0.53 for flour">
            <button type="submit">Save & Add Ingredient</button>
        </form>
        <p class="small-text">Why is this needed? The application stores all convertible ingredients by mass (grams) for accuracy. Providing a density (g/mL) allows the system to correctly handle both weight and volume units for '{ingredient_name}' in the future.</p>
    </div>
    """

def format_fraction(num):
    """
    Converts a float to a string, including common cooking fractions.
    e.g., 1.5 -> "1 1/2", 0.25 -> "1/4"
    """
    if num is None:
        return ""
    if num == 0:
        return "0"

    integer_part = int(num)
    decimal_part = num - integer_part

    # Common fractions and their decimal equivalents
    fractions = {
        1/8: "1/8", 1/4: "1/4", 1/3: "1/3", 1/2: "1/2",
        2/3: "2/3", 3/4: "3/4",
    }

    # Find the closest fraction within a small tolerance
    closest_fraction = ""
    min_diff = float('inf')
    for frac_val, frac_str in fractions.items():
        diff = abs(decimal_part - frac_val)
        if diff < 0.01: # Tolerance for floating point inaccuracies
            if diff < min_diff:
                min_diff = diff
                closest_fraction = frac_str

    # Format the final string
    integer_str = str(integer_part) if integer_part > 0 else ""
    if closest_fraction:
        if integer_str:
            return f"{integer_str} {closest_fraction}"
        else:
            return closest_fraction
    else:
        # If no common fraction is found, round to 2 decimal places
        return f"{num:.2f}".rstrip('0').rstrip('.')


def convert_from_base(base_quantity, base_unit, density_g_ml=None):
    """
    Converts a quantity from its base unit (g, ml, unit) to a more
    human-readable format for recipes.
    """
    if base_unit == 'unit':
        return f"{format_fraction(base_quantity)} {base_unit}"
    if base_quantity == 0:
        return f"0 {base_unit}"

    # Standard volume units from largest to smallest for intelligent selection
    preferred_units = ['gallon', 'quart', 'pint', 'cup', 'tbsp', 'tsp']
    quantity_in_ml = 0

    if base_unit == 'ml':
        quantity_in_ml = base_quantity
    elif base_unit == 'g':
        if not density_g_ml or density_g_ml == 0:
            # Cannot convert to volume, so return in grams
            return f"{base_quantity:.2f} g".rstrip('0').rstrip('.')
        quantity_in_ml = base_quantity / density_g_ml
    else:
        return f"{base_quantity} {base_unit}" # Should not happen for mass/volume

    conn = get_db_connection()
    try:
        # Special handling for cups, as it's very common in recipes
        cup_factor = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = 'cup' AND to_unit = 'ml'").fetchone()['factor']
        quantity_in_cups = quantity_in_ml / cup_factor
        if 0.25 <= quantity_in_cups < 4:
             return f"{format_fraction(quantity_in_cups)} cup"

        # General handling for other units
        for unit in preferred_units:
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'ml'", (unit,)).fetchone()
            if res:
                factor = res['factor']
                converted_quantity = quantity_in_ml / factor
                if converted_quantity >= 1: # Use this unit if it's at least 1
                    formatted_qty = format_fraction(converted_quantity)
                    return f"{formatted_qty} {unit}"

        # Fallback for very small quantities
        if quantity_in_cups > 0:
            return f"{format_fraction(quantity_in_cups)} cup"

        # If the quantity is too small for even a tsp, return in ml
        return f"{quantity_in_ml:.2f} ml".rstrip('0').rstrip('.')
    finally:
        conn.close()

def convert_units(quantity, from_unit, to_unit, ingredient_id=None):
    """
    A general-purpose function to convert between any two units.
    """
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    if from_unit == to_unit:
        return quantity

    # Step 1: Convert the initial quantity to its base unit (g or ml)
    base_quantity, base_unit, base_unit_type = convert_to_base(quantity, from_unit, ingredient_id)

    to_unit_type = get_base_unit_type(to_unit)

    if not to_unit_type:
        raise ValueError(f"Unknown unit type for '{to_unit}'")

    conn = get_db_connection()
    try:
        # Case 1: Target unit is the same type as the base unit (e.g., g -> oz, ml -> cup)
        if to_unit_type == base_unit_type:
            if to_unit == base_unit:
                return base_quantity
            # Find a conversion factor
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (base_unit, to_unit)).fetchone()
            if res:
                return base_quantity * res['factor']
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (to_unit, base_unit)).fetchone()
            if res:
                return base_quantity / res['factor']

        # Case 2: Target unit is a different type (mass <-> volume)
        elif {to_unit_type, base_unit_type} == {'mass', 'volume'}:
            ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
            if not ingredient or not ingredient['density_g_ml']:
                raise ValueError(f"Density required to convert between {base_unit_type} and {to_unit_type} for this ingredient.")
            density = ingredient['density_g_ml']

            # Path: base_unit -> ml -> to_unit
            quantity_in_ml = 0
            if base_unit_type == 'volume': # base_unit is ml
                quantity_in_ml = base_quantity
            elif base_unit_type == 'mass': # base_unit is g
                quantity_in_ml = base_quantity / density

            # Now we have the quantity in ml, convert it to the to_unit
            if to_unit_type == 'volume':
                if to_unit == 'ml':
                    return quantity_in_ml
                res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'ml'", (to_unit,)).fetchone()
                if res:
                    return quantity_in_ml / res['factor']
            elif to_unit_type == 'mass':
                quantity_in_g = quantity_in_ml * density
                if to_unit == 'g':
                    return quantity_in_g
                res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'g'", (to_unit,)).fetchone()
                if res:
                    return quantity_in_g / res['factor']

        raise ValueError(f"Could not find a conversion path from '{from_unit}' to '{to_unit}'")

    finally:
        conn.close()
