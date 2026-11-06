# PST Investigator

PST Investigator is a read-only, local investigation workbench for indexing and searching Outlook PST files. It uses SQLite with FTS5 for fast full-text searching and Flask for the responsive review interface.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 run.py --source /path/to/pst-files --data ./data
```

Then open `http://127.0.0.1:5000`. The source directory and the data directory are separate: the application never writes to the source directory.

The official libpff bindings are installed by `requirements.txt` with `pip install libpff-python` (the import name remains `pypff`). Do not install an unrelated package whose distribution name is simply `pypff`. Indexing reports a clear error if the adapter is not installed. A PST's SHA-256 is recorded before parsing and indexing is skipped when its path, size, mtime, and content hash are unchanged.

## Safety and evidence

Email HTML is sanitized before it is displayed: scripts, forms, frames, remote images and remote links are removed. Attachments are never opened automatically. Exports contain metadata, a per-file SHA-256, and JSON/CSV manifests.

For production use, run the application behind an authenticated local reverse proxy and retain the original PST hash record with the case notes.
