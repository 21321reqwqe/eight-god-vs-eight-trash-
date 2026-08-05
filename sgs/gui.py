# -*- coding: utf-8 -*-
"""
三国杀 1v1 对战胜率模拟器 — Tkinter 可视化 + 可调节界面。

运行：python gui.py

三个页签：
  1) 设置   —— 调节规则/AI 参数（滑块/下拉/勾选）、勾选双方技能、运行模拟
  2) 结果   —— 胜率条、平均回合、伤害分解、技能触发、回合分布（Canvas 手绘）
  3) 单局回放 —— 逐行播放对局日志（播放/暂停/单步/调速）

技术要点：
  - 模拟在后台线程跑（multiprocessing 或单进程），结果经 queue 回传主线程刷新。
  - 所有对局运行统一走 simulator.run_batch / run_single。
  - 配置从 config.py 读默认值，控件按 ui_spec 元数据自动生成。
  - 界面设置在关闭时自动保存到 gui_settings.json，启动自动恢复。
"""

import ctypes
import copy
import json
import os
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

from config import default_config
from skills import ALL_SKILLS_A, ALL_SKILLS_B, KNOWN_SKILLS
import ui_spec
from simulator import run_batch, run_single

APP_TITLE = '三国杀 1v1 胜率模拟器'
FONT = 'Microsoft YaHei'
SETTINGS_FILE = 'gui_settings.json'

COLORS = {
    'a': '#e05d5d',
    'b': '#5d8fe0',
    'draw': '#9aa0a6',
    'bg': '#f4f4f4',
    'bar_bg': '#e8e8e8',
    'text': '#202124',
    'muted': '#5f6368',
}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry('1200x780')
        self.root.minsize(1000, 640)

        self.cfg_defaults = default_config()
        self.msg_q = queue.Queue()
        self.busy = False

        self._combo_opts = {}   # key -> [(显示, 值)]
        self.widgets = {}       # key -> 控件
        self.skill_vars = {}    # {'A': {技能名: BooleanVar}, 'B': {...}}

        self.replay = {'events': [], 'idx': 0, 'playing': False,
                       'speed': 200, 'after': None}

        self._build_ui()

        self._load_settings_quiet(SETTINGS_FILE)
        self.root.after(100, self._poll_queue)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True)

        self.tab_setup = ttk.Frame(nb, padding=6)
        self.tab_result = ttk.Frame(nb, padding=6)
        self.tab_replay = ttk.Frame(nb, padding=6)
        nb.add(self.tab_setup, text='  设置  ')
        nb.add(self.tab_result, text='  胜率结果  ')
        nb.add(self.tab_replay, text='  单局回放  ')

        self._build_tab_setup()
        self._build_tab_result()
        self._build_tab_replay()

    # ---------- 页签 1：设置 ----------
    def _build_tab_setup(self):
        t = self.tab_setup
        # 顶部：运行参数 + 操作按钮
        top = ttk.Frame(t)
        top.pack(fill='x', pady=(0, 6))

        self.run_defaults = {
            'games': 2000, 'workers': os.cpu_count() or 1, 'seed_offset': 0,
        }
        self.run_vars = {}
        for spec in ui_spec.INDEX.values():
            if spec['scope'] != 'run':
                continue
            lbl = ttk.Label(top, text=spec['label'] + ':')
            lbl.pack(side='left', padx=(6, 0))
            var = tk.IntVar(value=self.run_defaults.get(spec['key'], spec.get('default', 0)))
            self.run_vars[spec['key']] = var
            spin = ttk.Spinbox(top, from_=spec.get('min'), to=spec.get('max'),
                               increment=spec.get('step', 1), textvariable=var, width=9)
            spin.pack(side='left', padx=(2, 8))

        ttk.Button(top, text='开始模拟', command=self._start_batch).pack(side='left', padx=6)
        self.btn_stop = ttk.Button(top, text='停止', command=self._cancel, state='disabled')
        self.btn_stop.pack(side='left', padx=2)
        ttk.Button(top, text='恢复默认', command=self._reset_defaults).pack(side='left', padx=6)
        ttk.Button(top, text='保存配置…', command=self._save_settings_dialog).pack(side='left', padx=2)
        ttk.Button(top, text='载入配置…', command=self._load_settings_dialog).pack(side='left', padx=2)

        self.progress_var = tk.StringVar(value='')
        ttk.Label(top, textvariable=self.progress_var).pack(side='right', padx=8)

        # 中部：滚动参数区
        body = ttk.Frame(t)
        body.pack(fill='both', expand=True)

        canvas = tk.Canvas(body, highlightthickness=0, bg=COLORS['bg'])
        sb = ttk.Scrollbar(body, orient='vertical', command=canvas.yview)
        self.params_frame = ttk.Frame(canvas)
        self.params_frame.bind(
            '<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=self.params_frame, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        # 参数分组
        row_idx = 0
        for sec in ui_spec.SECTIONS:
            sec_frame = ttk.LabelFrame(self.params_frame, text='　' + sec['title'] + '　',
                                       padding=8)
            sec_frame.grid(row=row_idx, column=0, sticky='ew', padx=4, pady=4)
            row_idx += 1
            self.params_frame.columnconfigure(0, weight=1)
            self._build_section(sec_frame, sec)

        # 技能区（A/B 两栏）
        skill_frame = ttk.LabelFrame(self.params_frame, text='　武将技能（勾选生效）　', padding=8)
        skill_frame.grid(row=row_idx, column=0, sticky='ew', padx=4, pady=4)
        col_a = ttk.Frame(skill_frame)
        col_b = ttk.Frame(skill_frame)
        col_a.pack(side='left', fill='both', expand=True, padx=(0, 10))
        col_b.pack(side='left', fill='both', expand=True)

        for side, frame, defaults in (('A', col_a, ALL_SKILLS_A),
                                      ('B', col_b, ALL_SKILLS_B)):
            self.skill_vars[side] = {}
            ttk.Label(frame, text=f'{side} 武将技能', font=(FONT, 12, 'bold')).pack(anchor='w')
            wrap = ttk.Frame(frame)
            wrap.pack(fill='x')
            for i, name in enumerate(KNOWN_SKILLS):
                var = tk.BooleanVar(value=(name in defaults))
                self.skill_vars[side][name] = var
                cb = ttk.Checkbutton(wrap, text=name, variable=var)
                cb.grid(row=i // 5, column=i % 5, sticky='w', padx=4, pady=2)

        # 鼠标滚轮滚动（只绑设置区子树，避免干扰其他页签）
        def _onwheel(e):
            canvas.yview_scroll(int(-e.delta / 120), 'units')

        def _bind_wheel_recursive(w):
            w.bind('<MouseWheel>', _onwheel)
            for child in w.winfo_children():
                _bind_wheel_recursive(child)

        _bind_wheel_recursive(canvas)
        _bind_wheel_recursive(self.params_frame)

    def _build_section(self, parent, sec):
        frame = ttk.Frame(parent)
        frame.pack(fill='x')
        # 每个参数一行：label + 控件 + 说明（hover 用 help 做 tooltip 简化：拼接在右侧灰色文本）
        for i, spec in enumerate(sec['params']):
            key = spec['key']
            lbl = ttk.Label(frame, text=spec['label'] + '：')
            lbl.grid(row=i, column=0, sticky='w', padx=(2, 8), pady=3)
            w = self._make_widget(frame, spec)
            self.widgets[key] = w
            w.grid(row=i, column=1, sticky='w', padx=2, pady=3)
            if spec.get('help'):
                ttk.Label(frame, text=spec['help'], foreground=COLORS['muted']).grid(
                    row=i, column=2, sticky='w', padx=(10, 0), pady=3)
            frame.columnconfigure(2, weight=1)

    def _make_widget(self, parent, spec):
        typ = spec['type']
        key = spec['key']
        if typ == 'bool':
            var = tk.BooleanVar(value=self._default_of(spec))
            cb = ttk.Checkbutton(parent, variable=var)
            cb.var = var
            return cb
        if typ == 'select':
            opts = spec['options']
            pairs = [(o[0] if isinstance(o, tuple) else o,
                      o[1] if isinstance(o, tuple) else o) for o in opts]
            self._combo_opts[key] = pairs
            current = self._default_of(spec)
            displays = [d for d, _v in pairs]
            box = ttk.Combobox(parent, state='readonly', width=22, values=displays)
            idx = next((i for i, (_d, v) in enumerate(pairs) if v == current), 0)
            box.current(idx)
            return box
        if typ == 'text':
            ent = ttk.Entry(parent, width=14)
            ent.insert(0, str(self._default_of(spec)))
            return ent
        if typ == 'int':
            var = tk.StringVar(value=str(self._default_of(spec)))
            spin = ttk.Spinbox(parent, from_=spec.get('min'), to=spec.get('max'),
                               increment=spec.get('step', 1), textvariable=var, width=7)
            spin.var = var
            return spin
        # float：滑块 + 数值标签（holder 容器并排放）
        holder = ttk.Frame(parent)
        scale = tk.Scale(holder, from_=spec['min'], to=spec['max'], orient='horizontal',
                         resolution=spec.get('step', 0.01), length=180, showvalue=False,
                         bg=COLORS['bg'], highlightthickness=0)
        val_lbl = ttk.Label(holder, text=f"{self._default_of(spec):g}", width=6)
        scale.set(self._default_of(spec))
        scale.config(command=lambda v, s=scale, l=val_lbl: l.config(text=f'{float(v):g}'))
        scale.pack(side='left')
        val_lbl.pack(side='left', padx=4)
        holder._scale = scale
        holder._val_lbl = val_lbl
        return holder

    def _default_of(self, spec):
        scope = spec['scope']
        if scope == 'run':
            return spec.get('default')
        d = self.cfg_defaults['RULES'] if scope == 'rules' else self.cfg_defaults['STRATEGY']
        return d.get(spec['key'])

    # ---------- 页签 2：结果 ----------
    def _build_tab_result(self):
        t = self.tab_result
        self.result_host = ttk.Frame(t)
        self.result_host.pack(fill='both', expand=True)
        ttk.Label(t, text='（点击「开始模拟」后在这里显示结果）',
                  foreground=COLORS['muted']).pack(pady=4)

    def _show_result(self, res):
        # 清空重建
        for w in self.result_host.winfo_children():
            w.destroy()
        host = self.result_host

        # 汇总文字
        a, b = res['a_name'], res['b_name']
        head = (f'共 {res["games"]} 局　|　A[{a}] 胜 {res["win_a"]} '
                f'（{res["a_rate"]*100:.1f}%）　|　B[{b}] 胜 {res["win_b"]} '
                f'（{res["b_rate"]*100:.1f}%）　|　平局 {res["draws"]} '
                f'（{res["draw_rate"]*100:.1f}%）')
        ttk.Label(host, text=head, font=(FONT, 13, 'bold')).pack(anchor='w', pady=(0, 2))
        stats_txt = (f'平均回合 {res["avg_turns"]:.1f}　|　平均手牌 A[{a}] {res["avg_hand"][a]:.1f}　'
                     f'B[{b}] {res["avg_hand"][b]:.1f}　|　总伤害 A[{a}] {res["dmg"][a]:.0f}　'
                     f'B[{b}] {res["dmg"][b]:.0f}')
        ttk.Label(host, text=stats_txt, font=(FONT, 11)).pack(anchor='w', pady=(0, 8))

        # 胜率条
        ttk.Label(host, text='胜率分布', font=(FONT, 12, 'bold')).pack(anchor='w')
        c = tk.Canvas(host, height=40, bg='white', highlightthickness=0)
        c.pack(fill='x', pady=(2, 10))
        self._draw_win_bar(c, res)

        # 伤害 + 平均手牌 + 技能触发（三栏）
        cols = ttk.Frame(host)
        cols.pack(fill='both', expand=True)
        left = ttk.Frame(cols)
        right = ttk.Frame(cols)
        left.pack(side='left', fill='both', expand=True, padx=(0, 12))
        right.pack(side='left', fill='both', expand=True)

        self._draw_metric_panel(left, '伤害与手牌对比', res)
        self._draw_skill_panel(right, '技能触发次数', res)

    def _draw_win_bar(self, canvas, res):
        canvas.delete('all')
        w = canvas.winfo_width()
        if w < 20:
            if not getattr(canvas, '_retried', False):
                canvas._retried = True
                canvas.after_idle(lambda: self._draw_win_bar(canvas, res))
                return
            w = 1000
        h = 34
        y0 = 6
        bar_w = max(w - 10, 10)
        items = [
            (f'A[{res["a_name"]}] {res["a_rate"]*100:.1f}%', res['a_rate'], COLORS['a']),
            (f'B[{res["b_name"]}] {res["b_rate"]*100:.1f}%', res['b_rate'], COLORS['b']),
            (f'平局 {res["draw_rate"]*100:.1f}%', res['draw_rate'], COLORS['draw']),
        ]
        x = 5
        for label, frac, color in items:
            if frac <= 0:
                continue
            bw = int(bar_w * frac)
            if bw < 2 and frac > 0:
                bw = 2
            canvas.create_rectangle(x, y0, x + bw, y0 + h, fill=color, outline='')
            canvas.create_text(x + bw / 2, y0 + h / 2, text=label,
                               fill='white' if bw > 80 else COLORS['text'], font=(FONT, 11))
            x += bw
        if x <= 5:
            canvas.create_text(10, y0 + h / 2, anchor='w', text='（无数据）', fill=COLORS['muted'])

    def _draw_metric_panel(self, host, title, res):
        ttk.Label(host, text=title, font=(FONT, 12, 'bold')).pack(anchor='w', pady=(0, 4))
        a, b = res['a_name'], res['b_name']
        data = [
            (f'A[{a}] 总伤害', res['dmg'][a], COLORS['a']),
            (f'B[{b}] 总伤害', res['dmg'][b], COLORS['b']),
            (f'A[{a}] 平均手牌', res['avg_hand'][a], COLORS['a']),
            (f'B[{b}] 平均手牌', res['avg_hand'][b], COLORS['b']),
        ]
        c = tk.Canvas(host, height=30 * len(data) + 10, bg='white', highlightthickness=0)
        c.pack(fill='x')
        self._draw_hbars(c, data)
        # 回合分布直方图
        ttk.Label(host, text='回合数分布', font=(FONT, 12, 'bold')).pack(anchor='w', pady=(10, 4))
        hc = tk.Canvas(host, height=140, bg='white', highlightthickness=0)
        hc.pack(fill='x')
        self._draw_histogram(hc, res.get('turns_list', []))

    def _draw_skill_panel(self, host, title, res):
        ttk.Label(host, text=title, font=(FONT, 12, 'bold')).pack(anchor='w', pady=(0, 4))
        triggers = res.get('skill_triggers', {})
        if not triggers:
            ttk.Label(host, text='（本批无技能触发记录）', foreground=COLORS['muted']).pack(anchor='w')
            return
        items = sorted(triggers.items(), key=lambda kv: -kv[1])[:12]
        data = [(f'{name} ×{cnt}', cnt, COLORS['a' if name in ALL_SKILLS_A else 'b'])
                for name, cnt in items]
        c = tk.Canvas(host, height=24 * len(data) + 10, bg='white', highlightthickness=0)
        c.pack(fill='x')
        self._draw_hbars(c, data)

    def _draw_hbars(self, canvas, data):
        """data = [(label, value, color)]，按最大值归一画横向条。"""
        canvas.delete('all')
        w = canvas.winfo_width()
        if w < 20:
            if not getattr(canvas, '_retried', False):
                canvas._retried = True
                canvas.after_idle(lambda: self._draw_hbars(canvas, data))
                return
            w = 700
        mx = max((v for _l, v, _c in data), default=1) or 1
        row_h = 24
        for i, (label, value, color) in enumerate(data):
            y = 4 + i * row_h
            canvas.create_text(6, y + 8, anchor='w', text=f'{label}: {value:.1f}',
                               font=(FONT, 11), fill=COLORS['text'])
            bx = 170
            bw = max(int((w - bx - 20) * value / mx), 2) if value > 0 else 0
            canvas.create_rectangle(bx, y + 2, bx + bw, y + 16, fill=color, outline='')

    def _draw_histogram(self, canvas, turns_list):
        canvas.delete('all')
        w = canvas.winfo_width()
        if w < 20:
            if not getattr(canvas, '_retried', False):
                canvas._retried = True
                canvas.after_idle(lambda: self._draw_histogram(canvas, turns_list))
                return
            w = 700
        h = 130
        if not turns_list:
            canvas.create_text(10, 20, anchor='w', text='（无数据）', fill=COLORS['muted'])
            return
        width = 20
        n_bins = max((max(turns_list) - 1) // width + 1, 1)
        bins = [0] * n_bins
        for t in turns_list:
            bins[min((t - 1) // width, n_bins - 1)] += 1
        mx = max(bins) or 1
        plot_w = max(w - 50, 50)
        bw = plot_w / n_bins
        for i, cnt in enumerate(bins):
            x0 = 45 + i * bw
            bar_h = (h - 30) * cnt / mx
            canvas.create_rectangle(x0 + 1, h - 20 - bar_h, x0 + bw - 1, h - 20,
                                    fill=COLORS['b'], outline='')
            canvas.create_text(x0 + bw / 2, h - 12, text=str(i * width + 1),
                               font=(FONT, 9), fill=COLORS['muted'])
        canvas.create_text(20, 10, anchor='w', text='回合数区间', font=(FONT, 10),
                           fill=COLORS['muted'])

    # ---------- 页签 3：单局回放 ----------
    def _build_tab_replay(self):
        t = self.tab_replay
        top = ttk.Frame(t)
        top.pack(fill='x', pady=(0, 6))
        ttk.Label(top, text='种子:').pack(side='left')
        self.replay_seed = tk.IntVar(value=1)
        ttk.Spinbox(top, from_=0, to=999999, textvariable=self.replay_seed,
                    width=8).pack(side='left', padx=(2, 12))
        self.btn_play = ttk.Button(top, text='▶ 开始单局', command=self._start_single)
        self.btn_play.pack(side='left', padx=4)
        self.btn_toggle = ttk.Button(top, text='⏸ 暂停', command=self._toggle_play,
                                     state='disabled')
        self.btn_toggle.pack(side='left', padx=2)
        self.btn_step = ttk.Button(top, text='单步', command=self._step, state='disabled')
        self.btn_step.pack(side='left', padx=2)
        self.btn_reset = ttk.Button(top, text='复位', command=self._replay_reset,
                                    state='disabled')
        self.btn_reset.pack(side='left', padx=2)
        ttk.Label(top, text='  速度:').pack(side='left', padx=(12, 0))
        self.speed_var = tk.IntVar(value=200)
        tk.Scale(top, from_=20, to=800, orient='horizontal', variable=self.speed_var,
                 resolution=10, length=120, showvalue=False, bg=COLORS['bg'],
                 highlightthickness=0).pack(side='left')
        self.replay_status = ttk.Label(top, text='', foreground=COLORS['muted'])
        self.replay_status.pack(side='right', padx=8)

        # 状态栏：当前回合双方 hp/手牌
        self.board_status = ttk.Label(t, text='', font=(FONT, 12, 'bold'))
        self.board_status.pack(fill='x', pady=(0, 4))

        wrap = ttk.Frame(t)
        wrap.pack(fill='both', expand=True)
        self.log_text = tk.Text(wrap, wrap='none', font=('Consolas', 10),
                                state='disabled', bg='#fdfdfd', fg='#222')
        l_sb = ttk.Scrollbar(wrap, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=l_sb.set)
        h_sb = ttk.Scrollbar(wrap, orient='horizontal', command=self.log_text.xview)
        self.log_text.configure(xscrollcommand=h_sb.set)
        self.log_text.pack(side='left', fill='both', expand=True)
        l_sb.pack(side='right', fill='y')
        h_sb.pack(side='bottom', fill='x')
        self.log_text.tag_configure('turn', foreground='#b3530e', font=(FONT, 13, 'bold'))
        self.log_text.tag_configure('end', foreground='#0a7d33', font=(FONT, 12, 'bold'))
        self.log_text.bind('<MouseWheel>',
                           lambda e: self.log_text.yview_scroll(int(-e.delta / 120), 'units'))

    def _start_single(self):
        if self.busy:
            return
        cfg = self._build_cfg()
        seed = self.replay_seed.get()
        self.busy = True
        self.btn_play.config(state='disabled')
        self.replay_status.config(text='跑局中…')
        threading.Thread(target=self._single_thread, args=(cfg, seed), daemon=True).start()

    def _single_thread(self, cfg, seed):
        try:
            result, events, _stats = run_single(cfg, seed)
            self.msg_q.put(('single', result, events))
        except Exception as e:  # noqa: BLE001
            self.msg_q.put(('error', f'单局回放失败：{e}'))

    def _load_replay(self, result, events):
        self.replay = {'events': events, 'idx': 0, 'playing': False, 'speed': 200,
                       'after': None}
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.see('1.0')          # 新一局从顶部开始看
        self.log_text.config(state='disabled')
        self.board_status.config(text=f'（{len(events)} 条日志，按 ▶ 播放；最终结果：{result} 胜）')
        self.btn_toggle.config(state='normal', text='▶ 播放')
        self.btn_play.config(state='normal')
        self.btn_step.config(state='normal')
        self.btn_reset.config(state='normal')

    def _toggle_play(self):
        rp = self.replay
        if rp['playing']:
            rp['playing'] = False
            self.btn_toggle.config(text='▶ 播放')
            if rp['after']:
                self.root.after_cancel(rp['after'])
                rp['after'] = None
        else:
            rp['playing'] = True
            self.btn_toggle.config(text='⏸ 暂停')
            self._schedule_tick()

    def _schedule_tick(self):
        rp = self.replay
        if not rp['playing']:
            return
        if rp['idx'] >= len(rp['events']):
            rp['playing'] = False
            self.btn_toggle.config(text='⏸ 已播完')
            return
        self._tick_once()
        rp['after'] = self.root.after(rp['speed'], self._schedule_tick)

    def _tick_once(self):
        rp = self.replay
        if rp['idx'] >= len(rp['events']):
            return
        line = rp['events'][rp['idx']]
        rp['idx'] += 1
        self._append_log_line(line)
        self._parse_status_line(line)

    def _step(self):
        rp = self.replay
        if rp['playing']:
            return
        self._tick_once()

    def _append_log_line(self, line):
        tag = None
        if line.startswith('====='):
            tag = 'turn'
        self.log_text.config(state='normal')
        self.log_text.insert('end', line + '\n', tag)
        self.log_text.config(state='disabled')
        # 不自动滚到底：让用户可自由滚动回看，播放中新行从下方继续追加

    _TURN_RE = re.compile(r'第 (\d+) 回合 \[(.+?)\] hp=(\d+) 手牌(\d+)')

    def _parse_status_line(self, line):
        m = self._TURN_RE.search(line)
        if m:
            self.board_status.config(
                text=f'—— 第 {m.group(1)} 回合　[{m.group(2)}] 体力 {m.group(3)}　手牌 {m.group(4)}')

    def _replay_reset(self):
        rp = self.replay
        rp['playing'] = False
        if rp['after']:
            self.root.after_cancel(rp['after'])
            rp['after'] = None
        rp['idx'] = 0
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')
        self.board_status.config(text='')
        self.btn_toggle.config(text='▶ 播放')
        self.btn_play.config(state='normal')

    # ============================================================
    # 配置读取/写入控件
    # ============================================================
    def _build_cfg(self):
        cfg = copy.deepcopy(self.cfg_defaults)
        for sec in ui_spec.SECTIONS:
            for spec in sec['params']:
                if spec['scope'] == 'run':
                    continue
                key = spec['key']
                val = self._get_widget_value(spec)
                if spec['scope'] == 'rules':
                    cfg['RULES'][key] = val
                elif spec['scope'] == 'strategy':
                    cfg['STRATEGY'][key] = val
        cfg['RULES']['A_SKILLS'] = [n for n in KNOWN_SKILLS if self.skill_vars['A'][n].get()]
        cfg['RULES']['B_SKILLS'] = [n for n in KNOWN_SKILLS if self.skill_vars['B'][n].get()]
        return cfg

    def _get_widget_value(self, spec):
        key = spec['key']
        w = self.widgets[key]
        if spec['type'] == 'bool':
            return bool(w.var.get())
        if spec['type'] == 'select':
            display = w.get()
            for d, v in self._combo_opts[key]:
                if d == display:
                    return v
            return display
        if spec['type'] == 'text':
            return w.get().strip() or self._default_of(spec)
        if spec['type'] == 'int':
            return int(w.var.get())
        # float
        return float(w._scale.get())

    def _set_widget_value(self, spec, val):
        key = spec['key']
        w = self.widgets[key]
        if spec['type'] == 'bool':
            w.var.set(bool(val))
        elif spec['type'] == 'select':
            for i, (d, v) in enumerate(self._combo_opts[key]):
                if v == val:
                    w.current(i)
                    return
        elif spec['type'] == 'text':
            w.delete(0, 'end')
            w.insert(0, str(val))
        elif spec['type'] == 'int':
            w.var.set(str(int(val)))
        else:
            w._scale.set(float(val))

    # ============================================================
    # 批量模拟
    # ============================================================
    def _start_batch(self):
        if self.busy:
            return
        try:
            games = self.run_vars['games'].get()
            workers = self.run_vars['workers'].get()
            seed = self.run_vars['seed_offset'].get()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror('参数错误', f'运行参数非法：{e}')
            return
        if games <= 0:
            messagebox.showerror('参数错误', '对局数必须 > 0')
            return
        cfg = self._build_cfg()
        self.busy = True
        self.btn_stop.config(state='normal')
        self.progress_var.set('模拟中… 0 局')
        threading.Thread(target=self._batch_thread,
                         args=(cfg, games, workers, seed), daemon=True).start()

    def _batch_thread(self, cfg, games, workers, seed):
        try:
            def progress(done, total):
                self.msg_q.put(('progress', done, total))
            res = run_batch(cfg, games, workers, seed, progress_cb=progress)
            self.msg_q.put(('result', res))
        except Exception as e:  # noqa: BLE001
            self.msg_q.put(('error', f'模拟失败：{e}'))

    def _cancel(self):
        # multiprocessing 无法优雅中断，只能提示用户等待；置 busy 标志让线程结束后不再刷新
        self.busy = False
        self.progress_var.set('（停止请求——当前批将在完成后结束）')

    # ============================================================
    # 队列轮询
    # ============================================================
    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_q.get_nowait()
                kind = msg[0]
                if kind == 'progress':
                    self.progress_var.set(f'模拟中… {msg[1]}/{msg[2]} 局')
                elif kind == 'result':
                    self._finish_batch(msg[1])
                elif kind == 'single':
                    self.busy = False
                    self._load_replay(msg[1], msg[2])
                    self.btn_play.config(state='normal')
                elif kind == 'error':
                    self.busy = False
                    self.btn_stop.config(state='disabled')
                    self.btn_play.config(state='normal')
                    self.progress_var.set('')
                    messagebox.showerror('错误', msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _finish_batch(self, res):
        self.busy = False
        self.btn_stop.config(state='disabled')
        self.progress_var.set('')
        self._show_result(res)

    # ============================================================
    # 默认/持久化
    # ============================================================
    def _reset_defaults(self):
        for key, val in self.run_defaults.items():
            if key in self.run_vars:
                self.run_vars[key].set(val)
        for sec in ui_spec.SECTIONS:
            for spec in sec['params']:
                if spec['scope'] == 'run':
                    continue
                self._set_widget_value(spec, self._default_of(spec))
        for side, defaults in (('A', ALL_SKILLS_A), ('B', ALL_SKILLS_B)):
            for name in KNOWN_SKILLS:
                self.skill_vars[side][name].set(name in defaults)

    def _snapshot(self):
        snap = {'run': {}, 'rules': {}, 'strategy': {}, 'skills': {}}
        for sec in ui_spec.SECTIONS:
            for spec in sec['params']:
                if spec['scope'] == 'run':
                    snap['run'][spec['key']] = self.run_vars[spec['key']].get()
                elif spec['scope'] == 'rules':
                    snap['rules'][spec['key']] = self._get_widget_value(spec)
                else:
                    snap['strategy'][spec['key']] = self._get_widget_value(spec)
        snap['skills'] = {
            'A': [n for n in KNOWN_SKILLS if self.skill_vars['A'][n].get()],
            'B': [n for n in KNOWN_SKILLS if self.skill_vars['B'][n].get()],
        }
        return snap

    def _apply_snapshot(self, snap):
        run = snap.get('run', {})
        for key, val in run.items():
            if key in self.run_vars:
                self.run_vars[key].set(val)
        for sec in ui_spec.SECTIONS:
            for spec in sec['params']:
                key = spec['key']
                src = {'rules': snap.get('rules', {}),
                       'strategy': snap.get('strategy', {})}.get(spec['scope'])
                if src and key in src:
                    self._set_widget_value(spec, src[key])
        skills = snap.get('skills', {})
        for side in ('A', 'B'):
            chosen = set(skills.get(side, []))
            for name in KNOWN_SKILLS:
                self.skill_vars[side][name].set(name in chosen)

    def _save_settings(self, path):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._snapshot(), f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror('保存失败', str(e))

    def _load_settings(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                snap = json.load(f)
        except (OSError, ValueError) as e:
            messagebox.showerror('载入失败', str(e))
            return
        self._apply_snapshot(snap)

    def _load_settings_quiet(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._apply_snapshot(json.load(f))
        except (OSError, ValueError):
            pass

    def _save_settings_dialog(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.json', initialfile='sgs_config.json',
            filetypes=[('JSON', '*.json')], title='保存配置')
        if path:
            self._save_settings(path)

    def _load_settings_dialog(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON', '*.json'), ('所有文件', '*.*')], title='载入配置')
        if path:
            self._load_settings(path)

    def _on_close(self):
        try:
            self._save_settings(SETTINGS_FILE)
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()


def _setup_fonts():
    """放大全局默认字体（默认 Tk 字体在高分屏上偏小）。"""
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
        try:
            tkfont.nametofont(name).configure(family=FONT, size=11)
        except Exception:  # noqa: BLE001
            pass
    try:
        tkfont.nametofont('TkFixedFont').configure(family='Consolas', size=11)
    except Exception:  # noqa: BLE001
        pass


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass

    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', 1.4)
    except Exception:  # noqa: BLE001
        pass
    _setup_fonts()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
