# -*- coding: utf-8 -*-
"""
技能库：所有已实现武将技能的逻辑，通过钩子接入 engine.Game。

约定：
  - 需要玩家决策处统一调用 player.ai 的方法（见 ai.py），引擎/技能只负责结算。
  - 锁定技无条件触发；"可以" 类技能由 AI 决策是否发动。
  - 事件钩子的调用时机见 engine.py 中对应位置。

本文件同时导出 ALL_SKILLS_A / ALL_SKILLS_B 两个武将技能清单：
要换武将只需改这两个列表，无需改动引擎。
"""

# ============================================================
# 武将配置
# ============================================================
# A 武将：自定义技能组
ALL_SKILLS_A = [
    '突袭', '驱虎', '节命', '制衡', '救援', '好施', '缔盟', '仁德', '激将',
    '观星', '空城', '庸肆', '伪帝', '闭月',
]

# B 武将：自定义技能组（2026-08-04 起默认：克己流，去掉雷击/鬼道）
ALL_SKILLS_B = [
    '不屈', '义从', '克己', '心战', '挥泪', '据守', '毅重', '狂骨', '谦逊', '连营',
]

# 全部已实现技能名（引擎/技能库/ai 中有引用），GUI 勾选框用。
# 注意：部分技能在特定对局下天然不生效（如主公技无主公、缔盟单挑不可用）。
# 克己/雷击/鬼道：代码完整实现但默认不在技能组里（2026-08-02 克己替换雷击/鬼道出 B），
# 在此单独加入使 GUI 能勾选（默认不勾）。雷击=打出闪后令对手判定黑桃受2雷电伤害；
# 鬼道=判定牌生效前可用黑色牌替换。
KNOWN_SKILLS = sorted(set(ALL_SKILLS_A + ALL_SKILLS_B + ['克己', '雷击', '鬼道']))


class Skills:
    def __init__(self, game):
        self.g = game

    # ---- 统计 ----
    def _count(self, name):
        self.g._count_skill(name)

    # ============================================================
    # 回合阶段钩子
    # ============================================================
    def on_turn_start(self, p):
        """回合开始阶段：观星。"""
        if p.has_skill('观星') and p.ai.choose_guanxing():
            self._stargaze(p)

    def _stargaze(self, p):
        """观看牌堆顶 X 张并按 AI 排布放回顶/底。

        X 来源：RULES['GUANXING_CARDS']——0/None=官方规则(存活角色数，最多5)，
        正数=固定看 N 张（自定规则，方便调强观星）。最终受牌堆余量约束。
        """
        g = self.g
        x = g.rules.get('GUANXING_CARDS')
        if x:
            X = int(x)
        else:
            X = min(len(g.alive_players), 5)
        X = min(X, len(g.draw_pile))
        if X <= 0:
            return
        top = g.draw_pile[-X:]              # top[-1] 是最顶（最先被摸）
        top_part, bottom_part = p.ai.arrange_stargaze(top)
        del g.draw_pile[-X:]
        g.draw_pile = list(bottom_part) + g.draw_pile      # 牌堆底
        g.draw_pile += list(reversed(top_part))            # top_part[0] 最先被摸
        g.log(f'{p.name} 发动【观星】观看 {X} 张')
        if top_part:
            g.log(f'{p.name} 观星将 {", ".join(str(c) for c in top_part)} 置于牌堆顶')
        if bottom_part:
            g.log(f'{p.name} 观星将 {", ".join(str(c) for c in bottom_part)} 置于牌堆底')
        self._count('观星')

    def on_draw_phase(self, p):
        """摸牌阶段：突袭 / 庸肆 / 好施。"""
        g = self.g
        mode = g.rules.get('DRAW_MODE', 'tuxi_replaces_all')
        # 突袭：放弃摸牌，改为获得其他角色手牌
        if p.has_skill('突袭') and p.ai.choose_tuxi():
            self._tuxi(p)
            if mode == 'tuxi_replaces_all':
                return                      # 突袭取代整个摸牌阶段
            # 'stack' 模式：突袭后继续正常摸牌
        # 基础摸牌
        g.draw_cards(p, 2)
        # 好施：额外摸2，手牌>5 时把一半交给手牌最少者。
        # 先于庸肆触发：此时手牌尚未被庸肆撑大，好施的"交一半"判定基于更小的手牌，
        # 更不容易资敌；庸肆的额外摸牌在好施判定之后补上。
        if p.has_skill('好施') and p.ai.choose_haoshi():
            self._haoshi(p)
        # 庸肆：额外摸 X（锁定技，X=势力数或自定 YONGSI_CARDS）
        if p.has_skill('庸肆'):
            X = g.yongsi_count()
            g.log(f'{p.name} 因【庸肆】额外摸 {X} 张')
            g.draw_cards(p, X)
            self._count('庸肆')

    def _tuxi(self, p):
        """突袭：至多两名其他角色各拿一张手牌（单挑中即对方的一张）。"""
        g = self.g
        for o in g.others(p):
            if o.alive and o.hand:
                c = p.ai.choose_card_to_steal(o)
                if c is None:
                    continue
                g.remove_card(o, c)
                p.hand.append(c)
                g.log(f'{p.name} 发动【突袭】，获得 {o.name} 的 {c}')
        self._count('突袭')

    def _haoshi(self, p):
        """好施：额外摸2；手牌>5 时把一半（向下取整）交给手牌最少者。"""
        g = self.g
        g.log(f'{p.name} 发动【好施】额外摸2张')
        g.draw_cards(p, 2)
        self._count('好施')
        if len(p.hand) > 5:
            n = len(p.hand) // 2
            target = min(g.others(p), key=lambda o: len(o.hand))
            cards = p.ai.choose_cards_to_give(n)
            for c in cards[:n]:
                g.remove_card(p, c)
                target.hand.append(c)
            g.log(f'{p.name} 因【好施】将 {min(n, len(cards))} 张牌交给 {target.name}')

    def on_end_phase(self, p):
        """回合结束阶段：据守（开始时）→ 闭月。"""
        g = self.g
        if p.alive and p.has_skill('据守') and p.ai.choose_jushou():
            g.log(f'{p.name} 发动【据守】摸3张并翻面')
            g.draw_cards(p, 3)
            p.face_down = True
            self._count('据守')
        if p.alive and p.has_skill('闭月'):
            g.log(f'{p.name} 发动【闭月】摸1张')
            g.draw_cards(p, 1)
            self._count('闭月')

    # ============================================================
    # 伤害相关钩子
    # ============================================================
    def on_hp_lost(self, p, source, dtype, card):
        """每扣减1点体力后触发：不屈（亮牌保命）、节命（补牌）。"""
        if p.has_skill('不屈') and p.hp <= 0:
            self._bqu(p)
        if p.has_skill('节命') and p.ai.choose_jiening():
            self._jiening(p)


    def _bqu(self, p):
        """不屈：亮出牌堆顶一张置于武将牌上（engine.check_dying 据此判断存活）。"""
        g = self.g
        if not g.draw_pile:
            g._reshuffle()
        if not g.draw_pile:
            g._end_draw()
            return
        if g.draw_pile:
            c = g.draw_pile.pop()
            p.bq.append(c)
            g.log(f'{p.name} 发动【不屈】，亮出 {c}（第{len(p.bq)}张）')
            self._count('不屈')

    def _jiening(self, p):
        """节命：令一名角色将手牌补至体力上限（不超过5张）。"""
        g = self.g
        target = p.ai.choose_jiening_target()
        n = min(target.max_hp, 5) - len(target.hand)
        if n > 0:
            g.log(f'{p.name} 发动【节命】，令 {target.name} 摸 {n} 张')
            g.draw_cards(target, n)
            self._count('节命')

    def on_damage_dealt(self, source, target, dtype, card):
        """每造成1点伤害后触发：狂骨（距离1以内回1体力）。"""
        if source and source.alive and source.has_skill('狂骨') \
                and self.g.distance(source, target) <= 1 \
                and source.hp < source.max_hp:
            source.hp += 1
            self.g.log(f'{source.name} 触发【狂骨】回复1体力')
            self._count('狂骨')

    def on_death(self, p, killer):
        """死亡时触发：挥泪（杀死你的角色立即弃置所有牌）。"""
        if p.has_skill('挥泪') and killer and killer.alive:
            for c in list(killer.all_cards):
                self.g.remove_card(killer, c)
                self.g.discard.append(c)
            self.g.log(f'{killer.name} 因【挥泪】弃置所有牌')
            self._count('挥泪')

    def on_peach_used(self, user, target):
        """桃结算后触发：救援（吴势力角色对你用桃时额外回复1体力）。
        单挑中无同势力队友，实际不会触发；钩子保留供主公局使用。"""
        if target.has_skill('救援') and user is not target and user.faction == '吴' \
                and target.hp < target.max_hp:
            target.hp += 1
            self.g.log(f'{target.name} 因【救援】额外回复1体力')
            self._count('救援')

    # ============================================================
    # 雷击 / 鬼道（张角技能组）
    # ============================================================
    def on_play_shan(self, p, source):
        """雷击：使用或打出【闪】后，可令一名其他角色判定，黑桃则造成2点雷电伤害。"""
        if p.has_skill('雷击'):
            target = p.ai.choose_leiji_target(source)
            if target is not None:
                self._leiji(p, target)

    def _leiji(self, p, target):
        g = self.g
        g.log(f'{p.name} 发动【雷击】，令 {target.name} 判定')
        jc = g.judge(target, '雷击')          # 判定可被鬼道替换
        if g.ended or jc is None:
            return
        if jc.suit == 'spade':
            g.log(f'【雷击】判定黑桃，造成2点雷电伤害')
            g.deal_damage(p, target, 2, 'lightning', reason='雷击')
        else:
            g.log(f'【雷击】判定 {jc}，未命中')
        self._count('雷击')

    def on_judge(self, judged, card, reason):
        """判定牌生效前：鬼道（打出一张黑色牌替换判定牌）。返回最终判定牌。"""
        for p in self.g.players:
            if p.alive and p.has_skill('鬼道'):
                c = p.ai.ask_guidao_replace(judged, card, reason)
                if c is not None:
                    self.g.spend_hand(p, c)
                    self.g.log(f'{p.name} 发动【鬼道】，用 {c} 替换判定牌 {card}')
                    self._count('鬼道')
                    return c
        return card

    # ============================================================
    # 出牌阶段技能执行（由 AI 决定是否调用）
    # ============================================================
    def skill_zhitong(self, p):
        """制衡：弃置任意数量牌，摸等量。"""
        g = self.g
        cards = p.ai.choose_zhitong_cards()
        if not cards:
            return
        n = len(cards)
        g.log(f'{p.name} 发动【制衡】弃置 {n} 张并摸 {n} 张')
        for c in list(cards):
            g.remove_card(p, c)
            g.discard.append(c)
        p.used_zhitong = True
        g.draw_cards(p, n)
        self._count('制衡')

    def skill_rende(self, p):
        """仁德：把最多 rende_max_give 张手牌交给其他角色，给满2张回1体力。"""
        g = self.g
        cards = p.ai.choose_rende_cards()
        if not cards:
            return
        target = g.others(p)[0]
        n = 0
        for c in list(cards):
            g.remove_card(p, c)
            target.hand.append(c)
            n += 1
        if n >= 2:
            p.hp = min(p.max_hp, p.hp + 1)
            g.log(f'{p.name} 发动【仁德】回1体力')
        g.log(f'{p.name} 发动【仁德】，交给 {target.name} {n} 张牌')
        self._count('仁德')

    def skill_quhu(self, p):
        """驱虎：与体力值大于你的角色拼点。
        单挑中无论胜负都由对方对你造成1点伤害，故仅用于配合节命连招。"""
        g = self.g
        o = g.others(p)[0]
        if o.hp <= p.hp or not p.hand or not o.hand:
            return
        p.used_quhu = True
        g.log(f'{p.name} 发动【驱虎】与 {o.name} 拼点')
        winner = g.pindian(p, o)
        if winner is o:
            g.log(f'{p.name} 驱虎拼点落败')
        else:
            g.log(f'{p.name} 驱虎拼点获胜（含平局）')
        # 赢：o 对其范围内你选的另一角色（单挑中仅自己）造成1点；输：o 对你造成1点
        g.deal_damage(o, p, 1, reason='驱虎')
        self._count('驱虎')

    def skill_xinzhan(self, p):
        """心战：观看牌堆顶3张，获得其中任意红桃，其余按 AI 顺序置回顶。"""
        g = self.g
        p.used_xinzhan = True
        n = min(3, len(g.draw_pile))
        if n <= 0:
            return
        top = g.draw_pile[-n:]
        del g.draw_pile[-n:]
        hearts = [c for c in top if c.is_heart]
        take = p.ai.choose_xinzhan_take(hearts)
        for c in take:
            top.remove(c)
            p.hand.append(c)
        rest = [c for c in top if c not in take]
        rest_sorted = p.ai.arrange_xinzhan_rest(rest)
        g.draw_pile += list(reversed(rest_sorted))   # rest_sorted[0] 最先被摸
        detail = f'：{", ".join(str(c) for c in take)}' if take else ''
        g.log(f'{p.name} 发动【心战】，获得 {len(take)} 张红桃{detail}')
        self._count('心战')

    def skill_dimeng(self, p):
        """缔盟：弃 X 张（X=两名其他角色手牌数差），令其交换手牌。
        单挑中无两名其他角色，实际不会触发；实现保留供多人局使用。"""
        g = self.g
        others = [pl for pl in g.players if pl.alive and pl is not p]
        if len(others) < 2:
            return
        p.used_dimeng = True
        a, b = others[0], others[1]
        diff = abs(len(a.hand) - len(b.hand))
        if diff > len(p.hand):
            return
        cards = p.ai.choose_cards_to_discard(diff)
        for c in cards[:diff]:
            g.remove_card(p, c)
            g.discard.append(c)
        a.hand, b.hand = b.hand, a.hand
        g.log(f'{p.name} 发动【缔盟】弃置 {diff} 张，令 {a.name} 与 {b.name} 交换手牌')
        self._count('缔盟')

    def ask_jijiang(self, p):
        """激将（主公技）：需要打杀时令其他蜀势力角色代打。
        单挑中无蜀势力队友，恒返回 None；钩子保留供主公局/多人局使用。"""
        for o in self.g.others(p):
            if o.alive and o.faction == '蜀' and o.ai.has_sha():
                c = o.ai.choose_sha_card()
                self.g.spend_hand(o, c)
                return c
        return None
