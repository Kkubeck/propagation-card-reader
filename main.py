import fitz  # PyMuPDF
import os

def convert_page_to_image(doc, page_number, output_folder="output_images"):
    """Converts a single page of an open PDF document to a PNG image."""
    # Create the output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    try:
        # Select the page (the doc is already open)
        page = doc.load_page(page_number)
        
        # Render page to a pixmap (an image object) at 300 DPI
        pix = page.get_pixmap(dpi=300)
        
        # Define the output image path
        output_path = os.path.join(output_folder, f"page_{page_number}.png")
        
        # Save the image
        pix.save(output_path)
        print(f"Successfully saved page {page_number} to {output_path}")
        return output_path
            
    except Exception as e:
        print(f"An error occurred converting page {page_number}: {e}")
        return None

# --- Main execution block for testing ---
if __name__ == "__main__":
    SAMPLE_PDF = os.path.join("data", "sample.pdf")
    OUTPUT_FOLDER = "output_images"

    if not os.path.exists(SAMPLE_PDF):
        print(f"Error: PDF file not found at '{SAMPLE_PDF}'")
    else:
        # Open the PDF document once
        doc = fitz.open(SAMPLE_PDF)
        print(f"Processing {doc.page_count} pages from '{os.path.basename(SAMPLE_PDF)}'...")

        # Loop through every page in the PDF
        for page_num in range(doc.page_count):
            
            # Step 1: Convert the current page to a raw image
            convert_page_to_image(
                doc=doc, 
                page_number=page_num, 
                output_folder=OUTPUT_FOLDER
            )
        
        doc.close()
        print(f"\nProcessing complete. All images are in the '{OUTPUT_FOLDER}' folder.")