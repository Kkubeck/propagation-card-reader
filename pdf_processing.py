# pdf_processing.py
import fitz  # PyMuPDF
import os

def convert_page_to_image(doc, page_number, output_folder="output_images"):
    """Converts a single page of an open PDF document to a PNG image."""
    os.makedirs(output_folder, exist_ok=True)
    
    try:
        page = doc.load_page(page_number)
        pix = page.get_pixmap(dpi=300)
        output_path = os.path.join(output_folder, f"page_{page_number}.png")
        pix.save(output_path)
        print(f"Successfully saved page {page_number} to {output_path}")
        return output_path
            
    except Exception as e:
        print(f"An error occurred converting page {page_number}: {e}")
        return None