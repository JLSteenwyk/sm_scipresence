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

    prompt = f"""You are an expert in evolutionary biology, genomics, and bioinformatics. Your task is to select the ONE preprint most likely to be published in a top-tier journal (Nature, Science, Cell, PNAS, Current Biology, eLife, Molecular Biology and Evolution, Genome Research, etc.).

Consider these factors:
1. Scientific novelty and significance
2. Methodological rigor and innovation
3. Broad impact and appeal across fields
4. Quality of the research question
5. Strength of the findings based on the abstract

Here are the candidate preprints:

{summaries_text}

Respond with ONLY the number of the best preprint (e.g., "3" if PREPRINT 3 is best). No explanation needed."""

    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )

        selection_text = response.content[0].text.strip()
        # Extract the number
        selection_num = int("".join(c for c in selection_text if c.isdigit()))
        selection_idx = selection_num - 1

        if 0 <= selection_idx < len(candidates):
            selected = candidates[selection_idx]
            print(f"Selected: {selected.title[:60]}...")
            return selected
        else:
            print(f"Invalid selection {selection_num}, defaulting to first candidate")
            return candidates[0]

    except Exception as e:
        print(f"Error selecting preprint: {e}")
        print("Defaulting to first candidate")
        return candidates[0]


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
