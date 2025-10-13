import os
from ocr_processing import get_text_from_image
from post_processing import clean_accession_number

# --- Configuration ---
TEST_IMAGE_FOLDER = "ocr_test_images"

if __name__ == "__main__":
    # Before running, make sure you've set your environment variable in the terminal:
    # export GOOGLE_APPLICATION_CREDENTIALS="gcp_key.json"

    print(f"--- Running OCR on images in '{TEST_IMAGE_FOLDER}' ---")

    if not os.path.isdir(TEST_IMAGE_FOLDER):
        print(f"Error: Test folder '{TEST_IMAGE_FOLDER}' not found.")
    else:
        # Loop through each image in the test folder
        for filename in sorted(os.listdir(TEST_IMAGE_FOLDER)):
            if filename.lower().endswith(".png"):
                image_path = os.path.join(TEST_IMAGE_FOLDER, filename)
                
                # Step 1: Get raw text from OCR
                raw_text = get_text_from_image(image_path)
                
                # Step 2: Clean the raw text using our new function
                cleaned_text = clean_accession_number(raw_text)
                
                print(f"\nFile: {filename}")
                print(f"  -> Raw Text: {raw_text.replace(chr(10), ' ')}")
                print(f"  -> Cleaned:  {cleaned_text}")