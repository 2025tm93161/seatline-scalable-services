import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from starlette.exceptions import HTTPException


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seatline")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Fault(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message


def error(code, message):
    return {"error": {"code": code, "message": message}}


def create_service(name, schema):
    engine = create_engine(os.environ["DATABASE_URL"], pool_size=25, max_overflow=10, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(app):
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status INTEGER NOT NULL, response TEXT NOT NULL)"))
            for statement in schema:
                connection.execute(text(statement))
        yield
        engine.dispose()

    app = FastAPI(title=f"Seatline {name}", version="1.0.0", lifespan=lifespan, responses={status: {"model": ErrorResponse} for status in (400, 404, 409, 422, 500, 503)})
    app.state.engine = engine

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        request.state.correlation_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.correlation_id
        logger.info(json.dumps({"service": name, "request_id": request.state.correlation_id, "method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": round((time.monotonic() - started) * 1000)}))
        return response

    @app.exception_handler(Fault)
    async def fault_handler(request, exception):
        return JSONResponse(error(exception.code, exception.message), status_code=exception.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exception):
        return JSONResponse(error("VALIDATION_ERROR", str(exception)), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_handler(request, exception):
        return JSONResponse(error("HTTP_ERROR", str(exception.detail)), status_code=exception.status_code)

    @app.exception_handler(Exception)
    async def unexpected_handler(request, exception):
        logger.error(json.dumps({"service": name, "request_id": getattr(request.state, "correlation_id", "unknown"), "error": type(exception).__name__}))
        return JSONResponse(error("INTERNAL_ERROR", "Unexpected service failure"), status_code=500)

    @app.get("/health")
    def health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"service": name, "status": "ok"}

    return app, engine


def idempotent(engine, request, key, payload, action):
    if not key or len(key) > 128:
        raise Fault(422, "INVALID_KEY", "Idempotency-Key must contain 1 to 128 characters")
    scoped_key = f"{request.url.path}:{key}"
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": scoped_key})
        stored = connection.execute(text("SELECT * FROM idempotency WHERE key = :key"), {"key": scoped_key}).mappings().first()
        if stored:
            if stored["fingerprint"] != fingerprint:
                raise Fault(409, "IDEMPOTENCY_CONFLICT", "Key already used with a different payload")
            logger.info(json.dumps({"event": "idempotency_replay", "request_id": request.state.correlation_id, "key": scoped_key}))
            return JSONResponse(json.loads(stored["response"]), status_code=stored["status"], headers={"Idempotency-Replayed": "true"})
        try:
            status, result = action(connection)
        except Fault as exception:
            status, result = exception.status, error(exception.code, exception.message)
        connection.execute(text("INSERT INTO idempotency VALUES (:key, :fingerprint, :status, :response)"), {"key": scoped_key, "fingerprint": fingerprint, "status": status, "response": json.dumps(result)})
    return JSONResponse(result, status_code=status)