# -*- coding: utf-8 -*-
"""
对战 AI 控制器。

核心设计：每一个需要决策的点都有对应方法，决策阈值全部读 game.cfg['STRATEGY']（由 Game 传入，
按局生效）。要微调 AI，改本文件里对应方法的逻辑，或调整传入的 STRATEGY 数值即可。

约定：
  - 决策方法（返回 True/False/卡牌/列表）只做判断，由引擎负责实际打牌与移牌。
  - 例外：ask_peach_dying 自己消耗桃/酒（濒死循环依赖 hp 变化）。
"""

import evaluate as EVAL
from cards import CLUB

# 突袭价值判定参数（ev 模式，2026-08-04 修正后经 1200 局单进程扫描校准）：
#   AVG_DRAW_VALUE      —— 从牌堆摸一张随机牌对 A 的期望价值（约 evaluate 中位数）
#   OVER_LIMIT_DISCOUNT —— 手牌已超体力上限时，摸到牌的边际价值系数（仍保留"摸多选优"价值，故较高）
#   STEAL_DEPLETION_BONUS——偷走对手 1 张牌的附加价值（削弱其防御/资源，让后续杀/决斗/南蛮更易命中）
#
# 修正要点：
#   ① 旧逻辑只按"手牌≥体力"就偷（每局 ~11 次），完全没算成本——A 有庸肆时
#      突袭要放弃 基础2+庸肆2 = 4 张摸牌，只为偷 1 张，实测把 A 从 13.4% 拖到 2.7%。
#   ② 2026-08-04 暗牌修正：手牌是隐藏信息，突袭只能"随机偷一张"，看不到对手手牌内容。
#      因此收益按"一张随机牌的期望价值 AVG_DRAW_VALUE + 削弱分"估算，不再偷看对手最好的牌。
#      正确判定：随机偷牌期望收益 > 放弃的摸牌价值时才发动。
#      由于随机偷牌的期望收益(≈1.8) < 摸牌阶段最低成本(≥1.92)，实测突袭几乎不该发动——
#      暗牌规则下突袭的真实价值远低于"偷最好牌"时，这正是移除开图后的正确结论。
AVG_DRAW_VALUE = 1.2
OVER_LIMIT_DISCOUNT = 0.8
STEAL_DEPLETION_BONUS = 0.6


class AIController:
    def __init__(self, game, player):
        self.g = game
        self.p = player
        self.o = game.others(player)[0]
        self.burst_mode = False

    # ============================================================
    # 便捷查询
    # ============================================================
    def has(self, name):
        return any(c.name == name for c in self.p.hand)

    def card_of(self, name):
        for c in self.p.hand:
            if c.name == name:
                return c
        return None

    def has_sha(self):
        return any(c.subtype == 'sha' for c in self.p.hand)

    def count_sha(self):
        return sum(1 for c in self.p.hand if c.subtype == 'sha')

    def has_suit(self, suit):
        return any(c.suit == suit for c in self.p.hand)

    def opp_sha_est(self):
        return len(self.o.hand) * 0.30

    def opp_dodge_est(self):
        return len(self.o.hand) * 0.20

    def hit_prob(self, card):
        if len(self.o.hand) <= 1:
            return 0.85
        if len(self.o.hand) <= 3:
            return 0.65
        return 0.5

    def opp_in_range(self):
        return self.g.in_range(self.p, self.o)

    # ============================================================
    # 出牌阶段主循环
    # ============================================================
    def play_phase(self):
        guard = 0
        while self.p.alive and not self.g.ended and self.g.phase == 'play' and guard < 120:
            guard += 1
            action = self._best_action()
            if action is None:
                break
            action()

    def _best_action(self):
        if self.g.ended or not self.o.alive:
            return None
        # 每个候选为 (key, value, fn)：key 供 PLAY_ORDER 指定顺序，value 供贪心兜底
        cands = []
        cands += self._act_peach()
        cands += self._act_zhitong()
        cands += self._act_equip()
        cands += self._act_taoyuan()
        cands += self._act_wuzhong()
        cands += self._act_xinzhan()
        cands += self._act_delayed()
        cands += self._act_steal_dismantle()
        cands += self._act_duel()
        cands += self._act_fireattack()
        cands += self._act_rende()
        cands += self._act_quhu()
        cands += self._act_wugu()
        cands += self._act_aoe()
        cands += self._act_wine_sha()
        cands += self._act_sha()
        cands += self._act_chongsheng()
        if not cands:
            return None
        floor = self.g.strat['min_action_value']
        order = self._play_order()
        if order:
            # 配置了发动顺序：按列表找第一个「价值达标」的动作
            for key in order:
                for k, v, fn in cands:
                    if k == key and v >= floor:
                        return fn
            # 列表未覆盖的动作：退回价值贪心兜底
            rest = [(v, fn) for k, v, fn in cands if v >= floor]
            return max(rest)[1] if rest else None
        # 未配置顺序：纯价值贪心（原行为）
        best = max(cands, key=lambda c: c[1])
        if best[1] < floor:
            return None
        return best[2]

    def _play_order(self):
        """本玩家配置的发动顺序列表；未配置返回空列表（= 纯价值贪心）。"""
        return self.g.strat.get('PLAY_ORDER_A' if self.p is self.g.a else 'PLAY_ORDER_B') or []

    def _safe_damage(self):
        """安全伤害模式（仅 A）：主打南蛮/决斗/火攻，不出杀/万箭（避免触发对手雷击）。"""
        return self.g.strat.get('safe_damage_mode') and self.p is self.g.a

    # ---- 动作生成器 ----
    def _act_peach(self):
        if self.p.hp >= self.p.max_hp or not self.g.strat['peach_when_damaged']:
            return []
        card = self.card_of('桃')
        if card and not self._keep_peach_for_xinzhan():
            return [('peach', 5.0, lambda: self.g.use_card(self.p, card))]
        return []

    def _keep_peach_for_xinzhan(self):
        """存桃：心战窗口（手牌>体力）激活时不治伤，桃留作濒死兜底。

        治伤会抬高体力、破坏「手牌>体力」，让本回合心战打不出来。
        """
        p = self.p
        if not (p.has_skill('心战') and not p.used_xinzhan):
            return False
        if self.g.strat.get('xinzhan_use') == 'never':
            return False
        if not self.g.strat.get('xinzhan_sell_blood', True):
            return False
        return len(p.hand) > p.hp and p.hp >= 2

    def _act_zhitong(self):
        p = self.p
        if not p.has_skill('制衡') or p.used_zhitong:
            return []
        cards = self.choose_zhitong_cards()
        if len(cards) < self.g.strat['zhitong_min_cards']:
            return []
        return [('zhitong', 0.5 * len(cards), lambda: self.g.skills.skill_zhitong(p))]

    def _act_equip(self):
        res = []
        # 蓄爆完成：换装连弩，进入爆发模式
        if self._hanbing_burst_ready():
            bow = self.card_of('诸葛连弩')
            if bow and not (self.p.weapon and self.p.weapon.name == '诸葛连弩'):
                self.burst_mode = True
                res.append(('equip', 4.0, lambda: self.g.use_card(self.p, bow)))
        for card in self.p.hand:
            if card.kind == 'equip':
                slot = card.subtype
                cur = getattr(self.p, slot)
                v = EVAL.equip_value(self.g, self.p, card)
                if cur:
                    v -= EVAL.equip_value(self.g, self.p, cur)
                    if cur.name == '白银狮子':
                        v += 1.0
                if v > 0.05:
                    res.append(('equip', v, lambda c=card: self.g.use_card(self.p, c)))
        return res

    def _act_taoyuan(self):
        card = self.card_of('桃园结义')
        if not card:
            return []
        self_gain = self.p.max_hp - self.p.hp
        opp_gain = self.o.max_hp - self.o.hp
        v = (self_gain - opp_gain) * 1.0 - 0.3
        if v <= 0:
            return []
        return [('taoyuan', v, lambda: self.g.use_card(self.p, card))]

    def _act_wuzhong(self):
        card = self.card_of('无中生有')
        if card:
            return [('wuzhong', 2.6, lambda: self.g.use_card(self.p, card))]
        return []

    def _act_xinzhan(self):
        p = self.p
        if not p.has_skill('心战') or p.used_xinzhan:
            return []
        if len(p.hand) <= p.hp or self.g.strat['xinzhan_use'] == 'never':
            return []
        return [('xinzhan', 1.2, lambda: self.g.skills.skill_xinzhan(p))]

    def _act_delayed(self):
        res = []
        card = self.card_of('乐不思蜀')
        if card and not self.o.has_skill('谦逊') and not any(
                c.name == '乐不思蜀' for c in self.o.judge_zone):
            res.append(('le', 1.9, lambda c=card: self.g.use_card(self.p, c, target=self.o)))
        card = self.card_of('兵粮寸断')
        if card and not any(c.name == '兵粮寸断' for c in self.o.judge_zone):
            if self._bingliang_timing():
                v = 3.0 if self.g.strat.get('bingliang_prio', True) else 2.5
                res.append(('bingliang', v, lambda c=card: self.g.use_card(self.p, c, target=self.o)))
        card = self.card_of('闪电')
        if card and self.p.has_skill('观星') and not any(
                c.name == '闪电' for pl in self.g.players for c in pl.judge_zone):
            res.append(('shandian', 0.5, lambda c=card: self.g.use_card(self.p, c, target=self.p)))
        return res

    def _act_steal_dismantle(self):
        res = []
        card = self.card_of('顺手牵羊')
        if card and not self.o.has_skill('谦逊') and self.g.distance(self.p, self.o) <= 1 \
                and self.o.all_cards:
            res.append(('snatch', 2.2, lambda c=card: self.g.use_card(self.p, c, target=self.o)))
        card = self.card_of('过河拆桥')
        if card and self.o.all_cards:
            res.append(('dismantle', 1.9, lambda c=card: self.g.use_card(self.p, c, target=self.o)))
        return res

    def _act_duel(self):
        res = []
        card = self.card_of('决斗')
        if card:
            limit = self.g.strat['duel_use_when_opp_sha_le'] if self.p.has_skill('克己') else 1.5
            if self.opp_sha_est() <= limit and not (not self.o.hand and self.o.has_skill('空城')):
                v = 2.0
                if self._safe_damage():
                    v += 1.2   # 安全伤害：优先级拉高
                res.append(('duel', v, lambda: self.g.use_card(self.p, card, target=self.o)))
        return res

    def _act_fireattack(self):
        card = self.card_of('火攻')
        if not card or not self.o.hand:
            return []
        # 花色覆盖越多命中概率越高
        suits = len({c.suit for c in self.p.hand})
        v = 1.4 * min(1.0, suits / 3.0)
        if self._safe_damage():
            v += 0.8
        return [('fireattack', v, lambda: self.g.use_card(self.p, card, target=self.o))]

    def _act_rende(self):
        p = self.p
        if not p.has_skill('仁德'):
            return []
        if p.hp > self.g.strat['rende_use_when_hp_le']:
            return []
        cards = self.choose_rende_cards()
        if len(cards) < self.g.strat['rende_min_give']:
            return []
        give_val = sum(EVAL.card_value(self.g, p, c) for c in cards)
        net = 1.2 - give_val * self.g.strat['rende_give_penalty']
        if net <= 0:
            return []
        return [('rende', net, lambda: self.g.skills.skill_rende(p))]

    def _act_quhu(self):
        p = self.p
        if not p.has_skill('驱虎') or p.used_quhu or not p.has_skill('节命'):
            return []
        o = self.o
        if o.hp <= p.hp or not p.hand or not o.hand:
            return []
        if o.hp - p.hp < self.g.strat['quhu_min_hp_gap']:
            return []
        if len(p.hand) > self.g.strat['quhu_max_hand']:
            return []
        n_draw = min(p.max_hp, 5) - len(p.hand)
        if n_draw <= 0:
            return []
        v = 0.7 * n_draw - 1.0
        if v <= 0:
            return []
        return [('quhu', v, lambda: self.g.skills.skill_quhu(p))]

    def _act_wugu(self):
        card = self.card_of('五谷丰登')
        if card and self.g.strat['use_wugu']:
            return [('wugu', 1.3, lambda: self.g.use_card(self.p, card))]
        return []

    def _act_aoe(self):
        res = []
        o = self.o
        safe = self._safe_damage()
        if not (o.armor and o.armor.name == '藤甲'):
            card = self.card_of('南蛮入侵')
            if card and self.g.strat['use_nanman']:
                v = 1.8 if self.opp_sha_est() <= 1.0 else 1.0
                if safe:
                    v += 1.2   # 南蛮是安全伤害
                res.append(('nanman', v, lambda c=card: self.g.use_card(self.p, c)))
            card = self.card_of('万箭齐发')
            if card and self.g.strat['use_wanjian'] and not safe:
                # 安全模式不出万箭：万箭让 B 打闪 → 触发雷击
                v = 1.6 if self.opp_dodge_est() <= 0.5 else 0.9
                res.append(('wanjian', v, lambda c=card: self.g.use_card(self.p, c)))
        return res

    def _act_wine_sha(self):
        if self._safe_damage():
            return []   # 安全模式：酒杀也是出杀
        if not self.g.strat['wine_before_sha']:
            return []
        if self.p.used_wine or not self.has_sha() or not self._wants_sha():
            return []
        card = self.card_of('酒')
        if card:
            return [('wine_sha', 1.0, lambda: self.g.use_card(self.p, card))]
        return []

    def _act_sha(self):
        if self._safe_damage():
            return []   # 安全模式：不出杀（出杀被闪 → 触发雷击）
        if not self._wants_sha():
            return []
        if self.p.used_sha >= 1 and not (self.p.weapon and self.p.weapon.name == '诸葛连弩'):
            return []
        if not self.opp_in_range():
            return []
        if not self.o.hand and self.o.has_skill('空城'):
            return []
        card = self.choose_sha_card()
        if card:
            return [('sha', self._sha_value(card), lambda: self.g.use_card(self.p, card, target=self.o))]
        return []

    def _act_chongsheng(self):
        card = self.card_of('铁索连环')
        if card:
            return [('chongsheng', 0.9, lambda: self.g.chongsheng(self.p, card))]
        return []

    # ---- 寒冰剑蓄爆流 ----
    def _kill_potential(self):
        """估算本回合若装备连弩能打出的有效伤害（扣闪后）。返回伤害值，不足则 0。"""
        o = self.o
        n_sha = self.count_sha()
        if n_sha <= 0:
            return 0
        dodge_est = len(o.hand) // 4        # 约每4张手牌1张闪
        dmg = max(0, n_sha - dodge_est)
        if not self.p.used_wine and self.has('酒'):
            dmg += 1
        needed = o.hp + len(o.bq) + 1       # 血 + 不屈牌数 + 缓冲
        return dmg if dmg >= needed else 0

    def _hanbing_burst_ready(self):
        """蓄爆完成：寒冰剑已到手 + 连弩在手/已装备 + 能确认击杀。"""
        p = self.p
        if not self.g.strat.get('hanbing_burst'):
            return False
        has_hanbing = (p.weapon and p.weapon.name == '寒冰剑') or any(c.name == '寒冰剑' for c in p.hand)
        has_bow = (p.weapon and p.weapon.name == '诸葛连弩') or any(c.name == '诸葛连弩' for c in p.hand)
        if not has_hanbing or not has_bow:
            return False
        return self._kill_potential() > 0

    # ---- 杀攻击决策 ----
    def _wants_sha(self):
        # 爆发模式：已确认击杀，倾泻所有杀
        if getattr(self, 'burst_mode', False):
            return True
        # 蓄爆期：装备寒冰剑时主动出杀削牌
        if (self.p.weapon and self.p.weapon.name == '寒冰剑'
                and self.g.strat.get('hanbing_use') and self.p is self.g.a
                and not self._hanbing_burst_ready()):
            return True
        if self.p.has_skill('克己'):
            return self._wants_sha_b()
        return self._wants_sha_a()

    def _wants_sha_a(self):
        if self.o.hp <= 1:
            return True
        if self.p.weapon and self.p.weapon.name == '诸葛连弩' and self.count_sha() >= 2:
            return True
        if len(self.o.hand) <= 1:
            return True
        if self.p.wine_count > 0 and self.hit_prob(None) >= 0.6:
            return True
        # 命中率阈值：A 走配置值（调低=更敢出杀），B 保持 0.55
        thr = self.g.strat['a_sha_attack_hit'] if self.p is self.g.a else 0.55
        return self.hit_prob(None) >= thr

    def _wants_sha_b(self):
        # 克己囤牌流：不轻易出杀，攒到有把握再出手
        if self.o.hp <= 1 and self.g.strat['keji_attack_when_lethal']:
            return True
        if self.count_sha() > self.g.strat['keji_hoard_sha_gt']:
            return True
        if len(self.o.hand) <= 1:
            return True
        if len(self.p.hand) > self.p.hp + 3:
            return True
        # 狂骨回血：受伤且手牌不多时，出杀=输出+回血，破克己代价低
        if self.p.hp < self.p.max_hp and len(self.p.hand) <= self.p.hp:
            return True
        return False

    def _sha_value(self, card):
        hit = self.hit_prob(card)
        dmg = 1
        if self.p.wine_count > 0:
            dmg += 1
        if self.p.weapon and self.p.weapon.name == '古锭刀' and not self.o.hand:
            dmg += 1
        val = hit * dmg
        if self.o.has_skill('不屈'):
            val *= 0.9
        # B 出杀命中会触发狂骨回血（距离1以内）
        if self.p.has_skill('狂骨') and self.g.distance(self.p, self.o) <= 1:
            val += 0.7 * hit
        return val - 0.2

    # ============================================================
    # 响应决策（返回判断，引擎负责打牌）
    # ============================================================
    def _sell_for_jiening(self):
        return (self.p.has_skill('节命') and len(self.p.hand) <= 1
                and self.p.hp > 2 and not self.g.strat['always_dodge'])

    def _bingliang_timing(self):
        """蓄意囤积兵粮寸断（仅 B，配置 bingliang_hoard）：B 绝不使用兵粮寸断，
        囤死留手牌喂心战（实测"囤>打"，无脑打反而耗 B 手牌）。
        A 或开关关闭时按旧行为（有就打）。"""
        if self.p is not self.g.b:               # A：有就打
            return True
        if not self.g.strat.get('bingliang_hoard', True):
            return True                          # 开关关：B 恢复旧行为（有就打）
        return False                             # B 囤死：绝不使用

    def _xinzhan_sell_blood(self, dmg=1):
        """心战卖血流：故意吃下 dmg 点伤害，换取下一回合心战（手牌>体力）可发动。

        心战要求「手牌>体力」。估计下回合摸牌后手牌≈当前+2（兵粮跳摸则+0）：
        若恰好=当前体力（不卖就发动不了、卖 dmg 后能发动），且能扛住，则卖血。
        """
        p = self.p
        if not (p.has_skill('心战') and not p.used_xinzhan):
            return False
        if self.g.strat.get('xinzhan_use') == 'never':
            return False
        if not self.g.strat.get('xinzhan_sell_blood', True):
            return False
        draw = 0 if any(c.name == '兵粮寸断' for c in p.judge_zone) else 2
        if len(p.hand) + draw != p.hp:    # 差太远卖不动；或本来就能发动无需卖
            return False
        after = p.hp - dmg
        if after < 1:
            return False
        if after >= 2:
            return True
        return self.has('桃')              # 剩1血需桃兜底（配合存桃策略）

    def ask_dodge(self, attacker, card):
        dmg = 1
        if card and card.subtype == 'sha' and attacker.wine_count > 0:
            dmg += 1                       # 酒杀 2 点
        if self._xinzhan_sell_blood(dmg):
            return False
        if self.g.strat['always_dodge']:
            return self.has('闪')
        if self._sell_for_jiening():
            return False
        return self.has('闪')

    def ask_dodge_for_wanjian(self):
        if self._xinzhan_sell_blood():
            return False
        if self.g.strat['always_dodge']:
            return self.has('闪')
        if self._sell_for_jiening():
            return False
        return self.has('闪')

    def ask_sha_for_duel(self, other, duel_target):
        if not self.has_sha():
            return False
        # 克己：只有1张杀且对方杀明显更多时，选择吃伤害保克己
        if self.p.has_skill('克己') and self.count_sha() == 1 and self.opp_sha_est() >= 2:
            return False
        return True

    def ask_sha_for_nanman(self):
        if not self.has_sha():
            return False
        # 心战卖血：吃1点伤害换取心战窗口（与克己保牌同理）
        if self._xinzhan_sell_blood():
            return False
        # 克己：只有1张杀且状态不错时，吃1点伤害保克己
        if self.p.has_skill('克己') and self.count_sha() == 1 and self.p.hp >= 3:
            return False
        return True

    def ask_play_sha_for_borrow(self, target):
        return False   # 对手命令出杀：通常不服从（保武器?）——由 choose_borrow_sha 决定

    THREAT = {
        '无中生有': 2.0, '顺手牵羊': 2.0, '过河拆桥': 2.0, '决斗': 2.0,
        '南蛮入侵': 2.0, '万箭齐发': 1.8, '乐不思蜀': 2.2, '兵粮寸断': 2.0,
        '火攻': 1.6, '借刀杀人': 1.5, '五谷丰登': 0.8, '桃园结义': 0.3,
        '铁索连环': 0.5, '闪电': 0.5,
    }

    def ask_nullify(self, card, is_pro):
        if not self.has('无懈可击'):
            return False
        if is_pro:
            # 反无懈：保护自己的关键锦囊
            return self.THREAT.get(card.name, 1.0) >= 1.0
        t = self.THREAT.get(card.name, 1.0)
        return t >= 1.5

    def ask_peach_dying(self):
        """濒死中消耗一张桃/酒回1血。返回是否用了。"""
        if self.p.hp >= 1:
            return False
        card = self.card_of('桃')
        if card:
            self.g.log(f'{self.p.name} 在濒死中使用【桃】回复1体力')
            self.g.spend_hand(self.p, card)
            self.p.hp = min(self.p.max_hp, self.p.hp + 1)
            return True
        card = self.card_of('酒')
        if card:
            self.g.log(f'{self.p.name} 在濒死中以【酒】当桃回复1体力')
            self.g.spend_hand(self.p, card)
            self.p.hp = min(self.p.max_hp, self.p.hp + 1)
            return True
        return False

    def ask_peach_for_other(self, dying):
        return False   # 单挑：不救对手

    def choose_discard_vs_let_draw(self, attacker):
        if not self.p.hand:
            return False
        return True

    def ask_baguazhen(self):
        return True

    def ask_guanshi(self):
        return len(self.p.hand) >= 3

    def ask_hanbing(self):
        # 寒冰剑猎手（仅 A）：命中是否用寒冰剑弃对手2张牌代替伤害。
        # 智慧版：对手手牌多（克己囤牌）→ 削弱；手牌已少 → 直接伤害推进；
        # 对手1血且无不屈 → 收人头。纯弃牌会让 A 打不出伤害（B 有屈死不掉）。
        if self.g.strat.get('hanbing_use') and self.p is self.g.a:
            o = self.o
            if o.hp <= 1 and not o.has_skill('不屈'):
                return False
            return len(o.hand) >= 3
        return False   # 默认直接造成伤害

    def ask_qiling(self):
        return True

    def ask_zhuque(self):
        o = self.o
        return bool(o.chained or (o.armor and o.armor.name == '藤甲'))

    def ask_fireattack_discard(self, shown):
        return self.has_suit(shown.suit)

    # ============================================================
    # 选牌类
    # ============================================================
    def choose_sha_card(self):
        sha = [c for c in self.p.hand if c.subtype == 'sha']
        if not sha:
            return None
        o = self.o
        if o.armor and o.armor.name == '藤甲':
            for c in sha:
                if c.name in ('火杀', '雷杀'):
                    return c
        if (o.armor and o.armor.name == '仁王盾') or (o.has_skill('毅重') and not o.armor):
            for c in sha:
                if c.color == 'red':
                    return c
        return sha[0]

    def choose_shan_card(self):
        for c in self.p.hand:
            if c.subtype == 'shan':
                return c
        return None

    def choose_tao_card(self):
        return self.card_of('桃')

    def choose_jiu_card(self):
        return self.card_of('酒')

    def choose_borrow_sha(self):
        if not self.has_sha():
            return None
        if self.p.has_skill('克己'):
            return None   # 保克己，交武器
        return self.choose_sha_card()

    def ask_qinglong_followup(self):
        return self.count_sha() >= 2

    def choose_pindian_card(self):
        if not self.p.hand:
            return None
        return min(self.p.hand, key=lambda c: c.rank)

    def choose_cards_to_discard(self, n):
        cards = sorted(self.p.hand, key=lambda c: EVAL.card_value(self.g, self.p, c))
        # 蓄意囤积（仅 B）：兵粮寸断是断粮锁牌，非万不得已不弃（保证能连段续锁）
        if self.g.strat.get('bingliang_hoard', True) and self.p is self.g.b:
            protected = [c for c in cards if c.name != '兵粮寸断']
            if len(protected) >= n:
                return protected[:n]
        return cards[:n]

    def choose_zhitong_cards(self):
        thr = self.g.strat['zhitong_value_threshold']
        # 蓄爆流（仅 A）：制衡保留杀/桃/酒，避免丢掉爆发资源
        protect = self.g.strat.get('hanbing_burst') and self.p is self.g.a
        return [c for c in self.p.hand
                if EVAL.card_value(self.g, self.p, c) < thr
                and not (protect and c.subtype in ('sha', 'tao', 'jiu'))]

    def choose_rende_cards(self):
        if self.p.hp > self.g.strat['rende_use_when_hp_le']:
            return []
        junk = sorted(self.p.hand, key=lambda c: EVAL.card_value(self.g, self.p, c))
        return junk[:self.g.strat['rende_max_give']]

    def choose_cards_to_give(self, n):
        return sorted(self.p.hand, key=lambda c: EVAL.card_value(self.g, self.p, c))[:n]

    def choose_card_to_steal(self, target):
        """突袭：只能从手牌偷。手牌是暗牌，随机拿一张（看不到内容）。"""
        if not target.hand:
            return None
        return self.g.rng.choice(target.hand)

    def choose_card_to_steal_any(self, target):
        """顺手牵羊：装备/判定区可见可选价值最高；手牌暗牌随机拿。"""
        if not target.all_cards:
            return None
        visible = list(target.equip_cards) + list(target.judge_zone)
        if visible:
            best = max(visible, key=lambda c: EVAL.card_value(self.g, self.p, c))
            if EVAL.card_value(self.g, self.p, best) >= AVG_DRAW_VALUE or not target.hand:
                return best
        if target.hand:
            return self.g.rng.choice(target.hand)
        return None

    def choose_card_to_dismantle(self, target, avail):
        """过河拆桥：装备/判定区可见弃价值最高；手牌暗牌随机弃。"""
        visible = [c for c in avail if c not in target.hand]
        if visible:
            best = max(visible, key=lambda c: EVAL.card_value(self.g, self.p, c))
            if EVAL.card_value(self.g, self.p, best) >= AVG_DRAW_VALUE or not target.hand:
                return best
        if target.hand:
            return self.g.rng.choice(target.hand)
        return None

    def choose_card_to_discard_any(self, n):
        return sorted(self.p.all_cards, key=lambda c: EVAL.card_value(self.g, self.p, c))[:n]

    def choose_target_cards_to_discard(self, target, n):
        """寒冰剑：弃置目标 n 张牌。装备/判定区可见选价值最高，手牌暗牌随机补足。"""
        visible = list(target.equip_cards) + list(target.judge_zone)
        picked = sorted(visible, key=lambda c: -EVAL.card_value(self.g, self.p, c))[:n]
        if len(picked) < n:
            hand_pool = [c for c in target.hand if c not in picked]
            extra = self.g.rng.sample(hand_pool, min(n - len(picked), len(hand_pool))) if hand_pool else []
            picked += extra
        return picked

    def choose_horse_to_discard(self, target):
        return target.p1horse or target.m1horse

    def choose_reveal_card(self):
        if not self.p.hand:
            return None
        return min(self.p.hand, key=lambda c: EVAL.card_value(self.g, self.p, c))

    def choose_wugu_card(self, revealed):
        return max(revealed, key=lambda c: EVAL.card_value(self.g, self.p, c))

    def choose_jiening_target(self):
        return self.p

    def choose_jiening(self):
        return True

    def choose_leiji_target(self, source):
        """雷击：选择一名其他角色进行判定（单挑中即对手）。"""
        o = self.o
        return o if o.alive else None

    def ask_guidao_replace(self, judged, card, reason):
        """鬼道：判定牌生效前打出一张黑色牌替换。只有能改变结果时才花牌。
        返回要打出的牌或 None。"""
        p = self.p
        black = [c for c in p.hand if c.color == 'black']
        if not black:
            return None
        is_self = (judged is p)
        # 雷击：目标判定已是黑桃则无需替换；否则打黑桃使命中
        if reason == '雷击':
            if card.suit == 'spade':
                return None
            spades = [c for c in black if c.suit == 'spade']
            return max(spades, key=lambda c: c.rank) if spades else None
        # 闪电：自己判定黑桃2-9才换（避开）；对方判定安全才换（制造命中）
        if reason == '闪电':
            if is_self:
                if not card.is_spade_2_9:
                    return None
                safe = [c for c in black if not c.is_spade_2_9]
                return min(safe, key=lambda c: c.rank) if safe else None
            if card.is_spade_2_9:
                return None
            hit = [c for c in black if c.is_spade_2_9]
            return hit[0] if hit else None
        # 乐不思蜀：对方判定红桃才换（使其不能过）；自己帮不了
        if reason == '乐不思蜀':
            if is_self:
                return None
            if not card.is_heart:
                return None
            return black[0]
        # 兵粮寸断：自己判定非梅花才换（出梅花免）；对方判定梅花才换（出非梅花使其中）
        if reason == '兵粮寸断':
            if is_self:
                if card.suit == 'club':
                    return None
                clubs = [c for c in black if c.suit == 'club']
                return clubs[0] if clubs else None
            if card.suit != 'club':
                return None
            nonclubs = [c for c in black if c.suit != 'club']
            return nonclubs[0] if nonclubs else None
        # 八卦阵：对方判定红才换（使其失效）；自己帮不了
        if reason == '八卦阵':
            if is_self:
                return None
            if card.color != 'red':
                return None
            return black[0]
        return None

    # ============================================================
    # 摸牌/回合类技能决策
    # ============================================================
    def choose_tuxi(self):
        mode = self.g.strat['tuxi_use']
        if mode == 'always':
            return True
        if mode == 'never':
            return False
        return self._tuxi_ev()

    def _tuxi_ev(self):
        """突袭的期望价值判定（ev 模式，暗牌）。

        收益：手牌是暗牌，突袭只能随机偷一张，期望收益 = 一张随机牌的期望价值 + 削弱对手防御分；
        成本：本次摸牌阶段放弃的摸牌价值（基础 2 张 + 庸肆 X + 好施 2），
              且手牌越超体力上限，摸到的牌越接近"摸了就弃"，边际价值越低。
        只有随机偷牌的期望收益 > 放弃的摸牌成本才发动。
        """
        if not self.o.hand:
            return False
        steal = AVG_DRAW_VALUE + STEAL_DEPLETION_BONUS
        return steal > self._tuxi_draw_value()

    def _tuxi_draw_value(self):
        """不突袭时本次摸牌阶段的期望价值（随弃牌压力打折）。"""
        p = self.p
        n = 2
        if p.has_skill('庸肆'):
            n += self.g.yongsi_count()
        if p.has_skill('好施') and self.g.strat.get('haoshi_use', 'never') != 'never':
            n += 2
        over = max(len(p.hand) - p.hp, 0)
        total = 0.0
        for i in range(n):
            if over + i <= 0:
                total += AVG_DRAW_VALUE
            else:
                total += AVG_DRAW_VALUE * OVER_LIMIT_DISCOUNT
        return total

    def choose_haoshi(self):
        mode = self.g.strat['haoshi_use']
        if mode == 'always':
            return True
        if mode == 'never':
            return False
        # ev：好施额外摸2，但手牌>5 时要交一半给手牌最少者（1v1 里恒为对手=资敌）。
        # 只有当前手牌 ≤3（摸2 后 ≤5，不触发交牌）才划算，等于白拿 2 张。
        # 有庸肆时摸牌阶段手牌必然 >3，故天然不会触发（庸肆+好施双摸必然资敌）。
        return len(self.p.hand) <= 3

    def choose_guanxing(self):
        return True

    # 延时锦囊的判定偏好与优先级。判定区同时存在多个延时锦囊时，
    # 按判定区顺序给每个判定安排一张合适的判定牌（第 0 个判定用第 1 张……）；
    # 合适牌不够时优先保更重要的判定：闪电（3点伤害）> 乐不思蜀（跳过出牌）> 兵粮寸断（跳过摸牌）。
    _JUDGE_PREF = {
        '闪电': lambda card: not card.is_spade_2_9,
        '乐不思蜀': lambda card: card.is_heart,
        '兵粮寸断': lambda card: card.suit == CLUB,
    }
    _JUDGE_PRIORITY = {'闪电': 0, '乐不思蜀': 1, '兵粮寸断': 2}

    def arrange_stargaze(self, top):
        """top 为牌堆顶若干张（最后一个是最顶）。返回 (top_part, bottom_part)，
        top_part 第一个元素最先被摸到。"""
        p = self.p
        judge = [c for c in p.judge_zone if c.name in self._JUDGE_PREF]
        if judge:
            remaining = list(top)
            # 分配顺序：默认按重要度（闪电>乐>兵粮）；若可见牌不足以覆盖全部判定，
            # 退化为按判定顺序填，保证 top_part 从第 1 张起连续可控。
            order = sorted(range(len(judge)),
                           key=lambda i: self._JUDGE_PRIORITY[judge[i].name])
            if len(judge) > len(remaining):
                order = list(range(len(judge)))
            arranged = [None] * len(judge)
            for i in order:
                if not remaining:
                    break
                pref = self._JUDGE_PREF[judge[i].name]
                cands = [c for c in remaining if pref(c)]
                # 用价值最低的合适牌挡判定（判定牌会进弃牌堆，别浪费好牌）
                chosen = min(cands or remaining, key=lambda c: EVAL.card_value(self.g, p, c))
                arranged[i] = chosen
                remaining.remove(chosen)
            # 取从位置 0 开始的连续已填判定牌（空洞=牌在可见范围外，无法控制）
            top_part = []
            for c in arranged:
                if c is None:
                    break
                top_part.append(c)
            keep = [c for c in remaining if EVAL.card_value(self.g, p, c) >= self.g.strat['guanxing_keep_value']]
            keep.sort(key=lambda c: -EVAL.card_value(self.g, p, c))
            bottom = [c for c in remaining if c not in keep]
            return top_part + keep, bottom
        keep = [c for c in top if EVAL.card_value(self.g, p, c) >= self.g.strat['guanxing_keep_value']]
        keep.sort(key=lambda c: -EVAL.card_value(self.g, p, c))
        bottom = [c for c in top if c not in keep]
        return keep, bottom

    def choose_jushou(self):
        p, o = self.p, self.o
        if p.hp <= self.g.strat['jushou_hp_le']:
            return True
        if len(o.hand) <= self.g.strat['jushou_opp_hand_le']:
            return True
        if self.g.strat['jushou_hand_gt_hp'] and len(p.hand) > p.hp:
            return True
        return False

    def choose_xinzhan(self):
        return self.g.strat['xinzhan_use'] != 'never'

    def choose_xinzhan_take(self, hearts):
        return list(hearts)

    def arrange_xinzhan_rest(self, rest):
        return sorted(rest, key=lambda c: -EVAL.card_value(self.g, self.p, c))
