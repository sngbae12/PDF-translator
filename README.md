# PDF 번역기

PDF에서 텍스트를 추출하고 OpenAI API로 영어·한국어 번역을 수행하는 로컬 Flask 웹 애플리케이션입니다. 번역 진행률과 결과를 SSE(Server-Sent Events)로 실시간 표시하며, 완료된 번역을 원본 PDF와 같은 이름의 TXT 파일로 내려받을 수 있습니다. OpenAI API 키는 환경 변수 설정 없이 브라우저 화면에서 직접 입력합니다.

## 주요 기능

- 브라우저 화면에서 본인의 OpenAI API 키 입력(보기/숨기기 지원, 환경 변수 불필요)
- 텍스트 기반 PDF에서 페이지별 텍스트 추출
- 영어 → 한국어, 한국어 → 영어 번역
- 긴 문서를 청크 단위로 나누어 OpenAI API 호출
- 실시간 진행률 및 번역 결과 표시
- UTF-8 BOM이 포함된 TXT 다운로드(Windows 메모장 한글 호환)
- 운영체제 설정에 따른 라이트/다크 디자인
- 최대 20MB PDF 업로드

## 프로젝트 구조

```text
PDF-translator/
├─ app.py
├─ requirements.txt
├─ start.bat
├─ .env.example
├─ .gitattributes
├─ .gitignore
├─ README.md
└─ templates/
   └─ index.html
```

업로드한 PDF와 번역 결과는 서버 디스크에 저장하지 않고 실행 중인 메모리에만 보관합니다. 서버를 종료하면 작업 결과도 사라집니다.

## 준비 사항

- Python 3.10 이상(검증 환경: Python 3.11)
- 인터넷 연결
- 결제 수단이 등록되고 API 사용이 가능한 OpenAI API 키([OpenAI API Keys](https://platform.openai.com/api-keys)에서 발급)

OpenAI Chat Completions API를 호출하므로 사용량에 따라 OpenAI API 요금이 발생하며, **요금은 화면에 입력한 키의 계정에 청구됩니다.** ChatGPT Plus 등의 웹 구독과 API 결제는 별개입니다. 기본 모델은 `gpt-4o-mini`이며 `OPENAI_MODEL` 환경 변수로 변경할 수 있습니다.

## 개인 노트북에서 설치 및 실행

### 1. 저장소 내려받기

```powershell
git clone https://github.com/sngbae12/PDF-translator.git
cd PDF-translator
```

Git이 없다면 GitHub 저장소의 **Code → Download ZIP**으로 내려받고 압축을 푼 뒤 해당 폴더에서 터미널을 여세요.

### 2. 가상환경 생성 및 활성화

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 때문에 활성화가 차단되면 현재 창에서만 다음 명령을 먼저 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 라이브러리 설치

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. (선택) 번역 모델 설정

API 키는 환경 변수로 설정할 필요가 없습니다. 앱 실행 후 브라우저 화면에서 입력합니다.

기본 모델(`gpt-4o-mini`) 대신 다른 모델을 쓰고 싶을 때만 실행 전에 `OPENAI_MODEL`을 설정하세요.

Windows PowerShell(현재 터미널에만 적용):

```powershell
$env:OPENAI_MODEL="gpt-4o-mini"
```

macOS/Linux:

```bash
export OPENAI_MODEL="gpt-4o-mini"
```

`.env.example`은 사용 가능한 변수 이름을 보여주는 예시일 뿐이며 앱이 `.env` 파일을 자동으로 읽지는 않습니다.

### 5. 앱 실행

모든 운영체제:

```powershell
python app.py
```

브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:5000
```

Windows에서는 라이브러리 설치를 마친 후 `start.bat`을 더블클릭해도 됩니다. `start.bat`은 프로젝트 폴더에 `.venv`가 있으면 그 가상환경의 Python으로, 없으면 PATH의 `python`으로 서버를 실행하고 브라우저를 자동으로 엽니다. 환경 변수가 없어도 실행이 막히지 않습니다. 서버가 실행 중인 터미널 창을 닫으면 앱도 종료됩니다.

## 사용 방법

1. **OpenAI API 키** 입력란에 본인의 API 키를 붙여 넣습니다. 입력 내용은 비밀번호처럼 가려지며 **보기/숨기기** 버튼으로 확인할 수 있습니다.
2. PDF 파일을 선택합니다.
3. 번역 방향을 선택합니다.
4. **번역 시작**을 누릅니다. API 키가 비어 있으면 번역이 시작되지 않고 입력 안내가 표시됩니다.
5. 진행률과 번역 결과를 확인합니다.
6. 완료되면 **TXT 다운로드**를 누릅니다.

예를 들어 `report.pdf`를 업로드하면 결과 파일명은 `report.txt`입니다. 같은 브라우저 탭에서는 입력한 키가 입력란에 남아 있어 여러 파일을 이어서 번역할 수 있고, 탭을 닫거나 새로고침하면 사라집니다.

## API 키 처리 방식

- 키는 번역 시작 요청의 본문(multipart form)으로만 로컬 서버에 전달되며 URL에는 포함되지 않습니다.
- 서버는 키를 번역 스레드의 인자로만 사용하고, 작업 상태·번역 결과·로그·파일에는 저장하지 않습니다. 번역이 끝나면 참조를 해제합니다.
- 브라우저의 localStorage, sessionStorage, 쿠키에 키를 저장하지 않습니다.
- OpenAI 오류 메시지는 원문 대신 아래와 같이 정리된 문구로 표시되며, 키 값이 화면이나 작업 기록에 노출되지 않습니다.

| 상황 | 표시되는 안내 |
| --- | --- |
| 키 미입력 | OpenAI API 키를 입력해 주세요. 키가 없으면 번역을 시작할 수 없습니다. |
| 잘못된 키(401) | OpenAI API 키가 올바르지 않습니다. 키를 다시 확인한 뒤 입력해 주세요. |
| 사용 한도·잔액 부족(429 `insufficient_quota`) | API 사용 한도 또는 잔액이 부족합니다. OpenAI 계정의 결제 정보와 사용량을 확인해 주세요. |
| 요청 제한(429) | 요청이 너무 많아 OpenAI가 잠시 제한했습니다. 잠시 후 다시 시도해 주세요. |
| 모델 권한 없음(403) / 모델 없음(404) | 모델 접근 권한 또는 `OPENAI_MODEL` 값을 확인하라는 안내 |
| 네트워크 오류·시간 초과 | 인터넷 연결 확인 또는 재시도 안내 |

## PDF, OCR 및 글꼴 관련 안내

- 현재 앱은 `pypdf`로 PDF 내부의 **텍스트 레이어만** 추출합니다.
- 스캔 문서나 이미지로만 구성된 PDF에는 OCR이 적용되지 않습니다. 이런 파일은 Adobe Acrobat, Google Drive OCR, Tesseract OCR 등의 도구로 먼저 검색 가능한 PDF로 변환해야 합니다.
- 현재 결과 형식은 TXT이며 번역된 PDF를 생성하지 않습니다.
- 따라서 별도 PDF 렌더러나 한글 글꼴 파일은 필요하지 않습니다. 브라우저는 시스템 한글 글꼴을 사용하고, TXT 파일은 UTF-8 BOM으로 저장됩니다.
- 향후 번역된 PDF 생성 기능을 추가한다면 `Noto Sans KR` 같은 한글 글꼴을 포함하고 배포 라이선스와 글꼴 임베딩을 별도로 처리해야 합니다.

## 제한 사항

- 암호화되거나 손상된 PDF는 읽을 수 없습니다.
- 표, 다단 편집, 복잡한 레이아웃은 텍스트 추출 순서가 달라질 수 있습니다.
- 작업 상태는 메모리에 저장되므로 서버를 재시작하면 사라집니다.
- Flask 개발 서버 기반의 개인 로컬 실행용 앱입니다. 인터넷에 공개 배포하도록 구성되어 있지 않습니다.
- 모델 접근 권한, API 잔액, 요청 제한 또는 네트워크 상태에 따라 번역 요청이 실패할 수 있습니다.

## 보안

- API 키는 코드나 설정 파일에 넣지 않고 화면에서 입력하며, 서버는 키를 디스크·로그·작업 결과에 기록하지 않습니다.
- 이 앱은 `127.0.0.1`(내 컴퓨터)에서만 수신하며 HTTP로 동작합니다. 다른 사람이 접근할 수 있는 네트워크에 공개하거나 `host`를 `0.0.0.0`으로 바꾸지 마세요. 공개 네트워크에서는 입력한 키가 평문으로 전송됩니다.
- `.env`, 인증 키, 가상환경, 캐시, 로그, 업로드 PDF 및 생성 결과 경로는 `.gitignore`에서 제외됩니다.
- 이미 노출된 API 키는 Git에서 파일을 삭제하는 것만으로 안전해지지 않습니다. 즉시 OpenAI 대시보드에서 해당 키를 폐기하고 새 키를 발급하세요.
