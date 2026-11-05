"""无显示器自测：判定 / 自动行军 / 四阵 / Boss 四拍破阵 / Fever / 素材。

运行：py -3 prototype-yingge/selftest.py
通过时最后打印 SELFTEST: PASS
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDLAUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import pygame

import core
import pseudo3d as p3d
import render as r
import runner
import runner_model as rm
import scene_ui as sui
import scenes
import telemetry

FAILS: list[str] = []
KEYS_FOR_COMMAND = {cmd[0]: keys for keys, cmd in core.COMMANDS.items()}


def correct_keys(intent_key: str) -> str:
    return KEYS_FOR_COMMAND[core.INTENTS[intent_key]["counter"]]


def wrong_keys(intent_key: str) -> str:
    good = correct_keys(intent_key)
    other = "J" if good[0] != "J" else "L"
    return other * 4


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[ok] {label}{('：' + detail) if detail else ''}")
    else:
        FAILS.append(label + ("：" + detail if detail else ""))
        print(f"[FAIL] {label}{('：' + detail) if detail else ''}")


def beat_sec(g: core.Game) -> float:
    return 60.0 / g.clock.base_bpm


def advance(g: core.Game, t: float, step: float = 0.02) -> None:
    """小步推进，避免一次大 dt 把刚触发的特效全部衰减掉。"""
    t = max(float(t), g.now)
    while g.now < t - 1e-9:
        nxt = min(t, g.now + step)
        g.update(nxt, nxt - g.now)


def press_at(g: core.Game, beat: int, key: str) -> None:
    """按整拍收令（判定偏差 0ms，等价全 Perfect）。"""
    g.beat_press(key, beat * beat_sec(g), 0.0)


def play_cycle(g: core.Game, keys: str, start_beat: int) -> core.GroupResult | None:
    for i, k in enumerate(keys):
        g.beat_press(k, (start_beat + i) * beat_sec(g), 0.0)
    advance(g, (start_beat + core.INPUT_BEATS) * beat_sec(g) + 0.002)
    return g.last_result


def perfect_attempt(cycle: int, intent_key: str,
                    key: str | None = None) -> core.BossAttempt:
    keys = correct_keys(intent_key)
    key = key or keys[0]
    att = core.BossAttempt(cycle=cycle, intent_key=intent_key)
    att.slots = [
        core.Slot(key=key, grade="perfect", dt_ms=0.0, beat=0)
        for _ in range(core.INPUT_BEATS)
    ]
    return att


def make_game(**kw) -> core.Game:
    kw.setdefault("start_time", 0.0)
    return core.Game(**kw)


# ================================================================== 1 判定
def test_judgement() -> None:
    check("判定窗口 ±45/±100/±160ms",
          core.judge_press(44) == "perfect"
          and core.judge_press(46) == "good"
          and core.judge_press(99) == "good"
          and core.judge_press(120) == "miss"
          and core.judge_press(161) is None)
    d = make_game(difficulty="drill")
    check("操练档窗口 ×1.35",
          abs(d.perfect_ms - core.PERFECT_MS * 1.35) < 0.01,
          f"perfect={d.perfect_ms:.1f}ms")
    f = make_game()
    f.fever_active = True
    check("Fever 判定放宽 +20/+30ms",
          abs(f.perfect_ms - 65.0) < 0.01 and abs(f.good_ms - 130.0) < 0.01,
          f"perfect={f.perfect_ms:.0f} / good={f.good_ms:.0f}")


# ================================================================== 2 循环
def test_cycle() -> None:
    g = make_game()
    for i in range(4):
        press_at(g, i, "J")
    advance(g, 4 * beat_sec(g) + 0.002)
    r = g.last_result
    check("8 拍循环：前 4 拍收令，第 5 拍起手",
          r is not None and r.success and r.command == "attack",
          f"keys={r.keys if r else '-'} grade={r.grade if r else '-'}")
    check("起手落在重拍（≠输入拍）", g.stats["commands_ok"] == 1)
    # 动作拍收踏点，不组令
    got = g.beat_press("K", 5 * beat_sec(g), 0.0)
    check("动作拍只收踏点，不污染指令",
          got is not None and got[0].slot == -1 and len(g.cycle_slots) == 4)
    # 单拍空槽 + 第 4 拍未收满 → 漏拍
    g2 = make_game()
    press_at(g2, 0, "J")
    advance(g2, 4 * beat_sec(g2) + 0.002)
    check("漏拍判定", g2.last_result is not None
          and g2.last_result.reason == "漏拍" and g2.combo == 0)


# ================================================================== 3 自动行军
def test_auto_march() -> None:
    g = make_game()
    for n in range(8):
        g.beat_press("J" if n < 4 else "K", n * beat_sec(g), 0.0)
        advance(g, n * beat_sec(g) + 0.03)
    check("自动行军：保持合拍就前压",
          g.squad.x > 1.2 and g.squad.walking and g.stats["auto_march"] >= 5,
          f"x={g.squad.x:.2f} streak={g.squad.march_streak} "
          f"auto={g.stats['auto_march']}")
    h = make_game()
    advance(h, 2.2 * beat_sec(h))
    check("停止/待机：脱拍即停步扬尘",
          not h.squad.walking and h.squad.stance == "halt", h.squad.stance)
    # 四种阵法的行军倍率：双龙 > 长蛇 > 龟甲 > 猛虎
    dists = {}
    for form in ("shuanglong", "changshe", "guijia", "menghu"):
        x = make_game()
        x.formation = form
        for n in range(4):
            x.beat_press("K", n * beat_sec(x), 0.0)
            advance(x, n * beat_sec(x) + 0.03)
        dists[form] = x.squad.x
    check("阵法行军倍率 双龙>长蛇>龟甲>猛虎",
          dists["shuanglong"] > dists["changshe"]
          > dists["guijia"] > dists["menghu"],
          " ".join(f"{k}={v:.2f}" for k, v in dists.items()))


# ================================================================== 4 三兵种 / 四阵
def test_squad_and_formations() -> None:
    g = make_game(spawn_boss=False)
    g.enemies = [core.Enemy("grunt", 2.0, 0)]
    play_cycle(g, "JJJJ", 0)
    grunt = g.enemies[0]
    dealt = 56.0 - grunt.hp
    check("三兵种盾/鼓/矛齐击", dealt >= 51.0 and g.stats["damage_dealt"] > 50,
          f"伤害={dealt:.1f}")

    dmgs = {}
    for form in ("changshe", "fengshi", "guijia", "shuanglong", "menghu"):
        g = make_game(spawn_boss=False)
        g.formation = form
        g.enemies = [core.Enemy("brute", 2.5, 0)]
        play_cycle(g, "JJJJ", 0)
        dmgs[form] = 96.0 - g.enemies[0].hp
    check("四阵攻击倍率（猛虎>锋矢>双龙>长蛇>龟甲）",
          dmgs["menghu"] > dmgs["fengshi"] > dmgs["shuanglong"]
          > dmgs["changshe"] > dmgs["guijia"],
          " ".join(f"{k}={v:.1f}" for k, v in dmgs.items()))
    g = make_game(spawn_boss=False)
    g.formation = "menghu"
    play_cycle(g, "JJJJ", 0)
    check("猛虎代价：攻击后硬直 + 减伤 -30%",
          g.stunned and g.formation_spec["dr"] < 0 and g.stun_until > g.now,
          f"stun={g.stun_until - g.now:.1f}s")
    # 阵法克制表：龟甲克 AOE、锋矢克抓取、双龙克冲锋
    check("四阵克制表（龟甲→AOE，锋矢→抓取，双龙→冲锋）",
          "sweep" in core.FORMATION_COUNTERS["guijia"]
          and "grab" in core.FORMATION_COUNTERS["fengshi"]
          and "charge" in core.FORMATION_COUNTERS["shuanglong"])


# ================================================================== 5 Boss 破阵
def boss_game(seed: int = 20261104) -> core.Game:
    g = make_game(seed=seed)
    g.phase = "boss"
    g.boss.active = True
    g.boss.dead = False
    g.boss.hp = g.boss.max_hp = g.diff["boss_hp"]
    g.boss.x = 9.0
    for e in g.enemies:
        e.dead = True
    g.enemies.clear()
    g.score = core.BossScore(seed)
    g.intent_cycle = -1
    advance(g, 3.95 * beat_sec(g))
    return g


def test_boss() -> None:
    g = boss_game()
    keys = correct_keys(g.intent_key or "")
    check("Boss 抬手在重拍前公示",
          g.attempt is not None and g.intent_variant == "phase_open",
          f"intent={g.intent_key} variant={g.intent_variant}")
    for i in range(4):
        press_at(g, 4 + i, keys[i])
    check("4 拍化解成功、0 伤",
          g.stats["intents_read"] >= 1 and g.stats["intents_hit"] == 0,
          f"reads={g.stats['intents_read']} hp={g.squad.hp:.0f}")

    # 全 Perfect → 极限破阵
    g2 = boss_game()
    keys2 = correct_keys(g2.intent_key or "")
    for i in range(4):
        press_at(g2, 4 + i, keys2[i])
    check("全 Perfect 触发极限破阵硬直",
          g2.boss_staggered and g2.stagger_until - g2.now >= 1.5
          and g2.stats["boss_perfect_breaks"] == 1,
          f"硬直={g2.stagger_until - g2.now:.2f}s")
    check("破阵同时获得 Fever 充能",
          g2.fever_active and g2.fever_gauge >= g2.diff["fever_gauge"],
          f"fever={g2.fever_active} gauge={g2.fever_gauge}")
    hp_before = g2.boss.hp
    advance(g2, g2.now + 1.4)
    check("硬直期自由输出（踏点自动追打）",
          g2.boss.hp < hp_before - 30,
          f"boss {hp_before:.0f}→{g2.boss.hp:.0f}")

    # 超时
    g3 = boss_game()
    g3.guidance = False        # 关闭教学招，验证原始全额伤害
    advance(g3, 6.0 * beat_sec(g3))
    check("4 拍窗口超时 → 全额伤害",
          g3.stats["intents_hit"] >= 1 and g3.squad.hp < 110,
          f"hit={g3.stats['intents_hit']} hp={g3.squad.hp:.1f}")

    # 错令
    g4 = boss_game()
    g4.guidance = False
    bad = wrong_keys(g4.intent_key or "")
    for i in range(4):
        press_at(g4, 4 + i, bad[i])
    check("错令 → 全额伤害",
          g4.stats["intents_hit"] >= 1 and g4.squad.hp < 110,
          f"hit={g4.stats['intents_hit']} hp={g4.squad.hp:.1f}")

    # 三类招式各有固定拍位与对应指令
    kinds = {k: v["kind"] for k, v in core.INTENTS.items()}
    check("三类以上招式：AOE/单体/抓取",
          set(kinds.values()) >= {"aoe", "heavy", "grab"},
          ",".join(f"{k}:{v}" for k, v in kinds.items()))


# ================================================================== 6 鼓劲槽 / Fever
def test_fever() -> None:
    g = make_game()
    for _ in range(g.diff["fever_gauge"] // 2):
        g._add_gauge(2)
    check("鼓劲槽满自动进入 Fever",
          g.fever_active and g.fever_until > g.now,
          f"gauge={g.fever_gauge} 持续={g.fever_until - g.now:.1f}s")
    check("Fever 极板提速（≤150 BPM）",
          g.clock.target_bpm(True) <= core.FEVER_BPM_CEIL
          and g.clock.target_bpm(True) > g.clock.base_bpm,
          f"{g.clock.base_bpm:.0f}→{g.clock.target_bpm(True):.0f}")

    # 双倍伤害：只留盾兵，排除矛兵穿甲/鼓手双击的额外加成
    def hit_once(fever: bool) -> float:
        x = make_game(spawn_boss=False)
        x.squad.units = [core.Unit("shield")]
        x.enemies = [core.Enemy("brute", 2.5, 0)]
        if fever:
            x.fever_active = True
            x.fever_until = 99.0
        play_cycle(x, "JJJJ", 0)
        return 96.0 - x.enemies[0].hp
    a, b = hit_once(False), hit_once(True)
    check("Fever 伤害 ×2", abs(b / a - 2.0) < 0.02, f"{a:.1f}→{b:.1f}")

    # 超时退出与冷却
    g.fever_until = g.now + 0.2
    advance(g, g.now + 0.4)
    check("Fever 超时退出、槽清零并冷却",
          not g.fever_active and g.fever_gauge == 0
          and g.fever_cd_until > g.now,
          f"冷却={g.fever_cd_until - g.now:.1f}s")
    before = g.fever_gauge
    g._add_gauge(2)
    check("冷却期不积攒鼓劲", g.fever_gauge == before)

    # 断档退出
    h = make_game()
    h.fever_active = True
    h.fever_until = h.now + 5
    h._on_fail(core.GroupResult(0, "JJJ·", None, None, False, "漏拍"))
    check("断档立即退出 Fever", not h.fever_active and h.fever_gauge == 0)

    # Fever 中再破阵叠加奖励
    k = boss_game()
    kkeys = correct_keys(k.intent_key or "")
    for i in range(4):
        press_at(k, 4 + i, kkeys[i])
    k.fever_until = k.now + 1.0
    att = perfect_attempt(k.cycle_index, k.intent_key or "")
    k._resolve_attempt(att, early=True)
    check("Fever 中再破阵 → 时长叠加", k.fever_until > k.now + 2.5,
          f"剩余={k.fever_until - k.now:.1f}s")


# ================================================================== 6.5 Boss 权重谱
def test_boss_score() -> None:
    path = os.path.join(ROOT, "config", "boss_score.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    pools = {p["id"]: p["pool"] for p in cfg["phases"]}
    check("谱面 JSON：3 阶段、权重与内置表一致",
          len(cfg["phases"]) == 3
          and pools[1] == {"slam": 30, "sweep": 18, "grab": 34, "roar": 18}
          and pools[2]["charge"] == 26 and pools[3]["charge"] == 30)
    check("开战前 2 拍不出招",
          core.BossScore(7).pick(0, 1.0) is None,
          "grace=2")

    sc = core.BossScore(7)
    p1 = sc.pick(4, 1.0)
    p2 = sc.pick(12, 0.65)
    p3 = sc.pick(20, 0.32)
    check("阶段按血量切换 100-66 / 65-33 / 32-0",
          p1.phase == 1 and p2.phase == 2 and p3.phase == 3,
          f"{p1.phase}/{p2.phase}/{p3.phase}")
    check("进入新阶段首招是可化解的公示招，公示 ≥4 拍",
          p2.variant == "phase_open" and p3.variant == "phase_open"
          and p2.intent in cfg["phases"][1]["open_pool"]
          and p3.intent in cfg["phases"][2]["open_pool"]
          and p2.reveal_beats >= 4 and p3.reveal_beats >= 4,
          f"{p2.intent}/{p3.intent} reveal={p2.reveal_beats}/{p3.reveal_beats}")

    def sequence(seed: int) -> list[tuple[int, str]]:
        s = core.BossScore(seed)
        out = []
        for i in range(30):
            beat = 4 + i * 8
            ratio = 1.0 if i < 10 else (0.5 if i < 20 else 0.2)
            p = s.pick(beat, ratio)
            out.append((beat, p.intent))
        return out

    check("同 seed 谱面可复现", sequence(99) == sequence(99))
    seq = sequence(13)
    triple = [seq[i:i + 3] for i in range(len(seq) - 2)
              if len({x[1] for x in seq[i:i + 3]}) == 1]
    check("同一招式不得三连", not triple, str(triple[:2]))
    aoe_beats = [b for b, k in seq if k in core.AOE_INTENTS]
    gaps = [b - a for a, b in zip(aoe_beats, aoe_beats[1:])]
    check("AOE 同阶段间隔 ≥6 拍", all(g >= 6 for g in gaps),
          f"gaps={gaps[:6]}")

    s2 = core.BossScore(21)
    longs = []
    prev = None
    for i in range(60):
        p = s2.pick(4 + i * 8, 1.0)
        kind = core.INTENTS[p.intent]["kind"]
        if prev is not None and kind == prev[0] and p.variant != "phase_open":
            longs.append((p.intent, p.variant, p.windup))
        prev = (kind, p.intent)
    check("连续同类型第二招带长蓄差异",
          bool(longs) and all(v == "long" and w >= 0.5 for _, v, w in longs),
          str(longs[:3]))

    for phase in cfg["phases"]:
        s = core.BossScore(5)
        n = 4000
        counts = {k: 0 for k in phase["pool"]}
        for _ in range(n):
            counts[s._weighted(phase["pool"])] += 1
        total = sum(phase["pool"].values())
        ok = all(abs(counts[k] / n - w / total) <= 0.035
                 for k, w in phase["pool"].items())
        check(f"阶段{phase['id']}权重分布", ok,
              " ".join(f"{k}={counts[k] / n:.3f}" for k in counts))


# ================================================================== 6.6 克制矩阵
def test_counter_matrix() -> None:
    path = os.path.join(ROOT, "config", "counter_matrix.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    m = data["matrix"]
    check("克制矩阵 5 阵 × 5 招",
          len(m) == 5 and all(len(row) >= 4 for row in m.values())
          and all(set(row) == set(core.INTENT_ORDER) for row in m.values()),
          f"{len(m)}x{len(next(iter(m.values())))}")
    check("矩阵与 core 常量一致（集中到 JSON）",
          core.COUNTER_MATRIX == m)
    check("破绽增益选伤害倍率",
          data.get("bonus_kind") == "damage_multiplier")

    every_ok = True
    for form, row in m.items():
        for key, val in row.items():
            if abs(core.COUNTER_MATRIX[form][key] - float(val)) > 1e-9:
                every_ok = False
    check("每个组合的配置倍率一致", every_ok)
    check("每阵都有克制与被克",
          all(any(v > 1 for v in row.values())
              and any(v < 1 for v in row.values()) for row in m.values()))

    def dmg(form: str, intent: str | None) -> float:
        g = make_game()
        g.start_boss_fight(squad_x=6.0, boss_x=8.4)
        g.formation = form
        g.intent_key = intent
        g.boss.hp = g.boss.max_hp
        g.stats["damage_dealt"] = 0.0
        r = core.GroupResult(0, "JJJJ", "attack", "perfect", True, "")
        g._do_attack(r)
        return g.stats["damage_dealt"]

    ratios = {}
    for form, row in m.items():
        base = dmg(form, None)
        for key, val in row.items():
            got = dmg(form, key)
            ratio = got / base if base else 0.0
            if abs(ratio - float(val)) > 0.02:
                ratios[f"{form}/{key}"] = (round(ratio, 3), val)
    check("实际伤害倍率与矩阵逐格一致", not ratios, str(ratios))

    g = make_game()
    g.start_boss_fight(squad_x=6.0, boss_x=8.4)
    g.formation = "guijia"
    g.intent_key = "sweep"
    g.boss.hp = g.boss.max_hp
    r = core.GroupResult(0, "JJJJ", "attack", "perfect", True, "")
    g._do_attack(r)
    check("克制命中打出「克」字印",
          g.counter_pop[0] == "克" and g.stats["counter_hits"] == 1,
          f"pop={g.counter_pop[0]} mult={g.counter_mult():.2f}")
    h = make_game()
    h.start_boss_fight(squad_x=6.0, boss_x=8.4)
    h.formation = "fengshi"
    h.intent_key = "sweep"
    h.boss.hp = h.boss.max_hp
    h._do_attack(r)
    check("被克命中可见提示、但不罚站",
          h.counter_pop[0] == "被克" and h.stats["countered_hits"] == 1
          and not h.stunned,
          f"pop={h.counter_pop[0]} mult={h.counter_mult():.2f}")


# ================================================================== 6.7 阶段集成 / 遥测
def test_phase_and_telemetry() -> None:
    g = boss_game()
    g.boss.hp = g.boss.max_hp * 0.64
    advance(g, 11.95 * beat_sec(g))
    check("Boss 战集成：越 66% 后首招走新阶段公示",
          g.boss_phase == 2 and g.intent_variant == "phase_open"
          and any(ev[0] == "boss_phase" for ev in g.events),
          f"phase={g.boss_phase} variant={g.intent_variant}")

    t = boss_game()
    tkeys = correct_keys(t.intent_key or "")
    for i in range(4):
        press_at(t, 4 + i, tkeys[i])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "telemetry.csv")
        rec = telemetry.RunRecorder(path=path, hand="selftest",
                                    seed=t.seed, difficulty=t.difficulty)
        row = rec.finish(t, "test")
        with open(path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        check("遥测 CSV 落盘且含判定分布/破阵/胜败",
              row is not None and len(rows) == 1
              and rows[0]["perfect"] == "4"
              and rows[0]["break_success"] == "1"
              and rows[0]["win"] == "0"
              and "avg_offset_ms" in rows[0],
              f"{list(rows[0].keys())[:8]}")


# ================================================================== 7 反馈 / 死亡 / 重开
def test_feedback_and_reset() -> None:
    g = make_game(spawn_boss=False)
    g.enemies = [core.Enemy("grunt", 2.0, 0)]
    play_cycle(g, "JJJJ", 0)
    check("Perfect 顿帧/震屏/火花/吼",
          g.hitstop > 0 and g.shake.trauma > 0 and g.sparks.count() > 10
          and g.shout_t > 0, f"sparks={g.sparks.count()}")
    h = make_game(spawn_boss=False)
    play_cycle(h, "JJKJ", 0)
    check("错令仅乱阵：断连、抖屏、无顿帧",
          h.combo == 0 and h.shake.trauma > 0 and h.hitstop == 0,
          h.last_result.reason if h.last_result else "无结算")

    d = make_game()
    for u in d.squad.units:
        u.hp = 0
        u.down = True
    advance(d, 0.2)
    check("三兵全灭 → 全军覆灭", d.status == "defeated")
    d.reset(10.0)
    check("R 重开：满血、长蛇、Boss 复位",
          d.status == "playing" and d.squad.hp == d.squad.max_hp
          and d.formation == "changshe" and not d.boss_active
          and d.fever_active is False and d.combo == 0, f"x={d.squad.x:.1f}")


# ================================================================== 8 坡面
def test_terrain() -> None:
    xs = [i * 8.0 for i in range(0, 161)]     # 0–1280 全屏
    ys = [core.ground_screen_y(x) for x in xs]
    check("坡度 = 10°", abs(core.TERRAIN["slope_deg"] - 10.0) < 1e-6
          and abs(core.SLOPE - __import__("math").tan(
              __import__("math").radians(10.0))) < 1e-9,
          f"slope={core.SLOPE:.4f}")
    check("坡面基线任意 x 不悬空/不穿地",
          0.0 <= min(ys) and max(ys) <= 720.0,
          f"y=[{min(ys):.0f},{max(ys):.0f}]")

    # 阵型槽位：全部落在三棱柱顶面的 (u,v) 范围内
    ok = True
    detail = ""
    for form, slots in core.FORMATION_SLOTS.items():
        for du, dv in slots:
            if not (p3d.V_NEAR <= dv <= p3d.V_FAR):
                ok = False
                detail = f"{form} v={dv}"
            px, py = p3d.world_to_screen(5.0 + du, dv, 5.0, 0.0)
            if not (0 <= py <= 720):
                ok = False
                detail = f"{form} py={py}"
    check("阵型槽位落在斜面上、无悬空穿地", ok, detail)

    g = make_game()
    down = core.slope_march_factor(1, 4)
    up = core.slope_march_factor(-1, 4)
    check("下坡加速、上坡减速（1.35 倍代价）",
          down > 1.2 and up < 0.8 and abs(1.0 / up - 1.35) < 1e-6,
          f"下坡×{down:.2f} 上坡×{up:.2f}")
    # 加速度：首拍加成 < 连拍加成
    check("起步前倾加速（首拍只吃 40%）",
          core.slope_march_factor(1, 1) < core.slope_march_factor(1, 5),
          f"{core.slope_march_factor(1, 1):.3f} → "
          f"{core.slope_march_factor(1, 5):.3f}")

    base = min(core.AUTO_MARCH["step"], core.AUTO_MARCH["max_step"])
    d_dist = base * core.slope_march_factor(1, 4)
    u_dist = base * core.slope_march_factor(-1, 4)
    check("坡度改变实际行军距离（下坡 > 上坡）", d_dist > u_dist,
          f"{d_dist:.2f} vs {u_dist:.2f} 世界单位/拍")

    # 击退：下坡更远、上坡更短（含队伍回撤实测）
    check("击退距离随坡向变化",
          core.slope_knock_distance(1.0, 1) >
          core.slope_knock_distance(1.0, -1),
          f"下坡 {core.slope_knock_distance(1.0, 1):.2f} / "
          f"上坡 {core.slope_knock_distance(1.0, -1):.2f}")
    g.squad.x = 5.0
    before = g.squad.x
    g._march_forward(core.slope_knock_distance(0.55, -1.0), -1.0)
    check("上坡击退更短（队伍仅回撤约 0.37）",
          abs((before - g.squad.x) - 0.55 / 1.50) < 0.02,
          f"回撤 {before - g.squad.x:.2f}")


# ================================================================== 8.4 伪 3D 投影
def test_pseudo3d() -> None:
    # 1) 投影正反算：世界→屏幕→世界→屏幕，像素误差必须为 0
    #    只在有效地面域内取点；屏幕地平线以上不属于地面，反算会失义。
    err = 0
    points = 0
    for cam in (-2.0, 0.0, 4.2, 8.0):
        for i in range(16):
            u = cam - 8.0 + i
            for j in range(13):
                v = p3d.V_NEAR + (p3d.V_FAR - p3d.V_NEAR) * j / 12.0
                sx, sy = p3d.world_to_screen(u, v, cam, 0.0)
                err = max(err, p3d.roundtrip_px(sx, sy, cam, 0.0))
                points += 1
    for u in (-6.0, -1.35, 0.0, 2.5, 9.75):
        for v in (-5.0, 0.0, 3.25):
            for cam in (0.0, 4.2):
                sx, sy = p3d.world_to_screen(u, v, cam)
                err = max(err, p3d.roundtrip_px(sx, sy, cam))
    check("(u,v)→屏幕→(u,v) 往返像素误差为 0",
          err == 0 and points >= 200, f"{points} 点 max={err}px")

    # 2) 深度排序：v 从远到近；同 v 按 u 升序（稳定画家算法）
    items = [(0.0, -4.0), (1.2, -1.0), (3.0, 0.0),
             (2.0, 2.0), (0.4, 4.0), (2.2, -1.0)]
    got = p3d.depth_sorted(items)
    want = [(0.4, 4.0), (2.0, 2.0), (3.0, 0.0),
            (1.2, -1.0), (2.2, -1.0), (0.0, -4.0)]
    check("深度排序严格按 v 远→近、同 v 按 u 升序", got == want, str(got))

    # 3) 遮挡：至少 3 组近排后画且与远排包围盒相交
    pairs = 0
    detail = ""
    for ux in (-2.0, 1.5, 5.0):
        far, near = (ux, -1.0), (ux, -1.8)
        fx, fy = p3d.world_to_screen(*far, 0.0, 0.0)
        nx, ny = p3d.world_to_screen(*near, 0.0, 0.0)
        order = p3d.depth_sorted([(ux, -1.0, "far"), (ux, -1.8, "near")],
                                 v_of=lambda a: a[1], u_of=lambda a: a[0])
        if (p3d.rect_overlap(p3d.footprint_rect(fx, fy, 64, 96),
                             p3d.footprint_rect(nx, ny, 64, 96))
                and order[-1][2] == "near"):
            pairs += 1
        else:
            detail = f"u={ux} far=({fx},{fy}) near=({nx},{ny})"
    check("遮挡对 ≥3 组：近排后画且包围盒相交", pairs >= 3, detail)

    # 4) 阴影：所有锚点共用同一左下向量
    ref = None
    ok = True
    for sx, sy in ((120, 400), (400, 260), (800, 380), (520, 480)):
        pts = p3d.shadow_points(sx, sy)
        off = (sum(p[0] for p in pts) / 4.0 - sx,
               sum(p[1] for p in pts) / 4.0 - sy)
        if ref is None:
            ref = off
        elif abs(off[0] - ref[0]) > 0.51 or abs(off[1] - ref[1]) > 0.51:
            ok = False
    check("阴影方向统一指向左下", ok and ref[0] < 0 and ref[1] > 0, str(ref))

    # 5) 五阵槽位：不重叠、落在棱柱顶面；前后排差异
    ok = True
    detail = ""
    for form, slots in core.FORMATION_SLOTS.items():
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                dx = slots[i][0] - slots[j][0]
                dy = slots[i][1] - slots[j][1]
                if (dx * dx + dy * dy) ** 0.5 < 1.0:
                    ok = False
                    detail = f"{form} 槽位 {i}/{j} 过近"
        for du, dv in slots:
            if not (p3d.V_NEAR < dv < p3d.V_FAR):
                ok = False
                detail = f"{form} v={dv} 越界"
    check("五阵 (u,v) 槽位不重叠且落在棱柱顶面", ok, detail)
    spread_ok = all(
        len({dv for _du, dv in slots}) >= 2
        for form, slots in core.FORMATION_SLOTS.items() if form != "changshe")
    check("前后排差异：长蛇单列同 v，其余阵列 ≥2 档 v",
          len({dv for _du, dv in core.FORMATION_SLOTS["changshe"]}) == 1
          and spread_ok,
          str({f: len({dv for _du, dv in s})
               for f, s in core.FORMATION_SLOTS.items()}))

    # 6) 棱柱：近侧厚边铺满视口；同一世界坡底截面随相机横移
    near_len = p3d.slab_near_visible_len(0.0, 0.0)
    end_a = p3d.slab_end_side(4.2, 0.0)
    end_b = p3d.slab_end_side(4.2, 4.2)
    shift = abs(end_a[0][0] - end_b[0][0])
    slant = ((end_a[1][0] - end_a[0][0]) ** 2
             + (end_a[1][1] - end_a[0][1]) ** 2) ** 0.5
    check("近侧厚边铺满视口、坡底截面随相机横移且投影为斜线",
          near_len >= p3d.VIEW_W - 1.0 and shift > 30.0 and slant > 100.0,
          f"近侧 {near_len:.0f}px / 坡底横移 {shift:.0f}px 斜长 {slant:.0f}px")

    # 7) 角色落点：全部整数像素（无亚像素采样）
    bad = 0
    for cam in (0.0, 2.5, 7.0):
        for form, slots in core.FORMATION_SLOTS.items():
            for du, dv in slots:
                sx, sy = p3d.world_to_screen(cam + 1.0 + du, dv, cam, 0.0)
                if not (isinstance(sx, int) and isinstance(sy, int)):
                    bad += 1
    check("角色落点全部整数像素", bad == 0, f"{bad} 个非整数")


# ================================================================== 8.4b 单点透视收敛
def test_perspective_convergence() -> None:
    """第十三/十四轮：三焦距 scale 单调、10 档无空档、预烘尺寸、往返、汇聚、剔除、相机。"""
    # 1) 三档焦距下 scale(v) 均严格递减；v=0 分别 1.00 / 1.25 / 0.80
    n = 200
    mono_ok = True
    detail = ""
    for name, focal in p3d.ZOOM_FOCALS.items():
        p3d.set_focal(focal)
        scales = [p3d.scale(p3d.V_NEAR
                            + (p3d.V_FAR - p3d.V_NEAR) * i / (n - 1))
                  for i in range(n)]
        if not all(b < a for a, b in zip(scales, scales[1:])):
            mono_ok = False
            detail = name
    p3d.set_focal(p3d.ZOOM_FOCALS["standard"])
    p3d.set_focal(p3d.ZOOM_FOCALS["near"])
    near0 = p3d.scale(0.0)
    p3d.set_focal(p3d.ZOOM_FOCALS["far"])
    far0 = p3d.scale(0.0)
    p3d.set_focal(p3d.ZOOM_FOCALS["standard"])
    check("三焦距下 scale(v) 200 点严格递减、v=0 为 1.00/1.25/0.80",
          mono_ok and abs(p3d.scale(0.0) - 1.0) < 1e-9
          and abs(near0 - 1.25) < 1e-6 and abs(far0 - 0.80) < 1e-6,
          f"near={near0:.3f} far={far0:.3f} {detail}")

    # 2) 10 档按最终屏幕缩放等比切分：首尾相接、覆盖全区间、档中心归位
    bounds = [p3d.band_scale_bounds(i) for i in range(p3d.BAND_COUNT)]
    contiguous = (p3d.BAND_COUNT == 10
                  and abs(bounds[0][0] - p3d.BAND_MIN) < 1e-9
                  and abs(bounds[-1][1] - p3d.BAND_MAX) < 1e-9
                  and all(abs(bounds[i][1] - bounds[i + 1][0]) < 1e-9
                          for i in range(len(bounds) - 1)))
    ratio = p3d.BAND_RATIO
    centers_ok = all(p3d.band_index_scale(p3d.band_scale(i)) == i
                     for i in range(p3d.BAND_COUNT))
    bscales = p3d.band_scales()
    check("10 档 scale 区间首尾相接覆盖全焦距、档中心归位、档缩放递增",
          contiguous and centers_ok
          and 1.14 <= ratio <= 1.18
          and all(b > a for a, b in zip(bscales, bscales[1:])),
          f"ratio={ratio:.4f} " + " ".join(f"{v:.3f}" for v in bscales))

    # 2b) 三焦距 × 200 v 的落档并集覆盖 0..9，且 v 逐点移动时档号跳变 ≤1
    covered: set[int] = set()
    jump_ok = True
    for _name, focal in p3d.ZOOM_FOCALS.items():
        p3d.set_focal(focal)
        last = None
        for i in range(n):
            b = p3d.band_index(p3d.V_NEAR
                               + (p3d.V_FAR - p3d.V_NEAR) * i / (n - 1))
            covered.add(b)
            if last is not None and abs(b - last) > 1:
                jump_ok = False
            last = b
    p3d.set_focal(p3d.ZOOM_FOCALS["standard"])
    check("三焦距落档覆盖 10 档且无空档、v 相邻点跳档 ≤1",
          covered == set(range(p3d.BAND_COUNT)) and jump_ok,
          f"covered={sorted(covered)}")

    # 3) 预烘 PNG 实际尺寸与 manifest 一致
    path = os.path.join(ROOT, "assets_gen", "manifest.json")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    bands = manifest["bands"]
    samples = [
        ("hero", "bands/b4/sprites/likui/top_idle_0.png"),
        ("enemy", "bands/b2/enemies/grunt/idle_0.png"),
        ("boss", "bands/b6/boss/drumking/idle_0.png"),
        ("prop", "bands/b1/props/lantern.png"),
    ]
    size_ok = True
    detail = ""
    for label, rel in samples:
        meta = bands["images"].get(rel)
        p = os.path.join(ROOT, "assets_gen", *rel.split("/"))
        if meta is None or not os.path.exists(p):
            size_ok = False
            detail = f"{label} 缺 manifest/文件"
            continue
        actual = pygame.image.load(p).get_size()
        if list(actual) != list(meta["size"]):
            size_ok = False
            detail = f"{label} 实际{actual} vs {meta['size']}"
    check("预烘档位 PNG 尺寸与 manifest bands.images 一致", size_ok, detail)

    sh_rel = "bands/b4/fx/shadow.png"
    sh_meta = bands.get("shadows", {}).get(sh_rel)
    sh_img = pygame.image.load(os.path.join(
        ROOT, "assets_gen", *sh_rel.split("/")))
    rect = p3d.shadow_rect(p3d.band_center(4))
    sh_ok = (sh_meta is not None
             and list(sh_img.get_size()) == list(sh_meta["size"])
             and sh_img.get_size() == (rect[2], rect[3]))
    check("阴影 PNG 尺寸与 manifest / shadow_rect(档4) 一致", sh_ok,
          f"实际{sh_img.get_size()} manifest={sh_meta['size'] if sh_meta else None} "
          f"rect={rect[2]}×{rect[3]}")

    # 4) 往返：3 个相机 × 21u × 25v ≥ 200 点，像素误差必须为 0
    err = 0
    points = 0
    for cam in (0.0, 30.0, 100.0):
        for i in range(21):
            u = cam - 10.0 + i
            for j in range(25):
                v = p3d.V_NEAR + 0.5 * j
                sx, sy = p3d.world_to_screen(u, v, cam, 0.0)
                err = max(err, p3d.roundtrip_px(sx, sy, cam, 0.0))
                points += 1
    check("往返 ≥200 点（cam∈{0,30,100}）像素误差为 0",
          points >= 200 and err == 0, f"{points} 点 max={err}px")

    # 5) 地面四边形：常数 u 边延长交于消失点；同 v 行不平行
    def intersect(p1, p2, p3, p4):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        x4, y4 = p4
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-9:
            return None
        px = ((x1 * y2 - y1 * x2) * (x3 - x4)
              - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
        py = ((x1 * y2 - y1 * x2) * (y3 - y4)
              - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
        return (px, py)

    v0, v1 = -5.9, 5.9
    vpx, vpy = p3d.vp_point()
    conv_ok = True
    detail = ""
    for u in (0.0, 1.0):
        quad = p3d.cell_quad(u, u + 2.0, v0, v1)
        if not all(isinstance(c, int) for p in quad for c in p):
            conv_ok = False
            detail = "四角非整数"
            break
        far_line = (p3d.world_to_screen(u + 10.0, v0),
                    p3d.world_to_screen(u + 10.0, v1))
        pt = intersect(quad[0], quad[3], far_line[0], far_line[1])
        d1 = (quad[3][0] - quad[0][0], quad[3][1] - quad[0][1])
        d2 = (quad[2][0] - quad[1][0], quad[2][1] - quad[1][1])
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        if (pt is None
                or ((pt[0] - vpx) ** 2 + (pt[1] - vpy) ** 2) ** 0.5 > 1.0
                or abs(cross) < 1.0):
            conv_ok = False
            detail = f"u={u} 交点={pt} cross={cross:.0f}"
    check("地面常数 u 边延长交于消失点（≤1px）且同 v 行不平行",
          conv_ok, detail)

    # 6) 屏幕剔除
    cam = 0.0
    check("可视剔除：cam+40 出屏、cam+2 在屏",
          not p3d.is_visible(cam + 40.0, 0.0, cam)
          and p3d.is_visible(cam + 2.0, 0.0, cam))

    # 7) 相机限位且无跳变
    import render as r
    try:
        pygame.display.set_mode((1, 1))
    except Exception:
        pass
    ren = r.Renderer()
    g = make_game()
    cam_ok = True
    detail = ""
    for x in (0.0, 40.0, 100.0, 147.0):
        g.squad.x = x
        step_max = 0.0
        for i in range(160):
            prev = ren.cam_x
            ren._camera(g, 1.0 / 60.0)
            if i >= 20:
                step_max = max(step_max, abs(ren.cam_x - prev))
        c0 = ren.cam_x
        ren._camera(g, 1.0 / 60.0)
        c1 = ren.cam_x
        ren._camera(g, 1.0 / 60.0)
        c2 = ren.cam_x
        hi = g.map_len - p3d.CAM_END_MARGIN
        if not (0.0 <= c1 <= hi and 0.0 <= c2 <= hi) \
                or abs(c1 - c0) > 5.0 or abs(c2 - c1) > 5.0 \
                or step_max > 5.0:
            cam_ok = False
            detail = f"x={x} cam={c0:.2f}/{c1:.2f}/{c2:.2f} step={step_max:.2f}"
    check("相机限位 [0,map_len-6] 且连续两帧位移 <5px", cam_ok, detail)

    # 8) 档位 hero PNG 逐像素 alpha 只有 0/255
    import random
    rng = random.Random(0x13)
    bad = []
    picked = []
    for band in (0, 4, 9):
        cand = sorted(k for k in bands["images"]
                      if k.startswith(f"bands/b{band}/sprites/")
                      and k.endswith("/top_idle_0.png"))
        rel = rng.choice(cand)
        picked.append(rel)
        img = pygame.image.load(os.path.join(
            ROOT, "assets_gen", *rel.split("/")))
        alphas = {img.get_at((px, py))[3]
                  for py in range(img.get_height())
                  for px in range(img.get_width())}
        if not alphas <= {0, 255}:
            bad.append(rel)
    check("随机 3 张档位 hero PNG 逐像素 alpha 只有 0/255",
          not bad, ",".join(bad) if bad else ",".join(picked))

    # 9) 道具预烘：7 类 × 10 档 = 70 张齐全，尺寸/alpha 与 manifest 一致
    prop_names = ("tree_0", "flag_0", "gate_forest", "gate_market",
                  "gate_plaza", "mile_0", "lantern")
    missing = [f"b{b}/{n}" for b in range(p3d.BAND_COUNT) for n in prop_names
               if not os.path.exists(os.path.join(
                   ROOT, "assets_gen", "bands", f"b{b}", "props", n + ".png"))]
    size_bad = []
    prop_alpha_bad = []
    for b in (0, 4, 9):
        for n in prop_names:
            rel = f"bands/b{b}/props/{n}.png"
            meta = bands["images"].get(rel)
            p = os.path.join(ROOT, "assets_gen", *rel.split("/"))
            img = pygame.image.load(p)
            if (meta is None or list(img.get_size()) != list(meta["size"])):
                size_bad.append(rel)
            alphas = {img.get_at((x, y))[3]
                      for y in range(img.get_height())
                      for x in range(img.get_width())}
            if not alphas <= {0, 255}:
                prop_alpha_bad.append(rel)
    check("道具 7 类 × 10 档齐全，尺寸与 manifest 一致、无中间 alpha",
          not missing and not size_bad and not prop_alpha_bad,
          f"缺{len(missing)} 尺寸{len(size_bad)} alpha{len(prop_alpha_bad)}")

    # 10) 任意焦距下角色落点仍为整数
    bad = 0
    for focal in p3d.ZOOM_FOCALS.values():
        p3d.set_focal(focal)
        for form, slots in core.FORMATION_SLOTS.items():
            for du, dv in slots:
                sx, sy = p3d.world_to_screen(10.0 + du, dv, 10.0, 0.0)
                if not (isinstance(sx, int) and isinstance(sy, int)):
                    bad += 1
    p3d.set_focal(p3d.ZOOM_FOCALS["standard"])
    check("三焦距 × 五阵角色落点全部整数像素", bad == 0, f"{bad} 个非整数")

    # 11) 变焦过渡：150–200ms 到位、逐帧整档、HUD 不动
    ren.focal = p3d.ZOOM_FOCALS["standard"]
    ren.focal_target = ren.focal
    ren.zoom_index = 0
    p3d.set_focal(ren.focal)
    hud_a, _ = ren._build_hud(g, g.now)
    ren.cycle_zoom()
    frames = 0
    seq = [ren.band_for(0.0)]
    while abs(ren.focal - ren.focal_target) > 1e-9 and frames < 40:
        ren._step_zoom(1.0 / 60.0)
        frames += 1
        seq.append(ren.band_for(0.0))
    hud_b, _ = ren._build_hud(g, g.now)
    dur = frames / 60.0
    smooth = all(abs(b - a) <= 1 for a, b in zip(seq, seq[1:]))
    same_hud = (pygame.image.tostring(hud_a, "RGBA")
                == pygame.image.tostring(hud_b, "RGBA"))
    check("变焦 150–200ms 落位、逐帧整档跳变 ≤1、HUD 不动",
          abs(ren.focal - 3.2) < 1e-9 and 0.15 <= dur <= 0.20
          and smooth and same_hud, f"{frames} 帧={dur:.3f}s seq={seq}")

    # 12) 旗/灯笼/里程桩鼓点震动：整像素、同档同幅
    flag_offs = []
    lantern_offs = []
    mile_offs = []
    for beat in (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875):
        g.clock.beat_pos = beat
        flag_offs.append(ren._prop_vib(g, 2))
        lantern_offs.append(ren._prop_vib(g, 1))
        mile_offs.append(ren._prop_vib(g, 1))
    check("旗 2px / 灯笼 1px / 里程桩 1px 鼓点震动全为整数像素",
          all(isinstance(v, int)
              for v in flag_offs + lantern_offs + mile_offs)
          and max(flag_offs) == 2 and min(flag_offs) == -2
          and max(lantern_offs) <= 1 and min(lantern_offs) >= -1
          and max(mile_offs) <= 1 and min(mile_offs) >= -1,
          f"flag={flag_offs} lantern={lantern_offs} mile={mile_offs}")

    # 13) 道具参与 (v,u) 深度排序：两组遮挡断言
    g.squad.x = 10.0
    ren.cam_x = 10.0
    props = ren._visible_props(g)
    tree = min((p for p in props if p[2] == "tree_0" and p[1] > 0),
               key=lambda p: abs(p[0] - 10.0))
    tu, tv = tree[0], tree[1]
    tree_img = ren.bank.prop_bands[ren.band_for(tv)]["tree_0"]
    tw, th = tree_img.get_size()
    # 树后角色（actor.v > tree.v）：角色先画，树冠后画压住角色
    back = (tu, tv + 0.3)
    order = p3d.depth_sorted([(tu, tv, "tree"), (back[0], back[1], "actor")],
                             v_of=lambda a: a[1], u_of=lambda a: a[0])
    bx, by = p3d.world_to_screen(back[0], back[1])
    over_back = p3d.rect_overlap(
        p3d.footprint_rect(bx, by, 90, 120),
        p3d.footprint_rect(*p3d.world_to_screen(tu, tv), tw, th))
    ok_back = order[0][2] == "actor" and order[-1][2] == "tree" and over_back
    # 树前角色（actor.v < tree.v）：树先画，角色遮住树干；
    # 同一世界 u 在不同 v 的屏幕 x 不同，取与树干同屏幕 x 的前排 u。
    tree_sx, tree_sy = p3d.world_to_screen(tu, tv)
    front_y = p3d.world_to_screen(tu, 0.0)[1]
    front_u = p3d.screen_to_world(tree_sx, front_y, ren.cam_x)[0]
    order2 = p3d.depth_sorted([(tu, tv, "tree"),
                               (front_u, 0.0, "actor")],
                              v_of=lambda a: a[1], u_of=lambda a: a[0])
    over_front = p3d.rect_overlap(
        p3d.footprint_rect(tree_sx, front_y, 90, 120),
        p3d.footprint_rect(tree_sx, tree_sy, tw, th))
    ok_front = order2[0][2] == "tree" and order2[-1][2] == "actor" and over_front
    acts = ren._all_actors(g)
    ti = next(i for i, a in enumerate(acts)
              if a[2] == "prop" and a[3][2] == "tree_0" and a[0] > 0)
    ui = next(i for i, a in enumerate(acts) if a[2] == "unit")
    check("树冠遮角色 / 角色遮树干 两组遮挡顺序与包围盒相交",
          ok_back and ok_front and ui > ti,
          f"back={over_back} front={over_front} tree@{ti} unit@{ui}")


# ================================================================== 8.4c 长关卡表
def test_level_long() -> None:
    level = core.LEVEL
    length = float(level["length_units"])
    check("长关卡长度 148 单位（140–160）",
          length == 148.0 and 140.0 <= length <= 160.0, f"{length}")

    segs = level["segments"]
    contig = (len(segs) == 3
              and all(abs(float(segs[i]["u1"]) - float(segs[i + 1]["u0"]))
                      < 1e-9 for i in range(len(segs) - 1))
              and abs(float(segs[-1]["u1"]) - length) < 1e-9)
    check("3 段 u0/u1 首尾相接、末段 u1 == 关卡长度", contig,
          " ".join(f"{s['u0']}-{s['u1']}" for s in segs))

    fields_ok = all(
        float(seg["slope_deg"]) in (8.0, 10.0, 12.0)
        and all(k in seg for k in ("bpm", "lantern_density", "recommend",
                                   "palette", "waves"))
        and seg.get("waves") for seg in segs)
    check("每段含坡度(8/10/12)/BPM/灯笼密度/推荐阵/配色/波次",
          fields_ok, " ".join(f"{s['name']}:{s['slope_deg']}°" for s in segs))

    prev = -1e9
    waves_ok = True
    detail = ""
    for seg in segs:
        for w in seg.get("waves", []):
            u = float(w["u"])
            if not (u > prev and float(seg["u0"]) <= u < float(seg["u1"])):
                waves_ok = False
                detail = f"u={u} 段={seg['u0']}-{seg['u1']}"
            prev = u
    check("全部波次 u 跨段严格递增、不重叠且落在本段内",
          waves_ok, detail)

    boss_u = float(level["boss"]["u"])
    third = segs[2]
    check("Boss u 落在第三段 [u0,u1)",
          float(third["u0"]) <= boss_u < float(third["u1"]),
          f"boss={boss_u} / {third['u0']}-{third['u1']}")

    names = [core.segment_at(10.0)["name"], core.segment_at(60.0)["name"],
             core.segment_at(130.0)["name"]]
    check("segment_at(10/60/130) 分别归到三段",
          names == [segs[0]["name"], segs[1]["name"], segs[2]["name"]],
          "/".join(names))
    check("segment_index_at 边界：-5 → 0、160 → 2",
          core.segment_index_at(-5.0) == 0
          and core.segment_index_at(160.0) == 2,
          f"{core.segment_index_at(-5.0)}/{core.segment_index_at(160.0)}")


# ================================================================== 8.5 倾斜 / 倒地滚动
def test_tilt_and_roll() -> None:
    base = core.unit_tilt_deg(False, 0)
    check("坡面倾斜 ≈ 坡度（8–12°）", 8.0 <= base <= 12.0,
          f"直立 {base:.1f}°")
    s1 = core.unit_tilt_deg(True, 1)
    s5 = core.unit_tilt_deg(True, 5)
    check("下坡冲锋按加速度叠加 0–6° 前倾",
          s1 > base and s5 > s1
          and s5 - base <= core.TERRAIN["tilt_charge_max"] + 1e-6,
          f"第1拍 {s1:.1f}° → 第5拍 {s5:.1f}°（+{s5-base:.1f}°）")
    check("急停回正到基准",
          abs(core.unit_tilt_deg(False, 5) - base) < 1e-9)
    hurt = core.unit_tilt_deg(False, 0, 1.0, 1.0)
    check("受击短暂后仰",
          hurt < base and abs(base - hurt - core.TERRAIN["tilt_hurt_back"]) < 1e-6,
          f"{base:.1f}° → {hurt:.1f}°")
    check("visual_tilt 开关关闭后直立贴地",
          core.unit_tilt_deg(True, 5, 1.0, 0.0, False) == 0.0)

    # 脚底锚点：绕底边中点旋转后，锚点位置不变，仍在坡线上
    ok = True
    detail = ""
    for deg in (0.0, -6.0, 10.0, 16.0):
        px, py, rw, rh = core.tilt_blit_pivot(128, 160, deg)
        if not (0.0 <= px <= rw and 0.0 <= py <= rh):
            ok = False
            detail = f"{deg}° pivot=({px:.1f},{py:.1f}) size={rw}×{rh}"
    for sx in (200.0, 500.0, 900.0):
        gy = core.ground_screen_y(sx)
        if abs((gy - 0.0) - (core.GROUND_SCREEN_Y + core.SLOPE
                             * (sx - core.SCREEN_BASE_X))) > 1e-9:
            ok = False
            detail = f"x={sx} 基线不连续"
    check("旋转后脚底锚点留在坡面", ok, detail)

    r0 = core.down_roll_offset(0.0)
    r_mid = core.down_roll_offset(0.27)
    r_end = core.down_roll_offset(9.0)
    check("倒地下坡滚动：0 → 30px 缓出后停",
          r0 == 0.0 and 0.0 < r_mid < r_end
          and abs(r_end - core.TERRAIN["down_roll_px"]) < 1e-6,
          f"0.27s={r_mid:.1f}px 停={r_end:.1f}px")
    check("滚动后脚底仍贴坡（y 随 x 重算）",
          abs(core.ground_screen_y(500 + r_end)
              - (core.GROUND_SCREEN_Y
                 + core.SLOPE * (500 + r_end - core.SCREEN_BASE_X))) < 1e-9)


# ================================================================== 8.6 Boss 石台高度
def test_boss_platform() -> None:
    def take(on: bool) -> float:
        x = boss_game()
        x.guidance = False
        x.boss.on_platform = on
        hp = x.squad.hp
        att = core.BossAttempt(cycle=0, intent_key="slam")
        x._boss_damage(att, core.INTENTS["slam"], False)
        return hp - x.squad.hp

    d_on, d_off = take(True), take(False)
    ratio = d_on / max(1e-6, d_off)
    check("台上 Boss 近战伤害 ×1.35",
          abs(ratio - core.BOSS_PLATFORM["boss_damage_mult"]) < 0.03,
          f"{d_off:.1f} → {d_on:.1f}（×{ratio:.2f}）")

    def strike(on: bool) -> float:
        x = boss_game()
        x.boss.on_platform = on
        x.boss.x = x.squad.x + 2.0
        before = x.boss.hp
        x._do_attack(core.GroupResult(0, "JJJJ", "attack", "perfect", True, ""))
        return before - x.boss.hp

    p_on, p_off = strike(True), strike(False)
    ratio = p_on / max(1e-6, p_off)
    check("台下仰攻台上 Boss 伤害 ×0.85",
          abs(ratio - core.BOSS_PLATFORM["player_damage_mult"]) < 0.03,
          f"{p_off:.1f} → {p_on:.1f}（×{ratio:.2f}）")

    # 破阵击落台下：顺坡更远、同层、长硬直、失去高度加成
    g = boss_game()
    g.boss.platform_x = g.boss.x
    before_x = g.boss.x
    keys = correct_keys(g.intent_key or "")
    for i in range(4):
        press_at(g, 4 + i, keys[i])
    check("破阵把 Boss 击落台下",
          not g.boss_on_platform
          and g.boss.x > before_x + core.slope_knock_distance(0.9, 1.0) - 0.05
          and g.stagger_until - g.now >= core.BOSS_PLATFORM["knockdown_stagger_sec"] - 0.05,
          f"x {before_x:.2f}→{g.boss.x:.2f} "
          f"硬直={g.stagger_until - g.now:.1f}s")
    check("击落后与台面同层（无高度加成）",
          not g.boss_on_platform
          and g.boss.x - g.boss.platform_x > 1.0,
          f"台距={g.boss.x - g.boss.platform_x:.2f}")


# ================================================================== 8.7 公示 / 新手引导
def test_reveal_and_tutorial() -> None:
    check("阶段公示：一阶段 6 拍、二三阶段 4 拍",
          core.BossScore(1).reveal_for_hp(1.0) == 6
          and core.BossScore(1).reveal_for_hp(0.5) == 4
          and core.BossScore(1).reveal_for_hp(0.2) == 4)
    g = boss_game()
    check("一阶段提前 2 拍公示且高亮同步拉长",
          g.intent_reveal_beats >= 5
          and g.attempt is not None
          and g.boss_telegraph_active and not g.boss_input_window,
          f"reveal={g.intent_reveal_beats} 拍 at={g.cycle_slot:.2f} "
          f"window={g.boss_input_window}")
    check("判定输入窗口仍为 4 拍", core.INPUT_BEATS == 4)

    g2 = boss_game()
    g2.guidance = True
    hp0 = g2.squad.hp
    wrong = core.BossAttempt(cycle=0, intent_key="slam")
    wrong.slots = [core.Slot(key="J", grade="good", dt_ms=60.0, beat=i)
                   for i in range(core.INPUT_BEATS)]
    for c in range(3):
        wrong.cycle = c
        wrong.resolved = False
        g2._resolve_attempt(wrong, early=True)
    check("新手前 3 招只公示免罚",
          abs(g2.squad.hp - hp0) < 1e-6
          and g2.stats.get("tutorial_grace") == 3,
          f"hp={g2.squad.hp:.1f} grace={g2.stats.get('tutorial_grace')}")
    wrong.cycle = 3
    wrong.resolved = False
    g2._resolve_attempt(wrong, early=True)
    check("第 4 招起恢复正常伤害",
          g2.squad.hp < hp0,
          f"hp={g2.squad.hp:.1f}")

    g3 = boss_game()
    g3.tutorial_seen.clear()
    g3.tutorial_shown = 0
    g3.tutorial_hint = ("", 0.0)
    g3._maybe_tutorial_hint("slam")
    first = g3.tutorial_hint[0]
    g3._maybe_tutorial_hint("slam")
    check("教程提示首次出现一次即消失",
          bool(first) and g3.tutorial_shown == 1
          and "-".join(core.INTENTS["slam"]["keys"]) in first,
          f"“{first}”")
    # 用关掉引导的独立实例验证“到点消失”，避免下一轮公示再弹新提示
    g4 = make_game()
    g4.guidance = False
    g4.tutorial_hint = ("教学提示", 0.5)
    advance(g4, g4.now + 0.8)
    check("教程提示到时自动消失（非法驻留）",
          g4.tutorial_hint[1] <= 0.0)


# ================================================================== 8.5 补打
def phase_fail_game(phase: int, makeup: bool = True) -> core.Game:
    """把 Boss 血量压到指定阶段，故意漏掉整组化解，返回补打待定状态。"""
    g = boss_game()
    g.guidance = False
    g.makeup_enabled = makeup
    ratio = {1: 1.0, 2: 0.55, 3: 0.2}[phase]
    g.boss.hp = g.boss.max_hp * ratio
    g.boss_phase = phase
    g.boss_phase_reached = phase
    g.attempt = None
    g.intent_key = None
    g.intent_cycle = -1
    advance(g, 4.2 * beat_sec(g))     # 重新公示本阶段招式
    advance(g, 5.2 * beat_sec(g))     # 不按键 → 窗口内漏拍
    return g


def test_makeup() -> None:
    g = phase_fail_game(2)
    hp = g.squad.hp
    check("二阶段漏拍 → 1 拍补打机会、伤害延后",
          g.makeup_pending and g.attempt is not None
          and g.attempt.makeup_state == "pending"
          and abs(g.squad.hp - hp) < 1e-6
          and 0.5 * beat_sec(g) <= g.makeup_remain <= 1.01 * beat_sec(g),
          f"remain={g.makeup_remain:.2f}s hp={g.squad.hp:.0f}")
    check("补打提示给出正确四拍序列",
          g.makeup_pattern == correct_keys(g.attempt.intent_key or ""),
          g.makeup_pattern)

    g.combo = 5
    g.fever_gauge = 3
    reads = g.stats["boss_perfect_breaks"]
    for k in g.makeup_pattern:
        g.beat_press(k, g.now, 0.0)
    loss_half = hp - g.squad.hp
    check("补打成功：保留连击 / 鼓劲槽 / 不给 Perfect",
          g.attempt.makeup_state == "ok" and g.combo == 5
          and g.fever_gauge == 3
          and g.stats["boss_perfect_breaks"] == reads
          and g.stats.get("makeup_ok") == 1,
          f"combo={g.combo} gauge={g.fever_gauge} "
          f"perfect_breaks={g.stats['boss_perfect_breaks']}")

    # 满额基准：同一局面关闭补打，立刻吃全额伤害
    base = boss_game()
    base.guidance = False
    base.makeup_enabled = False
    base.boss.hp = base.boss.max_hp * 0.55
    base.boss_phase = 2
    base.boss_phase_reached = 2
    base.attempt = None
    base.intent_key = None
    base.intent_cycle = -1
    advance(base, 4.2 * beat_sec(base))
    advance(base, 5.2 * beat_sec(base))
    loss_full = hp - base.squad.hp
    check("补打伤害正好是全额的一半",
          abs(loss_half / max(1e-6, loss_full) - 0.5) < 0.02,
          f"半伤={loss_half:.1f} / 全额={loss_full:.1f}")

    # 超时：1 拍内没补上 → 全额并清空连击
    t = phase_fail_game(2)
    t.combo = 4
    t.fever_gauge = 2
    advance(t, t.now + beat_sec(t) * 1.1)
    check("补打超时 → 全额伤害、清连击",
          t.attempt.makeup_state == "failed" and not t.makeup_pending
          and t.combo == 0 and t.fever_gauge == 0,
          f"state={t.attempt.makeup_state} hp={t.squad.hp:.0f}")

    # 错令补打：序列不对 → 立即判定失败
    w = phase_fail_game(2)
    wrong = "K" * 4 if w.makeup_pattern[:1] != "K" else "J" * 4
    for k in wrong:
        w.beat_press(k, w.now, 0.0)
    check("补打序列错误 → 立即全额伤害",
          w.attempt.makeup_state == "failed" and not w.makeup_pending,
          f"state={w.attempt.makeup_state}")

    # 每招只开一次：成功后再次按键不会二次补打
    once = phase_fail_game(2)
    for k in once.makeup_pattern:
        once.beat_press(k, once.now, 0.0)
    for k in once.makeup_pattern:
        once.beat_press(k, once.now, 0.0)
    check("每招仅一次补打机会",
          once.stats.get("makeup_ok") == 1 and not once.makeup_pending
          and once.attempt.makeup_used,
          f"ok={once.stats.get('makeup_ok')}")

    # 一阶段：无补打，维持原有全额/免罚规则
    p1 = phase_fail_game(1)
    check("一阶段不开补打、立即结算",
          p1.attempt.makeup_state == "none" and not p1.makeup_pending,
          f"state={p1.attempt.makeup_state}")
    # 三阶段同样开放
    p3 = phase_fail_game(3)
    check("三阶段同样开放补打", p3.makeup_pending,
          f"state={p3.attempt.makeup_state if p3.attempt else None}")

    # 新手保护优先：前 3 招免罚时不叠补打
    grace = boss_game()
    grace.guidance = True
    grace.boss_attacks = 0
    grace.boss.hp = grace.boss.max_hp * 0.55
    grace.attempt = None
    grace.intent_key = None
    grace.intent_cycle = -1
    advance(grace, 4.2 * beat_sec(grace))
    advance(grace, 5.2 * beat_sec(grace))
    check("新手前 3 招免罚优先，不与补打叠加",
          grace.attempt.makeup_state == "none"
          and grace.stats.get("tutorial_grace", 0) >= 1,
          f"state={grace.attempt.makeup_state} "
          f"grace={grace.stats.get('tutorial_grace')}")


# ================================================================== 9 好汉
HERO_STATE_COUNTS = {"idle": 4, "march": 6, "attack": 4,
                     "hurt": 2, "down": 2, "skill": 4}


def test_hero_frames() -> None:
    cfg = core.HERO_FRAMES
    heroes = cfg.get("heroes", {})
    check("三好汉帧序表可读", set(heroes) == {"wusong", "linchong", "likui"},
          ",".join(heroes))
    total_ok = True
    total = 0
    detail = ""
    for hero, spec in heroes.items():
        hero_total = 0
        for state, n in HERO_STATE_COUNTS.items():
            fs = spec["frames"][state]
            if fs["count"] != n or len(fs["durations_ms"]) != n:
                total_ok = False
                detail = f"{hero}/{state} count={fs['count']}"
            if not (-1 <= int(fs.get("peak", -1)) < n):
                total_ok = False
                detail = f"{hero}/{state} peak 越界"
            if "loop" not in fs or "cancelable" not in fs:
                total_ok = False
                detail = f"{hero}/{state} 缺 loop/cancelable"
            hero_total += n
        if hero_total != 22:
            total_ok = False
            detail = f"{hero} 仅 {hero_total} 帧"
        total += hero_total
    check("每人 22 帧（待机4/行军6/攻击4/受击2/倒地2/技能4）", total_ok,
          f"共 {total} 帧")
    check("攻击与技能峰值帧 = 2（起手/蓄/峰值/收势 的第 3 帧）",
          all(spec["frames"]["attack"]["peak"] == 2
              and spec["frames"]["skill"]["peak"] == 2
              for spec in heroes.values()))
    check("帧尺寸 144×192、脚底基线 180",
          cfg.get("frame_size") == [144, 192] and cfg.get("baseline") == 180,
          f"{cfg.get('frame_size')} baseline={cfg.get('baseline')}")
    check("好汉替换三兵种且保留数值分工",
          set(core.HERO_FOR_KIND) == set(core.FRONT_ORDER)
          and core.UNIT_TYPES["shield"]["max_hp"] == 46.0
          and core.UNIT_TYPES["drummer"]["atk"] == 18.0
          and core.UNIT_TYPES["spear"]["range"] == 2.4,
          f"{core.HERO_FOR_KIND}")

    missing = []
    for hero, spec in heroes.items():
        for state, n in HERO_STATE_COUNTS.items():
            for i in range(n):
                p = os.path.join(ROOT, "assets_gen", "sprites", hero,
                                 f"{hero}_{state}_{i}.png")
                if not os.path.exists(p):
                    missing.append(f"{hero}_{state}_{i}")
    check("66 张动作帧齐全（sprites/<hero>/<hero>_<state>_<idx>.png）",
          not missing, ",".join(missing[:5]))

    # 斜俯视 3/4 附加帧：每人 16 张（待机3/行军3/攻击3/技能3/受击2/倒地2）
    top_missing = []
    top_states = (("idle", 3), ("march", 3), ("attack", 3),
                  ("skill", 3), ("hurt", 2), ("down", 2))
    for hero in heroes:
        for state, n in top_states:
            for i in range(n):
                p = os.path.join(ROOT, "assets_gen", "sprites", hero,
                                 f"top_{state}_{i}.png")
                if not os.path.exists(p):
                    top_missing.append(f"{hero}_top_{state}_{i}")
                else:
                    img = pygame.image.load(p)
                    if img.get_size() != (144, 192):
                        top_missing.append(
                            f"{hero}_top_{state}_{i} {img.get_size()}")
    check("俯视 3/4 帧 16 张/人齐全（144×192）", not top_missing,
          ",".join(top_missing[:5]))

    # 峰值帧触发：攻击收手前发出 hero_peak 事件
    g = make_game()
    for i in range(4):
        press_at(g, i, "J")
    advance(g, 4 * beat_sec(g) + 0.26)
    peaks = [ev for ev in g.events if ev[0] == "hero_peak"]
    hero = core.HERO_FOR_KIND[g.squad.front.kind]
    check("命中峰值帧触发放大特效事件",
          bool(peaks) and g.hero_peak[0] == hero and g.stats["hero_peaks"] >= 1,
          f"hero={g.hero_peak[0]} events={len(peaks)}")
    check("峰值帧切换到独有技能帧",
          core.hero_attack_frame(hero, core.HERO_PEAK_PROGRESS)
          == ("skill", core.hero_peak_index(hero, "skill")),
          f"{core.HERO_SKILLS[hero]}")


# ================================================================== 10 素材
def test_assets() -> None:
    path = os.path.join(ROOT, "assets_gen", "manifest.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = json.load(f)
    except Exception as exc:
        check("manifest 可读", False, str(exc))
        return
    check("调色板 28→40 色（好汉三阶明暗扩展 12 色）",
          m["palette_count"] == 40
          and m.get("palette_count") == len(m.get("palette", {}))
          and len(m.get("palette_added", [])) == 12,
          f"{m.get('palette_count')} / added={len(m.get('palette_added', []))}")
    check("素材 ≥140 张", len(m["images"]) >= 140, f"{len(m['images'])} 张")
    required = [
        "players/shield/idle_0.png", "players/shield/down_0.png",
        "players/drummer/attack_0.png", "players/spear/hurt_0.png",
        "enemies/grunt/attack_0.png", "enemies/brute/down_0.png",
        "boss/drumking/telegraph_0.png", "ui/drum.png", "ui/cymbal.png",
        "ui/intent_grab.png", "ui/intent_roar.png",
        "ui/form_shuanglong.png", "ui/form_menghu.png",
        "ui/form_fengshi.png", "ui/form_guijia.png",
        "ui/phase_1.png", "ui/phase_2.png", "ui/phase_3.png",
        "ui/counter_mark.png",
        "props/lantern.png", "environment/ground.png", "environment/far.png",
        "environment/far_sky.png", "environment/mid_street.png",
        "environment/near_fg.png",
        "sprites/wusong/wusong_attack_2.png",
        "sprites/linchong/linchong_skill_2.png",
        "sprites/likui/likui_down_1.png",
        "sprites/wusong/top_idle_0.png",
        "sprites/linchong/top_attack_2.png",
        "sprites/likui/top_march_1.png",
        "sprites/wusong/wusong_sheet.png",
        "portraits/wusong.png", "portraits/linchong.png",
        "portraits/likui.png", "portraits/lineup.png",
    ]
    missing = [r for r in required if r not in m["images"]]
    check("新增阵型/破阵图标/好汉素材齐全", not missing, ",".join(missing))
    fam_scale: dict[str, set] = {}
    for meta in m["images"].values():
        fam = meta["family"]
        if fam in ("player", "enemy", "boss"):
            fam_scale.setdefault("characters", set()).add(meta["scale"])
        elif fam == "ui":
            fam_scale.setdefault("ui", set()).add(meta["scale"])
        elif fam == "hero":
            fam_scale.setdefault("hero", set()).add(meta["scale"])
        elif fam == "portrait":
            fam_scale.setdefault("portrait", set()).add(meta["scale"])
        elif fam == "sheet":
            fam_scale.setdefault("sheet", set()).add(meta["scale"])
        elif fam == "parallax":
            fam_scale.setdefault("parallax", set()).add(meta["scale"])
        else:
            fam_scale.setdefault("environment", set()).add(meta["scale"])
    check("同族同一整数倍缩放",
          fam_scale["characters"] == {4} and fam_scale["ui"] == {2}
          and fam_scale["environment"] == {2}
          and fam_scale["parallax"] == {1}
          and fam_scale["hero"] == {3} and fam_scale["portrait"] == {1}
          and fam_scale["sheet"] == {1},
          f"{fam_scale}")
    bases = {meta["baseline"] for name, meta in m["images"].items()
             if name.startswith("players/")}
    check("玩家脚底基线一致（136）", bases == {136}, str(sorted(bases)))
    hero_bases = {meta["baseline"] for name, meta in m["images"].items()
                  if name.startswith("sprites/") and "sheet" not in name}
    check("好汉脚底基线统一（180）", hero_bases == {180},
          str(sorted(hero_bases)))
    check("定妆照为 256×256",
          m["images"]["portraits/wusong.png"]["size"] == [256, 256],
          str(m["images"]["portraits/wusong.png"]["size"]))

    # 精灵表：22 帧横排、144×192 帧格、4px 间隔（尺寸与素材一致）
    cell_w, cell_h, gap, margin = 144, 192, 4, 8
    want_sheet = (3268, 228)
    sheet_ok = True
    detail = ""
    for hero in ("wusong", "linchong", "likui"):
        meta = m.get("sheets", {}).get(hero, {})
        p = os.path.join(ROOT, "assets_gen", *meta.get("path", "").split("/"))
        if (not meta or meta.get("size") != list(want_sheet)
                or meta.get("cell") != [cell_w, cell_h]
                or meta.get("count") != 22 or not os.path.exists(p)):
            sheet_ok = False
            detail = f"{hero}: {meta}"
        else:
            img = pygame.image.load(p)
            if img.get_size() != want_sheet:
                sheet_ok = False
                detail = f"{hero} 实际 {img.get_size()}"
    check("精灵表 3268×228（22 格 144×192 + 4px 间隔）", sheet_ok, detail)

    # 预览 GIF：14 帧（待机4+行军6+攻击4）、144×192、总时长 8.4s
    gif_ok = True
    detail = ""
    for hero in ("wusong", "linchong", "likui"):
        anim = m.get("animations", {}).get(hero, {})
        p = os.path.join(ROOT, "assets_gen", *anim.get("path", "").split("/"))
        if (not anim or anim.get("size") != [cell_w, cell_h]
                or anim.get("frames") != 14
                or len(anim.get("delays_ms", [])) != 14
                or not (8000 <= sum(anim.get("delays_ms", [])) <= 12000)
                or not os.path.exists(p)):
            gif_ok = False
            detail = f"{hero}: {anim}"
        else:
            img = pygame.image.load(p)
            if img.get_size() != (cell_w, cell_h):
                gif_ok = False
                detail = f"{hero} GIF 实际 {img.get_size()}"
    check("预览 GIF 14 帧 / 144×192 / 8–12s", gif_ok, detail)

    # 旧引用无残留：旧 heroes/ 目录与旧路径字符串都不再出现
    stale = []
    if os.path.isdir(os.path.join(ROOT, "assets_gen", "heroes")):
        stale.append("assets_gen/heroes 仍存在")
    stale += [k for k in m["images"] if k.startswith("heroes/")]
    for fn in ("render.py", "main.py"):
        p = os.path.join(ROOT, fn)
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
        if '_path("heroes"' in text or "heroes/" in text:
            stale.append(fn)
    check("旧 32×40 素材与 heroes/ 引用无残留", not stale,
          ",".join(stale[:5]))

    for rel, meta in m["images"].items():
        p = os.path.join(ROOT, "assets_gen", *rel.split("/"))
        surf = pygame.image.load(p)
        if surf.get_width() != meta["size"][0]:
            check("尺寸与 manifest 一致", False, rel)
            break
    else:
        check("尺寸与 manifest 一致", True)


# ================================================================== 15 景深与视口
def _edge_diff(img: pygame.Surface) -> float:
    iw, ih = img.get_size()
    total = 0
    n = 0
    for y in range(0, ih, 6):
        a = img.get_at((iw - 1, y))
        b = img.get_at((0, y))
        total += abs(a.r - b.r) + abs(a.g - b.g) + abs(a.b - b.b) + abs(a.a - b.a)
        n += 4
    return total / max(1, n)


def _edge_pair(left: pygame.Surface, right: pygame.Surface) -> float:
    """left 的右边列 ↔ right 的左边列，模拟平铺边界换变体。"""
    ih = min(left.get_height(), right.get_height())
    total = n = 0
    for y in range(0, ih, 6):
        a = left.get_at((left.get_width() - 1, y))
        b = right.get_at((0, y))
        total += abs(a.r - b.r) + abs(a.g - b.g) + abs(a.b - b.b) + abs(a.a - b.a)
        n += 4
    return total / max(1, n)


def test_layer_variants() -> None:
    import render as r
    try:
        pygame.display.set_mode((1, 1))
    except Exception:
        pass
    ren = r.Renderer()
    far = ren.bank.layer_variants["far"]
    mid = ren.bank.layer_variants["mid"]
    check("远景 ≥2 套 / 中景 ≥3 套变体",
          len(far) >= 2 and len(mid) >= 3,
          f"far={len(far)} mid={len(mid)}")
    check("变体宽度统一 960（平铺边界一致）",
          all(s.get_width() == r.VIEW_W for s in far + mid)
          and len({s.get_width() for s in far + mid}) == 1)

    worst = 0.0
    for group in (far, mid):
        for a in group:
            for b in group:
                worst = max(worst, _edge_pair(a, b))
    check("变体间右/左边列差 < 16（换图不跳变）", worst < 16.0,
          f"worst={worst:.1f}")

    # 段覆盖整屏、每段只属于一个平铺、切换点恰好落在 960 边界
    for key in ("far", "mid"):
        off = 12345
        spans = ren.layer_spans(key, off)
        pos = 0
        ok = True
        prev_tile = None
        for x, seg, tile, local, _vi in spans:
            ok = ok and x == pos and seg > 0 and 0 <= local < 960 \
                and local + seg <= 960
            if prev_tile is not None and tile != prev_tile:
                ok = ok and (off + x) % 960 == 0
            prev_tile = tile
            pos += seg
        check(f"{key} 变体段连续覆盖且只在平铺边界切换",
              ok and pos == r.VIEW_W, f"spans={len(spans)} cover={pos}")

    seq_a = [ren._layer_variant("far", t)[1] for t in range(16)]
    seq_a2 = [ren._layer_variant("far", t)[1] for t in range(16)]
    ren.layer_variant_seed += 7919
    seq_b = [ren._layer_variant("far", t)[1] for t in range(16)]
    check("同 seed 变体序列可复现、换 seed 可换排布",
          seq_a == seq_a2 and seq_a != seq_b
          and set(seq_a) == set(range(len(far))),
          f"seed→{''.join(map(str, seq_a[:8]))}")
    check("远景/中景变体都被实际用到",
          len({ren._layer_variant("far", t)[1] for t in range(24)}) == len(far)
          and len({ren._layer_variant("mid", t)[1] for t in range(24)}) == len(mid))


def test_parallax_and_view() -> None:
    import render as r
    try:
        pygame.display.set_mode((1, 1))
    except Exception:
        pass
    check("逻辑视口 960×540 + 整数 2× 呈现",
          (r.VIEW_W, r.VIEW_H, r.PRESENT_SCALE) == (960, 540, 2))
    check("三层视差系数落在规定区间",
          0.20 <= r.PARALLAX["far"]["x"] <= 0.30
          and 0.60 <= r.PARALLAX["mid"]["x"] <= 0.80
          and 1.30 <= r.PARALLAX["near"]["x"] <= 1.60,
          str({k: v["x"] for k, v in r.PARALLAX.items()}))
    check("渲染顺序写死：远→中→地面→敌→我→特效→近→HUD",
          r.LAYER_ORDER == ("far", "mid", "ground", "enemies",
                            "squad", "effects", "near", "hud"))

    ren = r.Renderer()
    w1 = ren.visible_units(1.0)
    w075 = ren.visible_units(0.75)
    check("可视世界宽度：单点透视固定约 20.9 单位（不随缩放档变化）",
          20.0 <= w1 <= 21.5 and abs(w075 - w1) < 1e-9,
          f"1.0×={w1:.2f} / 0.75×={w075:.2f}")

    # UI 坐标不随世界缩放档变化
    p1 = ren.hud_pos(640, 360)
    ren.zoom = 0.75
    p2 = ren.hud_pos(640, 360)
    check("两档缩放下 HUD 坐标一致", p1 == p2,
          f"{p1} vs {p2}")
    ren.zoom = 1.0

    # 平铺接缝：左右边列差异低于阈值（远/中/近）
    worst = 0.0
    for name in ("far_sky", "mid_street", "near_fg"):
        img = pygame.image.load(os.path.join(
            ROOT, "assets_gen", "environment", name + ".png")).convert_alpha()
        worst = max(worst, _edge_diff(img))
    check("三层图左右接缝差 < 16", worst < 16.0, f"worst={worst:.1f}")

    # 近景遮挡：把镜头对到人物剪影与队伍重叠的相位
    g = make_game()
    g.squad.x = 2.35
    ren.cam_x = 2.35
    surf = pygame.Surface((r.VIEW_W, r.VIEW_H), pygame.SRCALPHA)
    ren._draw_near(surf, g)
    check("近景遮挡角色触发", ren.near_occludes)
    ren.parallax_debug = 4
    ren._draw_near(surf, g)
    check("parallax_debug 可单独关闭近景", not ren.near_occludes)
    ren.parallax_debug = 0


def _alpha_only(img: pygame.Surface) -> bool:
    """文字/边框图只允许 0 或 255 alpha（出现中间值即重采样痕迹）。"""
    for y in range(img.get_height()):
        for x in range(img.get_width()):
            if img.get_at((x, y))[3] not in (0, 255):
                return False
    return True


def test_hud_sharpness() -> None:
    """960×540 原生 HUD 的锐度断言：无抗锯齿、无重采样、整数边界、与相机解耦。"""
    import render as r
    ren = r.Renderer()
    g = boss_game()
    keys = correct_keys(g.intent_key or "")
    for i in range(2):
        press_at(g, 4 + i, keys[i])
    g.combo = 12
    g.squad.units[0].hp = 8.0
    g.result_pop = ("PERFECT!", 0.75)
    ui, fx = ren._build_hud(g, g.now)

    # 1) 文字缓存：alpha 只有 0/255，且每张图最多 3 种实色（主色/投影/描边）
    bad = [k[0] for k, img in ren.fonts.cache.items() if not _alpha_only(img)]
    check("HUD 文字无抗锯齿中间 alpha", not bad,
          f"{len(bad)} 张异常" + (f"：{bad[:3]}" if bad else ""))
    too_many = []
    for text, img in ren.fonts.cache.items():
        cols = {img.get_at((x, y))[:3]
                for y in range(img.get_height())
                for x in range(img.get_width()) if img.get_at((x, y))[3]}
        if len(cols) > 3:
            too_many.append((text[0], len(cols)))
    check("HUD 文字只有硬边实色、无灰阶过渡", not too_many, str(too_many[:3]))

    # 2) 静态 HUD 合成层 alpha 仍只有 0/255（关掉设计内的淡出卡片后逐像素扫描）
    saved_card = getattr(g, "segment_entry", None)
    g.segment_entry = None
    static_ui, _ = ren._build_hud(g, g.now)
    g.segment_entry = saved_card
    ui_w, ui_h = pygame.Surface.get_size(static_ui)
    alphas = {static_ui.get_at((x, y))[3] for x in range(ui_w)
              for y in range(ui_h)}
    check("静态 HUD 合成后无半透明像素", alphas <= {0, 255},
          str(sorted(alphas)))

    # 3) 世界层锐度不变：960 逻辑 → 2× nearest 后仍是 2×2 同色块
    frame = pygame.Surface((r.VIEW_W * 2, r.VIEW_H * 2))
    ren.draw(frame, g, g.now, 0.016)
    scaled = pygame.transform.scale(ren.world, (r.VIEW_W * 2, r.VIEW_H * 2))
    bad_blocks = 0
    for x in range(0, r.VIEW_W, 7):
        for y in range(0, r.VIEW_H, 7):
            p = scaled.get_at((x * 2, y * 2))
            if not (scaled.get_at((x * 2 + 1, y * 2)) == p
                    and scaled.get_at((x * 2, y * 2 + 1)) == p
                    and scaled.get_at((x * 2 + 1, y * 2 + 1)) == p):
                bad_blocks += 1
    check("世界层 2× 呈现为整数像素块（锐度不变）", bad_blocks == 0,
          f"异常块={bad_blocks}")

    # 4) 元素边界全为整数；HUD 输出层外框 4px（2 逻辑 px）落在整数坐标
    ints = all(type(v) is int for rect in r.HUD_RECTS.values() for v in rect)
    rects_int = all(type(t) is int for t in
                    (v for rect in ren.fonts.rects for v in rect))
    check("HUD 面板/文字边界均为整数", ints and rects_int,
          f"{len(ren.fonts.rects)} 个文字块")
    px, py, _, _ = r.HUD_PANEL
    s = ren.hud_scale
    x0, y0 = px * s, (py + 10) * s
    run = 0
    while ui.get_at((x0 + run, y0)) == ui.get_at((x0, y0)):
        run += 1
    check("HUD 外框 3–4px 且落在整数坐标", 3 <= run <= 4,
          f"实测 {run}px")

    # 5) 字号阶梯：输出像素 16/20/24/30，最小 16
    check("HUD 字号阶梯 16/20/24/30、最小 16px",
          min(ren.fonts.used_sizes) >= r.HUD_MIN_FONT
          and set(ren.fonts.used_sizes) <= set(r.FONT_TIERS),
          f"min={min(ren.fonts.used_sizes)} sizes={sorted(ren.fonts.used_sizes)}")

    # 6) 内容寻址缓存：同一状态连续重绘不新增条目、像素完全一致
    a, _ = ren._build_hud(g, g.now)
    n1 = len(ren.fonts.cache)
    b, _ = ren._build_hud(g, g.now)
    check("文字缓存按内容命中（同帧不增长）",
          len(ren.fonts.cache) == n1
          and pygame.image.tostring(b, "RGBA") ==
          pygame.image.tostring(a, "RGBA"),
          f"cache {n1}→{len(ren.fonts.cache)}")

    # 7) 相机小数位移 / 缩放档不带动 HUD
    ren.cam_x, ren.zoom = 0.37, 1.0
    a, _ = ren._build_hud(g, g.now)
    ren.cam_x, ren.zoom = 1.9163, 0.75
    b, _ = ren._build_hud(g, g.now)
    check("HUD 与相机位移/缩放档解耦",
          pygame.image.tostring(a, "RGBA") ==
          pygame.image.tostring(b, "RGBA"))
    ren.zoom = 1.0


def _bounded_gap(img: pygame.Surface) -> int:
    """同一字内被墨迹夹住的空白游程最小值（行/列各扫一遍）。"""
    w, h = img.get_size()
    best = 10 ** 9
    for y in range(h):
        run = 0
        seen_ink = False
        for x in range(w):
            if img.get_at((x, y))[3]:
                if seen_ink and run:
                    best = min(best, run)
                seen_ink = True
                run = 0
            elif seen_ink:
                run += 1
    for x in range(w):
        run = 0
        seen_ink = False
        for y in range(h):
            if img.get_at((x, y))[3]:
                if seen_ink and run:
                    best = min(best, run)
                seen_ink = True
                run = 0
            elif seen_ink:
                run += 1
    return 0 if best == 10 ** 9 else best


def _ink_coverage(img: pygame.Surface) -> float:
    w, h = img.get_size()
    n = sum(1 for y in range(h) for x in range(w)
            if img.get_at((x, y))[3])
    return n / max(1, w * h)


def test_hud_font_layer() -> None:
    """第十五轮：HUD 独立输出层 + 开源像素字库硬指标。"""
    import render as r
    import pixel_font as pf
    g = boss_game()
    ren = r.Renderer()
    ui, _fx = ren._build_hud(g, g.now)

    check("HUD 独立输出层 = 1920×1080（逻辑 960×540）",
          pygame.Surface.get_size(ui) == (r.VIEW_W * 2, r.VIEW_H * 2)
          and ui.get_size() == (r.VIEW_W, r.VIEW_H),
          f"phys={pygame.Surface.get_size(ui)} logical={ui.get_size()}")

    # 许可证与来源
    lic = os.path.join(ROOT, "assets_gen", "fonts", "OFL.txt")
    ok_lic = (os.path.exists(lic) and pf.license_present()
              and pf.LICENSE_SPDX == "OFL-1.1")
    if ok_lic:
        with open(lic, "r", encoding="utf-8", errors="ignore") as f:
            ok_lic = "SIL OPEN FONT LICENSE" in f.read().upper()
    check("像素字库许可证字段存在（OFL-1.1）",
          ok_lic and "Fusion Pixel" in pf.FONT_SOURCE, pf.FONT_SOURCE)

    # 逐字形：alpha 0/255、覆盖率 12–45%、笔画间隙 ≥1px
    dense = "围团阵陈减响撤撒锣"
    sample = dense + "Aa09"
    covs, gaps, bad_alpha = [], [], []
    for size in (8, 10, 12, 15):
        for ch in sample:
            img, adv = pf.glyph(ch, size, 2)
            alphas = {img.get_at((x, y))[3]
                      for y in range(img.get_height())
                      for x in range(img.get_width())}
            if alphas - {0, 255}:
                bad_alpha.append((ch, size, sorted(alphas)))
            if ch not in "09Aa":
                covs.append((ch, size, _ink_coverage(img)))
            if ch in dense:
                gaps.append((ch, size, _bounded_gap(img)))
    cov_ok = all(0.12 <= c <= 0.45 for _ch, _s, c in covs)
    gap_ok = all(gp >= 1 for _ch, _s, gp in gaps)
    check("字形 alpha 仅 0/255", not bad_alpha, str(bad_alpha[:3]))
    check("字形墨迹覆盖率 12%–45%", cov_ok,
          f"min={min(c for _, _, c in covs):.1%} "
          f"max={max(c for _, _, c in covs):.1%}")
    check("密字笔画最小间隙 ≥1px（列/行扫描）", gap_ok,
          f"min_gap={min(gp for _, _, gp in gaps)}px")

    # ASCII 大小写齐全、小写不再映射大写
    lower_ok = True
    for ch in "abcdefghijklmnopqrstuvwxyz":
        a, _ = pf.glyph(ch, 10, 2)
        b, _ = pf.glyph(ch.upper(), 10, 2)
        if _ink_coverage(a) <= 0 or (ch == "a" and a.get_size() == b.get_size()
                                     and _ink_coverage(a) - _ink_coverage(b) > 0.1):
            lower_ok = False
    check("ASCII 大小写齐全且小写不映射大写", lower_ok)

    # 等宽数字：所有档位下 0–9 推进宽度一致
    widths = {}
    for size in (8, 10, 12, 15):
        widths[size] = {pf.advance(d, size, 2) for d in "0123456789"}
    check("等宽数字：110→10→9 字符宽度不变",
          all(len(v) == 1 for v in widths.values()),
          str({k: sorted(v) for k, v in widths.items()}))

    # 中文标点半宽；破折号/省略号/乘号不是方框
    punct_ok = pf.advance("，", 10, 2) == pf.advance("围", 10, 2) // 2
    marks_ok = True
    for ch in "…—×·":
        img, _adv = pf.glyph(ch, 10, 2)
        c = _ink_coverage(img)
        if c <= 0 or c >= 0.6:
            marks_ok = False
    check("中文标点半宽、破折号/省略号/乘号非方框",
          punct_ok and marks_ok)

    # 文字投影：纯色不透明（10,6,12,255），偏移 2 输出像素
    img = pf._compose("鼓", 10, (255, 240, 206), False, True, None)
    shadow = {(x, y) for y in range(img.get_height())
              for x in range(img.get_width())
              if img.get_at((x, y)) == (10, 6, 12, 255)}
    check("文字仍带纯色不透明 2px 硬投影", bool(shadow),
          f"{len(shadow)} 个投影像素")

    # 旧 5×7 与系统中文栅格路径无残留
    legacy = ("_G5", "msyh", "simhei", "simsun", "Microsoft YaHei")
    src = ""
    for name in ("pixel_font.py", "render.py"):
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
            src += f.read()
    check("旧 5×7 与系统中文栅格路径无残留引用",
          all(k not in src for k in legacy))


def test_hud_motion() -> None:
    """第十一轮：HUD 交互动效（按压/落位/预测/血条/鼓劲槽/Fever/破阵/结算）。"""
    import render as r
    ren = r.Renderer()

    need = ("drum_press_ms", "drum_rebound_ms", "slot_pending_pulse_ms",
            "miss_slash_ms", "perfect_glint_ms",
            "predict_flash_ms", "hp_ghost_ms", "hp_low_threshold",
            "gauge_wave_px", "gauge_burst_ms", "combo_stamp_ms",
            "fever_in_ms", "fever_out_ms", "break_flash_frames",
            "break_seal_ms", "result_in_ms", "result_out_ms")
    check("hud_timing 常量表齐全且逐条命名",
          all(k in r.HUD_TIMING for k in need)
          and all(isinstance(r.HUD_TIMING[k], (int, float)) for k in need),
          f"{len(r.HUD_TIMING)} 条")

    breathe = r.instrument_pose(-1.0, 0.25)
    down = r.instrument_pose(r.HUD_TIMING["drum_press_ms"] * 0.5, 0.0)
    rebound = r.instrument_pose(r.HUD_TIMING["drum_press_ms"]
                                + r.HUD_TIMING["drum_rebound_ms"] * 0.25, 0.0)
    check("乐器按压下沉 1–2px + 高亮一档 / 命中回弹 / 未按呼吸 1px",
          1 <= down[0] <= 2 and down[1] is True
          and rebound[0] == -1 and rebound[1] is False
          and breathe[0] in (-1, 0)
          and all(isinstance(v[0], int) for v in (breathe, down, rebound)),
          f"呼吸={breathe} 下沉={down} 回弹={rebound}")

    cases = {"JJJ": ("attack", True), "JJJJ": ("attack", False),
             "JJK": ("shuanglong", True), "KLK": ("menghu", True),
             "JKLJ": (None, False)}
    got = {k: r.predict_command(k) for k in cases}
    check("预测指令：第 3 拍灰版、第 4 拍实色、乱令不预测",
          got == cases, str(got))

    g = boss_game()
    u = g.squad.units[0]
    u.hp = u.max_hp * 0.9
    ren._update_hud_motion(g, 0.0)
    u.hp = u.max_hp * 0.4
    for _ in range(10):
        ren._update_hud_motion(g, 0.01)
    st = ren._hp_state[0]
    ghost_alive = st["ghost"] > st["shown"] and st["ghost_t"] > 0.0
    for _ in range(25):
        ren._update_hud_motion(g, 0.01)
    check("HP 掉血残影 0.2s 后消失 / 低血阈值 25%",
          ghost_alive and st["ghost"] == 0.0
          and r.HUD_TIMING["hp_low_threshold"] == 0.25,
          f"ghost={st['ghost']:.2f} t={st['ghost_t']:.2f}")

    waves = [r.gauge_wave_px(t, 60.0 / 132.0, x)
             for t in (0.0, 0.05, 0.1, 0.2) for x in (0, 30, 60)]
    check("鼓劲槽液面波浪幅度 ≤2px 且全为整数像素",
          all(isinstance(w, int) and -2 <= w <= 2 for w in waves)
          and max(waves) > 0 and min(waves) < 0, str(waves))

    level, steps = 0.0, 0
    while level < 1.0 and steps < 200:
        level = r.fever_level_step(level, True, 1.0 / 60.0)
        steps += 1
    t_in = steps / 60.0
    level, steps = 1.0, 0
    while level > 0.0 and steps < 200:
        level = r.fever_level_step(level, False, 1.0 / 60.0)
        steps += 1
    t_out = steps / 60.0
    check("Fever 进场 0.4s / 退场 0.25s、逐帧过渡不瞬切",
          abs(t_in - 0.4) < 0.03 and abs(t_out - 0.25) < 0.03
          and r.fever_level_step(0.0, True, 1.0 / 60.0) < 1.0,
          f"in={t_in:.2f}s out={t_out:.2f}s")

    sizes = [r.combo_stamp_size(t / 1000.0) for t in (0, 25, 50, 100)]
    check("连击敲印 22→16→12px（3 帧内）+ 40 连金边阈值",
          sizes[0] == 22 and sizes[-1] == 12 and sizes == sorted(sizes, reverse=True)
          and r.HUD_TIMING["combo_gold_at"] >= 40, str(sizes))

    g2 = boss_game()
    ren2 = r.Renderer()
    g2.last_stagger_cycle = 0
    ren2._update_hud_motion(g2, 0.0)
    check("破阵「破」字印章触发 + 白闪 ≤3 帧",
          ren2._seal_t <= 0.01 and 1 <= ren2._flash_frames <= 3
          and r.HUD_TIMING["break_flash_frames"] <= 3,
          f"flash={ren2._flash_frames} seal={ren2._seal_t:.2f}")

    g3 = boss_game()
    ren3 = r.Renderer()
    ren3._update_hud_motion(g3, 0.0)
    g3.status = "cleared"
    ren3._update_hud_motion(g3, 1.0 / 60.0)
    mid_in = 0.0 < ren3._result_progress(g3) < 1.0
    for _ in range(24):
        ren3._update_hud_motion(g3, 1.0 / 60.0)
    full_in = ren3._result_mode == "hold" and ren3._result_progress(g3) == 1.0
    g3.status = "playing"
    ren3._update_hud_motion(g3, 1.0 / 60.0)
    mid_out = 0.0 < ren3._result_progress(g3) < 1.0
    for _ in range(24):
        ren3._update_hud_motion(g3, 1.0 / 60.0)
    check("结算面板推入/淡入 0.3s、退出 0.3s",
          mid_in and full_in and mid_out and ren3._result_mode == ""
          and r.HUD_TIMING["result_in_ms"] == 300
          and r.HUD_TIMING["result_out_ms"] == 300,
          f"in={mid_in} hold={full_in} out={mid_out} mode={ren3._result_mode!r}")


def test_input_and_ribbon() -> None:
    """第十六轮：按键当帧可见 + 同帧多键有序 + 两段式槽位 + 横向滚动谱面带。"""
    import render as r
    ren = r.Renderer()

    # 1) 按键到像素 ≤1 帧：事件入队后同一次 update 即判定，同帧 HUD 乐器区变化
    g = make_game()
    ui0, _ = ren._build_hud(g, g.now)
    t1 = 1.0 / 60.0
    g.push_input("J", t1)
    g.update(t1, t1 - g.now)
    dx, lit = r.instrument_pose(0.0, g.beat_pos)
    ui1, _ = ren._build_hud(g, g.now)
    s = ren.hud_scale
    ax, ay, aw, ah = 36 * s, 434 * s, 26 * s, 26 * s
    changed = sum(1 for x in range(ax, ax + aw) for y in range(ay, ay + ah)
                  if ui1.get_at((x, y)) != ui0.get_at((x, y)))
    check("按键到像素 ≤1 帧（当帧判定 + 同帧乐器按压/高亮）",
          g.last_press is not None and g.last_press.key == "J"
          and dx >= 1 and lit is True and changed > 0,
          f"age0 dy={dx} lit={lit} 变化像素={changed}")

    # 2) 同帧多键按事件时间戳顺序入队（后到但时间戳更早的先判定）
    g2 = make_game()
    advance(g2, 1.00)
    seen: list[str] = []
    orig = g2.press

    def spy(key, now):
        seen.append(key)
        return orig(key, now)

    g2.press = spy
    # 在「上一帧 → 当前帧」区间内取跨 0.5 拍边界的两条时间戳：
    # 早一点吸附到拍 N，晚一点吸附到拍 N+1，从而占两个不同槽位。
    b0 = g2.clock.beat_pos
    rate = g2.clock.bpm / 60.0
    target = float(int(b0)) + 0.5
    if target <= b0:
        target += 1.0
    t_mid = g2.now + (target - b0) / rate
    t_early, t_late = t_mid - 0.004, t_mid + 0.004
    g2.push_input("K", t_late)        # 后到但时间戳更晚
    g2.push_input("J", t_early)       # 先到且时间戳更早
    now2 = t_mid + 0.006
    g2.update(now2, now2 - g2.now)
    n0 = int(b0)
    n1 = n0 + 1
    s_a = g2._group(n0 // core.CYCLE_BEATS).slots[n0 % core.CYCLE_BEATS]
    s_b = g2._group(n1 // core.CYCLE_BEATS).slots[n1 % core.CYCLE_BEATS]
    check("同帧多键按事件时间戳顺序入队、不丢拍",
          seen == ["J", "K"] and s_a.key == "J" and s_b.key == "K",
          f"seen={seen} slots={s_a.key}/{s_b.key}")

    # 3) 槽位状态机：拍点前 = 待确认半格 + 脉冲；拍点后 = Perfect 落定
    g3 = make_game()
    rect = pygame.Rect(100, 100, r.HUD_RIBBON_CELL, r.HUD_RIBBON_STRONG_H)
    canv = pygame.Surface((220, 200), pygame.SRCALPHA)
    slot = core.Slot(key="J", grade="perfect", beat=1)
    g3.now = 0.30
    ren._draw_ribbon_slot(canv, rect, slot, 1, g3)
    pend_fill = canv.get_at((rect.x + 10, rect.centery))[:3]
    pend_edge = canv.get_at((rect.x, rect.centery))[:3]
    canv.fill((0, 0, 0, 0))
    g3.now = 0.60
    ren._draw_ribbon_slot(canv, rect, slot, 1, g3)
    lock_fill = canv.get_at((rect.x + 10, rect.centery))[:3]
    lock_edge = canv.get_at((rect.x, rect.centery))[:3]
    check("槽位 待确认 → 锁定 状态机合法",
          pend_fill == (168, 126, 62)
          and pend_edge in ((255, 212, 120), (132, 100, 56))
          and lock_fill == (52, 42, 18)
          and lock_edge == (255, 214, 120),
          f"pending={pend_fill}/{pend_edge} locked={lock_fill}/{lock_edge}")

    # 4) 谱面带滚动：严格整数像素，每拍恰好一格，判定线在左 1/4
    beats = [0, 1, 2, 3, 7]
    xs = [r.ribbon_cell_x(b, bp) for bp in (0.0, 0.37, 1.618, 3.999)
          for b in beats]
    steps = [r.ribbon_cell_x(b + 1, 0.37) - r.ribbon_cell_x(b, 0.37)
             for b in range(6)]
    quarter = r.HUD_RIBBON_JUDGE_X - r.HUD_RIBBON[0]
    check("谱面带滚动位移为整数、每拍一格、判定线在左 1/4",
          all(type(v) is int for v in xs) and set(steps) == {r.HUD_RIBBON_PITCH}
          and quarter == r.HUD_RIBBON[2] // 4,
          f"步长={set(steps)} 判定线偏移={quarter}")

    # 5) 强/弱拍高度差
    check("强/弱拍高度差 14px 且常量为整数",
          r.HUD_RIBBON_STRONG_H - r.HUD_RIBBON_WEAK_H == 14
          and all(type(v) is int for v in (r.HUD_RIBBON_STRONG_H,
                                           r.HUD_RIBBON_WEAK_H)),
          f"{r.HUD_RIBBON_STRONG_H}/{r.HUD_RIBBON_WEAK_H}")

    # 6) Boss 公示预警叠在谱面带内（不再单开读招面板）
    gb = boss_game()
    uib, _ = ren._build_hud(gb, gb.now)
    bp = gb.beat_pos
    cur = int(bp)
    first = (cur // core.CYCLE_BEATS) * core.CYCLE_BEATS + core.INPUT_BEATS
    bx0 = r.ribbon_cell_x(first, bp) - r.HUD_RIBBON_CELL // 2 - 4
    by0 = r.HUD_RIBBON[1] + 4
    band_hit = any(uib.get_at(((bx0 + i) * s, by0 * s))[:3] == (126, 92, 62)
                   for i in range(10))
    check("Boss 公示预警叠在谱面带内", band_hit,
          f"band x0={bx0} y={by0}")

    # 7) 无第三块 UI：旧读招面板区域为空，谱面带自带内容
    px, py, pw, ph = r.HUD_READ_PANEL
    panel_alpha = {uib.get_at((x * s, y * s))[3]
                   for x in range(px, px + pw, 4)
                   for y in range(py, py + ph, 4)}
    rx, ry, rw, rh = r.HUD_RIBBON
    ribbon_ink = sum(1 for x in range(rx, rx + rw, 8)
                     for y in range(ry, ry + rh, 8)
                     if uib.get_at((x * s, y * s))[3])
    check("无第三块 UI 面板（读招面板区为空，谱面带承载）",
          panel_alpha <= {0} and ribbon_ink > 0,
          f"panel={sorted(panel_alpha)} ribbon={ribbon_ink}")


def test_judgement_injection() -> None:
    """第十七轮：带真实抖动的判定验证层（可复现、分布符合设定、统计口径正确）。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import judgement_injection as ji

    # 1) 同 seed 同配置 → 完全相同偏差序列；换 seed 必须不同
    a = ji.Injector(ji.DEFAULT_SEED, 38.0, 0.0).deviations(240)
    b = ji.Injector(ji.DEFAULT_SEED, 38.0, 0.0).deviations(240)
    c = ji.Injector(ji.DEFAULT_SEED + 1, 38.0, 0.0).deviations(240)
    check("注入层可复现（同 seed 同偏差序列）",
          a == b and a != c and len(a) == 240,
          f"len={len(a)} diff={sum(1 for x, y in zip(a, c) if x != y)}")

    # 2) 分布符合设定：均值≈系统性偏移，标准差≈高斯+脱拍混合理论
    for sigma in (38.0, 70.0):
        for offset in (0.0, -40.0, 40.0):
            res = ji.run_config(ji.DEFAULT_SEED, sigma, offset, 1.0)
            exp = ji.expected_std(sigma)
            ok_mean = abs(res["dev_mean"] - offset) <= 4.0
            ok_std = abs(res["dev_std"] / exp - 1.0) <= 0.06
            check(f"偏差分布符合设定 σ={sigma:.0f} 偏移{offset:+.0f}ms",
                  ok_mean and ok_std,
                  f"mean={res['dev_mean']:+.1f}ms std={res['dev_std']:.1f}ms "
                  f"(理论std={exp:.1f})")

    # 3) 理论占比与实测差 ≤3 个百分点（四档分别核对）
    for sigma in (38.0, 70.0):
        res = ji.run_config(ji.DEFAULT_SEED, sigma, 0.0, 1.0)
        diffs = {g: abs(res["pct"][g] - res["theory"][g]) for g in ji.GRADES}
        check(f"σ={sigma:.0f} 实测分布与理论一致（≤3pp）",
              max(diffs.values()) <= 3.0,
              " ".join(f"Δ{g}={v:.1f}" for g, v in diffs.items()))

    # 4) 统计口径：手工序列 → 计数/组成功/组全P/连击/连段
    one = ji.summarize([-44.0, -99.0, -120.0, -170.0], 1.0, 4)
    check("统计口径：四档边界逐拍命中", one["counts"] ==
          {"perfect": 1, "good": 1, "miss": 1, "off": 1}
          and one["group_success_pct"] == 0.0
          and one["group_perfect_pct"] == 0.0,
          f"counts={one['counts']}")
    seq = [0.0] * 8 + [0.0, 0.0, 0.0, 170.0]
    two = ji.summarize(seq, 1.0, 4)
    check("统计口径：组成功/全P/combo/连段",
          two["groups"] == 3 and two["counts"]["perfect"] == 11
          and two["counts"]["off"] == 1
          and abs(two["group_success_pct"] - 66.67) < 0.01
          and abs(two["group_perfect_pct"] - 66.67) < 0.01
          and two["combo_avg"] == 2.0 and two["combo_max"] == 4
          and two["streak_avg"] == 2.0,
          f"groups={two['groups']} counts={two['counts']} "
          f"combo={two['combo_avg']}/{two['combo_max']} "
          f"streak={two['streak_avg']}")

    # 5) 注入层不进入正常构建：运行时代码不得引用该工具
    leaked = []
    for name in ("core.py", "main.py", "render.py"):
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
            if "judgement_injection" in f.read():
                leaked.append(name)
    check("注入层不残留进正常构建", not leaked, f"引用={leaked}")


def _drive_guide(g: scenes.Guide, ms: float = 0.0) -> tuple[float, bool]:
    """用精确拍点把指南 6 步跑完；ms=整体系统性偏移。"""
    t0 = g.next_press_time()
    if not g.press("J", t0):
        return t0, False
    now = t0
    g.next(now)
    plans = {1: ("J",) * 4,
             2: ("J",) * 4 + ("K",) * 4 + ("L",) * 4,
             3: ("J", "K", "J", "K", "L", "K", "L", "K"),
             4: ("K",) * 4}
    for step in (1, 2, 3, 4):
        for key in plans[step]:
            t = g.next_press_time() + ms / 1000.0
            if not g.press(key, t):
                return t, False
            now = t
        if not g.done[step]:
            return now, False
        g.next(now)
    for _ in range(8):
        t = g.next_press_time() + ms / 1000.0
        g.press("J", t)
        now = t
    return now, g.done[5]


def test_scene_flow() -> None:
    """第十八轮：战前场景状态机 / 选将 / 指南门槛 / 校准 / 暂停重进。"""
    tmp = tempfile.mkdtemp(prefix="yingge_scene_")
    path = os.path.join(tmp, "settings.json")

    # 1) 主路径 Title → Roster → Guide → Battle
    f = scenes.Flow(path, core.BPM)
    check("Title Enter → Roster", f.scene == "title"
          and f.key("ENTER", 0.0) == "to_roster" and f.scene == "roster")
    check("标题 ENTER = Boss 主线（默认 boss_1819）", f.mode == "boss")
    # 显式 runner 模式仍可测（开关全开时才是默认入口）
    fr = scenes.Flow(path, core.BPM, mode="runner")
    fr.key("ENTER", 0.0)
    check("显式 runner：Roster Enter → Runner（领队已选）",
          fr.key("ENTER", 0.0) == "to_runner" and fr.scene == "runner"
          and fr.leader == "wusong")
    # Boss 模式保留：标题 B → 选人 → 指南 → 战斗
    f.mode = "boss"
    check("Roster Enter → Guide（Boss 模式）",
          f.key("ENTER", 0.0) == "to_guide" and f.scene == "guide"
          and f.leader == "wusong")
    # 指南门槛：未完成不亮下一步
    g = f.guide
    check("指南未完成不亮下一步",
          not g.next_enabled and not g.next(0.0),
          f"step={g.step + 1} done={g.done[g.step]}")
    now, ok = _drive_guide(g)
    check("指南 6 步全部可完成", ok and all(g.done)
          and sum(g.done) == len(scenes.GUIDE_STEPS),
          f"steps_done={sum(g.done)}")
    f.key("ENTER", now)      # 结束校准 → 标 finished
    check("指南结束 Enter → Battle",
          f.key("ENTER", now) == "to_battle" and f.scene == "battle"
          and f.leader == "wusong")

    # 2) 跳过指南 → 直接开战并记 telemetry 字段
    f2 = scenes.Flow(path, core.BPM)
    f2.key("B", 0.0)
    f2.key("ENTER", 0.0)
    check("G 跳过指南 → 直接战斗",
          f2.key("G", 0.0) == "to_battle" and f2.scene == "battle"
          and f2.guide_report is not None
          and f2.guide_report["skipped"] is True,
          f"report={f2.guide_report}")
    rep = f2.guide_report
    f2.guide_report = None
    row = telemetry.GuideRecorder(path=os.path.join(tmp, "guide.csv")).write(
        "wusong", rep)
    check("指南跳过写入 telemetry", row is not None
          and row["skipped"] == 1 and row["steps_done"] == 0,
          f"row={row}")

    # 3) Esc 逐级返回
    f3 = scenes.Flow(path, core.BPM)
    f3.key("B", 0.0)
    f3.key("ENTER", 0.0)
    check("Guide Esc → Roster",
          f3.key("ESC", 0.0) == "to_roster" and f3.scene == "roster")
    check("Roster Esc → Title",
          f3.key("ESC", 0.0) == "to_title" and f3.scene == "title")

    # 4) 锁定格：可悬停不可确认
    f4 = scenes.Flow(path, core.BPM)
    f4.key("ENTER", 0.0)
    f4.key("DOWN", 0.0)   # 3×3 第一行 → 第二行第一格（锁定位）
    check("锁定格可悬停看条件",
          f4.roster.preview_spec().get("kind") == "lock"
          and f4.roster.preview_index() == f4.roster.cursor,
          f"preview={f4.roster.preview_index()} "
          f"spec={f4.roster.preview_spec()}")
    check("锁定格不可确认",
          f4.key("ENTER", 0.0) is None and f4.scene == "roster"
          and f4.roster.toast[0].startswith("锁定"))

    # 5) 暂停菜单重进指南（每局一次）
    f5 = scenes.Flow(path, core.BPM)
    f5.skip_to_battle()
    check("战斗 Esc → 暂停", f5.key("ESC", 0.0) == "open_pause" and f5.paused)
    f5.key("DOWN", 0.0)
    check("暂停 ↑↓ 选到新手指南", f5.pause.sel == 1)
    check("暂停 Enter → 重进指南",
          f5.key("ENTER", 0.0) == "to_guide" and f5.scene == "guide"
          and f5.replay_used)
    check("指南跳过 → 回到战斗",
          f5.key("G", 0.0) == "resume" and f5.scene == "battle"
          and not f5.paused)
    f5.key("ESC", 0.0)
    f5.key("DOWN", 0.0)
    check("本局第二次重进被禁用",
          f5.key("ENTER", 0.0) is None and f5.paused
          and not f5.pause.enabled(1))

    # 6) 校准值写入并在重开后保留
    f6 = scenes.Flow(path, core.BPM)
    f6._start_guide(0.0)
    now, ok = _drive_guide(f6.guide, ms=30.0)
    check("8 拍校准算出 +30ms", ok and f6.guide.calib_ms == 30,
          f"calib={f6.guide.calib_ms}")
    f6.key("ENTER", now)
    f6.key("ENTER", now)
    check("校准值写入配置", f6.offset_ms == 30
          and scenes.load_settings(path)["input_offset_ms"] == 30,
          f"offset={f6.offset_ms}")
    f7 = scenes.Flow(path, core.BPM)
    check("重开保留校准值", f7.offset_ms == 30, f"offset={f7.offset_ms}")
    check("重开保留领队", f7.leader == "wusong", f"leader={f7.leader}")

    # 7) 三位好汉各自能真正开局
    bad = []
    for hero in scenes.HERO_ORDER:
        gg = scenes.new_battle(hero, core.BPM, "drill", start_time=0.0)
        load = scenes.LEADER_LOADOUT[hero]
        start_ok = (gg.leader == hero and gg.formation == load["formation"]
                    and gg.banner[0] == load["line"])
        play_cycle(gg, "JJJJ", 0)
        if not (start_ok and gg.last_result and gg.last_result.success):
            bad.append(hero)
    check("三位领队各自可开局并完成一组", not bad, f"失败={bad}")

    # 8) 场景切换当帧生效（同一帧内状态已改变且画面已更新）
    ren = r.Renderer()
    ui = sui.SceneUI(ren)
    screen = pygame.Surface((1920, 1080))
    f8 = scenes.Flow(path, core.BPM)
    f8.key("B", 0.0)
    f8.key("ENTER", 0.0)
    ui.draw_roster(screen, f8, 0.0)
    before = screen.copy()
    f8.key("ENTER", 0.0)
    ui.draw_guide(screen, f8, 0.0)
    probes = ((960, 540), (420, 220), (1300, 640))
    diff = sum(1 for p in probes if screen.get_at(p) != before.get_at(p))
    check("Roster → Guide 切换 ≤1 帧", f8.scene == "guide" and diff > 0,
          f"diff={diff}")


def test_scene_mouse_render() -> None:
    """第十九轮：鼠标全场景点击 / 指南纯鼠标 / 热区 / 重复绘制 / 字号。"""
    tmp = tempfile.mkdtemp(prefix="yingge_mouse_")
    path = os.path.join(tmp, "settings.json")
    pygame.display.set_mode((960, 540))
    ren = r.Renderer()
    screen = pygame.Surface((1920, 1080))
    ui = sui.SceneUI(ren, screen)

    def draw_scene(flow, now=0.0):
        if flow.scene == "title":
            ui.draw_title(screen, flow, now)
        elif flow.scene == "roster":
            ui.draw_roster(screen, flow, now)
        elif flow.scene == "guide":
            ui.draw_guide(screen, flow, now)
        elif flow.paused:
            ui.draw_pause(screen, flow, now)

    def makers():
        return {
            "title": lambda: scenes.Flow(path, core.BPM),
            "roster": lambda: (lambda f: (f.key("ENTER", 0.0), f)[1])(
                scenes.Flow(path, core.BPM)),
            "guide": lambda: (lambda f: (f.key("B", 0.0),
                                        f.key("ENTER", 0.0), f)[2])(
                scenes.Flow(path, core.BPM)),
            "pause": lambda: (lambda f: (f.skip_to_battle(),
                                        f.key("ESC", 0.0), f)[2])(
                scenes.Flow(path, core.BPM)),
        }

    # 1) 每个可交互元素逐点点击（中心 + 四角内缩 + 边界外），0 异常
    errors: list[str] = []
    for name, mk in makers().items():
        probe = mk()
        zones = probe.hotzones()
        check(f"{name} 热区已登记", len(zones) > 0, f"zones={len(zones)}")
        for label, rect in zones:
            x, y, w, h = rect
            for dx, dy, tag in ((w // 2, h // 2, "center"), (1, 1, "tl"),
                                (w - 1, h - 1, "br"), (-1, -1, "out")):
                flow = mk()
                draw_scene(flow)
                try:
                    flow.click(x + dx, y + dy, 0.0)
                    draw_scene(flow)
                except Exception as exc:
                    errors.append(f"{name}/{label}/{tag}: {exc!r}")
    check("全元素点击 0 异常", not errors, f"{len(errors)} 个：{errors[:3]}")

    # 2) 每场景 500 次随机点击：0 异常、状态合法
    rng = random.Random(19)
    fuzz_errors: list[str] = []
    for name, mk in makers().items():
        flow = mk()
        draw_scene(flow)
        for i in range(500):
            x, y = rng.randrange(960), rng.randrange(540)
            button = rng.choice((1, 2, 3, 4, 5))
            try:
                flow.hover(x, y)
                if button == 1:
                    flow.click(x, y, i * 0.02)
                if i % 5 == 0:
                    draw_scene(flow, i * 0.02)
            except Exception as exc:
                fuzz_errors.append(f"{name}#{i} ({x},{y}) b{button}: {exc!r}")
                break
            if flow.scene == "battle" and not flow.paused:
                flow = mk()
                draw_scene(flow)
            assert_valid = (flow.scene in scenes.SCENES
                            and (flow.guide is not None
                                 or flow.scene != "guide")
                            and (flow.pause is not None or not flow.paused)
                            and flow.leader in scenes.HERO_ORDER)
            if not assert_valid:
                fuzz_errors.append(f"{name}#{i} 状态非法 scene={flow.scene}")
                break
    check("每场景 500 次随机点击 0 异常", not fuzz_errors,
          f"{fuzz_errors[:3]}")

    # 3) 坐标映射：1× / 1.5× / 2×（含非 16:9 黑边）
    maps = []
    for size in ((960, 540), (1440, 810), (1920, 1080)):
        scr = pygame.Surface(size)
        u = sui.SceneUI(ren, scr)
        u._canvas_for(scr)
        w, h = size
        maps.append((size, u.logical_pos((0, 0)),
                     u.logical_pos((w - 1, h - 1)),
                     u.logical_pos((w // 2, h // 2))))
    check("坐标映射 1×/1.5×/2× 正确",
          all(a == (0, 0) and b == (959, 539) and c == (480, 270)
              for _s, a, b, c in maps), f"{maps}")
    scr = pygame.Surface((1000, 800))
    u = sui.SceneUI(ren, scr)
    u._canvas_for(scr)
    top = u.logical_pos((500, u._present_off[1]))
    check("非 16:9 窗口黑边映射正确", top == (480, 0), f"top={top}")

    # 4) 指南纯鼠标走完 6 步
    fm = scenes.Flow(path, core.BPM)
    # 18-19 单入口：默认标题只有 ENTER（Boss 主线）
    fm.click(*_rect_center(scenes.TITLE_ENTER_RECT))
    fm.click(*_rect_center(scenes.roster_cell_rect(0)))
    drum = _rect_center(scenes.GUIDE_KEY_RECT["J"])
    gong = _rect_center(scenes.GUIDE_KEY_RECT["K"])
    cym = _rect_center(scenes.GUIDE_KEY_RECT["L"])
    nxt = _rect_center(scenes.GUIDE_NEXT_RECT)
    t = 0.0

    def mc(pos):
        nonlocal t
        t += 0.02
        return fm.click(pos[0], pos[1], t)

    mc(drum)
    mc(nxt)
    for _ in range(4):
        mc(drum)
    mc(nxt)
    for _ in range(4):
        mc(drum)
    for _ in range(4):
        mc(gong)
    for _ in range(4):
        mc(cym)
    mc(nxt)
    for keypos in (drum, gong, drum, gong, cym, gong, cym, gong):
        mc(keypos)
    mc(nxt)
    for _ in range(4):
        mc(gong)
    mc(nxt)
    for _ in range(8):
        mc(drum)
    mc(nxt)
    check("纯鼠标走完 6 步指南",
          fm.scene == "battle" and fm.guide is None
          and fm.offset_ms is not None,
          f"scene={fm.scene} offset={fm.offset_ms}")

    # 5) 步骤悬停 / 已完成步骤回跳 / 禁用态点击无效果
    fg = scenes.Flow(path, core.BPM)
    fg.key("B", 0.0)
    fg.key("ENTER", 0.0)
    draw_scene(fg)
    fg.hover(180, 126)
    check("步骤项悬停高亮", fg.guide_hover == 0, f"hover={fg.guide_hover}")
    check("下一步禁用态无效果",
          fg.click(*_rect_center(scenes.GUIDE_NEXT_RECT), 0.0) is None
          and fg.guide.step == 0 and not fg.guide.done[0],
          f"step={fg.guide.step}")
    fg.click(*drum, 0.0)
    fg.click(*nxt, 0.0)       # → 第 2 步
    fg.click(*drum, 0.0)      # 第 2 步只落了 1 拍
    check("未完成步骤不可跳转",
          fg.guide.step == 1 and not fg.guide.goto(2, 0.0)
          and fg.guide.step == 1, f"step={fg.guide.step}")
    for _ in range(3):
        fg.click(*drum, 0.0)  # 第 2 步完成
    fg.click(*nxt, 0.0)       # → 第 3 步
    fg.click(*_rect_center(scenes.guide_step_rect(0)), 0.0)
    check("点击已完成步骤可回跳", fg.guide.step == 0,
          f"step={fg.guide.step}")
    fg.hover(*_rect_center(scenes.GUIDE_NEXT_RECT))
    check("按钮悬停命中", fg.hit_target(
        *_rect_center(scenes.GUIDE_NEXT_RECT)) == "next")
    # 热区内缩 1px 生效、边界外 1px 不生效
    nx, ny, nw, nh = scenes.GUIDE_NEXT_RECT
    check("热区边界与视觉一致",
          fg.hit_target(nx + 1, ny + 1) == "next"
          and fg.hit_target(nx - 1, ny + 1) is None)

    # 6) 文本单次绘制：无重复调用、无硬投影（双层描边）
    calls: list[tuple] = []
    orig_text = ren.fonts.text

    def probe_text(surf, s, size, color, pos, **kw):
        calls.append((s, int(size), tuple(color), tuple(pos),
                      bool(kw.get("shadow", True))))
        return orig_text(surf, s, size, color, pos, **kw)

    ren.fonts.text = probe_text
    try:
        for flow in (makers()["title"](), makers()["roster"](),
                     makers()["guide"]()):
            calls.clear()
            draw_scene(flow)
            dup = [c for c in set(calls) if calls.count(c) > 1]
            shadowed = [c for c in calls if c[4]]
            check("同一帧文本无重复绘制", not dup, f"dup={dup[:3]}")
            check("场景文本无硬投影", not shadowed, f"shadow={shadowed[:3]}")
    finally:
        ren.fonts.text = orig_text

    probe = sui.HudSurface(80, 14, scale=2)
    orig_text(probe, "脸谱：赤面", 10, (228, 216, 192), (0, 0),
              shadow=False)
    shadow_px = 0
    for y in range(28):
        for x in range(160):
            if pygame.Surface.get_at(probe, (x, y))[:3] == (10, 6, 12):
                shadow_px += 1
    check("像素探针：单层绘制无投影像素", shadow_px == 0,
          f"shadow_px={shadow_px}")

    # 7) 调试浮层默认关闭；F2 热区只在开启时绘制
    check("debug 浮层默认关闭", sui.SceneUI.debug_overlay is False
          and ui.debug_overlay is False and ui.debug_drawn is False)
    f0 = scenes.Flow(path, core.BPM)
    ui.overlay(screen, f0)
    check("默认不画调试层", ui.debug_drawn is False)
    ui.debug_overlay = True
    ui.overlay(screen, f0)
    check("F3 调试层可开启", ui.debug_drawn is True)
    ui.debug_overlay = False
    ui.show_hotzones = True
    ui.overlay(screen, f0)
    check("F2 热区覆盖可开启", ui.show_hotzones is True)
    ui.show_hotzones = False

    # 8) 最小字号：2× 输出 ≥16px
    for flow in (makers()["title"](), makers()["roster"](),
                 makers()["guide"]()):
        draw_scene(flow)
    sizes = sorted(ren.fonts.used_sizes)
    check("最小字号 ≥16px（输出）", sizes and min(sizes) >= 16
          and set(sizes) <= {16, 20, 24, 30}, f"sizes={sizes}")


def test_runner_model() -> None:
    """纯逻辑闭环：提示队列 / 速度边界 / 撞阵恢复 / 速度下限 / 同 seed 复现。"""
    check("判定窗口与 core 一致",
          (rm.PERFECT_MS, rm.GOOD_MS, rm.MISS_MS)
          == (core.PERFECT_MS, core.GOOD_MS, core.MISS_MS),
          f"{rm.PERFECT_MS}/{rm.GOOD_MS}/{rm.MISS_MS}")

    q = rm.PromptQueue()
    q.schedule_group(8, ("J", "K", "L", "J"))
    check("组提示提前 4 拍", q.group_shown(4, 8) and not q.group_shown(3, 8))
    cells = dict(q.visible_cells(6))
    check("单格提示提前 2 拍", 8 in cells and 9 not in cells, f"visible={sorted(cells)}")
    check("提示键位按拍可取", q.key_at(8) == "J" and q.key_at(10) == "L")

    check("速度公式基准值", abs(rm.solve_speed(1.0, 1.16, 1.040) - 1.2064) < 1e-9,
          f"v={rm.solve_speed(1.0, 1.16, 1.040):.4f}")
    check("惩罚拉满仍不低于下限",
          rm.solve_speed(1.0, 1.0, 1.0, penalty=1.0) >= rm.V_FLOOR)
    check("速度下限大于 0", rm.V_FLOOR > 0 and rm.solve_speed(0.0, 0.0, 0.0) > 0,
          f"floor={rm.V_FLOOR}")

    tr = rm.CollisionTracker()
    tr.hit("pike")
    p0 = tr.penalty()
    check("撞阵立即产生惩罚", 0.0 < p0 <= rm.P_CAP, f"P={p0:.2f}")
    for _ in range(rm.ENEMIES["pike"]["t_recover"]):
        tr.tick()
    check("恢复期结束惩罚归零", tr.penalty() == 0.0 and tr.stacks == 0)

    tr = rm.CollisionTracker()
    for _ in range(6):
        tr.hit("shield")
    check("连续撞击叠加上限",
          tr.stacks == rm.MAX_HIT_STACKS and tr.max_stacks_seen == rm.MAX_HIT_STACKS,
          f"stacks={tr.stacks}/{tr.max_stacks_seen}")
    check("叠加上限内惩罚不超顶", tr.penalty() <= rm.P_CAP, f"P={tr.penalty():.2f}")

    a1 = rm.simulate("A", "novice", seed=17)
    a2 = rm.simulate("A", "novice", seed=17)
    check("同 seed 可复现",
          (a1.time_s, a1.beats, a1.hits) == (a2.time_s, a2.beats, a2.hits),
          f"{a1.time_s:.2f}s/{a1.beats}拍")
    check("逐拍模拟速度恒大于 0", a1.min_speed > 0.0, f"min={a1.min_speed:.2f}")
    check("位移跑满参考路线", abs(a1.distance - rm.ROUTE_STEPS) < 1e-9,
          f"{a1.distance:.1f}")
    check("撞阵次数=错阵段数",
          (a1.hits, rm.simulate("A", "skilled", seed=17).hits,
           rm.simulate("A", "master", seed=17).hits) == (3, 1, 0))
    check("变阵与撞阵不阻断（全程有位移）", a1.beats > 0 and a1.time_s > 0)

    ref = rm.reference_times()
    for tier in ("novice", "skilled", "master"):
        check(f"复现文档 {tier} 时间", abs(ref[tier] - rm.DOC_TIMES[tier]) <= 0.06,
              f"{ref[tier]:.1f}s")

    ev = rm.evaluate("A", 17)
    gap = ev["runs"]["novice"].time_s - ev["runs"]["master"].time_s
    check("差距归属三项之和 = 新手−高手",
          abs(ev["attr_s"]["total_s"] - gap) < 1e-6,
          f"{ev['attr_s']['total_s']:.1f}s")
    evb = rm.evaluate("B", 17)
    check("组 B 归属占比归一", abs(sum(evb["share"].values()) - 1.0) < 1e-6)


def test_runner_scene() -> None:
    """急行模式：提示提前量 / 三档显示 / 缺口与撞阵 / 计时 split / 重开 / 组 B。"""
    cfg = runner.load_config()

    # 1) 提示即谱：整组接触前 4 拍、单格落拍前 2 拍
    q = runner.PromptQueue(cfg)
    g = q.schedule(10, cfg.pattern("menghu"), "menghu", 14, warning=True)
    check("整组提示提前 4 拍", q.visible_groups(10) and not q.visible_groups(9))
    check("单格提示提前 2 拍",
          q.cell_visible(8, g, 0) and not q.cell_visible(7, g, 0))
    check("跑酷提示键位按拍可取", q.key_at(10) == "K" and q.key_at(11) == "L")

    # 2) 三档显示层级切换
    sess = runner.RunnerSession(cfg, seed=5)
    seen = [sess.cfg.display_level]
    for _ in range(2):
        seen.append(sess.cycle_display())
    check("三档显示层级可切换",
          seen == ["novice", "skilled", "master"] and seen[0] == "novice",
          f"{seen}")

    # 3) 组 B 参数与速度下限
    fs = [cfg.form_f(k) for k in cfg.forms]
    check("组 B 阵型 F 在 0.92–1.12",
          min(fs) >= 0.92 and max(fs) <= 1.12 and cfg.compound_rate == 0.035,
          f"F={min(fs):.2f}–{max(fs):.2f}")
    sess = runner.RunnerSession(cfg, seed=9)
    for _ in range(40):
        sess.step(None)
    check("速度下限大于 0", sess.min_speed >= cfg.v_floor > 0,
          f"min={sess.min_speed:.2f}")

    # 4) 撞阵叠加与线性恢复 + 单撞等效 4.2 拍
    check("单撞等效损失 ≈ 4.2 拍",
          abs(runner.measure_hit_loss(cfg) - cfg.hit_loss_beats) <= 0.15,
          f"{runner.measure_hit_loss(cfg):.2f}")
    tr = rm.CollisionTracker(max_stacks=cfg.max_hit_stacks, p_cap=cfg.p_cap,
                             enemies=cfg.enemies)
    for _ in range(6):
        tr.hit("light")
    p0 = tr.penalty()
    check("撞阵最多叠 3 层", tr.stacks == 3 and tr.max_stacks_seen == 3,
          f"stacks={tr.stacks}")
    for _ in range(int(cfg.enemies["light"]["t_recover"])):
        tr.tick()
    check("线性恢复后惩罚归零", tr.penalty() == 0.0 and p0 > 0.0)

    # 5) 缝隙穿过：预警内 2 键签名 → 2.3 拍等效损失
    check("缝隙穿过的等效损失 = 2.3 拍",
          abs(runner.measure_gap_loss(cfg) - cfg.gap_loss_beats) <= 0.01,
          f"{runner.measure_gap_loss(cfg):.2f}")
    s = runner.RunnerSession(cfg, seed=3)
    s.distance, s.elapsed_s = 56.5, 50.0
    evs = []
    for k in ("J", "K", "L", "J"):
        evs += s.step(k, 2.0)
    check("预警内换阵可穿缝不撞",
          s.gaps == 1 and s.hits == 0 and s.gap_debits == cfg.gap_loss_beats
          and s.formation == cfg.route[1].recommend,
          f"gaps={s.gaps} hits={s.hits} form={s.formation}")
    check("换阵触发双槌动作", any(e[0] == "double_whack" for e in evs))

    # 6) 计时与三段 split
    run = runner.headless_run("skilled", 17, cfg)
    check("通关计数与三段 split",
          len(run["splits"]) == 3 and all(
              run["splits"][i] < run["splits"][i + 1] for i in range(2))
          and run["splits"][-1] < run["time_s"] <= 140.0,
          f"splits={run['splits']} total={run['time_s']:.1f}")
    check("结算评级存在", run["rating"] in ("S", "A", "B", "C"))

    # 7) R 重开 ≤2 秒回到可操作
    t0 = time.perf_counter()
    s.restart()
    dt = time.perf_counter() - t0
    check("R 重开立即回到可操作", s.ready() and dt <= 2.0,
          f"{dt * 1000:.1f}ms")

    # 8) 无头整段与 runner_model 同参数误差 ≤2%
    for tier in ("novice", "skilled", "master"):
        cmp = runner.compare(tier, 17, cfg)
        check(f"{tier} 与 runner_model 误差 ≤2%", cmp["within_2pct"],
              f"{cmp['err'] * 100:.3f}%")

    # 9) 复利敏感性只改倍率、不改默认
    sens = runner.sensitivity(17, cfg)
    check("复利敏感性 2%/3.5%/5% 可算",
          set(sens) == {0.02, 0.035, 0.05} and cfg.compound_rate == 0.035,
          f"{sorted(sens)}")

    # 10) Boss 模式仍可进入，B 可切换
    tmp = tempfile.mkdtemp(prefix="yingge_runner_")
    path = os.path.join(tmp, "settings.json")
    f = scenes.Flow(path, core.BPM)
    check("标题 B 进入 Boss 选人",
          f.key("B", 0.0) == "to_roster" and f.mode == "boss")
    check("Boss 选人后仍走指南",
          f.key("ENTER", 0.0) == "to_guide" and f.scene == "guide")
    f2 = scenes.Flow(path, core.BPM, mode="runner")
    f2.key("ENTER", 0.0)
    f2.key("ENTER", 0.0)
    check("急行中 B 切 Boss 战",
          f2.key("B", 0.0) == "to_battle" and f2.scene == "battle")

    # 11) 渲染五种状态 0 异常（结算页用伪造完成态）
    ren = r.Renderer()
    ui = sui.SceneUI(ren)
    screen = pygame.Surface((1920, 1080))
    f3 = scenes.Flow(path, core.BPM)
    ui.draw_title(screen, f3, 0.0)
    s3 = runner.RunnerSession(cfg, seed=11)
    for _ in range(6):
        s3.step()
    s3.distance = 56.5
    s3.warning = {"target": cfg.route[1].recommend, "enemy": "shield",
                  "gap_side": "left", "start_beat": s3.beat, "contact_beat": 4,
                  "name": cfg.form_name(cfg.route[1].recommend),
                  "enemy_name": "盾墙"}
    ui.draw_runner(screen, f3, s3, 0.0)
    s3.gaps = 1
    s3.ui_flash["gap"] = s3.beat + 2
    ui.draw_runner(screen, f3, s3, 0.0)
    s3.ui_flash["hit"] = s3.beat + 3
    s3.hits = 1
    ui.draw_runner(screen, f3, s3, 0.0)
    s3.finished, s3.final_time_s = True, 89.6
    ui.draw_runner(screen, f3, s3, 0.0)
    check("Runner 五状态渲染 0 异常", True)


def test_runner_culture() -> None:
    """三层文化状态：环境判定 / 同键异义 / buff 互斥与封顶 / 求雨净损 / 双时间。"""
    cfg = runner.load_config()

    def new_sess(seg: int):
        s = runner.RunnerSession(cfg, seed=7, culture=True)
        s.seg = seg
        s.distance = sum(x.steps for x in cfg.route[:seg])
        s.warning = None
        s.queue.groups.clear()
        s._schedule_blocks()
        return s

    def feed(s, key: str, n: int = 4) -> list[tuple]:
        evs: list[tuple] = []
        for _ in range(n):
            evs += s.step(key, 0.0)
        return evs

    # 1) 三态由环境切换 + 分段解锁顺序
    states = [runner.RunnerSession(cfg, culture=True).state_for_seg(i)
              for i in range(3)]
    check("三态由环境正确切换：世俗→神圣→历史",
          states == ["secular", "holy", "history"]
          and cfg.route[0].kind == "secular"
          and cfg.route[1].kind == "holy"
          and cfg.route[2].kind == "history", f"{states}")
    s0 = runner.RunnerSession(cfg, culture=True)
    check("分段解锁：第一段世俗、第二段神圣、第三段历史",
          not s0._seg_challenging(0) and s0._seg_challenging(1)
          and not s0._seg_challenging(2),
          f"challenge={[s0._seg_challenging(i) for i in range(4)]}")

    # 2) 同键在不同态产生不同效果
    holy = new_sess(1)
    ev_holy = feed(holy, "J")
    sec = new_sess(0)
    ev_sec = feed(sec, "K")
    hist = new_sess(2)
    ev_hist = feed(hist, "J")
    check("同键异义：神圣 JJJJ = 破邪（净化 + 撞击）",
          holy.last_command == "attack" and holy.purifies == 1
          and holy.martial_count == 0,
          f"cmd={holy.last_command} purify={holy.purifies}")
    check("同键异义：世俗 KKKK = 巡游（人气）",
          sec.last_command == "march" and sec.patrol_count == 1
          and sec.popularity > 0 and sec.purifies == 0,
          f"cmd={sec.last_command} pop={sec.popularity:.1f}")
    check("同键异义：历史 JJJJ = 尚武（武艺）",
          hist.last_command == "martial" and hist.martial_count == 1
          and hist.purifies == 0,
          f"cmd={hist.last_command} martial={hist.martial}")

    # 3) 净化 3 次换 1 点鼓劲
    p = new_sess(1)
    p.purifies = 2
    p._apply_command("attack", [])
    check("净化 3 换 1 点鼓劲",
          p.purifies == 3 and p.drum_charge == 1,
          f"purify={p.purifies} drum={p.drum_charge}")

    # 4) 人气只降 Fever 门槛、不加速度
    a = new_sess(0)
    b = new_sess(0)
    b.popularity = cfg.culture.popularity_max
    feed(a, "K")
    feed(b, "K")
    check("人气满 → Fever 门槛 14→10",
          a.fever_threshold == 14 and b.fever_threshold == 10,
          f"{a.fever_threshold}→{b.fever_threshold}")
    check("人气只降门槛、不加速度",
          abs(a.current_speed - b.current_speed) < 1e-9,
          f"{a.current_speed:.4f} vs {b.current_speed:.4f}")

    # 5) 求雨净损 ≈1.6 拍 + 雨只作用于坡面速度与撞阵
    check("求雨净损 ≈ 1.6 拍",
          abs(runner.measure_rain_loss(cfg) - 1.6) <= 0.05,
          f"{runner.measure_rain_loss(cfg):.2f}")
    flat_a, flat_b = new_sess(0), new_sess(0)
    flat_b.rain_left = cfg.culture.rain_beats
    feed(flat_a, "K")
    feed(flat_b, "K")
    check("雨 buff 不作用于平地速度",
          abs(flat_a.current_speed - flat_b.current_speed) < 1e-9,
          f"{flat_a.current_speed:.4f} vs {flat_b.current_speed:.4f}")
    slope_a, slope_b = new_sess(2), new_sess(2)
    slope_a.rain_collect_left = cfg.culture.rain_collect_beats
    slope_b.rain_collect_left = cfg.culture.rain_collect_beats
    slope_b.rain_left = cfg.culture.rain_beats
    feed(slope_a, "J")
    feed(slope_b, "J")
    ratio = slope_b.current_speed / max(1e-9, slope_a.current_speed)
    check("雨 buff 只作用于坡面（+8% 速度）",
          abs(ratio - cfg.culture.rain_slope) <= 0.01,
          f"ratio={ratio:.3f}")

    tr = rm.CollisionTracker(max_stacks=cfg.max_hit_stacks, p_cap=cfg.p_cap,
                             enemies=cfg.enemies)
    tr.hit("shield")
    p_full = tr.penalty()
    tr2 = rm.CollisionTracker(max_stacks=cfg.max_hit_stacks, p_cap=cfg.p_cap,
                              enemies=cfg.enemies)
    tr2.hit("shield", factor=1.0 - cfg.culture.rain_loss_cut)
    check("雨/护阵减伤只作用于撞阵损失",
          abs(tr2.penalty() / max(1e-9, p_full)
              - (1.0 - cfg.culture.rain_loss_cut)) < 1e-9,
          f"P={tr2.penalty():.3f}/{p_full:.3f}")
    both = new_sess(1)
    both.guard_left = cfg.culture.guard_beats
    both.rain_left = cfg.culture.rain_beats
    check("同类 buff 同时只生效一个（取上限、不叠加）",
          abs(both._hit_cut() - max(cfg.culture.guard_loss_cut,
                                    cfg.culture.rain_loss_cut)) < 1e-9,
          f"cut={both._hit_cut():.2f}")

    # 6) 武艺满 3 生效一次：免费变阵把 2 拍压到 1 拍
    m = new_sess(2)
    for _ in range(3):
        feed(m, "J")
    check("武艺满 3 → 一次免费变阵可用",
          m.martial_ready and m.martial_count == 3,
          f"ready={m.martial_ready} count={m.martial_count}")
    m.formation = cfg.route[3].recommend
    m.warning = {"start_beat": 0, "target": cfg.route[3].recommend}
    m.switch_started_beat, m.switch_done_beat = 0, 2
    m.martial_used_switch = True
    ev = m._contact(3)
    check("武艺生效一次：变阵损失 2.3→1.3 拍",
          ev is not None and ev[0] == "gap"
          and abs(ev[1]["loss_beats"] - 1.3) <= 1e-9
          and not m.martial_used_switch,
          f"{ev[1]['loss_beats'] if ev else '-'}")
    ev2 = m._contact(3)
    check("武艺只生效一次（第二次回到 2.3 拍）",
          ev2 is not None and ev2[0] == "gap"
          and abs(ev2[1]["loss_beats"] - cfg.gap_loss_beats) <= 1e-9,
          "已消耗")

    # 7) 结算双时间 + 三段时间 + 与旧基线对比
    rep = runner.culture_report("skilled", 17, cfg)
    c = rep["culture"]
    check("结算同时给含 buff / 不含 buff 两个时间",
          c["time_with_buff"] > 0 and c["time_no_buff"] > 0
          and abs(c["time_with_buff"] - c["time_no_buff"]) > 1e-6,
          f"{c['time_with_buff']:.2f}s / {c['time_no_buff']:.2f}s")
    check("文化跑分输出三段时间与净化/求雨/尚武",
          len(c["splits"]) == 3 and c["purifies"] > 0
          and c["rain_count"] > 0 and c["martial_count"] > 0
          and c["stop_count"] == 1,
          f"splits={c['splits']} purify={c['purifies']} "
          f"rain={c['rain_count']} martial={c['martial_count']}")
    check("与不含文化系统基线的总时间可对比",
          rep["baseline"]["culture"] is False and rep["delta_s"] != 0.0,
          f"Δ={rep['delta_s']:.2f}s ({rep['delta_pct']:.1f}%)")

    # 8) 三种文化态渲染 0 异常
    ren = r.Renderer()
    ui = sui.SceneUI(ren)
    screen = pygame.Surface((1920, 1080))
    f = scenes.Flow(os.path.join(tempfile.mkdtemp(prefix="yingge_culture_"),
                                 "settings.json"), core.BPM)
    for seg, rain in ((1, False), (0, False), (2, True)):
        s = new_sess(seg)
        if rain:
            s.rain_left = cfg.culture.rain_beats
            s.rain_count = 1
        s.ui_flash["purify"] = s.beat + 2
        ui.draw_runner(screen, f, s, 0.0)
    check("文化三态 HUD/雨幕/民众渲染 0 异常", True)


def test_mode_switch() -> None:
    """第18-19轮默认流程 + mode.json 开关：关掉后跑酷/三态入口不可达。"""
    tmp = tempfile.mkdtemp(prefix="yingge_mode_")
    path = os.path.join(tmp, "settings.json")

    # 1) 仓库 mode.json 默认值
    m = scenes.load_mode()
    check("mode.json 默认：boss_1819 / runner off / culture off / ribbon / guide_v2",
          m["default_mode"] == "boss_1819"
          and m["runner_enabled"] is False
          and m["culture_enabled"] is False
          and m["hud_style"] == "ribbon"
          and m["guide_v2"] is True, f"{m}")

    # 2) 缺失 mode.json 时回落到同一组默认值
    m2 = scenes.load_mode(os.path.join(tmp, "missing.json"))
    check("mode.json 缺失 → 默认值不变",
          m2 == scenes.DEFAULT_MODE, f"{m2}")

    # 3) 默认入口：Title → Roster(Boss) → Guide → Battle 四场景可达
    f = scenes.Flow(path, core.BPM)
    check("默认标题 ENTER 进入 Boss 选人",
          f.key("ENTER", 0.0) == "to_roster" and f.mode == "boss"
          and f.runner_enabled is False and f.culture_enabled is False)
    check("Boss 主线四场景可达（Title→Roster→Guide→Battle）",
          f.scene == "roster"
          and f.key("ENTER", 0.0) == "to_guide" and f.scene == "guide"
          and f.key("G", 0.0) == "to_battle" and f.scene == "battle")

    # 4) runner 关闭：标题只有单入口，第二入口点击/热区都不可达
    f0 = scenes.Flow(path, core.BPM)
    check("runner 关闭时标题只有 enter 热区",
          [n for n, _ in f0.hotzones()] == ["enter"],
          f"{[n for n, _ in f0.hotzones()]}")
    check("runner 关闭时点击 Boss 第二入口无效",
          f0.click(*_rect_center(scenes.TITLE_BOSS_RECT), 0.0) is None
          and f0.scene == "title")
    check("runner 关闭时 Enter 不会落到 runner",
          f0.key("ENTER", 0.0) == "to_roster" and f0.mode == "boss")

    # 5) 开关全开：跑酷仍是默认入口，culture 跟随开关
    on_path = os.path.join(tmp, "mode_on.json")
    with open(on_path, "w", encoding="utf-8") as fh:
        json.dump({"default_mode": "runner_20", "runner_enabled": True,
                   "culture_enabled": True, "hud_style": "ribbon",
                   "guide_v2": True}, fh)
    fo = scenes.Flow(path, core.BPM, mode_path=on_path)
    check("开关全开：默认模式 = 急行，culture 打开",
          fo.mode == "runner" and fo.runner_enabled is True
          and fo.culture_enabled is True)
    check("开关全开：标题双入口存在",
          [n for n, _ in fo.hotzones()] == ["enter", "boss"])
    fo.key("ENTER", 0.0)
    check("开关全开：Roster Enter → Runner",
          fo.key("ENTER", 0.0) == "to_runner" and fo.scene == "runner")

    # 6) 显式 mode 参数仍可绕过默认配置（测试/调试用，不构成玩家入口）
    fx = scenes.Flow(path, core.BPM, mode="runner")
    check("显式 mode=runner 仍可构造（不改变默认入口）",
          fx.mode == "runner" and not fx.runner_enabled)


def _rect_center(rect) -> tuple[int, int]:
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


def main() -> int:
    pygame.init()
    test_judgement()
    test_cycle()
    test_auto_march()
    test_squad_and_formations()
    test_boss()
    test_boss_score()
    test_counter_matrix()
    test_phase_and_telemetry()
    test_fever()
    test_feedback_and_reset()
    test_terrain()
    test_pseudo3d()
    test_perspective_convergence()
    test_level_long()
    test_tilt_and_roll()
    test_boss_platform()
    test_reveal_and_tutorial()
    test_makeup()
    test_hero_frames()
    test_parallax_and_view()
    test_layer_variants()
    test_hud_sharpness()
    test_hud_font_layer()
    test_hud_motion()
    test_input_and_ribbon()
    test_judgement_injection()
    test_scene_flow()
    test_mode_switch()
    test_scene_mouse_render()
    test_runner_model()
    test_runner_scene()
    test_runner_culture()
    test_assets()
    if FAILS:
        print("SELFTEST: FAIL")
        for f in FAILS:
            print("  -", f)
        return 1
    print("SELFTEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
