# V1 intake 结构

intake 保存用户已确认的路线与准备填写的值。研究计划书可在本轮上下文中阅读；是否可保留真实个人信息由 `metadata.operating_mode` 决定，绝不把实际申报信息写进 skill、Git 或测试工作目录。

```yaml
metadata:
  operating_mode: actual_submission | test_public
  structural_confirmation:
    status: pending | explicitly_confirmed
    method: user_explicit              # only after the user has explicitly confirmed
    confirmed_selections:              # exact, canonical option IDs confirmed by the user
      canonical.path: option-id | [option-id, ...]
  proposal_confirmation:
    status: pending | explicitly_confirmed
    method: user_explicit
    confirmed_values:                  # exact values extracted from the research plan and confirmed by the user
      canonical.path-or-repeat-key: "confirmed final value"
  completion_confirmation:
    status: pending | explicitly_confirmed
    method: user_explicit
    resolutions:                       # every remaining active field/group, in page order
      canonical.path-or-repeat-key: provided | not_applicable | account_prefill | platform_realtime | attachment_prepared | user_deferred

selections:       # 会决定可见字段的选项 ID；不填显示名
  canonical.path: option-id | [option-id, ...]
values:           # 文本、日期、数字、附件准备状态，或不会决定结构的选择
  canonical.path:
    value: "可复制内容"
    source: "研究计划书第 X 节 / 用户确认 / 账户预填"
    note: "可选；只记录必要限制"
repeat_groups:    # 以可重复组 canonical path 为键；每个实例按子字段 ID 填写
  canonical.group.path:
    - selections:
        child-option-field-id: option-id
      values:
        child-text-field-id:
          value: "第 1 项内容"
          source: "用户确认"
```

规则：

- `metadata.operating_mode` 必须明确：`actual_submission` 仅可保存到用户授权的私有工作区；`test_public` 的 intake、输出和持久记录必须先脱敏。
- **两阶段确认门槛**：先用 `scripts/render_confirmation_batches.py --stage framework` 生成第一阶段确认单。用户先确认路线、所有结构性选择，以及计划书已提取的拟填写值；计划书只能提供候选，不能替代确认。结构性选择写入 `structural_confirmation`，计划书值写入 `proposal_confirmation`，二者均须为 `explicitly_confirmed`／`user_explicit`。
- 第一阶段稳定后，运行 `scripts/render_confirmation_batches.py --stage gaps`。它会按平台页面顺序列出当前路线下全部未提供的必填项、可选项和可重复组。用户必须逐项提供内容或明确处理状态，再写入 `completion_confirmation.resolutions`。只有两阶段均通过，才可生成 Markdown／Word 填写稿。
- `selections` 使用 YAML 中的选项 ID，如 `yes`、`no`、`private`；不要用中文显示名代替，除非 canonical YAML 的 ID 本身就是中文。
- 所有当前可见、会触发条件显示或必填性变化的选择必须在 `selections` 和 `confirmed_selections` 中明确给出，不能只写进一段说明文字。用户确认一个选择后如有新结构性控件出现，必须再次生成确认单并继续确认。
- `user_deferred` 是用户明确暂缓的唯一状态；它会在最终输出中保留红色“待用户确认”。`not_applicable` 仅适用于非必填项或不新增的可重复组；平台实时字典、账户自动带入和附件准备分别使用对应的明确状态。
- 使用 `repeat_groups` 表示资金来源、材料捐献、参与单位、分组、结局指标或生物样本等多项数据；不要把多项内容串成一个文本框。
- ChiCTR 公开路线中的英文内容可由合格翻译草拟，但必须交由用户核对术语和研究事实。
