# VAResearchRadar

Daily pipeline that aggregates, scores and publishes Veterans Affairs research publications from PubMed and OpenAlex, with funding attribution. Published as a static dashboard on GitHub Pages.

- Refresh locally: `python -m vadaily.pipeline` (writes `site/data/` and `data/vadaily.db`).
- A GitHub Actions workflow refreshes the data daily and redeploys the site.
- Optional secret `OPENALEX_API_KEY` enables cursor paging in OpenAlex.
- Tests: `python -m pytest -q`

