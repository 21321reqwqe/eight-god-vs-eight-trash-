# -*- coding: utf-8 -*-
"""
规则引擎：回合流程、伤害/濒死/死亡、不屈、距离与攻击范围、拼点、判定、无懈链，
以及全部基本牌、锦囊、装备的结算。

设计要点：
  - 每个需要玩家决策的点都调用 对应角色的 ai 控制器 方法（见 ai.py），
    因此想改变某个行为的 AI，只需改 ai.py 里对应方法。
  - 技能逻辑集中在 skills.py，通过钩子接入本引擎。
"""

import random

from cards import (Card, CLUB, HEART, SPADE, DIAMOND, DAMAGE_CN, build_deck)
from player import Player
from skills import Skills
from ai import AIController
from config import default_config


class Game:
    def __init__(self, cfg=None, seed=1, cards=None, log=False):
        if cfg is None:
            cfg = default_config()
        self.cfg = cfg
        self.rules = cfg['RULES']
        self.strat = cfg['STRATEGY']

        self.log_enabled = log
        self.events = []

        r = self.rules
        self.rng = random.Random(seed)
        self.draw_pile = cards if cards is not None else build_deck(
            include_junzheng=(r['DECK'] != 'standard'))
        self.rng.shuffle(self.draw_pile)
        self.discard = []

        # 玩家
        self.players = [
            Player(r['A_NAME'], r['A_MAX_HP'], r['A_FACTION'], r['A_GENDER']),
            Player(r['B_NAME'], r['B_MAX_HP'], r['B_FACTION'], r['B_GENDER']),
        ]
        self.players[0].index = 0
        self.players[1].index = 1
        self.a = self.players[0]
        self.b = self.players[1]

        # 技能挂接（RULES 可覆盖技能列表；None 用默认，空列表=无技能）
        from skills import ALL_SKILLS_A, ALL_SKILLS_B
        self.a.skills = list(r['A_SKILLS']) if r.get('A_SKILLS') is not None else list(ALL_SKILLS_A)
        self.b.skills = list(r['B_SKILLS']) if r.get('B_SKILLS') is not None else list(ALL_SKILLS_B)
        self._apply_lord_and_weidizi()

        # AI 挂接
        self.a.ai = AIController(self, self.a)
        self.b.ai = AIController(self, self.b)

        self.skills = Skills(self)

        self.turn_no = 0
        self.current = 0
        self.phase = ''
        self.ended = False
        self.winner = None
        self.result = None          # 'A' / 'B' / 'draw'
        self.killer_of = {}         # 记录击杀者（挥泪用）

        self.stats = {
            'dmg_dealt': {self.a.name: 0, self.b.name: 0},
            'turns': 0,
            'skill_triggers': {},
            'sum_hand': {self.a.name: 0, self.b.name: 0},
            'hand_samples': {self.a.name: 0, self.b.name: 0},
        }

    # ============================================================
    # 便捷属性
    # ============================================================
    @property
    def alive_players(self):
        return [p for p in self.players if p.alive]

    def others(self, p):
        return [q for q in self.players if q is not p and q.alive]

    def current_player(self):
        return self.players[self.current]

    def log(self, msg):
        if self.log_enabled:
            self.events.append(msg)

    def _apply_lord_and_weidizi(self):
        """主公技与伪帝处理。LORD=None 时主公技全部失效。"""
        r = self.rules
        lord = r.get('LORD')
        if lord == 'A':
            lord_player, other = self.a, self.b
        elif lord == 'B':
            lord_player, other = self.b, self.a
        else:
            return
        # 伪帝：A 视为拥有当前主公的主公技
        if self.a.has_skill('伪帝') and self.a is not lord_player:
            for s in lord_player.skills:
                if s in ('救援', '激将'):
                    self.a.skills.append(s)

    # ============================================================
    # 主流程
    # ============================================================
    def run(self):
        r = self.rules
        # 开局摸牌
        for p in self.players:
            self.draw_cards(p, r['START_HAND'])

        # 先手
        if r['FIRST_PLAYER'] == 'A':
            self.current = 0
        elif r['FIRST_PLAYER'] == 'B':
            self.current = 1
        else:
            self.current = self.rng.choice([0, 1])
        self.log(f'== 对局开始，先手：{self.current_player().name} ==')

        while not self.ended and self.turn_no < r['MAX_TURNS']:
            self.run_turn()

        if not self.ended:
            # 超时：按体力+手牌判定
            self.result = self._timeout_winner()
            self.winner = self.result
        return self.result

    def _timeout_winner(self):
        a, b = self.a, self.b
        if a.hp != b.hp:
            return a.name if a.hp > b.hp else b.name
        ca, cb = len(a.all_cards), len(b.all_cards)
        if ca != cb:
            return a.name if ca > cb else b.name
        return 'draw'

    def run_turn(self):
        p = self.current_player()
        self.turn_no += 1
        self.stats['turns'] = self.turn_no
        # 每回合采样双方手牌数（用于统计平均手牌）
        for q in self.players:
            self.stats['sum_hand'][q.name] += len(q.hand)
            self.stats['hand_samples'][q.name] += 1
        # 翻面：跳过整个回合
        if p.face_down:
            p.face_down = False
            self.log(f'{p.name} 翻回正面，跳过回合')
            self.current = 1 - self.current
            return
        self.log(f'===== 第 {self.turn_no} 回合 [{p.name}] hp={p.hp} 手牌{len(p.hand)} =====')

        # 回合开始阶段（观星）
        self.phase = 'start'
        self.skills.on_turn_start(p)

        # 判定阶段
        self.phase = 'judge'
        self.judge_phase(p)
        if self.ended:
            return

        # 摸牌阶段
        self.phase = 'draw'
        if p.skip_draw:
            self.log(f'{p.name} 因【兵粮寸断】跳过摸牌阶段')
        elif p.alive:
            self.skills.on_draw_phase(p)
        if self.ended:
            return

        # 出牌阶段
        self.phase = 'play'
        if p.skip_play:
            self.log(f'{p.name} 因【乐不思蜀】跳过出牌阶段')
        elif p.alive:
            p.ai.play_phase()
        if self.ended:
            return

        # 弃牌阶段
        self.phase = 'discard'
        if p.alive:
            self.discard_phase(p)
        if self.ended:
            return

        # 回合结束阶段（据守 / 闭月）
        self.phase = 'end'
        if p.alive:
            self.skills.on_end_phase(p)
        if self.ended:
            return

        p.reset_turn_state()
        self.current = 1 - self.current

    # ============================================================
    # 摸牌 / 弃牌
    # ============================================================
    def _reshuffle(self):
        self.draw_pile = self.discard[:]
        self.discard.clear()
        self.rng.shuffle(self.draw_pile)
        self.log('牌堆耗尽，重洗弃牌堆')

    def _end_draw(self):
        """牌堆与弃牌堆皆空：游戏直接平局结束（官方规则，无胜利者）。"""
        self.ended = True
        self.result = 'draw'
        self.winner = None
        self.log('牌堆与弃牌堆皆空，游戏以平局结束')

    def draw_cards(self, p, n):
        for _ in range(n):
            if not self.draw_pile:
                if not self.discard:
                    self._end_draw()
                    return
                self._reshuffle()
            card = self.draw_pile.pop()
            p.hand.append(card)
            self.log(f'{p.name} 摸牌: {card}')

    def discard_phase(self, p):
        # 克己：跳过（本回合未于出牌阶段内使用/打出过杀）
        if p.has_skill('克己') and not p.played_sha:
            self.log(f'{p.name} 因【克己】跳过弃牌阶段')
            self._count_skill('克己')
            return
        hand_limit = max(0, p.hp)
        required = max(len(p.hand) - hand_limit, 0)
        if p.has_skill('庸肆'):
            X = self.yongsi_count()
            required = max(required, X)
        required = min(required, len(p.hand))
        if required > 0:
            cards = p.ai.choose_cards_to_discard(required)
            for c in cards[:required]:
                self.spend_hand(p, c)
            self.log(f'{p.name} 弃置 {min(required, len(cards))} 张牌')
        else:
            self.log(f'{p.name} 无需弃牌')

    def faction_count(self):
        return len({p.faction for p in self.players if p.alive})

    def yongsi_count(self):
        """庸肆张数：RULES['YONGSI_CARDS'] 正数=固定 N 张（自定规则），否则官方势力数。
        摸牌阶段额外摸 N 张、弃牌阶段至少弃 N 张（官方规则两者同 X）。"""
        n = self.rules.get('YONGSI_CARDS')
        return int(n) if n else self.faction_count()

    def _note_sha_use(self, p):
        """记录 p 使用/打出过【杀】（用于克己判定）。
        克己原文：若你未于【出牌阶段内】使用或打出过【杀】——只看自己的出牌阶段。
        因此只有 p 是自己的回合且处于出牌阶段时才记；回合外响应（别人回合打出的杀）不计入，
        不破克己（例：响应他人南蛮入侵出杀不破克己；自己出决斗时继续出杀破克己）。"""
        if p is self.current_player() and self.phase == 'play':
            p.played_sha = True

    # ============================================================
    # 手牌 / 卡牌移动（连营钩子在这里）
    # ============================================================
    def spend_hand(self, p, card, to=None):
        """从手牌移出某张牌：to=None 进弃牌堆，to=Player 进其手牌。"""
        if card not in p.hand:
            return
        p.hand.remove(card)
        if to is not None:
            to.hand.append(card)
        else:
            self.discard.append(card)
        self._on_hand_lost(p)

    def _on_hand_lost(self, p):
        if p.has_skill('连营') and not p.hand:
            self.draw_cards(p, 1)
            self.log(f'{p.name} 触发【连营】摸1张')
            self._count_skill('连营')

    def remove_card(self, p, card):
        """把一张牌从其所在区（手牌/装备/判定区）移除，返回是否成功。"""
        zone = p.card_zone(card)
        if zone == 'hand':
            p.hand.remove(card)
            self._on_hand_lost(p)
        elif zone == 'equip':
            self._unequip(p, card)
        elif zone == 'judge':
            p.judge_zone.remove(card)
        else:
            return False
        return True

    def _unequip(self, p, card):
        for attr in ('weapon', 'armor', 'p1horse', 'm1horse'):
            if getattr(p, attr) is card:
                setattr(p, attr, None)
                break
        # 白银狮子离场回血
        if card.name == '白银狮子' and p.hp < p.max_hp:
            p.hp += 1
            self.log(f'{p.name} 失去【白银狮子】回复1体力')

    def _equip_lost(self, p, card):
        """装备被替换/弃置/夺走时的处理。"""
        self._unequip(p, card)

    # ============================================================
    # 距离 / 攻击范围
    # ============================================================
    def distance(self, a, b):
        """a 到 b 的距离（单挑基本距离1）。义从：体力>2 时你计算距离-1；<=2 时他人对你+1。"""
        if a is b:
            return 0
        d = 1
        if a.m1horse:
            d -= 1
        if a.has_skill('义从') and a.hp > 2:
            d -= 1
        if b.p1horse:
            d += 1
        if b.has_skill('义从') and b.hp <= 2:
            d += 1
        return max(1, d)

    def attack_range(self, p):
        return p.weapon.weapon_range if p.weapon else 1

    def in_range(self, p, target):
        return self.distance(p, target) <= self.attack_range(p)

    # ============================================================
    # 判定
    # ============================================================
    def judge(self, p, reason=''):
        if not self.draw_pile:
            self._reshuffle()
        if not self.draw_pile:
            self._end_draw()
            return None
        card = self.draw_pile.pop()
        self.discard.append(card)
        self.log(f'{p.name} 判定[{reason}]: {card}')
        # 判定牌生效前：鬼道可用黑色牌替换
        return self.skills.on_judge(p, card, reason)

    def judge_phase(self, p):
        if not p.judge_zone:
            return
        for trick in list(p.judge_zone):
            if self.ended:
                return
            jc = self.judge(p, trick.name)
            if self.ended:
                return
            p.judge_zone.remove(trick)
            if trick.name == '乐不思蜀':
                self.discard.append(trick)
                if not jc.is_heart:
                    p.skip_play = True
                    self.log(f'{p.name} 【乐不思蜀】生效，跳过出牌阶段')
            elif trick.name == '兵粮寸断':
                self.discard.append(trick)
                if jc.suit != CLUB:
                    p.skip_draw = True
                    self.log(f'{p.name} 【兵粮寸断】生效，跳过摸牌阶段')
            elif trick.name == '闪电':
                if jc.is_spade_2_9:
                    self.discard.append(trick)
                    self.deal_damage(None, p, 3, 'lightning')
                else:
                    o = self.others(p)[0]
                    o.judge_zone.append(trick)
                    self.log(f'【闪电】未命中，传给 {o.name}')

    # ============================================================
    # 伤害 / 濒死 / 死亡
    # ============================================================
    def deal_damage(self, source, target, amount, dtype='normal', card=None):
        if amount <= 0 or not target.alive:
            return
        # 铁索连环：属性伤害传导
        chain = []
        if dtype in ('fire', 'lightning') and target.chained:
            chain = [p for p in self.players if p.alive and p.chained]
            for p in chain:
                p.chained = False
        victims = [target] + [p for p in chain if p is not target]
        for t in victims:
            if self.ended:
                return
            dmg = amount
            if t.armor and t.armor.name == '白银狮子':
                dmg = min(dmg, 1)
            if dtype == 'fire' and t.armor and t.armor.name == '藤甲':
                dmg += 1
            if dmg > 0:
                self.log(f'{source.name if source else "系统"} 对 {t.name} 造成 {dmg} 点'
                         f'{DAMAGE_CN.get(dtype, "")}伤害')
                if source:
                    self.stats['dmg_dealt'][source.name] += dmg
                self.lose_hp(source, t, dmg, dtype, card)

    def lose_hp(self, source, target, amount, dtype, card=None):
        """逐点扣减体力，每点触发 节命/不屈/狂骨 钩子并检查濒死。"""
        for _ in range(amount):
            if self.ended or not target.alive:
                return
            target.hp -= 1
            self.log(f'{target.name} 体力 -1（hp={target.hp}）')
            # 记录最近一次伤害来源，供濒死/死亡时判定击杀者（挥泪依赖）
            self.killer_of[target.name] = source
            self.skills.on_hp_lost(target, source, dtype, card)
            self.skills.on_damage_dealt(source, target, dtype, card)
            self.check_dying(target)

    def check_dying(self, p):
        if p.hp >= 1 or not p.alive:
            return
        # 不屈：最后一张不屈牌点数与之前都不同 → 存活
        if p.has_skill('不屈') and p.bq and p.bq[-1].rank not in {c.rank for c in p.bq[:-1]}:
            self.log(f'{p.name} 因【不屈】存活（hp={p.hp}）')
            return
        self.dying_flow(p)

    def dying_flow(self, p):
        self.log(f'{p.name} 进入濒死状态（hp={p.hp}）')
        source = self.killer_of.get(p.name)
        guard = 0
        while p.hp < 1 and p.alive and guard < 20:
            guard += 1
            if p.ai.ask_peach_dying():
                continue
            # 其他角色救援（1v1 对手 AI 默认不救）
            saved = False
            for o in self.others(p):
                if o.ai.ask_peach_for_other(p):
                    saved = True
                    break
            if saved:
                continue
            break
        if p.hp < 1:
            self.kill(p, source)

    def kill(self, p, killer):
        p.hp = 0
        p.alive = False
        self.log(f'{p.name} 死亡！击杀者：{killer.name if killer else "无"}')
        if killer:
            self.killer_of[p.name] = killer
        self.skills.on_death(p, killer)
        self.ended = True
        # 击杀者为空（闪电/环境伤害等）时，胜者=仍存活的另一名角色
        if killer:
            self.winner = killer
            self.result = killer.name
        else:
            alive = [q for q in self.players if q.alive]
            self.winner = alive[0] if len(alive) == 1 else None
            self.result = alive[0].name if len(alive) == 1 else 'draw'

    # ============================================================
    # 拼点（驱虎）
    # ============================================================
    def pindian(self, a, b):
        ca = a.ai.choose_pindian_card()
        cb = b.ai.choose_pindian_card()
        if ca is None or cb is None:
            self.log(f'拼点失败：{a.name if ca is None else b.name} 无手牌')
            return None
        self.spend_hand(a, ca)
        self.spend_hand(b, cb)
        self.log(f'拼点: {a.name}={ca} vs {b.name}={cb}')
        if ca.rank > cb.rank:
            return a
        if cb.rank > ca.rank:
            return b
        return None   # 平局：发起者视为"没赢"

    # ============================================================
    # 无懈可击
    # ============================================================
    def try_nullify(self, card, user, affected):
        """锦囊结算前询问无懈。返回 True 表示锦囊被抵消。
        1v1 中反方（对手）优先无懈，user 可反打，交替进行。"""
        side = 'anti'
        while True:
            if side == 'anti':
                o = self.others(user)[0]
                if o.alive and o.ai.ask_nullify(card, is_pro=False):
                    self.use_wuxie(o)
                    side = 'pro'
                    continue
                return False
            else:
                if user.alive and user.ai.ask_nullify(card, is_pro=True):
                    self.use_wuxie(user)
                    side = 'anti'
                    continue
                return True

    def use_wuxie(self, p):
        for c in p.hand:
            if c.name == '无懈可击':
                self.spend_hand(p, c)
                self.log(f'{p.name} 打出【无懈可击】')
                self._count_skill('无懈可击')
                return

    # ============================================================
    # 出牌阶段卡牌结算
    # ============================================================
    def use_card(self, p, card, target=None, targets=None):
        if card.subtype == 'sha':
            return self.use_sha(p, card, target)
        if card.subtype == 'tao':
            return self.use_tao(p)
        if card.subtype == 'jiu':
            return self.use_jiu(p)
        if card.kind == 'equip':
            return self.use_equip(p, card)
        if card.name == '乐不思蜀' or card.name == '兵粮寸断':
            return self.use_delayed(p, card, target)
        if card.name == '闪电':
            return self.use_lightning(p, card)
        name = card.name
        if name == '决斗':
            return self.use_duel(p, card, target)
        if name == '过河拆桥':
            return self.use_dismantle(p, card, target)
        if name == '顺手牵羊':
            return self.use_snatch(p, card, target)
        if name == '无中生有':
            self.spend_hand(p, card)
            if self.try_nullify(card, p, [p]):
                return True
            self.draw_cards(p, 2)
            return True
        if name == '无懈可击':
            return False
        if name == '借刀杀人':
            return self.use_borrow(p, card, target)
        if name == '五谷丰登':
            return self.use_wugu(p, card)
        if name == '南蛮入侵':
            return self.use_nanman(p, card)
        if name == '万箭齐发':
            return self.use_wanjian(p, card)
        if name == '桃园结义':
            return self.use_taoyuan(p, card)
        if name == '火攻':
            return self.use_fireattack(p, card, target)
        if name == '铁索连环':
            return self.use_chain(p, card, targets)
        return False

    # ---------- 基本牌 ----------
    def armor_ignored(self, attacker, target):
        return bool(attacker.weapon and attacker.weapon.name == '青釭剑')

    def use_sha(self, p, card, target):
        if target is None or target is p or not target.alive:
            return False
        if not self.sha_legal(p, card, target):
            return False
        if p.used_sha >= 1 and not (p.weapon and p.weapon.name == '诸葛连弩'):
            return False
        self.spend_hand(p, card)
        p.used_sha += 1
        self._note_sha_use(p)
        self.log(f'{p.name} 对 {target.name} 使用 {card}')

        # 黑杀：毅重 / 仁王盾 无效
        if card.color == 'black':
            if target.has_skill('毅重') and target.armor is None:
                self.log(f'{target.name} 【毅重】免疫黑色杀')
                return True
            armor = None if self.armor_ignored(p, target) else target.armor
            if armor and armor.name == '仁王盾':
                self.log(f'{target.name} 【仁王盾】免疫黑色杀')
                return True

        # 雌雄双股剑：异性目标弃一张手牌或你摸一张
        if p.weapon and p.weapon.name == '雌雄双股剑' and p.gender != target.gender:
            if target.hand and target.ai.choose_discard_vs_let_draw(p):
                c = target.ai.choose_card_to_discard_any(1)[0]
                self.remove_card(target, c)
                self.discard.append(c)
                self.log(f'{target.name} 因【雌雄双股剑】弃置 {c}')
            else:
                self.draw_cards(p, 1)

        # 目标出闪
        dodged = self.ask_target_dodge(target, p, card)
        if dodged:
            # 青龙偃月刀：被杀闪避后可再追一刀
            if p.weapon and p.weapon.name == '青龙偃月刀' and self.sha_legal(p, card, target):
                follow = p.ai.ask_qinglong_followup()
                if follow:
                    fc = p.ai.choose_sha_card()
                    if fc:
                        self.spend_hand(p, fc)
                        p.used_sha += 1
                        self._note_sha_use(p)
                        self.log(f'{p.name} 【青龙偃月刀】追加使用 {fc}')
                        return self.use_sha(p, fc, target)
            # 贯石斧：被杀闪避后可弃2张强制命中
            if p.weapon and p.weapon.name == '贯石斧' and len(p.hand) >= 2:
                if p.ai.ask_guanshi():
                    for c in p.ai.choose_cards_to_discard(2):
                        self.spend_hand(p, c)
                    self.log(f'{p.name} 【贯石斧】弃2张强制命中')
                    dodged = False
            if dodged:
                self.log(f'{target.name} 闪避 {card}')
                return True

        # 命中结算
        self.log(f'{card} 命中 {target.name}')
        dmg = 1
        if p.wine_count > 0:
            dmg += 1
            p.wine_count = 0
        if p.weapon and p.weapon.name == '古锭刀' and not target.hand:
            dmg += 1
        # 伤害类型
        if card.name == '火杀':
            cdtype = 'fire'
        elif card.name == '雷杀':
            cdtype = 'lightning'
        else:
            cdtype = 'normal'
        if p.weapon and p.weapon.name == '朱雀羽扇' and card.name == '杀' and p.ai.ask_zhuque():
            cdtype = 'fire'

        # 寒冰剑：命中后可弃目标2张牌代替伤害（官方规则：攻击者指定弃哪张）
        if p.weapon and p.weapon.name == '寒冰剑' and p.ai.ask_hanbing():
            n = min(2, len(target.all_cards))
            if n > 0:
                cards = p.ai.choose_target_cards_to_discard(target, n)
                for c in cards:
                    self.remove_card(target, c)
                    self.discard.append(c)
                self.log(f'{p.name} 【寒冰剑】弃置 {target.name} 的 {", ".join(str(c) for c in cards)} 代替伤害')
                return True

        # 麒麟弓：命中后可弃目标一匹坐骑
        if p.weapon and p.weapon.name == '麒麟弓' and (target.p1horse or target.m1horse):
            if p.ai.ask_qiling():
                horse = p.ai.choose_horse_to_discard(target)
                if horse:
                    self.remove_card(target, horse)
                    self.discard.append(horse)
                    self.log(f'{p.name} 【麒麟弓】弃置 {target.name} 的 {horse}')

        self.deal_damage(p, target, dmg, cdtype, card)
        return True

    def sha_legal(self, p, card, target):
        if not target.alive or target is p:
            return False
        if not self.in_range(p, target):
            return False
        if not target.hand and target.has_skill('空城'):
            return False
        return True

    def ask_target_dodge(self, target, attacker, card):
        armor = None if self.armor_ignored(attacker, target) else target.armor
        if armor and armor.name == '八卦阵' and target.ai.ask_baguazhen():
            jc = self.judge(target, '八卦阵')
            if self.ended:
                return False
            if jc.color == 'red':
                self.log(f'{target.name} 【八卦阵】判定红，视为出闪')
                return True
        if target.ai.ask_dodge(attacker, card):
            shan = target.ai.choose_shan_card()
            if shan is None:
                return False
            self.spend_hand(target, shan)
            self.log(f'{target.name} 打出 {shan}')
            self.skills.on_play_shan(target, attacker)
            return True
        return False

    def use_tao(self, p):
        if p.hp >= p.max_hp:
            return False
        card = p.ai.choose_tao_card()
        self.spend_hand(p, card)
        p.hp = min(p.max_hp, p.hp + 1)
        self.log(f'{p.name} 使用【桃】回复1体力')
        self.skills.on_peach_used(p, p)
        return True

    def use_jiu(self, p):
        if p.used_wine:
            return False
        card = p.ai.choose_jiu_card()
        self.spend_hand(p, card)
        p.used_wine = True
        p.wine_count = 1
        self.log(f'{p.name} 使用【酒】（下张杀伤害+1）')
        return True

    # ---------- 锦囊 ----------
    def use_duel(self, p, card, target):
        if target is p or not target.alive:
            return False
        if not target.hand and target.has_skill('空城'):
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [target]):
            return True
        self.resolve_duel(p, target)
        return True

    def resolve_duel(self, user, target, virtual=False):
        """决斗：目标先出杀，交替，先不出者受1点伤害（来源为对方）。"""
        self.log(f'{user.name} 与 {target.name} 决斗')
        current, other = target, user
        guard = 0
        while guard < 30:
            guard += 1
            if current.ai.ask_sha_for_duel(other, target):
                fc = current.ai.choose_sha_card()
                self.spend_hand(current, fc)
                self._note_sha_use(current)
                self.log(f'{current.name} 打出 {fc}')
                current, other = other, current
            else:
                self.log(f'{current.name} 无法打出【杀】，受到 {other.name} 的1点伤害')
                self.deal_damage(other, current, 1)
                break
            if self.ended:
                return

    def use_dismantle(self, p, card, target):
        if target is p or not target.alive:
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [target]):
            return True
        avail = target.all_cards
        if not avail:
            self.log(f'{target.name} 无牌可拆')
            return True
        c = p.ai.choose_card_to_dismantle(target, avail)
        self.remove_card(target, c)
        self.discard.append(c)
        self.log(f'{p.name} 弃置 {target.name} 的 {c}')
        return True

    def use_snatch(self, p, card, target):
        if target is p or not target.alive:
            return False
        if target.has_skill('谦逊'):
            return False
        if self.distance(p, target) > 1:
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [target]):
            return True
        avail = target.all_cards
        if not avail:
            return True
        c = p.ai.choose_card_to_steal_any(target)
        if c is None:
            return True
        self.remove_card(target, c)
        p.hand.append(c)
        self.log(f'{p.name} 获得 {target.name} 的 {c}')
        return True

    def use_borrow(self, p, card, target):
        if target is p or not target.alive or not target.weapon:
            return False
        # 指定另一名角色（1v1 即 p 自己）需在 target 攻击范围内
        if not self.in_range(target, p):
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [target]):
            return True
        if target.ai.ask_play_sha_for_borrow(p):
            fc = target.ai.choose_sha_card()
            if fc:
                self.spend_hand(target, fc)
                self._note_sha_use(target)
                self.log(f'{target.name} 按借刀杀人命令打出 {fc}')
                return self.use_sha(target, fc, p)
        # 否则交出武器
        weapon = target.weapon
        self.remove_card(target, weapon)
        p.hand.append(weapon)
        self.log(f'{target.name} 将 {weapon} 交给 {p.name}')
        return True

    def use_wugu(self, p, card):
        self.spend_hand(p, card)
        if self.try_nullify(card, p, self.alive_players):
            return True
        n = len(self.alive_players)
        revealed = []
        for _ in range(n):
            if not self.draw_pile:
                self._reshuffle()
            if not self.draw_pile:
                self._end_draw()
                return True
            revealed.append(self.draw_pile.pop())
        self.log(f'【五谷丰登】翻出: ' + ', '.join(str(c) for c in revealed))
        order = [p] + self.others(p)
        for pl in order:
            if not pl.alive:
                continue
            c = pl.ai.choose_wugu_card(revealed)
            revealed.remove(c)
            pl.hand.append(c)
            self.log(f'{pl.name} 获得 {c}')
        for c in revealed:
            self.discard.append(c)
        return True

    def use_nanman(self, p, card):
        self.spend_hand(p, card)
        o = self.others(p)[0]
        if self.try_nullify(card, p, [o]):
            return True
        if o.armor and o.armor.name == '藤甲' and not self.armor_ignored(p, o):
            self.log(f'{o.name} 【藤甲】免疫南蛮入侵')
        elif o.ai.ask_sha_for_nanman():
            # 响应杀需真实打出：消耗手牌并破坏克己（与决斗/借刀一致）
            fc = o.ai.choose_sha_card()
            if fc is not None:
                self.spend_hand(o, fc)
                self._note_sha_use(o)   # 回合外响应，不破克己
                self.log(f'{o.name} 打出 {fc} 响应南蛮入侵')
        else:
            self.deal_damage(p, o, 1)
        return True

    def use_wanjian(self, p, card):
        self.spend_hand(p, card)
        o = self.others(p)[0]
        if self.try_nullify(card, p, [o]):
            return True
        if o.armor and o.armor.name == '藤甲' and not self.armor_ignored(p, o):
            self.log(f'{o.name} 【藤甲】免疫万箭齐发')
        elif o.ai.ask_dodge_for_wanjian():
            shan = o.ai.choose_shan_card()
            if shan is not None:
                self.spend_hand(o, shan)
                self.log(f'{o.name} 打出 {shan}')
                self.skills.on_play_shan(o, p)
        else:
            self.deal_damage(p, o, 1)
        return True

    def use_taoyuan(self, p, card):
        self.spend_hand(p, card)
        if self.try_nullify(card, p, self.alive_players):
            return True
        for pl in self.alive_players:
            if pl.hp < pl.max_hp:
                pl.hp += 1
                self.log(f'{pl.name} 因【桃园结义】回复1体力')
        return True

    def use_delayed(self, p, card, target):
        if target is p or not target.alive:
            return False
        if card.name == '乐不思蜀' and target.has_skill('谦逊'):
            return False
        if any(c.name == card.name for c in target.judge_zone):
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [target]):
            return True
        target.judge_zone.append(card)
        self.log(f'{p.name} 对 {target.name} 使用【{card.name}】')
        return True

    def use_lightning(self, p, card):
        for pl in self.players:
            if any(c.name == '闪电' for c in pl.judge_zone):
                return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [p]):
            return True
        p.judge_zone.append(card)
        self.log(f'{p.name} 使用【闪电】置于己方判定区')
        return True

    def use_fireattack(self, p, card, target):
        if target is p or not target.alive or not target.hand:
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, [target]):
            return True
        shown = target.ai.choose_reveal_card()
        if shown is None:
            return True
        self.log(f'{target.name} 因【火攻】亮出 {shown}')
        if p.ai.ask_fireattack_discard(shown):
            same = next((c for c in p.hand if c.suit == shown.suit), None)
            if same:
                self.spend_hand(p, same)
                self.deal_damage(p, target, 1, 'fire')
        return True

    def use_chain(self, p, card, targets):
        if not targets:
            return False
        self.spend_hand(p, card)
        if self.try_nullify(card, p, targets):
            return True
        for t in targets:
            t.chained = not t.chained
            self.log(f'{t.name} 【铁索连环】{"横置" if t.chained else "重置"}')
        return True

    def chongsheng(self, p, card):
        """铁索连环重铸：弃置此牌，摸一张。"""
        self.spend_hand(p, card)
        self.draw_cards(p, 1)
        self.log(f'{p.name} 重铸【铁索连环】摸1张')
        return True

    # ---------- 装备 ----------
    def use_equip(self, p, card):
        slot = {'weapon': 'weapon', 'armor': 'armor',
                'p1horse': 'p1horse', 'm1horse': 'm1horse'}[card.subtype]
        old = getattr(p, slot)
        setattr(p, slot, card)
        self.spend_hand(p, card)
        if old:
            self.discard.append(old)
            self._equip_lost(p, old)
        self.log(f'{p.name} 装备 {card.name}')
        return True

    # ---------- 工具 ----------
    def _count_skill(self, name):
        d = self.stats['skill_triggers']
        d[name] = d.get(name, 0) + 1

    def count_skill(self, name):
        return self.stats['skill_triggers'].get(name, 0)
