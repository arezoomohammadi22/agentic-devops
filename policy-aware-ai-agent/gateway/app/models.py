from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

class ProposedAction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tool: Literal["get_logs","restart_deployment","delete_namespace"]
    namespace: Literal["agent-lab-staging","agent-lab-production"]
    resource_kind: Literal["deployment","namespace"]
    resource: str=Field(min_length=1,max_length=63,pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
    reason: str=Field(min_length=1,max_length=200)

    @model_validator(mode="after")
    def semantics(self):
        if self.tool in {"get_logs","restart_deployment"} and self.resource_kind!="deployment":
            raise ValueError(f"{self.tool} requires resource_kind=deployment")
        if self.tool=="delete_namespace":
            if self.resource_kind!="namespace": raise ValueError("delete_namespace requires resource_kind=namespace")
            if self.resource!=self.namespace: raise ValueError("resource must equal namespace for delete_namespace")
        return self

class ExecuteApprovedRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    approval_id: str=Field(min_length=1,max_length=100)
    action: ProposedAction

class OpaDecision(BaseModel):
    effect: Literal["allow","deny","require_approval"]
    reason: str
