import os
import tarfile
import sqlite3
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "backup_secret"

DB = "backup.db"

# Simple in-process scheduler: {job_id: (interval_seconds, thread)}
_scheduled = {}

def _schedule_loop(job_id, interval):
    while job_id in _scheduled:
        time.sleep(interval)
        if job_id in _scheduled:
            run_backup(job_id)

# ─── DB SETUP ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name    TEXT NOT NULL,
                source_path TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                schedule    TEXT DEFAULT 'manual',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id     INTEGER,
                job_name   TEXT,
                status     TEXT,
                filename   TEXT,
                size_kb    REAL,
                message    TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );
        """)

init_db()

# ─── BACKUP LOGIC ────────────────────────────────────────────────────────────

def run_backup(job_id):
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        return False, "Job not found"

    src = job["source_path"]
    dst = job["backup_path"]

    if not os.path.exists(src):
        db.execute("INSERT INTO logs (job_id,job_name,status,message) VALUES (?,?,?,?)",
                   (job_id, job["job_name"], "FAILED", f"Source path does not exist: {src}"))
        db.commit()
        return False, f"Source path not found: {src}"

    os.makedirs(dst, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{job['job_name'].replace(' ','_')}_{ts}.tar.gz"
    fpath = os.path.join(dst, fname)

    try:
        with tarfile.open(fpath, "w:gz") as tar:
            tar.add(src, arcname=os.path.basename(src))
        size_kb = round(os.path.getsize(fpath) / 1024, 2)
        db.execute("INSERT INTO logs (job_id,job_name,status,filename,size_kb,message) VALUES (?,?,?,?,?,?)",
                   (job_id, job["job_name"], "SUCCESS", fname, size_kb, f"Backup saved to {fpath}"))
        db.commit()
        return True, fname
    except Exception as e:
        db.execute("INSERT INTO logs (job_id,job_name,status,message) VALUES (?,?,?,?)",
                   (job_id, job["job_name"], "FAILED", str(e)))
        db.commit()
        return False, str(e)

# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    db = get_db()
    jobs = db.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    logs = db.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 30").fetchall()
    return render_template("dashboard.html", jobs=jobs, logs=logs)

@app.route("/job/new", methods=["GET", "POST"])
def new_job():
    if request.method == "POST":
        name = request.form["job_name"].strip()
        src  = request.form["source_path"].strip()
        dst  = request.form["backup_path"].strip()
        sched = request.form.get("schedule", "manual")

        if not name or not src or not dst:
            flash("All fields are required.", "danger")
            return redirect(url_for("new_job"))

        db = get_db()
        db.execute("INSERT INTO jobs (job_name,source_path,backup_path,schedule) VALUES (?,?,?,?)",
                   (name, src, dst, sched))
        db.commit()

        # Register scheduled job if needed
        if sched != "manual":
            register_schedule(db.execute("SELECT last_insert_rowid()").fetchone()[0], sched)

        flash(f'Job "{name}" created!', "success")
        return redirect(url_for("dashboard"))
    return render_template("new_job.html")

@app.route("/job/<int:job_id>/run", methods=["POST"])
def run_job(job_id):
    ok, msg = run_backup(job_id)
    if ok:
        flash(f"Backup successful: {msg}", "success")
    else:
        flash(f"Backup failed: {msg}", "danger")
    return redirect(url_for("dashboard"))

@app.route("/job/<int:job_id>/delete", methods=["POST"])
def delete_job(job_id):
    db = get_db()
    db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    db.execute("DELETE FROM logs WHERE job_id=?", (job_id,))
    db.commit()
    _scheduled.pop(job_id, None)
    flash("Job deleted.", "info")
    return redirect(url_for("dashboard"))

@app.route("/restore", methods=["GET", "POST"])
def restore():
    db = get_db()
    # Get all successful backups
    backups = db.execute(
        "SELECT logs.*, jobs.source_path FROM logs JOIN jobs ON logs.job_id=jobs.id WHERE logs.status='SUCCESS' ORDER BY logs.id DESC"
    ).fetchall()

    if request.method == "POST":
        log_id  = request.form["log_id"]
        restore_to = request.form["restore_to"].strip()

        entry = db.execute(
            "SELECT logs.*, jobs.backup_path, jobs.source_path FROM logs JOIN jobs ON logs.job_id=jobs.id WHERE logs.id=?",
            (log_id,)
        ).fetchone()

        if not entry:
            flash("Backup record not found.", "danger")
            return redirect(url_for("restore"))

        archive = os.path.join(entry["backup_path"], entry["filename"])
        if not os.path.exists(archive):
            flash(f"Archive file not found: {archive}", "danger")
            return redirect(url_for("restore"))

        target = restore_to or entry["source_path"]
        os.makedirs(target, exist_ok=True)

        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(path=target)
            flash(f"Restored to: {target}", "success")
        except Exception as e:
            flash(f"Restore failed: {e}", "danger")

        return redirect(url_for("restore"))

    return render_template("restore.html", backups=backups)

@app.route("/logs")
def all_logs():
    db = get_db()
    logs = db.execute("SELECT * FROM logs ORDER BY id DESC").fetchall()
    return render_template("logs.html", logs=logs)

# ─── SCHEDULER HELPER ────────────────────────────────────────────────────────

def register_schedule(job_id, sched):
    intervals = {"hourly": 3600, "daily": 86400}
    seconds = intervals.get(sched, 0)
    if seconds and job_id not in _scheduled:
        _scheduled[job_id] = True
        t = threading.Thread(target=_schedule_loop, args=(job_id, seconds), daemon=True)
        t.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
