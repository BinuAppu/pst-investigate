import hashlib, json, os
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for
from markupsafe import Markup
from .db import connect, get_setting, set_setting
from .evidence import export
from .parser import load_pst

def create_app(data_dir="./data", source=None):
    app = Flask(__name__); app.secret_key = os.environ.get("PST_INVESTIGATOR_SECRET", "local-investigation-key")
    data = Path(data_dir); data.mkdir(parents=True, exist_ok=True); db_path = data / "investigator.sqlite3"
    conn = connect(db_path)
    if source: set_setting(conn, "source", str(Path(source).expanduser().resolve()))
    conn.commit(); conn.close()
    app.config.update(DB=str(db_path), DATA=str(data))

    @app.template_filter("datetime")
    def format_datetime(value):
        try: return datetime.fromtimestamp(float(value), timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception: return "—"

    @app.template_filter("safe_email_html")
    def safe_email_html(value):
        try:
            import bleach
            return Markup(bleach.clean(value or "", tags=["p","br","div","span","strong","b","em","i","u","ul","ol","li","table","thead","tbody","tr","th","td","blockquote","a"], attributes={"a":["href","title"], "*": ["class"]}, protocols=["mailto"], strip=True))
        except ImportError:
            import re
            return Markup(re.sub(r"<(script|style|iframe|object|form)[^>]*>.*?</\1>", "", value or "", flags=re.I|re.S))

    def db(): return connect(app.config["DB"])
    def hash_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
        return h.hexdigest()
    def index_one(path):
        path = Path(path); stat = path.stat(); digest = hash_file(path); c = db()
        old = c.execute("SELECT * FROM pst_files WHERE path=?", (str(path),)).fetchone()
        if old and old["sha256"] == digest and old["size"] == stat.st_size and old["mtime"] == stat.st_mtime:
            c.close(); return "unchanged"
        if old: c.execute("DELETE FROM emails_fts WHERE rowid IN (SELECT id FROM emails WHERE pst_id=?)", (old["id"],)); c.execute("DELETE FROM pst_files WHERE id=?", (old["id"],))
        cur = c.execute("INSERT INTO pst_files(path,filename,size,mtime,sha256,status,indexed_at) VALUES(?,?,?,?,?,?,?)", (str(path), path.name, stat.st_size, stat.st_mtime, digest, "indexing", datetime.now(timezone.utc).isoformat()))
        pst_id = cur.lastrowid; total = indexed = 0; errors = []
        try:
            for item in load_pst(path):
                total += 1
                if item.get("error"): errors.append(item["error"]); continue
                atts = item.pop("attachments", []); item["pst_id"] = pst_id
                fields = "pst_id,folder,sender,to_recipients,cc,bcc,subject,sent_at,received_at,message_id,conversation,importance,size,body_text,body_html"
                vals = [item.get(x, "") for x in fields.split(",")]
                cur2 = c.execute(f"INSERT INTO emails({fields}) VALUES ({','.join('?' for _ in vals)})", vals); email_id = cur2.lastrowid
                names = " ".join(a.get("filename", "") for a in atts)
                from .parser import html_to_text
                search_body = " ".join(filter(None, [item.get("body_text", ""), html_to_text(item.get("body_html", ""))]))
                c.execute("INSERT INTO emails_fts(rowid,subject,sender,to_recipients,cc,bcc,body_text,attachment_names) VALUES(?,?,?,?,?,?,?,?)", (email_id,item.get("subject",""),item.get("sender",""),item.get("to_recipients",""),item.get("cc",""),item.get("bcc",""),search_body,names))
                for a in atts: c.execute("INSERT INTO attachments(email_id,filename,content_type,size,data) VALUES(?,?,?,?,?)", (email_id,a.get("filename"),a.get("content_type"),a.get("size",0),a.get("data")))
                indexed += 1
            status = "indexed"
        except Exception as exc: status = "error"; errors.append(str(exc))
        c.execute("UPDATE pst_files SET total=?,indexed=?,status=?,errors=? WHERE id=?", (total,indexed,status,"\n".join(errors),pst_id)); c.commit(); c.close(); return status

    @app.context_processor
    def context():
        c = db(); value = get_setting(c, "source", ""); c.close(); return {"source": value}

    @app.get("/")
    def index():
        c=db(); psts=c.execute("SELECT * FROM pst_files ORDER BY filename").fetchall(); count=c.execute("SELECT COUNT(*) FROM emails").fetchone()[0]; c.close()
        return render_template("index.html", psts=psts, email_count=count)

    @app.post("/settings")
    def settings():
        folder = request.form.get("source", "").strip(); c=db(); set_setting(c,"source",str(Path(folder).expanduser().resolve()) if folder else ""); c.commit(); c.close(); flash("Source directory saved.", "success"); return redirect(url_for("index"))

    @app.post("/scan")
    def scan():
        settings_db = db(); source_dir = get_setting(settings_db, "source", ""); settings_db.close()
        folder = Path(source_dir); files=sorted(folder.rglob("*.pst")) if folder.is_dir() else []
        for path in files:
            try: index_one(path)
            except Exception as exc: flash(f"{path.name}: {exc}", "error")
        flash(f"Scanned {len(files)} PST file(s).", "success"); return redirect(url_for("index"))

    @app.post("/reindex/<int:pst_id>")
    def reindex(pst_id):
        c=db(); row=c.execute("SELECT path FROM pst_files WHERE id=?",(pst_id,)).fetchone(); c.close()
        if row:
            try: index_one(row["path"]); flash("PST re-indexed.", "success")
            except Exception as exc: flash(str(exc), "error")
        return redirect(url_for("index"))

    @app.post("/remove/<int:pst_id>")
    def remove(pst_id):
        c=db(); row=c.execute("SELECT id FROM pst_files WHERE id=?",(pst_id,)).fetchone()
        if row: c.execute("DELETE FROM emails_fts WHERE rowid IN (SELECT id FROM emails WHERE pst_id=?)",(pst_id,)); c.execute("DELETE FROM pst_files WHERE id=?",(pst_id,)); c.commit()
        c.close(); flash("Removed from index; original file was not changed.", "success"); return redirect(url_for("index"))

    @app.get("/search")
    def search():
        q=request.args.get("q","").strip(); sender=request.args.get("sender","").strip(); subject=request.args.get("subject","").strip(); recipient=request.args.get("recipient","").strip(); start=request.args.get("start",""); end=request.args.get("end",""); sort=request.args.get("sort","sent_at"); direction=request.args.get("direction","desc"); page=max(1,int(request.args.get("page",1))); size=min(250,max(25,int(request.args.get("size",50))))
        allowed={"sent_at":"e.sent_at","sender":"e.sender","subject":"e.subject","to_recipients":"e.to_recipients"}; order=allowed.get(sort,"e.sent_at")+ (" ASC" if direction=="asc" else " DESC")
        joins=" JOIN pst_files p ON p.id=e.pst_id"; where=[]; args=[]
        if q:
            joins += " JOIN emails_fts f ON f.rowid=e.id"; where.append("f.emails_fts MATCH ?"); args.append(q)
        for col,val in (("e.sender",sender),("e.subject",subject)):
            if val: where.append(f"LOWER(COALESCE({col},'')) LIKE LOWER(?)"); args.append("%"+val+"%")
        if recipient: where.append("LOWER(COALESCE(e.to_recipients,'')||' '||COALESCE(e.cc,'')||' '||COALESCE(e.bcc,'')) LIKE LOWER(?)"); args.append("%"+recipient+"%")
        if start: where.append("date(COALESCE(e.received_at,e.sent_at)) >= date(?)"); args.append(start)
        if end: where.append("date(COALESCE(e.received_at,e.sent_at)) <= date(?)"); args.append(end)
        clause=" WHERE "+" AND ".join(where) if where else ""; c=db(); total=c.execute("SELECT COUNT(*) FROM emails e"+joins+clause,args).fetchone()[0]; rows=c.execute("SELECT e.*,p.filename source_pst,p.path source_path,(SELECT COUNT(*) FROM attachments a WHERE a.email_id=e.id) attachment_count FROM emails e"+joins+clause+f" ORDER BY {order} LIMIT ? OFFSET ?",args+[size,(page-1)*size]).fetchall(); c.close()
        return render_template("results.html",rows=rows,total=total,page=page,size=size,pages=max(1,(total+size-1)//size),q=q,filters=request.args)

    @app.get("/email/<int:email_id>")
    def email(email_id):
        c=db(); row=c.execute("SELECT e.*,p.filename source_pst FROM emails e JOIN pst_files p ON p.id=e.pst_id WHERE e.id=?",(email_id,)).fetchone(); atts=c.execute("SELECT * FROM attachments WHERE email_id=?",(email_id,)).fetchall(); c.close()
        if not row: abort(404)
        return render_template("email.html", email=row, attachments=atts)

    @app.get("/attachment/<int:attachment_id>")
    def attachment(attachment_id):
        c = db(); row = c.execute("SELECT filename,content_type,data FROM attachments WHERE id=?", (attachment_id,)).fetchone(); c.close()
        if not row or row["data"] is None: abort(404)
        return send_file(BytesIO(row["data"]), mimetype=row["content_type"] or "application/octet-stream", as_attachment=True, download_name=row["filename"] or "attachment")

    @app.post("/export")
    def do_export():
        ids=[int(x) for x in request.form.getlist("ids")]; fmt=request.form.get("format","eml"); directory=request.form.get("directory","").strip();
        if not ids or not directory: flash("Select messages and an export directory.","error"); return redirect(request.referrer or url_for("index"))
        c=db(); placeholders=','.join('?'*len(ids)); rows=c.execute(f"SELECT e.*,p.filename source_pst FROM emails e JOIN pst_files p ON p.id=e.pst_id WHERE e.id IN ({placeholders})",ids).fetchall()
        data=[]
        for r in rows:
            item=dict(r); item["attachments"]=[dict(a) for a in c.execute("SELECT * FROM attachments WHERE email_id=?",(r["id"],)).fetchall()]; data.append(item)
        c.close(); root,manifest=export(data,directory,fmt,request.form.get("reference","")); flash(f"Exported {len(manifest)} message(s) to {root}.","success"); return redirect(request.referrer or url_for("index"))
    return app
