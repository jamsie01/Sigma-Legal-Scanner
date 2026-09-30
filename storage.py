"""Append-only observations and durable identities; no automatic removal inference."""
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path


SCHEMA = '''
CREATE TABLE IF NOT EXISTS decisions (
 firm TEXT NOT NULL, job_id TEXT NOT NULL, reason TEXT NOT NULL, decided_at TEXT NOT NULL,
 PRIMARY KEY (firm, job_id)
);
CREATE TABLE IF NOT EXISTS scan_metadata (
 scan_id INTEGER PRIMARY KEY REFERENCES scans(id), source TEXT NOT NULL, baseline INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY, firm TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL, status TEXT NOT NULL,
    coverage_json TEXT NOT NULL, errors_json TEXT NOT NULL,
    review_json TEXT NOT NULL, excluded_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vacancies (
    firm TEXT NOT NULL, job_id TEXT NOT NULL, reference TEXT NOT NULL,
    title TEXT NOT NULL, location TEXT NOT NULL, url TEXT NOT NULL,
    practice_area TEXT, practice_area_source TEXT, pqe TEXT,
    checked_at TEXT NOT NULL, london INTEGER NOT NULL, category TEXT NOT NULL,
    qualification_evidence TEXT NOT NULL,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    first_scan_id INTEGER NOT NULL REFERENCES scans(id),
    last_scan_id INTEGER NOT NULL REFERENCES scans(id),
    PRIMARY KEY (firm, job_id)
);
CREATE TABLE IF NOT EXISTS observations (
    scan_id INTEGER NOT NULL REFERENCES scans(id), firm TEXT NOT NULL,
    job_id TEXT NOT NULL, is_new INTEGER NOT NULL, payload_json TEXT NOT NULL,
    PRIMARY KEY (scan_id, firm, job_id),
    FOREIGN KEY (firm, job_id) REFERENCES vacancies(firm, job_id)
);
'''


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys = ON')
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def save(self, result):
        """Transaction serializes NEW checks even if two scans finish together."""
        try:
            self.db.execute('BEGIN IMMEDIATE')
            baseline = self.db.execute('SELECT 1 FROM vacancies WHERE firm=? LIMIT 1', (result.firm,)).fetchone() is None
            previous_scan = self.db.execute('SELECT id, status FROM scans WHERE firm=? ORDER BY id DESC LIMIT 1', (result.firm,)).fetchone()
            cursor = self.db.execute(
                'INSERT INTO scans (firm,started_at,finished_at,status,coverage_json,errors_json,review_json,excluded_json) VALUES (?,?,?,?,?,?,?,?)',
                (result.firm, result.started_at, result.finished_at, result.status,
                 json.dumps(result.coverage), json.dumps(result.errors),
                 json.dumps(result.review), json.dumps(result.excluded)))
            scan_id = cursor.lastrowid
            self.db.execute('INSERT INTO scan_metadata VALUES (?,?,?)', (scan_id, result.source, baseline))
            records = []
            for vacancy in result.vacancies:
                record = asdict(vacancy)
                previous = self.db.execute('SELECT * FROM vacancies WHERE firm=? AND job_id=?',
                                           (vacancy.firm, vacancy.job_id)).fetchone()
                is_new = previous is None
                changed_fields = [key for key in ('title', 'location', 'url', 'practice_area', 'pqe')
                                  if previous is not None and previous[key] != record[key]]
                change = ('BASELINE' if baseline else 'NEW') if is_new else (
                    'UPDATED' if changed_fields else
                    'RETURNED' if previous_scan and previous_scan['status'] == 'SUCCESS' and previous['last_scan_id'] != previous_scan['id'] else 'SEEN')
                report_record = {**record, 'is_new': is_new and not baseline, 'change': change,
                                 'changed_fields': changed_fields, 'baseline': baseline,
                                 'first_seen': vacancy.checked_at if is_new else previous['first_seen'],
                                 'last_seen': vacancy.checked_at}
                fields = list(record)
                values = list(record.values())
                assignments = ','.join(f'{key}=excluded.{key}' for key in fields if key not in ('firm', 'job_id'))
                self.db.execute(
                    f"INSERT INTO vacancies ({','.join(fields)},first_seen,last_seen,first_scan_id,last_scan_id) "
                    f"VALUES ({','.join('?' for _ in range(len(fields)+4))}) "
                    f"ON CONFLICT(firm,job_id) DO UPDATE SET {assignments},last_seen=excluded.last_seen,last_scan_id=excluded.last_scan_id",
                    values + [vacancy.checked_at, vacancy.checked_at, scan_id, scan_id])
                self.db.execute('INSERT INTO observations VALUES (?,?,?,?,?)',
                                (scan_id, vacancy.firm, vacancy.job_id, is_new, json.dumps(report_record)))
                records.append({**report_record, 'is_new': is_new})
            self.db.commit()
            return scan_id, records
        except BaseException:
            self.db.rollback()
            raise

    def history(self):
        return [dict(row) for row in self.db.execute('''
            SELECT s.id,s.firm,s.started_at,s.status,COUNT(o.job_id) AS qualified,
                   COALESCE(SUM(o.is_new),0) AS new
            FROM scans s LEFT JOIN observations o ON s.id=o.scan_id
            GROUP BY s.id ORDER BY s.id DESC LIMIT 20
        ''')]

    def all_vacancies(self):
        cursor = self.db.execute('''
            SELECT firm, job_id, reference, title, location, url,
                   practice_area, practice_area_source, pqe, checked_at,
                   london, category, first_seen, last_seen
            FROM vacancies
            ORDER BY london DESC, firm ASC, title ASC
        ''')
        return [dict(row) for row in cursor.fetchall()]


    def exclude(self, firm, job_id, reason):
        from models import utc_now
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?)',
                            (firm, job_id, reason, utc_now()))

    def restore(self, firm, job_id):
        with self.db:
            self.db.execute('DELETE FROM decisions WHERE firm=? AND job_id=?', (firm, job_id))

    def decisions(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM decisions ORDER BY firm,job_id')]

    def latest_scans(self):
        rows = self.db.execute("""
            SELECT s.*, m.source, m.baseline FROM scans s
            LEFT JOIN scan_metadata m ON m.scan_id=s.id
            WHERE s.id=(SELECT MAX(s2.id) FROM scans s2 WHERE s2.firm=s.firm)
            ORDER BY s.firm
        """)
        results = []
        for row in rows:
            scan = dict(row)
            for key in ('coverage', 'errors', 'review', 'excluded'):
                scan[key] = json.loads(scan.pop(key + '_json'))
            scan['vacancies'] = []
            for obs in self.db.execute('SELECT payload_json,is_new FROM observations WHERE scan_id=?', (scan['id'],)):
                record = json.loads(obs['payload_json'])
                record.setdefault('change', 'LEGACY')
                record.setdefault('is_new', False)
                record.setdefault('first_seen', '')
                scan['vacancies'].append(record)
            results.append(scan)
        return results
