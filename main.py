# main.py
import os
import fitz  # PyMuPDF

# Import our custom modules
from utils import load_template
from pdf_processing import convert_page_to_image
from image_processing import extract_fields_from_image

if __name__ == "__main__":
    SAMPLE_PDF = os.path.join("data", "sample.pdf")
    OUTPUT_FOLDER = "output_images"
    TEMPLATE_FILE = "template.json"

    fields_to_extract = load_template(TEMPLATE_FILE)
    
    if not fields_to_extract:
        print("Could not load template or template is empty. Exiting.")
    elif not os.path.exists(SAMPLE_PDF):
        print(f"Error: PDF file not found at '{SAMPLE_PDF}'")
    else:
        doc = fitz.open(SAMPLE_PDF)
        print(f"Processing {doc.page_count} pages from '{os.path.basename(SAMPLE_PDF)}'...")

        for page_num in range(doc.page_count):
            print(f"--- Processing Page {page_num} ---")
            
            card_image_path = convert_page_to_image(
                doc=doc, 
                page_number=page_num, 
                output_folder=OUTPUT_FOLDER
            )
            
            if card_image_path:
                extract_fields_from_image(
                    card_image_path=card_image_path,
                    fields=fields_to_extract
                )
        
        doc.close()
        print("\nField extraction complete.")