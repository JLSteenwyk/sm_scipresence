"""Track posting history for weekly roundups and analytics."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional


HISTORY_FILE = Path(__file__).parent / "posting_history.json"


def load_history() -> List[Dict]:
    """Load the full posting history."""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            return data.get("posts", [])
    return []


def save_to_history(preprint_data: Dict) -> None:
    """Add a posted preprint to the history.

    Args:
        preprint_data: Dict with doi, title, abstract, category, web_url
    """
    history = load_history()

    # Add timestamp
    entry = {
        **preprint_data,
        "posted_at": datetime.now().isoformat(),
        "posted_date": datetime.now().strftime("%Y-%m-%d"),
    }

    history.append(entry)

    with open(HISTORY_FILE, "w") as f:
        json.dump({"posts": history}, f, indent=2)


def get_posts_from_week(week_offset: int = 0) -> List[Dict]:
    """Get all posts from a specific week.

    Args:
        week_offset: 0 for current week, -1 for last week, etc.

    Returns:
        List of post entries from that week
    """
    history = load_history()

    # Calculate the start and end of the target week
    today = datetime.now()
    # Get start of current week (Monday)
    start_of_week = today - timedelta(days=today.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

    # Adjust for week offset
    start_of_week += timedelta(weeks=week_offset)
    end_of_week = start_of_week + timedelta(days=7)

    # Filter posts
    week_posts = []
    for post in history:
        posted_date = post.get("posted_date", "")
        if posted_date:
            post_dt = datetime.strptime(posted_date, "%Y-%m-%d")
            if start_of_week <= post_dt < end_of_week:
                week_posts.append(post)

    return week_posts


def get_posts_from_last_n_days(days: int = 7) -> List[Dict]:
    """Get all posts from the last N days.

    Args:
        days: Number of days to look back

    Returns:
        List of post entries from that period
    """
    history = load_history()
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    return [
        post for post in history
        if post.get("posted_date", "") >= cutoff_str
    ]
