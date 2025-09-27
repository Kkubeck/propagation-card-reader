import fitz  # PyMuPDF
import os

def convert_pdf_page_to_image(pdf_path, page_number, output_folder="output_images"):
    """
    Converts a single page of a PDF to a high-resolution PNG image.

    Args:
        pdf_path (str): The file path to the PDF.
        page_number (int): The page number to convert (0-indexed).
        output_folder (str): The folder to save the output image in.

    Returns:
        str: The path to the saved image file, or None if failed.
    """
    # Create the output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    try:
        # Open the PDF file
        doc = fitz.open(pdf_path)
        
        # Select the page (pages are 0-indexed)
        if 0 <= page_number < len(doc):
            page = doc.load_page(page_number)
            
            # Render page to a pixmap (an image object) at 300 DPI
            # Higher DPI is crucial for good OCR results
            pix = page.get_pixmap(dpi=300)
            
            # Define the output image path
            output_path = os.path.join(output_folder, f"page_{page_number}.png")
            
            # Save the image
            pix.save(output_path)
            print(f"Successfully saved page {page_number} to {output_path}")
            return output_path
        else:
            print(f"Error: Page number {page_number} is out of range.")
            return None
            
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

# --- Main execution block for testing ---
if __name__ == "__main__":
    # Define the path to the sample PDF inside the data folder
    SAMPLE_PDF = os.path.join("data", "sample.pdf")
    
    # Check if the sample file exists
    if os.path.exists(SAMPLE_PDF):
        # Convert the first page (page 0)
        convert_pdf_page_to_image(pdf_path=SAMPLE_PDF, page_number=0)
    else:
        print(f"Please add a PDF file named '{SAMPLE_PDF}' to your project folder to run this test.")