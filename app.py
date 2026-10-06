import json
import os
import threading
import uuid
from io import BytesIO
from pathlib import Path
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


def translate_job(job_id: str, chunks: list[str], direction: str) -> None:
    source_language, target_language = LANGUAGES[direction]
    try:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
        client = OpenAI(api_key=api_key)
        translated_parts = []
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            response = client.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
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
        finish_job(job_id, "error", message=str(exc))


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/start")
def start_translation():
    pdf_file = request.files.get("pdf")
    direction = request.form.get("direction", "en-ko")
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
        args=(job_id, chunks, direction),
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
