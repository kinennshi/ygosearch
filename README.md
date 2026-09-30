# YGOSearch · 游戏王卡片检索程序

游戏王卡片自然语义检索器：手动筛选与 AI 自然语言检索共用一套 DSL 执行引擎。
数据源：ygopro 简中卡池（15,019 张卡），离线构建效果段五维索引（33,586 段）。

## 目录结构

```
ygosearch/
├── core/                        # 全部源代码
│   ├── effect_splitter.py       # zh/ja 双语效果段切分器
│   ├── effect_classifier.py     # 五维分类器（targets/activation/location/timing/negate_type）
│   ├── build_effects_db.py      # 离线构建效果段索引库
│   ├── dsl.py                   # 检索 DSL：校验 / SQL 编译（全参数化）/ 可读描述
│   ├── engine.py                # 执行引擎：检索、alias 展开、排序、命中理由
│   ├── constants.py             # 位常量、卡池标签
│   ├── strings_conf.py          # strings.conf / lflist.conf 解析
│   ├── vocab.py                 # 统一词汇表（前端控件与 LLM 提示词同一来源）
│   ├── llm_system_prompt.py     # LLM 系统提示词（运行时注入词汇表，零硬编码卡名）
│   ├── llm_client.py            # LLM 客户端（OpenAI 兼容，校验失败回喂重试一次）
│   └── app.py                   # Flask 入口与路由
├── web/
│   └── index.html               # 前端（单文件，无构建步骤）
├── build/
│   ├── card_effects.db          # 效果段索引库（可直接使用，无需重新构建）
│   └── coverage_report.md       # 覆盖率与审计报告
├── cdb/zh-CN/
│   ├── cards.cdb                # 原始卡池数据库（运行必需，引擎 ATTACH 此库）
│   ├── strings.conf             # 系列名等字符串表（运行必需）
│   └── lflist.conf              # 禁限卡表（运行必需）
├── tests/
│   ├── test_golden.py           # 金标回归 61 项
│   └── test_app_p0.py           # P0 验收 22 项（Web 层 + mock LLM + 注入安全）
├── docs/
│   └── card_effects规则.md       # 切分与分类规则（v1.0，实现依据）
├── config.presets.json          # DeepSeek、GLM、Kimi、本地服务预设
├── config.example.json          # 手工配置模板（可选）
└── 交付报告.md                   # 交付物清单、验收结果、遗留问题
```

## 环境要求

- Python 3.10 及以上（开发时使用 3.13）
- 依赖仅一个第三方包：`flask`

## 部署步骤

```bash
cd ygosearch

# 1. 创建虚拟环境（可选但推荐）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 2. 安装依赖
pip install flask

# 3. 启动
cd core
python app.py
# 输出：YGOSearch 已启动：http://127.0.0.1:5000
```

浏览器打开 http://127.0.0.1:5000 即可使用。

> 引擎按相对路径定位数据库（`../build/card_effects.db`、`../cdb/zh-CN/`），
> 请保持目录结构原样移动，从 `core/` 目录启动。

## AI 模式配置

打开网页的「AI 搜索」→「API 配置」，选择 DeepSeek、GLM 或 Kimi 后填写 API Key 并保存。服务地址和模型由 `config.presets.json` 预设。本地 AI 服务默认地址为 `http://127.0.0.1:8000/v1`；启动支持 OpenAI 兼容接口的本地服务后，点击「扫描模型」可读取 `/models` 返回的名称，也可手填名称和修改本地地址。配置保存在仅当前用户可读写的 `config.json`，页面不会回显密钥。

也可以手工复制 `config.example.json` 为 `config.json`，填入 OpenAI 兼容接口：

```json
{
  "llm": {
    "base_url": "https://api.example.com/v1",
    "api_key": "sk-xxxx",
    "model": "your-model-name"
  }
}
```

- LLM 只负责把自然语言翻译成 DSL JSON，检索本身全部走确定性参数化 SQL
- 输出校验失败会自动把错误回喂重试一次；两次失败返回
  「这句话我没能理解，换个说法试试」
- 未配置 config.json 时：手动筛选不受影响，AI 模式返回配置指引
- AI 自然语言解析会参考 [玩家黑话检索词典](docs/玩家黑话检索词典.md)，区分「康」「擦」「耐性」等含义；当前 DSL 无法精确表达的概念不应被当作精确筛选条件

## 卡池与排除规则

卡池不选时使用数据库中所有现存的卡池值，包括 OCG、TCG、OCG/TCG、简中/OCG、简中/OCG/TCG；只显示数据库里确实存在的值。检索固定排除衍生物和陷阱怪兽，包括同名异画展开结果；原始数据库记录保留。

检索结果按卡名合并同名异画，优先显示符合条件的原版；若只有异画版符合条件，则显示其中一张。合并发生在分页前，因此命中数量与页数也按去重后的卡片计算。默认不额外展开同名再版。怪兽能力中的「特殊召唤」对应卡片类型位（例如积木龙），与效果类型中的「特殊召唤」含义不同。

检索结果每页显示 100 张，顶部和底部都可翻页或输入页码跳转，直到浏览完全部命中卡片。手动筛选桌面布局的筛选栏与结果栏宽度为 2:3。

效果类型中的「仪式相关」是派生条件：仅当怪兽、灵摆、魔法或陷阱的真实效果段文本包含「仪式召唤」「仪式魔法」「仪式怪兽」「仪式卡」之一时命中。卡片仅有仪式种类不会自动命中；规则文本与描述文本不参与。该条件可与官方效果类型组合，按任一命中处理。

## 重新构建索引（可选）

打包内已含构建好的 `build/card_effects.db`，通常无需重建。如卡池更新：

```bash
cd core
python build_effects_db.py
# 产出 build/card_effects.db 与 build/coverage_report.md（含索引自动创建）
```

## 运行测试

```bash
cd ygosearch
python tests/test_golden.py     # 金标回归：61 项
python tests/test_app_p0.py     # P0 验收：22 项（需要 build 与 cdb 数据在位）
```

## 验收基准

| 查询 | 期望 |
|---|---|
| 「不取对象破坏卡片的仪式怪兽」 | 精确 22 张 |
| timing=when_optional | 非空，命中段时点全部正确 |
| 手动 DSL vs AI(mock LLM) | 3 个基准查询结果逐 id 一致 |
| SQL 注入（DROP/注释/通配符） | 全部拦截，表完好 |

## 已知事项

1. **五维组合查询性能**：`build/card_effects.db` 已补建 activation/timing 索引
   （`build_effects_db.py` 同步更新）。若自行重建索引库，请使用最新
   `build_effects_db.py`，否则多维组合查询会因缺索引变慢。
2. 多轮对话条件栈（P1）未实现；AI 模式为单轮独立解析，新条件并入一句话表达即可。
3. LLM 客户端以 mock 全链路验证，接入真实 API 后建议先用
   「不取对象破坏卡片的仪式怪兽」等基准句回归。
4. timing 维度判定率 88.3%（规则未覆盖的句式按纪律返回 NULL，详见
   coverage_report.md）；切分异常 6.53% 均为 zh 翻译丢失编号标记的数据源损耗。
