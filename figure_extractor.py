"""Extract figures from preprint PDFs for Bluesky posts."""

import io
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass

import fitz  # PyMuPDF
import requests
from PIL import Image


@dataclass
class ExtractedFigure:
    """Represents an extracted figure from a PDF."""
    image_bytes: bytes
    width: int
    height: int
    format: str = "PNG"
    page_num: int = 0
    description: str = ""


def download_pdf_to_bytes(url: str) -> Optional[bytes]:
    """Download PDF from URL and return bytes."""
    try:
        response = requests.get(url, timeout=60, headers={
            "User-Agent": "BioSkyPoster/1.0 (Academic Research Bot)"
        })
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        print(f"Error downloading PDF: {e}")
        return None


def extract_figure_from_pdf(
    pdf_bytes: bytes,
    min_width: int = 200,
    min_height: int = 200,
    prefer_first_page: bool = True
) -> Optional[ExtractedFigure]:
    """Extract the best figure from a PDF.

    Strategy:
    1. Look for large images on the first page (potential graphical abstract)
    2. Fall back to the first substantial figure in the document

    Args:
        pdf_bytes: PDF content as bytes
        min_width: Minimum image width to consider
        min_height: Minimum image height to consider
        prefer_first_page: Prioritize images from first page

    Returns:
        ExtractedFigure or None if no suitable figure found
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return None

    best_image: Optional[ExtractedFigure] = None
    best_score = 0

    # Scoring function: larger images score higher, first page gets bonus
    def score_image(width: int, height: int, page_num: int) -> float:
        area_score = width * height
        page_bonus = 2.0 if page_num == 0 and prefer_first_page else 1.0
        # Prefer landscape or square images (better for social media)
        aspect_ratio = width / height if height > 0 else 1
        aspect_bonus = 1.2 if 0.5 <= aspect_ratio <= 2.0 else 1.0
        return area_score * page_bonus * aspect_bonus

    for page_num in range(min(len(doc), 10)):  # Check first 10 pages max
        page = doc[page_num]

        # Get images from page
        image_list = page.get_images(full=True)

        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]

            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                width = base_image["width"]
                height = base_image["height"]

                # Skip small images (likely icons or logos)
                if width < min_width or height < min_height:
                    continue

                # Skip very thin images (likely lines or borders)
                if width / height > 10 or height / width > 10:
                    continue

                # Calculate score
                score = score_image(width, height, page_num)

                if score > best_score:
                    best_score = score

                    # Convert and compress for Bluesky
                    try:
                        img = Image.open(io.BytesIO(image_bytes))
                        # Convert to RGB if necessary (handles CMYK, etc.)
                        if img.mode not in ("RGB", "RGBA"):
                            img = img.convert("RGB")

                        # Resize if too large (Bluesky has size limits)
                        max_dimension = 2000
                        if img.width > max_dimension or img.height > max_dimension:
                            ratio = max_dimension / max(img.width, img.height)
                            new_size = (int(img.width * ratio), int(img.height * ratio))
                            img = img.resize(new_size, Image.LANCZOS)

                        # Bluesky limit is ~1MB (976KB), target 900KB to be safe
                        max_size_bytes = 900 * 1024

                        # Try PNG first
                        output = io.BytesIO()
                        img.save(output, format="PNG", optimize=True)
                        png_bytes = output.getvalue()

                        # If PNG is too large, use JPEG with progressive quality reduction
                        img_format = "PNG"
                        if len(png_bytes) > max_size_bytes:
                            print(f"    PNG too large ({len(png_bytes) / 1024:.0f}KB), compressing to JPEG...")
                            # Convert to RGB for JPEG (no alpha)
                            if img.mode == "RGBA":
                                img = img.convert("RGB")

                            # Try decreasing quality until it fits
                            for quality in [85, 75, 65, 55, 45]:
                                output = io.BytesIO()
                                img.save(output, format="JPEG", quality=quality, optimize=True)
                                if len(output.getvalue()) <= max_size_bytes:
                                    png_bytes = output.getvalue()
                                    img_format = "JPEG"
                                    break

                            # If still too large, also reduce dimensions
                            if len(output.getvalue()) > max_size_bytes:
                                for scale in [0.75, 0.5, 0.4, 0.3]:
                                    new_size = (int(img.width * scale), int(img.height * scale))
                                    resized = img.resize(new_size, Image.LANCZOS)
                                    output = io.BytesIO()
                                    resized.save(output, format="JPEG", quality=70, optimize=True)
                                    if len(output.getvalue()) <= max_size_bytes:
                                        png_bytes = output.getvalue()
                                        img = resized
                                        img_format = "JPEG"
                                        break

                        best_image = ExtractedFigure(
                            image_bytes=png_bytes,
                            width=img.width,
                            height=img.height,
                            format=img_format,
                            page_num=page_num,
                            description=f"Figure from page {page_num + 1}"
                        )
                    except Exception as e:
                        print(f"Error processing image: {e}")
                        continue

            except Exception as e:
                print(f"Error extracting image {img_index} from page {page_num}: {e}")
                continue

    doc.close()

    if best_image:
        print(f"Extracted figure: {best_image.width}x{best_image.height} from page {best_image.page_num + 1}")
    else:
        print("No suitable figure found in PDF")

    return best_image


def extract_figure_from_url(pdf_url: str) -> Optional[ExtractedFigure]:
    """Download PDF and extract the best figure.

    Args:
        pdf_url: URL of the PDF

    Returns:
        ExtractedFigure or None
    """
    print(f"Downloading PDF from {pdf_url}...")
    pdf_bytes = download_pdf_to_bytes(pdf_url)

    if pdf_bytes is None:
        return None

    return extract_figure_from_pdf(pdf_bytes)


def save_figure(figure: ExtractedFigure, output_path: str) -> bool:
    """Save extracted figure to a file.

    Args:
        figure: The extracted figure
        output_path: Path to save the image

    Returns:
        True if successful
    """
    try:
        with open(output_path, "wb") as f:
            f.write(figure.image_bytes)
        print(f"Saved figure to {output_path}")
        return True
    except Exception as e:
        print(f"Error saving figure: {e}")
        return False


if __name__ == "__main__":
    # Test with a sample preprint
    from biorxiv_scraper import BiorxivScraper
    from preprint_selector import select_best_preprint

    scraper = BiorxivScraper(days_back=7)
    preprints = scraper.fetch_preprints()

    if preprints:
        selected = select_best_preprint(preprints[:5])  # Test with first 5
        if selected:
            print(f"\nExtracting figure from: {selected.title[:60]}...")
            figure = extract_figure_from_url(selected.pdf_url)

            if figure:
                output_path = f"/tmp/test_figure.png"
                save_figure(figure, output_path)
                print(f"Figure saved to {output_path}")
