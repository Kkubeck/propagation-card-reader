# image_processing.py
import cv2
import os
import numpy as np

def preprocess_field_for_ocr(field_image):
    """
    Cleans a field image for better OCR results using binarization.
    """
    # Convert the image to grayscale
    gray = cv2.cvtColor(field_image, cv2.COLOR_BGR2GRAY)
    
    # Apply Otsu's Binarization to create a black and white image
    _, processed_image = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # Invert the image to get black text on a white background
    processed_image = cv2.bitwise_not(processed_image)

    return processed_image

def align_card_to_template(card_image_path, anchor_template_paths, output_folder="output_images", target_offset=(0, 0), debug=False):
    """
    Aligns a card by trying a list of anchor templates and finding the best match.
    """
    try:
        image = cv2.imread(card_image_path)
        if image is None:
            print(f"Error: Could not read card image at {card_image_path}")
            return None

        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        best_match = {'max_val': -1, 'max_loc': None, 'template_shape': None}

        for template_path in anchor_template_paths:
            template = cv2.imread(template_path)
            if template is None:
                print(f"Warning: Could not read template at {template_path}, skipping.")
                continue
            
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            result = cv2.matchTemplate(image_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val > best_match['max_val']:
                best_match['max_val'] = max_val
                best_match['max_loc'] = max_loc
                best_match['template_shape'] = template.shape[:2]

        max_val = best_match['max_val']
        max_loc = best_match['max_loc']

        if debug:
            debug_image = image.copy()
            h, w = best_match['template_shape']
            top_left = max_loc
            bottom_right = (top_left[0] + w, top_left[1] + h)
            cv2.rectangle(debug_image, top_left, bottom_right, (0, 255, 0), 3)
            cv2.putText(debug_image, f"Confidence: {max_val:.2f}", (top_left[0], top_left[1] - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            debug_output_path = os.path.join(output_folder, os.path.basename(card_image_path).replace('.png', '_debug_match.png'))
            cv2.imwrite(debug_output_path, debug_image)
            print(f"Debug image saved to {debug_output_path}")

        if max_val < 0.6:
            print(f"Warning: Best match confidence ({max_val:.2f}) is below threshold. Skipping alignment.")
            return None

        detected_x, detected_y = max_loc
        shift_x = target_offset[0] - detected_x
        shift_y = target_offset[1] - detected_y

        M = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
        aligned_image = cv2.warpAffine(image, M, (image.shape[1], image.shape[0]), borderValue=(255, 255, 255))
        
        aligned_output_path = os.path.join(output_folder, os.path.basename(card_image_path).replace('.png', '_aligned.png'))
        cv2.imwrite(aligned_output_path, aligned_image)
        print(f"Aligned image saved to {aligned_output_path} with confidence {max_val:.2f}")
        return aligned_output_path

    except Exception as e:
        print(f"An error occurred during image alignment for {card_image_path}: {e}")
        return None

def extract_fields_from_image(card_image_path, fields, output_folder="output_images/fields"):
    """
    Dynamically finds each field using template matching for its label, then
    applies a relative offset to crop the data.
    """
    os.makedirs(output_folder, exist_ok=True)
    image = cv2.imread(card_image_path)
    if image is None:
        print(f"Could not read image: {card_image_path}")
        return

    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    base_name = os.path.basename(card_image_path).replace('_aligned.png', '')

    for field in fields:
        name = field['name']
        label_templates = field['label_templates']
        offset = field['data_offset']

        best_match = {'max_val': -1, 'max_loc': None}

        for template_path in label_templates:
            template = cv2.imread(template_path, 0)
            if template is None:
                print(f"Warning: Could not read label template at {template_path}, skipping.")
                continue
            
            result = cv2.matchTemplate(image_gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val > best_match['max_val']:
                best_match['max_val'] = max_val
                best_match['max_loc'] = max_loc
        
        if best_match['max_val'] > 0.7:
            label_x, label_y = best_match['max_loc']
            
            data_x = label_x + offset['x']
            data_y = label_y + offset['y']
            data_w = offset['width']
            data_h = offset['height']
            
            field_image = image[data_y : data_y + data_h, data_x : data_x + data_w]
            
            processed_field = preprocess_field_for_ocr(field_image)
            
            safe_name = "".join(c for c in name if c.isalnum()).rstrip()
            field_output_path = os.path.join(output_folder, f"{base_name}_{safe_name}.png")
            cv2.imwrite(field_output_path, processed_field)
            print(f"Successfully extracted field: {name} (Confidence: {best_match['max_val']:.2f})")
        else:
            print(f"Warning: Could not find a confident match for field '{name}' on {base_name}. Best score: {best_match['max_val']:.2f}")