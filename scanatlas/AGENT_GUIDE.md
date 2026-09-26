# Atlas 0.4 — agent quick start

The website-style desktop UI is optional. Catalog search, plans, previews,
download jobs and staging work through CLI or the `atlas mcp` stdio MCP server.
The Mixamo session now runs in a separate background process and auto-starts on
agent commands. It does not require the Atlas catalog window.

## Mixamo session and agent commands

1. Run `atlas mixamo connect`, or click Mixamo in the desktop. The USER signs in
   directly on Adobe's page. Never ask for passwords/cookies in chat.
2. Close the sign-in window to hide it. The background service stays alive.
3. `atlas mixamo status` returns UI readiness, current cards, selection and jobs.
   `ready` is observed export controls, not a verified Adobe API entitlement.
   `last_successful_export` records completed transfers in this service session;
   `authentication_check: not_performed` is not a download failure.
4. `atlas mixamo search walking --type Animations` returns current-page `ref`s.
   Use `--type Characters` for characters, `--page N` for later pages.
5. `atlas mixamo select RETURNED_REF`, then `atlas mixamo prepare-download`.
6. `atlas mixamo download --type Animations --character LOCAL_CHARACTER_ID
   --destination /existing/folder` is a dry run. Add `--execute` to request the
   selected export. Character downloads use `--type Characters` (With Skin);
   animation downloads use Without Skin. Format is verified as FBX for Unity.
7. Poll `atlas mixamo status`; successful jobs return `asset_id` and local path.
   FBXs are automatically indexed for normal Atlas search and `atlas stage`.
8. `atlas mixamo preview --output /new/path.png` captures the ready browser for
   vision. Login pages are refused. Preview files are never overwritten.

Session cookies remain in memory only; reboot/service restart requires sign-in.
`atlas mixamo disconnect` stops the helper and clears that session. Export jobs
are session-scoped; completed assets and their file hashes persist in the catalog.
Mixamo size is unknown until transfer. Original FBX does not imply 2K textures or
Medium mesh complexity. Rigging and animation playback must be validated in Unity.
Live verification on 2026-09-25: signed-in search found 370 walking results;
Walking on X Bot exported as FBX for Unity Without Skin (366,208 bytes), and
With Skin (1,839,568 bytes). Both transfers completed and were indexed locally.
This verifies export and catalog ingestion; Unity Avatar/playback validation is
still required. Do not treat DOM readiness as proof that a new export will work.

MCP tools expose catalog search/inspect/plan/preview/download/status/stage and
Mixamo connect/status/search/select/prepare/download/preview. `execute` defaults
false. Environment downloads default to Medium/2K and run as background jobs.
Current sessions can always invoke the same `atlas` CLI if MCP has not reloaded.

# Atlas agent contract — atlas.v1

## My assets — personal Mixamo derivatives

The desktop's My assets section and `atlas search --scope my-assets` expose
personal derivatives, retaining Mixamo source attribution and license terms.
MCP `atlas_search` also accepts `scope: "my-assets"`.

```
atlas import-mixamo /path/Package/Arms.fbx --type Characters --name "Military FPS Arms" --my-asset --bundle /path/Package --preview /path/Package/preview.png --tags "fps arms gloves sleeves military"
atlas search arms --scope my-assets --brief
atlas stage RETURNED_ID --destination /new/handoff --execute
```

`--bundle` explicitly indexes all files in that directory, including textures,
editable Blender sources, previews and handoff instructions. Staging preserves
relative paths in an asset-ID subfolder and verifies every file hash. After
editing a package, re-import it to refresh the manifest. Search availability
reports the total package size and file count. My assets means personally saved
or edited; it does not grant redistribution rights or claim original authorship.

Use `atlas capabilities` first. All agent commands write a single JSON object to
stdout, with `schema: atlas.v1`; failures include error.code/error.message and
exit nonzero. Argument parsing errors use standard argparse stderr/exit 2.
Run `atlas gui` or `atlas-desktop` for the native application.
Catalog operations require no browser; Mixamo uses the isolated background browser service.

## Search → see → inspect → plan → download → import

```
atlas search grass --type '3D Plants' --type Surfaces --limit 12
atlas inspect ASSET_ID
atlas preview ID1 ID2 ID3 --output /tmp/atlas-candidates.png --fetch-previews
atlas plan ASSET_ID --quality Medium
atlas download ASSET_ID --quality Medium --destination /path/to/staging
atlas download ASSET_ID --quality Medium --destination /path/to/staging --execute --background
atlas status --job JOB_ID
atlas cancel JOB_ID
```

Replace uppercase placeholders with returned IDs, not names. Search supports
pagination, literal mode, subtype, minimum resolution, and ownership/favorite
scopes. Types combine with OR. Exact quoted phrases and negative terms work.
`facets` provides the actual source taxonomy. 3D vegetation is usually 3D Plants.
Search and inspect include four quality plans with size_bytes, size_is_complete,
resolution, and file_count. Estimates come from historical metadata, not a live
server quote. Inspect/plan expose exact relative filenames, MIME, LOD and triangles
where available. Missing metadata is not evidence of zero size or low complexity.

## Vision

Preview emits image_path and manifest_path. Open the PNG with your vision tool.
Each numbered tile has a readable ID/name/type and four size estimates. The JSON
maps numbers and pixel rectangles to IDs and records whether the image came from
cache, online preview, a low-resolution embedded thumbnail, or is unavailable.
Missing/low-resolution images must not be treated as reliable visual evidence.
Maximum 24 tiles; use smaller sheets or a single ID for closer inspection.
Single-ID sheets are larger and prefer the higher-resolution gallery preview when
--fetch-previews is set. Manifests include the actual source pixel dimensions. Output
files are never overwritten. Use unique filenames for subsequent sheets.
Without --fetch-previews only cached/embedded images are used. That flag fetches
only preview images (8 MiB limit per image), never models or texture payloads.

## Downloads and Unity

Without --execute, download is a dry run. To execute, provide
ATLAS_QUIXEL_TOKEN in the process environment using your credential provider.
Never include it in command arguments, logs, source files or prompts. The desktop
session's token is not exposed to the CLI. Entitlements are checked live for every
transfer. Legacy Quixel authentication/download remains unverified against a live
account; Fab-only entitlements must use the official Fab flow.

Background execution returns a job ID. Poll status until complete, failed, or
cancelled. It reports bytes_done, estimated bytes_total, current_file, updated Unix
time, heartbeat age, destination, error, and final path. potentially_stale flags
nonterminal jobs without updates for >180 seconds; verify the process before
retrying. Abrupt machine/process termination cannot report its own failure.
Cancellation is cooperative and can wait for network timeouts. Completed files
may remain after failure/cancel; no automatic resume or overwrite is attempted.
Desktop and CLI downloads share this job store. Historic downloads made before
job tracking remain in download_history and inspect.downloads.

Only import after a complete status. Read <path>/download.json for exact files and
SHA256 checksums. Paths point to a staging folder selected by the user/agent; Atlas
does not silently write into a Unity project. Use your Unity tooling to import the
chosen mesh/textures and configure materials. Source units/dimensions are metadata,
not an automatic Unity scale conversion. Do not use preview images as materials.

## Storage and installation

System app: /opt/atlas; entrypoints: /usr/local/bin/atlas, atlas-desktop.
Each user retains a private database under ~/.local/share/scanatlas for backward
compatibility. Override with SCANATLAS_DATA or global --database PATH. The installed
package does not redistribute the community metadata snapshot or user libraries.
Existing favorites/collections/cache are preserved. Other users can import their
own legally held metadata from the desktop. Source code is MIT; third-party assets
and metadata retain their own terms.

Medium is the default for CLI plans/downloads and the desktop. Texture selection
never exceeds the selected resolution cap (Medium: 2048px); unavailable maps
fail the plan instead of silently downloading larger textures. Mesh LOD is separate.

## Active Hugging Face source

`atlas sources` reports indexed sources and archive leads. `atlas sync-huggingface`
refreshes metadata only from Sl8th/Megascans, pins file URLs to its commit, and
activates the source-backed catalog. Historical Quixel records remain stored but
are hidden from search, inspect, facets and counts. No asset payloads are fetched
by sync. Only folders with identifiable Quixel JSON and loose usable texture files
are indexed along with ZIP packages. Unrelated repository uploads retain unverified-license labels; they are not presented as original Megascans.

Use `atlas search grass --available-quality Medium` to exclude assets with no
2K-or-lower plan. The source predominantly carries 4K/8K files: never silently
substitute those for Medium. Public availability is not verified redistribution
permission: the uploader states no license. Inspect exposes source, source_url,
repository, revision, quixel_id and duplicate_key. Equal duplicate_key values mean
sources may refer to the same original asset; names alone are not proof.

Hugging Face downloads need no Quixel token. They use the same explicit --execute,
background jobs, destination folders and download.json manifests. File sizes and
source SHA256 hashes are checked before finalizing files. 3D/surface archive leads
are exposed by `sources` with listing_only status; they are not downloadable assets.

Verified smoke test: hf_oi3tzbp0 (Yellow Leather), Medium, in
/home/alex/AtlasDownloads/Yellow Leather_hf_oi3tzbp0_medium.
This is a texture set, not a mesh. Unity import/material setup is a separate step.

## Mixamo characters and animations

Run `atlas mixamo-guide` for structured setup and Unity handoff instructions.
Mixamo requires your Adobe ID in the browser. Atlas does not bulk-index its remote catalog or automate credential entry. Its browser bridge searches live pages only after user sign-in.
Use Import library → Open Mixamo, then download a character With Skin and selected
animations Without Skin, exported for that character as FBX for Unity.

```
atlas import-mixamo /path/Character.fbx --type Characters --preview /path/character.png
atlas import-mixamo /path/Walking.fbx --type Animations --character CHARACTER_ID --tags "walk locomotion in-place"
atlas search walking --type Animations --brief
atlas inspect ANIMATION_ID
atlas stage CHARACTER_ID ANIMATION_ID --destination /path/new-staging-folder
atlas stage CHARACTER_ID ANIMATION_ID --destination /path/new-staging-folder --execute
```

Imports index existing FBXs without copying them. Supply a screenshot with
`--preview` for vision contact sheets; Atlas does not render FBXs. The declared
role, tags, and source are user-supplied. FBX header recognition is not full file
validation. Rig compatibility, duration, frame rate, texture resolution and root
motion are not inferred. `availability` reports local file presence, size and
recorded SHA256; staging checks actual hashes and refuses changed files.
Identical FBX bytes have one stable ID. Staging copies only selected files plus
`atlas-manifest.json`; linked characters are not silently added. External texture
files are not collected: export embedded textures or handle those dependencies
explicitly. Original FBXs have no Low/Medium/High tiers or automatic 2K conversion.
Unity must validate the Humanoid Avatar and animation playback before use.
Search `--brief` reduces response size; inspect selected IDs for complete detail.

## Connected public catalogs

`atlas sync-public` refreshes metadata for Poly Haven, ambientCG and the selected
Hugging Face repository. No model or texture files are downloaded during sync.
Search now spans all connected catalogs; `--source polyhaven`, `--source ambientcg`
and `--source huggingface` narrow results. Types combine with OR.

```
atlas search grass --type Surfaces --type '3D Assets' --brief --limit 12
atlas search brick --source ambientcg --available-quality Medium --brief
atlas plan polyhaven_ArmChair_01 --quality Medium
atlas download polyhaven_ArmChair_01 --quality Medium --destination /existing/folder
# Review exact size/files, then add --execute to download.
```

Poly Haven file manifests are fetched on demand by `plan` or `download`; search
stays local. `available: null` means an unverified quality candidate, not a verified
transfer plan. `--available-quality` includes these candidates based on advertised
maximum resolution; always run `plan` before committing. Public downloads need no
Quixel token. Model dependencies retain relative paths. ambientCG downloads a
single resolution-specific ZIP; extract that ZIP before importing into Unity.
HF archive-only entries carry their original resolution; unknown-resolution
packages are offered only at Ultra (original), never represented as 2K/Medium.
These uploads have unverified licenses and are not all Megascans.

Sources show both CGer archive listings, but neither has a verified per-asset
manifest or accessible download adapter. They do not add invented search records.
Mixamo live search uses `atlas mixamo search`; normal `atlas search` lists only
imported Mixamo FBXs. Successful exports are automatically imported. Use
`atlas sources` to distinguish local library counts from live search results.
Desktop: source dropdown + type filter + Reset;
Sources → Sync public catalogs; Open source opens the selected provider's page.

Preview cache (0.4.2): The desktop lazily fetches visible thumbnails into the same
256 MiB disk cache used by `atlas preview`. Reopening Atlas reuses cached images;
`atlas-desktop --offline` displays cached and local previews without requests.
Cache pruning runs after new image writes, not on every launch. Local generated
Mixamo previews are retained separately. Missing imported FBX previews are rendered
in the background with Blender when configured (`preview_blender` catalog setting
or Blender on PATH). `atlas render-previews [IDs...] --retry` retries failed local
renders without downloading any assets. Animations require a linked matching
character or embedded skin. The saved preview gallery contains three sampled poses,
not a full playback or Unity rig validation.

Mixamo catalog (0.5.0): `atlas sync-mixamo` indexes every public product record
(names, stable IDs, descriptions, preview URLs) without downloading FBXs. Search
`--source mixamo --type Animations` or `--type Characters` uses local SQLite, even
when Atlas and the Mixamo website are closed. `--scope downloaded` restricts to
imports. `availability.state=remote_catalog` is browseable metadata, not a local
file. Animation packs are clearly marked; export their individual clips.

Use `atlas mixamo-export CATALOG_ID --destination EXISTING_FOLDER` to inspect the
export plan; `--execute` uses the signed-in background session to select the exact
catalog variant and export FBX for Unity. MCP has `atlas_mixamo_export` with the
same dry-run default. Size is unknown until export starts; no Medium/2K conversion
is implied. For animations, optional `--character DOWNLOADED_CHARACTER_ID` selects
a character with a verified catalog link; otherwise the current session character
is used and the import remains unlinked. Poll `atlas mixamo status` / MCP
`atlas_mixamo_status` for completion, the imported asset ID, and bytes. Stage that
local ID. Character replacement may require confirmation in the Mixamo panel if
Adobe shows its confirmation dialog. Initial login remains required for exports.
Static thumbnails and optional animated GIF previews share Atlas's disk cache.

Catalog navigation (0.5.1): Sidebar categories and sources browse their complete
catalog totals and clear previous search/filter state. Use the top asset-type
checkboxes and source selector to filter an existing search instead. Search and
type filters appear as removable chips. Pages show both the matching asset total
and page count; entries have a stable ID tie-breaker so equal names do not drift
between pages. Preview cache failures retry once automatically; failed cards offer
Retry preview. Damaged cache entries are regenerated on access. Missing source
thumbnails remain explicitly labeled rather than fabricated.


## Import downloaded assets into Unity

Atlas automatically targets the sole Unity project that is open, including Editors
launched from Unity Hub on Linux. If several projects are open, choose the target with
the Unity project control or pass `--project`; Atlas won't guess between them. With
no Editor open, Atlas falls back to the saved project. The first executed import into
a project installs Atlas's bundled Editor helper and, when the Unity CLI is available, the optional Unity
Pipeline package used for Editor status and refresh commands. Each Unity project has
its own package manifest, so this setup happens once per project:

```sh
atlas unity-configure /path/to/project
```

Download chosen assets into the user's OS folder as usual, then:

```sh
atlas unity-import ASSET_ID --quality Medium
atlas unity-import ASSET_ID --quality Medium --execute
atlas unity-status --job JOB_ID
```

The first command plans only. The executed import copies supported FBX/OBJ/textures,
safely expands ZIPs, and queues the Unity work under `Assets/Atlas/Imported`. Source
files stay in place. Local Mixamo characters/animations and My assets use original
FBX quality. `--rig generic` can preserve a nonhumanoid rig; the default is `auto`.
Unity must have the target project open to process the queue (including the first
helper compilation). The importer itself does not depend on the Pipeline package.
Status `queued` or `processing` is
not success: wait for `complete`, inspect warnings and the returned prefab, material
and animation paths. Unsupported sources, missing models and failed imports are
reported explicitly. Importing creates assets, never places objects into scenes or
changes gameplay controllers. Identical imports reuse their previous job.

MCP equivalents: `atlas_unity_configure`, `atlas_unity_import` (dry-run by default),
and `atlas_unity_status`. These work with the Atlas UI closed. The desktop has a
Unity project connection and an **Import to Unity** button beside download options.

Progress: `atlas status` returns `progress_percent` from transferred bytes (null when total size is unknown). `atlas unity-status` returns `progress_percent`, `progress_estimated`, and `stage`. Unity progress is a weighted phase estimate, not an ETA; wait for `status: complete` before consuming generated outputs. Queued means the project must be open and ready in Unity.

Unity handoff: Atlas checks which projects have an Editor open. When the target is
open and its Pipeline bridge is ready, Atlas explicitly requests an Editor refresh so
new or updated helper scripts are compiled and queued imports are picked up. Without
a reachable bridge, `editor_wakeup` reports that the job is waiting for the Editor's
file watcher or a manual refresh. Atlas never launches Unity or changes Play Mode, and
a wakeup acknowledgement is not completion; the Editor report is authoritative. If a
job stays queued, check script compilation and choose Assets > Refresh.
