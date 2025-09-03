# Pantry Manager

Pantry Manager is a web application designed to help you keep track of your pantry ingredients, manage recipes, and plan your cooking sessions. It provides a user-friendly interface for adding, editing, and deleting ingredients, as well as importing recipes from text or images.

## Features

- **Pantry Management**: Keep a detailed inventory of your ingredients, including quantity, unit, and category.
- **Recipe Management**: Store your favorite recipes, including ingredients and instructions.
- **Recipe Import**: Import recipes from text or images using a powerful AI-powered parser.
- **Cooking Mode**: Start a cooking session for a specific meal, and the application will show you what you have and what you need.
- **Unit Conversion**: A built-in unit converter helps you with mass and volume conversions.
- **Density Calculator**: Calculate the density of your ingredients for accurate mass-to-volume conversions.

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/pantry-manager.git
    cd pantry-manager
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Set up the environment variables:**
    Create a `.env` file in the root of the project and add your Google API key:
    ```
    GOOGLE_API_KEY=your_google_api_key
    ```

4.  **Initialize the database:**
    ```bash
    python init_db.py
    ```

5.  **Run the application:**
    ```bash
    python run.py
    ```

    The application will be available at `http://localhost:5000`.

## Usage

- **Adding Ingredients**: Use the "Add Ingredient" form to add new items to your pantry.
- **Managing Recipes**: Navigate to the "Recipes" page to add, edit, or delete your meals.
- **Importing Recipes**: Use the "Import Recipe" feature to parse recipes from text or images.
- **Cooking Mode**: Select a meal and start a cooking session to see a checklist of your ingredients.
