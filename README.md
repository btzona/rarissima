# Rarissima

Rarissima — Latin for roughly “the rarest things” — is a minimal static ledger of rare, cryptic, rediscovered, and newly described insect research. It collects public entomology RSS and Atom feeds (and PubMed, when the host allows it) and presents them as a short research journal: titles, sources, dates, excerpts, and a link to the original paper or story.

**Live site:** [https://btzona.github.io/rarissima/](https://btzona.github.io/rarissima/)

Headlines and excerpts stay with their publishers. Each card links out.

## Daily refresh

[`.github/workflows/pages.yml`](.github/workflows/pages.yml) refreshes the ledger and deploys the site. It runs:

- every day at 13:17 UTC
- on every push to `main`
- when someone starts it by hand (`workflow_dispatch` on the Actions tab)

The job runs `python3 fetch.py`, copies `index.html`, `css/`, `js/`, and `data/` into a static bundle, then publishes that bundle with the official GitHub Pages actions (`configure-pages`, `upload-pages-artifact`, `deploy-pages`).

A feed that fails is logged and skipped. PubMed often blocks GitHub-hosted runners and returns an HTML warning instead of XML; that does not fail the build. If a run collects no articles at all, `fetch.py` leaves the existing `data/articles.json` in place and exits successfully.

When a run does collect articles, it merges them into the ledger instead of replacing it. Europe PMC supplies older new-species and cryptic-insect papers, month by month, so the shelf keeps reaching back to April 2026. Duplicates collapse on DOI or title. The file is capped at 180 articles, and that cap reserves space for the earlier papers rather than keeping only this week's headlines. The page groups cards by month and offers “Show earlier specimens” so a longer archive stays readable.

`configure-pages` is called with `enablement: true`. The workflow’s `GITHUB_TOKEN` cannot create a Pages site (that needs a personal access token, or a GitHub App with `administration:write` and `pages:write`). If this repository has never had Pages turned on, open **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions** once. After that, this workflow can deploy on its own. The site is served from the `/rarissima/` project path; asset and data URLs in the page are relative (`css/style.css`, `js/app.js`, `data/articles.json`), so they resolve under that path.

## Refresh locally

From the repository root (Python 3, standard library only):

```bash
python3 fetch.py
python3 -m http.server 8765
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/).

The same commands are `npm run fetch` and `npm run serve`.

To check the GitHub Pages subpath on your machine, serve a parent directory:

```bash
mkdir -p /tmp/pages-sim
ln -sfn "$PWD" /tmp/pages-sim/rarissima
python3 -m http.server 8765 --directory /tmp/pages-sim
```

Then open [http://127.0.0.1:8765/rarissima/](http://127.0.0.1:8765/rarissima/).

## Layout

| Path | Role |
|------|------|
| `index.html` | Page shell |
| `css/style.css` | Museum-label / journal styling |
| `img/curtis-plate-71.webp` | Header plate, John Curtis, *British Entomology* (1825), public domain |
| `js/app.js` | Loads `data/articles.json`, filters, month groups, italics for taxa |
| `fetch.py` | Feed fetch, Europe PMC backfill, and rare/entomology heuristics. Not deployed. |
| `data/articles.json` | Article ledger. The site reads this file in the browser. |

`fetch.py` writes titles, sources, dates, excerpts, outbound links, any detected species names, a `rare` flag, and a per-feed status list. Screenshots or a `previews/` folder, if you add them later, are not part of the Pages artifact.

## Design

Cream paper, charcoal ink, a brass accent. Serif titles, a plain sans for body text, mono for the catalog metadata. The header carries a public-domain hand-colored engraving of a burying beetle (John Curtis, Plate 71 of *British Entomology*, 1825, via Wikimedia Commons); the footer repeats that credit. Cards link out; nothing is republished in full.
