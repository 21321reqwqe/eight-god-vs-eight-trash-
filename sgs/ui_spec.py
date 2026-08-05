# -*- coding: utf-8 -*-
"""
GUI 可调参数元数据规格：gui.py 据此自动生成控件（数值/下拉/勾选）。

每项字段：
  key     — config 字典里的键（scope=rules/strategy），或运行参数名（scope=run）
  scope   — 'rules' | 'strategy' | 'run'
  type    — 'int' | 'float' | 'bool' | 'select' | 'text'
  label   — 中文显示名
  help    — 说明（tooltip）
  min/max/step — 数值控件范围（type=int/float；int 用 Spinbox，float 用滑块）
  options — type=select 的选项：字符串列表（显示=值）或 (显示, 值) 元组列表
  default — 仅 scope=run 需要；rules/strategy 默认值从 config 读取，保证与 config.py 同步

排除的"死参数"（全仓库无读取，改了不生效）：card_value_scale、use_taoyuan_when_hp_le。
P2 暂不做：PLAY_ORDER_A/B 出牌顺序编辑（见 config.py 注释）。
"""


def _sel(*pairs):
    """选项 helper：接收 (显示, 值) 或直接传字符串（显示=值）。"""
    return list(pairs)


SECTIONS = [
    # ============ 模拟运行 ============
    {
        'title': '模拟运行',
        'scope': 'run',
        'params': [
            {'key': 'games', 'type': 'int', 'min': 10, 'max': 50000, 'step': 10,
             'label': '对局数', 'help': '每批跑多少局（越多越稳定，越慢）', 'default': 2000},
            {'key': 'workers', 'type': 'int', 'min': 1, 'max': 64, 'step': 1,
             'label': '并行进程数', 'help': '1 = 单进程（最稳定）；多进程需可 pickle 的配置', 'default': 8},
            {'key': 'seed_offset', 'type': 'int', 'min': -1000000, 'max': 1000000, 'step': 1,
             'label': '种子偏移', 'help': '固定值可复现结果（随机数种子 = 偏移 + 局序号）', 'default': 0},
        ],
    },
    # ============ 武将与规则 ============
    {
        'title': '武将与规则',
        'scope': 'rules',
        'params': [
            {'key': 'A_NAME', 'type': 'text', 'label': 'A 武将名', 'help': '仅显示用'},
            {'key': 'B_NAME', 'type': 'text', 'label': 'B 武将名', 'help': '仅显示用'},
            {'key': 'A_MAX_HP', 'type': 'int', 'min': 1, 'max': 12, 'step': 1,
             'label': 'A 体力上限', 'help': '影响生存与节命/据守等技能'},
            {'key': 'B_MAX_HP', 'type': 'int', 'min': 1, 'max': 12, 'step': 1,
             'label': 'B 体力上限'},
            {'key': 'A_FACTION', 'type': 'select',
             'options': _sel(('群', '群'), ('魏', '魏'), ('蜀', '蜀'), ('吴', '吴')),
             'label': 'A 势力', 'help': '影响庸肆摸牌数、救援'},
            {'key': 'B_FACTION', 'type': 'select',
             'options': _sel(('吴', '吴'), ('魏', '魏'), ('蜀', '蜀'), ('群', '群')),
             'label': 'B 势力'},
            {'key': 'A_GENDER', 'type': 'select', 'options': _sel('男', '女'),
             'label': 'A 性别', 'help': '影响雌雄双股剑'},
            {'key': 'B_GENDER', 'type': 'select', 'options': _sel('男', '女'),
             'label': 'B 性别'},
            {'key': 'LORD', 'type': 'select',
             'options': _sel(('无主公', None), ('A 为主公', 'A'), ('B 为主公', 'B')),
             'label': '主公设定', 'help': '主公技（救援/激将/伪帝）是否生效'},
            {'key': 'DECK', 'type': 'select',
             'options': _sel(('标准版', 'standard'), ('标准 + 军争', 'standard+junzheng')),
             'label': '牌堆', 'help': '军争含 酒/火攻/火杀雷杀/藤甲 等'},
            {'key': 'DRAW_MODE', 'type': 'select',
             'options': _sel(('突袭取代全部摸牌', 'tuxi_replaces_all'),
                             ('可叠加(非官方)', 'stack')),
             'label': '摸牌叠加规则'},
            {'key': 'FIRST_PLAYER', 'type': 'select',
             'options': _sel(('随机', 'random'), ('A 先手', 'A'), ('B 先手', 'B')),
             'label': '先手'},
            {'key': 'START_HAND', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '开局手牌数'},
            {'key': 'GUANXING_CARDS', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '观星张数', 'help': '0=官方(存活数≤5)；正数=固定看N张（调强观星）'},
            {'key': 'YONGSI_CARDS', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '庸肆张数', 'help': '0=官方(势力数,1v1=2)；正数=固定N张(摸牌额外N/弃牌至少N)'},
            {'key': 'MAX_TURNS', 'type': 'int', 'min': 1, 'max': 1000, 'step': 1,
             'label': '超时回合数', 'help': '超过判定平局/超时胜者'},
            {'key': 'WEAPON_EFFECTS', 'type': 'bool', 'label': '武器技能生效',
             'help': '连弩/寒冰/雌雄等武器特效'},
            {'key': 'ARMOR_EFFECTS', 'type': 'bool', 'label': '防具技能生效',
             'help': '八卦阵/藤甲/仁王盾/白银狮子'},
        ],
    },
    # ============ AI·通用 ============
    {
        'title': 'AI·通用',
        'scope': 'strategy',
        'params': [
            {'key': 'always_dodge', 'type': 'bool', 'label': '永远出闪',
             'help': 'False 时可卖血换节命/不屈'},
            {'key': 'peach_when_damaged', 'type': 'bool', 'label': '受伤就用桃回复'},
            {'key': 'yizhong_no_armor', 'type': 'bool', 'label': '毅重不装防具',
             'help': '毅重(无防具时黑杀无效)角色不装任何防具，保住毅重、让位防具槽'},
        ],
    },
    # ============ AI·A 专属 ============
    {
        'title': 'AI·A 专属',
        'scope': 'strategy',
        'params': [
            {'key': 'tuxi_use', 'type': 'select',
             'options': _sel(('期望价值', 'ev'), ('总是发动', 'always'), ('从不发动', 'never')),
             'label': '突袭', 'help': 'ev=手牌接近上限时偷牌更划算'},
            {'key': 'haoshi_use', 'type': 'select',
             'options': _sel(('从不', 'never'), ('总是', 'always'), ('期望价值', 'ev')),
             'label': '好施'},
            {'key': 'zhitong_value_threshold', 'type': 'float', 'min': 0.0, 'max': 3.0,
             'step': 0.05, 'label': '制衡价值阈值', 'help': '价值低于该值的牌弃掉重摸'},
            {'key': 'zhitong_min_cards', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '制衡最少弃牌'},
            {'key': 'a_sha_attack_hit', 'type': 'float', 'min': 0.1, 'max': 1.0,
             'step': 0.05, 'label': '出杀命中阈值', 'help': '调低=更敢出杀'},
            {'key': 'quhu_use', 'type': 'select',
             'options': _sel(('仅节命连招', 'combo'), ('从不', 'never'), ('总是', 'always')),
             'label': '驱虎'},
            {'key': 'quhu_max_hand', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '驱虎手牌上限', 'help': '连招条件：A 手牌≤该值'},
            {'key': 'quhu_min_hp_gap', 'type': 'int', 'min': 0, 'max': 5, 'step': 1,
             'label': '驱虎体力差', 'help': '连招条件：B 体力至少比 A 高该值'},
            {'key': 'rende_use_when_hp_le', 'type': 'int', 'min': 1, 'max': 6, 'step': 1,
             'label': '仁德触发体力', 'help': 'A 体力≤该值才考虑仁德'},
            {'key': 'rende_min_give', 'type': 'int', 'min': 1, 'max': 6, 'step': 1,
             'label': '仁德最少送牌', 'help': '≥2 才回血'},
            {'key': 'rende_max_give', 'type': 'int', 'min': 1, 'max': 6, 'step': 1,
             'label': '仁德最多送牌'},
            {'key': 'rende_give_penalty', 'type': 'float', 'min': 0.0, 'max': 2.0,
             'step': 0.05, 'label': '仁德送牌惩罚', 'help': '送牌对己方价值的折算系数'},
            {'key': 'guanxing_keep_value', 'type': 'float', 'min': 0.0, 'max': 2.0,
             'step': 0.05, 'label': '观星保留阈值', 'help': '价值高于该值放牌堆顶'},
            {'key': 'bingliang_prio', 'type': 'bool', 'label': '重视兵粮寸断',
             'help': 'A 把兵粮寸断视为高价值断粮牌：价值2.2(不弃不制衡)、优先打出(3.0)；断B摸牌=断心战/克己引擎'},
        ],
    },
    # ============ AI·B 专属 ============
    {
        'title': 'AI·B 专属',
        'scope': 'strategy',
        'params': [
            {'key': 'keji_hoard_sha_gt', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '克己出杀阈值', 'help': '手牌杀超过该张数才主动出杀'},
            {'key': 'keji_attack_when_lethal', 'type': 'bool', 'label': '克己可斩杀即出手'},
            {'key': 'jushou_hp_le', 'type': 'int', 'min': 0, 'max': 6, 'step': 1,
             'label': '据守触发体力', 'help': 'B 体力≤该值才用'},
            {'key': 'jushou_opp_hand_le', 'type': 'int', 'min': 0, 'max': 10, 'step': 1,
             'label': '据守对手手牌', 'help': '对手手牌≤该值（安全）时用'},
            {'key': 'jushou_hand_gt_hp', 'type': 'bool', 'label': '据守手牌>体力时用'},
            {'key': 'xinzhan_use', 'type': 'select',
             'options': _sel(('手牌>体力时', 'auto'), ('从不', 'never')),
             'label': '心战'},
            {'key': 'xinzhan_sell_blood', 'type': 'bool', 'label': '心战卖血流',
             'help': 'B 存桃不治伤、故意吃伤害（不闪/不应南蛮）保证手牌>体力，心战更易发动'},
            {'key': 'duel_use_when_opp_sha_le', 'type': 'float', 'min': 0.0, 'max': 5.0,
             'step': 0.5, 'label': '决斗触发阈值', 'help': '估计对手杀≤该值才用决斗'},
            {'key': 'bingliang_hoard', 'type': 'bool', 'label': '囤死兵粮寸断',
             'help': 'B 绝不使用兵粮寸断，囤死留手牌喂心战（实测囤>打）；关=恢复有就打'},
        ],
    },
    # ============ AI·卡牌与细节 ============
    {
        'title': 'AI·卡牌与细节',
        'scope': 'strategy',
        'params': [
            {'key': 'use_nanman', 'type': 'bool', 'label': '使用南蛮入侵'},
            {'key': 'use_wanjian', 'type': 'bool', 'label': '使用万箭齐发',
             'help': '注意：万箭让对手打闪→触发雷击'},
            {'key': 'use_wugu', 'type': 'bool', 'label': '使用五谷丰登'},
            {'key': 'wine_before_sha', 'type': 'bool', 'label': '先喝酒再出杀'},
            {'key': 'sha_opp_hand_hit', 'type': 'float', 'min': 0.0, 'max': 4.0,
             'step': 0.1, 'label': '杀价值系数', 'help': '杀的价值 = 命中×伤害×该系数'},
            {'key': 'min_action_value', 'type': 'float', 'min': 0.0, 'max': 3.0,
             'step': 0.1, 'label': '最小动作价值', 'help': '价值低于该值的出牌动作不执行'},
            {'key': 'hanbing_hunt', 'type': 'bool', 'label': '寒冰剑猎手（实验）',
             'help': 'A 全力找寒冰剑（实验证明负收益）'},
            {'key': 'hanbing_use', 'type': 'bool', 'label': '寒冰剑削牌（实验）'},
            {'key': 'hanbing_burst', 'type': 'bool', 'label': '寒冰剑蓄爆流（实验）'},
            {'key': 'safe_damage_mode', 'type': 'bool', 'label': '安全伤害模式',
             'help': 'A 主打南蛮/决斗/火攻，不出杀/万箭（专克雷击）'},
        ],
    },
]

# 每个参数的 scope 由所属 section 注入；key -> spec 索引（GUI 用）
INDEX = {}
for _sec in SECTIONS:
    for _p in _sec['params']:
        _p['scope'] = _sec['scope']
        INDEX[_p['key']] = _p
