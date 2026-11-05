"""无头对照：参考口径复现 + 组 A / 组 B 三档模拟 + 差距归属。

运行：py -3 prototype-yingge/tools/runner_compare.py
不读素材、不初始化 pygame，可直接在无显示器环境跑。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import runner_model as rm

SEED = 17


def _fmt_plan(plan) -> str:
    counts: dict[str, int] = {}
    for key in plan:
        name = rm.FORMS["A"][key][0]
        counts[name] = counts.get(name, 0) + 1
    return " / ".join(f"{name}×{n}" for name, n in counts.items())


def print_reference() -> None:
    print("== 参考口径（文档 §4.6 解析式：T = L/(v_base·F·C) + Σt_hit）==")
    print(f"{'档位':<6}{'有效F':>7}{'C':>7}{'撞阵拍':>7}{'拍数':>8}{'时间':>9}{'文档':>8}{'差':>8}")
    ref = rm.reference_times()
    for tier in ("novice", "skilled", "master"):
        cfg = rm.DOC_REF[tier]
        beats = rm.ROUTE_STEPS / (rm.V_BASE * cfg["F"] * cfg["C"]) + cfg["hit_beats"]
        t = ref[tier]
        doc = rm.DOC_TIMES[tier]
        print(f"{tier:<6}{cfg['F']:>7.2f}{cfg['C']:>7.3f}{cfg['hit_beats']:>7.1f}"
              f"{beats:>8.1f}{t:>8.1f}s{doc:>7.1f}s{t - doc:>+7.1f}s")
    print()


def print_group(result: dict) -> None:
    g = result["group"]
    print(f"== 组 {g}：σ 逐拍模拟（seed={result['seed']}，240 步 4 段）==")
    print(f"{'档位':<6}{'时间':>8}{'拍数':>7}{'撞阵':>6}{'P/G/M':>16}"
          f"{'最低速':>8}{'复利层':>7}  每段平均速度(步/拍)")
    for tier in ("novice", "skilled", "master"):
        r = result["runs"][tier]
        speeds = " ".join(f"{v:.2f}" for v in r.seg_speeds)
        print(f"{tier:<6}{r.time_s:>7.1f}s{r.beats:>7d}{r.hits:>6d}"
              f"  {r.p_perfect:.2f}/{r.p_good:.2f}/{r.p_miss:.2f}"
              f"{r.min_speed:>8.2f}{r.max_compound:>7d}  {speeds}")
    print(f"  选阵轨迹：新手 {_fmt_plan(result['runs']['novice'].plan)}")
    print(f"            熟练 {_fmt_plan(result['runs']['skilled'].plan)}")
    print(f"            高手 {_fmt_plan(result['runs']['master'].plan)}")
    a = result["attr_s"]
    s = result["share"]
    print(f"  差距归属（新手→高手，共 {a['total_s']:.1f}s）："
          f"选阵 {s['form'] * 100:.0f}%（{a['form']:+.1f}s）/ "
          f"合拍 {s['rhythm'] * 100:.0f}%（{a['rhythm']:+.1f}s）/ "
          f"撞阵 {s['collision'] * 100:.0f}%（{a['collision']:+.1f}s）")
    print(f"  高手 – 熟练 = {result['gap_s']:.1f}s（{result['gap_pct'] * 100:.1f}%）")
    print()


def main() -> int:
    print_reference()
    a = rm.evaluate("A", SEED)
    b = rm.evaluate("B", SEED)
    print_group(a)
    print_group(b)
    print("== 组 B 指标 ==")
    print(f"  合拍 ≥ 选阵：{b['share']['rhythm'] * 100:.0f}% vs {b['share']['form'] * 100:.0f}%"
          f" → {'PASS' if b['criteria']['rhythm_ge_form'] else 'FAIL'}")
    print(f"  高手–熟练 ≥ 12%：{b['gap_pct'] * 100:.1f}%"
          f" → {'PASS' if b['criteria']['gap_ge_12pct'] else 'FAIL'}")
    print(f"  对照：组 A 同两条 → "
          f"合拍 {a['share']['rhythm'] * 100:.0f}% vs 选阵 {a['share']['form'] * 100:.0f}%、"
          f"高手–熟练 {a['gap_pct'] * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
