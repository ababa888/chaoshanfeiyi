"""急行模式无头跑分：三档整段、与 runner_model 误差、复利敏感性。

用法：
    py -3 prototype-yingge/tools/runner_headless.py
    py -3 prototype-yingge/tools/runner_headless.py --seed 17 --tier skilled
    py -3 prototype-yingge/tools/runner_headless.py --rate 0.05

不依赖 pygame；默认输出三档时间、撞阵/变阵/缺口次数、平均速度、Perfect 率，
并给出与 runner_model 同参数的误差（要求 ≤2%）。
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import runner  # noqa: E402


def one(tier: str, seed: int, rate: float | None) -> None:
    cfg = runner.load_config()
    run = runner.headless_run(tier, seed, cfg, compound_rate=rate)
    model = runner.model_run(tier, seed, cfg, compound_rate=rate)
    err = abs(run["time_s"] - model["time_s"]) / max(1e-9, model["time_s"])
    print(f"[{tier}] seed={seed} rate={cfg.compound_rate * 100:.1f}%")
    print(f"  通关 {run['time_s']:.2f}s  评级 {run['rating']}  "
          f"撞阵 {run['hits']}  变阵 {run['switches']}  缺口 {run['gaps']}")
    print(f"  Perfect {run['perfect_rate'] * 100:.1f}%  "
          f"平均 {run['avg_speed']:.3f} 步/拍  split {run['splits']}")
    print(f"  runner_model {model['time_s']:.2f}s  误差 {err * 100:.3f}%  "
          f"{'PASS' if err <= 0.02 else 'FAIL'}")


def culture_one(tier: str, seed: int) -> None:
    cfg = runner.load_config()
    rep = runner.culture_report(tier, seed, cfg)
    c, b = rep["culture"], rep["baseline"]
    print(f"[{tier}] seed={seed} 三层文化状态")
    print(f"  含 buff {c['time_with_buff']:.2f}s  "
          f"不含 buff {c['time_no_buff']:.2f}s  三段 {c['splits']}")
    print(f"  撞阵 {c['hits']}  净化 {c['purifies']}（鼓劲 ×{c['drum_charge']}）  "
          f"求雨 {c['rain_count']}  尚武 {c['martial_count']}  "
          f"护阵 {c['guard_count']}  驻足 {c['stop_count']}")
    print(f"  人气 {c['popularity']:.0f} → Fever 门槛 {c['fever_threshold']}  "
          f"Perfect {c['perfect_rate'] * 100:.1f}%  "
          f"平均 {c['avg_speed']:.3f} 步/拍")
    print(f"  旧基线 {b['time_s']:.2f}s  Δ {rep['delta_s']:+.2f}s "
          f"({rep['delta_pct']:+.2f}%)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=("novice", "skilled", "master"))
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--rate", type=float, default=None)
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--culture", action="store_true")
    args = ap.parse_args()

    if args.sensitivity:
        rows = runner.sensitivity(args.seed)
        print("复利敏感性（只改倍率，默认 3.5% 不变）")
        for rate, row in rows.items():
            print(f"  {rate * 100:.1f}%：新手 {row['novice_s']:.2f}s  "
                  f"高手–熟练 {row['master_minus_skilled_pct'] * 100:.2f}%")
        return 0

    tiers = (args.tier,) if args.tier else ("novice", "skilled", "master")
    for tier in tiers:
        if args.culture:
            culture_one(tier, args.seed)
        else:
            one(tier, args.seed, args.rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
