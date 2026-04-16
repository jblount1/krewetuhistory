# Historical Marker Site

This folder contains the deployable static website for the digital historical marker experience. The front end is intentionally build-free so it can be served directly by Netlify, GitHub Pages, or any static host.

## How the content gets here

The website does not author stories directly. Instead, the workflow copies approved story packages and media into this folder:

```bash
PYTHONPATH=historical_marker_workflow/src python3 -m marker_workflow.cli build-site --source-mode approved
```

The site can also be built from Airtable-backed content:

```bash
PYTHONPATH=historical_marker_workflow/src python3 -m marker_workflow.cli build-site --source-mode airtable
```

In the Airtable-backed mode, only submissions with a public-ready workflow status are exported. If `AI Copy` is blank, the carousel falls back to approved story text from the submission.

## Runtime data source

By default, the site reads from `data/stories.json`. You can also point the pages at Supabase without changing the UI by editing `site-config.js`:

```js
window.KTH_SITE_CONFIG = {
  dataSource: "supabase",
  supabaseUrl: "https://YOUR_PROJECT.supabase.co",
  supabaseAnonKey: "YOUR_PUBLIC_ANON_KEY",
  supabaseSchema: "public",
  supabaseStoriesTable: "stories_public",
};
```

When Supabase is enabled, the site fetches approved story rows at runtime and falls back to the local JSON snapshot if Supabase is unavailable.

For an internal preview before editorial approval, you can generate from processing packages instead:

```bash
PYTHONPATH=historical_marker_workflow/src python3 -m marker_workflow.cli build-site --source-mode processing-preview
```

## Local preview

Run a simple static server from the repository root:

```bash
cd historical_marker_site
python3 -m http.server 8080
```

Then open [http://localhost:8080](http://localhost:8080).

## Key files

- `index.html`: branded archive and browsing page
- `carousel.html`: large-screen display carousel page
- `app.js`: archive-page rendering, filtering, and selected-story detail
- `carousel.js`: display-mode carousel logic, autoplay, and story rotation
- `site-data.js`: shared data loading and media helpers for both pages
- `styles.css`: visual system and responsive layout for archive and carousel views
- `data/stories.json`: generated story payload
- `site-config.js`: runtime source configuration for static JSON or Supabase
- `media/`: copied media assets that are safe to publish with the site

## Public content rules

- The archive page shows title, theme, keywords, summary, narrative, and context/connections only.
- The carousel page shows title, theme, references, AI copy, and public asset caption/citation metadata.
- Contributor data, contact details, submission IDs, internal review notes, and display queue data are intentionally omitted from the public payload.
