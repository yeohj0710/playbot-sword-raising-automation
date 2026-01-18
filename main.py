import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import keyboard
import pyautogui
import pyperclip


# =========================
# 0) USER SETTINGS
# =========================
STOP_HOTKEY = "f8"
STOP_KEY_ALT = None

TARGET_PROB = 0.90

TYPE_INTERVAL = 0.02
CLICK_STABILIZE = 0.02
ENTER_GAP = 0.05

WAIT_AFTER_SEND_CMD = 0.03
DRAG_DURATION = 0.20
WAIT_AFTER_COPY = 0.02
PASTE_STABILIZE = 0.07

POLL_INTERVAL = 0.18
MAX_WAIT_SECONDS = 15.0
SELL_MAX_WAIT_SECONDS = 8.0

CMD_ENHANCE = "/강화"
CMD_SELL = "/판매"

pyautogui.FAILSAFE = True


# =========================
# LOGGING (buffered)
# =========================
LOG_PATH = "enhance_log.jsonl"
SUMMARY_PATH = "enhance_summary.json"
FLUSH_EVERY_N = 25
FLUSH_EVERY_SEC = 10.0


# =========================
# 1) 강화 확률 (전체 통합 통계)
# index k = +k -> +(k+1)
# =========================
SUCCESS = [
    1.000, 0.898, 0.803, 0.702, 0.596,
    0.498, 0.455, 0.401, 0.358, 0.296,
    0.256, 0.220, 0.216, 0.195, 0.158,
    0.141, 0.102, 0.083, 0.048, 0.022,
]
DESTROY = [
    0.000, 0.000, 0.000, 0.018, 0.053,
    0.106, 0.098, 0.101, 0.102, 0.095,
    0.104, 0.089, 0.090, 0.097, 0.095,
    0.102, 0.117, 0.098, 0.128, 0.109,
]

COST = [
    10, 20, 50, 100, 200,
    500, 1000, 2000, 5000, 10000,
    20000, 30000, 40000, 50000, 70000,
    100000, 200000, 500000, 1000000, 2000000,
]


# =========================
# 2) 판매가 (관측 + 추정)
# =========================
SELL = [
    0.0, 10.5, 40.0, 117.0, 300.0,
    759.0, 2459.0, 5413.0, 14964.0, 33301.0,
    101061.0, 228825.0, 440403.0, 768998.0, 1_500_000.0,
    3_100_000.0, 7_120_000.0, 19_600_000.0, 53_970_000.0, 148_600_000.0,
    410_000_000.0,
]


def build_sell_prices() -> List[float]:
    return SELL


# =========================
# 3) 확률/비용 유틸
# =========================
def p_success_before_destroy(k: int) -> float:
    t = SUCCESS[k] + DESTROY[k]
    return 0.0 if t <= 0 else SUCCESS[k] / t


def expected_tries_until_end(k: int) -> float:
    t = SUCCESS[k] + DESTROY[k]
    return float("inf") if t <= 0 else 1.0 / t


def precompute_reach_probs_from_0() -> List[float]:
    reach = [1.0] * 21
    for k in range(20):
        reach[k + 1] = reach[k] * p_success_before_destroy(k)
    return reach


def expected_cost_one_run_to_y_from_0(y: int, reach: List[float]) -> float:
    total = 0.0
    for k in range(y):
        total += reach[k] * COST[k] * expected_tries_until_end(k)
    return total


def prob_reach_y_at_least_once_with_budget(budget: int, y: int, reach: List[float]) -> float:
    p = reach[y]
    c = expected_cost_one_run_to_y_from_0(y, reach)
    if c <= 0:
        return 0.0
    n = int(budget // c)
    if n <= 0:
        return 0.0
    return 1.0 - (1.0 - p) ** n


def best_y_by_confidence(budget: int, q: float, reach: List[float]) -> int:
    best = 1
    for y in range(1, 21):
        pr = prob_reach_y_at_least_once_with_budget(budget, y, reach)
        if pr >= q:
            best = y
    return best


# =========================
# 4) 채팅 파싱 + "결과 대기" 판별
# =========================
GOLD_RE = re.compile(r"남은\s*골드:\s*([\d,]+)G")
USED_GOLD_RE = re.compile(r"사용\s*골드:\s*-([\d,]+)G")

LV_RE = re.compile(r"\[\+(\d+)\]")
SUCCESS_ARROW_RE = re.compile(r"\+(\d+)\s*→\s*\+(\d+)")
WAITING_RE = re.compile(r"강화\s*중이니\s*잠깐\s*기다리도록")

EVENT_RE = re.compile(r"(강화\s*성공|강화\s*파괴|강화\s*(유지|실패)|강화\s*중이니\s*잠깐\s*기다리도록)")
CMD_ENHANCE_RE = re.compile(r"/강화")


@dataclass(frozen=True)
class State:
    gold: int
    level: int
    event: str
    used_gold: int = 0


def parse_latest_state(text: str, fallback_level: int = 0) -> Optional[State]:
    last_pos = -1
    for m in EVENT_RE.finditer(text):
        last_pos = m.start()

    chunk = text[last_pos:] if last_pos >= 0 else text

    gm = GOLD_RE.search(chunk)
    if gm:
        gold = int(gm.group(1).replace(",", ""))
    else:
        allg = GOLD_RE.findall(text)
        if not allg:
            return None
        gold = int(allg[-1].replace(",", ""))

    um = USED_GOLD_RE.search(chunk)
    used_gold = int(um.group(1).replace(",", "")) if um else 0

    if WAITING_RE.search(chunk):
        return State(gold=gold, level=fallback_level, event="waiting", used_gold=used_gold)

    if "강화 파괴" in chunk:
        return State(gold=gold, level=0, event="destroy", used_gold=used_gold)

    if "강화 성공" in chunk:
        am = SUCCESS_ARROW_RE.search(chunk)
        if am:
            lvl = int(am.group(2))
            return State(gold=gold, level=lvl, event="success", used_gold=used_gold)

        lm = LV_RE.search(chunk)
        if lm:
            lvl = int(lm.group(1))
            return State(gold=gold, level=lvl, event="success", used_gold=used_gold)

        return State(gold=gold, level=fallback_level, event="success", used_gold=used_gold)

    if "강화 유지" in chunk or "강화 실패" in chunk:
        lm = LV_RE.search(chunk)
        if lm:
            return State(gold=gold, level=int(lm.group(1)), event="keep", used_gold=used_gold)
        return State(gold=gold, level=fallback_level, event="keep", used_gold=used_gold)

    lm = LV_RE.search(chunk)
    if lm:
        return State(gold=gold, level=int(lm.group(1)), event="unknown", used_gold=used_gold)

    return State(gold=gold, level=fallback_level, event="unknown", used_gold=used_gold)


def enhance_result_not_ready(text: str) -> bool:
    all_cmds = list(CMD_ENHANCE_RE.finditer(text))
    if not all_cmds:
        return False

    last_cmd_end = all_cmds[-1].end()
    tail = text[last_cmd_end:]

    return EVENT_RE.search(tail) is None


# =========================
# 5) UI (좌표 3개: input / drag_start / drag_end)
# =========================
@dataclass(frozen=True)
class Coords:
    input_pos: Tuple[int, int]
    drag_start: Tuple[int, int]
    drag_end: Tuple[int, int]


def capture_point(msg: str) -> Tuple[int, int]:
    print(msg)
    input("마우스 올려두고 Enter > ")
    x, y = pyautogui.position()
    print(f"captured: ({x}, {y})\n")
    return (x, y)


def copy_chat(coords: Coords) -> str:
    pyautogui.moveTo(coords.drag_start[0], coords.drag_start[1])
    pyautogui.dragTo(coords.drag_end[0], coords.drag_end[1], duration=DRAG_DURATION, button="left")
    time.sleep(0.01)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(WAIT_AFTER_COPY)
    return pyperclip.paste()


def send_slash_command(cmd: str, coords: Coords):
    pyautogui.click(coords.input_pos[0], coords.input_pos[1])
    time.sleep(CLICK_STABILIZE)

    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("backspace")

    pyperclip.copy(cmd)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(PASTE_STABILIZE)

    pyautogui.press("enter")
    time.sleep(ENTER_GAP)
    pyautogui.press("enter")


# =========================
# 6) Buffered Stats (overall + per_level)
# =========================
@dataclass
class LevelStats:
    attempts: int = 0
    success: int = 0
    keep: int = 0
    destroy: int = 0
    unknown: int = 0
    waiting: int = 0

    spent_gold: int = 0

    sells: int = 0
    earned_gold: int = 0

    def snapshot(self) -> dict:
        attempts = self.attempts
        success_rate = (self.success / attempts) if attempts else 0.0
        destroy_rate = (self.destroy / attempts) if attempts else 0.0
        keep_rate = (self.keep / attempts) if attempts else 0.0
        unknown_rate = (self.unknown / attempts) if attempts else 0.0

        return {
            "attempts": self.attempts,
            "success": self.success,
            "keep": self.keep,
            "destroy": self.destroy,
            "unknown": self.unknown,
            "waiting": self.waiting,
            "spent_gold": self.spent_gold,
            "sells": self.sells,
            "earned_gold": self.earned_gold,
            "net_gold": self.earned_gold - self.spent_gold,
            "success_rate": success_rate,
            "destroy_rate": destroy_rate,
            "keep_rate": keep_rate,
            "unknown_rate": unknown_rate,
        }


@dataclass
class Stats:
    attempts: int = 0
    success: int = 0
    keep: int = 0
    destroy: int = 0
    waiting: int = 0
    unknown: int = 0

    sells: int = 0
    spent_gold: int = 0
    earned_gold: int = 0

    per_level: List[LevelStats] = field(default_factory=lambda: [LevelStats() for _ in range(21)])

    buffer: List[dict] = field(default_factory=list)
    last_flush_ts: float = field(default_factory=lambda: time.time())

    def record(self, row: dict):
        self.buffer.append(row)

    def record_waiting(self, before_level: int):
        self.waiting += 1
        if 0 <= before_level <= 20:
            self.per_level[before_level].waiting += 1

    def record_enhance(self, before_level: int, event: str, spent: int):
        self.attempts += 1
        self.spent_gold += spent

        if 0 <= before_level <= 20:
            lv = self.per_level[before_level]
            lv.attempts += 1
            lv.spent_gold += spent

        if event == "success":
            self.success += 1
            if 0 <= before_level <= 20:
                self.per_level[before_level].success += 1
        elif event == "keep":
            self.keep += 1
            if 0 <= before_level <= 20:
                self.per_level[before_level].keep += 1
        elif event == "destroy":
            self.destroy += 1
            if 0 <= before_level <= 20:
                self.per_level[before_level].destroy += 1
        else:
            self.unknown += 1
            if 0 <= before_level <= 20:
                self.per_level[before_level].unknown += 1

    def record_sell(self, before_level: int, earned: int):
        self.sells += 1
        self.earned_gold += earned

        if 0 <= before_level <= 20:
            lv = self.per_level[before_level]
            lv.sells += 1
            lv.earned_gold += earned

    def snapshot(self) -> dict:
        attempts = self.attempts
        return {
            "overall": {
                "attempts": self.attempts,
                "success": self.success,
                "keep": self.keep,
                "destroy": self.destroy,
                "waiting": self.waiting,
                "unknown": self.unknown,
                "sells": self.sells,
                "spent_gold": self.spent_gold,
                "earned_gold": self.earned_gold,
                "net_gold": self.earned_gold - self.spent_gold,
                "success_rate": (self.success / attempts) if attempts else 0.0,
                "destroy_rate": (self.destroy / attempts) if attempts else 0.0,
            },
            "per_level": {
                str(i): self.per_level[i].snapshot() for i in range(21)
            },
        }

    def maybe_flush(self):
        now = time.time()
        if len(self.buffer) >= FLUSH_EVERY_N or (now - self.last_flush_ts) >= FLUSH_EVERY_SEC:
            self.flush()

    def flush(self):
        if self.buffer:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                for row in self.buffer:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.buffer.clear()

        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            json.dump(self.snapshot(), f, ensure_ascii=False, indent=2)

        self.last_flush_ts = time.time()


# =========================
# 7) Control helpers
# =========================
def should_stop(stop_flag: dict) -> bool:
    if stop_flag.get("stop", False):
        return True
    if STOP_KEY_ALT and keyboard.is_pressed(STOP_KEY_ALT):
        return True
    return False


def wait_for_enhance_outcome(
    coords: Coords,
    stop_flag: dict,
    prev_gold: int,
    prev_level: int,
) -> Optional[State]:
    start = time.time()

    while True:
        if should_stop(stop_flag):
            return None

        txt = copy_chat(coords)

        if enhance_result_not_ready(txt):
            if time.time() - start > MAX_WAIT_SECONDS:
                st = parse_latest_state(txt, fallback_level=prev_level)
                if st is None:
                    time.sleep(POLL_INTERVAL)
                    continue
                return st
            time.sleep(POLL_INTERVAL)
            continue

        st = parse_latest_state(txt, fallback_level=prev_level)
        if st is None:
            time.sleep(POLL_INTERVAL)
            continue

        if st.event != "unknown":
            return st

        if st.gold != prev_gold or st.level != prev_level:
            return st

        if time.time() - start > MAX_WAIT_SECONDS:
            return st

        time.sleep(POLL_INTERVAL)


def wait_for_gold_change(
    coords: Coords,
    stop_flag: dict,
    old_gold: int,
    fallback_level: int = 0,
) -> Optional[int]:
    start = time.time()
    while True:
        if should_stop(stop_flag):
            return None
        txt = copy_chat(coords)
        st = parse_latest_state(txt, fallback_level=fallback_level)
        if st is not None and st.gold != old_gold:
            return st.gold
        if time.time() - start > SELL_MAX_WAIT_SECONDS:
            return old_gold
        time.sleep(POLL_INTERVAL)


# =========================
# 8) MAIN LOOP
# =========================
def main():
    print("=== 자동 입력 ===")
    print(f"- stop: {STOP_HOTKEY}")
    print("- pyautogui fail-safe: 마우스를 화면 좌상단으로 보내면 즉시 중단\n")

    stop_flag = {"stop": False}
    keyboard.add_hotkey(STOP_HOTKEY, lambda: stop_flag.update({"stop": True}))

    coords = Coords(
        input_pos=capture_point("1) 채팅창 입력칸 좌표"),
        drag_start=capture_point("2) 채팅 drag start 좌표"),
        drag_end=capture_point("3) 채팅 drag end 좌표"),
    )

    reach = precompute_reach_probs_from_0()
    _ = build_sell_prices()

    stats = Stats()

    last_level = 0
    last_gold = 0

    print("초기 상태 읽는 중... 채팅에 최근 강화 결과가 보이게 해둬.\n")
    for _ in range(12):
        if should_stop(stop_flag):
            print("STOP")
            return
        txt = copy_chat(coords)
        st = parse_latest_state(txt, fallback_level=0)
        if st is not None:
            last_gold, last_level = st.gold, st.level
            break
        time.sleep(0.25)

    print(f"init: gold={last_gold:,} / level=+{last_level}\n")
    time.sleep(0.3)

    stats.record(
        {
            "ts": time.time(),
            "type": "init",
            "gold": last_gold,
            "level": last_level,
            "target_prob": TARGET_PROB,
        }
    )
    stats.maybe_flush()

    while True:
        if should_stop(stop_flag):
            print("STOP")
            break

        gold_before = last_gold
        level_before = last_level

        if last_level >= 20:
            print("✅ +20 도달! 종료")
            break

        target_y = best_y_by_confidence(last_gold, TARGET_PROB, reach)

        if last_level >= target_y:
            action = "SELL"
            cmd = CMD_SELL
        else:
            action = "ENHANCE"
            cmd = CMD_ENHANCE

        print(f"[gold {last_gold:,}] level +{last_level} / target +{target_y} => {action}")

        send_slash_command(cmd, coords)
        time.sleep(WAIT_AFTER_SEND_CMD)

        if action == "ENHANCE":
            st = wait_for_enhance_outcome(coords, stop_flag, prev_gold=gold_before, prev_level=level_before)
            if st is None:
                print("STOP")
                break

            if st.event == "waiting":
                stats.record_waiting(level_before)
                time.sleep(0.6)
                st = wait_for_enhance_outcome(coords, stop_flag, prev_gold=gold_before, prev_level=level_before)
                if st is None:
                    print("STOP")
                    break

            spent = st.used_gold if st.used_gold > 0 else max(0, gold_before - st.gold)

            stats.record_enhance(level_before, st.event, spent)

            stats.record(
                {
                    "ts": time.time(),
                    "type": "enhance",
                    "before_level": level_before,
                    "after_level": st.level,
                    "event": st.event,
                    "spent": spent,
                    "gold_before": gold_before,
                    "gold_after": st.gold,
                    "target_y": target_y,
                    "used_gold_parsed": st.used_gold,
                }
            )
            stats.maybe_flush()

            last_gold, last_level = st.gold, st.level

            if last_level >= 20:
                print("✅ +20 도달! 종료")
                break

        else:
            new_gold = wait_for_gold_change(coords, stop_flag, old_gold=gold_before, fallback_level=0)
            if new_gold is None:
                print("STOP")
                break

            earned = max(0, new_gold - gold_before)

            stats.record_sell(level_before, earned)
            stats.record(
                {
                    "ts": time.time(),
                    "type": "sell",
                    "before_level": level_before,
                    "gold_before": gold_before,
                    "gold_after": new_gold,
                    "earned": earned,
                    "target_y": target_y,
                }
            )
            stats.maybe_flush()

            last_gold = new_gold
            last_level = 0

        time.sleep(0.03)

    stats.flush()


if __name__ == "__main__":
    try:
        main()
    except pyautogui.FailSafeException:
        print("FAILSAFE: 마우스가 좌상단으로 이동해서 중단됨.")
    except KeyboardInterrupt:
        print("KeyboardInterrupt")
