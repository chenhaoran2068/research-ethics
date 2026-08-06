---
name: research-ethics
description: 为中国医学研究伦理申报和国家医学研究登记准备“研究计划书 → 用户确认 → 按平台顺序可复制填写稿”。支持受控的实际申报模式与脱敏测试／公开模式。当用户需要根据研究计划书、伦理材料或资助材料生成逐项填写清单、ChiCTR 中英文配对内容、确认缺口或相关附件清单时使用。当前 V1 只支持研究者发起的观察性研究；干预性和产品注册路线必须明确转为 V2，不得臆造。
---

# research-ethics

生成可复核的“平台填写准备稿”，不替用户登录、保存、提交或上传。

## 当前支持范围

- 支持：研究者发起的临床研究 → 观察性研究 → 诊断试验“是”或“否”。
- 支持两个公开策略：`private`（两个平台均不公开）与 `public-on-chictr`（中国临床试验注册中心公开）。后者必须给出适用的中英文配对字段。
- 延后：干预性研究，以及药品、器械、IVD、特殊医学用途配方食品等产品注册路线，均为 `deferred_to_v2`。
- 阻止：传统医学平台注册平台（暂未开通）与结果发布方式“其他”的未核验细节，标为 `out_of_scope_or_blocked`；不要猜填。

## 运行模式：先确定，再读取材料

- `actual_submission`：用户明确说明正在为真实研究准备伦理申报或登记备案时使用。可在用户授权的本地私有工作区读取并保留为填写稿所必需的真实题目、单位、人员、联系方式、编号和附件状态；**不要自动脱敏**，也不要把这些内容写入 Git、skill 安装目录、测试夹具、公开示例、持久日志或调试记录。
- `test_public`：用于规则测试、公开示例、GitHub、教学演示、共享排错或可复用夹具时使用。首次保存任何输入、输出、截图描述或测试记录前，必须脱敏；可使用 `scripts/deidentify_protocol_docx.py` 创建脱敏副本。
- 模式不明时，先问用户“实际申报还是测试／公开？”；不要因看到真实信息而擅自转为脱敏模式，也不要把真实材料当作测试数据保留。

先读取 [references/v1-scope.md](references/v1-scope.md)、[references/v1-skill-readiness.md](references/v1-skill-readiness.md) 和 [references/registration-tree.yaml](references/registration-tree.yaml)。只在准入状态是 `READY` 或 `READY_WITH_EXCLUSIONS` 时生成 V1 填写稿。

## 工作流

1. 确认运行模式。从用户提供的研究计划书、伦理材料和资助材料中提取**候选**值，并在对话中注明依据位置；不要把候选值写成用户已决定的事实。`actual_submission` 可在用户授权的私有工作区使用真实材料；`test_public` 才先创建脱敏副本。
2. **先过结构性确认门槛，禁止跳过。** 用候选 `selections` 运行 `scripts/render_structural_confirmation.py`，向用户一次展示当前可见的所有结构性选择：平台字段、候选值、可选项与会改变的字段／页面。必须明确询问用户确认或修改，不能因研究计划书看似已有答案就自行选定。
3. 收到用户明确确认后，按 [references/intake-schema.md](references/intake-schema.md) 建立 intake：把确认过的值同时写入 `selections` 和 `metadata.structural_confirmation.confirmed_selections`，并写入 `status: explicitly_confirmed`、`method: user_explicit`。若选择后新出现结构性控件，重新生成确认单并再次询问，直至确认单无未确认项。实际申报 intake 只能放在用户授权的私有工作区，不能放入 skill、Git 或测试目录。
4. 只有 `scripts/validate_v1_intake.py` 通过后，才运行 `scripts/render_copyable_checklist.py` 生成按平台页面顺序的 Markdown 填写稿；校验器和渲染器都会拒绝未完成结构性确认的 intake。非结构性的文本、日期、数值、实时字典和附件状态仍可显示为红色“待用户确认”。
5. 把每个红色“待用户确认”明确分为：真实事实待确认、平台规则待核验、计划书可提取但映射待补全、平台实时字典待选择。把“账户自动带入”“实时字典中选择”“需上传附件”分别标明，不伪造内容。
6. 使用工作区依赖中的 Python 运行 `scripts/render_copyable_docx.py`，由同一 Markdown 生成 Word 填写稿。所有 Word 填写稿必须使用同一视觉语义：建议填写／选择的实际值为蓝色；`待用户确认` 为红色；字段名、可选项、来源、操作和规则证据均为黑色。`actual_submission` 的 Word 只能输出到用户指定的私有目录；生成后按 documents 工作流渲染并检查页面；若渲染环境缺少 LibreOffice，则执行 DOCX 结构检查并明确说明未完成视觉检查。
7. 运行现有 YAML、账本、产物校验器。若平台当前页面与规则不一致，以平台页面为准，记录为规则待修订，而不是默默修改研究内容。

## 生成要求

- 依页面顺序输出：研究类别、基本信息、实施信息、研究内容、研究设计、其他信息、数据共享与信息公开、相关附件；明确页面在当前路线中被跳过时的原因。
- 每个可填写项都写明：平台字段名、建议填写/选择、来源、操作、必填性、证据等级。中文和英文是独立字段，不能只提示“翻译一下”。
- Word 中蓝色只表示建议填写／选择的实际值；红色只表示尚未确认的值；字段名、可选项、来源、操作、附件规则和实时字典说明保持黑色。
- 将动态的本页区块组织在其控制项下，例如“涉及材料捐献＝是”后列出每一份材料；不要把仅影响本页的控件展开成重复的整条后续路线。
- 将 `fully_live_verified`、`sample_verified`、`assumption_expanded` 与 `inferred_from_initial_tree` 区分显示。后面三者都不能表述为全量现场核验。
- 对实时长字典只说明选择依据和需要人工从当前平台选择，不罗列或捏造全部值。
- 附件只列名称、必填性、格式、来源和准备动作，并追加“附件准备清单（不上传）”；绝不声称已经上传。

## 安全与隐私

- 不执行保存、提交、完成、上传、删除或账号资料修改。
- 不保留网页源码、截图、Cookie、密码、令牌、真实账号资料或用户未要求保存的研究材料。真实申报材料可仅在当前受控本地工作区和用户指定输出中使用，不复制到任何可公开或可复用资产。
- 输出前核对：研究题目、单位、姓名、电话和邮箱仅来自用户明确提供或账户预填提示；没有依据时保持“待用户确认”。
- 本 skill 提供填表辅助，不代替伦理审查、法律意见或平台最终校验。

## 工具

- [references/intake-schema.md](references/intake-schema.md)：输入结构、来源标记及可重复组格式。
- [references/intake-template.yaml](references/intake-template.yaml)：仅含占位符的 intake 起点。
- `scripts/render_copyable_checklist.py`：canonical YAML + intake → Markdown 填写稿。
- `scripts/render_structural_confirmation.py`：canonical YAML + 候选 selections → 必须先由用户确认的结构性确认单。
- `scripts/render_copyable_docx.py`：Markdown 填写稿 → Word 文档；使用 `compact_reference_guide` 的单色清单变体，并固定应用蓝色建议值、红色待确认值、黑色说明与可选项的语义样式。
- `scripts/validate_v1_intake.py`：检查路线、选项路径及被阻止的分支。
- `scripts/deidentify_protocol_docx.py`：研究方案 DOCX → 脱敏副本；还须清除修订痕迹和文档元数据，并进行残留模式检查。
