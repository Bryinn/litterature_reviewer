# Fieldnotes

A local literature review workspace for the `good`, `bad`, `mby`, and `uncategorized` folders.
You will have to create these folders locally yourself within this folder

## Run

From this folder, run:

```powershell
py server.py
```

Then open <http://localhost:8765>. Use `py server.py --port 9000` if the default port is busy.

The app reads PDF, HTM, and HTML papers directly from the four folders. Notes, section tags, DOI, and last-opened state are stored in `review_metadata.json` (created on first save). Categorizing moves the paper on disk. Citation lookup uses Crossref's public API and requires internet access; local browsing and metadata persistence work without it.

DOIs found in paper contents or entered during editing are used for canonical titles and Crossref citation lookup. The app does not download papers from DOI links.
