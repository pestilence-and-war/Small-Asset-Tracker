from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Navigate to the app
        page.goto("http://127.0.0.1:5000")

        # 2. Go to the recipe manager
        # Using get_by_role for robustness
        recipe_link = page.get_by_role("link", name="Recipes")
        recipe_link.click()

        # Wait for the meals list to be visible
        expect(page.locator(".meals-list")).to_be_visible()

        # 3. Click the first "Manage" button
        # This assumes at least one meal exists
        manage_button = page.get_by_role("link", name="Manage").first
        expect(manage_button).to_be_visible()
        manage_button.click()

        # 4. Verify the new layout and take a screenshot
        # Wait for the new layout to be present
        expect(page.locator(".recipe-editor-layout")).to_be_visible()

        # Check for the instructions section
        expect(page.locator(".instructions-section h2")).to_have_text("Instructions")

        # Fill in some instructions
        instructions_textarea = page.get_by_placeholder("Enter recipe instructions here...")
        instructions_textarea.fill("1. Do the first thing.\\n2. Do the second thing.")

        # Give a moment for the htmx request to fire and save
        page.wait_for_timeout(1000)

        page.screenshot(path="jules-scratch/verification/recipe_editor.png")
        print("Screenshot taken successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")

    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)
