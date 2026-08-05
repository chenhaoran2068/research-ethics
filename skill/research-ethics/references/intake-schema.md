# V1 intake 结构

intake 保存用户已确认的路线与准备填写的值。研究计划书可在本轮上下文中阅读；是否可保留真实个人信息由 `metadata.operating_mode` 决定，绝不把实际申报信息写进 skill、Git 或测试工作目录。

```yaml
metadata:
  operating_mode: actual_submission | test_public

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

- `metadata.operating_mode` 必须明确：`actual_submission` 仅可保存到用户授权的私有工作区；`test_public` 的 intake、输出和持久记录必须先脱敏。旧测试夹具未写该项时按 `test_public` 处理。
- `selections` 使用 YAML 中的选项 ID，如 `yes`、`no`、`private`；不要用中文显示名代替，除非 canonical YAML 的 ID 本身就是中文。
- 所有会触发条件显示的选择必须在 `selections` 中明确给出，不能只写进一段说明文字。
- 任何没有可靠来源的值都留空；渲染器会写为“待用户确认”。
- 使用 `repeat_groups` 表示资金来源、材料捐献、参与单位、分组、结局指标或生物样本等多项数据；不要把多项内容串成一个文本框。
- ChiCTR 公开路线中的英文内容可由合格翻译草拟，但必须交由用户核对术语和研究事实。
