from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.bootstrap import build_agent

app = FastAPI(title="Kubernetes Troubleshooting Agent", version="0.1.0")


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class AskResponse(BaseModel):
    answer: str


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        answer = build_agent().run(request.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AskResponse(answer=answer)
