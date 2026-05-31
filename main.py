# main.py
import os
import pymupdf as fitz  # PyMuPDF
import csv
import cv2

# Import our custom modules
from utils import load_template
from pdf_processing import convert_page_to_image
from image_processing import align_card_to_template, extract_fields_from_image, find_and_extract_single_field
from ocr_processing import get_text_from_image
from post_processing import clean_accession_number, clean_botanical_name, clean_propagation_notes

if __name__ == "__main__":
    # --- Configuration ---
    SAMPLE_PDF = os.path.join("data", "sample.pdf")
    OUTPUT_FOLDER = "output_images"
    FIELDS_FOLDER = os.path.join(OUTPUT_FOLDER, "fields")
    TEMPLATE_FILE = "template.json"
    ANCHOR_TEMPLATE_PATHS = [
        os.path.join("templates", "anchor_v1.png"),
        os.path.join("templates", "anchor_v2.png"),
    ]
    TARGET_ANCHOR_OFFSET = (60, 150)
    
    # --- Main Script ---
    all_cards_data = []
    failed_card_images = []
    fields_to_extract = load_template(TEMPLATE_FILE)
    
    accession_field_def = next((field for field in fields_to_extract if field['name'] == 'Accession Number'), None)

    if not fields_to_extract or not accession_field_def:
        print("Could not load template or 'Accession Number' is not defined in it. Exiting.")
    elif not os.path.exists(SAMPLE_PDF):
        print(f"Error: PDF file not found at '{SAMPLE_PDF}'")
    else:
        doc = fitz.open(SAMPLE_PDF)
        print(f"Processing {doc.page_count} pages from '{os.path.basename(SAMPLE_PDF)}'...")

        for page_num in range(doc.page_count):
            # ... (the main processing loop is the same) ...
            print(f"\n--- Processing Page {page_num} ---")
            card_data = {'Source': f"{os.path.basename(SAMPLE_PDF)}_page_{page_num}"}

            raw_card_image_path = convert_page_to_image(doc=doc, page_number=page_num, output_folder=OUTPUT_FOLDER)
            if not raw_card_image_path: continue

            aligned_card_image_path = align_card_to_template(card_image_path=raw_card_image_path, anchor_template_paths=ANCHOR_TEMPLATE_PATHS, output_folder=OUTPUT_FOLDER, target_offset=TARGET_ANCHOR_OFFSET)
            if not aligned_card_image_path:
                failed_card_images.append(raw_card_image_path)
                continue

            accession_path = find_and_extract_single_field(aligned_card_image_path, accession_field_def, FIELDS_FOLDER)
            
            if not accession_path:
                failed_card_images.append(raw_card_image_path)
                continue
            
            raw_accession_text = get_text_from_image(accession_path)
            cleaned_accession = clean_accession_number(raw_accession_text)
            card_data['Accession Number'] = cleaned_accession

            other_fields_def = [f for f in fields_to_extract if f['name'] != 'Accession Number']
            extracted_field_paths = extract_fields_from_image(card_image_path=aligned_card_image_path, fields=other_fields_def, output_folder=FIELDS_FOLDER)
            
            for field_name, field_path in extracted_field_paths.items():
                raw_text = get_text_from_image(field_path)
                cleaned_text = raw_text.strip().replace('\n', ' ')
                card_data[field_name] = cleaned_text
            
            all_cards_data.append(card_data)
        
        doc.close()

        # --- Define Reports Folder ---  <<<--- FIX IS HERE
        REPORTS_FOLDER = 'reports'
        os.makedirs(REPORTS_FOLDER, exist_ok=True)

        # --- Write Successful Data to CSV ---
        if all_cards_data:
            output_csv_path = os.path.join(REPORTS_FOLDER, 'output.csv')
            all_headers = {key for card in all_cards_data for key in card.keys()}
            pre_ordered_headers = ['Accession Number', 'Source', 'Botanical Name', 'Propagation']
            ordered_headers = [h for h in pre_ordered_headers if h in all_headers] + sorted([h for h in all_headers if h not in pre_ordered_headers])

            with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=ordered_headers)
                writer.writeheader()
                writer.writerows(all_cards_data)
            print(f"\nProcessing complete. Data saved to {output_csv_path}")

        # --- Create "Review" PDF from Failures ---
        if failed_card_images:
            review_pdf_path = os.path.join(REPORTS_FOLDER, 'review_failures.pdf')
            review_doc = fitz.open()
            for image_path in failed_card_images:
                img = fitz.open(image_path)
                rect = img[0].rect
                pdf_bytes = img.convert_to_pdf()
                img.close()
                
                img_pdf = fitz.open("pdf", pdf_bytes)
                review_doc.insert_pdf(img_pdf)
            
            review_doc.save(review_pdf_path)
            print(f"Saved {len(failed_card_images)} failed cards to {review_pdf_path} for manual review.")