# ocr_processing.py
import io
from google.cloud import vision

def get_text_from_image(image_path):
    """
    Uses the Google Cloud Vision API to perform OCR on a single image.

    Args:
        image_path (str): The path to the image file.

    Returns:
        str: The extracted text, or an empty string if no text is found or an error occurs.
    """
    try:
        client = vision.ImageAnnotatorClient()

        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()

        image = vision.Image(content=content)

        # The 'text_detection' feature performs OCR
        response = client.text_detection(image=image)
        texts = response.text_annotations

        if response.error.message:
            raise Exception(
                f'{response.error.message}\nFor more info on error messages, check: '
                'https://cloud.google.com/apis/design/errors'
            )

        # The first text annotation is the full text from the image
        if texts:
            return texts[0].description.strip()
        else:
            return "" # Return empty string if no text is found

    except Exception as e:
        print(f"An error occurred during OCR for {image_path}: {e}")
        return ""