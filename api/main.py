"""Local SQLite-backed report and faculty-decision API.

Approving a decision records faculty intent only; it never publishes question-bank edits.
"""
import hashlib
import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engine import comments, detectors, guards, prompts
from engine.llm import LLM, Unavailable
from engine.records import ROOT, build_record, load_all
from engine.run import fallback_judge, template_reply

load_dotenv()
logger = logging.getLogger("acadz_api")
DEFAULT_DB = ROOT / "data" / "acadza.sqlite3"
QUESTION_RECORDS, _BASE_REPORTS, TAXONOMY = load_all()
KNOWN_QUESTIONS = set(QUESTION_RECORDS)


class ReportCreate(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    comment: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="web", min_length=1, max_length=32)
    student_id: str | None = Field(default=None, max_length=128)


class ReviewAction(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=1000)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database_path():
    path = Path(os.environ.get("DATABASE_PATH", str(DEFAULT_DB)))
    return path if path.is_absolute() else ROOT / path


def connect(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def transaction(path):
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def connection(path):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def initialize_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                question_id TEXT NOT NULL,
                student_id TEXT,
                source TEXT NOT NULL,
                comment TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                process_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (process_status IN ('pending', 'processing', 'processed', 'failed')),
                process_error TEXT,
                UNIQUE(question_id, dedupe_key)
            );
            CREATE INDEX IF NOT EXISTS reports_created_at ON reports(created_at DESC);
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL UNIQUE REFERENCES reports(id),
                verdict TEXT NOT NULL,
                repair TEXT,
                edit_json TEXT NOT NULL,
                route TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                evidence TEXT NOT NULL,
                student_reply TEXT NOT NULL,
                checks_json TEXT NOT NULL,
                execution_mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                source TEXT NOT NULL,
                api_errors_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'awaiting_review'
                    CHECK (status IN ('awaiting_review', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit (
                id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL REFERENCES decisions(id),
                report_id TEXT NOT NULL REFERENCES reports(id),
                action TEXT NOT NULL CHECK(action IN ('approve', 'reject')),
                reviewer TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(decision_id, action)
            );
            CREATE INDEX IF NOT EXISTS audit_created_at ON audit(created_at DESC);
        """)
        conn.execute("UPDATE reports SET process_status='pending' WHERE process_status='processing'")


def _report_view(conn, row):
    result = dict(row)
    result.pop("dedupe_key", None)
    decision = conn.execute("SELECT * FROM decisions WHERE report_id=?", (row["id"],)).fetchone()
    result["decision"] = _decision_view(decision) if decision else None
    return result


def _live_mode():
    return os.environ.get("ACADZA_MODE", "replay").strip().lower()


def _process_report(report_id, db_path):
    with connection(db_path) as conn:
        report_row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if report_row is None:
        return
    report = dict(report_row)
    try:
        records, _, taxonomy = load_all()
        rec = records[report["question_id"]]
        screen = comments.screen(report["comment"])
        engine_report = {
            "reportId": report["id"], "questionId": report["question_id"],
            "studentId": report["student_id"], "source": report["source"],
            "reportedAt": report["created_at"], "comment": report["comment"],
        }
        screen_by_id = {report_id: screen}
        llm = LLM(mode=_live_mode())
        notes = []
        try:
            solve = llm.json("solver", rec.id, prompts.SOLVER_SYSTEM, prompts.solver_user(rec),
                             prompts.SOLVER_SCHEMA, effort="high")
        except Unavailable as exc:
            solve = None
            notes.append(str(exc))
        findings = detectors.run(rec)
        try:
            judge = llm.json("judge", rec.id, prompts.judge_system(taxonomy),
                             prompts.judge_user(rec, findings, solve, [engine_report], screen_by_id),
                             prompts.judge_schema(taxonomy), effort="high")
            source = "llm"
        except Unavailable as exc:
            notes.append(str(exc))
            judge, source = fallback_judge(rec, findings, [engine_report], screen_by_id), "fallback"
        decision = next((item for item in judge.get("reports", []) if item.get("reportId") == report_id), None)
        if decision is None:
            decision = fallback_judge(rec, findings, [engine_report], screen_by_id)["reports"][0]
            source = "fallback"
        route, checks, edits = guards.evaluate(
            rec, decision, solve, findings, screen, taxonomy
        )
        reply = decision.get("student_reply") or ""
        if not guards.reply_consistent(reply, route):
            payload = {"verdict": decision["verdict"], "repair": decision.get("repair"),
                       "route": route, "evidence": decision.get("evidence", "")}
            try:
                reply_result = llm.json(
                    "reply", report_id, prompts.REPLY_SYSTEM,
                    prompts.reply_user(report, payload, screen["register"]),
                    prompts.REPLY_SCHEMA, effort="low", max_tokens=2000,
                )
                reply = reply_result["student_reply"]
            except Unavailable as exc:
                notes.append(str(exc))
            if not guards.reply_consistent(reply, route):
                reply = template_reply(decision["verdict"], route, screen["register"])

        item = {
            "id": uuid.uuid4().hex,
            "report_id": report_id,
            "verdict": decision["verdict"],
            "repair": decision.get("repair") if decision["verdict"] == "defect" else None,
            "edit_json": json.dumps(edits, ensure_ascii=False),
            "route": route,
            "confidence": max(0.0, min(1.0, float(decision.get("confidence", 0)))),
            "evidence": str(decision.get("evidence") or "No evidence was returned."),
            "student_reply": reply,
            "checks_json": json.dumps(checks, ensure_ascii=False),
            "execution_mode": llm.mode,
            "provider": llm.provider if llm.mode == "live" else "replay",
            "model": llm.model if llm.mode == "live" else "Claude Opus 5.5 (recorded)",
            "source": source,
            "api_errors_json": json.dumps(llm.errors, ensure_ascii=False),
            "created_at": utc_now(),
        }
        with transaction(db_path) as conn:
            conn.execute("""
                INSERT INTO decisions
                (id, report_id, verdict, repair, edit_json, route, confidence, evidence, student_reply,
                 checks_json, execution_mode, provider, model, source, api_errors_json, created_at)
                VALUES (:id, :report_id, :verdict, :repair, :edit_json, :route, :confidence, :evidence,
                        :student_reply, :checks_json, :execution_mode, :provider, :model, :source,
                        :api_errors_json, :created_at)
            """, item)
            conn.execute("UPDATE reports SET process_status='processed', process_error=NULL WHERE id=?",
                         (report_id,))
        logger.info("report_processed report_id=%s mode=%s provider=%s source=%s notes=%s",
                    report_id, item["execution_mode"], item["provider"], source, len(notes))
    except Exception:
        logger.exception("report_processing_failed report_id=%s", report_id)
        with transaction(db_path) as conn:
            conn.execute(
                "UPDATE reports SET process_status='failed', process_error=? WHERE id=?",
                ("Processing failed. Check server logs; no decision was saved.", report_id),
            )


def _decision_view(row):
    result = dict(row)
    result["edits"] = json.loads(result.pop("edit_json"))
    result["checks"] = json.loads(result.pop("checks_json"))
    result["api_errors"] = json.loads(result.pop("api_errors_json"))
    return result


def create_app(db_path=None):
    db_path = Path(db_path or database_path())
    initialize_db(db_path)
    app = FastAPI(
        title="Acadza Report-to-Fix API",
        description="Report intake and faculty decisions. Approval records an audit event; publishing is intentionally separate.",
        version="1.0.0",
    )
    origins = [origin.strip() for origin in os.environ.get(
        "CORS_ORIGINS", "http://127.0.0.1:8765,http://localhost:8765"
    ).split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health():
        with connection(db_path) as conn:
            failures = conn.execute("SELECT COUNT(*) FROM reports WHERE process_status='failed'").fetchone()[0]
            success = conn.execute(
                "SELECT MAX(created_at) FROM decisions WHERE execution_mode='live' AND api_errors_json='[]'"
            ).fetchone()[0]
            error_rows = conn.execute(
                "SELECT api_errors_json FROM decisions WHERE api_errors_json!='[]' ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        from engine import llm
        configured = bool(os.environ.get("GROQ_API_KEY")) if llm.PROVIDER == "groq" else bool(os.environ.get("ANTHROPIC_API_KEY"))
        config_error = None if llm.PROVIDER in llm.DEFAULT_MODELS and llm.MODEL else "Provider or model configuration is invalid."
        api_errors = [error for row in error_rows for error in json.loads(row["api_errors_json"])]
        return {
            "status": "ok" if config_error is None else "configuration_error",
            "provider": llm.PROVIDER,
            "model": llm.MODEL,
            "mode": _live_mode(),
            "api_key_configured": configured,
            "last_successful_processing": success,
            "processing_errors": failures,
            "api_errors": api_errors[:10],
            "configuration_error": config_error,
        }

    @app.post("/reports", status_code=201)
    def submit_report(payload: ReportCreate):
        if payload.question_id not in KNOWN_QUESTIONS:
            raise HTTPException(status_code=422, detail="question_id is not present in the question dataset")
        comment = payload.comment.strip()
        if not comment:
            raise HTTPException(status_code=422, detail="comment cannot be blank")
        normalized = " ".join(comment.casefold().split())
        dedupe_key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        report_id = uuid.uuid4().hex
        created_at = utc_now()
        with transaction(db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM reports WHERE question_id=? AND dedupe_key=?",
                (payload.question_id, dedupe_key),
            ).fetchone()
            if existing:
                result = _report_view(conn, existing)
                result["duplicate"] = True
                return result
            conn.execute(
                """INSERT INTO reports
                (id, question_id, student_id, source, comment, dedupe_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (report_id, payload.question_id, payload.student_id, payload.source.strip(), comment,
                 dedupe_key, created_at),
            )
            saved = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            result = _report_view(conn, saved)
            result["duplicate"] = False
            return result

    @app.get("/reports")
    def list_reports(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        with connection(db_path) as conn:
            rows = conn.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                (limit, offset)).fetchall()
            return [_report_view(conn, row) for row in rows]

    @app.get("/reports/{report_id}")
    def get_report(report_id: str):
        with connection(db_path) as conn:
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="report not found")
            return _report_view(conn, row)

    @app.post("/reports/{report_id}/process", status_code=202)
    def process_report(report_id: str, background_tasks: BackgroundTasks):
        with transaction(db_path) as conn:
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="report not found")
            existing = conn.execute("SELECT id FROM decisions WHERE report_id=?", (report_id,)).fetchone()
            if existing:
                return {"report_id": report_id, "status": "processed", "decision_id": existing["id"], "duplicate": True}
            if row["process_status"] == "processing":
                return {"report_id": report_id, "status": "processing", "duplicate": True}
            conn.execute("UPDATE reports SET process_status='processing', process_error=NULL WHERE id=?",
                         (report_id,))
        background_tasks.add_task(_process_report, report_id, db_path)
        return {"report_id": report_id, "status": "processing", "duplicate": False}

    @app.get("/decisions/{report_id}")
    def get_decision(report_id: str):
        with connection(db_path) as conn:
            row = conn.execute("SELECT * FROM decisions WHERE report_id=?", (report_id,)).fetchone()
            if row is None:
                report_exists = conn.execute("SELECT 1 FROM reports WHERE id=?", (report_id,)).fetchone()
                if not report_exists:
                    raise HTTPException(status_code=404, detail="report not found")
                return {"report_id": report_id, "status": "pending"}
            return _decision_view(row)

    def review(decision_id, action, payload):
        with transaction(db_path) as conn:
            row = conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="decision not found")
            expected = "approved" if action == "approve" else "rejected"
            if row["status"] == expected:
                return {"decision_id": decision_id, "status": expected, "duplicate": True}
            if row["status"] != "awaiting_review":
                raise HTTPException(status_code=409, detail="decision has already been reviewed")
            reviewed_at = utc_now()
            audit_id = uuid.uuid4().hex
            conn.execute("UPDATE decisions SET status=?, reviewed_at=? WHERE id=?",
                         (expected, reviewed_at, decision_id))
            conn.execute(
                """INSERT INTO audit (id, decision_id, report_id, action, reviewer, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (audit_id, decision_id, row["report_id"], action, payload.reviewer.strip(),
                 payload.note, reviewed_at),
            )
        return {"decision_id": decision_id, "status": expected, "duplicate": False,
                "published": False, "audit_id": audit_id}

    @app.post("/decisions/{decision_id}/approve")
    def approve_decision(decision_id: str, payload: ReviewAction):
        return review(decision_id, "approve", payload)

    @app.post("/decisions/{decision_id}/reject")
    def reject_decision(decision_id: str, payload: ReviewAction):
        return review(decision_id, "reject", payload)

    @app.get("/audit")
    def list_audit(limit: int = Query(default=100, ge=1, le=500)):
        with connection(db_path) as conn:
            rows = conn.execute(
                """SELECT a.id, a.decision_id, a.report_id, r.question_id, a.action, a.reviewer,
                          a.note, a.created_at
                   FROM audit a JOIN reports r ON r.id=a.report_id
                   ORDER BY a.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    return app


app = create_app()
