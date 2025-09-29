# image_processing.py
import cv2
import os

def extract_fields_from_image(card_image_path, fields, output_folder="output_images/fields"):
    """Crops individual fields from a card image based on template coordinates."""
    os.makedirs(output_folder, exist_ok=True)
    image = cv2.imread(card_image_path)
    if image is None:
        print(f"Could not read image: {card_image_path}")
        return

    base_name = os.path.basename(card_image_path).replace('.png', '')

    for field in fields:
        name = field['name']
        coords = field['coordinates']
        x, y, w, h = coords['x'], coords['y'], coords['width'], coords['height']

        field_image = image[y:y+h, x:x+w]
        
        safe_name = "".join(c for c in name if c.isalnum()).rstrip()
        field_output_path = os.path.join(output_folder, f"{base_name}_{safe_name}.png")
        cv2.imwrite(field_output_path, field_image)
    
    print(f"Extracted {len(fields)} fields from {os.path.basename(card_image_path)}")