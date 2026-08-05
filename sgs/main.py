# -*- coding: utf-8 -*-
"""
三国杀 1v1 对战胜率模拟入口。

用法：
  python main.py -n 1000            # 跑 1000 局（多进程，默认用满 CPU）
  python main.py -n 1 --log         # 单局，打印完整事件日志
  python main.py -n 5000 -w 8       # 指定并行进程数
  python main.py -n 1000 -s 42      # 固定随机种子偏移，结果可复现

胜负判定：见 engine._timeout_winner（超时按体力+牌数，否则平局）。

所有对局运行统一走 simulator 模块（与 GUI 共用同一套实现）。
"""

import argparse

from config import default_config
from simulator import run_batch, run_single


def main():
    ap = argparse.ArgumentParser(description='三国杀 1v1 对战胜率模拟')
    ap.add_argument('-n', '--games', type=int, default=1000, help='对局数（默认1000）')
    ap.add_argument('-w', '--workers', type=int, default=None, help='并行进程数（默认=CPU核数）')
    ap.add_argument('-s', '--seed', type=int, default=0, help='随机种子偏移（默认0）')
    ap.add_argument('--log', action='store_true', help='单局详细日志（自动只跑1局）')
    args = ap.parse_args()

    if args.log:
        result, events, _stats = run_single(default_config(), args.seed)
        print('\n'.join(events))
        print()
        if result == 'draw':
            print('结果：平局（超时）')
        else:
            print(f'结果：{result} 获胜')
        return

    r = run_batch(default_config(), args.games, args.workers, args.seed)
    print(f'共 {r["games"]} 局（{args.workers or "全部核"} 进程，seed 偏移 {args.seed}）')
    print(f'A 胜 {r["win_a"]:>6}  {r["a_rate"] * 100:6.1f}%')
    print(f'B 胜 {r["win_b"]:>6}  {r["b_rate"] * 100:6.1f}%')
    print(f'平局 {r["draws"]:>6}  {r["draw_rate"] * 100:6.1f}%')


if __name__ == '__main__':
    main()
