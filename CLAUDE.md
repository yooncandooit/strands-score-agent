# 프로젝트: ASBG 발표용 Strands 실습 repo

## 이 문서의 목적

동아리(AWS Student Builder Group at DGU) 기술 발표를 위한 실습 repo를 만든다.
이 문서는 다른 세션에서 정리된 맥락을 인수인계하기 위한 것이다.
**코드를 짜기 전에 이 문서를 끝까지 읽고, 불명확한 점은 먼저 질문할 것.**

---

## 1. 발표 개요

| 항목 | 내용 |
|---|---|
| 제목 | 「내 백엔드는 그대로, 앞단만 바꿨습니다」 — 학원 성적 시스템에 에이전트 얹기 |
| 시간 | 20분 (문제·개념 ~9분 + 핸즈온 ~7분 + 마무리 ~4분) |
| 청중 | 동아리 부원 전체. 기술 배경 다양 (프론트/백엔드/인프라/입문자 혼재) |
| 장르 | 회고 + 트러블슈팅. "AI 신기해요" 발표가 아님 |
| 발표자 배경 | 프론트엔드 중심, 최근 AWS 학습 중. FDE(Forward Deployed Engineer) 취업 준비 |

### 발표의 한 문장 (모든 판단의 기준)

> 자주 쓰는 건 화면으로 남기고, 가끔 나오는 변형 요구는 도구로 열어 챗봇이 받게 했다.
> 백엔드(admin-api)는 한 줄도 안 바꾸고.

### 3줄 요약

1. 매주 반복되는 기능은 화면으로 잘 만들었다. 그건 화면이 맞다.
2. 근데 어쩌다 나오는 변형 요구까지 전부 화면으로 만들 필요는 없었다.
3. 백엔드를 도구(@tool)로 감싸니, 그런 요구는 챗봇이 받더라. 백엔드 코드는 그대로.

### 하지 말아야 할 프레이밍 (중요)

- ❌ "불필요한 화면을 만들었다" → 발표자의 3개월을 깎는 말. 화면은 필요했다.
- ⭕ "모든 요구를 화면으로 받으려 한 게 문제였다" → 이게 정확한 진단.
- 화면 vs 도구의 **대립**이 아니라 화면 **+** 도구의 **증축**이다.

---

## 2. 실화 배경 (발표의 재료)

발표자는 대성 영어학원의 성적 관리 시스템을 **3개월간 외주 개발**했다.
학부모-선생님 연결, 학생 점수 입력, 학부모 성적 확인, 성적 문자 발송 등.

실제 시스템 구성 (배포 중):
```
admin.html (관리자 화면) ──┐
index.html (학부모/학생용) ─┼─→ admin-api (Deno Edge Function) ─→ Supabase (PostgreSQL)
                            Vercel 호스팅
```

### admin-api의 정체 (발표의 핵심 코드)

admin-api는 **범용 데이터 접근 게이트웨이**다. 화면마다 API를 따로 만든 게 아니라,
하나의 통로로 8개 테이블 전부를 CRUD하게 열어뒀다.

동작:
```
프론트가 { password, path, method, body }를 던지면
→ 비밀번호 확인 (safeEqual)
→ 허용 테이블인지 확인 (classes, students, weeks, scores, mock_exams, mock_scores, memos, app_settings)
→ Supabase REST(`/rest/v1/{path}`)로 그대로 전달
→ 결과 반환
```

핵심 통찰: **지금은 admin.html(화면)이 path를 조립해서 이 게이트웨이를 부른다.**
"path를 조립하는 그 일"을 사람 대신 에이전트가 하면 그게 도구 방식이다.

```
현재:  선생님 버튼 클릭 → admin.html이 path 조립 → admin-api → Supabase
발표:  선생님 자연어    → 에이전트가 path 조립 → @tool     → (실습은 mock DB)
```

### 선생님이 실제로 보낸 요청들 (발표 도입부 재료)

1. "점수입력 탭의 채점 항목 더 늘릴 수 있을까요?"
2. "성적 발송 탭에서 기본 양식을 제가 수정하게 할 수 있을까여?"
3. "성적 문자 발송, 학생이나 학부모 선택해서 보낼 수 있게 가능할까요?"
4. "특정 반끼리 묶어 평균을 계산하도록 할 수 있을까요?"

이 요청들은 모두 **매주 반복되는 업무**라 화면으로 만든 게 옳았다.
문제는 이런 요청이 올 때마다 매번 새 화면을 만들어야 했다는 것.
그리고 화면으로 안 만든 변형 질문(예: "결석 많은 애들 빼고 평균")은 답할 방법이 없었다.

---

## 3. 실제 DB 스키마 (Supabase / PostgreSQL)

실습은 **이 스키마를 그대로 따르되 데이터는 mock**으로 만든다.
실제 Supabase에 연결하지 않는다 (개인정보 + 네트워크 리스크 + 발표장 안정성).

```sql
CREATE TABLE public.classes (
  id integer PRIMARY KEY,
  name text NOT NULL UNIQUE,   -- 예: "3반"
  day text NOT NULL,           -- 예: "월수", "화목", "금"
  time text,
  grade text                   -- 예: "중1", "중2", "중3"
);

CREATE TABLE public.students (
  id integer PRIMARY KEY,
  name text NOT NULL,
  pin text NOT NULL,
  class_id integer REFERENCES classes(id),
  is_active boolean DEFAULT true,
  phone text,           -- 학부모 연락처
  student_phone text    -- 학생 본인 연락처
);

CREATE TABLE public.weeks (
  id integer PRIMARY KEY,
  class_id integer REFERENCES classes(id),
  test_date text NOT NULL,     -- 예: "2026-08-15"
  label text,
  score_config jsonb,
  item_config jsonb
);

CREATE TABLE public.scores (
  id integer PRIMARY KEY,
  student_id integer REFERENCES students(id),
  week_id integer REFERENCES weeks(id),
  word_score numeric DEFAULT 0,      -- 단어
  reading_score numeric DEFAULT 0,   -- 독해
  mc_score numeric DEFAULT 0,        -- 객관식
  total_score numeric,               -- 총점 (word+reading+mc)
  homework_rate integer DEFAULT 0,   -- 숙제율
  attendance boolean DEFAULT true,   -- 출결
  no_homework boolean DEFAULT false,
  clinic_target boolean DEFAULT false,
  item_scores jsonb
);
```

실습에서 실제로 쓰는 테이블: **classes, students, weeks, scores** 4개.

---

## 4. 만들 것

### 4.1 도구 설계

핵심 도구는 admin-api를 흉내 낸 **범용 조회 도구**다.
단, 발표에서 모델이 뭘 하는지 잘 보이도록 의미 단위로 나눈다.

```python
@tool
def list_classes(grade: str = None, day: str = None) -> str:
    """반 목록을 조회합니다. 학년(grade: 중1/중2/중3)이나 요일(day: 월수/화목/금)로
    필터링할 수 있습니다. 반 id, 이름, 요일, 학년을 반환합니다."""

@tool
def query_scores(class_ids: list[int] = None, date_from: str = None,
                 date_to: str = None, include_absent: bool = True) -> str:
    """주차 시험 점수를 조회합니다. 반 목록, 기간, 결석 포함 여부로 필터링합니다.
    include_absent=False면 결석한 학생을 제외합니다.
    학생별 단어/독해/객관식/총점, 숙제율, 출결을 반환합니다."""

@tool
def aggregate(rows: list, group_by: str, metric: str) -> str:
    """조회된 점수를 그룹별로 집계(평균)합니다.
    group_by: class(반별) | grade(학년별) | day(요일별)
    metric: total | word | reading | mc | homework_rate"""
```

**docstring이 생명이다.** Strands에서 모델은 docstring만 읽고 도구를 고른다.
발표에서 이 점을 강조하므로, 모델이 정확히 고를 수 있게 정성껏 작성할 것.

(선택) admin-api 구조를 그대로 보여주고 싶다면, 범용 `query_table(path)` 버전을
백업으로 만들어두되, 데모 본편은 위 3개로 진행한다.

### 4.2 데모 질문 — "화면에 있는 것" vs "화면에 없는 것" 대비

이 대비가 발표의 증명 구조다. 실습에서 아래 순서로 던진다.

**① 화면으로 이미 만든 질문 (에이전트도 당연히 됨)**
```
"3반이랑 5반, 이번 달 단어 점수 평균 비교해줘"
```
→ list_classes → query_scores → aggregate. "화면에 있던 걸 말로도 할 수 있네"

**② 화면으로 안 만든 변형 질문 (여기가 하이라이트)**
```
"결석 많은 애들 빼고 3반 평균 다시 내줘"
```
→ query_scores(include_absent=False) → aggregate.
→ **이런 화면은 없다. 근데 답이 나온다. 도구 조합이 새로우니까.**

**③ 한 번 더 다른 조합 (코드 안 바뀜을 못박기)**
```
"중2 반들 중에 숙제율 제일 낮은 반이 어디야?"
```
→ list_classes(grade="중2") → query_scores → aggregate(metric="homework_rate")

세 질문의 **툴 호출 순서/인자가 서로 달라야** 데모가 산다.
실행 시 **툴 호출 로그가 터미널에 보기 좋게 출력**되어야 한다. 이게 발표 화면이다.

증명 목표 한 줄: **"질문이 바뀌어도 도구 코드는 한 줄도 안 바뀐다."**

### 4.3 mock 데이터 요건

- 반 6~8개. 학년(중1/중2/중3) × 요일(월수/화목/금)이 골고루 섞이도록
- 반당 학생 8~12명, 가명
- 주차(weeks) 최근 2~3개월치 8~12주
- **반별 점수 차이가 눈에 띄게** (비교 결과가 밋밋하면 데모 실패)
- 결석(attendance=false), 숙제 미제출(no_homework=true) 케이스를 일부 섞을 것
  → 데모 ②("결석 빼고")가 실제로 값이 달라지게 만들어야 함
- 실제 개인정보 절대 금지

---

## 5. 기술 스택

### 실제로 쓰는 것 (2개뿐)

| | 뭔지 | 역할 |
|---|---|---|
| **Strands Agents** | AWS가 만든 오픈소스 SDK (AWS 서비스 아님) | 에이전트 프레임워크. 도구를 접착 |
| **Amazon Bedrock** | Claude 등 LLM을 API로 부르는 AWS 서비스 | 모델(Claude Sonnet) 제공 |

발표에서 실제로 만지는 AWS는 Bedrock **하나**다.

### 추가로 실제 진행할 것 (발표자가 D-2에 시도)

| | 뭔지 | 발표에서 |
|---|---|---|
| **AgentCore Runtime** | 에이전트를 올려 돌리는 관리형 호스팅 | 로컬 에이전트를 여기에 **실제 배포**. 스크린샷 1장 확보 |

→ 마무리에서 "로컬 → 배포까지 해봤다"의 증거로 사용.
→ 배포가 3일 안에 안 되면 마무리를 "배포는 다음 숙제"로 조정 (아래 7절 참고).

### 마무리에서 이름만 언급 (구현 안 함)

```
관측     → CloudWatch GenAI Observability
권한통제  → AgentCore Policy (Cedar)
대량데이터 → Text2SQL (Athena)
```

---

## 5.5 참고 자료와 API 검증 원칙

### 가장 중요한 규칙: 샘플 코드를 그대로 복사하지 말 것

`strands-agents` 1.54.0은 최신이고 내부 구조가 최근 바뀌었다
(`strands/_middleware/registry.py` 미들웨어 계층 도입).
공개 샘플은 대부분 이전 버전 기준이라 특히 Hook/콜백/스트리밍 API가 다를 수 있다.

### API의 절대 기준은 로컬 설치본

코드 짜기 전 **반드시** 아래를 먼저 읽는다:
```
~/miniconda3/lib/python3.13/site-packages/strands/
├── agent/agent.py          # Agent 시그니처
├── tools/                  # @tool 데코레이터
├── models/bedrock.py       # BedrockModel 파라미터
```
샘플과 로컬이 다르면 **무조건 로컬이 맞다.**

### 참고 자료 목록

| # | 자료 | 가져올 것 | 코드 복사 |
|---|---|---|---|
| 1 | `strands-agents/samples` (공식) | `01-learn`의 @tool 관용법 | 검증 후 |
| 2 | `aws-samples/sample-strands-agents-hands-on-workshop` | Module 1 구조 (도구 붙인 에이전트) | 구조만 |
| 3 | `ottlseo/agentcore-multi-agent-workshop-main` | AgentCore Runtime 배포 방식, Text2SQL 패턴 개념 | 배포는 참고, 나머지 ❌ |
| 4 | 공식 문서 strandsagents.com | 개념·용어 | — |

3번은 CDK로 스택 9개를 배포하는 프로덕션 레퍼런스. 규모가 다르므로
AgentCore Runtime 배포 부분만 참고하고, 나머지 코드는 가져오지 않는다.

---

## 6. repo 구조

```
score-agent-demo/
├── README.md              # 실습 참가자용. STEP 0~3
├── requirements.txt       # strands-agents==1.54.0
├── CLAUDE.md              # 이 문서
├── data/
│   ├── seed.py            # mock 데이터 생성 → SQLite
│   └── school.db          # 생성 결과 (gitignore)
├── db.py                  # SQLite 조회 헬퍼
├── tools.py               # @tool 3개
├── agent.py               # 에이전트 정의 + 모델 설정 + 로그 출력
├── demo.py                # 데모 질문 3개 순차 실행
├── deploy/                # (선택) AgentCore Runtime 배포용
└── .env.example           # AWS_REGION 등
```

README STEP 0에 반드시 포함:
```
STEP 0 — 준비물
$ pip install -r requirements.txt
$ aws configure                    # region: us-west-2
$ aws sts get-caller-identity      ← 이게 나와야 준비 완료
```
`aws sts get-caller-identity`를 헬스체크로 쓴다. 실습 시작 전 전원 확인용.

---

## 7. 기술 제약

| 항목 | 값 |
|---|---|
| SDK | `strands-agents` **1.54.0** (requirements.txt에 고정) |
| Python | 3.13 (miniconda) |
| 모델 | Amazon Bedrock 경유 Claude |
| 리전 | `us-west-2` |
| 모델 ID | **코드에 명시적 하드코딩** (기본값 의존 금지) |
| 데이터 | 로컬 SQLite (mock). Supabase 연결 안 함 |

모델은 반드시 명시:
```python
from strands import Agent
from strands.models import BedrockModel

model = BedrockModel(
    model_id="...",        # aws bedrock list-foundation-models로 확인한 실제 ID
    region_name="us-west-2",
)
```

### 하지 말 것

- ❌ 실제 Supabase/admin-api 연결 (mock DB로 대체)
- ❌ 웹 UI (터미널 출력으로 충분)
- ❌ 도구 4개 이상 (3개가 요점)
- ❌ 실패/폭주 재현 데모 (성공만 보여준다)
- ❌ CloudWatch/Policy/Text2SQL 구현 (마무리에서 이름만)

---

## 8. 발표 슬라이드 흐름 (repo가 지원해야 함)

| 파트 | 시간 | 내용 |
|---|---|---|
| 문제 | 0–3분 | 실제 시스템 소개 + admin-api 게이트웨이 구조. 선생님 요청 4개. "요청 올 때마다 화면을 만들었다" |
| 진단 | 3–6분 | 화면은 옳았다. 근데 안 만든 변형 질문엔 답할 방법이 없었다. "path 조립을 사람이 했다" |
| 개념 | 6–9분 | Strands 3요소 + 루프. @tool = 기존 함수를 모델이 부르게. docstring을 모델이 읽는다 |
| **실습** | **9–16분** | 도구 3개 → 질문 ①(화면에 있던 것) → ②③(화면에 없던 변형) → 코드 안 바뀜 |
| 한계 | 16–18분 | 권한 / 비용 / 검증 문제 3개 (해결책 아님, 문제 제시) |
| 마무리 | 18–20분 | "로컬→AgentCore Runtime 배포까지 해봤다"(스크린샷) + 관측/통제/Text2SQL은 다음 숙제 + Q&A |

### 마무리 문구 (배포 성공 시)
> "실습은 로컬까지 보여드렸지만, 저는 AgentCore Runtime 배포까지 해봤습니다. (스크린샷)
> 관측·권한통제·Text2SQL은 다음 숙제로 남겨뒀어요."

### 마무리 문구 (배포 실패 시 — 폴백)
> "실습은 로컬까지입니다. 프로덕션으로 밀면 배포·관측·통제·Text2SQL이 남아 있고,
> 이게 제 다음 숙제입니다."

### 마지막 한 문장 (회고 마무리)
> "3개월간 저는 선생님 말을 코드로 옮기는 번역가였습니다.
> 그 번역을, 이제 에이전트도 합니다."

---

## 9. 작업 순서 요청

0. **API 확인** — 로컬 설치본(`site-packages/strands/`)을 읽고 1.54.0 기준
   `Agent`, `@tool`, `BedrockModel`의 실제 시그니처를 파악. 요약 보고 후 진행.
1. **mock 데이터** (`data/seed.py`, `db.py`) — 스키마대로, 반별 차이 뚜렷하게,
   결석/숙제미제출 케이스 포함. 생성 후 SELECT로 데이터 확인.
2. **도구 3개** (`tools.py`) — docstring 정성껏. 각 도구 단독 실행 테스트.
3. **에이전트** (`agent.py`) — 모델 ID/리전 명시, 툴 호출 로그를 보기 좋게 출력.
4. **데모** (`demo.py`) — 질문 ①②③ 순차 실행.
5. **검증** — 세 질문의 툴 호출 순서/인자가 서로 다른지 확인.
   특히 ②("결석 빼고")가 ①과 값이 실제로 달라지는지 확인.
6. **README** (코드 확정 후) — STEP 0~3.
7. (선택/D-2) **AgentCore Runtime 배포** — 참고 #3의 배포 방식 참고.
   배포 성공 스크린샷 확보. 안 되면 폴백 마무리로.

각 단계 끝나면 실행해서 확인하고 다음으로. 막히면 로컬 설치본을 다시 확인할 것.
