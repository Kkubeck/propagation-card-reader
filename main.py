# main.py
import os
import fitz  # PyMuPDF

# Import our custom modules
from utils import load_template
from pdf_processing import convert_page_to_image
from image_processing import extract_fields_from_image, align_card_to_template

if __name__ == "__main__":
    # --- Configuration ---
    # Set to True to generate debug images showing the anchor match
    DEBUG_MODE = True 
    
    # Define file and folder paths
    SAMPLE_PDF = os.path.join("data", "sample.pdf")
    OUTPUT_FOLDER = "output_images"
    TEMPLATE_FILE = "template.json"

    # --- Alignment Configuration ---
    # Create a list of all anchor images you want to try
    ANCHOR_TEMPLATE_PATHS = [
        os.path.join("templates", "anchor_v1.png"),
        os.path.join("templates", "anchor_v2.png"),
        os.path.join("templates", "anchor_v3.png"),
        # Add more anchor paths here if needed
    ]

    # Define the ideal (x,y) coordinate for your anchor's top-left corner
    # This must be the SAME for all templates.
    TARGET_ANCHOR_OFFSET = (60, 150) # <<<--- REPLACE WITH YOUR ACTUAL COORDINATES
    
    # --- Main Script ---
    fields_to_extract = load_template(TEMPLATE_FILE)
    
    if not fields_to_extract:
        print("Could not load template or template is empty. Exiting.")
    elif not os.path.exists(SAMPLE_PDF):
        print(f"Error: PDF file not found at '{SAMPLE_PDF}'")
    else:
        # Check if anchor templates exist before starting
        for path in ANCHOR_TEMPLATE_PATHS:
            if not os.path.exists(path):
                print(f"Error: Anchor template not found at '{path}'. Please create it.")
                exit()

        doc = fitz.open(SAMPLE_PDF)
        print(f"Processing {doc.page_count} pages from '{os.path.basename(SAMPLE_PDF)}'...")

        for page_num in range(doc.page_count):
            print(f"--- Processing Page {page_num} ---")
            
            # Step 1: Convert the page to a raw card image
            raw_card_image_path = convert_page_to_image(
                doc=doc, 
                page_number=page_num, 
                output_folder=OUTPUT_FOLDER
            )
            
            if raw_card_image_path:
                # Step 2: Align the card image using the best anchor match
                aligned_card_image_path = align_card_to_template(
                    card_image_path=raw_card_image_path,
                    anchor_template_paths=ANCHOR_TEMPLATE_PATHS,
                    output_folder=OUTPUT_FOLDER,
                    target_offset=TARGET_ANCHOR_OFFSET,
                    debug=DEBUG_MODE
                )
                
                # Step 3: Extract fields from the ALIGNED image
                if aligned_card_image_path:
                    extract_fields_from_image(
                        card_image_path=aligned_card_image_path,
                        fields=fields_to_extract,
                        output_folder=os.path.join(OUTPUT_FOLDER, "fields")
                    )
        
        doc.close()
        print("\nCard processing and field extraction complete.")