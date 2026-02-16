# sm_scipresence

Automated science communication bot that discovers, curates, and posts bioRxiv preprints to Bluesky, Twitter/X, and LinkedIn with AI-generated summaries and extracted figures.

## How It Works

Each morning, the bot scrapes bioRxiv for recent preprints matching research themes in evolutionary biology, genomics, bioinformatics, and related fields. Claude ranks candidates by scientific merit and publication likelihood, extracts a figure from the PDF, generates a concise social media post, and publishes to all three platforms.

Additional engagement comes from midweek follow-up questions posted as replies to the morning thread, and a weekly Sunday roundup summarizing all posts from the past week.

All AI-generated text passes through a custom "stop slop" ruleset that eliminates common AI writing patterns (filler phrases, em-dashes, dramatic fragmentation, business jargon) to keep posts sounding natural and direct.

## Architecture

```
DAILY (weekdays ~8:00 AM):
  main.py
    1. Scrape bioRxiv for matching preprints    (biorxiv_scraper.py)
    2. Rank by scientific merit via Claude       (preprint_selector.py)
    3. Extract figure from PDF                   (figure_extractor.py)
    4. Generate post text via Claude + stop_slop (post_generator.py)
    5. Post to Bluesky                           (bluesky_poster.py)
    6. Post to Twitter/X                         (twitter_poster.py)
    7. Post to LinkedIn                          (linkedin_poster.py)
    8. Save history, git commit & push           (posting_history.py)

MIDDAY (Tue/Wed/Thu, probabilistic ~12:00 PM):
  framing_question.py
    → Generates a thought-provoking question about the morning's preprint
    → Posts as a reply to the original thread on all platforms

WEEKLY (Sundays):
  weekly_roundup.py
    → Summarizes all posts from the past week in a threaded roundup

ON-DEMAND:
  post_now.py <pdf_path> <url> [options]
    → Manually post any PDF with interactive confirmation
```

## Project Structure

```
sm_scipresence/
├── main.py                  # Daily orchestration script
├── post_now.py              # Manual on-demand posting
├── biorxiv_scraper.py       # bioRxiv API scraper with category/keyword filtering
├── preprint_selector.py     # Claude-powered ranking by scientific merit
├── post_generator.py        # AI post generation with grapheme-aware splitting
├── figure_extractor.py      # PDF figure extraction and image processing
├── bluesky_poster.py        # Bluesky API client (primary platform)
├── twitter_poster.py        # Twitter/X API client (v2 posting, v1.1 media)
├── linkedin_poster.py       # LinkedIn API client with OAuth token refresh
├── posting_history.py       # Posting history tracking for roundups
├── framing_question.py      # Midweek follow-up question generator
├── weekly_roundup.py        # Sunday weekly roundup thread generator
├── run_scheduled.sh         # Cron wrapper for main.py (0-20 min random delay)
├── run_framing_question.sh  # Cron wrapper for framing_question.py (0-45 min delay)
├── run_weekly_roundup.sh    # Cron wrapper for weekly_roundup.py (0-30 min delay)
├── stop_slop/               # AI writing pattern elimination rules
│   ├── phrases.md           # Banned phrases and filler words
│   ├── structures.md        # Banned structural patterns (em-dashes, three-item lists)
│   ├── examples.md          # Before/after transformation examples
│   └── skills.md            # Scoring rubric and meta-rules
├── requirements.txt         # Python dependencies
├── .env.example             # Template for credentials
├── posting_history.json     # All posted preprints with timestamps
├── posted_preprints.json    # DOIs already posted (deduplication)
├── last_posted_preprint.json# Morning post info (used by framing questions)
└── last_framing_question.json # Weekly framing question tracker
```

## Setup

### 1. Clone and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required credentials:
- **Anthropic** API key (for Claude)
- **Bluesky** username and app password
- **Twitter/X** API key, secret, access token, and access token secret
- **LinkedIn** client ID, client secret, and access token (OAuth2)

### 3. Schedule with cron

```cron
# Daily preprint post (weekdays at 8:00 AM)
0 8 * * 1-5 /path/to/sm_scipresence/run_scheduled.sh >> /path/to/sm_scipresence/cron.log 2>&1

# Framing question (weekdays at 11:45 AM)
45 11 * * 1-5 /path/to/sm_scipresence/run_framing_question.sh >> /path/to/sm_scipresence/cron.log 2>&1

# Weekly roundup (Sundays at 10:00 AM)
0 10 * * 0 /path/to/sm_scipresence/run_weekly_roundup.sh >> /path/to/sm_scipresence/cron.log 2>&1
```

## Usage

### Automated daily posting

```bash
python main.py                # Standard single post
python main.py --thread       # Force multi-post thread
python main.py --dry-run      # Preview without posting
python main.py --days 14      # Look back 14 days instead of 7
python main.py --no-image     # Skip figure extraction
```

### Manual posting

```bash
python post_now.py paper.pdf https://doi.org/10.1101/...
python post_now.py paper.pdf https://doi.org/10.1101/... --thread --dry-run
python post_now.py paper.pdf https://doi.org/10.1101/... --title "Custom Title" --abstract "Custom abstract"
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | bioRxiv API calls |
| `python-dotenv` | Environment variable loading |
| `anthropic` | Claude API for ranking and text generation |
| `PyMuPDF` | PDF parsing and figure extraction |
| `Pillow` | Image processing and compression |
| `atproto` | Bluesky AT Protocol client |
| `tweepy` | Twitter/X API client |
| `grapheme` | Unicode grapheme counting for Bluesky character limits |

## Design Decisions

- **Bluesky is the primary platform** — Twitter and LinkedIn post failures are non-blocking warnings; a Bluesky failure halts the run.
- **Grapheme-aware text splitting** — Bluesky counts characters by Unicode grapheme clusters, not bytes. Posts split at sentence boundaries to maximize content within limits.
- **Randomized scheduling** — Shell wrappers add random delays (up to 20-45 minutes) to avoid bot-like posting patterns.
- **Stop slop rules** — Custom prompt engineering eliminates AI writing tics (throat-clearing, em-dashes, dramatic fragmentation, business jargon) for natural-sounding posts.
- **Probabilistic framing questions** — Tuesday (1/3 chance), Wednesday (1/2 chance), Thursday (guaranteed), ensuring exactly one question per week without manual scheduling.
- **Excluded topics** — 41+ keyword filters remove illicit drug research while keeping legitimate pharmacology.
