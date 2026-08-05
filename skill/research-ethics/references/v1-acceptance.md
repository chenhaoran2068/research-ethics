# research-ethics V1.0 验收记录

## 验收结论

**通过：`READY_WITH_EXCLUSIONS`。**

V1.0 可用于把研究者发起的观察性研究计划书整理为按平台顺序的填写稿；它不是对平台全部组合的全量现场验证，也不替代平台、伦理委员会或人工核对。

## 已接受的能力

| 验收项 | 结果 | 依据 |
| --- | --- | --- |
| V1 路线边界 | 通过 | 仅支持观察性研究、诊断试验是／否；干预性与产品注册均为 `deferred_to_v2`。 |
| 路线级研究设计 | 通过 | 观察性 `study-design` 已从干预性 V2 的全局不一致中隔离；队列第二级、其他设计文本和随机分组独立性均保留为 `sample_verified`。 |
| private 路线生成 | 通过 | 既有脱敏 intake、Markdown／DOCX 回归和规则校验。 |
| ChiCTR 公开路线生成 | 通过 | [chictr-public-route-acceptance.md](chictr-public-route-acceptance.md) 的脱敏端到端验收与英文配对回归。 |
| 重复组 | 通过但非无限展开 | 以模板和 intake 实例数生成，不伪造无限条目。 |
| 填写稿提示 | 通过 | 蓝色建议值、红色待确认值、附件准备清单和实时字典说明由共享生成器输出。 |
| 规则／账本一致性 | 通过 | 原子 YAML、账本、覆盖矩阵、树工具和 V1 artifact 校验均通过。 |
| 隐私边界 | 通过发布前门槛 | 将以公开白名单再次扫描；原始方案与真实衍生物不进入源码仓库。 |

## 已知限制（验收时保留）

- `sample_verified` 与 `assumption_expanded` 不代表所有选项组合均已从根到叶现场重放。
- ChiCTR 公开路线在后续页主要增加英文配对字段的结论，仍按 V1 局部性假设处理；出现任何非英文结构差异时必须局部复核。
- 未验证保存、提交、审核、注册号、同步、服务端附件校验和团队成员保存行为。
- 传统医学平台注册平台与结果发布方式“其他”保持 `out_of_scope_or_blocked`。
- 当前纵向树是可再生成的证据预览；它清楚标记证据等级和假设，不得称为全量 DFS 证明。
- DOCX 已完成结构与颜色测试；本机未发现 LibreOffice，无法完成 PNG 视觉渲染检查。

## 必跑验收命令

```powershell
py -3.13 scripts\validate_atomic_schema.py references\registration-tree.yaml
py -3.13 scripts\validate_dfs_ledger.py
py -3.13 scripts\validate_v1_artifacts.py
py -3.13 scripts\check_v1_skill_readiness.py
py -3.13 scripts\test_unmerged_tree_tools.py
py -3.13 tests\test_chictr_public_e2e.py
<bundled-python> tests\test_copyable_docx_styles.py
```

发布前还必须执行公开白名单扫描；安装后还必须执行一次隔离的 Codex 触发和生成测试。
