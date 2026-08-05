# -*- coding: utf-8 -*-
"""
卡牌价值估算（AI 决策用）。

函数签名约定：
  card_value(game, player, card)    —— 某张牌对 player 的价值
  equip_value(game, player, card)   —— 装备某件装备的绝对价值（不扣当前装备）

数值越大代表越值得保留/使用。本模块只读状态，不修改任何数据。
所有启发式阈值集中在 config.STRATEGY，改配置即可调 AI 手感。
"""

# 阈值全部从 game.cfg['STRATEGY'] 读取（按局生效），见各函数内 g.strat。



def _opp(g, p):
    return g.others(p)[0]


def _safe(g, p):
    """安全伤害模式（A）：主打南蛮/决斗/火攻，不出杀/万箭。"""
    return g.strat.get('safe_damage_mode') and p is g.a


def _hit_prob(opp):
    """估计杀命中概率：对手手牌越多越难命中。"""
    n = len(opp.hand)
    if n <= 1:
        return 0.85
    if n <= 3:
        return 0.65
    return 0.5


# ---- 锦囊基础价值（随后按场上状态微调）----
TRICK_BASE = {
    '无中生有': 2.4,
    '顺手牵羊': 2.1,
    '过河拆桥': 1.8,
    '无懈可击': 1.4,
    '决斗': 1.5,
    '南蛮入侵': 1.2,
    '万箭齐发': 1.2,
    '借刀杀人': 0.7,
    '五谷丰登': 1.0,
    '桃园结义': 0.6,
    '乐不思蜀': 2.0,
    '兵粮寸断': 1.4,
    '闪电': 0.3,
    '火攻': 1.0,
    '铁索连环': 0.6,
}


def card_value(g, p, card):
    name = card.name

    # ---------- 基本牌 ----------
    if card.subtype == 'sha':
        return _sha_value(g, p, card)
    if card.subtype == 'shan':
        return 0.9
    if card.subtype == 'tao':
        # 受伤时价值 2.0，满血时只剩濒死救命用途
        return 2.0 if p.hp < p.max_hp else 0.8
    if card.subtype == 'jiu':
        # 有杀且本回合还没喝酒时价值最高
        if not p.used_wine and p.ai.has_sha():
            return 0.9
        return 0.5

    # ---------- 装备 ----------
    if card.kind == 'equip':
        return equip_value(g, p, card)

    # ---------- 锦囊 ----------
    base = TRICK_BASE.get(name, 1.0)
    o = _opp(g, p)

    if name == '顺手牵羊':
        if o.has_skill('谦逊') or g.distance(p, o) > 1 or not o.all_cards:
            return 0.3
        return base
    if name == '过河拆桥':
        return base if o.all_cards else 0.3
    if name == '决斗':
        if not o.hand and o.has_skill('空城'):
            return 0.3
        if p.has_skill('克己'):
            return base - 0.6   # 克己囤牌：打杀破克己
        if _safe(g, p):
            return base + 0.7
        return base
    if name in ('南蛮入侵', '万箭齐发'):
        if o.armor and o.armor.name == '藤甲':
            return 0.3          # 藤甲免疫
        if p.has_skill('克己'):
            return base - 0.5
        # 安全伤害模式：南蛮值得保留，万箭会喂雷击该弃
        if _safe(g, p):
            return base + 1.0 if name == '南蛮入侵' else base - 0.5
        return base
    if name == '乐不思蜀':
        if o.has_skill('谦逊') or any(c.name == '乐不思蜀' for c in o.judge_zone):
            return 0.2
        return base
    if name == '兵粮寸断':
        if any(c.name == '兵粮寸断' for c in o.judge_zone):
            return 0.2
        return base
    if name == '桃园结义':
        self_gain = p.max_hp - p.hp
        opp_gain = o.max_hp - o.hp
        return max(0.0, (self_gain - opp_gain) * 0.8)
    if name == '借刀杀人':
        if not o.weapon or not g.in_range(o, p):
            return 0.2
        return base
    if name == '火攻':
        if not o.hand:
            return 0.3
        if _safe(g, p):
            return base + 1.0
        return base
    if name == '铁索连环':
        return 0.7   # 1v1 中主要价值是重铸
    if name == '闪电':
        return 0.3
    if name == '无中生有':
        return base + max(0, (6 - len(p.hand)) * 0.15)
    if name == '无懈可击':
        # 暗牌：看不到对手手牌内容，按手牌数估算其持无懈的概率（牌堆约 5% 一张）
        p_opp = 1 - (1 - 0.05) ** len(o.hand)
        return base + 0.5 * p_opp
    return base


def _sha_value(g, p, card):
    o = _opp(g, p)
    # 空城：对手无手牌时不能成为杀的目标
    if not o.hand and o.has_skill('空城'):
        return 0.2
    # 本回合已出过杀且无连弩：杀暂不可用
    if p.used_sha >= 1 and not (p.weapon and p.weapon.name == '诸葛连弩'):
        return 0.2
    hit = _hit_prob(o)
    dmg = 1
    if p.wine_count > 0:
        dmg += 1
    if p.weapon and p.weapon.name == '古锭刀' and not o.hand:
        dmg += 1
    val = hit * dmg * g.strat['sha_opp_hand_hit']
    # 火杀/雷杀克制藤甲
    if card.name in ('火杀', '雷杀') and o.armor and o.armor.name == '藤甲':
        val += 0.4
    return val


def equip_value(g, p, card):
    """装备某件装备的绝对价值（AI 出牌阶段据此做替换决策）。"""
    o = _opp(g, p)
    subtype = card.subtype

    if subtype == 'weapon':
        return _weapon_value(g, p, card, o)
    if subtype == 'armor':
        # 毅重（无防具时黑杀无效）：开启 yizhong_no_armor 后不装任何防具，保住毅重
        if p.has_skill('毅重') and p.armor is None and g.strat.get('yizhong_no_armor', True):
            return 0.0
        if card.name == '八卦阵':
            return 2.4
        if card.name == '仁王盾':
            # 兜底：即使允许装防具，仁王盾对毅重也零增益（毅重已挡黑杀）且占槽
            if p.has_skill('毅重') and p.armor is None:
                return 0.0
            return 2.2
        if card.name == '藤甲':
            # 免疫普通杀/南蛮/万箭，但火属性伤害+1
            fire_risk = 0.6
            if p.has_skill('狂骨'):
                fire_risk = 0.2   # 狂骨回血对冲藤甲负作用
            return 1.6 - fire_risk
        if card.name == '白银狮子':
            return 1.6
        return 1.0
    if subtype == 'p1horse':
        return 1.2   # 挡住顺手牵羊（对方距离+1）
    if subtype == 'm1horse':
        return 0.5   # 单挑距离恒为1，基本无用
    return 0.5


def _weapon_value(g, p, card, o):
    name = card.name
    if name == '诸葛连弩':
        # 蓄爆流：A 保留连弩不弃（但蓄爆期不抢先装备，寒冰剑优先）
        if g.strat.get('hanbing_burst') and p is g.a:
            return 2.2
        return 3.0 if p.ai.count_sha() >= 3 else 1.6
    if name == '青釭剑':
        return 1.8
    if name == '雌雄双股剑':
        return 1.6 if p.gender != o.gender else 1.0
    if name == '青龙偃月刀':
        return 1.5
    if name == '丈八蛇矛':
        return 1.6
    if name == '贯石斧':
        return 1.7
    if name == '寒冰剑':
        # 寒冰剑猎手：A 全力找它 → 抬高价值（装备/观星/制衡保留/突袭偷取都优先它）
        if g.strat.get('hanbing_hunt') and p is g.a:
            return 3.0
        return 1.4
    if name == '麒麟弓':
        return 1.8
    if name == '古锭刀':
        return 1.8
    if name == '朱雀羽扇':
        return 1.7
    return 1.0
