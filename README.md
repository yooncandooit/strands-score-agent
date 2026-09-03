# Strands Agents로 내 서비스에 AI Agent 얹기 — 멀티 에이전트 패턴 3종 비교 실습

#### 목차

- Step 0. [사전 준비](#step-0-사전-준비)
  * [Bedrock 모델 액세스 요청하기](#bedrock-모델-액세스-요청하기)
  * [IAM 사용자 및 액세스 키 생성하기](#iam-사용자-및-액세스-키-생성하기)
- Step 1. [로컬 환경 구성하기](#step-1-로컬-환경-구성하기)
- Step 2. [도구(@tool) 살펴보기](#step-2-도구tool-살펴보기)
- Step 3. [단일 에이전트 실행해보기](#step-3-단일-에이전트-실행해보기)
- Step 4. [멀티 에이전트 패턴 3종 비교하기](#step-4-멀티-에이전트-패턴-3종-비교하기)
  * [Agents-as-Tools — 모델이 순서를 정합니다](#agents-as-tools--모델이-순서를-정합니다)
  * [Graph — 개발자가 순서를 정합니다](#graph--개발자가-순서를-정합니다)
  * [Swarm — 아무도 순서를 정하지 않습니다](#swarm--아무도-순서를-정하지-않습니다)
- Step 5. [AgentCore Runtime에 배포하기](#step-5-agentcore-runtime에-배포하기)
- Step 6. [리소스 정리하기](#step-6-리소스-정리하기)

---

영어 학원의 성적 관리 시스템을 3개월간 외주로 개발했습니다. 학생 약 70명이 실제로 사용하는 서비스입니다. 그런데 선생님의 요청이 올 때마다 화면을 하나씩 늘려야 했고, 요청 하나당 리드타임은 매번 1~3일이었습니다. **요구사항 1개 = view 1개** 구조였기 때문입니다.

이 저장소는 **이미 운영 중인 웹 서비스에 AI Agent를 얹으면 무엇이 달라지는가**를 실습으로 확인하는 코드입니다. 백엔드 코드는 한 줄도 바꾸지 않고, 기존 조회 함수 3개에 `@tool` 데코레이터만 붙였습니다. 그 결과 화면으로 만든 적 없는 질문에도 답할 수 있게 되었습니다.

여기서 한 걸음 더 나아가, *"성적 정리하고, 리포트 만들고, 학부모 문자 초안까지"* 같은 복합 요청을 **여러 에이전트로 나누면 어떻게 되는지** 확인합니다. Strands Agents가 제공하는 멀티 에이전트 패턴 **Agents-as-Tools / Graph / Swarm**을 같은 질문·같은 도구로 각각 실행하고, 실행 시간·토큰·재현성을 실측 비교합니다.

> 본 실습은 AWS Student Builders Group(ASBG) 세션 발표를 위해 작성되었습니다.

## Architecture & Demo

에이전트를 얹기 전과 후의 구조는 다음과 같습니다.

**Before — 요구사항 1개 = view 1개**

```
선생님 ──①요청──> admin.html ──②화면이 조회 조건을 고정──> admin-api ──③──> Supabase
                                                                         (테이블 8개)
새 요청이 오면 → 해석 → 새 화면 추가 → 배포 (리드타임 1~3일)
```

**After — 어떤 도구를 어떤 조건으로 부를지 모델이 결정**

```
선생님 ──①자연어 질문──> Strands Agent ──③도구 호출──> @tool 3개 ──> SQLite
                             │②모델이 결정                (list_classes / query_scores / aggregate)
                             ↕ 추론
                       Amazon Bedrock (Claude Sonnet 4.5)
```

**멀티 에이전트 — Workflow (Graph로 구현)**

```
                    ┌─ AgentCore Runtime ──────────────────────┐
선생님 ──①요청──>   │  score_query Agent   ──> Tool 1/2/3       │──> SQLite
                    │       │②조회 및 도구 활용 결정            │
                    │       │③병렬 분기                        │
                    │  ┌────┴────┐                             │
                    │ report   message ──> save_report/message │──> report.md
                    │  └────┬────┘  (서로 독립 → 동시 실행)     │    message.md
                    │       │④합류                             │
                    │  summary Agent                           │
                    └──────────────────────────────────────────┘
                            ⑤리포트 + 문자 초안
```

## Step 0. 사전 준비

실습 시작 전 아래 두 가지를 **미리** 완료해야 합니다. 특히 모델 액세스 승인은 최대 15분이 소요되므로 실습 전날 완료하시는 것을 권장합니다.

### Bedrock 모델 액세스 요청하기

AWS 콘솔에서 Amazon Bedrock 서비스로 이동합니다. 이때 **리전을 서울(ap-northeast-2)로 설정**해야 합니다.

좌측 사이드바에서 `모델 카탈로그(Model catalog)`를 클릭하고, **Claude Sonnet 4.5** 모델을 선택합니다. 모델 상세 페이지에서 `플레이그라운드에서 열기` 버튼을 클릭하면 Anthropic 사용 사례 제출 양식이 나타납니다.

양식을 아래와 같이 작성하고 제출합니다.

| 항목 | 입력 예시 |
|---|---|
| 회사 이름 | 동국대학교 |
| 회사 웹 사이트 URL | https://www.dongguk.edu/main |
| 대상 사용자 | 내부 직원 |
| 사용 목적 | 외부 사용자를 위한 콘텐츠, 코드 또는 분석 결과 생성 |
| 사용 사례 설명 | AWS Student Builders Group 실습용 |

> Important
>
> 제출 후 승인 메일 수신까지 **최대 약 15분**이 소요됩니다. 승인 전에는 모델 호출 시 `ResourceNotFoundException: Model use case details have not been submitted` 오류가 발생합니다.

### IAM 사용자 및 액세스 키 생성하기

AWS 콘솔에서 IAM 서비스로 이동해 `사용자 생성`을 클릭합니다. 사용자 이름을 입력하고, 권한 옵션에서 `직접 정책 연결`을 선택한 뒤 아래 정책을 연결합니다.

- `AmazonBedrockFullAccess` — 모델 호출용
- `BedrockAgentCoreFullAccess` — AgentCore 배포 및 호출용 (Step 5를 진행하는 경우에만 필요)

> Warning
>
> `AmazonBedrockFullAccess`는 `bedrock:*` 권한만 포함합니다. `bedrock-agentcore:*`는 **별도 서비스 네임스페이스**이므로 포함되지 않습니다. Step 5에서 `agentcore invoke` 실행 시 `is not authorized to perform: bedrock-agentcore:InvokeAgentRuntime` 오류가 발생한다면 `BedrockAgentCoreFullAccess`가 연결되어 있는지 확인하세요.

사용자 생성이 완료되면 해당 사용자를 클릭하고 `보안 자격 증명` 탭 → `액세스 키 만들기`를 선택합니다. 사용 사례로 `Command Line Interface(CLI)`를 선택하고 확인란에 체크한 뒤 액세스 키를 생성합니다.

> Warning
>
> 비밀 액세스 키는 **생성 직후 한 번만** 확인할 수 있습니다. 이 화면을 벗어나면 다시 조회할 수 없으니 안전한 곳에 복사해두세요.

## Step 1. 로컬 환경 구성하기

저장소를 클론하고 필요한 패키지를 설치합니다.

```
$ git clone https://github.com/yooncandooit/strands-score-agent.git
$ cd strands-score-agent

$ pip install -r requirements.txt
```

앞서 발급받은 액세스 키로 AWS CLI를 구성합니다. **리전은 반드시 `ap-northeast-2`로 설정**합니다.

```
$ aws configure
AWS Access Key ID     [None]: AKIA...
AWS Secret Access Key [None]: ...
Default region name   [None]: ap-northeast-2
Default output format [None]: json
```

아래 명령어로 자격증명이 정상적으로 설정되었는지 확인합니다. 이 출력이 나와야 준비가 완료된 것입니다.

```
$ aws sts get-caller-identity
{
    "UserId": "AIDAYIU5MPQZTNY2EUXOV",
    "Account": "568339495987",
    "Arn": "arn:aws:iam::568339495987:user/asbg-0903"
}
```

이어서 사용 가능한 모델이 있는지 확인합니다.

```
$ aws bedrock list-inference-profiles --region ap-northeast-2 \
    --query "inferenceProfileSummaries[?contains(inferenceProfileId,'sonnet-4-5')].inferenceProfileId"
```

> Warning
>
> 서울 리전에는 `apac.` 계열 Sonnet 4.5 추론 프로파일이 없습니다. 본 실습은 `global.` 추론 프로파일을 사용하며, 모델 ID는 `agent.py`에 하드코딩되어 있습니다.
>
> - 기본: `global.anthropic.claude-sonnet-4-5-20250929-v1:0`
> - 폴백: `global.anthropic.claude-haiku-4-5-20251001-v1:0`
>
> 모델을 변경하려면 환경 변수로 덮어쓸 수 있습니다.
> ```
> $ export BEDROCK_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
> ```

마지막으로 실습용 mock 데이터베이스를 생성합니다.

```
$ python data/seed.py
생성 완료: classes=7, students=69, weeks=77, scores=759
3반 중2 월수 11명 전체평균 81.2 출석만 86.1
```

> 실제 Supabase에는 연결하지 않습니다. 운영 중인 시스템과 **동일한 스키마**의 로컬 SQLite mock DB를 생성하며, 학생 이름은 전부 가명입니다.
>
> 출력에서 두 가지를 눈여겨보세요. 첫째, `전체평균`과 `출석만`의 값이 다릅니다. 결석 회차를 0점으로 계산하느냐 제외하느냐의 차이입니다. 둘째, `"3반"`의 id는 3이 아니라 **103**입니다. 실제 운영 DB가 그렇기 때문이며, 그래야 모델이 반 이름에서 id를 추측하지 않고 `list_classes`를 먼저 호출합니다.

## Step 2. 도구(@tool) 살펴보기

`tools.py`에는 함수가 3개 있습니다. 그게 전부입니다.

| 도구 | 역할 |
|---|---|
| `list_classes(grade, day)` | 반 목록 조회. 학년·요일로 필터링 |
| `query_scores(class_ids, date_from, date_to, include_absent)` | 주차 시험 점수 조회 |
| `aggregate(rows, group_by, metric)` | 반별·학년별·요일별 집계 |

에이전트 없이 도구만 직접 호출해볼 수 있습니다. 이 단계는 **AWS 자격증명 없이도 실행 가능**합니다.

```
$ python tools.py
결석 포함 81.6점 / 결석 제외 86.9점
```

같은 반, 같은 기간인데 값이 다릅니다. `include_absent` 불린 하나가 5.3점을 바꿉니다.

여기서 핵심은 **모델이 함수 본문을 보지 못한다**는 점입니다. 모델은 함수 이름, 타입 힌트, 그리고 docstring만 읽고 어떤 도구를 어떤 인자로 호출할지 결정합니다.

```python
@tool
def query_scores(
    class_ids: list[int] = None,
    date_from: str = None,
    date_to: str = None,
    include_absent: bool = True,
) -> str:
    """주차 시험 점수를 조회합니다. 학생 한 명당 한 줄로, 기간 내 성적을 평균 내어 돌려줍니다.

    반 목록(class_ids), 시험 기간(date_from~date_to), 결석 포함 여부로 필터링합니다.
    조회 결과(rows)를 그대로 aggregate 도구에 넘기면 반별/학년별/요일별 집계가 됩니다.
    """
```

> 식당 메뉴판과 같습니다. 손님은 주방을 볼 수 없고, 메뉴 설명만 읽고 주문합니다. 모델도 함수 안을 볼 수 없고, **설명문만 읽고 호출**합니다. 그래서 docstring이 곧 API 명세입니다.

## Step 3. 단일 에이전트 실행해보기

도구 3개를 가진 에이전트에 질문 3개를 순서대로 던집니다.

```
$ python demo.py
```

터미널에 찍히는 툴 호출 로그를 확인하세요. 세 질문의 호출 체인이 서로 다릅니다.

**질문 1 — 화면에 있던 질문**

```
Q: 3반이랑 5반, 이번 달 단어 점수 평균 비교해줘

[1] list_classes
[2] query_scores  class_ids=[103, 105]  date_from="2026-08-01"  date_to="2026-08-31"
[3] aggregate     group_by="class"  metric="word"

답변: 이번 달(8월) 단어 점수 평균은 3반이 24.4점, 5반이 15.9점으로 3반이 8.5점 더 높습니다.
26.2s · 툴 3회 · 토큰 in 30,193 / out 2,482
```

**질문 2 — 화면에 없던 질문**

```
Q: 중2 반들 중에 숙제율 제일 낮은 반이 어디야?

[1] list_classes   grade="중2"
[2] query_scores   class_ids=[103, 104, 105]
[3] aggregate      group_by="class"  metric="homework_rate"

답변: 중2 반들 중에 숙제율이 제일 낮은 반은 4반(화목반)으로 평균 53.0%입니다.
32.3s · 툴 3회 · 토큰 in 113,676 / out 6,011
```

**질문 3 — 화면에 없던 질문**

```
Q: 결석 많은 애들 빼고 3반 평균 다시 내줘

[1] query_scores   class_ids=[103]  date_from="2026-08-01"  date_to="2026-08-31"
                   include_absent=False

답변: 결석 빼고 응시한 회차만으로 다시 계산하니 3반 단어 평균은 26.1점입니다.
      아까 결석을 0점 처리했을 때는 24.4점이었는데, 결석 제외하면 1.7점 올라갑니다.
7.9s · 툴 1회 · 토큰 in 53,426 / out 2,774
```

세 질문을 실행하는 동안 `tools.py`와 `agent.py`는 **한 줄도 수정하지 않았습니다.** 질문 3은 화면으로 만든 적이 없는 조건이지만, docstring에 `include_absent` 설명이 있었기 때문에 자연어가 그대로 인자가 되었습니다.

## Step 4. 멀티 에이전트 패턴 3종 비교하기

*"3반 성적 정리하고, 분석해서 리포트 만들고, 학부모님께 보낼 문자 초안까지 만들어줘"*

이 요청은 조회 하나가 아니라 **조회 + 리포트 작성 + 문자 작성**, 세 가지 일입니다. 단일 에이전트로도 가능하지만 시스템 프롬프트에 조회 규칙·리포트 형식·문자 톤을 전부 넣어야 하고, 하나를 수정하면 나머지가 흔들립니다.

그래서 아래와 같이 3개의 전문 에이전트로 분해했습니다.

| 에이전트 | 역할 | 도구 |
|---|---|---|
| `score_query` | 조회와 집계 담당 | `list_classes`, `query_scores`, `aggregate` |
| `report` | 조회 결과를 마크다운 리포트로 작성 | `save_report` |
| `message` | 200자 이내 학부모 문자 초안 작성 | `save_message` |

`multi.py`는 `--pattern` 플래그로 세 가지 패턴을 각각 실행합니다. `tools.py`와 `db.py`는 그대로 재사용하며, 패턴별로 **에이전트를 묶는 방식만** 다릅니다.

### Agents-as-Tools — 모델이 순서를 정합니다

전문 에이전트를 `@tool`로 감싸고, 오케스트레이터가 docstring을 읽어 필요한 것만 호출합니다.

```
$ python multi.py --pattern tools "3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘"
```

```
orchestrator
  ask_score_query_agent   query="3반 이번 달 성적을 조회해줘"
    └ (score_query) list_classes
    └ (score_query) query_scores  class_ids=[103]  date_from="2026-08-01"  include_absent=True
  ask_report_agent        data="## 3반 이번 달(2026년 8월) 성적 조회 결과 …"
  ask_message_agent       data="## 3반 이번 달(2026년 8월) 성적 조회 결과 …"
    └ (message) save_message   content="안녕하세요, 3반 학부모님. …"
    └ (report)  save_report    content="# 3반 8월 성적 리포트 …"

실행 노드: score_query → report → message
총 소요:   51.9초
토큰:      입력 42,284 / 출력 4,728
호출된 전문 에이전트: 3개 · 순서 결정: 모델
```

이 패턴의 강점은 **질문에 따라 필요한 에이전트만 호출**한다는 점입니다. 같은 코드에 질문만 바꿔보겠습니다.

```
$ python multi.py --pattern tools -q "3반 평균만 알려줘"
```

```
orchestrator
  ask_score_query_agent   query="3반의 평균을 알려줘"
    └ (score_query) list_classes
    └ (score_query) query_scores  class_ids=[103]

실행 노드: score_query
총 소요:   16.0초
토큰:      입력 25,899 / 출력 776
호출된 전문 에이전트: 1개 · 순서 결정: 모델
```

`report`와 `message` 에이전트는 **호출되지 않았습니다.** 코드는 그대로인데 오버헤드가 질문에 따라 줄어듭니다.

### Graph — 개발자가 순서를 정합니다

`GraphBuilder`로 엣지를 직접 그립니다. `score_query`가 끝난 뒤 `report`와 `message`를 병렬로 실행하고, 둘 다 끝나면 `summary`로 합류시킵니다.

```
$ python multi.py --pattern graph
```

```
엣지: score_query → report / score_query → message / report,message → summary

▶ 노드 시작 score_query +0.0s
■ 노드 종료 score_query +27.7s (걸린 시간 27.7s)
▶ 노드 시작 report  +27.7s
▶ 노드 시작 message +27.7s        ← 같은 시각에 시작
■ 노드 종료 message +37.4s (걸린 시간 9.7s)
■ 노드 종료 report  +52.9s (걸린 시간 25.2s)
▶ 노드 시작 summary +52.9s
■ 노드 종료 summary +58.3s (걸린 시간 5.4s)
```

`report`와 `message`가 **같은 타임스탬프에 시작**하는 것을 확인할 수 있습니다. 순차로 실행했다면 27.7 + 9.7 + 25.2 + 5.4 = 68.0초가 걸렸을 작업이 58.3초에 완료되었습니다. **9.7초(약 14%) 단축**입니다.

리포트와 문자 초안은 서로의 결과를 필요로 하지 않기 때문에 병렬화가 가능했습니다.

### Swarm — 아무도 순서를 정하지 않습니다

에이전트끼리 `handoff_to_agent`로 작업을 주고받으며 자율 협업합니다.

```
$ python multi.py --pattern swarm
```

```
▶ 노드 시작 score_query +0.0s
    └ (score_query) handoff_to_agent  agent_name="report"
■ 노드 종료 score_query +25.1s
▶ 노드 시작 report +25.1s
    └ (report) handoff_to_agent  agent_name="message"
■ 노드 종료 report +52.9s
▶ 노드 시작 message +52.9s
■ 노드 종료 message +65.7s

handoff 이력: score_query → report → message  (handoff 2회)
호출된 전문 에이전트: 3개 · 순서 결정: 에이전트 자신
```

> Warning
>
> `summary` 노드는 **끝내 실행되지 않았습니다.** Swarm은 더 느린데(Graph 58.3초 vs Swarm 65.7초) 시킨 일은 덜 했습니다.
>
> 전체 실행 시간은 `score_query` 지연에 좌우되어 노이즈가 큽니다. 패턴 차이만 보려면 조회 이후 구간을 비교해야 하며, 이 수치는 6회 실행에서 일관되게 나타났습니다.
>
> - Graph 후속 구간: 30.6s / 29.9s / 29.1s (report ∥ message 병렬 + summary 실행)
> - Swarm 후속 구간: 38.5s / 36.6s / 40.6s (report → message 순차, summary 미실행)

**검증 중 발견한 함정**

처음에는 Swarm이 `report`를 통째로 건너뛰고 `score_query → message`로 끝났습니다. 원인은 각 `Agent`에 `description=`을 채우지 않은 것이었습니다. Strands의 Swarm은 다른 에이전트를 **이름과 description으로만** 소개하기 때문에, description이 비어 있으면 `Agent name: report.` 만 전달되어 협업 판단 자체가 불가능합니다.

description을 채운 뒤에야 3개 에이전트가 정상적으로 동작했습니다. 자율 협업은 공짜가 아니라, **서로를 설명해줘야 겨우 돌아갑니다.**

### Benchmark Results

동일한 질문, 동일한 도구로 실행한 실측값입니다.

| 패턴 | 시간 | 에이전트 | 순서 결정 | 재현성 | 토큰(입/출) | 이 도메인에서 |
|---|---|---|---|---|---|---|
| Agents-as-Tools | 55.3초 | 3개 | 모델 | 3/3 | 42.5k / 4.9k | 적합 |
| └ "평균만" 변형 | 17.2초 | 1개 | 모델 | 3/3 | 25.9k / 0.8k | 부분 호출 |
| Graph 병렬 | 58.3초 | 4개 | 개발자 | 3/3 | 34.9k / 4.7k | 적합 |
| Swarm | 65.7초 | 3개 (handoff 2회) | 에이전트 | 낮음 | 51.1k / 5.1k | 과잉 |

**측정 환경**

| 항목 | 값 |
|---|---|
| SDK | `strands-agents` 1.54.0 |
| Python | 3.13.5 |
| 모델 | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| 리전 | `ap-northeast-2` |
| 모델 파라미터 | `temperature=0`, `streaming=False` |
| 데이터 | 로컬 SQLite mock, 시험일 범위 2026-06-15 ~ 2026-08-28 |

**패턴 선택 기준**

- **순서를 모르면** — 질문마다 필요한 것이 다르다면 Agents-as-Tools로 모델이 고르게 둡니다.
- **순서를 알면** — 흐름이 정해져 있다면 Graph로 엣지를 그립니다. 독립적인 작업은 병렬로 묶어 시간을 줄일 수 있습니다.
- **자율에 맡기려면** — 순서를 아무도 모를 때만 유효합니다. 이 도메인은 조회 → 정리 → 발송으로 순서가 이미 정해져 있어 Swarm의 이득이 없었습니다.

## Step 5. AgentCore Runtime에 배포하기

로컬에서 실행하던 에이전트를 Amazon Bedrock AgentCore Runtime에 배포합니다.

```
$ npm install -g @aws/agentcore
$ pip install uv

$ cd deploy
$ AWS_REGION=ap-northeast-2 agentcore deploy --yes
```

배포가 완료되면 상태를 확인하고 호출해봅니다.

```
$ agentcore status
Runtime: READY

$ agentcore invoke "중2 반들 중에 숙제율 제일 낮은 반이 어디야?"
{
  "answer": "중2 반들 중 숙제율이 가장 낮은 반은 **4반(화목반)**입니다. 4반의 평균 숙제율은 53.0%로, 1위인 3반(82.0%)보다 29.0%p 낮습니다.",
  "tools_used": [
    "list_classes(grade='중2')",
    "query_scores(class_ids=[103, 104, 105])",
    "aggregate(rows=[28개 항목], group_by='class', metric='homework_rate')"
  ],
  "model": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "region": "ap-northeast-2"
}
```

배포를 위해 새로 작성한 것은 HTTP 엔트리포인트인 `main.py` 하나뿐입니다. `tools.py`와 `db.py`는 수정 없이 그대로 올라갑니다.

```
로컬: 터미널 → agent.py  → tools.py → SQLite
배포: HTTP   → main.py   → tools.py → SQLite
```

> Warning
>
> AgentCore 배포에는 CloudFormation, ECR, IAM PassRole 권한이 추가로 필요합니다. `AmazonBedrockFullAccess`와 `BedrockAgentCoreFullAccess`만 가진 실습용 사용자로는 배포가 제한될 수 있습니다. 이 경우 관리자 권한을 가진 자격증명으로 진행하세요.

## Step 6. 리소스 정리하기

> Important
>
> Step 5(배포)를 진행하지 않았다면 **정리할 AWS 리소스가 없습니다.** 로컬 파일(`data/school.db`, `report.md`, `message.md`)만 생성되며, Amazon Bedrock은 호출한 만큼만 과금됩니다.

배포를 진행했다면 아래 순서로 정리합니다.

```
$ export R=ap-northeast-2

# 1) 스택 이름 확인
$ aws cloudformation list-stacks --region $R \
    --query "StackSummaries[?contains(StackName,'AgentCore') && StackStatus!='DELETE_COMPLETE'].StackName"

# 2) 스택 삭제
$ aws cloudformation delete-stack --stack-name AgentCore-scoreagentdemo-default --region $R

# 3) 삭제 완료까지 대기
$ aws cloudformation wait stack-delete-complete --stack-name AgentCore-scoreagentdemo-default --region $R

# 4) 정리 확인
$ aws bedrock-agentcore-control list-agent-runtimes --region $R
{
    "agentRuntimes": []
}
```

스택을 삭제하면 함께 생성된 ECR 리포지토리와 IAM 실행 역할도 제거됩니다. CloudWatch 로그 그룹(`/aws/bedrock-agentcore/`)이 남아 있다면 콘솔에서 별도로 삭제하세요.

> Warning
>
> 3번 `wait` 단계를 건너뛰고 ECR 리포지토리를 먼저 삭제하면 스택이 `DELETE_FAILED` 상태로 남을 수 있습니다.

---

## Repository Structure

```
strands-score-agent/
├── data/
│   └── seed.py          mock 데이터 생성 (실제 스키마 기반, 가명 처리)
├── db.py                SQLite 조회 헬퍼
├── tools.py             @tool 3개 — list_classes / query_scores / aggregate
├── agent.py             단일 에이전트 정의 (모델 ID·리전 하드코딩)
├── demo.py              질문 3개 순차 실행
├── multi.py             멀티 에이전트 패턴 3종 (--pattern tools|graph|swarm)
├── deploy/
│   └── main.py          AgentCore Runtime용 HTTP 엔트리포인트
└── requirements.txt     strands-agents==1.54.0
```

## References

- [Strands Agents 소개 — AWS 한국 기술 블로그](https://aws.amazon.com/ko/blogs/tech/introducing-strands-agents-an-open-source-ai-agents-sdk/)
- [AgentCore로 포스트잇 워크샵 자료 만들기 — AWS 한국 기술 블로그](https://aws.amazon.com/ko/blogs/tech/agentcore-agent-for-post-it-presentation/)
- [Strands Agents 공식 문서](https://strandsagents.com)
- [strands-agents/samples](https://github.com/strands-agents/samples)
