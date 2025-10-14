# Propagation Card Reader

This project is a Python tool to automate data extraction from digitized propagation card files using OCR and export the results to a CSV.

[![View Project Website](https://img.shields.io/badge/View%20Website-Live-blue)](https://kkubeck.github.io/propagation-card-reader/)

## Getting Started

### Installation

1.  **Clone the repository:**
    ```sh
    git clone https://github.com/Kkubeck/propagation-card-reader.git
    cd propagation-card-reader
    ```

2.  **Create and activate the Conda environment:**
    ```sh
    conda env create -f environment.yml
    conda activate prop-card-reader
    ```

### History

- Initial Setup: Established the project with a Conda environment and Git repository.

- Module 1 (PDF to Image): Wrote the initial script to convert a single PDF page to a high-resolution PNG. This was later refactored to efficiently process all pages in a multi-page PDF.

- Initial Field Extraction Attempt: Created a template.json with fixed physical coordinates to crop fields. This approach failed due to slight misalignments in the scanned cards.

- Revised Module 2 (Image Alignment): Implemented a robust image alignment module using OpenCV's template matching.

- Started with a single, central anchor point.

- Developed a debug mode to visually diagnose matching errors.

- Evolved the function to use a multi-template approach, trying several anchor variations to find the best match.

- This resulted in 100% successful card alignment, solving the geometric positioning problem.

- Pivot to "Power Path": After successful alignment, it was discovered that the internal layout of the cards themselves varied, making a single fixed-coordinate template for fields unreliable. The project is now pivoting to a more dynamic approach: finding each field label individually using template matching.

- Iterative Tuning: Developed a workflow of testing, analyzing failures, and creating new, higher-quality templates (combining text and graphical features) to improve the success rate.

- High Success Rate Achieved: Reached a high success rate (90-98%) for key fields like "Accession Number" and "Botanical Name" across multiple test batches, proving the dynamic method is robust.

- System Expansion: Successfully expanded the system to extract additional, varied fields, including large text blocks like "Propagation.

- OCR Integration: Integrated the Google Cloud Vision API to perform handwritten and typed text recognition on the extracted and preprocessed field images.

- Post-Processing: Created a dedicated module for cleaning raw OCR text. Implemented a function using regular expressions (regex) to extract the structured 'Accession Number', achieving 100% accuracy on test data.

- Assembly & Output: Integrated all modules into the main script to create a full end-to-end pipeline. The script now outputs a clean output.csv file for successful extractions.

- Advanced Error Handling: Implemented "early exit" logic to skip processing cards where the key 'Accession Number' field cannot be found, saving API calls. Images of failed cards are compiled into a separate review_failures.pdf for manual review.

---