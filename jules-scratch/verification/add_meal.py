from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Navigate to the recipe manager
        page.goto("http://127.0.0.1:5000/recipes")

        # 2. Add a new meal
        add_meal_input = page.get_by_placeholder("New meal name...")
        add_meal_input.fill("Test Meal")

        # Click the button to trigger the hx-post
        add_meal_button = page.get_by_role("button", name="Add Meal")
        add_meal_button.click()

        # 3. Verify the meal was added
        # Wait for the htmx swap to complete
        expect(page.locator(".meal-name", has_text="test meal")).to_be_visible(timeout=10000)

        print("Meal added successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/add_meal_error.png")
        # print page content for debugging
        print(page.content())

    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)
