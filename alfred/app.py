"""
Alfred routing layer — entry point.

Start with: uvicorn alfred.app:app --reload --port 3000
Or from repo root: python -m uvicorn alfred.app:app --reload --port 3000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
from dotenv import load_dotenv

from alfred.router import route_query
from alfred.dispatch import dispatch

load_dotenv()

app = FastAPI(title="Alfred — KLG Routing Layer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str
    skill: Optional[str] = None  # override auto-classification; e.g. "klg-response-plan"
    matter: Optional[str] = None  # matter name for Notion context injection
    braid: Optional[bool] = False  # fire parallel Claude + ChatGPT calls


class QueryResponse(BaseModel):
    response: str
    skill_used: str
    model: str
    braided_response: Optional[str] = None  # ChatGPT panel if braid=True
    routing_log: dict


@app.get("/health")
def health():
    return {"status": "ok", "service": "alfred"}


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    # 1. Route: classify query, select skill
    routing = route_query(req.query, skill_override=req.skill)

    # 2. Dispatch to Claude (+ ChatGPT if braiding)
    result = await dispatch(
        query=req.query,
        skill_name=routing["skill"],
        skill_text=routing["skill_text"],
        matter=req.matter,
        braid=req.braid or False,
    )

    return QueryResponse(
        response=result["response"],
        skill_used=routing["skill"],
        model=result["model"],
        braided_response=result.get("braided_response"),
        routing_log={
            "query_type": routing["query_type"],
            "skill": routing["skill"],
            "primary_model": result["model"],
            "braid": req.braid,
        },
    )
