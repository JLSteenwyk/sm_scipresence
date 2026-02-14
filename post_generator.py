"""Generate Bluesky posts from preprints using Claude API with stop_slop rules."""

import base64
import tempfile
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

import anthropic
import grapheme
import requests

from biorxiv_scraper import Preprint


# Load stop_slop rules
STOP_SLOP_DIR = Path(__file__).parent / "stop_slop"

# Bluesky's limit is 300 graphemes per post
BLUESKY_GRAPHEME_LIMIT = 300
# bioRxiv URLs are ~56 chars, plus "\n\n" = ~60 chars buffer needed for first post
URL_BUFFER = 65


def count_graphemes(text: str) -> int:
    """Count graphemes in text (what Bluesky uses for length limits)."""
    return grapheme.length(text)


def split_at_boundary(text: str, max_graphemes: int) -> tuple:
    """Split text at a sentence boundary, returning (kept, remainder).

    Finds the last complete sentence that fits within the limit. If no sentence
    boundary is found, falls back to the last word boundary. Never appends
    ellipses or cuts mid-sentence.

    Returns:
        Tuple of (text that fits within limit, leftover text).
        If the text already fits, remainder is an empty string.
    """
    if count_graphemes(text) <= max_graphemes:
        return text, ""

    grapheme_list = list(grapheme.graphemes(text))
    candidate = "".join(grapheme_list[:max_graphemes])
    full_remainder = "".join(grapheme_list[max_graphemes:])

    def _make_remainder(kept_end_idx: int) -> str:
        """Build remainder from what was cut, preserving the full original text."""
        full_text = candidate + full_remainder
        return full_text[kept_end_idx:].strip()

    # Try to find the last sentence-ending punctuation (.!?) followed by space/newline
    for end_char in [". ", ".\n", "? ", "?\n", "! ", "!\n"]:
        idx = candidate.rfind(end_char)
        if idx != -1:
            kept = candidate[:idx + 1].rstrip()
            return kept, _make_remainder(idx + 1)

    # Check if the candidate ends right at a sentence boundary
    if candidate.rstrip().endswith((".", "?", "!")):
        kept = candidate.rstrip()
        return kept, full_remainder.strip()

    # No sentence boundary found - fall back to last word boundary
    last_space = candidate.rfind(" ")
    if last_space > 0:
        # Walk back to find a sentence ending before this word boundary
        word_truncated = candidate[:last_space].rstrip()
        for end_char in [".", "?", "!"]:
            idx = word_truncated.rfind(end_char)
            if idx != -1:
                kept = word_truncated[:idx + 1].rstrip()
                return kept, _make_remainder(idx + 1)
        # No sentence boundary at all - split at word boundary
        return word_truncated, _make_remainder(last_space)

    # Absolute fallback (single very long word)
    return candidate, full_remainder.strip()


def truncate_to_graphemes(text: str, max_graphemes: int) -> str:
    """Truncate text to a maximum number of graphemes at a sentence boundary.

    Convenience wrapper around split_at_boundary that discards the remainder.
    """
    kept, _ = split_at_boundary(text, max_graphemes)
    return kept


def validate_thread_posts(posts: list, first_post_limit: int, other_post_limit: int) -> list:
    """Validate and fix thread posts so every post fits within its grapheme limit.

    If a post is too long, it is split at a sentence/word boundary and the
    remainder is prepended to the next post (or appended as a new post).
    """
    validated = []
    carry = ""

    for i, post in enumerate(posts):
        # Prepend any leftover text from the previous post
        if carry:
            post = carry + " " + post
            carry = ""

        limit = first_post_limit if i == 0 else other_post_limit
        if count_graphemes(post) > limit:
            print(f"Splitting post {i+1} at sentence boundary ({count_graphemes(post)} > {limit} graphemes)")
            kept, carry = split_at_boundary(post, limit)
            validated.append(kept)
        else:
            validated.append(post)

    # If there's still leftover text after the last post, add new posts
    while carry:
        limit = other_post_limit
        if count_graphemes(carry) <= limit:
            validated.append(carry)
            carry = ""
        else:
            print(f"Adding overflow post ({count_graphemes(carry)} graphemes)")
            kept, carry = split_at_boundary(carry, limit)
            validated.append(kept)

    return validated


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


# Maximum PDF size to send to Claude (10 MB raw = ~13 MB base64)
MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024


def download_pdf(url: str) -> Optional[bytes]:
    """Download PDF from URL and return bytes."""
    try:
        response = requests.get(url, timeout=60, headers={
            "User-Agent": "BioSkyPoster/1.0 (Academic Research Bot)"
        })
        response.raise_for_status()
        content = response.content

        # Check if PDF is too large for Claude API
        if len(content) > MAX_PDF_SIZE_BYTES:
            print(f"PDF too large ({len(content) / 1024 / 1024:.1f} MB > {MAX_PDF_SIZE_BYTES / 1024 / 1024:.0f} MB limit)")
            print("Will use abstract-only mode for post generation")
            return None

        return content
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
- The FIRST post MUST be under 230 characters (a link will be appended separately)
- Posts 2-5 MUST each be under 290 characters
- Bluesky counts graphemes, not bytes, so special characters count as expected
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

    system_prompt = f"""You are a science journalist reporting on evolutionary biology, genomics, and bioinformatics preprints for Bluesky. Your audience is scientists and science enthusiasts.

WRITING RULES (stop_slop):
{stop_slop_rules}

CRITICAL FRAMING RULES:
- You are REPORTING on research done by others, not presenting your own work
- NEVER use "we" - you did not do this research
- Attribute findings to the authors/researchers, not yourself
- Write as a journalist highlighting interesting work, not as a participant

SENTENCE VARIETY (important!):
- VARY your opening structure. Do NOT always start with "Researchers..."
- Good openings can lead with: the organism/system, the finding itself, a surprising fact, the method, or the implication
- Examples of varied openings:
  * "Fruit flies undergo massive synapse pruning during early adulthood..."
  * "Ancient hybridization drove plum diversification across tropical zones..."
  * "A new algorithm maps which genes interact with transcriptional condensates..."
  * "The human hypothalamus shows striking sex differences at single-cell resolution..."
  * "Psilocybin biosynthesis evolved independently at least twice in mushrooms..."
- Attribution can come later in the sentence or be implicit
- Mix passive and active voice naturally

ADDITIONAL GUIDELINES:
- State findings directly without hype
- Avoid emoji unless absolutely natural
- No hashtags
- Be specific about what the research found
- Do not start with "New preprint:" or similar throat-clearing
- Do not use phrases like "This is huge" or "Game-changer"
- Trust your reader's intelligence
- NEVER use em-dashes (—) - use commas or periods instead

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

    # Grapheme limits (Bluesky max is 300)
    # First post has URL appended, so needs ~65 char buffer
    SINGLE_POST_LIMIT = BLUESKY_GRAPHEME_LIMIT - URL_BUFFER  # 235 graphemes
    THREAD_FIRST_POST_LIMIT = BLUESKY_GRAPHEME_LIMIT - URL_BUFFER  # 235 graphemes
    THREAD_OTHER_POST_LIMIT = BLUESKY_GRAPHEME_LIMIT - 5  # 295 graphemes (small safety margin)

    try:
        if thread_mode:
            # Generate thread directly
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=True
            )
            posts = _parse_posts(response_text, thread_mode=True)

            # Validate thread posts using grapheme counting
            valid = True
            for i, post in enumerate(posts):
                limit = THREAD_FIRST_POST_LIMIT if i == 0 else THREAD_OTHER_POST_LIMIT
                grapheme_count = count_graphemes(post)
                if grapheme_count > limit:
                    print(f"Warning: Thread post {i+1} exceeds {limit} graphemes ({grapheme_count})")
                    valid = False

            if not valid:
                print("Regenerating thread with stricter limits...")
                for retry in range(2):
                    response_text = _call_claude_for_post(
                        preprint, pdf_content, stop_slop_rules,
                        thread_mode=True
                    )
                    posts = _parse_posts(response_text, thread_mode=True)
                    # Check if all posts now fit
                    all_fit = all(
                        count_graphemes(p) <= (THREAD_FIRST_POST_LIMIT if i == 0 else THREAD_OTHER_POST_LIMIT)
                        for i, p in enumerate(posts)
                    )
                    if all_fit:
                        break
                    print(f"Retry {retry + 1} still has oversized posts, {'retrying' if retry == 0 else 'will truncate at sentence boundary'}...")

            # Final validation — split oversized posts and carry remainder forward
            validated_posts = validate_thread_posts(
                posts, THREAD_FIRST_POST_LIMIT, THREAD_OTHER_POST_LIMIT
            )

            return BlueskyPost(posts=validated_posts, is_thread=True)

        else:
            # Try to generate a single post
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=False, char_limit=SINGLE_POST_LIMIT
            )
            posts = _parse_posts(response_text, thread_mode=False)

            grapheme_count = count_graphemes(posts[0]) if posts else 0
            if posts and grapheme_count <= SINGLE_POST_LIMIT:
                # Success - single post fits
                return BlueskyPost(posts=posts, is_thread=False)

            # Post too long - retry with stricter instructions
            print(f"Post too long ({grapheme_count} graphemes), retrying with stricter limit...")
            response_text = _call_claude_for_post(
                preprint, pdf_content, stop_slop_rules,
                thread_mode=False, char_limit=SINGLE_POST_LIMIT, retry_attempt=True
            )
            posts = _parse_posts(response_text, thread_mode=False)

            grapheme_count = count_graphemes(posts[0]) if posts else 0
            if posts and grapheme_count <= SINGLE_POST_LIMIT:
                # Success on retry
                return BlueskyPost(posts=posts, is_thread=False)

            # Still too long - only switch to thread mode if we have PDF content
            # (abstract-only mode should stay as single post)
            if pdf_content:
                print(f"Post still too long ({grapheme_count} graphemes), switching to thread mode...")
                response_text = _call_claude_for_post(
                    preprint, pdf_content, stop_slop_rules,
                    thread_mode=True
                )
                posts = _parse_posts(response_text, thread_mode=True)

                # Validate — split oversized posts and carry remainder forward
                validated_posts = validate_thread_posts(
                    posts, THREAD_FIRST_POST_LIMIT, THREAD_OTHER_POST_LIMIT
                )

                return BlueskyPost(posts=validated_posts, is_thread=True)
            else:
                # In abstract-only mode, split into a thread to preserve all content
                print(f"Post too long ({grapheme_count} graphemes) in abstract-only mode, splitting into thread...")
                validated_posts = validate_thread_posts(
                    posts, THREAD_FIRST_POST_LIMIT, THREAD_OTHER_POST_LIMIT
                )
                is_thread = len(validated_posts) > 1
                return BlueskyPost(posts=validated_posts, is_thread=is_thread)

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
                print(f"Post ({count_graphemes(post.text)} graphemes):")
                print(post.text)

            print("\n--- Thread Mode ---")
            thread = generate_post(selected, thread_mode=True)
            if thread:
                for i, p in enumerate(thread.posts, 1):
                    print(f"\nPost {i} ({count_graphemes(p)} graphemes):")
                    print(p)
