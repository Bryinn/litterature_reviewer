from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FOLDERS = ("uncategorized", "good", "mby", "bad")
PAPER_EXTENSIONS = {".pdf", ".htm", ".html"}
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
STATIC_FILES = {"": "index.html", "index.html": "index.html", "app.js": "app.js", "styles.css": "styles.css"}
METADATA_FILE = ROOT / "review_metadata.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_metadata() -> dict:
    if not METADATA_FILE.exists():
        return {}
    try:
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_metadata(metadata: dict) -> None:
    temporary = METADATA_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temporary.replace(METADATA_FILE)


def paper_id(filename: str) -> str:
    return hashlib.sha1(filename.casefold().encode("utf-8")).hexdigest()[:16]


def safe_paper_path(folder: str, filename: str) -> Path:
    if folder not in FOLDERS or Path(filename).name != filename or Path(filename).suffix.casefold() not in PAPER_EXTENSIONS:
        raise ValueError("Invalid paper path")
    path = (ROOT / folder / filename).resolve()
    if path.parent != (ROOT / folder).resolve():
        raise ValueError("Invalid paper path")
    return path


def detect_doi(path: Path) -> str:
    try:
        content = path.read_bytes()[:2_000_000].decode("latin-1", errors="ignore")
    except OSError:
        return ""
    match = DOI_PATTERN.search(content)
    if not match:
        return ""
    value = match.group(0).rstrip(".,;)")
    return value.split(")/", 1)[0].rstrip(".,;)")


def scan_papers() -> list[dict]:
    metadata = load_metadata()
    papers = []
    for folder in FOLDERS:
        directory = ROOT / folder
        directory.mkdir(exist_ok=True)
        for path in sorted((item for item in directory.iterdir() if item.is_file() and item.suffix.casefold() in PAPER_EXTENSIONS), key=lambda item: item.name.casefold()):
            filename = path.name
            identifier = paper_id(filename)
            entry = metadata.get(identifier, {})
            tags = entry.get("tags", [entry["section"]] if entry.get("section") else [])
            doi = detect_doi(path) or entry.get("doi", "")
            papers.append({
                "id": identifier,
                "name": filename,
                "folder": folder,
                "url": f"/files/{folder}/{urllib.parse.quote(filename)}",
                "filePath": str(path),
                "fileUrl": path.as_uri(),
                "note": entry.get("note", ""),
                "section": tags[0] if tags else "",
                "tags": tags,
                "doi": doi,
                "lastOpened": entry.get("lastOpened"),
                "updatedAt": entry.get("updatedAt"),
            })
    return papers


def json_response(handler: BaseHTTPRequestHandler, payload: object, status=HTTPStatus.OK) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def citation_for(title: str, doi: str = "") -> dict:
    cleaned_title = re.sub(r"\.(pdf|html?)$", "", title, flags=re.IGNORECASE).replace("_", " ").replace("-", " ")
    endpoint = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}" if doi else f"https://api.crossref.org/works?{urllib.parse.urlencode({'query.bibliographic': cleaned_title, 'rows': 1})}"
    request = urllib.request.Request(
        endpoint,
        headers={"User-Agent": "MSC-Literature-Review/1.0 (local app)"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        result = json.load(response)
    items = [result.get("message", {})] if doi else result.get("message", {}).get("items", [])
    if not items or not items[0]:
        raise LookupError("No matching publication found")
    item = items[0]
    authors = []
    for author in item.get("author", []):
        family = author.get("family", "")
        given = author.get("given", "")
        authors.append(f"{family}, {given}".strip(", "))
    year = (item.get("published-print") or item.get("published-online") or {}).get("date-parts", [[""]])[0][0]
    journal = (item.get("container-title") or [""])[0]
    doi = item.get("DOI", "")
    published_title = item.get("title", [cleaned_title])[0]
    entry_type = {"journal-article": "article", "proceedings-article": "inproceedings", "book-chapter": "incollection"}.get(item.get("type"), "misc")
    bibtex_authors = " and ".join(
        ", ".join(filter(None, [author.get("family", ""), author.get("given", "")]))
        for author in item.get("author", [])
    )
    return {
        "text": "; ".join(filter(None, [", ".join(authors), str(year), published_title, journal, doi])),
        "entryType": entry_type,
        "author": bibtex_authors,
        "title": published_title,
        "year": str(year),
        "journal": journal,
        "volume": item.get("volume", ""),
        "number": item.get("issue", ""),
        "pages": item.get("page", ""),
        "publisher": item.get("publisher", ""),
        "doi": doi,
        "url": f"https://doi.org/{doi}" if doi else item.get("URL", ""),
    }


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "LiteratureReview/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/papers":
            json_response(self, {"papers": scan_papers(), "folders": FOLDERS})
            return
        if parsed.path == "/api/citation":
            query = urllib.parse.parse_qs(parsed.query)
            title = query.get("title", [""])[0]
            doi = query.get("doi", [""])[0].strip()
            if not title and not doi:
                json_response(self, {"error": "A title or DOI is required"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                json_response(self, citation_for(title, doi))
            except Exception as error:
                json_response(self, {"error": f"Citation lookup failed: {error}"}, HTTPStatus.BAD_GATEWAY)
            return
        if parsed.path.startswith("/files/"):
            parts = parsed.path.split("/", 3)
            if len(parts) == 4:
                try:
                    file_path = safe_paper_path(parts[2], urllib.parse.unquote(parts[3]))
                except ValueError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if file_path.exists():
                    data = file_path.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    content_type = "application/pdf" if file_path.suffix.casefold() == ".pdf" else "text/html; charset=utf-8"
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", f'inline; filename="{file_path.name}"')
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        relative = parsed.path.lstrip("/")
        if relative in STATIC_FILES:
            path = ROOT / STATIC_FILES[relative]
            content_type = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}[path.suffix]
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = read_json(self)
            metadata = load_metadata()
            identifier = payload.get("id", "")
            if parsed.path == "/api/metadata":
                if not identifier:
                    raise ValueError("A paper ID is required")
                entry = metadata.setdefault(identifier, {})
                if "note" in payload:
                    entry["note"] = str(payload["note"])[:5000]
                if "section" in payload:
                    entry["section"] = str(payload["section"])[:200]
                if "tags" in payload:
                    entry["tags"] = [str(tag)[:100] for tag in payload["tags"][:20] if str(tag).strip()]
                if "doi" in payload:
                    entry["doi"] = str(payload["doi"]).strip()[:200]
                entry["updatedAt"] = now_iso()
                save_metadata(metadata)
                json_response(self, {"ok": True, "metadata": entry})
                return
            if parsed.path == "/api/opened":
                for paper_metadata in metadata.values():
                    paper_metadata.pop("lastOpened", None)
                metadata.setdefault(identifier, {})["lastOpened"] = now_iso()
                save_metadata(metadata)
                json_response(self, {"ok": True})
                return
            if parsed.path == "/api/open-system":
                filename = payload.get("name", "")
                folder = payload.get("folder", "")
                file_path = safe_paper_path(folder, filename)
                if not file_path.exists():
                    raise FileNotFoundError(filename)
                if not hasattr(os, "startfile"):
                    raise OSError("System file opening is only supported on Windows")
                os.startfile(str(file_path))
                for paper_metadata in metadata.values():
                    paper_metadata.pop("lastOpened", None)
                metadata.setdefault(payload.get("id", paper_id(filename)), {})["lastOpened"] = now_iso()
                save_metadata(metadata)
                json_response(self, {"ok": True})
                return
            if parsed.path == "/api/categorize":
                target = payload.get("target")
                filename = payload.get("name", "")
                source = payload.get("folder", "uncategorized")
                if target not in FOLDERS:
                    raise ValueError("Invalid destination folder")
                source_path = safe_paper_path(source, filename)
                target_path = safe_paper_path(target, filename)
                if not source_path.exists():
                    raise FileNotFoundError(filename)
                if target != source and target_path.exists():
                    raise FileExistsError(f"{filename} already exists in {target}")
                if target != source:
                    shutil.move(str(source_path), str(target_path))
                entry = metadata.setdefault(identifier or paper_id(filename), {})
                if "note" in payload:
                    entry["note"] = str(payload["note"])[:5000]
                if "section" in payload:
                    entry["section"] = str(payload["section"])[:200]
                if "tags" in payload:
                    entry["tags"] = [str(tag)[:100] for tag in payload["tags"][:20] if str(tag).strip()]
                if "doi" in payload:
                    entry["doi"] = str(payload["doi"]).strip()[:200]
                entry["updatedAt"] = now_iso()
                save_metadata(metadata)
                json_response(self, {"ok": True, "paper": next(p for p in scan_papers() if p["name"] == filename)})
                return
            raise ValueError("Unknown endpoint")
        except FileNotFoundError as error:
            json_response(self, {"error": f"File not found: {error}"}, HTTPStatus.NOT_FOUND)
        except (ValueError, FileExistsError, json.JSONDecodeError) as error:
            json_response(self, {"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            json_response(self, {"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self):
        try:
            payload = read_json(self)
            filename = payload.get("name", "")
            folder = payload.get("folder", "")
            identifier = payload.get("id", paper_id(filename))
            file_path = safe_paper_path(folder, filename)
            if not file_path.exists():
                raise FileNotFoundError(filename)
            file_path.unlink()
            metadata = load_metadata()
            metadata.pop(identifier, None)
            save_metadata(metadata)
            json_response(self, {"ok": True})
        except FileNotFoundError as error:
            json_response(self, {"error": f"File not found: {error}"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            json_response(self, {"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            json_response(self, {"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Local literature review workspace")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    for folder in FOLDERS:
        (ROOT / folder).mkdir(exist_ok=True)
    print(f"Literature review workspace: http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), ReviewHandler).serve_forever()
