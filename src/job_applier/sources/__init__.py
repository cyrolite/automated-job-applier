"""Job posting sources.

Three tiers, all normalising into `base.Posting`:

  api     — public, keyless endpoints, fully automated:
            mycareersfuture, greenhouse, lever, ashby
  browser — no public API and terms that prohibit scraping, so these build a
            search URL for your own browser and ingest what it captures:
            linkedin, jobstreet, indeed, glassdoor
  manual  — paste a posting and run `ja apply -f`

`registry.SourceConfig` builds the active set from Context/sources.yaml.
"""
from .base import Posting, Source, html_to_text

__all__ = ["Posting", "Source", "html_to_text"]
