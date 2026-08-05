# -*- coding: utf-8 -*-
"""
全局配置：规则参数 + AI 策略参数。

修改本文件即可调整模拟规则与对战 AI，无需改动其他代码。
本文件是可调节性的核心：所有会影响胜负率的开关和阈值都集中在这里。
"""

# ============================================================
# 一、规则参数
# ============================================================
RULES = {
    # ---- 武将基础 ----
    'A_NAME': 'A',
    'B_NAME': 'B',
    'A_MAX_HP': 4,          # A 体力上限
    'B_MAX_HP': 4,          # B 体力上限
    'A_FACTION': '魏',      # A 势力（影响庸肆 X=势力数）
    'B_FACTION': '吴',      # B 势力
    'A_GENDER': '女',       # A 性别（'男'/'女'，影响雌雄双股剑）
    'B_GENDER': '男',       # B 性别

    # ---- 武将技能 ----
    # None = 用 skills.py 的 ALL_SKILLS_A/B 默认清单；
    # 传技能名列表则覆盖（GUI 可自由勾选，未知技能名不会崩溃只会静默不触发）。
    'A_SKILLS': None,
    'B_SKILLS': None,

    # ---- 主公设定 ----
    # None = 无主公，所有主公技（救援/激将/伪帝）一律失效
    # 'A'  = A 为主公，A 的救援/激将 生效；伪帝使 A 视为拥有当前主公的主公技
    # 'B'  = B 为主公，A 的救援/激将 失效
    'LORD': 'B',

    # ---- 牌堆 ----
    # 'standard'          ：标准版
    # 'standard+junzheng' ：标准版 + 军争扩展（酒/火攻/铁索连环/兵粮寸断/火杀/雷杀/藤甲/仁王盾/白银狮子/古锭刀/朱雀羽扇）
    'DECK': 'standard+junzheng',

    # ---- 摸牌阶段技能叠加规则（突袭 / 庸肆 / 好施 同时存在的处理）----
    # 'tuxi_replaces_all' ：突袭一旦发动，"放弃摸牌" 取代整个摸牌阶段，庸肆/好施不再触发
    # 'stack'             ：三者可叠加（非官方规则，供测试与自定规则使用）
    'DRAW_MODE': 'tuxi_replaces_all',

    # ---- 对局 ----
    'FIRST_PLAYER': 'A',       # 'A' / 'B' / 'random'
    'MAX_TURNS': 300,           # 超过该回合数判定为平局/超时
    'START_HAND': 4,            # 开局每名角色手牌数
    # 观星张数：0/None=官方规则(存活角色数，最多5)；正数=固定看 N 张（自定规则，调强观星用）
    'GUANXING_CARDS': 5,
    # 庸肆张数：0/None=官方规则(势力数，1v1=2)；正数=固定 N 张（摸牌额外摸N、弃牌至少弃N）
    'YONGSI_CARDS': 4,

    # ---- 细节开关（想简化规则时可关闭）----
    'WEAPON_EFFECTS': True,     # 武器技能效果（连弩/青釭/雌雄/青龙/丈八/贯石/寒冰/麒麟/古锭/朱雀羽扇）
    'ARMOR_EFFECTS': True,      # 防具效果（八卦阵/藤甲/仁王盾/白银狮子）
}

# ============================================================
# 二、AI 策略参数（微调对战 AI 改这里）
# 所有阈值都有中文注释，改完直接生效。
# ============================================================
STRATEGY = {
    # ---------- 通用 ----------
    'always_dodge': True,          # 永远出闪（若想用"卖血换节命/不屈"可改为 False）
    'peach_when_damaged': True,    # 非濒死时，受伤就使用桃回复
    'yizhong_no_armor': True,      # 毅重（无防具时黑杀无效）：不装任何防具，保住毅重（让位防具槽）

    # ---------- A 专属 ----------
    'tuxi_use': 'ev',              # 突袭：'ev'=按期望价值决策 / 'always' / 'never'
    'haoshi_use': 'ev',            # 好施：'ev'=仅手牌≤3(摸2后≤5不资敌)才用 / 'never' / 'always'
    'zhitong_value_threshold': 1.5,  # 制衡：弃置价值低于该值的牌去重摸（实测降到0.8反而更输）
    'zhitong_min_cards': 1,           # 制衡：至少弃几张才发动
    'a_sha_attack_hit': 0.55,      # 出杀命中率阈值（0.4更敢出手，实测仅微升不显著）
    'quhu_use': 'combo',           # 驱虎：'combo'=仅用于节命连招 / 'never' / 'always'
    'quhu_max_hand': 1,            # 驱虎连招条件：A 手牌数不超过该值（补牌收益才大）
    'quhu_min_hp_gap': 1,          # 驱虎连招条件：B 体力至少比 A 高该值（否则 B 不满足"体力值大于你"）
    'rende_use_when_hp_le': 3,     # 仁德：A 当前体力不超过该值才考虑用（实测限制到1反而更输）
    'rende_min_give': 2,           # 仁德：至少给几张（>=2 才回血，默认 2）
    'rende_max_give': 2,           # 仁德：一次最多给几张（控制给敌方的牌量）
    'rende_give_penalty': 0.7,     # 仁德送牌的价值惩罚系数（0.7=送牌不亏；实测提高反而更输）
    'guanxing_keep_value': 0.8,    # 观星：把价值高于该值的牌放牌堆顶，其余放底
    'bingliang_prio': True,        # 八神重视兵粮寸断：价值提高到2.2（不弃不制衡）、打出优先级3.0（断B摸牌=断心战/克己）

    # ---------- B 专属 ----------
    'keji_hoard_sha_gt': 200,      # 克己：手中【杀】超过该张数才考虑主动出杀（囤牌流）
    'keji_attack_when_lethal': True,  # 克己：能斩杀（对手体力<=1且有杀）时无视囤牌直接出手
    'jushou_hp_le': 2,             # 据守：B 体力不超过该值才用（防守）
    'jushou_opp_hand_le': 1,       # 据守：或对手手牌不超过该值（安全）时用
    'jushou_hand_gt_hp': True,     # 据守：或手牌超过体力（反正要弃）时用
    'xinzhan_use': 'auto',         # 心战：'auto'=手牌>体力时用 / 'never'
    'xinzhan_sell_blood': True,    # 心战卖血流：B 存桃不治伤、故意吃伤害（不闪/不应南蛮）保证手牌>体力可发动心战
    'duel_use_when_opp_sha_le': 1, # B 用决斗：估计对手手里杀不超过该值才用（否则要打出杀破克己）
    'bingliang_hoard': True,       # 蓄意囤积兵粮寸断（激进）：B 绝不使用兵粮，囤死留手牌喂心战（实测囤>打）

    # ---------- 卡牌使用 ----------
    'use_nanman': True,            # 是否使用南蛮入侵
    'use_wanjian': True,           # 是否使用万箭齐发
    'use_taoyuan_when_hp_le': 3,   # 桃园结义：自己体力不超过该值才用（否则帮对手）
    'use_wugu': True,              # 是否使用五谷丰登
    'wine_before_sha': True,       # 是否先喝酒再出杀（酒杀连招）
    'sha_opp_hand_hit': 2.0,       # 杀的价值估算参数（见 evaluate.py）

    # ---------- 数值 ----------
    'card_value_scale': 1.0,       # 卡牌价值整体缩放（调试用）
    'min_action_value': 0.2,       # 出牌阶段：价值低于该值的动作不执行

    # ---------- 技能发动顺序（出牌阶段）----------
    # 留空/None = 纯价值贪心（原行为）。填列表后 AI 按列表顺序找第一个
    # 「可用且价值达标」的动作执行；列表没覆盖的动作退回价值贪心兜底。
    # 可用 key：
    #   技能类  zhitong(制衡) quhu(驱虎) rende(仁德) xinzhan(心战)
    #   卡牌类  peach(桃) wuzhong(无中生有) taoyuan(桃园) wugu(五谷)
    #           duel(决斗) nanman(南蛮) wanjian(万箭) snatch(顺手) dismantle(过拆)
    #           le(乐不思蜀) bingliang(兵粮) shandian(闪电) equip(装备)
    #           wine_sha(酒杀连招) sha(出杀) chongsheng(铁索重铸)
    'PLAY_ORDER_A': None,
    'PLAY_ORDER_B': None,

    # ---------- 本轮新 AI：A 安全伤害模式（主南蛮+决斗+火攻）----------
    # safe_damage_mode：A 主打 南蛮入侵/决斗/火攻（不触发对手出闪），
    # 不出杀/不出万箭（都会让 B 打闪 → 触发雷击反打），专克雷击/鬼道 B。
    # 寒冰剑三开关已关（实验证明对 A 是负收益）。
    'hanbing_hunt': False,
    'hanbing_use': False,
    'hanbing_burst': False,
    'safe_damage_mode': True,
}

# ============================================================
# 三、配置装配（engine.py 从这里取配置）
# ============================================================
def default_config():
    """返回 {'RULES', 'STRATEGY'} 字典，供 Game 使用。"""
    return {'RULES': RULES, 'STRATEGY': STRATEGY}
