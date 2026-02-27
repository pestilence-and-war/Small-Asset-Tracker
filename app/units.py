from app.database import get_db_connection
import re


def parse_quantity(quantity_str):
    """Parses a quantity string into a float.

    The string can be a decimal, a fraction, or a mixed number.
    For example: "1.5", "1/2", "1 1/2".

    Args:
        quantity_str (str or float): The string to parse. If a float is passed,
            it will be returned as is.

    Returns:
        float: The parsed quantity as a float.

    Raises:
        ValueError: If the string format is invalid.
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
    """Determines if a unit is for mass, volume, or count.

    This is a simplified mapping based on common cooking units.

    Args:
        unit (str): The unit to classify (e.g., 'g', 'ml', 'cup').

    Returns:
        str or None: The type of unit ('mass', 'volume', 'count'), or None if
            the unit is not recognized.
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
    """Returns the base unit for a given unit type.

    Args:
        unit_type (str): The type of unit ('mass', 'volume', 'count').

    Returns:
        str or None: The base unit ('g', 'ml', 'unit'), or None if the type
            is not recognized.
    """
    if unit_type == 'mass':
        return 'g'
    if unit_type == 'volume':
        return 'ml'
    if unit_type == 'count':
        return 'unit'
    return None


def convert_to_base(quantity, unit, ingredient_id=None, density_g_ml=None, conn=None):
    """Converts a given quantity and unit to its base unit quantity.

    The base units are 'g' for mass, 'ml' for volume, and 'unit' for count.
    The conversion can be direct (e.g., 'kg' to 'g'), or based on an
    ingredient's density (e.g., 'cup' of flour to 'g').

    Args:
        quantity (float): The quantity to convert.
        unit (str): The unit of the quantity.
        ingredient_id (int, optional): The ID of the ingredient, used for
            density-based conversions. Defaults to None.
        density_g_ml (float, optional): A provided density value to use
            if ingredient_id is not provided. Defaults to None.
        conn (sqlite3.Connection, optional): The database connection. If not
            provided, a new one will be created. Defaults to None.

    Returns:
        tuple: A tuple containing:
            - float: The converted quantity.
            - str: The base unit.
            - str: The type of the base unit.

    Raises:
        ValueError: If the conversion cannot be performed.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        unit = unit.lower().strip()

        ingredient = None
        if ingredient_id:
            ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()

        source_unit_type = get_base_unit_type(unit)
        target_base_unit = ingredient['base_unit'] if ingredient else get_base_unit(source_unit_type)
        target_base_unit_type = ingredient['base_unit_type'] if ingredient else source_unit_type

        if not source_unit_type:
            raise ValueError(f"Unknown unit type for '{unit}'")
        if not target_base_unit_type:
            raise ValueError(f"Could not determine target unit type.")

        if unit == target_base_unit:
            return (quantity, target_base_unit, target_base_unit_type)

        # Case 1: Same unit type (e.g., mass to mass, volume to volume)
        if source_unit_type == target_base_unit_type:
            # Direct conversion
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, target_base_unit)).fetchone()
            if res:
                return (quantity * res['factor'], target_base_unit, target_base_unit_type)
            # Reverse conversion
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_base_unit, unit)).fetchone()
            if res:
                return (quantity / res['factor'], target_base_unit, target_base_unit_type)

        # Case 2: Different unit types (mass to volume or volume to mass)
        if source_unit_type != target_base_unit_type and {source_unit_type, target_base_unit_type} == {'mass', 'volume'}:
            density = density_g_ml
            if ingredient and ingredient['density_g_ml']:
                density = ingredient['density_g_ml']

            if not density:
                # This is the error that the user was seeing.
                raise ValueError(f"Cannot convert between mass and volume for '{ingredient['name'] if ingredient else 'this ingredient'}' without a density.")

            # Path: Source -> ml -> g -> Target Base Unit
            quantity_in_ml = 0

            # Step 1: Convert source unit to ml
            if source_unit_type == 'volume':
                if unit == 'ml':
                    quantity_in_ml = quantity
                else:
                    res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'ml'", (unit,)).fetchone()
                    if not res:
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
                        raise ValueError(f"No standard conversion factor found for '{unit}' to 'g'")
                    quantity_in_g = quantity * res['factor']
                quantity_in_ml = quantity_in_g / density

            # At this point, we have quantity_in_ml. Now convert to the target base unit.
            if target_base_unit_type == 'volume': # Target is ml
                 return (quantity_in_ml, 'ml', 'volume')
            elif target_base_unit_type == 'mass': # Target is g
                quantity_in_g = quantity_in_ml * density
                return (quantity_in_g, 'g', 'mass')

        # Fallback for other cases, like ingredient-specific non-density conversions
        if ingredient_id:
            res = conn.execute("SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?", (ingredient_id, unit, target_base_unit)).fetchone()
            if res:
                return (quantity * res['factor'], target_base_unit, target_base_unit_type)
            res = conn.execute("SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ? AND to_unit = ?", (ingredient_id, target_base_unit, unit)).fetchone()
            if res:
                return (quantity / res['factor'], target_base_unit, target_base_unit_type)

        raise ValueError(f"No conversion factor found for '{unit}' to '{target_base_unit}'")
    finally:
        if close_conn and conn:
            conn.close()


def needs_conversion_prompt(unit, ingredient_id, conn=None):
    """Checks if a mass-to-volume conversion prompt is needed.

    This is required when a user enters a unit of a different type than the
    ingredient's stored base unit (e.g., adding 'cups' to 'flour' which is
    stored in 'g'), and the density is not known.

    Args:
        unit (str): The unit entered by the user.
        ingredient_id (int): The ID of the ingredient.
        conn (sqlite3.Connection, optional): The database connection. If not
            provided, a new one will be created. Defaults to None.

    Returns:
        bool: True if a prompt is needed, False otherwise.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()

        if not ingredient:
            return False

        current_base_type = ingredient['base_unit_type']
        new_unit_type = get_base_unit_type(unit)

        # If types are different (mass vs volume), a conversion is needed.
        if current_base_type != new_unit_type and {current_base_type, new_unit_type} == {'mass', 'volume'}:
            # A prompt is needed only if the density is not already known.
            if ingredient['density_g_ml'] and ingredient['density_g_ml'] > 0:
                return False  # Density exists, no prompt needed.
            else:
                return True   # No density, prompt is needed.

        return False
    finally:
        if close_conn and conn:
            conn.close()


def get_conversion_prompt_html(ingredient_id, original_quantity, original_unit, pending_quantity):
    """Generates HTML for a conversion prompt.

    Args:
        ingredient_id (int): The ID of the ingredient requiring conversion.
        original_quantity (float): The original quantity entered by the user.
        original_unit (str): The original unit entered by the user.
        pending_quantity (float): The amount in the base unit that could not
            be converted.

    Returns:
        str: The HTML for the conversion prompt.
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
    """Generates HTML for a density prompt for a new ingredient.

    Args:
        ingredient_name (str): The name of the new ingredient.
        original_quantity (float): The original quantity entered by the user.
        original_unit (str): The original unit entered by the user.

    Returns:
        str: The HTML for the density prompt.
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
    """Converts a float to a string, including common cooking fractions.

    For example, 1.5 becomes "1 1/2", and 0.25 becomes "1/4".

    Args:
        num (float or None): The number to format.

    Returns:
        str: The formatted string, or an empty string if num is None.
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



def convert_from_base(base_quantity, base_unit, density_g_ml=None, conn=None):
    """Converts a quantity from its base unit to a human-readable format.

    This function attempts to convert a base unit quantity (g, ml, or unit)
    into a more convenient unit for display in recipes (e.g., 'cup', 'tbsp').

    Args:
        base_quantity (float): The quantity in the base unit.
        base_unit (str): The base unit ('g', 'ml', 'unit').
        density_g_ml (float, optional): The density of the ingredient in g/ml,
            required for mass-to-volume conversions. Defaults to None.
        conn (sqlite3.Connection, optional): The database connection. If not
            provided, a new one will be created. Defaults to None.

    Returns:
        str: A formatted string representing the converted quantity and unit.
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

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

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
        if close_conn and conn:
            conn.close()


def convert_units(quantity, from_unit, to_unit, ingredient_id=None, conn=None):
    """A general-purpose function to convert between any two units.

    This function leverages `convert_to_base` to first convert the source
    quantity to its base unit, and then converts it to the target unit.

    Args:
        quantity (float): The quantity to convert.
        from_unit (str): The starting unit.
        to_unit (str): The target unit.
        ingredient_id (int, optional): The ID of the ingredient, required for
            conversions between mass and volume. Defaults to None.
        conn (sqlite3.Connection, optional): The database connection. If not
            provided, a new one will be created. Defaults to None.

    Returns:
        float: The converted quantity.

    Raises:
        ValueError: If a conversion path cannot be found.
    """
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    if from_unit == to_unit:
        return quantity

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        # Step 1: Convert the initial quantity to its base unit (g or ml)
        base_quantity, base_unit, base_unit_type = convert_to_base(quantity, from_unit, ingredient_id, conn=conn)

        to_unit_type = get_base_unit_type(to_unit)

        if not to_unit_type:
            raise ValueError(f"Unknown unit type for '{to_unit}'")

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
        if close_conn and conn:
            conn.close()
