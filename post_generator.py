"""Generate Bluesky posts from preprints using Claude API with stop_slop rules."""

import base64
import tempfile
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

import anthropic
import requests

from biorxiv_scraper import Preprint


# Load stop_slop rules
STOP_SLOP_DIR = Path(__file__).parent / "stop_slop"


def load_stop_slop_rules() -> str:
    """Load all stop_slop rules into a single string for the prompt."""
    rules = []

    files = ["skills.md", "phrases.md", "structures.md", "examples.md"]
    for filename in files:
        filepath = STOP_SLOP_DIR / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                rules.append(f"## {filename}\n{f.read()}")

    return "\n\n".join(rules)


@dataclass
class BlueskyPost:
    """Represents a Bluesky post or thread."""
    posts: List[str]  # List of post texts (single item for regular post, multiple for thread)
    is_thread: bool

    @property
    def text(self) -> str:
        """Get the full text (first post for threads, only post for single)."""
        return self.posts[0] if self.posts else ""


def download_pdf(url: str) -> Optional[bytes]:
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


def _call_claude_for_post(
    preprint: Preprint,
    pdf_content: Optional[bytes],
    stop_slop_rules: str,
    thread_mode: bool,
    char_limit: int = 250,
    retry_attempt: bool = False
) -> Optional[str]:
    """Internal function to call Claude API for post generation.

    Returns the raw response text.
    """
    if thread_mode:
        format_instructions = """Generate a Bluesky THREAD (3-5 posts) about this preprint.

CRITICAL CONSTRAINTS:
- The FIRST post MUST be under 220 characters (a link will be appended)
- Posts 2-5 MUST each be under 280 characters
- The first post should hook readers
- Subsequent posts should expand on key findings
- Final post can include implications or significance

Format your response as:
POST 1: [text]
POST 2: [text]
POST 3: [text]
(etc.)"""
    else:
        strict_note = ""
        if retry_attempt:
            strict_note = f"""
IMPORTANT: Your previous attempt was too long. This time you MUST be under {char_limit} characters.
Count carefully. Be more concise. Cut unnecessary words."""

        format_instructions = f"""Generate a SINGLE Bluesky post about this preprint.

CRITICAL CONSTRAINTS:
- The post MUST be under {char_limit} characters (a link will be appended separately)
- Be concise and direct
- Focus on ONE key finding or contribution
- Every word must earn its place{strict_note}

Format your response as:
POST: [text]"""

    system_prompt = f"""You are a science communicator writing Bluesky posts about evolutionary biology, genomics, and bioinformatics preprints. Your audience is scientists and science enthusiasts.

WRITING RULES (stop_slop):
{stop_slop_rules}

ADDITIONAL GUIDELINES:
- Write like a scientist sharing interesting work, not a marketer
- State findings directly without hype
- Avoid emoji unless absolutely natural
- No hashtags
- Be specific about what the research found
- Do not start with "New preprint:" or similar throat-clearing
- Do not use phrases like "This is huge" or "Game-changer"
- Vary your sentence structure
- Trust your reader's intelligence

{format_instructions}"""

    user_content = []

    # Add PDF if available
    if pdf_content:
        pdf_base64 = base64.standard_b64encode(pdf_content).decode("utf-8")
        user_content.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_base64,
            },
        })

    # Add text context
    context_text = f"""Preprint to summarize:

Title: {preprint.title}
Authors: {preprint.authors}
Category: {preprint.category}
Date: {preprint.date}

Abstract:
{preprint.abstract}

{"The full PDF is attached above. Use it to understand the methods and results in detail." if pdf_content else "No PDF available, use the abstract above."}

Generate the Bluesky {"thread" if thread_mode else "post"} now. Remember the character limits - this is critical."""

    user_content.append({"type": "text", "text": context_text})

    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    return response.content[0].text.strip()


def _parse_posts(response_text: str, thread_mode: bool) -> List[str]:
    """Parse the response text into a list of posts."""
    posts = []
    if thread_mode:
        # Parse thread format
        lines = response_text.split("\n")
        current_post = []
        for line in lines:
            if line.startswith("POST ") and ":" in line:
                if current_post:
                    posts.append(" ".join(current_post).strip())
                # Extract text after "POST N:"
                post_text = line.split(":", 1)[1].strip()
                current_post = [post_text] if post_text else []
            elif current_post is not None and line.strip():
                current_post.append(line.strip())
        if current_post:
            posts.append(" ".join(current_post).strip())
    else:
        # Parse single post format
        if response_text.startswith("POST:"):
            post_text = response_text[5:].strip()
        else:
            post_text = response_text
        posts = [post_text]

    return posts


def generate_post(
    preprint: Preprint,
    thread_mode: bool = False,
    pdf_content: Optional[bytes] = None
) -> Optional[BlueskyPost]:
    """Generate a Bluesky post (or thread) for a preprint using Claude API.

    Args:
        preprint: The preprint to generate a post for
        thread_mode: If True, generate a thread instead of single post
        pdf_content: Optional PDF bytes (will download if not provided)

    Returns:
        BlueskyPost object or None if generation fails
    """
    # Download PDF if not provided
    if pdf_content is None:
        print(f"Downloading PDF from {preprint.pdf_url}...")
        pdf_content = download_pdf(preprint.pdf_url)

    if pdf_content is None:
        print("Failed to download PDF, falling back to abstract-only mode")

    # Load stop_slop rules
    stop_slop_rules = load_stop_slop_rules()

    SINGLE_POST_LIMIT = 220  # Leave room for link
    THREAD_FIRST_POST_LIMIT = 220
    THREAD_OTHER_POST_LIMIT = 280

    try:
        if thread_mode:
            # Generate thread directly
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=True
            )
            posts = _parse_posts(response_text, thread_mode=True)

            # Validate thread posts
            valid = True
            for i, post in enumerate(posts):
                limit = THREAD_FIRST_POST_LIMIT if i == 0 else THREAD_OTHER_POST_LIMIT
                if len(post) > limit:
                    print(f"Warning: Thread post {i+1} exceeds {limit} chars ({len(post)})")
                    valid = False

            if not valid:
                print("Regenerating thread with stricter limits...")
                response_text = _call_claude_for_post(
                    preprint, pdf_content, stop_slop_rules,
                    thread_mode=True
                )
                posts = _parse_posts(response_text, thread_mode=True)

            return BlueskyPost(posts=posts, is_thread=True)

        else:
            # Try to generate a single post
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=False, char_limit=SINGLE_POST_LIMIT
            )
            posts = _parse_posts(response_text, thread_mode=False)

            if posts and len(posts[0]) <= SINGLE_POST_LIMIT:
                # Success - single post fits
                return BlueskyPost(posts=posts, is_thread=False)

            # Post too long - retry with stricter instructions
            print(f"Post too long ({len(posts[0])} chars), retrying with stricter limit...")
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=False, char_limit=SINGLE_POST_LIMIT, retry_attempt=True
            )
            posts = _parse_posts(response_text, thread_mode=False)

            if posts and len(posts[0]) <= SINGLE_POST_LIMIT:
                # Success on retry
                return BlueskyPost(posts=posts, is_thread=False)

            # Still too long - automatically switch to thread mode
            print(f"Post still too long ({len(posts[0])} chars), switching to thread mode...")
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=True
            )
            posts = _parse_posts(response_text, thread_mode=True)

            return BlueskyPost(posts=posts, is_thread=True)

    except Exception as e:
        print(f"Error generating post: {e}")
        return None


if __name__ == "__main__":
    # Test with a sample preprint
    from biorxiv_scraper import BiorxivScraper
    from preprint_selector import select_best_preprint

    scraper = BiorxivScraper(days_back=7)
    preprints = scraper.fetch_preprints()

    if preprints:
        selected = select_best_preprint(preprints)
        if selected:
            print("\n--- Single Post Mode ---")
            post = generate_post(selected, thread_mode=False)
            if post:
                print(f"Post ({len(post.text)} chars):")
                print(post.text)

            print("\n--- Thread Mode ---")
            thread = generate_post(selected, thread_mode=True)
            if thread:
                for i, p in enumerate(thread.posts, 1):
                    print(f"\nPost {i} ({len(p)} chars):")
                    print(p)
