"""PST adapter. The import is deliberately lazy so the web UI remains usable without libpff."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime

def _value(obj, *names, default=""):
    for name in names:
        candidates = [name]
        if not name.startswith("get_"):
            candidates.append("get_" + name)
        for candidate in candidates:
            try:
                value = getattr(obj, candidate)
            except Exception:
                continue
            value = value() if callable(value) else value
            if value is not None:
                return value
    return default

def _text(value):
    if value is None: return ""
    if isinstance(value, bytes): return value.decode("utf-8", "replace")
    return str(value)

def _date(value):
    if not value: return ""
    if isinstance(value, datetime):
        if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return _text(value)

def _recipients(message, kind):
    names = {"to": ["display_to", "get_display_to"], "cc": ["display_cc", "get_display_cc"], "bcc": ["display_bcc", "get_display_bcc"]}[kind]
    return _text(_value(message, *names))

def load_pst(path):
    try:
        import pypff
    except ImportError as exc:
        raise RuntimeError("pypff/libpff is required to index PST files. Install pypff for your platform.") from exc
    # Current libpff-python exposes pypff.open(path). Older builds expose the
    # pypff.file() constructor instead. Supporting both avoids depending on a
    # particular distro's binding version.
    if callable(getattr(pypff, "open", None)):
        pst = pypff.open(str(path))
    elif callable(getattr(pypff, "file", None)):
        pst = pypff.file()
        pst.open(str(path))
    else:
        attrs = ", ".join(x for x in dir(pypff) if not x.startswith("_"))
        raise RuntimeError("The imported pypff module is not the libpff bindings (no open() or file()). "
                           "Install the libpff-python package, not an unrelated package named pypff. "
                           f"Available attributes: {attrs}")
    try:
        yield from _walk_folder(pst.get_root_folder(), "")
    finally:
        try: pst.close()
        except Exception: pass

def _walk_folder(folder, parent):
    name = _text(_value(folder, "name", "display_name", default=""))
    folder_path = "/".join(x for x in [parent, name] if x)
    for i in range(_value(folder, "number_of_sub_messages", default=0) or 0):
        try:
            yield _message(folder.get_sub_message(i), folder_path)
        except Exception as exc:
            yield {"error": f"message {i}: {exc}", "folder": folder_path}
    for i in range(_value(folder, "number_of_sub_folders", default=0) or 0):
        yield from _walk_folder(folder.get_sub_folder(i), folder_path)

def _message(message, folder):
    attachments = []
    for i in range(_value(message, "number_of_attachments", default=0) or 0):
        try:
            att = message.get_attachment(i)
            data = b""
            try:
                size = _value(att, "size", default=0) or 0
                data = att.read_buffer(size) if size else b""
            except Exception: pass
            attachments.append({"filename": _text(_value(att, "name", "display_name")), "content_type": _text(_value(att, "mime_type", "content_type")), "size": len(data), "data": data})
        except Exception: pass
    body_text = _text(_value(message, "plain_text_body", "body", "plain_text"))
    body_html = _text(_value(message, "html_body", "html"))
    sender = _text(_value(message, "sender_name", "sender_email_address", "display_from"))
    return {"folder": folder, "sender": sender, "to_recipients": _recipients(message, "to"), "cc": _recipients(message, "cc"), "bcc": _recipients(message, "bcc"), "subject": _text(_value(message, "subject")), "sent_at": _date(_value(message, "client_submit_time", "delivery_time")), "received_at": _date(_value(message, "delivery_time")), "message_id": _text(_value(message, "internet_message_id")), "conversation": _text(_value(message, "conversation_topic")), "importance": _text(_value(message, "importance")), "size": int(_value(message, "size", default=0) or 0), "body_text": body_text, "body_html": body_html, "attachments": attachments}

def as_eml(item):
    msg = EmailMessage()
    msg["From"] = item.get("sender", "")
    for header, key in (("To", "to_recipients"), ("Cc", "cc"), ("Bcc", "bcc"), ("Subject", "subject"), ("Message-ID", "message_id"), ("Date", "sent_at")):
        if item.get(key): msg[header] = item[key]
    if item.get("body_html"):
        msg.set_content(item.get("body_text") or "")
        msg.add_alternative(item["body_html"], subtype="html")
    else: msg.set_content(item.get("body_text") or "")
    for att in item.get("attachments", []):
        if att.get("data") is not None:
            msg.add_attachment(att["data"], maintype="application", subtype="octet-stream", filename=att.get("filename") or "attachment")
    return msg.as_bytes()
