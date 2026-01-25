#!/usr/bin/env python3
"""Generate and post afternoon "framing question" follow-ups.

Posts a thought-provoking question about the morning's preprint to encourage engagement.
Runs once per week on a randomly selected day (Tue, Wed, or Thu).
"""

import json
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

import anthropic

from bluesky_poster import BlueskyPoster


LAST_POST_FILE = Path(__file__).parent / "last_posted_preprint.json"
LAST_FRAMING_FILE = Path(__file__).parent / "last_framing_question.json"
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


def load_last_preprint() -> dict | None:
    """Load info about the last posted preprint."""
    if not LAST_POST_FILE.exists():
        return None

    with open(LAST_POST_FILE, "r") as f:
        data = json.load(f)

    # Check if it's from today
    posted_date = data.get("posted_date", "")
    today = datetime.now().strftime("%Y-%m-%d")

    if posted_date != today:
        print(f"Last preprint was posted on {posted_date}, not today ({today})")
        return None

    return data


def save_preprint_for_followup(preprint_data: dict) -> None:
    """Save preprint info for afternoon follow-up."""
    preprint_data["posted_date"] = datetime.now().strftime("%Y-%m-%d")

    with open(LAST_POST_FILE, "w") as f:
        json.dump(preprint_data, f, indent=2)


def get_week_number() -> str:
    """Get current ISO week identifier (YYYY-WNN)."""
    now = datetime.now()
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def posted_framing_this_week() -> bool:
    """Check if we've already posted a framing question this week."""
    if not LAST_FRAMING_FILE.exists():
        return False

    with open(LAST_FRAMING_FILE, "r") as f:
        data = json.load(f)

    return data.get("week") == get_week_number()


def save_framing_posted() -> None:
    """Record that we posted a framing question this week."""
    with open(LAST_FRAMING_FILE, "w") as f:
        json.dump({
            "week": get_week_number(),
            "posted_date": datetime.now().strftime("%Y-%m-%d"),
        }, f, indent=2)


def should_post_today() -> tuple[bool, str]:
    """Determine if we should post the framing question today.

    Uses probabilistic selection to guarantee exactly one post per week:
    - Tuesday: 1/3 chance
    - Wednesday: 1/2 chance (if Tuesday didn't post)
    - Thursday: 100% (if neither Tue nor Wed posted)

    Returns:
        Tuple of (should_post, reason)
    """
    if posted_framing_this_week():
        return False, "Already posted framing question this week"

    today = datetime.now().weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, ...

    if today == 1:  # Tuesday
        if random.random() < 1/3:
            return True, "Tuesday selected (1/3 chance)"
        return False, "Tuesday not selected (1/3 chance)"

    elif today == 2:  # Wednesday
        if random.random() < 1/2:
            return True, "Wednesday selected (1/2 chance)"
        return False, "Wednesday not selected (1/2 chance)"

    elif today == 3:  # Thursday
        return True, "Thursday - must post (last chance this week)"

    else:
        return False, f"Not a posting day (today is weekday {today})"


def generate_framing_question(preprint: dict, dry_run: bool = False) -> str | None:
    """Generate a framing question post using Claude."""

    stop_slop_rules = load_stop_slop_rules()

    system_prompt = f"""You are a science journalist on Bluesky generating a thoughtful follow-up post about a preprint you highlighted earlier today. Your goal is to spark discussion.

WRITING RULES (stop_slop):
{stop_slop_rules}

CRITICAL FRAMING RULES:
- You are REPORTING on research done by others, not presenting your own work
- NEVER use "we" - you did not do this research
- Use framing like "the researchers", "the authors", "this study"
- Write as someone curating and discussing others' work

TASK: Generate a "framing question" post that:
1. Identifies a specific conceptual tension, implication, or interpretive question from the paper
2. Invites others (especially from a relevant subfield) to share their perspective
3. Feels like genuine intellectual curiosity, not engagement-bait

FORMAT:
- Jump straight into the question or tension, no preamble or throat-clearing
- Be concrete and specific, not vague
- End by inviting input from a relevant community
- Total post MUST be under 280 characters
- No hashtags
- No emoji except maybe one at the start if it feels natural
- NEVER use em-dashes, use commas or periods instead

Output ONLY the post text, nothing else."""

    user_prompt = f"""Generate a framing question for this preprint:

Title: {preprint.get('title', 'Unknown')}
Category: {preprint.get('category', 'Unknown')}
Abstract: {preprint.get('abstract', 'No abstract')[:1500]}

Remember: under 280 characters, genuine curiosity, invite discussion from relevant subfield."""

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        post_text = response.content[0].text.strip()

        # Validate length
        if len(post_text) > 280:
            print(f"Post too long ({len(post_text)} chars), regenerating...")
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=300,
                system=system_prompt + "\n\nCRITICAL: Your last attempt was too long. Be MORE concise. Under 280 characters is mandatory.",
                messages=[{"role": "user", "content": user_prompt}],
            )
            post_text = response.content[0].text.strip()

        return post_text

    except Exception as e:
        print(f"Error generating framing question: {e}")
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Post afternoon framing question")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--force", action="store_true", help="Bypass weekly scheduling (for testing)")
    args = parser.parse_args()

    print("=" * 60)
    print("FRAMING QUESTION FOLLOW-UP POST")
    print("=" * 60)

    # Check if we should post today (weekly scheduling)
    if not args.force:
        should_post, reason = should_post_today()
        print(f"\nScheduling check: {reason}")

        if not should_post:
            print("Skipping framing question today.")
            sys.exit(0)
    else:
        print("\n--force flag: bypassing weekly scheduling")

    # Load this morning's preprint
    preprint = load_last_preprint()

    if not preprint:
        print("No preprint from today found. Skipping afternoon post.")
        sys.exit(0)

    print(f"\nMorning preprint: {preprint.get('title', 'Unknown')[:60]}...")

    # Generate framing question
    print("\nGenerating framing question with Claude...")
    question = generate_framing_question(preprint)

    if not question:
        print("Failed to generate framing question.")
        sys.exit(1)

    print(f"\n--- Generated Post ({len(question)} chars) ---")
    print(question)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN: Skipping actual posting")
        print("=" * 60)
    else:
        print("\nPosting to Bluesky...")
        try:
            poster = BlueskyPoster()

            # Check if we have the original post URI to reply to
            last_uri = preprint.get("last_uri")
            root_uri = preprint.get("root_uri")

            if last_uri:
                # Reply to the end of the original thread
                print(f"Replying to thread: {last_uri}")
                uri = poster.post_reply(
                    text=question,
                    reply_to_uri=last_uri,
                    root_uri=root_uri
                )
            else:
                # Fallback to standalone post if no URI saved (backwards compatibility)
                print("No original post URI found, posting as standalone")
                uri = poster.post_single(question)

            if uri:
                print(f"Posted successfully: {uri}")
                # Record that we posted this week
                save_framing_posted()
                print(f"Recorded framing question for week {get_week_number()}")
            else:
                print("Failed to post")
                sys.exit(1)

        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
