from app.database import get_db_connection
import re

# Comprehensive dictionary mapping aliases and plurals to canonical units
UNIT_ALIASES = {
    # Mass
    'g': 'g', 'gram': 'g', 'grams': 'g',
    'kg': 'kg', 'kgs': 'kg', 'kilogram': 'kg', 'kilograms': 'kg',
    'lb': 'lb', 'lbs': 'lb', 'pound': 'lb', 'pounds': 'lb',
    'oz': 'oz', 'ozs': 'oz', 'ounce': 'oz', 'ounces': 'oz',
    'mg': 'mg', 'milligram': 'mg', 'milligrams': 'mg',
    # Volume
    'ml': 'ml', 'milliliter': 'ml', 'milliliters': 'ml',
    'l': 'l', 'liter': 'l', 'liters': 'l',
    'cup': 'cup', 'cups': 'cup', 'c': 'cup',
    'tbsp': 'tbsp', 'tbs': 'tbsp', 'tablespoon': 'tbsp', 'tablespoons': 'tbsp',
    'tsp': 'tsp', 'teaspoon': 'tsp', 'teaspoons': 'tsp',
    'fl oz': 'fl oz', 'fl. oz': 'fl oz', 'floz': 'fl oz', 'fluid ounce': 'fl oz', 'fluid ounces': 'fl oz',
    'gallon': 'gallon', 'gallons': 'gallon', 'gal': 'gallon', 'gals': 'gallon',
    'quart': 'quart', 'quarts': 'quart', 'qt': 'quart', 'qts': 'quart',
    'pint': 'pint', 'pints': 'pint', 'pt': 'pint', 'pts': 'pint',
    'cc': 'cc',
    # Count & Containers
    'unit': 'unit', 'units': 'unit', 'ea': 'unit', 'each': 'unit', 'piece': 'unit', 'pieces': 'unit', 'item': 'unit', 'items': 'unit',
    'can': 'can', 'cans': 'can',
    'box': 'box', 'boxes': 'box',
    'bottle': 'bottle', 'bottles': 'bottle',
    'pkg': 'pkg', 'package': 'pkg', 'packages': 'pkg', 'pack': 'pkg', 'packs': 'pkg',
    'bag': 'bag', 'bags': 'bag',
    'jar': 'jar', 'jars': 'jar',
    'container': 'container', 'containers': 'container',
    'stick': 'stick', 'sticks': 'stick',
    'slice': 'slice', 'slices': 'slice',
    'clove': 'clove', 'cloves': 'clove',
    'head': 'head', 'heads': 'head',
    'bunch': 'bunch', 'bunches': 'bunch',
    'pinch': 'pinch', 'pinches': 'pinch',
    'dash': 'dash', 'dashes': 'dash',
}

# Category default densities (g/ml) for smart fallback conversions
CATEGORY_DEFAULT_DENSITIES = {
    'beverages': 1.0,
    'dairy & eggs': 1.03,
    'canned goods': 1.0,
    'condiments': 1.05,
    'oils & vinegars': 0.92,
    'oil & vinegar': 0.92,
    'baking': 0.65,
    'fresh produce': 0.8,
    'produce': 0.8,
    'spices': 0.6,
    'pantry': 1.0,
    'snacks': 0.7,
    'other': 1.0,
}


def normalize_unit(unit_str):
    """Normalizes unit strings into standard canonical units.

    Args:
        unit_str (str): The raw unit string (e.g. 'cups', 'fl. oz', 'oz diced').

    Returns:
        str: The normalized canonical unit.
    """
    if not unit_str:
        return 'unit'

    clean_str = unit_str.strip().lower()
    if clean_str in UNIT_ALIASES:
        return UNIT_ALIASES[clean_str]

    # Handle prefixed descriptors, e.g. "cup diced" -> "cup"
    words = clean_str.split()
    if words and words[0] in UNIT_ALIASES:
        return UNIT_ALIASES[words[0]]

    # Handle multi-word units like 'fl oz'
    for alias, canonical in UNIT_ALIASES.items():
        if clean_str == alias or clean_str.startswith(alias + ' '):
            return canonical

    return clean_str


def parse_quantity(quantity_str):
    """Parses a quantity string into a float.

    The string can be a decimal, a fraction, or a mixed number.
    For example: "1.5", "1/2", "1 1/2".

    Args:
        quantity_str (str or float): The string to parse.

    Returns:
        float: The parsed quantity as a float.

    Raises:
        ValueError: If the string format is invalid.
    """
    if quantity_str is None:
        raise ValueError("Quantity string cannot be None.")

    if not isinstance(quantity_str, str):
        return float(quantity_str)

    quantity_str = quantity_str.strip()
    if not quantity_str:
        raise ValueError("Empty quantity string.")

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
                pass

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
                pass

    # Clean non-numeric trailing text if present (e.g. "15.5g" -> "15.5")
    match = re.search(r"^([\d.]+)", quantity_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    try:
        return float(quantity_str)
    except ValueError:
        raise ValueError(f"Could not parse quantity: '{quantity_str}'")


def parse_quantity_and_unit(quantity_str):
    """Parses a quantity string into a (quantity, unit) tuple.

    Handles single and dual/parenthetical formats, e.g.:
    - "500 g" -> (500.0, "g")
    - "15 oz (425 g)" -> (15.0, "oz")
    - "1.5 cup diced" -> (1.5, "cup diced")

    Args:
        quantity_str (str): The string to parse.

    Returns:
        tuple: (float, str) or (None, None) if parsing fails.
    """
    if not quantity_str:
        return None, None

    cleaned_str = str(quantity_str).strip()

    # Look for parenthetical weight/volume, e.g. "15 oz (425 g)" or "1 can (15 oz)"
    paren_match = re.search(r"\(([\d\s./]+)\s*([a-zA-Z\s.]+)\)", cleaned_str)
    if paren_match:
        try:
            p_qty = parse_quantity(paren_match.group(1).strip())
            p_unit = paren_match.group(2).strip().lower()
            norm = normalize_unit(p_unit)
            if get_base_unit_type(norm) in ('mass', 'volume'):
                return p_qty, p_unit
        except ValueError:
            pass

    # Regex to capture the numeric/fractional part and the remaining part as the unit
    match = re.search(r"^([\d\s./]+)\s*(.*)$", cleaned_str)
    if match:
        qty_part = match.group(1).strip()
        unit_part = match.group(2).strip().lower()
        try:
            qty = parse_quantity(qty_part)
            unit = unit_part if unit_part else 'unit'
            return qty, unit
        except ValueError:
            pass

    return None, None


def get_base_unit_type(unit):
    """Determines if a unit is for mass, volume, or count/container.

    Args:
        unit (str): The unit to classify.

    Returns:
        str: 'mass', 'volume', or 'count'.
    """
    if not unit:
        return 'count'

    norm = normalize_unit(unit)

    # Mass
    if norm in ['g', 'kg', 'lb', 'oz', 'mg']:
        return 'mass'

    # Volume
    if norm in ['ml', 'l', 'cup', 'tbsp', 'tsp', 'gallon', 'quart', 'pint', 'cc', 'fl oz']:
        return 'volume'

    # Count / Containers
    return 'count'


def get_base_unit(unit_type):
    """Returns the base unit for a given unit type.

    Args:
        unit_type (str): 'mass', 'volume', or 'count'.

    Returns:
        str: The base unit ('g', 'ml', 'unit').
    """
    if unit_type == 'mass':
        return 'g'
    if unit_type == 'volume':
        return 'ml'
    return 'unit'


def get_category_density(category_name):
    """Gets default density for an ingredient category."""
    if not category_name:
        return 1.0
    cat_lower = str(category_name).strip().lower()
    return CATEGORY_DEFAULT_DENSITIES.get(cat_lower, 1.0)


def convert_to_base(quantity, unit, ingredient_id=None, density_g_ml=None, conn=None, skip_hierarchical=False, last_unit=None):
    """Converts a given quantity and unit to its base unit quantity.

    Robust against missing conversion factors, using category densities and safe fallbacks.
    Handles legacy positional invocations where sqlite3.Connection was passed as 4th arg.

    Args:
        quantity (float): The quantity to convert.
        unit (str): The unit of the quantity.
        ingredient_id (int, optional): The ID of the ingredient.
        density_g_ml (float or sqlite3.Connection, optional): Density to use, or connection if passed positionally.
        conn (sqlite3.Connection, optional): Database connection.
        skip_hierarchical (bool, optional): If True, skips parent/child fallback.
        last_unit (str, optional): The unit converted from to prevent infinite loops.

    Returns:
        tuple: (float: quantity, str: base_unit, str: base_unit_type)
    """
    # Handle legacy positional call convert_to_base(qty, unit, ingredient_id, conn)
    if density_g_ml is not None and not isinstance(density_g_ml, (int, float)):
        if conn is None:
            conn = density_g_ml
        density_g_ml = None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        unit = normalize_unit(unit)
        ingredient = None
        parent_id = None
        category = 'Other'

        if ingredient_id:
            ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
            if ingredient:
                parent_id = ingredient['parent_id']
                category = ingredient['category'] or 'Other'

        # Determine actual density
        actual_density = density_g_ml if isinstance(density_g_ml, (int, float)) else None
        if ingredient and ingredient['density_g_ml']:
            actual_density = ingredient['density_g_ml']
        elif parent_id:
            parent = conn.execute("SELECT density_g_ml FROM ingredients WHERE id = ?", (parent_id,)).fetchone()
            if parent and parent['density_g_ml']:
                actual_density = parent['density_g_ml']

        # Default category density fallback if density is needed but missing
        if not actual_density or actual_density <= 0:
            actual_density = get_category_density(category)

        source_unit_type = get_base_unit_type(unit)
        target_base_unit = ingredient['base_unit'] if ingredient and ingredient['base_unit'] else get_base_unit(source_unit_type)
        target_base_unit_type = ingredient['base_unit_type'] if ingredient and ingredient['base_unit_type'] else source_unit_type

        # If already matching target base unit
        if unit == target_base_unit:
            return (quantity, target_base_unit, target_base_unit_type)

        # 1. Check custom ingredient conversion rules (Highest Priority)
        if ingredient_id:
            # Forward: unit -> target or other
            res = conn.execute("SELECT factor, to_unit FROM ingredient_conversions WHERE ingredient_id = ? AND from_unit = ?", (ingredient_id, unit)).fetchone()
            if res and res['to_unit'] != last_unit:
                if res['to_unit'] == target_base_unit:
                    return (quantity * res['factor'], target_base_unit, target_base_unit_type)
                else:
                    qty_in_other = quantity * res['factor']
                    return convert_to_base(qty_in_other, res['to_unit'], ingredient_id=ingredient_id, density_g_ml=actual_density, conn=conn, skip_hierarchical=True, last_unit=unit)

            # Reciprocal: target or other -> unit
            res = conn.execute("SELECT factor, from_unit FROM ingredient_conversions WHERE ingredient_id = ? AND to_unit = ?", (ingredient_id, unit)).fetchone()
            if res and res['factor'] != 0 and res['from_unit'] != last_unit:
                if res['from_unit'] == target_base_unit:
                    return (quantity / res['factor'], target_base_unit, target_base_unit_type)
                else:
                    qty_in_other = quantity / res['factor']
                    return convert_to_base(qty_in_other, res['from_unit'], ingredient_id=ingredient_id, density_g_ml=actual_density, conn=conn, skip_hierarchical=True, last_unit=unit)

        # 2. Check Standard Conversions (Same type: mass->mass, vol->vol)
        if source_unit_type == target_base_unit_type:
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, target_base_unit)).fetchone()
            if res:
                return (quantity * res['factor'], target_base_unit, target_base_unit_type)
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_base_unit, unit)).fetchone()
            if res:
                return (quantity / res['factor'], target_base_unit, target_base_unit_type)

            # Check conversion via intermediate standard unit (e.g. lb -> g or fl oz -> ml)
            std_source = get_base_unit(source_unit_type)
            res_to_std = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, std_source)).fetchone()
            if res_to_std:
                qty_std = quantity * res_to_std['factor']
                if target_base_unit == std_source:
                    return (qty_std, target_base_unit, target_base_unit_type)
                res_std_to_target = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (std_source, target_base_unit)).fetchone()
                if res_std_to_target:
                    return (qty_std * res_std_to_target['factor'], target_base_unit, target_base_unit_type)

        # 3. Check Mass <-> Volume using Density
        if {source_unit_type, target_base_unit_type} == {'mass', 'volume'}:
            std_source_base = get_base_unit(source_unit_type)
            qty_in_std_base = quantity

            if unit != std_source_base:
                res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (unit, std_source_base)).fetchone()
                if res:
                    qty_in_std_base = quantity * res['factor']
                else:
                    res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (std_source_base, unit)).fetchone()
                    if res:
                        qty_in_std_base = quantity / res['factor']

            qty_in_target_std_base = qty_in_std_base / actual_density if source_unit_type == 'mass' else qty_in_std_base * actual_density
            target_std_base = get_base_unit(target_base_unit_type)

            final_qty = qty_in_target_std_base
            if target_base_unit != target_std_base:
                res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_std_base, target_base_unit)).fetchone()
                if res:
                    final_qty = qty_in_target_std_base * res['factor']
                else:
                    res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = ?", (target_base_unit, target_std_base)).fetchone()
                    if res:
                        final_qty = qty_in_target_std_base / res['factor']

            return (final_qty, target_base_unit, target_base_unit_type)

        # 4. Hierarchical Fallbacks (Parent/Child)
        if ingredient_id and not skip_hierarchical:
            if parent_id:
                try:
                    return convert_to_base(quantity, unit, ingredient_id=parent_id, density_g_ml=actual_density, conn=conn, skip_hierarchical=True)
                except ValueError:
                    pass

            children = conn.execute("SELECT id FROM ingredients WHERE parent_id = ?", (ingredient_id,)).fetchall()
            for child in children:
                try:
                    child_qty_in_base, child_base, _ = convert_to_base(quantity, unit, ingredient_id=child['id'], density_g_ml=actual_density, conn=conn, skip_hierarchical=True)
                    final_qty, _, _ = convert_to_base(child_qty_in_base, child_base, density_g_ml=actual_density, conn=conn)
                    return (final_qty, target_base_unit, target_base_unit_type)
                except ValueError:
                    continue

        # 5. Last Resort Fallback (Containers/Count to Mass/Volume)
        # If adding e.g. 1 can or 1 box or 1 unit to a mass/volume ingredient
        if source_unit_type == 'count' and target_base_unit_type in ('mass', 'volume'):
            # Default package weights: 1 stick butter = 113.4g, 1 can = 425g, standard unit = 100g/ml
            default_weights = {'stick': 113.398, 'can': 425.0, 'box': 400.0, 'bottle': 500.0, 'pkg': 400.0, 'unit': 100.0}
            weight_in_g = default_weights.get(unit, 100.0) * quantity
            if target_base_unit == 'g':
                return (weight_in_g, 'g', 'mass')
            elif target_base_unit == 'ml':
                return (weight_in_g / actual_density, 'ml', 'volume')
            else:
                return (quantity, target_base_unit, target_base_unit_type)

        if target_base_unit_type == 'count':
            # Target is count, source is mass/volume
            return (quantity, target_base_unit, target_base_unit_type)

        # Fallback default
        return (quantity, target_base_unit, target_base_unit_type)

    finally:
        if close_conn and conn:
            conn.close()


def needs_conversion_prompt(unit, ingredient_id, conn=None):
    """Checks if a conversion prompt is strictly necessary.

    Returns False if density or automatic fallback covers the conversion.
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
        new_unit = normalize_unit(unit)
        new_unit_type = get_base_unit_type(new_unit)

        if current_base_type == new_unit_type:
            return False

        # If types are different, check if density exists or can be inherited
        if {current_base_type, new_unit_type} == {'mass', 'volume'}:
            density = ingredient['density_g_ml']
            if density and density > 0:
                return False
            if ingredient['parent_id']:
                parent = conn.execute("SELECT density_g_ml FROM ingredients WHERE id = ?", (ingredient['parent_id'],)).fetchone()
                if parent and parent['density_g_ml']:
                    return False
            # Check if category density fallback applies
            cat_density = get_category_density(ingredient['category'])
            if cat_density and cat_density > 0:
                return False

        # Check for explicit ingredient conversion factor
        res = conn.execute(
            "SELECT factor FROM ingredient_conversions WHERE ingredient_id = ? AND ((from_unit = ? AND to_unit = ?) OR (from_unit = ? AND to_unit = ?))",
            (ingredient_id, new_unit, ingredient['base_unit'], ingredient['base_unit'], new_unit)
        ).fetchone()
        if res:
            return False

        return False  # Return False to utilize smart defaults instead of blocking flow
    finally:
        if close_conn and conn:
            conn.close()


def get_conversion_prompt_html(ingredient_id, original_quantity, original_unit, pending_quantity):
    """Generates HTML for a conversion prompt."""
    conn = get_db_connection()
    ingredient = conn.execute("SELECT * FROM ingredients WHERE id = ?", (ingredient_id,)).fetchone()
    conn.close()

    if not ingredient:
        return "<div class='alert alert-error'>Error: Ingredient not found.</div>"

    target_unit = ingredient['base_unit']
    norm_unit = normalize_unit(original_unit)

    if 'unit' in {norm_unit, target_unit}:
        prompt_text = f"How many <strong>{target_unit}</strong> are in <strong>{original_quantity} {norm_unit}</strong> of {ingredient['name']}?"
        default_factor_input = f"""
            {original_quantity} {norm_unit} = <input type="number" name="total_target_quantity" step="any" class="form-input" required> {target_unit}
            <input type="hidden" name="is_total_conversion" value="true">
        """
    else:
        prompt_text = f"How many <strong>{target_unit}</strong> are in 1 <strong>{norm_unit}</strong> of {ingredient['name']}?"
        default_factor_input = f"""
            1 {norm_unit} = <input type="number" name="factor" step="any" class="form-input" required> {target_unit}
        """

    return f"""
    <div id="user-prompts" hx-swap-oob="true">
        <div id="conversion-prompt" class="conversion-prompt-card">
            <div class="prompt-header">
                <i data-lucide="calculator" class="prompt-icon"></i>
                <h4>Conversion Adjustment Needed</h4>
            </div>
            <p>{prompt_text}</p>
            <form hx-post="/add_conversion" hx-target="#ingredient-list-container" hx-swap="innerHTML" hx-on:htmx:after-request="this.closest('#conversion-prompt').remove()" class="prompt-form">
                <input type="hidden" name="ingredient_id" value="{ingredient_id}">
                <input type="hidden" name="from_unit" value="{norm_unit}">
                <input type="hidden" name="to_unit" value="{target_unit}">
                <input type="hidden" name="quantity_to_add" value="{original_quantity}">
                <input type="hidden" name="unit_to_add" value="{norm_unit}">

                <div class="input-row">
                    {default_factor_input}
                    <button type="submit" class="btn btn-primary">Save & Add</button>
                    <button type="button" class="btn btn-ghost" onclick="this.closest('#conversion-prompt').remove()">Cancel</button>
                </div>
            </form>
        </div>
        <script>if(window.lucide) lucide.createIcons();</script>
    </div>
    """


def get_new_ingredient_conversion_prompt_html(ingredient_name, original_quantity, original_unit):
    """Generates HTML for a density prompt for a new ingredient."""
    norm_unit = normalize_unit(original_unit)
    return f"""
    <div id="user-prompts" hx-swap-oob="true">
        <div id="conversion-prompt" class="conversion-prompt-card">
            <div class="prompt-header">
                <i data-lucide="beaker" class="prompt-icon"></i>
                <h4>New Ingredient: Density Setup</h4>
            </div>
            <p>To enable accurate mass-to-volume conversions, set a density for <strong>{ingredient_name}</strong>.</p>
            <form hx-post="/add_new_ingredient_with_density" hx-target="#ingredient-list-container" hx-swap="innerHTML" hx-on:htmx:after-request="this.closest('#conversion-prompt').remove()" class="prompt-form">
                <input type="hidden" name="ingredient_name" value="{ingredient_name}">
                <input type="hidden" name="original_quantity" value="{original_quantity}">
                <input type="hidden" name="original_unit" value="{norm_unit}">

                <div class="input-row">
                    <label for="density">Density (g/ml):</label>
                    <input type="number" name="density_g_ml" id="density" step="any" required placeholder="e.g. 1.0" value="1.0" class="form-input" style="width: 100px;">
                    <button type="submit" class="btn btn-primary">Save & Add</button>
                    <button type="button" class="btn btn-ghost" onclick="this.closest('#conversion-prompt').remove()">Cancel</button>
                </div>
            </form>
        </div>
        <script>if(window.lucide) lucide.createIcons();</script>
    </div>
    """


def format_fraction(num):
    """Converts a float to a clean string with common fractions."""
    if num is None:
        return ""
    if num == 0:
        return "0"

    integer_part = int(num)
    decimal_part = abs(num - integer_part)

    fractions = {
        1/8: "1/8", 1/4: "1/4", 1/3: "1/3", 1/2: "1/2",
        2/3: "2/3", 3/4: "3/4",
    }

    closest_fraction = ""
    min_diff = float('inf')
    for frac_val, frac_str in fractions.items():
        diff = abs(decimal_part - frac_val)
        if diff < 0.02:
            if diff < min_diff:
                min_diff = diff
                closest_fraction = frac_str

    integer_str = str(integer_part) if integer_part > 0 else ""
    if closest_fraction:
        return f"{integer_str} {closest_fraction}".strip()
    else:
        return f"{num:.2f}".rstrip('0').rstrip('.')


def convert_from_base(base_quantity, base_unit, density_g_ml=None, conn=None):
    """Converts a quantity from base unit to human-readable format."""
    if not base_unit or base_unit == 'unit':
        return f"{format_fraction(base_quantity)} unit"
    if base_quantity == 0:
        return f"0 {base_unit}"

    preferred_units = ['gallon', 'quart', 'pint', 'cup', 'tbsp', 'tsp']
    quantity_in_ml = 0

    if base_unit == 'ml':
        quantity_in_ml = base_quantity
    elif base_unit == 'g':
        density = density_g_ml if density_g_ml and density_g_ml > 0 else 1.0
        quantity_in_ml = base_quantity / density
    else:
        return f"{format_fraction(base_quantity)} {base_unit}"

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cup_row = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = 'cup' AND to_unit = 'ml'").fetchone()
        cup_factor = cup_row['factor'] if cup_row else 236.588
        quantity_in_cups = quantity_in_ml / cup_factor

        if 0.25 <= quantity_in_cups < 4:
            return f"{format_fraction(quantity_in_cups)} cup"

        for unit in preferred_units:
            res = conn.execute("SELECT factor FROM unit_conversions WHERE from_unit = ? AND to_unit = 'ml'", (unit,)).fetchone()
            if res:
                factor = res['factor']
                converted_quantity = quantity_in_ml / factor
                if converted_quantity >= 1:
                    return f"{format_fraction(converted_quantity)} {unit}"

        if quantity_in_cups > 0:
            return f"{format_fraction(quantity_in_cups)} cup"

        return f"{quantity_in_ml:.2f} ml".rstrip('0').rstrip('.')
    finally:
        if close_conn and conn:
            conn.close()


def convert_units(quantity, from_unit, to_unit, ingredient_id=None, conn=None):
    """General-purpose unit converter with fail-safe behavior."""
    from_unit = normalize_unit(from_unit)
    to_unit = normalize_unit(to_unit)

    if from_unit == to_unit:
        return quantity

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        qty_in_base, base_unit, _ = convert_to_base(quantity, from_unit, ingredient_id, conn=conn)
        target_unit_value_in_base, _, _ = convert_to_base(1.0, to_unit, ingredient_id, conn=conn)

        if target_unit_value_in_base == 0:
            return qty_in_base

        return qty_in_base / target_unit_value_in_base
    except Exception as e:
        print(f"Warning in convert_units: {e}")
        return quantity
    finally:
        if close_conn and conn:
            conn.close()

