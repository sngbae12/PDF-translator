import json
import os
import threading
import uuid
from io import BytesIO
from pathlib import Path
import openai
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_file,
    stream_with_context,
)
from openai import OpenAI
from pypdf import PdfReader

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
# 간단한 단일 서버용 메모리 작업 저장소입니다.
# 사용자가 입력한 API 키는 여기에 절대 저장하지 않습니다(번역 스레드 인자로만 전달).
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
LANGUAGES = {
    "en-ko": ("영어", "한국어"),
    "ko-en": ("한국어", "영어"),
}


def split_text(text: str, max_chars: int = 6000) -> list[str]:
    """문단 경계를 우선하여 API에 전달하기 적당한 크기로 나눕니다."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    while len(text) > max_chars:
        split_at = text.rfind("\n\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = text.rfind("\n", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = text.rfind(" ", 0, max_chars)
        if split_at < max_chars // 2:
            split_at = max_chars
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


def add_event(job_id: str, event_type: str, **data) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        with job["condition"]:
            job["events"].append({"type": event_type, **data})
            job["condition"].notify_all()


def finish_job(job_id: str, event_type: str, **data) -> None:
    """최종 이벤트 저장과 완료 표시를 원자적으로 처리합니다."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        with job["condition"]:
            if "result" in data:
                job["result"] = data.pop("result")
            if event_type == "error":
                job["error"] = data.get("message")
            job["events"].append({"type": event_type, **data})
            job["done"] = True
            job["condition"].notify_all()


def describe_error(exc: Exception, model: str) -> tuple[str, str]:
    """OpenAI 예외를 사용자가 이해할 수 있는 (코드, 메시지)로 바꿉니다.

    API 키가 화면이나 작업 기록에 섞여 나가지 않도록 예외 원문은 노출하지 않습니다.
    """
    if isinstance(exc, openai.AuthenticationError):
        return (
            "invalid_api_key",
            "OpenAI API 키가 올바르지 않습니다. 키를 다시 확인한 뒤 입력해 주세요.",
        )
    if isinstance(exc, openai.PermissionDeniedError):
        return (
            "permission_denied",
            f"이 API 키로는 '{model}' 모델을 사용할 권한이 없습니다. "
            "OpenAI 계정의 모델 접근 권한을 확인해 주세요.",
        )
    if isinstance(exc, openai.RateLimitError):
        detail = f"{getattr(exc, 'code', '')} {getattr(exc, 'type', '')} {exc}"
        if "insufficient_quota" in detail:
            return (
                "insufficient_quota",
                "API 사용 한도 또는 잔액이 부족합니다. "
                "OpenAI 계정의 결제 정보와 사용량을 확인해 주세요.",
            )
        return (
            "rate_limit",
            "요청이 너무 많아 OpenAI가 잠시 제한했습니다. 잠시 후 다시 시도해 주세요.",
        )
    if isinstance(exc, openai.NotFoundError):
        return (
            "model_not_found",
            f"'{model}' 모델을 찾을 수 없습니다. OPENAI_MODEL 환경 변수 값을 확인해 주세요.",
        )
    if isinstance(exc, openai.BadRequestError):
        return (
            "bad_request",
            "OpenAI가 요청을 거부했습니다. 문서가 너무 길거나 모델이 처리할 수 없는 내용일 수 있습니다.",
        )
    if isinstance(exc, openai.APITimeoutError):
        return (
            "timeout",
            "OpenAI 응답이 제한 시간을 초과했습니다. 잠시 후 다시 시도해 주세요.",
        )
    if isinstance(exc, openai.APIConnectionError):
        return (
            "connection",
            "OpenAI 서버에 연결할 수 없습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.",
        )
    if isinstance(exc, openai.InternalServerError):
        return (
            "server_error",
            "OpenAI 서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.",
        )
    if isinstance(exc, openai.APIStatusError):
        return (
            "api_error",
            f"OpenAI API 오류가 발생했습니다. (HTTP {exc.status_code})",
        )
    return (
        "unexpected",
        f"번역 중 예상하지 못한 오류가 발생했습니다. ({type(exc).__name__})",
    )


def translate_job(job_id: str, chunks: list[str], direction: str, api_key: str) -> None:
    """사용자가 입력한 API 키로 번역합니다. 키는 이 함수가 실행되는 동안만 메모리에 둡니다."""
    source_language, target_language = LANGUAGES[direction]
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = None
    try:
        client = OpenAI(api_key=api_key)
        translated_parts = []
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"당신은 전문 번역가입니다. {source_language} 원문을 "
                            f"{target_language}로 정확하고 자연스럽게 번역하세요. "
                            "제목, 문단, 목록 형식을 최대한 유지하고 번역문만 출력하세요."
                        ),
                    },
                    {"role": "user", "content": chunk},
                ],
                temperature=0.2,
            )
            translated = response.choices[0].message.content or ""
            translated_parts.append(translated)
            progress = round(index / total * 100)
            add_event(
                job_id,
                "progress",
                progress=progress,
                text=translated + ("\n\n" if index < total else ""),
            )
        result = "\n\n".join(translated_parts)
        finish_job(job_id, "complete", progress=100, result=result)
    except Exception as exc:
        code, message = describe_error(exc, model)
        finish_job(job_id, "error", code=code, message=message)
    finally:
        # 번역이 끝나면 키와 HTTP 클라이언트 참조를 즉시 해제합니다.
        if client is not None:
            client.close()
        del client, api_key


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/start")
def start_translation():
    pdf_file = request.files.get("pdf")
    direction = request.form.get("direction", "en-ko")
    # API 키는 URL이 아닌 multipart 요청 본문으로만 받습니다.
    api_key = (request.form.get("api_key") or "").strip()
    if not api_key:
        return (
            jsonify(
                {
                    "error": "OpenAI API 키를 입력해 주세요. 키가 없으면 번역을 시작할 수 없습니다.",
                    "field": "api_key",
                }
            ),
            400,
        )
    if any(character.isspace() for character in api_key):
        return (
            jsonify(
                {
                    "error": "API 키에 공백이나 줄바꿈이 포함되어 있습니다. 키를 다시 복사해 입력해 주세요.",
                    "field": "api_key",
                }
            ),
            400,
        )
    if not pdf_file or not pdf_file.filename:
        return jsonify({"error": "PDF 파일을 선택해 주세요."}), 400
    if direction not in LANGUAGES:
        return jsonify({"error": "지원하지 않는 번역 방향입니다."}), 400
    if Path(pdf_file.filename).suffix.lower() != ".pdf":
        return jsonify({"error": "PDF 파일만 업로드할 수 있습니다."}), 400
    try:
        reader = PdfReader(pdf_file.stream)
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pages.append(f"[페이지 {page_number}]\n{page_text}")
    except Exception:
        return (
            jsonify(
                {
                    "error": "PDF를 읽을 수 없습니다. 파일이 손상되었거나 암호화되었는지 확인해 주세요."
                }
            ),
            400,
        )
    extracted_text = "\n\n".join(pages)
    chunks = split_text(extracted_text)
    if not chunks:
        return (
            jsonify(
                {
                    "error": "PDF에서 텍스트를 찾지 못했습니다. 스캔 이미지 PDF는 OCR이 필요합니다."
                }
            ),
            400,
        )
    # 경로 문자는 제거하되 한글 원본 파일명은 보존합니다.
    original_name = Path(pdf_file.filename).name or "translation.pdf"
    download_name = f"{Path(original_name).stem}.txt"
    job_id = uuid.uuid4().hex
    condition = threading.Condition()
    with jobs_lock:
        jobs[job_id] = {
            "events": [],
            "condition": condition,
            "result": "",
            "download_name": download_name,
            "done": False,
            "error": None,
        }
    threading.Thread(
        target=translate_job,
        args=(job_id, chunks, direction, api_key),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id, "extracted_text": extracted_text})


@app.get("/events/<job_id>")
def stream_events(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "작업을 찾을 수 없습니다."}), 404

    @stream_with_context
    def generate():
        event_index = 0
        while True:
            with jobs_lock:
                job = jobs.get(job_id)
                if not job:
                    return
                condition = job["condition"]
            with condition:
                while event_index >= len(job["events"]) and not job["done"]:
                    condition.wait(timeout=15)
                    if event_index >= len(job["events"]) and not job["done"]:
                        yield ": keep-alive\n\n"
                pending = job["events"][event_index:]
            for event in pending:
                event_index += 1
                event_type = event["type"]
                payload = {key: value for key, value in event.items() if key != "type"}
                yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if job["done"] and event_index >= len(job["events"]):
                return

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/download/<job_id>")
def download(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
        if not job["done"] or job["error"]:
            return jsonify({"error": "완료된 번역 결과가 없습니다."}), 409
        content = job["result"].encode("utf-8-sig")
        download_name = job["download_name"]
    return send_file(
        BytesIO(content),
        mimetype="text/plain; charset=utf-8",
        as_attachment=True,
        download_name=download_name,
    )


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({"error": "파일 크기는 20MB를 초과할 수 없습니다."}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
