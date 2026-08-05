# -*- coding: utf-8 -*-
"""玩家状态。"""


class Player:
    def __init__(self, name, max_hp, faction, gender):
        self.name = name
        self.index = 0
        self.max_hp = max_hp
        self.hp = max_hp
        self.faction = faction
        self.gender = gender
        self.skills = []          # 技能名列表

        # 牌
        self.hand = []            # 手牌
        self.weapon = None        # 武器
        self.armor = None         # 防具
        self.p1horse = None       # +1马
        self.m1horse = None       # -1马
        self.judge_zone = []      # 判定区（乐不思蜀/兵粮寸断/闪电）

        # 状态
        self.alive = True
        self.face_down = False    # 翻面（据守）
        self.chained = False      # 铁索连环

        # 每回合状态（由引擎在回合开始时/结束时重置）
        self.used_sha = 0         # 本回合已使用【杀】的次数（连弩可突破1次限制）
        self.played_sha = False   # 本回合是否使用或打出过【杀】（克己判断）
        self.wine_count = 0       # 酒状态（下张杀伤害+1，出牌阶段限一次）
        self.used_wine = False    # 本回合是否已用【酒】
        self.used_zhitong = False # 制衡（限一次）
        self.used_quhu = False    # 驱虎（限一次）
        self.used_dimeng = False  # 缔盟（限一次）
        self.used_xinzhan = False # 心战（限一次）
        self.skip_play = False    # 跳过出牌阶段（乐不思蜀）
        self.skip_draw = False    # 跳过摸牌阶段（兵粮寸断）

        # 技能附加状态
        self.bq = []              # 不屈牌（周泰）

        self.ai = None            # AI 控制器（引擎挂接）
        self.game = None          # 对局引用

    # ---- 便捷属性 ----
    @property
    def equip_cards(self):
        """装备区里所有牌。"""
        return [c for c in (self.weapon, self.armor, self.p1horse, self.m1horse) if c is not None]

    @property
    def all_cards(self):
        return list(self.hand) + self.equip_cards + list(self.judge_zone)

    def has_skill(self, skill):
        return skill in self.skills

    def card_zone(self, card):
        """返回某张牌所在的区。"""
        if card in self.hand:
            return 'hand'
        if card is self.weapon or card is self.armor or card is self.p1horse or card is self.m1horse:
            return 'equip'
        if card in self.judge_zone:
            return 'judge'
        return None

    def reset_turn_state(self):
        """回合结束后的清理（下次回合开始前由引擎调用）。"""
        self.used_sha = 0
        self.played_sha = False
        self.used_wine = False
        self.wine_count = 0
        self.used_zhitong = False
        self.used_quhu = False
        self.used_dimeng = False
        self.used_xinzhan = False
        self.skip_play = False
        self.skip_draw = False

    def __repr__(self):
        return f'{self.name}(hp={self.hp}/{self.max_hp} 手牌{len(self.hand)})'
