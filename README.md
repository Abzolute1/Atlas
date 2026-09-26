# Atlas

Native desktop asset catalog for a personally held Megascans metadata snapshot.
Dark Qt interface, real preview images, structured asset types, local search,
favorites and manual or saved-search collections. Browsing never requests asset
payloads. Online preview images are fetched lazily; they can be disabled.

## Launch

Run `./run.sh`, or choose **Atlas** in your desktop applications menu.
Python 3.12, PySide6 and SQLite; no browser or web server required.

On another machine, install `uv`, then `uv sync --python 3.12` and `./run.sh`.
Import a metadata `.tar.zst` archive or an existing Bridge download folder from
**Import library**. The code repository contains no asset library or account token.

## Search and collections

- Ctrl+F focuses the search bar. Escape clears it.
- Names, tags, source taxonomy and exact Quixel IDs are searchable.
- Multiple terms narrow results. Quotes require a phrase; `grass -dry` excludes dry.
- Related terms adds curated synonyms/concepts and typo correction. Exact name
  matches rank first. Disable it for literal metadata search (with word stemming).
- This is SQLite FTS5 with weighted BM25 and curated vocabulary expansion, **not
  an embedding model or image-recognition service**. It cannot identify concepts
  absent from the metadata and vocabulary. Extend `CONCEPTS` in `catalog.py`.
- Click an asset type to expand its source subtypes and filter the grid.
- Use the type buttons below search to combine types. For example, search `grass`
  and select **3D Plants** plus **Surfaces** to see both kinds together. **3D Models**
  corresponds to Quixel's **3D Assets** category; vegetation meshes are usually
  under **3D Plants**. Selected types use OR; text and other filters narrow results.
  **All types** clears the type filter. Changing type buttons clears a subtype
  selection. Saved searches and JSON exports retain the combined type filter.
- Favorites and collections persist across sessions. Add selected assets to a
  named collection, or save a query and its filters as a live collection.
- Right-click a personal collection to delete it or remove the selected member.
- Click a card’s heart to toggle its favorite status. Click a tag in asset details
  to search for that tag while keeping the active type filters.
- Double-click a card for a larger preview. Resolution and sort filters combine
  with search. Results are paginated, 120 per page.

## Quality and downloads

Click **Download asset…** to review the exact selected filenames,
estimated payload size and destination before starting. Four presets:

| Preset | Preferred texture resolution | Preferred geometry |
|---|---|---|
| Low | 1K | LOD3, nearest available |
| Medium | 2K | LOD2, nearest available |
| High | 4K | LOD0, nearest available |
| Ultra | Highest available | Original mesh where present, otherwise LOD0 |

Actual availability wins: a 4K-only asset does not become 8K in Ultra. The UI shows
what will really be selected. JPEG is preferred for supported texture maps; FBX
for meshes. Core PBR maps are included; extra alternate maps and ZBrush source
files are not included by default. The size estimate is the sum of metadata file
sizes, not compressed archive size. Old metadata can differ from current files.

**Connect Quixel** reads your acquired IDs using a session token pasted into a
password field. The token stays in memory, never in the database or logs. Downloads
recheck acquisition with Quixel before requesting signed file URLs. Only the
chosen filenames may be transferred; missing signed files fail closed, with no
unauthenticated CDN fallback. Credentials are never forwarded to file hosts.
Files go into a new named asset/quality subfolder. Existing files are never
silently overwritten. Cancellation removes the active partial file and retains
completed files. Each completed download has a SHA-256 manifest.

**Live authenticated downloading has not been tested with the user's account.**
The adapter uses Quixel's legacy documented API and may need updates if the service
changes. Authentication and access errors are shown explicitly. No assets were
claimed or downloaded during development. Fab-only entitlements are not treated
as Quixel entitlements: **Find on Fab** opens official search for those assets.
There is no automatic Fab purchase or Fab download adapter in this version.

## Data, storage and licensing

Default data directory: `~/.local/share/scanatlas` (override `SCANATLAS_DATA`).
`catalog.sqlite` holds the catalog and preferences. `previews/` holds an on-demand
image cache (pruned to 256 MiB on launch/exit). Image memory cache is bounded.
The initial installed database has 18,870 legacy records and is approximately
321 MB; only metadata, filenames and tiny embedded previews are indexed.
The 38.3 MB compressed metadata archive is streamed, not expanded to a 1.5 GB file.

Metadata source:
https://github.com/WAUthethird/quixel-megascans-scripts
(snapshot available when fetched September 25, 2026; repository last pushed
September 2025). Original Quixel categories, tags, dimensions and file sizes are
retained. The UI classifies asset types using `semanticTags.asset_type`; these
counts can differ from older top-level facet totals. There is no inferred claim
that merely appearing in this catalog means you own an asset.

Catalog metadata, previews and assets remain subject to their respective owners'
rights. This application does not grant permission to redistribute them. The
application source code is MIT-licensed; the imported catalog is not included in
that grant. Quixel and Megascans are trademarks of their respective owners.
ScanAtlas is an independent application, not an official Quixel product.

API references:
- https://quixel.github.io/megascans-api-docs/assets/
- https://quixel.github.io/megascans-api-docs/asset-downloads/

## Verification

`uv run pytest -q`

Tests cover search ranking/filtering, typo and ID search, collections/persistence,
quality selection, entitlement gating, selected-file-only transfer, credential
separation, cancellation cleanup and offline native UI interactions. Downloads
are mocked in tests; no asset files are requested from Quixel.

## Agent interface

See [AGENT_GUIDE.md](scanatlas/AGENT_GUIDE.md) for JSON commands, vision preview
sheets, exact quality plans, background downloads and persistent status tracking.
Start with `atlas capabilities`. Launch the installed desktop with `atlas-desktop`.
