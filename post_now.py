#!/usr/bin/env python3
"""Post immediately to Bluesky from a manuscript PDF and link.

This script allows posting right away without the scheduled timing.
Usage:
    python post_now.py path/to/manuscript.pdf "https://link-to-manuscript"
    python post_now.py manuscript.pdf "https://doi.org/..." --title "Paper Title" --abstract "Abstract text"
    python post_now.py manuscript.pdf "https://doi.org/..." --thread  # Force thread mode
    python post_now.py manuscript.pdf "https://doi.org/..." --dry-run  # Preview without posting
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from dotenv import load_dotenv

from biorxiv_scraper import Preprint
from bluesky_poster import BlueskyPoster
from linkedin_poster import LinkedInPoster
from figure_extractor import extract_figure_from_pdf, ExtractedFigure
from post_generator import generate_post, count_graphemes


def extract_metadata_from_pdf(pdf_path: str) -> tuple[Optional[str], Optional[str]]:
    """Try to extract title and abstract from PDF metadata or first page.

    Returns:
        Tuple of (title, abstract) - either may be None
    """
    try:
        doc = fitz.open(pdf_path)

        # Try PDF metadata first
        metadata = doc.metadata
        title = metadata.get("title", "").strip() if metadata else None

        # Try to get abstract from first page text
        abstract = None
        if len(doc) > 0:
            first_page_text = doc[0].get_text()

            # Look for "Abstract" section
            abstract_markers = ["Abstract", "ABSTRACT", "Summary", "SUMMARY"]
            for marker in abstract_markers:
                if marker in first_page_text:
                    idx = first_page_text.find(marker)
                    # Get text after the marker
                    after_marker = first_page_text[idx + len(marker):].strip()
                    # Take first ~1500 characters as abstract (roughly one paragraph)
                    if after_marker:
                        # Try to find end of abstract (next section header or significant break)
                        lines = after_marker.split('\n')
                        abstract_lines = []
                        char_count = 0
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            # Stop at likely section headers
                            if line.isupper() and len(line) > 5:
                                break
                            if line.startswith("Introduction") or line.startswith("INTRODUCTION"):
                                break
                            if line.startswith("Keywords") or line.startswith("KEYWORDS"):
                                break
                            abstract_lines.append(line)
                            char_count += len(line)
                            if char_count > 1500:
                                break
                        if abstract_lines:
                            abstract = " ".join(abstract_lines)
                    break

        doc.close()
        return title, abstract

    except Exception as e:
        print(f"Warning: Could not extract metadata from PDF: {e}")
        return None, None


def read_pdf_file(pdf_path: str) -> Optional[bytes]:
    """Read PDF file and return bytes."""
    try:
        with open(pdf_path, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Post immediately to Bluesky from a manuscript PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python post_now.py paper.pdf "https://doi.org/10.1101/2024.01.01.123456"
  python post_now.py paper.pdf "https://arxiv.org/abs/2401.00001" --title "My Paper Title"
  python post_now.py paper.pdf "https://example.com/paper" --title "Title" --abstract "Abstract..."
  python post_now.py paper.pdf "https://example.com/paper" --thread --dry-run
        """
    )

    parser.add_argument("pdf_path", help="Path to the manuscript PDF file")
    parser.add_argument("manuscript_url", help="URL link to the manuscript")
    parser.add_argument("--title", "-t", help="Paper title (auto-extracted from PDF if not provided)")
    parser.add_argument("--abstract", "-a", help="Paper abstract (auto-extracted from PDF if not provided)")
    parser.add_argument("--authors", help="Author names (optional)")
    parser.add_argument("--category", default="research", help="Category/field (default: research)")
    parser.add_argument("--thread", action="store_true", help="Force thread mode (3-5 posts)")
    parser.add_argument("--dry-run", action="store_true", help="Preview post without actually posting")
    parser.add_argument("--no-image", action="store_true", help="Skip figure extraction")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Validate PDF path
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    if not pdf_path.suffix.lower() == ".pdf":
        print(f"Warning: File does not have .pdf extension: {pdf_path}")

    print(f"Reading PDF: {pdf_path}")

    # Read PDF bytes
    pdf_bytes = read_pdf_file(str(pdf_path))
    if pdf_bytes is None:
        print("Error: Failed to read PDF file")
        sys.exit(1)

    print(f"PDF size: {len(pdf_bytes) / 1024 / 1024:.1f} MB")

    # Get title and abstract
    title = args.title
    abstract = args.abstract

    if not title or not abstract:
        print("Extracting metadata from PDF...")
        extracted_title, extracted_abstract = extract_metadata_from_pdf(str(pdf_path))

        if not title:
            title = extracted_title
        if not abstract:
            abstract = extracted_abstract

    # Fallbacks if still missing
    if not title:
        title = pdf_path.stem.replace("_", " ").replace("-", " ").title()
        print(f"Warning: Using filename as title: {title}")

    if not abstract:
        abstract = "Research manuscript."
        print("Warning: No abstract found, using placeholder")

    if args.verbose:
        print(f"\nTitle: {title}")
        print(f"Abstract: {abstract[:200]}...")
        print(f"URL: {args.manuscript_url}")

    # Create Preprint object for post generation
    preprint = Preprint(
        doi="manual-post",
        title=title,
        authors=args.authors or "Authors",
        abstract=abstract,
        category=args.category,
        date="",
        pdf_url="",
        web_url=args.manuscript_url,
    )

    # Extract figure from PDF
    figure: Optional[ExtractedFigure] = None
    if not args.no_image:
        print("\nExtracting figure from PDF...")
        figure = extract_figure_from_pdf(pdf_bytes)
        if figure:
            print(f"Extracted figure: {figure.width}x{figure.height} {figure.format}")
        else:
            print("No suitable figure found in PDF")

    # Generate post using Claude
    print("\nGenerating post with Claude...")

    # Check if PDF is too large for Claude
    MAX_PDF_SIZE = 10 * 1024 * 1024  # 10MB
    pdf_for_claude = pdf_bytes if len(pdf_bytes) <= MAX_PDF_SIZE else None

    if pdf_for_claude is None and len(pdf_bytes) > MAX_PDF_SIZE:
        print(f"PDF too large for Claude ({len(pdf_bytes) / 1024 / 1024:.1f} MB), using abstract-only mode")

    post = generate_post(
        preprint=preprint,
        thread_mode=args.thread,
        pdf_content=pdf_for_claude
    )

    if not post:
        print("Error: Failed to generate post")
        sys.exit(1)

    # Display the generated post
    print("\n" + "=" * 60)
    if post.is_thread:
        print("GENERATED THREAD:")
        for i, p in enumerate(post.posts, 1):
            print(f"\n--- Post {i} ({count_graphemes(p)} graphemes) ---")
            print(p)
    else:
        print(f"GENERATED POST ({count_graphemes(post.text)} graphemes):")
        print(post.text)
    print("\n" + "=" * 60)
    print(f"Link: {args.manuscript_url}")
    if figure:
        print(f"Image: {figure.width}x{figure.height} {figure.format} ({len(figure.image_bytes) / 1024:.0f} KB)")

    # Dry run - stop here
    if args.dry_run:
        print("\n[DRY RUN] Post not sent to Bluesky")
        return

    # Confirm before posting
    print("\n")
    response = input("Post to Bluesky and LinkedIn? [y/N]: ").strip().lower()
    if response != "y":
        print("Cancelled.")
        return

    # Post to Bluesky
    print("\nPosting to Bluesky...")
    poster = BlueskyPoster()

    if not poster.login():
        print("Error: Failed to login to Bluesky")
        sys.exit(1)

    uris = poster.post(
        bluesky_post=post,
        link_url=args.manuscript_url,
        image=figure,
        image_alt=f"Figure from: {title[:100]}"
    )

    if uris:
        print("\nSuccess! Posted to Bluesky:")
        for uri in uris:
            print(f"  {uri}")
    else:
        print("\nError: Failed to post to Bluesky")
        sys.exit(1)

    # Post to LinkedIn (non-blocking)
    print("\nPosting to LinkedIn...")
    try:
        linkedin_poster = LinkedInPoster()
        linkedin_success = linkedin_poster.post(
            bluesky_post=post,
            link_url=args.manuscript_url,
            image=figure,
            image_alt=f"Figure from: {title[:100]}"
        )
        if linkedin_success:
            print("Success! Posted to LinkedIn")
        else:
            print("Warning: Failed to post to LinkedIn (Bluesky post was successful)")
    except Exception as e:
        print(f"Warning: LinkedIn posting failed: {e} (Bluesky post was successful)")


if __name__ == "__main__":
    main()
