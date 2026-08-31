# 성적 에이전트 실습

> 자주 쓰는 건 화면으로 남기고, 가끔 나오는 변형 요구는 도구로 열어 챗봇이 받게 했다.
> 백엔드는 한 줄도 안 바꾸고.

학원 성적 시스템의 백엔드를 **도구 3개(`@tool`)로 감싸면**, 화면으로 만들지 않은
질문에도 답이 나온다는 걸 직접 확인하는 실습입니다.

증명할 것은 하나입니다. **질문이 바뀌어도 코드는 한 줄도 안 바뀝니다.**

---

## STEP 0 — 준비물

```bash
pip install -r requirements.txt

aws configure                 # region: ap-northeast-2
aws sts get-caller-identity   # ← 이게 나와야 준비 완료
```

`get-caller-identity`가 아래처럼 나오면 통과입니다.

```json
{ "UserId": "...", "Account": "...", "Arn": "arn:aws:iam::...:user/..." }
```

### 모델 액세스 확인

Bedrock은 계정마다 모델 액세스를 따로 켜야 합니다. 아래가 비어 있으면
콘솔 → Bedrock(서울) → **Model access**에서 Anthropic 항목을 활성화하고,
**use case details 양식**까지 제출해야 합니다.

```bash
aws bedrock list-inference-profiles --region ap-northeast-2 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId,'sonnet-4-5')].inferenceProfileId"
```

이 실습이 쓰는 모델은 `agent.py`에 **하드코딩**되어 있습니다.

| | 모델 ID |
|---|---|
| 기본 | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| 폴백(더 싸고 빠름) | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |

> 서울 리전에는 `apac.` 계열 Sonnet 4.5가 없습니다. `global.` 프로파일을 씁니다.

바꿔야 하면 환경변수로만 덮어쓰세요.

```bash
export BEDROCK_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
```

---

## STEP 1 — 데이터 만들기

실제 Supabase에는 붙지 않습니다. 같은 스키마의 **로컬 mock DB**를 만듭니다.
(학생 이름은 전부 가명입니다.)

```bash
python data/seed.py
```

```
생성 완료: classes=7, students=69, weeks=77, scores=759

     반      학년      요일      학생    전체평균     출석만      단어     숙제율      결석     미제출
    1반      중1      월수       9    68.4    76.1    21.1    71.6      10      17
    2반      중1      화목      12    61.6    67.2    18.3    58.3      11      30
    3반      중2      월수      11    81.2    86.1    24.5    82.0       7      12
    4반      중2      화목       8    62.3    65.3    18.8    53.0       4      17
    5반      중2       금       9    52.6    59.1    15.9    64.9      11      21
    6반      중3      월수      10    73.0    81.1    22.1    68.9      11      20
    7반      중3      화목      10    74.3    77.1    22.2    65.0       4      15
```

여기서 눈여겨볼 두 가지:

- **전체평균 vs 출석만** — 결석 회차를 0점으로 세느냐 빼느냐에 따라 값이 다릅니다. STEP 3의 ②번 질문이 이걸 건드립니다.
- **반 id는 반 이름과 다릅니다.** "3반"의 id는 3이 아니라 **103**입니다. 실제 DB가 그렇고, 그래야 모델이 이름에서 id를 추측하지 않고 `list_classes`를 먼저 부릅니다.

---

## STEP 2 — 도구 3개 뜯어보기

`tools.py`에 함수가 3개 있습니다. 그게 전부입니다.

```python
@tool
def list_classes(grade: str = None, day: str = None) -> str: ...

@tool
def query_scores(class_ids: list[int] = None, date_from: str = None,
                 date_to: str = None, include_absent: bool = True) -> str: ...

@tool
def aggregate(rows: list, group_by: str, metric: str) -> str: ...
```

에이전트 없이 사람이 직접 불러볼 수 있습니다.

```bash
python tools.py
```

```
--- query_scores(class_ids=[103], date_from='2026-08-01') 결석 포함 ---
{"student_count": 11, "overall_total_avg": 81.6, ...}

--- 같은 조건, 결석 제외 ---
{"student_count": 11, "overall_total_avg": 86.9, ...}
```

### 여기가 실습의 핵심입니다

**모델은 함수 본문을 보지 못합니다.** 함수 이름, 타입힌트, 그리고 **docstring만** 읽고
"지금 어떤 도구를 어떤 인자로 부를지"를 정합니다.

```python
    include_absent: True(기본)면 결석한 회차도 0점으로 포함해 평균을 냅니다.
        False면 결석한 회차를 아예 빼고 응시한 회차만으로 평균을 냅니다.
        "결석한 애들 빼고", "결석 제외하고 다시" 같은 요청에는 False를 쓰세요.
```

이 세 줄이 있어서 "결석 많은 애들 빼고"라는 말이 `include_absent=False`가 됩니다.
docstring이 곧 API 명세이자 사용설명서입니다.

---

## STEP 3 — 질문 던지기

```bash
python demo.py
```

질문 3개가 순서대로 나갑니다. **터미널에 찍히는 툴 호출 로그를 보세요.**

### ① 화면으로 이미 만들어 둔 질문

```
❓ 3반이랑 5반, 이번 달 단어 점수 평균 비교해줘

  🔧 [1] list_classes
  🔧 [2] query_scores   class_ids=[103, 105]  date_from="2026-08-01"  date_to="2026-08-31"
  🔧 [3] aggregate      group_by="class"  metric="word"

💬 3반 24.4점, 5반 15.9점으로 3반이 8.5점 더 높습니다.
```

화면에 있던 기능입니다. 말로도 되는군요. 여기까진 당연합니다.

### ② 화면으로 **안 만든** 변형 질문 — 여기가 핵심

```
❓ 결석 많은 애들 빼고 3반 평균 다시 내줘

  🔧 [1] query_scores   class_ids=[103]  include_absent=False

💬 결석 제외하면 3반 단어 평균은 26.1점. 아까 24.4점에서 1.7점 올랐습니다.
```

**이런 화면은 없습니다.** 만든 적이 없어요.
그런데 답이 나옵니다. 도구 조합이 새로울 뿐이니까요.

### ③ 또 다른 조합

```
❓ 중2 반들 중에 숙제율 제일 낮은 반이 어디야?

  🔧 [1] list_classes   grade="중2"
  🔧 [2] query_scores   class_ids=[103, 104, 105]
  🔧 [3] aggregate      group_by="class"  metric="homework_rate"

💬 4반(화목반) 53.0%로 가장 낮습니다. 3반 82.0%보다 29.0%p 낮습니다.
```

### 그래서 뭐가 달라졌나

세 질문의 툴 호출 **순서와 인자가 전부 다릅니다.**

| | 툴 체인 | 결정적 인자 |
|---|---|---|
| ① | `list_classes → query_scores → aggregate` | 날짜 범위 + `metric="word"` |
| ② | `query_scores` 하나 | `include_absent=False` |
| ③ | `list_classes → query_scores → aggregate` | `grade="중2"` + `metric="homework_rate"` |

**그리고 이 3개를 돌리는 동안 `tools.py`와 `agent.py`는 단 한 줄도 바뀌지 않았습니다.**

---

## 직접 질문 던져보기

```bash
python agent.py "월수반이랑 화목반, 총점 평균 비교해줘"
python agent.py "숙제 안 하는 애들이 점수도 낮아?"
python agent.py "중3 중에 제일 잘하는 반이 어디야?"
```

특정 질문만 다시 보고 싶으면:

```bash
python demo.py 2      # ②번만
```

---

## (보너스) AgentCore Runtime에 배포하기

실습 본편은 로컬까지입니다. 여기서부터는 "같은 코드를 클라우드에 올리면 어떻게 되나"입니다.

```bash
npm install -g @aws/agentcore     # 공식 CLI (구 bedrock-agentcore-starter-toolkit은 deprecated)
pip install uv

cd deploy
AWS_REGION=ap-northeast-2 agentcore deploy --yes
agentcore status                  # Runtime: READY 확인
agentcore invoke "중2 반들 중에 숙제율 제일 낮은 반이 어디야?"
```

`deploy/app/scoreagent/`에는 **`tools.py`와 `db.py`가 수정 없이 그대로** 들어가 있습니다.
바뀐 건 `main.py` 하나뿐이고, 그것도 하는 일은 "터미널 대신 HTTP로 질문을 받는다"가 전부입니다.

```
로컬:  터미널 → agent.py  → tools.py → SQLite
배포:  HTTP  → main.py   → tools.py → SQLite
                            ^^^^^^^^ 같은 파일
```

연속 대화(“…다시 내줘”)를 보려면 세션을 이어붙입니다.

```bash
agentcore invoke --session-id <앞 호출이 알려준 id> "결석 많은 애들 빼고 3반 평균 다시 내줘"
```

### 정리

`agentcore remove`는 로컬 config만 건드립니다. AWS 자원을 지우려면 CloudFormation 스택을 삭제하세요.

```bash
aws cloudformation delete-stack --stack-name AgentCore-scoreagentdemo-default --region ap-northeast-2
```

## 파일 구조

```
score-agent-demo/
├── data/seed.py    mock 데이터 생성 → SQLite
├── db.py           SQLite 조회 헬퍼 (실제 시스템에선 이 자리가 admin-api 호출)
├── tools.py        @tool 3개 ← 실습의 핵심
├── agent.py        모델·도구·프롬프트를 묶는 곳 + 툴 호출 로그
├── demo.py         질문 3개 순차 실행
└── deploy/         (보너스) AgentCore Runtime 배포용
    └── app/scoreagent/
        ├── main.py     HTTP 껍데기 — 여기만 새로 씀
        ├── tools.py    로컬과 동일 (복사본)
        └── db.py       로컬과 동일 (복사본)
```

## 잘 안 될 때

| 증상 | 원인 / 해결 |
|---|---|
| `school.db 가 없습니다` | `python data/seed.py` 먼저 |
| `Unable to locate credentials` | `aws configure` |
| `Model use case details have not been submitted` | Bedrock 콘솔에서 Anthropic **use case 양식** 제출 후 약 15분 대기 |
| `AccessDeniedException` | 해당 모델 액세스 미승인. Model access에서 켜거나 `BEDROCK_MODEL_ID`를 폴백으로 |
| 응답이 너무 느림 | `export BEDROCK_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0` |
