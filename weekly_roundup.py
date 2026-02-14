#!/usr/bin/env python3
"""Generate and post weekly roundup of shared preprints.

Posts a summary thread highlighting the week's preprints and any connecting themes.
Runs on Sundays.
"""

import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import anthropic

from bluesky_poster import BlueskyPoster
from posting_history import get_posts_from_last_n_days


STOP_SLOP_DIR = Path(__file__).parent / "stop_slop"


def load_stop_slop_rules() -> str:
    """Load stop_slop rules."""
    rules = []
    files = ["skills.md", "phrases.md", "structures.md", "examples.md"]
    for filename in files:
        filepath = STOP_SLOP_DIR / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                rules.append(f.read())
    return "\n\n".join(rules)


def generate_roundup(posts: list, dry_run: bool = False) -> list[str] | None:
    """Generate a weekly roundup thread using Claude.

    Args:
        posts: List of post dicts from the week
        dry_run: If True, skip API call validation

    Returns:
        List of post strings for a thread, or None on error
    """
    if not posts:
        return None

    stop_slop_rules = load_stop_slop_rules()

    # Build summaries of the week's posts
    post_summaries = []
    for i, post in enumerate(posts, 1):
        summary = f"""
{i}. {post.get('title', 'Unknown')}
   Category: {post.get('category', 'Unknown')}
   URL: {post.get('web_url', '')}
   Abstract snippet: {post.get('abstract', '')[:300]}...
"""
        post_summaries.append(summary)

    posts_text = "\n".join(post_summaries)

    system_prompt = f"""You are a science journalist on Bluesky writing a weekly roundup of preprints you highlighted this week. Your goal is to create a brief, engaging summary thread.

WRITING RULES (stop_slop):
{stop_slop_rules}

CRITICAL FRAMING RULES:
- You are REPORTING on research done by others, not presenting your own work
- NEVER use "we" - you did not do this research
- Use framing like "researchers", "teams", "studies showed"
- Write as a curator highlighting others' work

TASK: Generate a 2-3 post thread summarizing this week's preprints:

POST 1 (intro):
- Start with something like "This week in preprints:" or similar
- Mention how many papers were highlighted
- Hint at any connecting theme if one emerges naturally
- MUST be under 280 characters

POST 2 (highlights):
- Brief 1-line mention of 2-3 standout papers (just title keywords + why interesting)
- Reference them casually, attributing to researchers when natural
- MUST be under 280 characters

POST 3 (optional, only if needed):
- Any remaining highlights or a closing thought
- Could invite discussion or ask what others found interesting this week
- MUST be under 280 characters

FORMAT:
- Output each post on its own line, separated by "---"
- No hashtags
- No emoji except sparingly if natural
- Be genuine and conversational, not performative
- NEVER use em-dashes, use commas or periods instead

Example output format:
This week in preprints: 6 papers spanning genomics to evolutionary dev bio. A few convergent evolution stories stood out.
---
Highlights: researchers showing mushroom psilocybin evolved twice independently, a clever CRISPR screen for host-pathogen interactions, and some gorgeous single-cell atlases.
---
What caught your eye in preprints this week?"""

    user_prompt = f"""Generate a weekly roundup thread for these {len(posts)} preprints shared this week:

{posts_text}

Remember: 2-3 posts, each under 280 characters, separated by ---"""

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content = response.content[0].text.strip()

        # Parse the posts
        thread_posts = [p.strip() for p in content.split("---") if p.strip()]

        # Validate lengths — split oversized posts, carrying remainder forward
        from post_generator import validate_thread_posts
        ROUNDUP_LIMIT = 280
        valid_posts = validate_thread_posts(
            thread_posts,
            first_post_limit=ROUNDUP_LIMIT,
            other_post_limit=ROUNDUP_LIMIT,
        )

        return valid_posts if valid_posts else None

    except Exception as e:
        print(f"Error generating roundup: {e}")
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Post weekly roundup thread")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    args = parser.parse_args()

    print("=" * 60)
    print("WEEKLY ROUNDUP")
    print("=" * 60)

    # Get this week's posts
    posts = get_posts_from_last_n_days(args.days)

    if not posts:
        print(f"\nNo posts found in the last {args.days} days. Skipping roundup.")
        sys.exit(0)

    print(f"\nFound {len(posts)} posts from the last {args.days} days:")
    for post in posts:
        print(f"  - {post.get('title', 'Unknown')[:60]}...")

    # Generate roundup thread
    print("\nGenerating roundup thread with Claude...")
    thread = generate_roundup(posts)

    if not thread:
        print("Failed to generate roundup.")
        sys.exit(1)

    print(f"\n--- Generated Thread ({len(thread)} posts) ---")
    for i, post in enumerate(thread, 1):
        print(f"\nPost {i} ({len(post)} chars):")
        print(post)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN: Skipping actual posting")
        print("=" * 60)
    else:
        print("\nPosting thread to Bluesky...")
        try:
            poster = BlueskyPoster()

            # Post as a thread
            uris = poster.post_thread(thread)

            if uris:
                print(f"\nPosted roundup thread successfully!")
                for i, uri in enumerate(uris, 1):
                    print(f"  Post {i}: {uri}")
            else:
                print("Failed to post thread")
                sys.exit(1)

        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
