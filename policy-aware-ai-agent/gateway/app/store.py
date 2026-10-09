import json, sqlite3, threading, uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .settings import db_path

_LOCK=threading.Lock()
def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.isoformat()
def connect():
    p=Path(db_path()); p.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(p); c.row_factory=sqlite3.Row; return c
def init_db():
    with _LOCK,connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS approvals(
          approval_id TEXT PRIMARY KEY, action_hash TEXT NOT NULL, action_json TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          approved_at TEXT, executed_at TEXT);
        CREATE TABLE IF NOT EXISTS action_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL, tool TEXT NOT NULL,
          namespace TEXT NOT NULL, action_hash TEXT NOT NULL, executed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
          agent_id TEXT, tool TEXT, namespace TEXT, action_hash TEXT, opa_decision_id TEXT,
          policy_effect TEXT, policy_reason TEXT, approval_id TEXT, result TEXT, details_json TEXT);
        """)
def _norm(row):
    if row is None: return None
    r=dict(row)
    if r["status"] in {"pending","approved"} and datetime.fromisoformat(r["expires_at"])<=now():
        with _LOCK,connect() as db:
            db.execute("UPDATE approvals SET status='expired' WHERE approval_id=?",(r["approval_id"],))
        r["status"]="expired"
    r["action"]=json.loads(r.pop("action_json"))
    return r
def create_approval(h,action,ttl):
    aid="apr-"+uuid.uuid4().hex[:12]; created=now(); exp=created+timedelta(seconds=ttl)
    with _LOCK,connect() as db:
        db.execute("""INSERT INTO approvals(approval_id,action_hash,action_json,status,created_at,expires_at)
                      VALUES(?,?,?,'pending',?,?)""",
                   (aid,h,json.dumps(action,sort_keys=True),iso(created),iso(exp)))
    return get_approval(aid)
def get_approval(aid):
    with connect() as db: row=db.execute("SELECT * FROM approvals WHERE approval_id=?",(aid,)).fetchone()
    return _norm(row)
def list_approvals():
    with connect() as db: rows=db.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    return [_norm(x) for x in rows]
def approve(aid):
    a=get_approval(aid)
    if not a or a["status"]!="pending": return a
    with _LOCK,connect() as db:
        db.execute("UPDATE approvals SET status='approved',approved_at=? WHERE approval_id=? AND status='pending'",
                   (iso(now()),aid))
    return get_approval(aid)
def mark_executed(aid):
    with _LOCK,connect() as db:
        db.execute("UPDATE approvals SET status='executed',executed_at=? WHERE approval_id=?",(iso(now()),aid))
def count_recent_executions(agent_id,tool,window_seconds):
    cutoff=now()-timedelta(seconds=window_seconds)
    with connect() as db:
        row=db.execute("""SELECT COUNT(*) c FROM action_events
                          WHERE agent_id=? AND tool=? AND executed_at>=?""",
                       (agent_id,tool,iso(cutoff))).fetchone()
    return int(row["c"])
def record_execution(agent_id,h,action):
    with _LOCK,connect() as db:
        db.execute("""INSERT INTO action_events(agent_id,tool,namespace,action_hash,executed_at)
                      VALUES(?,?,?,?,?)""",
                   (agent_id,action["tool"],action["namespace"],h,iso(now())))
def audit(event_type,agent_id=None,action=None,action_hash_value=None,opa_decision_id=None,
          policy_effect=None,policy_reason=None,approval_id=None,result=None,details=None):
    with _LOCK,connect() as db:
        db.execute("""INSERT INTO audit_log(timestamp,event_type,agent_id,tool,namespace,action_hash,
                      opa_decision_id,policy_effect,policy_reason,approval_id,result,details_json)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (iso(now()),event_type,agent_id,action.get("tool") if action else None,
                    action.get("namespace") if action else None,action_hash_value,opa_decision_id,
                    policy_effect,policy_reason,approval_id,result,json.dumps(details or {},sort_keys=True)))
def recent_audit(limit=100):
    with connect() as db: rows=db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in rows]
