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

                # Try to get quantity and unit
                # OFF often has 'quantity' as a string like "500 g" or "1.5 l"
                quantity_str = product.get("quantity", "")
                
                # Category suggestion
                category = product.get("main_category")
                if category and ":" in category:
                    category = category.split(":")[-1].replace("-", " ").title()

                return {
                    "name": full_name,
                    "quantity_str": quantity_str,
                    "category": category,
                    "source": "Open Food Facts"
                }
            return None
        except Exception as e:
            print(f"Error fetching from Open Food Facts: {e}")
            return None
