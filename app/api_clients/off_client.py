import requests

class OpenFoodFactsClient:
    """A client for interacting with the Open Food Facts API."""

    def __init__(self, user_agent: str = "PantryManager/1.0"):
        """Initializes the OpenFoodFactsClient.

        Args:
            user_agent (str): The User-Agent string to identify the application.
        """
        self.user_agent = user_agent
        self.base_url = "https://world.openfoodfacts.org/api/v0/product/"

    def get_product_by_barcode(self, barcode: str):
        """Fetches product information from Open Food Facts using its barcode.

        Args:
            barcode (str): The product's barcode (UPC/EAN).

        Returns:
            dict: A dictionary containing product details or None if not found.
        """
        url = f"{self.base_url}{barcode}.json"
        headers = {"User-Agent": self.user_agent}

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == 1:
                product = data.get("product", {})
                
                # Extract relevant fields
                name = product.get("product_name") or product.get("product_name_en")
                brands = product.get("brands")
                if brands and name:
                    full_name = f"{brands} {name}"
                else:
                    full_name = name or "Unknown Product"

                # Category suggestion
                # OFF provides 'categories_hierarchy' which is a list of categories from broad to specific
                category_list = product.get("categories_hierarchy", [])
                category = "Other"
                if category_list:
                    # Take the last one (most specific) or the second to last for a good balance
                    raw_cat = category_list[-1] if len(category_list) == 1 else category_list[1]
                    category = raw_cat.split(":")[-1].replace("-", " ").title()

                # Try to get quantity and unit
                quantity_str = product.get("quantity", "")
                
                # Get image URL (prefer front_small or front)
                image_url = product.get("image_front_small_url") or product.get("image_front_url") or product.get("image_url")
                
                # Check for liquid/solid hints
                # If the unit is ml, l, etc., it's volume. If g, kg, it's mass.
                unit_hint = "count"
                if "ml" in quantity_str.lower() or " l" in quantity_str.lower():
                    unit_hint = "volume"
                elif " g" in quantity_str.lower() or "kg" in quantity_str.lower() or "oz" in quantity_str.lower() or "lb" in quantity_str.lower():
                    unit_hint = "mass"

                return {
                    "name": full_name,
                    "quantity_str": quantity_str,
                    "category": category,
                    "unit_hint": unit_hint,
                    "image_url": image_url,
                    "source": "Open Food Facts"
                }
            return None
        except Exception as e:
            print(f"Error fetching from Open Food Facts: {e}")
            return None
