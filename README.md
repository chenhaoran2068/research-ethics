# research-ethics

## Governed Study Bridge

V1.1.1 can be used after a user explicitly selects the compatible
`governed-research-workflow` ethics-preparation route for a China Mainland,
researcher-initiated observational Study. It adds no automatic discovery,
submission, upload, approval, or project-state transition.

For this optional context, use the `governed_study` instructions and
`MODULE_MANIFEST.yaml` in the installable Skill. The current editable protocol
remains in `03_protocol/`; derived preparation drafts are separate from actual
ethics and registration evidence in `02_registry/compliance/`. The user must
still confirm current official, institutional, and project-specific conditions
before an actual submission task.

### Maintenance And Expansion

Before every `actual_submission`, the accountable human must recheck current
official, institutional, jurisdictional, and project requirements. Review the
Skill's public-source references at least every 90 days and immediately after
an official/platform or institutional-template change, a discovered error or
near miss, a System authority/path change, or a request for a new study type.

A V1 field correction that does not change this bridge's scope or authority may
be handled as a Skill patch. A new jurisdiction, prospective or
researcher-assigned study, trial/intervention route, product/device/IVD route,
credential workflow, submission service, or System authority change requires a
separate Charter and, where relevant, coordinated System and Skill review.

`research-ethics` 是一个 Codex skill，用于准备中国医学研究伦理材料、代码化研究计划书骨架，以及按国家医学研究登记备案信息系统页面顺序编排的可复制填写稿。

它生成的是准备材料，不会登录、保存、提交、完成登记或上传附件，也不替代伦理审查、法律意见或平台最终校验。

## V1.0 支持范围

当前仅支持中国大陆：

- 研究者发起的临床研究 → 观察性研究；
- 诊断试验：是／否；
- 两个平台均不公开，或在中国临床试验注册中心（ChiCTR）公开；
- 相应的中文字段、ChiCTR 英文配对字段、重复组、附件准备要求与实时字典提示。

当前状态为 `READY_WITH_EXCLUSIONS`：规则基于现场抽样、已记录的平台结构与明确的局部性假设，不声称已穷尽所有平台组合。

以下路线延后至 V2，不能套用观察性研究规则：干预性研究、药品、医疗器械、体外诊断试剂和特殊医学用途配方食品。

## 计划书：覆盖矩阵、语义规则与同源双语事实

计划书不是由一份手工 Word 模板或逐句改写生成，而是由三层共同决定：

```text
覆盖矩阵（章节、顺序、适用条件）
  + 语义组合规则（段落／小节／清单／表格）
  + 私有事实模型（已确认或待确认的 statement_id）
  = 中文、英文或双语研究计划书
```

- 叙述段按完整论点组织，通常包含 2–5 个相互关联的陈述；不得按句号、换行或来源摘录机械断段。
- 定义、标准、流程和附件按适合的清单或步骤表达；只有三条及以上同构记录适合横向比较时使用表格。
- “研究结果发布、数据共享与再利用边界”固定拆为三个独立小节，避免混杂。
- 中文与英文从同一 `statement_id` 读取，不允许临时翻译、补写或用不同事实填充两种语言。
- 缺失事实显示为待用户确认，生成器不根据常识、标题或文献猜测补全。

示例：

```powershell
py -3.13 scripts\render_protocol_template.py --diagnostic-trial no --output protocol-skeleton.md
py -3.13 scripts\render_semantic_protocol.py --facts private-facts.yaml --language bilingual --output protocol-bilingual.md
py -3.13 scripts\render_protocol_docx.py --markdown protocol-bilingual.md --output protocol-bilingual.docx
```

默认输出带有 `presentation_status: content_structure_draft`：内容、章节、段落逻辑和待确认项已生成，但尚未声称完成机构品牌、视觉美编、分页控制或最终提交版式。视觉质量必须经过独立的 Word／PDF 审查与机构模板适配。

## 使用方式

在 Codex 对话中，例如：

> 使用 `$research-ethics` 读取我的研究计划书，先确认观察性研究的登记结构，再生成按平台顺序可复制填写的草稿。

工作流：

1. 判断是否属于 V1 支持路线；V2 路线会明确停止，不臆造规则。
2. 从研究计划书提取候选值和来源。
3. 先分批确认会改变页面结构的选择，以及从计划书提取出的拟填写内容。
4. 再按平台页面顺序确认剩余必填项、可选项、重复组、实时字典和附件准备情况。
5. 两个确认阶段完成后，生成 Markdown 和 Word 填写稿。

Word 颜色语义：蓝色为建议填写／选择的实际值；红色为待用户确认；黑色为字段名、选项、来源、操作说明、附件规则和平台证据。

## 安全与隐私

- `actual_submission` 允许在用户授权的本地私有工作区使用真实事实，但不得复制到 Git、测试、示例、日志或已安装 skill。
- `test_public` 的持久化输入和输出必须脱敏。
- 不公开研究计划书、截图、网页源码、账号资料、凭据、真实填写稿或原始附件。
- 公开版由 `scripts/prepare_public_release.py` 的白名单生成；不得整体复制构建目录。

## 安装

将仓库内的 `skill/research-ethics` 复制到：

```text
<CODEX_HOME>/skills/research-ethics/
```

不要将仓库根目录作为 skill 安装。

## 验证

在 `skill/research-ethics` 目录运行：

```powershell
py -3.13 -m unittest discover -s tests -p 'test_*.py' -q
py -3.13 scripts\validate_protocol_template_assets.py
py -3.13 scripts\validate_semantic_protocol_assets.py
```

更多 V1 边界、平台规则与版本路线见 `references/`。

## License

MIT License.
