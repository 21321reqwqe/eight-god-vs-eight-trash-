# -*- coding: utf-8 -*-
"""
卡牌定义与牌堆构建。

每张牌带 名称/花色/点数/类别。花色与点数对以下技能是必须的：
  - 心战：红桃牌
  - 闪电判定：黑桃 2-9
  - 拼点（驱虎）：点数大小
  - 不屈：点数是否重复
  - 毅重/仁王盾：黑色杀
具体花色点数分布对胜率影响极小，如需调整直接改下面的牌堆表。
"""

from dataclasses import dataclass, field

# ---- 花色 ----
SPADE, HEART, CLUB, DIAMOND = 'spade', 'heart', 'club', 'diamond'
SUIT_CN = {SPADE: '♠', HEART: '♥', CLUB: '♣', DIAMOND: '♦'}
RANK_STR = ['', 'A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
BLACK_SUITS = (SPADE, CLUB)

DAMAGE_CN = {'normal': '普通', 'fire': '火焰', 'lightning': '雷电'}


@dataclass
class Card:
    name: str                 # '杀'/'火杀'/'雷杀'/'闪'/'桃'/'酒'/锦囊名/装备名
    suit: str                 # spade/heart/club/diamond
    rank: int                 # A=1 ... K=13
    id: int = -1
    kind: str = 'basic'       # 'basic' | 'trick' | 'equip'
    subtype: str = ''         # 'sha'/'shan'/'tao'/'jiu' | 锦囊名 | 'weapon'/'armor'/'p1horse'/'m1horse'
    weapon_range: int = 1     # 武器攻击范围（非武器忽略）

    @property
    def color(self) -> str:
        return 'black' if self.suit in BLACK_SUITS else 'red'

    @property
    def is_heart(self) -> bool:
        return self.suit == HEART

    @property
    def is_spade_2_9(self) -> bool:
        return self.suit == SPADE and 2 <= self.rank <= 9

    def __repr__(self):
        return f'[{self.name} {SUIT_CN[self.suit]}{RANK_STR[self.rank]}]'

    __str__ = __repr__


# ---- 武器攻击范围 ----
WEAPON_RANGE = {
    '诸葛连弩': 1, '青釭剑': 2, '雌雄双股剑': 2, '青龙偃月刀': 3,
    '丈八蛇矛': 3, '贯石斧': 3, '寒冰剑': 2, '麒麟弓': 5,
    '古锭刀': 2, '朱雀羽扇': 4,
}
ARMOR_NAMES = ('八卦阵', '藤甲', '仁王盾', '白银狮子')
P1HORSE_NAMES = ('的卢', '绝影', '爪黄飞电', '骅骝')
M1HORSE_NAMES = ('赤兔', '大宛', '紫骍')


def classify(name):
    """根据牌名判断 kind/subtype。"""
    if name in ('杀', '火杀', '雷杀'):
        return 'basic', 'sha'
    if name == '闪':
        return 'basic', 'shan'
    if name == '桃':
        return 'basic', 'tao'
    if name == '酒':
        return 'basic', 'jiu'
    if name in WEAPON_RANGE:
        return 'equip', 'weapon'
    if name in ARMOR_NAMES:
        return 'equip', 'armor'
    if name in P1HORSE_NAMES:
        return 'equip', 'p1horse'
    if name in M1HORSE_NAMES:
        return 'equip', 'm1horse'
    return 'trick', name


# ============================================================
# 标准版牌堆（约106张）
# 每项: (牌名, 花色, 点数)
# ============================================================
STANDARD = [
    # 杀 ×30（红11 黑19）
    ('杀', 'heart', 1), ('杀', 'heart', 12),
    ('杀', 'diamond', 1), ('杀', 'diamond', 6), ('杀', 'diamond', 7), ('杀', 'diamond', 8),
    ('杀', 'diamond', 9), ('杀', 'diamond', 10), ('杀', 'diamond', 11), ('杀', 'diamond', 12),
    ('杀', 'diamond', 13),
    ('杀', 'spade', 1), ('杀', 'spade', 7), ('杀', 'spade', 8), ('杀', 'spade', 9),
    ('杀', 'spade', 10), ('杀', 'spade', 11), ('杀', 'spade', 13),
    ('杀', 'club', 1), ('杀', 'club', 2), ('杀', 'club', 3), ('杀', 'club', 4), ('杀', 'club', 5),
    ('杀', 'club', 6), ('杀', 'club', 7), ('杀', 'club', 8), ('杀', 'club', 9), ('杀', 'club', 10),
    ('杀', 'club', 11), ('杀', 'club', 13),
    # 闪 ×15
    ('闪', 'heart', 2), ('闪', 'heart', 7), ('闪', 'heart', 13),
    ('闪', 'diamond', 2), ('闪', 'diamond', 3), ('闪', 'diamond', 4), ('闪', 'diamond', 5),
    ('闪', 'diamond', 6), ('闪', 'diamond', 7), ('闪', 'diamond', 8), ('闪', 'diamond', 9),
    ('闪', 'diamond', 10), ('闪', 'diamond', 11), ('闪', 'diamond', 12), ('闪', 'diamond', 13),
    # 桃 ×8
    ('桃', 'heart', 3), ('桃', 'heart', 4), ('桃', 'heart', 5), ('桃', 'heart', 6),
    ('桃', 'heart', 8), ('桃', 'heart', 9), ('桃', 'heart', 10), ('桃', 'heart', 12),
    # 锦囊 ×36
    ('决斗', 'spade', 1), ('决斗', 'club', 1), ('决斗', 'diamond', 1),
    ('过河拆桥', 'spade', 3), ('过河拆桥', 'spade', 4), ('过河拆桥', 'club', 3),
    ('过河拆桥', 'club', 4), ('过河拆桥', 'club', 12), ('过河拆桥', 'diamond', 3),
    ('顺手牵羊', 'spade', 3), ('顺手牵羊', 'spade', 4), ('顺手牵羊', 'spade', 11),
    ('顺手牵羊', 'diamond', 3), ('顺手牵羊', 'diamond', 4),
    ('无中生有', 'heart', 7), ('无中生有', 'heart', 8), ('无中生有', 'heart', 9), ('无中生有', 'heart', 11),
    ('无懈可击', 'spade', 13), ('无懈可击', 'club', 13), ('无懈可击', 'diamond', 12), ('无懈可击', 'heart', 1),
    ('借刀杀人', 'club', 12), ('借刀杀人', 'club', 13),
    ('五谷丰登', 'heart', 3), ('五谷丰登', 'heart', 4),
    ('南蛮入侵', 'spade', 7), ('南蛮入侵', 'spade', 13), ('南蛮入侵', 'club', 7),
    ('万箭齐发', 'heart', 1),
    ('桃园结义', 'heart', 1),
    ('乐不思蜀', 'spade', 6), ('乐不思蜀', 'club', 6), ('乐不思蜀', 'heart', 6),
    ('闪电', 'spade', 1), ('闪电', 'spade', 12),
    # 装备 ×17
    ('诸葛连弩', 'club', 1), ('诸葛连弩', 'diamond', 1),
    ('青釭剑', 'spade', 6), ('雌雄双股剑', 'spade', 2), ('青龙偃月刀', 'spade', 5),
    ('丈八蛇矛', 'spade', 12), ('贯石斧', 'diamond', 5), ('寒冰剑', 'spade', 2), ('麒麟弓', 'heart', 5),
    ('八卦阵', 'spade', 2), ('八卦阵', 'club', 2),
    ('的卢', 'club', 5), ('绝影', 'spade', 5), ('爪黄飞电', 'heart', 13),
    ('赤兔', 'heart', 5), ('大宛', 'spade', 13), ('紫骍', 'diamond', 13),
]

# ============================================================
# 军争扩展牌堆（约40张）
# ============================================================
JUNZHENG = [
    # 火杀 ×5（红）
    ('火杀', 'heart', 4), ('火杀', 'heart', 7), ('火杀', 'heart', 10),
    ('火杀', 'diamond', 4), ('火杀', 'diamond', 5),
    # 雷杀 ×9（黑）
    ('雷杀', 'spade', 4), ('雷杀', 'spade', 5), ('雷杀', 'spade', 6), ('雷杀', 'spade', 7),
    ('雷杀', 'spade', 8), ('雷杀', 'club', 5), ('雷杀', 'club', 6), ('雷杀', 'club', 7), ('雷杀', 'club', 8),
    # 酒 ×5
    ('酒', 'spade', 9), ('酒', 'club', 3), ('酒', 'club', 9), ('酒', 'diamond', 3), ('酒', 'diamond', 9),
    # 锦囊 ×14
    ('火攻', 'heart', 2), ('火攻', 'heart', 3), ('火攻', 'diamond', 12),
    ('铁索连环', 'spade', 11), ('铁索连环', 'spade', 12), ('铁索连环', 'club', 10),
    ('铁索连环', 'club', 11), ('铁索连环', 'club', 12), ('铁索连环', 'club', 13),
    ('兵粮寸断', 'spade', 10), ('兵粮寸断', 'club', 4),
    ('无懈可击', 'heart', 1), ('无懈可击', 'heart', 13), ('无懈可击', 'diamond', 12),
    # 装备 ×7
    ('古锭刀', 'spade', 1), ('朱雀羽扇', 'diamond', 1),
    ('藤甲', 'spade', 2), ('藤甲', 'club', 2), ('仁王盾', 'club', 2), ('白银狮子', 'club', 1),
    ('骅骝', 'diamond', 13),
]


def build_deck(include_junzheng=True):
    """构建一副牌，返回 Card 列表。"""
    spec = list(STANDARD)
    if include_junzheng:
        spec += list(JUNZHENG)
    cards = []
    for i, (name, suit, rank) in enumerate(spec):
        kind, subtype = classify(name)
        cards.append(Card(name, suit, rank, id=i, kind=kind, subtype=subtype,
                          weapon_range=WEAPON_RANGE.get(name, 1)))
    return cards


def deck_summary(cards):
    from collections import Counter
    c = Counter(x.name for x in cards)
    return dict(c)
