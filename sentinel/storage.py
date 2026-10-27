"""SQLite audit storage. Each operation commits before returning."""
import json
import sqlite3
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started_at TEXT,ended_at TEXT,task TEXT,status TEXT,rules_version TEXT);
        CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY,run_id TEXT REFERENCES runs(id),ts TEXT,tool TEXT,args_json TEXT,status TEXT,duration_ms REAL,result_json TEXT,agent_note TEXT);
        CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY,action_id INTEGER REFERENCES actions(id),verdict TEXT,rule_id TEXT,reason TEXT,decided_by TEXT,decided_at TEXT,rules_version TEXT);
        CREATE TABLE IF NOT EXISTS counters(run_id TEXT REFERENCES runs(id),name TEXT,value INTEGER,PRIMARY KEY(run_id,name));
        CREATE TABLE IF NOT EXISTS rules(version_hash TEXT PRIMARY KEY,rules_json TEXT,english_source TEXT,activated_at TEXT);
        CREATE TABLE IF NOT EXISTS compile_log(id INTEGER PRIMARY KEY,english TEXT,model TEXT,draft_json TEXT,tests_json TEXT,accepted INTEGER DEFAULT 0);
        ''')
        # A restart never resumes a pending action or silently reruns a tool.
        self.db.execute("UPDATE actions SET status='interrupted' WHERE status IN ('waiting_for_human','executing','checking')")
        self.db.execute("UPDATE runs SET status='interrupted', ended_at=? WHERE status='running'",(now(),))
        self.db.commit()
    def write(self,sql,args=()):
        cur=self.db.execute(sql,args); self.db.commit(); return cur.lastrowid
    def rows(self,sql,args=()): return [dict(r) for r in self.db.execute(sql,args).fetchall()]
    def one(self,sql,args=()):
        rows=self.rows(sql,args); return rows[0] if rows else None
    def counters(self,run): return {r['name']:r['value'] for r in self.rows('SELECT name,value FROM counters WHERE run_id=?',(run,))}
    def success(self,action,result,elapsed):
        with self.db:
            self.db.execute("UPDATE actions SET status='executed',result_json=?,duration_ms=? WHERE id=?",(json.dumps(result),elapsed,action['id']))
            tool=action['tool']; args=json.loads(action['args_json'])
            updates={'executed':1}
            if tool=='delete_file': updates['deleted']=1
            if tool=='spend_money': updates['spent']=args['amount_inr']
            for name,amount in updates.items():
                self.db.execute('INSERT INTO counters VALUES(?,?,?) ON CONFLICT(run_id,name) DO UPDATE SET value=value+excluded.value',(action['run_id'],name,amount))
