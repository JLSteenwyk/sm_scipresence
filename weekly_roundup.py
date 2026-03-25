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
from linkedin_poster import LinkedInPoster
from posting_history import get_posts_from_last_n_days


STOP_SLOP_DIR = Path(__file__).parent / "stop_slop"
HUMANIZER_DIR = Path(__file__).parent / "humanizer"


def load_writing_rules() -> str:
    """Load all writing quality rules (stop_slop + humanizer)."""
    rules = []
    for filename in ["skills.md", "phrases.md", "structures.md", "examples.md"]:
        filepath = STOP_SLOP_DIR / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                rules.append(f.read())
    for filename in ["patterns.md", "voice.md"]:
        filepath = HUMANIZER_DIR / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                rules.append(f.read())
    return "\n\n".join(rules)


def generate_roundup(posts: list, dry_run: bool = False) -> tuple[list[str], list[str | None]] | None:
    """Generate a weekly roundup thread using Claude.

    Args:
        posts: List of post dicts from the week
        dry_run: If True, skip API call validation

    Returns:
        Tuple of (thread_posts, link_urls) or None on error.
        link_urls[i] is the URL for thread_posts[i], or None if no link.
    """
    if not posts:
        return None

    stop_slop_rules = load_writing_rules()

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

    system_prompt = f"""You are a science journalist on Bluesky writing a weekly roundup of preprints you highlighted this week. Your goal is to create a brief, engaging summary thread where each article gets its own post with a link.

WRITING RULES (stop_slop):
{stop_slop_rules}

CRITICAL FRAMING RULES:
- You are REPORTING on research done by others, not presenting your own work
- NEVER use "we" - you did not do this research
- Use framing like "researchers", "teams", "studies showed"
- Write as a curator highlighting others' work

TASK: Generate a roundup thread. The thread has this structure:
- First section: an intro blurb (under 280 characters)
- Then one section per article: a brief, engaging summary of that article (under 220 characters each, because the article link will be appended automatically)
- Optionally, a closing section (under 280 characters)

Each section is separated by "---".

INTRO (section 1):
- Start with something like "This week in preprints:" or similar
- Mention how many papers were highlighted
- Hint at any connecting theme if one emerges naturally
- MUST be under 280 characters

ARTICLE SECTIONS (one per article, in the same order as provided):
- Write a brief, engaging 1-2 sentence summary of the article
- MUST be under 220 characters (a link will be appended automatically)
- Do NOT include the URL yourself

CLOSING (optional, final section):
- Invite discussion or a closing thought
- MUST be under 280 characters

FORMAT:
- Output each section separated by "---"
- The article sections MUST appear in the same order as the articles listed
- There must be exactly {len(posts)} article sections (one per article)
- No hashtags
- No emoji except sparingly if natural
- Be genuine and conversational, not performative
- NEVER use em-dashes, use commas or periods instead

Example for 3 articles:
This week in preprints: 3 papers spanning genomics to evolutionary dev bio.
---
Researchers found mushroom psilocybin evolved twice independently, a striking case of convergent evolution in fungi.
---
A clever CRISPR screen reveals new host-pathogen interaction mechanisms that could reshape how we think about infection.
---
Gorgeous single-cell atlases map gene expression across developing embryos with unprecedented resolution.
---
What caught your eye in preprints this week?"""

    user_prompt = f"""Generate a weekly roundup thread for these {len(posts)} preprints shared this week:

{posts_text}

Remember: intro + exactly {len(posts)} article summaries (each under 220 chars) + optional closing, separated by ---"""

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content = response.content[0].text.strip()

        # Parse the sections
        sections = [s.strip() for s in content.split("---") if s.strip()]

        if len(sections) < 1 + len(posts):
            print(f"Warning: expected at least {1 + len(posts)} sections (intro + articles), got {len(sections)}")
            return None

        # Build thread_posts and link_urls
        # Section 0 = intro, sections 1..N = articles, section N+1 = optional closing
        intro = sections[0]
        article_sections = sections[1:1 + len(posts)]
        closing_sections = sections[1 + len(posts):]

        # Collect article URLs in order
        article_urls = [post.get('web_url', '') or None for post in posts]

        # Validate lengths
        from post_generator import validate_thread_posts

        FULL_LIMIT = 280
        ARTICLE_LIMIT = 220  # leave room for "\n\n" + URL (~59 chars)

        # Validate intro
        intro_valid = validate_thread_posts(
            [intro],
            first_post_limit=FULL_LIMIT,
            other_post_limit=FULL_LIMIT,
        )

        # Validate each article post individually and track link mapping
        valid_article_posts = []
        article_link_map = []  # parallel to valid_article_posts
        for idx, article_text in enumerate(article_sections):
            validated = validate_thread_posts(
                [article_text],
                first_post_limit=ARTICLE_LIMIT,
                other_post_limit=ARTICLE_LIMIT,
            )
            for j, vpost in enumerate(validated):
                valid_article_posts.append(vpost)
                # Only the first chunk of a split article gets the link
                article_link_map.append(article_urls[idx] if j == 0 else None)

        # Validate closing if present
        valid_closing = []
        if closing_sections:
            valid_closing = validate_thread_posts(
                closing_sections,
                first_post_limit=FULL_LIMIT,
                other_post_limit=FULL_LIMIT,
            )

        # Assemble final thread and parallel link_urls
        thread_posts = intro_valid + valid_article_posts + valid_closing
        link_urls: list[str | None] = (
            [None] * len(intro_valid)
            + article_link_map
            + [None] * len(valid_closing)
        )

        return (thread_posts, link_urls) if thread_posts else None

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
    result = generate_roundup(posts)

    if not result:
        print("Failed to generate roundup.")
        sys.exit(1)

    thread, link_urls = result

    print(f"\n--- Generated Thread ({len(thread)} posts) ---")
    for i, post in enumerate(thread):
        url = link_urls[i] if i < len(link_urls) else None
        url_len = len(f"\n\n{url}") if url else 0
        print(f"\nPost {i+1} ({len(post)} chars, {len(post) + url_len} with link):")
        print(post)
        if url:
            print(f"  Link: {url}")

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN: Skipping actual posting")
        print("=" * 60)
    else:
        print("\nPosting thread to Bluesky...")
        try:
            poster = BlueskyPoster()

            # Post as a thread with per-post links
            uris = poster.post_thread(thread, link_urls=link_urls)

            if uris:
                print(f"\nPosted roundup thread to Bluesky!")
                for i, uri in enumerate(uris, 1):
                    print(f"  Post {i}: {uri}")
            else:
                print("Failed to post thread to Bluesky")
                sys.exit(1)

        except Exception as e:
            print(f"Bluesky error: {e}")
            sys.exit(1)

        # Post to LinkedIn (non-blocking)
        print("\nPosting roundup to LinkedIn...")
        try:
            linkedin_poster = LinkedInPoster()
            linkedin_success = linkedin_poster.post_thread(thread, link_urls=link_urls)

            if linkedin_success:
                print("Posted roundup to LinkedIn!")
            else:
                print("Warning: Failed to post roundup to LinkedIn")
        except Exception as e:
            print(f"Warning: LinkedIn posting failed: {e}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
