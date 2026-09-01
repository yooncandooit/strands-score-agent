# multi.py 사양서 — 멀티에이전트 패턴 4종

## 이 문서의 목적

기존 `strands-score-agent` repo에 **`multi.py` 파일 하나만 추가**해서
Strands SDK의 멀티에이전트 패턴 4종을 실행·비교할 수 있게 만든다.

ASBG 동아리 20분 기술 발표의 핸즈온 파트에서 사용한다.

**코드를 짜기 전에 이 문서를 끝까지 읽고, 불명확한 점은 먼저 질문할 것.**

---

## 0. 절대 규칙

### 건드리지 말 것

```
tools.py    ← 손대지 않는다
db.py       ← 손대지 않는다
agent.py    ← 손대지 않는다
demo.py     ← 손대지 않는다
data/       ← 손대지 않는다
```

**"기존 코드 그대로, 묶는 방법만 바꿨다"가 발표의 핵심 메시지다.**
기존 파일을 수정해야만 하는 상황이 생기면, 수정하지 말고 먼저 보고할 것.

새로 만드는 파일은 `multi.py` **하나뿐**이다.

### API 검증 원칙

`strands-agents` 1.54.0은 내부 구조가 최근 바뀌었다.
공개 샘플/워크샵 코드를 **그대로 복사하지 말 것.**

코드 작성 전 반드시 로컬 설치본을 먼저 읽는다:

```
~/miniconda3/lib/python3.13/site-packages/strands/
├── multiagent/          # Swarm, GraphBuilder 실제 시그니처
├── agent/agent.py
├── models/bedrock.py
└── tools/
```

특히 `strands.multiagent`의 `Swarm`, `GraphBuilder` 파라미터명을
**실제 설치본에서 확인**한 뒤 사용할 것. 워크샵 문서와 다르면 로컬이 맞다.

확인 결과를 요약 보고한 뒤 다음 단계로 진행한다.

---

## 1. 기술 제약

| 항목 | 값 |
|---|---|
| SDK | `strands-agents` 1.54.0 |
| Python | 3.13 |
| 리전 | **`ap-northeast-2` (서울)** |
| 모델 ID | **`global.anthropic.claude-sonnet-4-5-20250929-v1:0`** |
| 폴백 모델 | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| 실행 | `python multi.py ...` (uv 아님) |

### 모델 설정 주의

- 서울 리전에는 `us.` / `apac.` 계열 Sonnet 4.5가 **없다.** `global.` 프로파일을 쓴다.
- 워크샵 예제들이 `model="us.anthropic.claude-3-7-sonnet..."`처럼 **문자열을 직접 넘기는데,
  그렇게 하지 말 것.** `BedrockModel` 객체를 만들어 모든 에이전트가 공유한다.
- 모델 ID는 `agent.py`와 동일하게 맞추고, 환경변수 `BEDROCK_MODEL_ID`로 덮어쓸 수 있게 한다.

```python
import os
from strands.models import BedrockModel

MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
model = BedrockModel(model_id=MODEL_ID, region_name="ap-northeast-2")
```

---

## 2. CLI 인터페이스

```bash
python multi.py --pattern tools
python multi.py --pattern graph
python multi.py --pattern route -q "3반 평균 알려줘"
python multi.py --pattern route -q "3반 학부모님께 문자 보내줘"
python multi.py --pattern swarm
```

| 인자 | 설명 | 기본값 |
|---|---|---|
| `--pattern` | `tools` \| `graph` \| `route` \| `swarm` (필수) | — |
| `-q`, `--query` | 사용자 질문 | 패턴별 기본 질문 (아래 4절) |

---

## 3. 도메인 — 3개의 전문 에이전트

기존 `tools.py`의 `@tool` 3개(`list_classes`, `query_scores`, `aggregate`)를
**재료로 삼아** 아래 3개의 전문 에이전트를 정의한다.

### 3.1 score_query_agent — 성적 조회

- **도구**: `list_classes`, `query_scores`, `aggregate` (tools.py에서 import)
- **역할**: 반/기간/항목 조건으로 성적을 조회하고 집계한다
- **시스템 프롬프트 요지**:
  - 반 이름("3반")과 반 id(103)는 다르다. 반드시 `list_classes`로 id를 먼저 확인한다
  - "결석 빼고" 같은 요청은 `include_absent=False`를 쓴다
  - 숫자를 지어내지 않는다. 반드시 도구 결과만 사용한다

### 3.2 report_agent — 반별 리포트 작성

- **도구**: `file_write` (strands_tools)
- **역할**: 전달받은 성적 데이터를 마크다운 리포트로 정리해 `report.md`에 저장
- **시스템 프롬프트 요지**:
  - 반 평균, 상위/하위 학생, 숙제율을 표로 정리
  - 데이터를 새로 조회하지 않는다. 전달받은 내용만 쓴다

### 3.3 message_agent — 학부모 문자 초안

- **도구**: `file_write`
- **역할**: 성적 데이터를 바탕으로 학부모 발송용 문자 **초안**을 작성해 `message.md`에 저장
- **시스템 프롬프트 요지**:
  - 200자 이내, 존댓말, 학부모가 읽는다는 전제
  - **초안만 작성한다. 실제 발송 기능은 없다.** (발표에서 이 점을 강조)
  - 개별 학생 실명을 문자에 넣지 않는다

> `file_write` 사용 시 y/n 확인 프롬프트가 뜨므로
> `os.environ['BYPASS_TOOL_CONSENT'] = 'true'`를 **strands_tools import 전에** 설정한다.

---

## 4. 패턴 4종 구현

### 4.1 `--pattern tools` — Agents-as-Tools

**구조**
```
orchestrator
  ├─ @tool score_query_agent(query)   내부에 Agent
  ├─ @tool report_agent(data)         내부에 Agent
  └─ @tool message_agent(data)        내부에 Agent
```

각 전문 에이전트를 `@tool` 데코레이터로 감싼 함수 안에서 생성·호출한다.
오케스트레이터는 사용자 질문을 보고 **필요한 것만** 고른다.

**기본 질문**
```
3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘
```

**부분 호출 검증용 질문** (발표 STEP 3에서 사용)
```
3반 평균만 알려줘
```
→ `score_query_agent`만 호출되고 `report_agent`, `message_agent`는 **호출되지 않아야 한다.**
이게 이 패턴의 핵심 시연 포인트다.

---

### 4.2 `--pattern graph` — Graph 병렬 실행

**구조**
```
        score_query
        ╱          ╲
   report          message      ← 병렬
        ╲          ╱
         summary
```

`GraphBuilder`로 노드 4개와 엣지를 정의한다.
- entry point: `score_query`
- `score_query → report`, `score_query → message`
- `report → summary`, `message → summary`

`summary` 노드는 두 결과를 합쳐 한 문단으로 정리하는 에이전트다.

**기본 질문**
```
3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘
```

**검증 포인트**: `report`와 `message`가 **동시에** 실행되어
순차 실행보다 총 시간이 짧아야 한다. (아래 6절 참고)

---

### 4.3 `--pattern route` — Graph 조건부 라우팅

**구조**
```
classifier
  ├─(조회)→ score_query_agent      바로 실행
  └─(발송)→ message_agent          승인 게이트 후 실행
```

`classifier` 에이전트는 사용자 요청을 `QUERY` 또는 `SEND` 로만 분류한다.
조건 함수 `is_query(state)`, `is_send(state)`로 엣지에 `condition`을 건다.

**발송 경로에는 사람 확인을 넣는다.**
`message_agent` 실행 전에 터미널에 아래를 출력하고 `input()`으로 y/n을 받는다:

```
⚠️  발송 경로로 분기되었습니다.
    대상: 3반 학부모
    이 실습에서는 실제 발송하지 않고 초안만 만듭니다.
    계속할까요? (y/n)
```

> 이게 학원 도메인의 핵심 논거다. 조회는 되돌릴 수 있지만
> 학부모에게 나간 문자는 되돌릴 수 없다. 발표에서 이 대비를 강조한다.

**검증용 질문 2개**
```
-q "3반 평균 알려줘"              → QUERY 경로
-q "3반 학부모님께 문자 보내줘"     → SEND 경로 (승인 프롬프트 뜸)
```

---

### 4.4 `--pattern swarm` — 비교용 (안 쓰는 이유 보여주기)

**목적이 다르다.** 이 패턴은 "좋다"를 보여주는 게 아니라
**"이 케이스엔 과잉이다"를 실행 결과로 증명**하기 위한 것이다.

`strands.multiagent.Swarm`으로 4개 에이전트를 자율 협업시킨다:
`score_query`, `report`, `message`, `summary`

**⚠️ 타임아웃을 반드시 짧게 잡는다.** 워크샵 기본값(900초)을 그대로 쓰면
발표 중 세션이 멈춘다.

```python
swarm = Swarm(
    [...],
    max_handoffs=6,
    max_iterations=6,
    execution_timeout=90.0,
    node_timeout=30.0,
)
```

타임아웃이 발생해도 **에러로 죽지 말고** 경과 시간과 handoff 이력을 출력한 뒤
정상 종료한다. 타임아웃 자체가 논거가 된다.

**출력에 반드시 포함**: handoff 순서(`node_history`), 총 실행 시간, 토큰 사용량

---

## 5. 출력 포맷

**터미널 출력이 곧 발표 화면이다.** 읽기 쉽게 만드는 게 중요하다.

### 공통 헤더

```
============================================================
 패턴: Agents-as-Tools
 질문: 3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘
============================================================
```

### 에이전트/도구 호출 로그

계층을 들여쓰기로 표현한다.

```
🤖 orchestrator
   🔧 score_query_agent("3반 이번 달 성적")
      └ 🔧 list_classes
      └ 🔧 query_scores  class_ids=[103]  date_from="2026-08-01"
      └ 🔧 aggregate     group_by="class"  metric="total"
      ↩ 평균 81.2점, 응시 11명
   🔧 message_agent("위 결과로 학부모 문자 초안")
      ↩ message.md 저장됨
```

### 공통 푸터 — 반드시 출력

```
------------------------------------------------------------
 실행 노드: score_query → report ∥ message → summary
 총 소요:   6.4초
 토큰:      입력 12,340 / 출력 2,180
------------------------------------------------------------
```

- 실행 시간은 **초 단위 소수점 1자리**로 (ms를 그대로 찍지 말 것)
- Graph 패턴은 병렬 구간을 `∥` 기호로 표시
- 토큰 사용량은 가능한 경우에만 (SDK가 제공하는 필드 확인 후)

### 로그 구현 방법

`agent.py`에 이미 툴 호출 로그 출력이 구현돼 있다.
**같은 방식(hooks)을 재사용**하되, `agent.py`를 수정하지 말고
`multi.py` 안에서 동일한 hook을 새로 정의한다.

`strands.hooks`의 `BeforeToolCallEvent` / `AfterToolCallEvent`를 쓴다.
(1.54.0 기준. `strands.experimental.hooks`는 구버전 경로다.)

---

## 6. 검증 기준 — 이게 통과해야 완성이다

각 항목을 실제로 실행해서 확인하고 결과를 보고할 것.

| # | 검증 | 통과 조건 |
|---|---|---|
| 1 | `--pattern tools` 기본 질문 | 3개 에이전트가 모두 호출됨 |
| 2 | `--pattern tools -q "3반 평균만 알려줘"` | **score_query만** 호출됨 |
| 3 | `--pattern graph` | report와 message가 병렬 실행됨 |
| 4 | **graph가 순차보다 빠른가** | graph 총시간 < (조회+리포트+문자) 합 |
| 5 | `--pattern route -q "3반 평균 알려줘"` | QUERY 경로로 분기 |
| 6 | `--pattern route -q "...문자 보내줘"` | SEND 경로 + 승인 프롬프트 |
| 7 | `--pattern swarm` | 90초 내 종료, handoff 이력 출력 |
| 8 | **swarm이 graph보다 느린가** | swarm 시간 > graph 시간 |
| 9 | 기존 파일 무변경 | `git diff`에 tools.py/db.py/agent.py 없음 |
| 10 | 재현성 | tools/graph/route를 3회씩 돌려 결과 일관성 확인 |

### 4번과 8번이 핵심이다

발표의 논거가 이 두 숫자에 걸려 있다.

- **4번이 실패하면**(병렬 효과가 안 보이면): report/message 에이전트의 작업량이
  너무 적어서 그럴 수 있다. 프롬프트를 조금 더 무겁게 만들어 차이를 드러낼 것.
- **8번이 실패하면**: 그대로 보고할 것. 억지로 맞추지 말고 실제 숫자를 쓴다.

### 10번 재현성

발표에서 라이브로 돌리므로 **매번 같은 툴 체인이 나와야 한다.**
tools/graph/route에서 호출 순서가 흔들리면 시스템 프롬프트를 더 구체적으로 조인다.
(swarm은 원래 비결정적이므로 예외)

---

## 7. 작업 순서

0. **API 확인** — `site-packages/strands/multiagent/`에서
   `Swarm`, `GraphBuilder`의 실제 시그니처 확인 후 요약 보고
1. **뼈대** — argparse, 모델 설정, 공통 출력 함수, hook 로거
2. **전문 에이전트 3종** 정의 (3절)
3. `--pattern tools` 구현 → 검증 1, 2
4. `--pattern graph` 구현 → 검증 3, 4
5. `--pattern route` 구현 → 검증 5, 6
6. `--pattern swarm` 구현 → 검증 7, 8
7. **전체 재현성 테스트** → 검증 9, 10
8. 실행 시간·토큰 실측값을 표로 정리해서 보고 (발표 슬라이드에 들어감)

각 단계마다 실제로 실행해서 확인하고 다음으로 넘어갈 것.

---

## 8. 마지막에 보고할 것

발표 슬라이드에 그대로 들어갈 표다. **실측값**으로 채워서 보고할 것.

```
                  실행시간   호출된 에이전트        순서 결정   재현성
Agents-as-Tools     ?초      ?개                   모델        ?
Graph 병렬          ?초      4개                   개발자      ?
Graph 조건부        ?초      2개                   개발자      ?
Swarm               ?초      ?개 (handoff ?회)     에이전트    낮음
```

그리고 각 패턴의 **툴 호출 로그 원문**을 텍스트로 남겨줄 것.
슬라이드에 붙여넣을 것이다.
