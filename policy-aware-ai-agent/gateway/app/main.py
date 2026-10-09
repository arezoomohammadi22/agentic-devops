import html
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse,JSONResponse,RedirectResponse
from . import store
from .executor import get_executor
from .models import ProposedAction,ExecuteApprovedRequest
from .opa_client import evaluate
from .security import action_hash
from .settings import config

app=FastAPI(title="Secure Agent Execution Gateway",version="1.0.0")
@app.on_event("startup")
def startup(): store.init_db()
def trusted_identity():
    i=config()["identity"]
    return {"agent_id":i["agent_id"],"roles":list(i.get("roles",[])),"capabilities":list(i.get("capabilities",[]))}
def policy_input(action,approval_valid=False,approval_hash=None):
    cfg=config(); ident=trusted_identity()
    lc=cfg.get("rate_limits",{}).get(action.tool,{"max_calls":999999,"window_seconds":600})
    recent=store.count_recent_executions(ident["agent_id"],action.tool,int(lc.get("window_seconds",600)))
    h=action_hash(action)
    return {"identity":ident,"action":action.model_dump(),
            "context":{"action_hash":h,"calls_last_window":recent,
                       "max_calls":int(lc.get("max_calls",999999)),
                       "window_seconds":int(lc.get("window_seconds",600))},
            "approval":{"valid":approval_valid,"action_hash":approval_hash or ""}}
def execute_and_record(action,h,approval_id,decision_id,effect,reason):
    ident=trusted_identity()
    try: result=get_executor().execute(action)
    except Exception as e:
        store.audit("execution_failed",agent_id=ident["agent_id"],action=action.model_dump(),
                    action_hash_value=h,opa_decision_id=decision_id,policy_effect=effect,
                    policy_reason=reason,approval_id=approval_id,result="error",details={"error":str(e)})
        return JSONResponse(status_code=500,content={"status":"execution_failed","error":str(e)})
    store.record_execution(ident["agent_id"],h,action.model_dump())
    if approval_id: store.mark_executed(approval_id)
    store.audit("executed",agent_id=ident["agent_id"],action=action.model_dump(),action_hash_value=h,
                opa_decision_id=decision_id,policy_effect=effect,policy_reason=reason,
                approval_id=approval_id,result="success",details={"executor_result":result})
    return {"status":"executed","policy":{"effect":effect,"reason":reason,"opa_decision_id":decision_id},
            "execution":result}

@app.get("/health")
def health(): return {"status":"ok"}

@app.post("/v1/actions/propose")
def propose(action:ProposedAction):
    ident=trusted_identity(); h=action_hash(action)
    try: decision,did=evaluate(policy_input(action))
    except Exception as e:
        store.audit("policy_error",agent_id=ident["agent_id"],action=action.model_dump(),
                    action_hash_value=h,result="denied",details={"error":str(e)})
        return JSONResponse(status_code=503,content={"status":"denied","reason":"policy engine unavailable; fail closed"})
    store.audit("policy_decision",agent_id=ident["agent_id"],action=action.model_dump(),action_hash_value=h,
                opa_decision_id=did,policy_effect=decision.effect,policy_reason=decision.reason,result=decision.effect)
    if decision.effect=="deny":
        return JSONResponse(status_code=403,content={"status":"denied",
            "policy":{"effect":decision.effect,"reason":decision.reason,"opa_decision_id":did}})
    if decision.effect=="require_approval":
        approval=store.create_approval(h,action.model_dump(),int(config().get("approval",{}).get("ttl_seconds",120)))
        store.audit("approval_requested",agent_id=ident["agent_id"],action=action.model_dump(),
                    action_hash_value=h,opa_decision_id=did,policy_effect=decision.effect,
                    policy_reason=decision.reason,approval_id=approval["approval_id"],result="pending")
        return JSONResponse(status_code=202,content={"status":"require_approval",
            "policy":{"effect":decision.effect,"reason":decision.reason,"opa_decision_id":did},"approval":approval})
    return execute_and_record(action,h,None,did,decision.effect,decision.reason)

@app.post("/v1/approvals/{approval_id}/approve")
def approve(approval_id:str):
    a=store.approve(approval_id)
    if not a: raise HTTPException(404,"approval not found")
    if a["status"]=="expired": raise HTTPException(410,"approval expired")
    store.audit("approval_changed",approval_id=approval_id,action=a["action"],
                action_hash_value=a["action_hash"],result=a["status"])
    return a

@app.get("/v1/approvals/{approval_id}")
def approval_status(approval_id:str):
    a=store.get_approval(approval_id)
    if not a: raise HTTPException(404,"approval not found")
    return a
@app.get("/v1/approvals")
def approvals(): return store.list_approvals()

@app.post("/v1/actions/execute-approved")
def execute_approved(req:ExecuteApprovedRequest):
    a=store.get_approval(req.approval_id)
    if not a: raise HTTPException(404,"approval not found")
    if a["status"]=="expired": raise HTTPException(410,"approval expired")
    if a["status"]!="approved": raise HTTPException(409,f"approval is {a['status']}, not approved")
    h=action_hash(req.action)
    if h!=a["action_hash"]:
        store.audit("approval_hash_mismatch",action=req.action.model_dump(),action_hash_value=h,
                    approval_id=req.approval_id,result="denied",
                    details={"approved_hash":a["action_hash"],"submitted_hash":h})
        raise HTTPException(409,"action changed after approval; approval is bound to the original action hash")
    decision,did=evaluate(policy_input(req.action,True,a["action_hash"]))
    if decision.effect!="allow":
        return JSONResponse(status_code=403,content={"status":"denied",
            "policy":{"effect":decision.effect,"reason":decision.reason,"opa_decision_id":did}})
    return execute_and_record(req.action,h,req.approval_id,did,decision.effect,decision.reason)

@app.get("/v1/audit")
def audit(limit:int=100): return store.recent_audit(max(1,min(limit,500)))

@app.get("/approvals/ui",response_class=HTMLResponse)
def ui():
    rows=[]
    for a in store.list_approvals():
        ac=a["action"]; button=""
        if a["status"]=="pending":
            button=f'<form method="post" action="/approvals/{html.escape(a["approval_id"])}/approve-form"><button>Approve</button></form>'
        rows.append(f"<tr><td>{html.escape(a['approval_id'])}</td><td>{html.escape(a['status'])}</td>"
                    f"<td>{html.escape(ac['tool'])}</td><td>{html.escape(ac['namespace'])}</td>"
                    f"<td>{html.escape(ac['resource'])}</td><td><code>{html.escape(a['action_hash'][:16])}...</code></td><td>{button}</td></tr>")
    return f"""<!doctype html><html><head><meta http-equiv="refresh" content="3"><title>Approval Gate</title>
    <style>body{{font-family:system-ui;max-width:1200px;margin:40px auto;background:#071827;color:#eef7ff}}
    table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #244055;padding:12px;text-align:left}}
    button{{padding:8px 14px;font-weight:700}}code{{color:#74e6ff}}</style></head><body>
    <h1>Human Approval Gate</h1><p>Approvals are bound to the exact action hash and expire automatically.</p>
    <table><thead><tr><th>ID</th><th>Status</th><th>Tool</th><th>Namespace</th><th>Resource</th><th>Hash</th><th>Action</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table></body></html>"""

@app.post("/approvals/{approval_id}/approve-form")
def approve_form(approval_id:str):
    a=store.approve(approval_id)
    if not a: raise HTTPException(404,"approval not found")
    return RedirectResponse("/approvals/ui",status_code=303)
