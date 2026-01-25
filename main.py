#!/usr/bin/env python3
"""Main CLI script for posting bioRxiv preprints to Bluesky.

Usage:
    python main.py                    # Single post mode (default)
    python main.py --thread           # Thread mode
    python main.py --dry-run          # Preview without posting
    python main.py --days 14          # Look back 14 days instead of 7
"""

import argparse
import sys
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from biorxiv_scraper import BiorxivScraper
from preprint_selector import select_best_preprint, select_ranked_preprints, save_posted_preprint
from post_generator import generate_post, download_pdf
from figure_extractor import extract_figure_from_pdf
from bluesky_poster import BlueskyPoster
from framing_question import save_preprint_for_followup
from posting_history import save_to_history


def main():
    parser = argparse.ArgumentParser(
        description="Post bioRxiv preprints to Bluesky",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                    # Post a single-post summary
    python main.py --thread           # Post a thread with more detail
    python main.py --dry-run          # Preview the post without publishing
    python main.py --days 14          # Search preprints from last 14 days
        """
    )

    parser.add_argument(
        "--thread",
        action="store_true",
        help="Generate a thread instead of a single post"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and display the post without actually posting to Bluesky"
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back for preprints (default: 7)"
    )

    parser.add_argument(
        "--no-image",
        action="store_true",
        help="Skip extracting and posting a figure from the PDF"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    # Step 1: Scrape bioRxiv for preprints
    print("=" * 60)
    print("STEP 1: Scraping bioRxiv for relevant preprints...")
    print("=" * 60)

    scraper = BiorxivScraper(days_back=args.days)
    preprints = scraper.fetch_preprints()

    if not preprints:
        print("No preprints found matching target themes. Exiting.")
        sys.exit(1)

    print(f"Found {len(preprints)} preprints matching target themes")

    # Step 2: Rank preprints using Claude
    print("\n" + "=" * 60)
    print("STEP 2: Ranking preprints by scientific merit...")
    print("=" * 60)

    ranked_preprints = select_ranked_preprints(preprints, top_n=5)

    if not ranked_preprints:
        print("No suitable preprints found. Exiting.")
        sys.exit(1)

    # Step 3 & 4: Try each ranked preprint until we find one with an extractable figure
    print("\n" + "=" * 60)
    print("STEP 3-4: Finding preprint with extractable figure...")
    print("=" * 60)

    selected = None
    pdf_content = None
    figure = None

    if args.no_image:
        # If no image mode, just use the top-ranked preprint
        print("--no-image mode: using top-ranked preprint")
        selected = ranked_preprints[0]
        pdf_content = download_pdf(selected.pdf_url)
    else:
        # Try each ranked preprint until we find one with a figure
        for i, candidate in enumerate(ranked_preprints, 1):
            print(f"\nTrying candidate {i}/{len(ranked_preprints)}: {candidate.title[:50]}...")

            # Download PDF
            candidate_pdf = download_pdf(candidate.pdf_url)
            if not candidate_pdf:
                print("  Could not download PDF, trying next...")
                continue

            # Try to extract figure
            candidate_figure = extract_figure_from_pdf(candidate_pdf)
            if candidate_figure:
                print(f"  Found figure: {candidate_figure.width}x{candidate_figure.height} pixels")
                selected = candidate
                pdf_content = candidate_pdf
                figure = candidate_figure
                break
            else:
                print("  No suitable figure found, trying next...")

        # Fall back to top-ranked preprint if no figures found
        if not selected:
            print("\nNo preprints with extractable figures found.")
            print("Falling back to top-ranked preprint without figure.")
            selected = ranked_preprints[0]
            pdf_content = download_pdf(selected.pdf_url)

    print(f"\nSelected preprint:")
    print(f"  Title: {selected.title}")
    print(f"  Authors: {selected.authors[:80]}...")
    print(f"  Category: {selected.category}")
    print(f"  Date: {selected.date}")
    print(f"  DOI: {selected.doi}")
    print(f"  URL: {selected.web_url}")
    if figure:
        print(f"  Figure: {figure.width}x{figure.height} pixels")

    # Step 5: Generate post using Claude
    print("\n" + "=" * 60)
    print(f"STEP 5: Generating {'thread' if args.thread else 'post'} with Claude...")
    print("=" * 60)

    post = generate_post(
        selected,
        thread_mode=args.thread,
        pdf_content=pdf_content
    )

    if not post:
        print("Failed to generate post. Exiting.")
        sys.exit(1)

    # Display the generated post
    print("\n--- Generated Content ---")
    if post.is_thread:
        if not args.thread:
            print("(Auto-converted to thread due to content length)")
        for i, p in enumerate(post.posts, 1):
            print(f"\nPost {i} ({len(p)} chars):")
            print(p)
    else:
        print(f"\nPost ({len(post.text)} chars):")
        print(post.text)

    print(f"\nLink: {selected.web_url}")
    if figure:
        print(f"Image: {figure.width}x{figure.height} PNG attached")

    # Step 6: Post to Bluesky (unless dry-run)
    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN: Skipping actual posting to Bluesky")
        print("=" * 60)
        print("\nTo post for real, run without --dry-run")
    else:
        print("\n" + "=" * 60)
        print("STEP 6: Posting to Bluesky...")
        print("=" * 60)

        try:
            poster = BlueskyPoster()
            uris = poster.post(
                post,
                link_url=selected.web_url,
                image=figure,
                image_alt=f"Figure from: {selected.title[:100]}"
            )

            if uris:
                print("\nSuccessfully posted to Bluesky!")
                for i, uri in enumerate(uris, 1):
                    print(f"  Post {i}: {uri}")

                # Save the preprint as posted
                save_posted_preprint(selected.doi)
                print(f"\nMarked {selected.doi} as posted")

                # Save preprint info for afternoon follow-up (include post URI for replies)
                save_preprint_for_followup({
                    "doi": selected.doi,
                    "title": selected.title,
                    "abstract": selected.abstract,
                    "category": selected.category,
                    "web_url": selected.web_url,
                    "post_uri": uris[0],  # First post URI (or only post for single)
                    "root_uri": uris[0],  # Root of thread
                    "last_uri": uris[-1],  # Last post in thread (for replying to end)
                })
                print("Saved preprint info for afternoon follow-up")

                # Save to posting history for weekly roundups
                save_to_history({
                    "doi": selected.doi,
                    "title": selected.title,
                    "abstract": selected.abstract,
                    "category": selected.category,
                    "web_url": selected.web_url,
                    "authors": selected.authors,
                })
                print("Saved to posting history")
            else:
                print("\nFailed to post to Bluesky")
                sys.exit(1)

        except ValueError as e:
            print(f"\nError: {e}")
            print("Make sure BLUESKY_USERNAME and BLUESKY_PASSWORD are set in your environment")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
