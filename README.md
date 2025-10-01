# Propagation Card Reader

This project is a Python tool to automate data extraction from digitized propagation card files using OCR and export the results to a CSV.

## Getting Started

### Prerequisites

- [Miniforge](https://github.com/conda-forge/miniforge) or another Conda distribution.

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

---
_This README will be updated as new features are added._
