# debug_categorization.py
import os
from analytics import Analytics

# This script is for debugging the categorization of window titles.
# It loads the configuration and tests the get_cat method directly.

def main():
    print(f"Current working directory: {os.getcwd()}")
    print("Initializing Analytics class to load config.dat...")
    
    try:
        analytic = Analytics()
        print("Analytics class initialized.")
        
        # Print the loaded categories for inspection
        print("\n--- Loaded Categories from config.dat ---")
        if analytic.string_cats:
            for keyword, category in analytic.string_cats:
                print(f"'{keyword}': '{category}'")
        else:
            print("No categories loaded.")
        print("-----------------------------------------\n")

        window_title_to_test = "windows default lock screen"
        print(f"Testing window title: '{window_title_to_test}'")
        
        # Call the function to get the category
        category_result = analytic.get_cat(window_title_to_test)
        
        print(f"\n--- RESULT ---")
        print(f"The title '{window_title_to_test}' was categorized as: '{category_result}'")
        print("----------------\n")

        if category_result == "idle":
            print("SUCCESS: The category is 'idle' as expected.")
        else:
            print(f"FAILURE: The category should be 'idle', but was '{category_result}'.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
