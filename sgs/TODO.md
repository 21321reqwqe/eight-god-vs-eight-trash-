# 三国杀 1v1 对战胜率模拟器 — 进度交接（Handoff）

> 更新于 2026-08-05。上次交接 2026-08-02。本次会话完成了可视化 GUI、大量 AI/规则修复、默认配置调整。
> 快速接上：读本文件 + `.claude` 记忆（`~/.claude/projects/.../memory/sgs-winrate-simulator.md`）。

---

## 一、项目是什么

用 Python 模拟两名三国杀武将的 1v1 对决，蒙特卡洛统计胜率，用于研究"哪个武将/技能/打法更强"。

**运行方式**：
```bash
python main.py -n 2000 -w 8 -s 42   # CLI 批量模拟
python gui.py                       # ★ 可视化 GUI（推荐，设置页可调全部参数+技能勾选）
```

**代码结构**：
| 文件 | 职责 |
|---|---|
| `config.py` | RULES + STRATEGY（**改这里/用 GUI 即可调规则与 AI**，全部参数已进 ui_spec） |
| `skills.py` | 技能库 + `ALL_SKILLS_A/B`（武将默认技能）+ `KNOWN_SKILLS`（26 个可勾选） |
| `engine.py` | 规则引擎：回合、伤害/濒死/不屈、判定、无懈链、全卡牌结算 |
| `ai.py` | AI 控制器：每决策点一个方法，阈值读 `self.g.strat`（**按局生效**） |
| `evaluate.py` | 卡牌价值估算（AI 选牌/装备估值基础） |
| `simulator.py` | **共享运行模块**（run_batch/run_single），GUI 与 CLI 同源 |
| `gui.py` | Tkinter 三页签：设置 / 胜率结果 / 单局回放；Canvas 图表；JSON 持久化 |
| `ui_spec.py` | 参数元数据，GUI 据此自动生成滑块/下拉/勾选控件 |
| `main.py` | CLI 入口（复用 simulator） |

---

## 二、当前配置（2026-08-05 起为项目默认）

- **A 武将（14 技能）**：突袭、驱虎、节命、制衡、救援、好施、缔盟、仁德、激将、观星、空城、庸肆、伪帝、闭月。A 魏/女，B 为主公
- **B 武将（10 技能，克己流）**：不屈、义从、克己、心战、挥泪、据守、毅重、狂骨、谦逊、连营（**无雷击/鬼道**）
- `庸肆=4`、`观星=5`、先手=A、`DRAW_MODE=tuxi_replaces_all`
- AI：`safe_damage_mode=True`、tuxi/haoshi=ev、xinzhan=auto、`yizhong_no_armor=True`、`keji_hoard_sha_gt=200`、jushou_opp_hand_le=1

**当前默认基线：A ≈ 78% / B ≈ 22%**（庸肆=4 是 A 大优主因）。

---

## 三、本次会话已完成的工作（2026-08-04/05）

1. **可视化 GUI（gui.py/simulator.py/ui_spec.py）**：零依赖 Tkinter 三页签，参数全可调，技能可勾选，Canvas 手绘胜率条/伤害/技能/回合分布，单局回放（播放/暂停/调速），关闭自动存 gui_settings.json（已 gitignore）。
2. **STRATEGY 按局生效重构**：ai.py/evaluate.py 原先读模块级 `config.STRATEGY`（传 cfg 覆盖不生效），改为读 `self.g.strat`。这是"可调节"的地基。
3. **技能列表可调**：RULES 新增 `A_SKILLS/B_SKILLS`（None=默认；空列表=无技能）。`KNOWN_SKILLS` 含克己。
4. **突袭 EV 修正**：旧逻辑"手牌≥体力就偷"每局 ~11 次（A 从 13.4% 拖到 2.7%）。改为真 EV（收益=偷牌期望+削弱分 > 成本=放弃的摸牌价值），常量在 ai.py 顶部（AVG_DRAW_VALUE=1.2 / OVER_LIMIT_DISCOUNT=0.8 / STEAL_DEPLETION_BONUS=0.6）。
5. **暗牌（隐藏信息）修正**：4 处开图全改——突袭/顺手/过拆/寒冰剑偷弃手牌改 `rng.choice` 随机，无懈估值按手牌数估概率。副作用：默认胜率从 13.5%→11.8%。
6. **好施修复 + 摸牌顺序**：ev 分支原是死代码；改为"手牌≤3 才用"（避免资敌）。摸牌顺序改为**好施先于庸肆**（好施"交一半"判定基于未撑大的手牌）。
7. **观星/庸肆张数可调**：`GUANXING_CARDS`（默认5）、`YONGSI_CARDS`（默认4）进 RULES + GUI。
8. **克己/出杀规则修正（官方规则核对）**：克己"未于**出牌阶段内**使用或打出过杀"——只看自己的出牌阶段。新增 `engine._note_sha_use(p)`：回合外响应杀（南蛮/决斗目标/借刀）**不破克己**；自己出决斗继续出杀**破克己**。修了南蛮响应杀**不消耗手牌**的 bug。
9. **毅重+仁王盾联动 + yizhong_no_armor 选项**：仁王盾对"无防具的毅重角色"价值 0；新增选项让毅重角色不装任何防具（**默认 True，但见下"注意事项"——实测坑 B**）。
10. **牌堆耗尽平局规则**：`engine._end_draw()`，双堆皆空→直接平局（官方规则），修了 judge/五谷双空 `pop()` 崩溃。
11. **武将名修改 bug 修复**：simulator.run_batch 硬编码 wins={'A','B'} → 改名后 KeyError。改为用实际名做键。**注意：运行中的 GUI 是旧代码，需重启才生效。**

---

## 四、关键结论 / 数据（别重复踩坑）

| 主题 | 数据 | 结论 |
|---|---|---|
| 庸肆张数 | 4→A 12.8%→37.2%（vs 默认B） | **庸肆是最强 A 杠杆**；当前默认4 → A≈78% |
| 观星张数 | 2→5：A +0.8 点 | 观星5 明显强于官方2 |
| 突袭 always | 与好施 always 叠加 → A=0.4% | **突袭=总是发动 + A 有庸肆 = 灾难**（摸牌阶段被取代） |
| 好施 always | A=0.0% | 1v1 里"多摸但交牌给对手"=资敌，毒药 |
| 心战 never | A 冲到 90.5% | xinzhan=never 让 B 少一大截手牌生成，用户已改回 auto |
| 毅重不装防具 | True: B=21.7% vs False: B=25.5% | **yizhong_no_armor=True 坑 B ~3.8 点**（B 丢了藤甲克南蛮/八卦阵） |
| 克己规则 | 回合外响应杀不破克己 | 已按官方规则实现（之前错误全破） |
| 南蛮响应 | 原来不消耗杀（bug） | 已修：响应要真打杀，但回合外不破克己 |

**默认配置下 A≈78% 的组成**：庸肆4（主因）+ yizhong_no_armor=True（+3.8）+ 先手A。想 A 回到 ~60%：庸肆 4→3 + 关 yizhong 选项 → A≈56%；庸肆2 → A≈35%。

---

## 五、已知问题 / 注意事项

- **GUI 需重启加载新代码**：修改 .py 后，运行中的 GUI 进程仍是旧代码（本次武将名 bug 即此原因）。改完代码请重开 GUI。
- **`yizhong_no_armor=True` 可能是负收益**（见上，坑 B ~3.8 点）。用户最初要求该选项，但实测 B 装藤甲/八卦阵更好。**建议默认改回 False**（用户未最终确认）。
- **`keji_hoard_sha_gt=200` 疑似实验残留**：克己 B 囤 200 张杀才出手 ≈ 永不进攻。对胜率影响小（~0.5 点），若属无意可改回 2。
- **死参数**（改了不生效，已从 UI 剔除）：`card_value_scale`、`use_taoyuan_when_hp_le`。
- `sgs\1\` 是误建空 git 仓库（已 gitignore）。git 身份是占位（xzas/xzas@localhost）。
- 雷击在当前默认（safe_damage_mode=True）下不触发（A 不出杀/万箭），雷击/鬼道已不在 B 默认技能组。

---

## 六、下一步建议

1. **确认 yizhong_no_armor 默认**：实测 False 对 B 更好，建议改回（用户待确认）。
2. **确认 keji_hoard_sha_gt**：200 疑似残留，建议改 2。
3. **调平衡**：想 A≈60% 用 庸肆3 + yizhong关；想 B 占优用 庸肆2 或给 B 加回鬼道/雷击。
4. **扩技能库**：KNOWN_SKILLS 26 个，可加 刚烈/武圣/咆哮/遗计 等。
5. **统计增强**：95% 置信区间、死亡路径分布。
6. **git 收尾**：改真实 git 身份；删残留 `sgs\1\`。

---

## 七、环境 / git 备注

- 工作目录：`C:\Users\xzas\Desktop\1\sgs`（Windows，PowerShell，Python 3.14.3，Tkinter 8.6）
- git master 分支。本次会话提交：`a35d770`(GUI) → `173f1d7`(庸肆可调) → `cadeb96`(克己规则) → `55ea7ee`(毅重选项) → `8281cea`(牌堆平局) → `cf110cf`(默认配置) → `e0c710d`(武将名bug)
- `.gitignore`：`__pycache__/`、`*.pyc`、`1/`、`gui_settings.json`
- 长期记忆已同步（`sgs-winrate-simulator.md`，含本次全部决策与数据）
