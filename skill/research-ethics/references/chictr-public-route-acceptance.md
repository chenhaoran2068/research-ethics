# ChiCTR 公开路线端到端验收（V1）

## 验收对象

- 路线：研究者发起的临床研究 → 观察性研究 → 诊断试验：是 → 中国临床试验注册中心公开。
- 输入：`tests/fixtures/observational-diagnostic-yes-chictr.yaml` 中的纯虚构、脱敏 intake。
- 输出：按页面顺序生成的 Markdown 填写稿，以及由同一 Markdown 转换的 DOCX。

## 已通过的链路

1. `registration-tree.yaml` 的公开策略条件会显示已记录的填报状态和英文配对字段。
2. `render_copyable_checklist.py` 按公开路线渲染英文标题、缩写、通俗标题，以及后续可见的英文配对字段；观察性 `研究设计` 不再被干预性 V2 的全局不一致状态错误阻断。
3. 输出包含附件准备清单、PDF／大小说明、实时字典使用说明和提交前人工核对框。
4. `render_copyable_docx.py` 继承同一内容：建议填写值为蓝色，`待用户确认` 为红色，其余说明为黑色。
5. `tests/test_chictr_public_e2e.py` 验证公开路线的英文配对、附件清单、实时字典说明、研究设计的路线级证据和 DOCX 结构；`tests/test_copyable_docx_styles.py` 验证颜色语义。

## 现场证据与证据等级

- `basic-information.sync-platform=public-on-chictr`：`sample_verified`。基本信息页已记录填报状态、英文题目、英文缩写、英文通俗题名与英文经费来源等公开差异。
- 后续页面的英文配对：`assumption_expanded` 或页面级 `sample_verified`。当前 V1 采用用户确认的“公开路线主要增加英文配对字段”局部性假设；发现非英文的字段、必填性、顺序、重复模板或附件差异时，必须取消受影响部分的假设并局部复核。
- 附件：仅记录可见槽位、必填性与说明；未选择文件、未上传、未保存、未提交。

## 不纳入本次验收的结论

- 不验证保存、提交、审核、注册号、同步或服务端附件校验。
- 不冻结国家／地区、机构、学科、ICD-11、适应症和资助专项等实时长字典的具体值。
- 不将本路线的字段推广到干预性研究或产品注册路线；它们仍为 `deferred_to_v2`。
- DOCX 已通过结构与颜色回归检查；由于本机没有 LibreOffice，无法生成 PNG 进行视觉渲染检查。

## 验收结论

**通过（`READY_WITH_EXCLUSIONS`）**：公开路线可以安全生成一份明确标注证据等级、人工确认项、附件准备要求和实时字典边界的填写稿；不能把它表述为全平台或全部组合的完整现场验证。
