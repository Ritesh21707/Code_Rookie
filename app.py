from __future__ import annotations

import csv
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import secrets
import hmac
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD environment variable is not set.")


# Keep actual scores on the server.
PRIVATE_GRADES = {}
PRIVATE_GRADES_LOCK = threading.Lock()


def store_private_grade(result, kind, problem_id=None):
    receipt = secrets.token_urlsafe(32)

    with PRIVATE_GRADES_LOCK:
        PRIVATE_GRADES[receipt] = {
            "result": result,
            "kind": kind,
            "problem_id": problem_id,
        }

    return {"receipt": receipt}


def get_private_grade(receipt, kind):
    with PRIVATE_GRADES_LOCK:
        entry = PRIVATE_GRADES.get(str(receipt))

    if not entry or entry["kind"] != kind:
        raise ValueError("Invalid submission receipt.")

    return entry


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
RESULTS_DIR = BASE_DIR / "results"
EDIT_FILE = BASE_DIR / "EDIT_HERE.json"
RESULTS_DIR.mkdir(exist_ok=True)


def load_editable_data() -> dict[str, Any]:
    if not EDIT_FILE.is_file():
        raise RuntimeError(f"Missing editable config file: {EDIT_FILE.name}")

    try:
        data = json.loads(EDIT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{EDIT_FILE.name} has invalid JSON near line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    validate_editable_data(data)
    return data


def validate_editable_data(data: dict[str, Any]) -> None:
    for key in ("branding", "theme", "settings", "round1", "problems"):
        if key not in data:
            raise RuntimeError(f"{EDIT_FILE.name}: missing top-level key '{key}'.")

    settings = data["settings"]

    required_settings = (
        "round1_minutes", "round2_minutes", "round3_minutes",
        "round1_pass_percent", "round2_pass_percent", "round1_question_count",
    )

    for key in required_settings:
        if key not in settings:
            raise RuntimeError(f"{EDIT_FILE.name}: settings.{key} is required.")

    ids: set[str] = set()

    for bank_name in ("common", "python", "cpp"):
        bank = data["round1"].get(bank_name)

        if not isinstance(bank, list):
            raise RuntimeError(f"{EDIT_FILE.name}: round1.{bank_name} must be a list.")

        for q in bank:
            qid = str(q.get("id", ""))

            if not qid or qid in ids:
                raise RuntimeError(
                    f"{EDIT_FILE.name}: every Round 1 question needs a unique non-empty id; problem id: {qid!r}."
                )

            ids.add(qid)
            options = q.get("options")
            answer = q.get("answer")

            if not isinstance(options, list) or len(options) < 2:
                raise RuntimeError(
                    f"{EDIT_FILE.name}: question {qid} must have at least 2 options."
                )

            if not isinstance(answer, int) or answer < 0 or answer >= len(options):
                raise RuntimeError(
                    f"{EDIT_FILE.name}: question {qid} has an invalid answer index."
                )

            for field in ("question", "explanation"):
                if not str(q.get(field, "")).strip():
                    raise RuntimeError(
                        f"{EDIT_FILE.name}: question {qid} is missing {field}."
                    )

    problems = data["problems"]

    if not isinstance(problems, dict) or not problems:
        raise RuntimeError(f"{EDIT_FILE.name}: problems must be a non-empty object.")

    for pid, problem in problems.items():
        if problem.get("round") not in (2, 3):
            raise RuntimeError(
                f"{EDIT_FILE.name}: problem {pid} must have round 2 or 3."
            )

        for field in ("title", "kind", "statement", "input_format", "output_format"):
            if not str(problem.get(field, "")).strip():
                raise RuntimeError(
                    f"{EDIT_FILE.name}: problem {pid} is missing {field}."
                )

        starter = problem.get("starter", {})

        for lang in ("python", "cpp"):
            if lang not in starter:
                raise RuntimeError(
                    f"{EDIT_FILE.name}: problem {pid} needs starter.{lang}."
                )

        if not isinstance(problem.get("samples"), list) or not problem["samples"]:
            raise RuntimeError(
                f"{EDIT_FILE.name}: problem {pid} needs at least one sample."
            )

        if not isinstance(problem.get("tests"), list) or not problem["tests"]:
            raise RuntimeError(
                f"{EDIT_FILE.name}: problem {pid} needs at least one evaluator test."
            )


EDITABLE_DATA = load_editable_data()
BRANDING = EDITABLE_DATA["branding"]
THEME = EDITABLE_DATA["theme"]
APP_CONFIG = dict(EDITABLE_DATA["settings"])
APP_CONFIG["title"] = BRANDING.get("title", "Code Rookie")
APP_CONFIG["branding"] = BRANDING
APP_CONFIG["theme"] = THEME
ROUND1_COMMON = EDITABLE_DATA["round1"]["common"]
ROUND1_PYTHON = EDITABLE_DATA["round1"]["python"]
ROUND1_CPP = EDITABLE_DATA["round1"]["cpp"]
PROBLEMS: dict[str, dict[str, Any]] = EDITABLE_DATA["problems"]


def normalize_output(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def compiler_path() -> str | None:
    return shutil.which("g++") or shutil.which("clang++")


def capabilities() -> dict[str, Any]:
    compiler = compiler_path()

    return {
        "python": {"available": True, "version": sys.version.split()[0]},
        "cpp": {"available": bool(compiler), "compiler": compiler or "Not installed"},
    }


@dataclass
class RunResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    compile_error: bool = False


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_python(code: str, stdin: str, timeout: float = 2.0) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="code_rookie_") as td:
        path = Path(td) / "main.py"
        path.write_text(code, encoding="utf-8")

        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(path)],
                input=stdin,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=td,
                env=_subprocess_env(),
            )

            return RunResult(proc.returncode == 0, proc.stdout, proc.stderr)

        except subprocess.TimeoutExpired as exc:
            return RunResult(
                False,
                (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "Time limit exceeded",
                True,
            )


def run_cpp(code: str, stdin: str, timeout: float = 2.0) -> RunResult:
    compiler = compiler_path()

    if not compiler:
        return RunResult(
            False,
            stderr="No C++ compiler found. Install g++ or clang++ and restart the app.",
            compile_error=True,
        )

    with tempfile.TemporaryDirectory(prefix="code_rookie_") as td:
        src = Path(td) / "main.cpp"
        exe = Path(td) / ("main.exe" if os.name == "nt" else "main")
        src.write_text(code, encoding="utf-8")

        compile_cmd = [
            compiler, str(src), "-std=c++17", "-O2", "-o", str(exe)
        ]

        try:
            comp = subprocess.run(
                compile_cmd,
                text=True,
                capture_output=True,
                timeout=8,
                cwd=td,
            )

        except subprocess.TimeoutExpired:
            return RunResult(
                False,
                stderr="Compilation timed out.",
                compile_error=True,
            )

        if comp.returncode != 0:
            return RunResult(False, stderr=comp.stderr, compile_error=True)

        try:
            proc = subprocess.run(
                [str(exe)],
                input=stdin,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=td,
            )

            return RunResult(proc.returncode == 0, proc.stdout, proc.stderr)

        except subprocess.TimeoutExpired as exc:
            return RunResult(
                False,
                (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "Time limit exceeded",
                True,
            )


def execute(language: str, code: str, stdin: str) -> RunResult:
    if language == "python":
        return run_python(code, stdin)

    if language == "cpp":
        return run_cpp(code, stdin)

    return RunResult(False, stderr="Unsupported language")


def public_problem(problem: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": problem["title"],
        "kind": problem["kind"],
        "statement": problem["statement"],
        "input_format": problem["input_format"],
        "output_format": problem["output_format"],
        "samples": problem["samples"],
        "starter": problem["starter"],
        "test_count": len(problem["tests"]),
    }


def round1_payload(language: str) -> dict[str, Any]:
    language = "cpp" if language == "cpp" else "python"
    bank = ROUND1_COMMON + (ROUND1_CPP if language == "cpp" else ROUND1_PYTHON)
    count = min(APP_CONFIG["round1_question_count"], len(bank))
    rng = random.SystemRandom()
    picked = rng.sample(bank, count)

    # Never send the answer key to the browser.
    questions = [
        {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "options": q["options"],
        }
        for q in picked
    ]

    token = str(uuid.uuid4())

    QUIZ_SESSIONS[token] = {
        "created": time.time(),
        "question_ids": [q["id"] for q in picked],
        "language": language,
    }

    return {"token": token, "questions": questions}


def all_round1_by_id() -> dict[str, dict[str, Any]]:
    return {
        q["id"]: q
        for q in ROUND1_COMMON + ROUND1_PYTHON + ROUND1_CPP
    }


QUIZ_SESSIONS: dict[str, dict[str, Any]] = {}
SESSIONS_LOCK = threading.Lock()


def grade_round1(token: str, answers: dict[str, Any]) -> dict[str, Any]:
    with SESSIONS_LOCK:
        session = QUIZ_SESSIONS.pop(token, None)

    if not session or time.time() - session["created"] > 7200:
        raise ValueError("Quiz session expired or invalid.")

    bank = all_round1_by_id()
    total = len(session["question_ids"])
    correct = 0
    review = []

    for qid in session["question_ids"]:
        q = bank[qid]
        selected = answers.get(qid)
        is_correct = selected == q["answer"]

        if is_correct:
            correct += 1

        review.append({
            "id": qid,
            "correct": is_correct,
            "selected": selected,
            "answer": q["answer"],
            "explanation": q["explanation"],
        })

    percent = round((correct / total) * 100, 2) if total else 0

    return {
        "correct": correct,
        "total": total,
        "percent": percent,
        "qualified": percent >= APP_CONFIG["round1_pass_percent"],
        "review": review,
    }


def evaluate_problem(
    problem_id: str,
    language: str,
    code: str,
    mode: str,
) -> dict[str, Any]:
    if problem_id not in PROBLEMS:
        raise ValueError("Unknown problem.")

    problem = PROBLEMS[problem_id]
    tests = problem["tests"]

    if mode == "sample":
        tests = [
            {
                "input": s["input"],
                "expected": normalize_output(s["output"]),
            }
            for s in problem["samples"]
        ]

    results = []
    passed = 0
    started = time.perf_counter()

    for index, test in enumerate(tests, start=1):
        run = execute(language, code, test["input"])
        actual = normalize_output(run.stdout)
        expected = normalize_output(test["expected"])
        ok = run.ok and actual == expected

        if ok:
            passed += 1

        item: dict[str, Any] = {
            "test": index,
            "passed": ok,
            "runtime_error": bool(run.stderr) and not run.compile_error,
            "timed_out": run.timed_out,
            "compile_error": run.compile_error,
        }

        if mode == "sample":
            item.update({
                "input": test["input"],
                "expected": expected,
                "actual": actual,
                "stderr": run.stderr[:3000],
            })
        elif run.compile_error:
            item["stderr"] = run.stderr[:3000]

        results.append(item)

        if run.compile_error:
            # A compilation error will affect every test.
            break

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    total = len(tests)
    percent = round((passed / total) * 100, 2) if total else 0

    return {
        "problem_id": problem_id,
        "mode": mode,
        "passed": passed,
        "total": total,
        "percent": percent,
        "elapsed_ms": elapsed_ms,
        "qualified": (
            percent >= APP_CONFIG["round2_pass_percent"]
            if problem["round"] == 2 else None
        ),
        "results": results,
    }


def save_result(payload: dict[str, Any]) -> str:
    rid = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"

    safe = {
        "id": rid,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "participant": str(payload.get("participant", "")).strip()[:120],
        "college_id": str(payload.get("college_id", "")).strip()[:80],
        "language": str(payload.get("language", ""))[:20],
        "round1": payload.get("round1"),
        "round2": payload.get("round2"),
        "round3": payload.get("round3"),
    }

    (RESULTS_DIR / f"{rid}.json").write_text(
        json.dumps(safe, indent=2),
        encoding="utf-8",
    )

    return rid


def load_results() -> list[dict[str, Any]]:
    rows = []

    for path in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue

    return rows


# ---------- Activity warnings ----------

WARNINGS_DIR = BASE_DIR / "activity_warnings"
WARNINGS_DIR.mkdir(exist_ok=True)
WARNINGS_LOCK = threading.Lock()


def save_activity_warning(payload):
    event_id = str(uuid.UUID(str(payload.get("event_id", ""))))
    participant = str(payload.get("participant", "")).strip()[:120]
    round_no = payload.get("round")

    if (
        not participant
        or type(round_no) is not int
        or round_no not in (1, 2, 3)
    ):
        raise ValueError("Invalid activity warning.")

    record = {
        "event_id": event_id,
        "participant": participant,
        "college_id": str(payload.get("college_id", "")).strip()[:80],
        "language": str(payload.get("language", ""))[:20],
        "round": round_no,
        "reported_at": str(payload.get("reported_at", ""))[:40],
        "received_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ),
        "reason": "Quiz page hidden or navigated away",
    }

    with WARNINGS_LOCK:
        target = WARNINGS_DIR / f"{event_id}.json"

        # Retrying the same warning must not create duplicates.
        if not target.exists():
            target.write_text(
                json.dumps(record, ensure_ascii=False),
                encoding="utf-8",
            )

    return {"saved": True}


def load_activity_warnings():
    rows = []

    with WARNINGS_LOCK:
        for path in WARNINGS_DIR.glob("*.json"):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue

    return sorted(
        rows,
        key=lambda row: row.get("received_at", ""),
        reverse=True,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "CodeRookie/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(
        self,
        text: str,
        content_type: str,
        status: int = 200,
    ) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))

        if length <= 0 or length > 2_000_000:
            raise ValueError("Invalid request size.")

        raw = self.rfile.read(length)
        obj = json.loads(raw.decode("utf-8"))

        if not isinstance(obj, dict):
            raise ValueError("Expected a JSON object.")

        return obj

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in (
            "/api/results",
            "/api/results.csv",
            "/api/activity-warnings",
        ):
            supplied = self.headers.get("X-Admin-Password", "")

            if not hmac.compare_digest(
                supplied.encode("utf-8"),
                ADMIN_PASSWORD.encode("utf-8"),
            ):
                self._send_json(
                    {"error": "Admin password required or incorrect."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return

        try:
            if path == "/api/activity-warnings":
                self._send_json({"warnings": load_activity_warnings()})
                return

            if path == "/api/config":
                self._send_json({
                    "config": APP_CONFIG,
                    "capabilities": capabilities(),
                })
                return

            if path == "/api/round1":
                lang = query.get("language", ["python"])[0]

                with SESSIONS_LOCK:
                    payload = round1_payload(lang)

                self._send_json(payload)
                return

            if path == "/api/problems":
                round_no = int(query.get("round", ["2"])[0])
                language = query.get("language", ["python"])[0]

                items = [
                    {"id": pid, **public_problem(p)}
                    for pid, p in PROBLEMS.items()
                    if p["round"] == round_no
                    and p.get("language") == language
                ]

                self._send_json({"problems": items})
                return

            if path == "/api/results":
                self._send_json({"results": load_results()})
                return

            if path == "/api/results.csv":
                rows = load_results()
                buf = io.StringIO()
                writer = csv.writer(buf)

                writer.writerow([
                    "saved_at",
                    "participant",
                    "college_id",
                    "language",
                    "round1_percent",
                    "round2_percent",
                    "round3_passed",
                    "round3_total",
                ])

                for r in rows:
                    writer.writerow([
                        r.get("saved_at", ""),
                        r.get("participant", ""),
                        r.get("college_id", ""),
                        r.get("language", ""),
                        (r.get("round1") or {}).get("percent", ""),
                        (r.get("round2") or {}).get("percent", ""),
                        (r.get("round3") or {}).get("passed", ""),
                        (r.get("round3") or {}).get("total", ""),
                    ])

                self._send_text(
                    buf.getvalue(),
                    "text/csv; charset=utf-8",
                )
                return

            self._serve_static(path)

        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(
                {"error": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )

        except Exception as exc:
            self._send_json(
                {"error": f"Server error: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_POST(self) -> None:
        try:
            payload = self._read_json()

        except json.JSONDecodeError:
            self._send_json(
                {"error": "Invalid JSON in request body"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        except ValueError as exc:
            self._send_json(
                {"error": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if self.path == "/api/results/reset":
            supplied = self.headers.get("X-Admin-Password", "")

            if not hmac.compare_digest(
                supplied.encode("utf-8"),
                ADMIN_PASSWORD.encode("utf-8"),
            ):
                self._send_json(
                    {"error": "Admin password required or incorrect."},
                    HTTPStatus.UNAUTHORIZED,
                )
                return

            deleted = 0

            for result_file in RESULTS_DIR.glob("*.json"):
                try:
                    result_file.unlink()
                    deleted += 1
                except Exception:
                    pass

            self._send_json({
                "reset": True,
                "deleted": deleted,
            })
            return

        try:
            if self.path == "/api/activity-warnings":
                self._send_json(save_activity_warning(payload))
                return

            if self.path == "/api/round1/grade":
                result = grade_round1(
                    str(payload.get("token", "")),
                    payload.get("answers", {}),
                )

                self._send_json(store_private_grade(result, "round1"))
                return

            if self.path == "/api/evaluate":
                code = str(payload.get("code", ""))

                if len(code) > 100_000:
                    raise ValueError("Code is too large.")

                problem_id = str(payload.get("problem_id", ""))

                if problem_id not in PROBLEMS:
                    raise ValueError("Unknown problem.")

                mode = str(payload.get("mode", "submit"))

                if mode == "sample":
                    result = evaluate_problem(
                        problem_id,
                        str(payload.get("language", "python")),
                        code,
                        "sample",
                    )
                    self._send_json(result)
                    return

                # Final submission stays private.
                result = evaluate_problem(
                    problem_id,
                    str(payload.get("language", "python")),
                    code,
                    "submit",
                )

                self._send_json(
                    store_private_grade(result, "coding", problem_id)
                )
                return

            if self.path == "/api/results":
                r1 = get_private_grade(
                    payload.get("round1_receipt"), "round1"
                )["result"]

                def collect_round(round_no, receipts):
                    if not isinstance(receipts, dict):
                        raise ValueError("Invalid round submissions.")

                    selected_language = str(
                        payload.get("language", "python")
                    )
                    selected_language = (
                        "cpp" if selected_language == "cpp" else "python"
                    )

                    expected = {
                        pid
                        for pid, p in PROBLEMS.items()
                        if p["round"] == round_no
                        and p.get("language") == selected_language
                    }

                    if set(receipts) != expected:
                        raise ValueError("Missing round submissions.")

                    passed = 0
                    total = 0

                    for pid, receipt in receipts.items():
                        entry = get_private_grade(receipt, "coding")

                        if entry["problem_id"] != pid:
                            raise ValueError(
                                "Submission does not match problem."
                            )

                        result = entry["result"]
                        passed += result.get("passed", 0)
                        total += result.get("total", 0)

                    percent = round(passed / total * 100, 2) if total else 0

                    return {
                        "passed": passed,
                        "total": total,
                        "percent": percent,
                    }

                r2 = collect_round(2, payload.get("round2_receipts"))
                r3 = collect_round(3, payload.get("round3_receipts"))

                # Ignore any scores supplied by the browser.
                rid = save_result({
                    "participant": payload.get("participant", ""),
                    "college_id": payload.get("college_id", ""),
                    "language": payload.get("language", ""),
                    "round1": r1,
                    "round2": r2,
                    "round3": r3,
                })

                self._send_json({"saved": True, "id": rid})
                return

            self._send_json(
                {"error": "Not found"},
                HTTPStatus.NOT_FOUND,
            )

        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(
                {"error": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )

        except Exception:
            self._send_json(
                {"error": "Server error. Please contact the organizer."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"

        clean = Path(path.lstrip("/")).as_posix()
        target = (STATIC_DIR / clean).resolve()

        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self._send_json(
                {"error": "Invalid path"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if not target.is_file():
            self._send_json(
                {"error": "Not found"},
                HTTPStatus.NOT_FOUND,
            )
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }

        body = target.read_bytes()

        self.send_response(200)
        self.send_header(
            "Content-Type",
            content_types.get(target.suffix, "application/octet-stream"),
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)

    print("=" * 60)
    print(APP_CONFIG["title"])
    print(f"Open: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()