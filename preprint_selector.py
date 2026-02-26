"""Select the best preprint using Claude API based on anticipated journal tier."""

import json
import os
from typing import List, Dict, Optional
from pathlib import Path

import anthropic

from biorxiv_scraper import Preprint


POSTED_PREPRINTS_FILE = Path(__file__).parent / "posted_preprints.json"

# Terms to exclude from posting (illicit drugs and related topics)
EXCLUDED_TERMS = [
    "psilocybin",
    "psilocin",
    "psychedelic",
    "hallucinogen",
    "hallucinogenic",
    "lsd",
    "lysergic",
    "dmt",
    "dimethyltryptamine",
    "ayahuasca",
    "mescaline",
    "peyote",
    "magic mushroom",
    "psychoactive mushroom",
    "mdma",
    "ecstasy",
    "cocaine",
    "methamphetamine",
    "heroin",
    "opioid abuse",
    "cannabis recreational",
    "marijuana recreational",
    "drug abuse",
    "illicit drug",
]


def filter_excluded_topics(preprints: List[Preprint]) -> List[Preprint]:
    """Filter out preprints related to illicit drugs and excluded topics."""
    filtered = []
    for p in preprints:
        text = f"{p.title} {p.abstract}".lower()
        if not any(term in text for term in EXCLUDED_TERMS):
            filtered.append(p)
        else:
            print(f"Excluding (illicit drug topic): {p.title[:60]}...")
    return filtered


def load_posted_preprints() -> set:
    """Load the set of already-posted preprint DOIs."""
    if POSTED_PREPRINTS_FILE.exists():
        with open(POSTED_PREPRINTS_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("posted_dois", []))
    return set()


def save_posted_preprint(doi: str) -> None:
    """Add a DOI to the posted preprints list."""
    posted = load_posted_preprints()
    posted.add(doi)

    with open(POSTED_PREPRINTS_FILE, "w") as f:
        json.dump({"posted_dois": sorted(list(posted))}, f, indent=2)


def filter_unposted(preprints: List[Preprint]) -> List[Preprint]:
    """Filter out preprints that have already been posted."""
    posted = load_posted_preprints()
    return [p for p in preprints if p.doi not in posted]


def select_best_preprint(preprints: List[Preprint]) -> Optional[Preprint]:
    """Use Claude to select the preprint most likely to be published in a top journal.

    Args:
        preprints: List of candidate preprints

    Returns:
        The selected Preprint, or None if no suitable candidates
    """
    if not preprints:
        print("No preprints to select from.")
        return None

    # Filter out already-posted preprints
    candidates = filter_unposted(preprints)

    if not candidates:
        print("All preprints have already been posted.")
        return None

    # Filter out preprints about illicit drugs
    candidates = filter_excluded_topics(candidates)

    if not candidates:
        print("No suitable preprints after filtering excluded topics.")
        return None

    print(f"Selecting from {len(candidates)} unposted preprints...")

    # If only one candidate, return it
    if len(candidates) == 1:
        return candidates[0]

    # Prepare summaries for Claude
    summaries = []
    for i, p in enumerate(candidates):
        summary = f"""
PREPRINT {i + 1}:
Title: {p.title}
Category: {p.category}
Date: {p.date}
Abstract: {p.abstract[:1500]}...
"""
        summaries.append(summary)

    # Limit to top 20 candidates to avoid token limits
    if len(summaries) > 20:
        summaries = summaries[:20]
        candidates = candidates[:20]

    summaries_text = "\n---\n".join(summaries)

    prompt = f"""You are an expert in evolutionary biology, genomics, and bioinformatics. Your task is to rank the TOP 5 preprints most likely to be published in a top-tier journal (Nature, Science, Cell, PNAS, Current Biology, eLife, Molecular Biology and Evolution, Genome Research, etc.).

Consider these factors:
1. Scientific novelty and significance
2. Methodological rigor and innovation
3. Broad impact and appeal across fields
4. Quality of the research question
5. Strength of the findings based on the abstract

Here are the candidate preprints:

{summaries_text}

Respond with ONLY the numbers of the top 5 preprints in ranked order, separated by commas (e.g., "3,7,1,12,5" if PREPRINT 3 is best, 7 is second-best, etc.). If fewer than 5 candidates, rank all of them. No explanation needed."""

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )

        selection_text = response.content[0].text.strip()
        # Parse comma-separated numbers
        numbers = [int(n.strip()) for n in selection_text.split(",") if n.strip().isdigit()]

        # Convert to 0-indexed and filter valid indices
        ranked_indices = [n - 1 for n in numbers if 0 <= n - 1 < len(candidates)]

        if ranked_indices:
            selected = candidates[ranked_indices[0]]
            print(f"Top ranked: {selected.title[:60]}...")
            return selected
        else:
            print(f"Invalid selection, defaulting to first candidate")
            return candidates[0]

    except Exception as e:
        print(f"Error selecting preprint: {e}")
        print("Defaulting to first candidate")
        return candidates[0]


def select_ranked_preprints(preprints: List[Preprint], top_n: int = 5) -> List[Preprint]:
    """Use Claude to rank preprints by likelihood of top-tier publication.

    Args:
        preprints: List of candidate preprints
        top_n: Number of top candidates to return

    Returns:
        List of top Preprints in ranked order, or empty list if none suitable
    """
    if not preprints:
        print("No preprints to select from.")
        return []

    # Filter out already-posted preprints
    candidates = filter_unposted(preprints)

    if not candidates:
        print("All preprints have already been posted.")
        return []

    # Filter out preprints about illicit drugs
    candidates = filter_excluded_topics(candidates)

    if not candidates:
        print("No suitable preprints after filtering excluded topics.")
        return []

    print(f"Ranking {len(candidates)} unposted preprints...")

    # If only one candidate, return it
    if len(candidates) == 1:
        return candidates

    # Prepare summaries for Claude
    summaries = []
    for i, p in enumerate(candidates):
        summary = f"""
PREPRINT {i + 1}:
Title: {p.title}
Category: {p.category}
Date: {p.date}
Abstract: {p.abstract[:1500]}...
"""
        summaries.append(summary)

    # Limit to top 20 candidates to avoid token limits
    if len(summaries) > 20:
        summaries = summaries[:20]
        candidates = candidates[:20]

    summaries_text = "\n---\n".join(summaries)

    prompt = f"""You are an expert in evolutionary biology, genomics, and bioinformatics. Your task is to rank the TOP {min(top_n, len(candidates))} preprints most likely to be published in a top-tier journal (Nature, Science, Cell, PNAS, Current Biology, eLife, Molecular Biology and Evolution, Genome Research, etc.).

Consider these factors:
1. Scientific novelty and significance
2. Methodological rigor and innovation
3. Broad impact and appeal across fields
4. Quality of the research question
5. Strength of the findings based on the abstract

Here are the candidate preprints:

{summaries_text}

Respond with ONLY the numbers of the top {min(top_n, len(candidates))} preprints in ranked order, separated by commas (e.g., "3,7,1,12,5" if PREPRINT 3 is best, 7 is second-best, etc.). No explanation needed."""

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )

        selection_text = response.content[0].text.strip()
        # Parse comma-separated numbers
        numbers = [int(n.strip()) for n in selection_text.split(",") if n.strip().isdigit()]

        # Convert to 0-indexed and filter valid indices
        ranked_indices = [n - 1 for n in numbers if 0 <= n - 1 < len(candidates)]

        if ranked_indices:
            ranked = [candidates[i] for i in ranked_indices[:top_n]]
            print(f"Ranked {len(ranked)} candidates")
            for i, p in enumerate(ranked, 1):
                print(f"  {i}. {p.title[:60]}...")
            return ranked
        else:
            print(f"Invalid selection, returning first {top_n} candidates")
            return candidates[:top_n]

    except Exception as e:
        print(f"Error ranking preprints: {e}")
        print(f"Returning first {top_n} candidates")
        return candidates[:top_n]


if __name__ == "__main__":
    from biorxiv_scraper import BiorxivScraper

    scraper = BiorxivScraper(days_back=7)
    preprints = scraper.fetch_preprints()

    if preprints:
        selected = select_best_preprint(preprints)
        if selected:
            print(f"\nSelected preprint:")
            print(f"Title: {selected.title}")
            print(f"DOI: {selected.doi}")
            print(f"URL: {selected.web_url}")
