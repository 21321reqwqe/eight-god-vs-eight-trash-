# -*- coding: utf-8 -*-
"""
模拟运行模块（GUI 与 main.py 共用）。

本模块是所有对局运行的唯一来源，且在 Windows 多进程 spawn 时被子进程 import，
因此不得在模块顶层创建任何进程/线程/窗口资源。

对外接口：
  run_batch(cfg, games, workers, seed_offset, progress_cb=None)
      -> dict（胜率、平均回合、平均手牌、伤害、技能触发等聚合结果）
  run_single(cfg, seed)
      -> (result, events, stats)   单局详细日志
"""

import copy
import os
from multiprocessing import Pool

from engine import Game


def _play_one(args):
    """多进程 worker：跑一局，返回 (结果, 统计)。args=(cfg, seed)。"""
    cfg, seed = args
    g = Game(cfg=cfg, seed=seed)
    result = g.run()
    return result, g.stats


def run_single(cfg, seed):
    """跑一局带详细日志。返回 (result, events, stats)。"""
    g = Game(cfg=cfg, seed=seed, log=True)
    result = g.run()
    return result, g.events, g.stats


def _merge_stats(acc, stats, a_name, b_name):
    """把一局的 stats 合并进聚合 acc。"""
    acc['turns_total'] += stats.get('turns', 0)
    acc['turns_list'].append(stats.get('turns', 0))
    for name in (a_name, b_name):
        acc['sum_hand'][name] += stats.get('sum_hand', {}).get(name, 0)
        acc['hand_samples'][name] += stats.get('hand_samples', {}).get(name, 0)
        acc['dmg'][name] += stats.get('dmg_dealt', {}).get(name, 0)
    for sk, cnt in stats.get('skill_triggers', {}).items():
        acc['skill_triggers'][sk] = acc['skill_triggers'].get(sk, 0) + cnt


def _empty_acc(a_name, b_name):
    return {
        'turns_total': 0,
        'turns_list': [],
        'sum_hand': {a_name: 0, b_name: 0},
        'hand_samples': {a_name: 0, b_name: 0},
        'dmg': {a_name: 0, b_name: 0},
        'skill_triggers': {},
    }


def run_batch(cfg, games, workers=None, seed_offset=0, progress_cb=None):
    """跑 games 局，聚合统计。cfg 会被深拷贝，workers=None 时自动取 CPU 核数。

    progress_cb(completed, total) 在每局完成后调用（由 GUI 用于进度显示）。
    返回 dict：
      games / win_a / win_b / draws / a_rate / b_rate / draw_rate
      avg_turns / avg_hand{a,b} / dmg{a,b} / skill_triggers / turns_list
      a_name / b_name
    """
    if workers is None:
        workers = os.cpu_count() or 1

    rules = cfg['RULES']
    a_name, b_name = rules['A_NAME'], rules['B_NAME']
    base = default_agg(a_name, b_name)
    # 引擎返回的 result 是实际武将名（A_NAME/B_NAME），不能用硬编码 'A'/'B'
    wins = {a_name: 0, b_name: 0, 'draw': 0}
    done = 0

    def _count(result, stats):
        nonlocal done
        wins[result] += 1
        _merge_stats(base, stats, a_name, b_name)
        done += 1
        if progress_cb:
            progress_cb(done, games)

    # 每个 worker 进程用独立深拷贝的 cfg（避免共享默认 dict 引用）
    tasks = [(copy.deepcopy(cfg), seed_offset + i) for i in range(games)]

    if workers <= 1 or games <= 1:
        for args in tasks:
            result, stats = _play_one(args)
            _count(result, stats)
    else:
        with Pool(workers) as pool:
            for result, stats in pool.imap_unordered(_play_one, tasks):
                _count(result, stats)

    n = games
    base.update({
        'games': n,
        'win_a': wins[a_name], 'win_b': wins[b_name], 'draws': wins['draw'],
        'a_rate': wins[a_name] / n, 'b_rate': wins[b_name] / n, 'draw_rate': wins['draw'] / n,
        'avg_turns': base['turns_total'] / n if n else 0,
        'avg_hand': {
            a_name: (base['sum_hand'][a_name] / base['hand_samples'][a_name])
                    if base['hand_samples'][a_name] else 0,
            b_name: (base['sum_hand'][b_name] / base['hand_samples'][b_name])
                    if base['hand_samples'][b_name] else 0,
        },
        'a_name': a_name, 'b_name': b_name,
    })
    return base


def default_agg(a_name, b_name):
    """与 run_batch 内部聚合结构同构的空聚合（供 GUI 首次渲染占位）。"""
    acc = _empty_acc(a_name, b_name)
    acc.update({
        'games': 0, 'win_a': 0, 'win_b': 0, 'draws': 0,
        'a_rate': 0.0, 'b_rate': 0.0, 'draw_rate': 0.0,
        'avg_turns': 0.0, 'avg_hand': {a_name: 0.0, b_name: 0.0},
        'a_name': a_name, 'b_name': b_name,
    })
    return acc
