from datetime import datetime,timezone
from .settings import config,executor_mode

class MockExecutor:
    def execute(self,a):
        if a.tool=="get_logs":
            return {"mode":"mock","tool":a.tool,"namespace":a.namespace,"resource":a.resource,
                    "logs":["GET /health 200","upstream timeout","readiness probe failed"]}
        if a.tool=="restart_deployment":
            return {"mode":"mock","tool":a.tool,"namespace":a.namespace,"resource":a.resource,
                    "patched_annotation":"secure-agent-lab/restartedAt","status":"simulated-success"}
        raise PermissionError(f"No executor exists for tool '{a.tool}'")

class KubernetesExecutor:
    def __init__(self):
        from kubernetes import client,config as kc
        try: kc.load_incluster_config()
        except Exception: kc.load_kube_config()
        self.core=client.CoreV1Api(); self.apps=client.AppsV1Api()
    def execute(self,a):
        if a.tool=="get_logs":
            pods=self.core.list_namespaced_pod(a.namespace,label_selector=f"app={a.resource}").items
            if not pods: raise RuntimeError(f"No pod found for app={a.resource}")
            pod=pods[0].metadata.name
            tail=int(config().get("executor",{}).get("log_tail_lines",50))
            logs=self.core.read_namespaced_pod_log(pod,a.namespace,tail_lines=tail)
            return {"mode":"kubernetes","tool":a.tool,"namespace":a.namespace,
                    "deployment":a.resource,"pod":pod,"logs":logs.splitlines()}
        if a.tool=="restart_deployment":
            ts=datetime.now(timezone.utc).isoformat()
            body={"spec":{"template":{"metadata":{"annotations":{"secure-agent-lab/restartedAt":ts}}}}}
            r=self.apps.patch_namespaced_deployment(a.resource,a.namespace,body)
            return {"mode":"kubernetes","tool":a.tool,"namespace":a.namespace,
                    "resource":a.resource,"generation":r.metadata.generation,"patched_annotation":ts}
        raise PermissionError(f"No executor exists for tool '{a.tool}'")
def get_executor(): return KubernetesExecutor() if executor_mode()=="kubernetes" else MockExecutor()
