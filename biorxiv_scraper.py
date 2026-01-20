"""Scraper for bioRxiv preprints in evolutionary/comparative genomics fields."""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import time


@dataclass
class Preprint:
    """Represents a bioRxiv preprint."""
    doi: str
    title: str
    authors: str
    abstract: str
    category: str
    date: str
    pdf_url: str
    web_url: str
    server: str = "biorxiv"

    def to_dict(self) -> Dict:
        return {
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "category": self.category,
            "date": self.date,
            "pdf_url": self.pdf_url,
            "web_url": self.web_url,
            "server": self.server,
        }


class BiorxivScraper:
    """Scrape bioRxiv for preprints matching target research themes."""

    # bioRxiv API endpoint for content
    BASE_URL = "https://api.biorxiv.org/details"

    # Target subject categories on bioRxiv that align with our themes
    TARGET_CATEGORIES = [
        "evolutionary biology",
        "genomics",
        "bioinformatics",
        "genetics",
        "microbiology",
        "ecology",
        "animal behavior and cognition",
        "developmental biology",
        "molecular biology",
        "systems biology",
        "synthetic biology",
        "paleontology",
    ]

    # Keywords for filtering preprints to our specific themes
    THEME_KEYWORDS = [
        # Evolutionary genomics
        "evolutionary genomic", "evolution of genome", "genome evolution",
        "molecular evolution", "sequence evolution", "evolutionary history",
        "evolutionary origin", "evolutionary analysis",
        # Comparative genomics
        "comparative genomic", "genome comparison", "synteny",
        "ortholog", "paralog", "homolog", "conserved element",
        # Functional genomics
        "functional genomic", "gene function", "functional annotation",
        "transcriptome", "transcriptomic", "gene expression",
        "regulatory element", "enhancer", "promoter",
        # Animal evolution
        "animal evolution", "metazoan", "animal phylogeny",
        "vertebrate evolution", "invertebrate", "chordate",
        # Early animal evolution
        "early animal", "cambrian", "ediacaran", "precambrian",
        "animal origin", "basal animal", "early metazoan",
        "cnidaria", "porifera", "ctenophore", "placozoa",
        # Fungal evolution
        "fungal evolution", "fungal genome", "fungal phylogen",
        "mycology", "ascomycete", "basidiomycete", "fungal diversity",
        "yeast evolution", "filamentous fung",
        # Bioinformatics
        "bioinformatic", "computational biology", "algorithm",
        "software tool", "pipeline", "sequence analysis",
        "genome assembly", "annotation pipeline",
        # AI in biology
        "machine learning", "deep learning", "artificial intelligence",
        "neural network", "protein structure prediction", "alphafold",
        "language model", "transformer", "classification model",
        # Phylogenetics
        "phylogenetic", "phylogeny", "tree of life", "clade",
        "monophyletic", "ancestral", "divergence time", "molecular clock",
        "bayesian", "maximum likelihood", "coalescent",
        # Phylogenomics
        "phylogenomic", "species tree", "gene tree", "concordance",
        "incomplete lineage sorting", "horizontal gene transfer",
        "genome-scale phylogen",
    ]

    def __init__(self, days_back: int = 7):
        """Initialize scraper with lookback window.

        Args:
            days_back: Number of days to look back for preprints (default: 7)
        """
        self.days_back = days_back
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "BioSkyPoster/1.0 (Academic Research Bot)"
        })

    def _get_date_range(self) -> tuple[str, str]:
        """Get date range for API query."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.days_back)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    def _matches_themes(self, preprint: Dict) -> bool:
        """Check if preprint matches our target themes based on title and abstract."""
        title = preprint.get("title", "").lower()
        abstract = preprint.get("abstract", "").lower()
        combined_text = f"{title} {abstract}"

        for keyword in self.THEME_KEYWORDS:
            if keyword.lower() in combined_text:
                return True
        return False

    def _fetch_page(self, server: str, start_date: str, end_date: str, cursor: int = 0) -> Optional[Dict]:
        """Fetch a page of results from the bioRxiv API.

        Args:
            server: 'biorxiv' or 'medrxiv'
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            cursor: Pagination cursor

        Returns:
            API response dict or None if error
        """
        url = f"{self.BASE_URL}/{server}/{start_date}/{end_date}/{cursor}"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching from {server}: {e}")
            return None

    def fetch_preprints(self) -> List[Preprint]:
        """Fetch all preprints matching our themes from the last week.

        Returns:
            List of Preprint objects matching our research themes
        """
        start_date, end_date = self._get_date_range()
        all_preprints: List[Preprint] = []

        print(f"Fetching preprints from {start_date} to {end_date}...")

        # Fetch from bioRxiv
        cursor = 0
        while True:
            data = self._fetch_page("biorxiv", start_date, end_date, cursor)
            if not data:
                break

            collection = data.get("collection", [])
            if not collection:
                break

            for item in collection:
                # Check if category matches our targets
                category = item.get("category", "").lower()
                category_match = any(
                    target in category for target in self.TARGET_CATEGORIES
                )

                # Check if content matches our themes
                if category_match or self._matches_themes(item):
                    if self._matches_themes(item):  # Double-check theme relevance
                        doi = item.get("doi", "")
                        preprint = Preprint(
                            doi=doi,
                            title=item.get("title", ""),
                            authors=item.get("authors", ""),
                            abstract=item.get("abstract", ""),
                            category=item.get("category", ""),
                            date=item.get("date", ""),
                            pdf_url=f"https://www.biorxiv.org/content/{doi}.full.pdf",
                            web_url=f"https://www.biorxiv.org/content/{doi}",
                            server="biorxiv",
                        )
                        all_preprints.append(preprint)

            # Check if more pages
            messages = data.get("messages", [])
            if messages:
                msg = messages[0]
                total = int(msg.get("total", 0))
                count = int(msg.get("count", 0))
                if cursor + count >= total:
                    break
                cursor += count
            else:
                break

            # Rate limiting
            time.sleep(0.5)

        print(f"Found {len(all_preprints)} preprints matching target themes")
        return all_preprints

    def fetch_preprints_as_dicts(self) -> List[Dict]:
        """Fetch preprints and return as list of dictionaries."""
        preprints = self.fetch_preprints()
        return [p.to_dict() for p in preprints]


if __name__ == "__main__":
    scraper = BiorxivScraper(days_back=7)
    preprints = scraper.fetch_preprints()

    print(f"\nFound {len(preprints)} relevant preprints:")
    for i, p in enumerate(preprints[:10], 1):
        print(f"\n{i}. {p.title[:80]}...")
        print(f"   Category: {p.category}")
        print(f"   Date: {p.date}")
        print(f"   DOI: {p.doi}")
