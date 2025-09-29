# utils.py
import json

def load_template(template_path="template.json"):
    """Loads the field coordinates from the JSON template file."""
    try:
        with open(template_path, 'r') as f:
            template = json.load(f)
        return template.get("fields", [])
    except FileNotFoundError:
        print(f"Error: Template file not found at '{template_path}'")
        return None
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{template_path}'")
        return None