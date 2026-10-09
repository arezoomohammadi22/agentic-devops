import hashlib,json
from .models import ProposedAction
def canonical_action(a:ProposedAction)->str:
    return json.dumps(a.model_dump(),sort_keys=True,separators=(",",":"))
def action_hash(a:ProposedAction)->str:
    return hashlib.sha256(canonical_action(a).encode()).hexdigest()
