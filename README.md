# BackupBot — Backup & Restore Automation System

## Folder Structure

```
backup_system/
├── app.py               # Flask backend (all routes + logic)
├── backup.db            # SQLite database (auto-created on first run)
├── requirements.txt
├── sources/             # Put files here to test backups
├── backups/             # Archives land here by default
└── templates/
    ├── base.html        # Layout + sidebar + styles
    ├── dashboard.html   # Job list + recent logs
    ├── new_job.html     # Create job form
    ├── restore.html     # Restore picker
    └── logs.html        # Full log history
```

## Database Schema

```sql
CREATE TABLE jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    source_path TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    schedule    TEXT DEFAULT 'manual',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER,
    job_name   TEXT,
    status     TEXT,          -- 'SUCCESS' or 'FAILED'
    filename   TEXT,          -- e.g. myjob_20240501_142300.tar.gz
    size_kb    REAL,
    message    TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

## Setup & Run

```bash
# 1. Clone / navigate to project
cd backup_system

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python app.py

# 5. Open browser
# http://localhost:5000
```

## Quick Demo (30 seconds)

```bash
# Put some test files in sources/
echo "hello world" > sources/test.txt
mkdir sources/myproject
echo "main code" > sources/myproject/main.py

# Then in the browser:
# 1. New Job → name: "test", source: ./sources, dest: ./backups
# 2. Dashboard → click ▶ Run
# 3. Restore → select the archive → restore
```

## Features

| Feature            | Implementation                        |
|--------------------|---------------------------------------|
| Create backup job  | `/job/new` form → SQLite `jobs` table |
| Run manually       | `▶ Run` button → POST `/job/<id>/run` |
| Compress files     | `tarfile` module → `.tar.gz` archives |
| Backup history     | SQLite `logs` table                   |
| Restore backup     | `tarfile.extractall()` to target path |
| Auto-schedule      | APScheduler (hourly / daily)          |
| Dashboard          | Job list + last 30 log entries        |
