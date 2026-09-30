# 接手提示词：游戏王卡片检索程序（双模式）

> 用法：把下面「=====」之间的全部内容作为提示词发给另一个 LLM（Claude / GPT / 其他代码模型均可）。
> 它包含全部上下文、数据路径、验收标准。效果索引的规格细节在规则文档里，提示词会引导对方先读文档。

=====

# 任务：实现游戏王卡片检索程序（手动筛选 + AI 自然语言双模式）

## 你是谁

你是一个 Python 工程师，接手一个已完成架构设计的项目。**设计已定稿，你的任务是按规格实现一个可运行的检索程序**，不需要重新做架构决策。

## 背景（3 分钟版）

我们在做 Yu-Gi-Oh! OCG 卡片的检索工具，数据源是 ygopro 体系的 `cards.cdb`（15,019 张卡，三语言齐备）。

程序提供**两种检索手段，共用同一个执行引擎**：

1. **手动模式**：用户在界面上勾选条件（类型/属性/种族/星级/系列/效果类别/效果五维…），直接构造筛选 DSL
2. **AI 模式**：用户输入一句自然语言（如"有什么不取对象破坏卡片的仪式怪兽？"），调用 LLM API 把意图解析成**同一个 DSL**，校验后执行，并把解析出的条件回显给用户

卡片效果的深层语义（取不取对象、在哪发动、会不会错过时点、发动无效还是效果无效）不在数据库原始字段里，需要先按规格文档离线构建 `card_effects` 效果段索引表，检索时 JOIN 使用。

**核心原则：DSL 是两种模式与执行引擎之间的唯一契约。LLM 只负责把话翻译成 DSL，检索全走确定性 SQL，绝不让 LLM 直接给答案。**

## 必读文档（先完整读完再动手）

**`C:/Users/Administrator/WorkBuddy/ygosearch/docs/card_effects规则.md`**

包含：数据表结构与字段解码（type/attribute/race/level 打包/category 等全部位掩码规则）、card_effects 建表 schema、效果切分 6 规则、五维分类中日双语正则、官方 32 位 category 对照表、DSL→SQL 编译示例、验收标准与金标集。一切以它为准。

## 数据资产（已存在，只读使用）

| 路径 | 内容 |
|---|---|
| `C:/Users/Administrator/WorkBuddy/ygosearch/cdb/zh-CN/cards.cdb` | 简中卡池（**展示/检索主语言**） |
| `C:/Users/Administrator/WorkBuddy/ygosearch/cdb/ja-JP/cards.cdb` | 日文卡池（**效果分类权威来源**） |
| `C:/Users/Administrator/WorkBuddy/ygosearch/cdb/en-US/cards.cdb` | 英文卡池（备用） |
| `C:/Users/Administrator/WorkBuddy/ygosearch/cdb/zh-CN/strings.conf` | 字符串表：598 条系列名（`!setname`）+ category 位名（`!system 1100`~`1131`） |
| `C:/Users/Administrator/WorkBuddy/ygosearch/cdb/zh-CN/lflist.conf` | 禁限卡表（P1 需求用） |
| `C:/Users/Administrator/WorkBuddy/ygosearch/export/cards_<lang>.json` | 已解码 JSON（与 cdb 等价，可任选读取） |

关键事实：三语言卡片 id 一一对应（已验证）；表结构 `datas(id, ot, alias, setcode, type, atk, def, level, race, attribute, category)` + `texts(id, name, desc, str1..str16)`；效果分类用 ja-JP 文本，展示用 zh-CN。

⚠️ 打开 en-US/ja-JP 的 cdb 后会留下 `-shm`/`-wal` 附属文件（WAL 模式），用完删除：`rm -f cdb/*/cards.cdb-shm cdb/*/cards.cdb-wal`。

## 运行环境（硬约束）

- Python 用绝对路径：`C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe`
- **禁止全局 pip install**。依赖装进 venv：
  `C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe -m venv C:\Users\Administrator\.workbuddy\binaries\python\envs\default`
  （激活后 `pip install flask requests`，或你选的其他轻量框架）
- 工作目录：`C:/Users/Administrator/WorkBuddy/ygosearch`。代码放 `core/`，测试放 `tests/`，索引产物放 `build/`，前端静态文件放 `web/`

## 程序形态

**本地 Web 应用**（单机使用）：Flask（或同级轻量框架）后端 + 单个 HTML 页面（原生 JS，不引前端框架）。启动后浏览器访问 `http://127.0.0.1:端口`：

- 页面上半部：手动筛选区（全部条件控件）+「检索」按钮
- 页面顶部：自然语言输入框 +「AI 检索」按钮
- 页面下半部：结果列表（卡名、id、类型/属性/种族/星级/攻守、效果摘要、**命中理由**）
- AI 检索后：先展示「我理解为：<人类可读的条件描述>」，命中 N 张，再列结果；条件以可读形式呈现，允许用户照着改手动条件再查

## 交付物

### 一、效果索引构建（按规则文档实现）

1. `core/effect_splitter.py` — 效果切分器（规则文档 §3 全部 6 种情况，zh/ja 双切 + 段数校验）
2. `core/effect_classifier.py` — 五维 + seg_category 分类器（规则文档 §4、§5）
3. `core/build_effects_db.py` — 主流程，产出 `build/card_effects.db` + `build/coverage_report.md`
4. `tests/test_golden.py` — 金标集回归（规则文档 §8 清单，要求 100% 通过）

### 二、DSL 与执行引擎（两种模式共用）

5. `core/dsl.py` — DSL 定义、校验、SQL 编译：
   - 条件类型：卡片标量（type/attribute/race 位掩码；level/atk/def/lscale 数值与区间；setname 系列；ot 卡池；name/desc 关键词）、category 32 位（has_any/has_all/has_none）、card_effects EXISTS 子查询（targets/activation/location/timing/negate_type/seg_category，可组合）
   - `validate()`：枚举值对齐白名单（属性 7 种、种族表、类型标签表、598 系列名、32 位 category、五维取值表），非法值拒绝并给出可读错误
   - `compile()`：DSL → 单条参数化 SQL（禁止字符串拼接防注入）
   - `describe()`：DSL → 人类可读中文描述（用于回显）
6. `core/engine.py` — 执行器：跑 SQL、展开 alias 链（P1）、按 YGOPro2 风格排序（主类型 → 副类型 → 等级降 → 攻击降 → id）、为每条结果标注**命中理由**（哪段效果命中）

### 三、手动模式 UI

7. `web/index.html` + `core/app.py`（Flask 路由 `/api/search` `/api/nl_search` `/api/vocab`）：
   - 控件清单：卡名/描述关键词；主类型（怪兽/魔法/陷阱）+ 细分标签（通常/效果/仪式/融合/同调/超量/灵摆/连接/调整 + 魔陷子类）；属性 7 种；种族下拉；等级/阶级/LINK 区间；灵摆刻度区间；攻击力/守备力区间（含 `?` 选项）；系列下拉（598 条，从 strings.conf 加载）；category 32 个复选框；五维条件（取对象/发动类型/发动位置/时点/无效类型，均可选"不限"）；卡池；默认勾选「排除衍生物」
   - 所有控件值来自 `/api/vocab`（后端从数据生成，不写死）

### 四、AI 模式

8. `core/llm_client.py` + LLM 系统提示词：
   - 配置走 `config.json`：`{"llm": {"base_url": "...", "api_key": "...", "model": "..."}}`，OpenAI 兼容的 `/chat/completions` 接口（用户自填，DeepSeek/通义/OpenAI 均可），用 JSON 模式/结构化输出
   - **系统提示词设计**：注入 DSL schema + 词汇表（从 `/api/vocab` 同源生成，保证与校验层一致）+ 少量 few-shot 示例（≥6 条，覆盖：纯字段查询、五维查询、系列查询、混合查询、效果类别查询、无法映射时的降级）
   - 输出必须是合法 DSL JSON → 过 `validate()` → 失败时把错误信息回喂 LLM 重试一次 → 再失败则明确告知用户"这句话我没能理解，换个说法试试"
   - 检索后调 `describe()` 回显条件

## 验收标准

**P0（必须全部通过）**

1. 索引构建：规则文档 §8 全部指标（切分异常 <2%、五维规则可判 ≥85%、金标集 100%）
2. 手动模式：上述控件全部可用，组合条件 AND 生效
3. AI 模式（用 mock LLM 响应测试，不依赖真实 API）：自然语言 → 合法 DSL → 正确结果
4. 基准查询对照（手动和 AI 两种模式结果应一致）：
   - 「不取对象破坏卡片的仪式怪兽」≈ 22 张（±3，差异写进报告）
   - 「会错过时点才能发动的卡」= `timing='when_optional'` 的结果集
   - 「暗属性龙族 4 星调整」纯字段查询
5. DSL 注入安全：所有 SQL 参数化；非法 DSL 值被拒绝且错误可读

**P1（尽量完成）**

6. alias 链展开（检索卡名时同名再版一并命中）
7. 禁限卡筛选（读 `cdb/zh-CN/lflist.conf` 最新 OCG 表）
8. 多轮对话：AI 模式保留当前条件栈，支持"放宽到 5 星""去掉调整"这类增量修改（LLM 输出条件操作指令 add/remove/replace/reset，而非全量重建）

**P2（不做或留接口）**：LLM rerank、向量语义搜索

## 工作方式要求

- **用真实数据验证，不凭感觉写规则**。每条分类规则写完立刻在全库 24,309 个效果段上跑覆盖率
- 规格没覆盖的文本模式：**不擅自扩规则**，记入覆盖率报告"未覆盖模式"章节，标 `confidence='undecided'`
- 先看 20 张真实卡原文（灵摆/多效果/无编号/魔法/永续陷阱各几张）再写切分器
- LLM 系统提示词是交付物的一部分，单独成文件（`core/llm_system_prompt.py` 或 `.md`），里面不许出现硬编码的卡片名单
- 完成后输出：交付物清单 + 覆盖率报告要点 + P0 验收逐项结果 + 遗留问题清单

=====
