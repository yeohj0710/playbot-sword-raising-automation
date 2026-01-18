# Auto Enhance Bot (Chat-based)

채팅창에서 `/강화`, `/판매` 명령을 자동으로 입력하고, 강화 결과를 파싱해 **강화/판매를 반복 수행**하는 Python 스크립트입니다.  
강화 결과는 로그로 누적되며, 통계를 `enhance_summary.json`에 저장합니다.

---

## Demo (시연 영상, 사용법)

[![Demo Video](https://img.youtube.com/vi/Y_0OazUQnik/0.jpg)](https://www.youtube.com/watch?v=Y_0OazUQnik)

---

## Features

- `/강화`, `/판매` 자동 입력 (클립보드 붙여넣기 기반)
- 강화 결과 파싱
  - 성공 / 유지(실패) / 파괴 / 대기 / unknown
- 현재 보유 골드 기준으로 목표 확률(`TARGET_PROB`) 이상을 만족하는 **최대 목표 성(`target_y`) 계산**
- 목표 성(`target_y`) 이상이면 `/판매`, 아니면 `/강화`
- 강화 결과가 늦게 오는 경우(대기 메시지 포함) 자동 재대기
- 로그 누적 기록
  - `enhance_log.jsonl` : 이벤트 단위 라인 로그(JSONL)
  - `enhance_summary.json` : 누적 통계(JSON)
- `+20` 도달 시 자동 종료
- 긴급 종료
  - 단축키: `F8`
  - Fail-safe: 마우스를 화면 좌상단으로 이동하면 pyautogui가 즉시 중단

---

## Requirements

- Windows 권장
- Python 3.10+

필요 패키지:

- `pyautogui`
- `pyperclip`
- `keyboard`

---

## Install

```bash
pip install pyautogui pyperclip keyboard
```

---

## Run

```bash
python main.py
```

실행하면 좌표를 3개 받습니다.

1. 채팅 입력칸 좌표
2. 채팅 드래그 시작 좌표
3. 채팅 드래그 종료 좌표

각 단계마다 마우스를 해당 위치에 올려두고 Enter를 누르면 좌표가 저장됩니다.

---

## How it works

1. 채팅을 드래그해서 Ctrl+C로 복사
2. 복사된 텍스트에서 마지막 강화 이벤트를 파싱
3. 현재 골드 기준으로 `TARGET_PROB` 이상으로 “한 번이라도 도달 가능한 최대 목표 성(target_y)” 계산
4. 현재 성 < target_y → `/강화`
5. 현재 성 >= target_y → `/판매`
6. 강화 결과가 나올 때까지 채팅을 폴링하며 대기
7. 로그 기록 + 통계 업데이트
8. +20 도달 시 종료

---

## Configuration

코드 상단의 USER SETTINGS 영역을 수정하면 됩니다.

- `STOP_HOTKEY`: 종료 단축키 (기본 `f8`)
- `TARGET_PROB`: 목표 확률 (기본 `0.95`)
- 입력/드래그/복사 딜레이 관련
  - `CLICK_STABILIZE`
  - `DRAG_DURATION`
  - `WAIT_AFTER_COPY`
  - `PASTE_STABILIZE`
  - `POLL_INTERVAL`
  - `MAX_WAIT_SECONDS`

로그 관련:

- `LOG_PATH` (default: `enhance_log.jsonl`)
- `SUMMARY_PATH` (default: `enhance_summary.json`)
- `FLUSH_EVERY_N` (default: `25`)
- `FLUSH_EVERY_SEC` (default: `10.0`)

---

## Output files

### `enhance_log.jsonl`

이벤트 1개당 JSON 1줄로 기록됩니다.

예시:

```json
{
  "ts": 1730000000.0,
  "type": "enhance",
  "before_level": 11,
  "after_level": 12,
  "event": "success",
  "spent": 30000,
  "gold_before": 12000000,
  "gold_after": 11970000,
  "target_y": 15
}
```

### `enhance_summary.json`

누적 통계를 저장합니다.

- attempts / success / keep / destroy / waiting / unknown
- sells
- spent_gold / earned_gold / net_gold
- success_rate / destroy_rate

---

## Troubleshooting

### 명령어가 텍스트로만 입력되는 경우

- `PASTE_STABILIZE` 값을 올려보세요. (예: `0.07` → `0.10`)
- 채팅창 포커스가 확실히 잡히는지 확인하세요.

### 너무 빠르게 돌아서 오작동하는 경우

- `POLL_INTERVAL`, `WAIT_AFTER_SEND_CMD`, `DRAG_DURATION`을 늘리면 안정성이 올라갑니다.
- 딜레이를 줄이면 속도는 빨라지지만 실패 확률도 올라갑니다.

### 중간에 갑자기 멈추는 경우

- `F8`가 눌렸거나
- 마우스가 좌상단으로 이동해 pyautogui Fail-safe가 발동했거나
- 강화 결과가 늦게 와서 `MAX_WAIT_SECONDS`를 초과했을 가능성이 있습니다.

---

## Disclaimer

이 프로젝트는 개인 자동화 실험 목적의 화면 제어 스크립트입니다.
사용 환경/채팅 UI/게임 규칙에 따라 동작이 달라질 수 있으며, 사용에 따른 책임은 사용자에게 있습니다.
