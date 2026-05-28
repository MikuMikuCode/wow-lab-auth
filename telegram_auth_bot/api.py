from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from telegram_auth_bot.database import (
    create_session,
    get_session,
    init_db,
    revoke_token,
    verify_token,
)


app = FastAPI(title="WOW Preview Engine Auth")


class SessionRequest(BaseModel):
    device_id: str


class VerifyRequest(BaseModel):
    access_token: str
    device_id: str


@app.on_event("startup")
def startup():
    init_db()


@app.post("/api/auth/session")
def start_session(request: SessionRequest):
    return {
        "ok": True,
        "session_id": create_session(request.device_id),
    }


@app.get("/api/auth/session/{session_id}")
def read_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    payload = {
        "ok": True,
        "status": session["status"],
    }
    if session["status"] == "approved":
        payload["access_token"] = session["access_token"]
        user = verify_token(session["access_token"], session["device_id"])
        payload["user"] = user

    return payload


@app.post("/api/auth/verify")
def verify(request: VerifyRequest):
    user = verify_token(request.access_token, request.device_id)
    if not user:
        return {"ok": False, "error": "Access denied"}

    return {"ok": True, "user": user}


@app.post("/api/auth/revoke")
def revoke(request: VerifyRequest):
    revoke_token(request.access_token, request.device_id)
    return {"ok": True}
