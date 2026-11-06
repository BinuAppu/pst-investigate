import csv, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from .parser import as_eml

def sha256(data): return hashlib.sha256(data).hexdigest()
def safe_name(value): return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "untitled")[:120]

def export(rows, directory, fmt="eml", reference=""):
    root = Path(directory); root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(); manifest = []
    for n, row in enumerate(rows, 1):
        item = dict(row); evidence_id = f"E-{datetime.now(timezone.utc):%Y%m%d}-{n:06d}"
        base = root / f"{evidence_id}_{safe_name(item.get('subject'))}"; base.mkdir(exist_ok=True)
        eml = as_eml(item)
        if fmt == "html": data = (item.get("body_html") or item.get("body_text") or "").encode()
        elif fmt == "txt": data = (item.get("body_text") or "").encode()
        elif fmt == "json": data = json.dumps(item, default=str, indent=2).encode()
        else: data = eml
        suffix = fmt if fmt in ("html", "txt", "json") else "eml"
        target = base / f"message.{suffix}"; target.write_bytes(data)
        hashes = {target.name: sha256(data)}
        for att in item.get("attachments", []):
            if att.get("data") is not None:
                p = base / safe_name(att.get("filename")); p.write_bytes(att["data"]); hashes[p.name] = sha256(att["data"])
        metadata = {"evidence_id": evidence_id, "source_pst": item.get("source_pst"), "folder": item.get("folder"), "message_id": item.get("message_id"), "export_timestamp": stamp, "investigation_reference": reference, "file_hashes": hashes}
        (base / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        manifest.append({"Evidence ID": evidence_id, "Source PST": item.get("source_pst", ""), "Email Subject": item.get("subject", ""), "From": item.get("sender", ""), "To": item.get("to_recipients", ""), "CC/BCC": "; ".join(filter(None, [item.get("cc", ""), item.get("bcc", "")])), "Email Date": item.get("sent_at", ""), "Message ID": item.get("message_id", ""), "Export Date": stamp, "Export Format": suffix, "SHA-256": hashes[target.name]})
    if manifest:
        with (root / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(manifest[0])); writer.writeheader(); writer.writerows(manifest)
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root, manifest
