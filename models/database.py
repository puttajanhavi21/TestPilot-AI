"""Small SQLite repository; immutable suite revisions keep old runs reproducible."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise RuntimeError('Database schema is newer than this application.')
            if version == 0:
                db.executescript('''
                    CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE suites(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), data TEXT NOT NULL, source TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
                    CREATE TABLE cases(suite_id INTEGER NOT NULL REFERENCES suites(id), case_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(suite_id, case_id));
                    CREATE TABLE runs(id INTEGER PRIMARY KEY, suite_id INTEGER NOT NULL REFERENCES suites(id), target TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL, analysis TEXT, created_at TEXT NOT NULL);
                    CREATE TABLE reports(id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id), suite_id INTEGER REFERENCES suites(id), format TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE INDEX runs_suite ON runs(suite_id);
                    PRAGMA user_version=1;
                ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_suite(self, suite, config, source='adaption', project_id=None, reviewed=False):
        with self.connect() as db:
            stamp = now()
            if project_id is None:
                project_id = db.execute('INSERT INTO projects(name,config,created_at) VALUES(?,?,?)', (suite['api_name'], json.dumps(config), stamp)).lastrowid
            sid = db.execute('INSERT INTO suites(project_id,data,source,reviewed,created_at) VALUES(?,?,?,?,?)', (project_id, json.dumps(suite), source, int(reviewed), stamp)).lastrowid
            db.executemany('INSERT INTO cases VALUES(?,?,?)', [(sid, c['id'], json.dumps(c)) for c in suite['test_cases']])
            return sid

    def suite(self, sid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM suites WHERE id=?', (sid,)).fetchone()
            if row is None:
                raise KeyError('Suite not found.')
            result = dict(row)
            result['data'] = json.loads(result['data'])
            return result

    def suites(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT s.id,s.project_id,p.name,s.source,s.reviewed,s.created_at,(SELECT count(*) FROM cases c WHERE c.suite_id=s.id) AS case_count FROM suites s JOIN projects p ON p.id=s.project_id ORDER BY s.id DESC LIMIT 100')]

    def start_run(self, sid, target):
        with self.connect() as db:
            return db.execute('INSERT INTO runs(suite_id,target,state,data,created_at) VALUES(?,?,?,?,?)', (sid, target, 'running', '{}', now())).lastrowid

    def finish_run(self, rid, data):
        with self.connect() as db:
            db.execute('UPDATE runs SET state=?,data=? WHERE id=?', ('completed', json.dumps(data), rid))

    def run(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT r.*,s.data AS suite FROM runs r JOIN suites s ON s.id=r.suite_id WHERE r.id=?', (rid,)).fetchone()
            if row is None:
                raise KeyError('Run not found.')
            result = dict(row)
            for field in ('data', 'suite', 'analysis'):
                result[field] = json.loads(result[field]) if result[field] else None
            return result

    def runs(self):
        with self.connect() as db:
            rows = db.execute('SELECT r.id,r.suite_id,r.target,r.state,r.created_at,r.data,p.name FROM runs r JOIN suites s ON s.id=r.suite_id JOIN projects p ON p.id=s.project_id ORDER BY r.id DESC LIMIT 100').fetchall()
            return [{**dict(r), 'data': json.loads(r['data'])} for r in rows]

    def save_analysis(self, rid, analysis):
        with self.connect() as db:
            db.execute('UPDATE runs SET analysis=? WHERE id=?', (json.dumps(analysis), rid))

    def report(self, fmt, rid=None, sid=None):
        with self.connect() as db:
            db.execute('INSERT INTO reports(run_id,suite_id,format,created_at) VALUES(?,?,?,?)', (rid, sid, fmt, now()))

    def dashboard(self):
        with self.connect() as db:
            totals = {name: db.execute('SELECT count(*) FROM ' + table).fetchone()[0] for name, table in [('projects', 'projects'), ('suites', 'suites'), ('cases', 'cases'), ('runs', 'runs'), ('reports', 'reports')]}
            totals['generated_cases'] = db.execute("SELECT count(*) FROM cases c JOIN suites s ON s.id=c.suite_id WHERE s.source='adaption'").fetchone()[0]
            for status in ('passed', 'failed', 'skipped', 'error'):
                totals[status] = db.execute("SELECT coalesce(sum(json_extract(data, ?)),0) FROM runs", ('$.summary.' + status,)).fetchone()[0]
            trends = [dict(r) for r in db.execute("SELECT substr(created_at,1,10) AS day, count(*) AS runs, coalesce(sum(json_extract(data,'$.summary.passed')),0) AS passed, coalesce(sum(json_extract(data,'$.summary.failed')),0) AS failed FROM runs WHERE state='completed' GROUP BY day ORDER BY day DESC LIMIT 14")]
        return {'totals': totals, 'trends': list(reversed(trends)), 'recent': self.runs()[:6], 'suites': self.suites()[:6]}
