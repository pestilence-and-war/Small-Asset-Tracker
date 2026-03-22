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


def parse_quantity_and_unit(quantity_str):
    """Parses a quantity string like '500 g', '1.5 cup diced', or '10oz' into a (quantity, unit) tuple.

    Args:
        quantity_str (str): The string to parse.

    Returns:
        tuple: (float, str) or (None, None) if parsing fails.
    """
    if not quantity_str:
        return None, None

    # Regex to capture the numeric/fractional part and the remaining part as the unit
    match = re.search(r"^([\d\s./]+)\s*(.*)$", quantity_str.strip())
    if match:
        qty_part = match.group(1).strip()
        unit_part = match.group(2).strip().lower()
        try:
            qty = parse_quantity(qty_part)
            return qty, unit_part
        except ValueError:
            pass
    return None, None


def get_base_unit_type(unit):
    """Determines if a unit is for mass, volume, or count.

    This handles simple units ('g', 'ml') and preparation units ('cup diced').

    Args:
        unit (str): The unit to classify (e.g., 'g', 'ml', 'cup diced').

    Returns:
        str or None: The type of unit ('mass', 'volume', 'count'), or None if
            the unit is not recognized.
    """
    if not unit: return None
    
    # Check for prefix match in volume/mass
    # This allows 'cup diced' to be recognized as 'volume'
    # and 'oz chopped' to be recognized as 'mass'
    
    # Mass
    for m_unit in ['g', 'kg', 'lb', 'oz']:
        if unit == m_unit or unit.startswith(m_unit + ' '):
            return 'mass'
    # Volume
    for v_unit in ['ml', 'l', 'cup', 'tbsp', 'tsp', 'gallon', 'quart', 'pint', 'teaspoon', 'tablespoon', 'cc', 'fl oz', 'fl.oz', 'floz']:
        if unit == v_unit or unit.startswith(v_unit + ' '):
            return 'volume'
    # Count
    for c_unit in ['unit', 'units', 'ea', 'each', 'pkg', 'package', 'can', 'bottle', 'box', 'piece', 'slice']:
        if unit == c_unit or unit.startswith(c_unit + ' '):
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


def convert_to_base(quantity, unit, ingredient_id=None, density_g_ml=None, conn=None, skip_hierarchical=False, last_unit=None):
    """Converts a given quantity and unit to its base unit quantity.

    Args:
        quantity (float): The quantity to convert.
        unit (str): The unit of the quantity.
        ingredient_id (int, optional): The ID of the ingredient.
        density_g_ml (float, optional): Density to use if ingredient_id is None.
        conn (sqlite3.Connection, optional): Database connection.
        skip_hierarchical (bool, optional): If True, skips parent/child fallback.
        last_unit (str, optional): The unit we just converted from, to prevent loops.

    Returns:
        tuple: (float: quantity, str: base_unit, str: base_unit_type)
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        unit = unit.lower().strip()
        ingredient = None
        parent_id = None
        
        if ingredient_id:
            ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
            if ingredient:
                parent_id = ingredient['parent_id']

        # Determine actual density early for all conversion tiers
        actual_density = density_g_ml
        if ingredient and ingredient['density_g_ml']:
            actual_density = ingredient['density_g_ml']
        elif parent_id:
            parent = conn.execute("SELECT density_g_ml FROM ingredients WHERE id = ?", (parent_id,)).fetchone()
            if parent: actual_density = parent['density_g_ml']

        source_unit_type = get_base_unit_type(unit)
        target_base_unit = ingredient['base_unit'] if ingredient else get_base_unit(source_unit_type)
        target_base_unit_type = ingredient['base_unit_type'] if ingredient else source_unit_type

        if not source_unit_type or not target_base_unit_type:
            raise ValueError(f"Unknown unit type for '{unit}' or target.")

        if unit == target_base_unit:
            return (quantity, target_base_unit, target_base_unit_type)

        # 1. Check conversion for this specific ingredient (Highest Priority)
        if ingredient_id:
            # Look for ANY custom rule for this unit
            # Forward: unit -> something
            res = conn.execute("SELECT factor, to_unit FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ?", (ingredient_id, unit)).fetchone()
            if res and res['to_unit'] != last_unit:
                if res['to_unit'] == target_base_unit:
                    return (quantity * res['factor'], target_base_unit, target_base_unit_type)
                else:
                    # Bridge: Custom Unit -> Other Unit (e.g., pkg -> oz)
                    qty_in_other = quantity * res['factor']
                    return convert_to_base(qty_in_other, res['to_unit'], ingredient_id=ingredient_id, density_g_ml=actual_density, conn=conn, skip_hierarchical=True, last_unit=unit)

            # Reciprocal: something -> unit
            res = conn.execute("SELECT factor, from_unit FROM ingredient_conversions WHERE ingredient_id = ? AND to_unit = ?", (ingredient_id, unit)).fetchone()
            if res and res['factor'] != 0 and res['from_unit'] != last_unit:
                if res['from_unit'] == target_base_unit:
                    return (quantity / res['factor'], target_base_unit, target_base_unit_type)
                else:
                    # Bridge: unit -> other (reciprocal)
                    qty_in_other = quantity / res['factor']
                    return convert_to_base(qty_in_other, res['from_unit'], ingredient_id=ingredient_id, density_g_ml=actual_density, conn=conn, skip_hierarchical=True, last_unit=unit)

        # 2. Check Standard Conversions (Same type: mass->mass, vol->vol)
        if source_unit_type == target_base_unit_type:
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, target_base_unit)).fetchone()
            if res: return (quantity * res['factor'], target_base_unit, target_base_unit_type)
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_base_unit, unit)).fetchone()
            if res: return (quantity / res['factor'], target_base_unit, target_base_unit_type)

        # 3. Check Mass <-> Volume using Density
        if {source_unit_type, target_base_unit_type} == {'mass', 'volume'}:
            if actual_density:
                std_source_base = get_base_unit(source_unit_type)
                qty_in_std_base = quantity
                if unit != std_source_base:
                    # Convert to standard base (g or ml) for density math
                    res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, std_source_base)).fetchone()
                    if res: qty_in_std_base = quantity * res['factor']
                    else:
                        res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (std_source_base, unit)).fetchone()
                        if res: qty_in_std_base = quantity / res['factor']
                
                qty_in_target_std_base = qty_in_std_base / actual_density if source_unit_type == 'mass' else qty_in_std_base * actual_density
                target_std_base = get_base_unit(target_base_unit_type)

                final_qty = qty_in_target_std_base
                if target_base_unit != target_std_base:
                    res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_std_base, target_base_unit)).fetchone()
                    if res: final_qty = qty_in_target_std_base * res['factor']
                    else:
                        res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_base_unit, target_std_base)).fetchone()
                        if res: final_qty = qty_in_target_std_base / res['factor']
                
                return (final_qty, target_base_unit, target_base_unit_type)

        # 4. Hierarchical Fallbacks (Inherit Parent rules OR borrow from Children)
        if ingredient_id and not skip_hierarchical:
            # Look Upward (If child, check parent)
            if parent_id:
                try:
                    return convert_to_base(quantity, unit, ingredient_id=parent_id, density_g_ml=actual_density, conn=conn, skip_hierarchical=True)
                except ValueError: pass
            
            # Look Downward (If parent, check children for a representative factor)
            children = conn.execute("SELECT id FROM ingredients WHERE parent_id = ?", (ingredient_id,)).fetchall()
            for child in children:
                try:
                    child_qty_in_base, child_base, _ = convert_to_base(quantity, unit, ingredient_id=child['id'], density_g_ml=actual_density, conn=conn, skip_hierarchical=True)
                    final_qty, _, _ = convert_to_base(child_qty_in_base, child_base, density_g_ml=actual_density, conn=conn)
                    return (final_qty, target_base_unit, target_base_unit_type)
                except ValueError: continue

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
        if current_base_type != new_unit_type:
            if {current_base_type, new_unit_type} == {'mass', 'volume'}:
                # Check for specific density or parent density
                density = ingredient['density_g_ml']
                if (not density or density <= 0) and ingredient['parent_id']:
                    parent = conn.execute("SELECT density_g_ml FROM ingredients WHERE id = ?", (ingredient['parent_id'],)).fetchone()
                    if parent:
                        density = parent['density_g_ml']

                if density and density > 0:
                    return False  # Density exists (locally or inherited), no prompt needed.
                else:
                    return True   # No density, prompt is needed.

            # Handle count-to-mass or count-to-volume
            elif 'count' in {current_base_type, new_unit_type}:
                # Check if a specific conversion factor already exists for this ingredient
                res = conn.execute("SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND ((from_unit = ? AND to_unit = ?) OR (from_unit = ? AND to_unit = ?))",
                                   (ingredient_id, unit, ingredient['base_unit'], ingredient['base_unit'], unit)).fetchone()
                if res:
                    return False
                
                # Check parent
                if ingredient['parent_id']:
                    res = conn.execute("SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND ((from_unit = ? AND to_unit = ?) OR (from_unit = ? AND to_unit = ?))",
                                       (ingredient['parent_id'], unit, ingredient['base_unit'], ingredient['base_unit'], unit)).fetchone()
                    if res:
                        return False

                return True # No conversion factor found, prompt is needed.

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
    
    target_unit = ingredient['base_unit']
    
    # Smarter prompt for count conversions
    if 'unit' in {original_unit, target_unit}:
        prompt_text = f"How many <strong>{target_unit}</strong> are in <strong>{original_quantity} {original_unit}</strong> of {ingredient['name']}?"
        default_factor_input = f"""
            {original_quantity} {original_unit} = <input type="number" name="total_target_quantity" step="any" required> {target_unit}
            <input type="hidden" name="is_total_conversion" value="true">
        """
    else:
        prompt_text = f"How many {target_unit} are in 1 {original_unit} of {ingredient['name']}?"
        default_factor_input = f"""
            1 {original_unit} = <input type="number" name="factor" step="any" required> {target_unit}
        """

    return f"""
    <div id="user-prompts" hx-swap-oob="true">
        <div id="conversion-prompt" class="conversion-prompt">
            <h4><i data-lucide="help-circle"></i> Conversion Needed</h4>
            <p>{prompt_text}</p>
            <form hx-post="/add_conversion" hx-target="#ingredient-list-container" hx-swap="innerHTML" hx-on:htmx:after-request="this.closest('#conversion-prompt').remove()">
                <input type="hidden" name="ingredient_id" value="{ingredient_id}">
                <input type="hidden" name="from_unit" value="{original_unit}">
                <input type="hidden" name="to_unit" value="{target_unit}">
                <input type="hidden" name="quantity_to_add" value="{original_quantity}">
                <input type="hidden" name="unit_to_add" value="{original_unit}">

                {default_factor_input}
                <button type="submit">Save & Add</button>
                <button type="button" class="button-secondary" onclick="this.closest('#conversion-prompt').remove()">Cancel</button>
            </form>
        </div>
        <script>lucide.createIcons();</script>
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
    <div id="user-prompts" hx-swap-oob="true">
        <div id="conversion-prompt" class="conversion-prompt">
            <h4><i data-lucide="info"></i> New Ingredient: Density Needed</h4>
            <p>To allow for conversions between mass and volume (e.g., cups to grams), please provide the density for <strong>{ingredient_name}</strong>.</p>
            <p class="small-text">Don't know the density in g/ml? <button type="button" class="link-button" onclick="openModalAndTab('Density')">Calculate it here</button>.</p>
            <form hx-post="/add_new_ingredient_with_density" hx-target="#ingredient-list-container" hx-swap="innerHTML" hx-on:htmx:after-request="this.closest('#conversion-prompt').remove()">
                <input type="hidden" name="ingredient_name" value="{ingredient_name}">
                <input type="hidden" name="original_quantity" value="{original_quantity}">
                <input type="hidden" name="original_unit" value="{original_unit}">

                <div style="display: flex; align-items: center; gap: 1rem;">
                    <label for="density" style="margin-bottom: 0;">Density (g/ml):</label>
                    <input type="number" name="density_g_ml" id="density" step="any" required placeholder="e.g., 1.0" style="width: 100px;">
                    <button type="submit">Save & Add</button>
                    <button type="button" class="button-secondary" onclick="this.closest('#conversion-prompt').remove()">Cancel</button>
                </div>
            </form>
            <p class="small-text" style="margin-top: 1rem; margin-bottom: 0;">Accuracy Tip: Most liquids are ~1.0. Flour is ~0.53. Sugar is ~0.85.</p>
        </div>
        <script>lucide.createIcons();</script>
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

    This function leverages `convert_to_base` to convert both the source
    and the target units to the base unit, then calculates the ratio.
    This ensures that multi-hop and hierarchical rules work in both directions.

    Args:
        quantity (float): The quantity to convert.
        from_unit (str): The starting unit.
        to_unit (str): The target unit.
        ingredient_id (int, optional): The ID of the ingredient.
        conn (sqlite3.Connection, optional): Database connection.

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
        # Step 1: Convert the source quantity to the base unit
        # This handles custom rules, parent/child borrowing, and bridging (e.g. unit -> oz -> g)
        qty_in_base, base_unit, _ = convert_to_base(quantity, from_unit, ingredient_id, conn=conn)

        # Step 2: Determine how much 1 unit of the target unit is worth in the base unit
        # We use the same smart logic to find the 'value' of the target unit.
        try:
            target_unit_value_in_base, _, _ = convert_to_base(1.0, to_unit, ingredient_id, conn=conn)
        except ValueError:
            # If we can't find a path to the base unit for the target unit, we can't convert.
            raise ValueError(f"Could not find a conversion path from '{from_unit}' to '{to_unit}'")

        if target_unit_value_in_base == 0:
            return 0

        return qty_in_base / target_unit_value_in_base

    finally:
        if close_conn and conn:
            conn.close()
