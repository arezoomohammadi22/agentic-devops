import os
from functools import lru_cache
from pathlib import Path
import yaml
@lru_cache
def config():
    p=Path(os.getenv("CONFIG_PATH","/config/config.yaml"))
    if not p.exists(): p=Path(__file__).resolve().parents[1]/"config.yaml"
    return yaml.safe_load(p.read_text())
def opa_url(): return os.getenv("OPA_URL","http://opa:8181").rstrip("/")
def db_path(): return os.getenv("DB_PATH","/data/lab.db")
def executor_mode(): return os.getenv("EXECUTOR_MODE",config().get("executor",{}).get("mode","mock"))
