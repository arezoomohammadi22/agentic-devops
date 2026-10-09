import httpx
from .models import OpaDecision
from .settings import opa_url
def evaluate(policy_input):
    with httpx.Client(timeout=3.0) as c:
        r=c.post(opa_url()+"/v1/data/agent/authz/decision",
                 params={"decision_id":"true"},json={"input":policy_input})
        r.raise_for_status(); body=r.json()
    if "result" not in body: raise RuntimeError("OPA returned an undefined decision")
    return OpaDecision.model_validate(body["result"]),body.get("decision_id")
