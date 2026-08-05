# 观察性研究 V1.0：DFS 覆盖矩阵

> 范围仅为“研究者发起的临床研究 → 观察性研究 → 诊断试验是/否”。此矩阵不把当前页比较或局部性假设误写成全路径现场验证。
> 干预性研究和产品注册路线均为 `deferred_to_v2`；数据共享/结果发布方式=其他为 `out_of_scope_or_blocked`。

## 已确认的根路线

- `investigator-observational / diagnostic=yes`：`sample_verified`，研究设计结构与诊断否不同。
- `investigator-observational / diagnostic=no`：`sample_verified`，研究设计结构与诊断是不同。

## 条件驱动与验证状态

| 页面 | 控制路径 | 当前页影响 | 后续影响 | 证据等级 | 现场/假设结论 |
| --- | --- | --- | --- | --- | --- |
| `basic-information` | `basic-information.sync-platform` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 私有/ChiCTR 公开的中英文配对、填报状态和数据公开页字段组已完成代表性现场比较；附件类别在本次对照中一致。 |
| `data-sharing-and-public-disclosure` | `basic-information.sync-platform` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 私有/ChiCTR 公开的中英文配对、填报状态和数据公开页字段组已完成代表性现场比较；附件类别在本次对照中一致。 |
| `data-sharing-and-public-disclosure` | `data-sharing-and-public-disclosure.data-share-statement` | `local_fields_changed` | `not_checked` | `sample_verified` | 共享显示共享计划、获取条件、网址等字段；公开策略组合待抽查。 |
| `implementation-information` | `basic-information.sync-platform` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 私有/ChiCTR 公开的中英文配对、填报状态和数据公开页字段组已完成代表性现场比较；附件类别在本次对照中一致。 |
| `implementation-information` | `implementation-information.multicenter-flag` | `local_fields_changed` | `not_checked` | `sample_verified` | 是/否当前页结构差异已记录；深层国家、角色和参与机构按局部性假设展开。 |
| `recruitment-information` | `recruitment-information.recruitment-flag` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 高风险候选：需要当前页比较及代表性后续抽查。 |
| `recruitment-information` | `recruitment-information.recruitment-status` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 高风险候选：需要当前页比较及代表性后续抽查。 |
| `research-category` | `research-category.diagnostic-trial` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 诊断是显示诊断相关字段；否显示普通分组/暴露相关字段。两者不可合并。 |
| `research-category` | `research-category.route-leaf` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 观察性根路线与诊断是/否均有独立未保存草稿的当前页和研究设计页比较。 |
| `research-content` | `basic-information.sync-platform` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 私有/ChiCTR 公开的中英文配对、填报状态和数据公开页字段组已完成代表性现场比较；附件类别在本次对照中一致。 |
| `research-design` | `basic-information.sync-platform` | `page_or_structure_changed` | `confirmed_cross_page` | `sample_verified` | 私有/ChiCTR 公开的中英文配对、填报状态和数据公开页字段组已完成代表性现场比较；附件类别在本次对照中一致。 |
| `basic-information` | `basic-information.material-donation-flag` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `implementation-information` | `implementation-information.branch-country` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `implementation-information` | `implementation-information.has-participating-branches` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `implementation-information` | `implementation-information.leading-country` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `implementation-information` | `implementation-information.organization-role` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `other-information` | `other-information.platform-name` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `recruitment-information` | `basic-information.funding-international-cooperation` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `recruitment-information` | `recruitment-information.overseas-recruitment-flag` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-category` | `research-category.invasive-bci` | `none` | `not_checked` | `assumption_expanded` | V1.0 局部性假设：暂视为仅本页普通条件；未进行后续穷举。 |
| `research-category` | `research-category.tcm-guided` | `none` | `not_checked` | `assumption_expanded` | V1.0 局部性假设：暂视为仅本页普通条件；未进行后续穷举。 |
| `research-content` | `research-content.extra-inspection-measures` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-content` | `research-content.research-phase` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.allocation-concealment-method` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.biologic-drug` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.biological-sample-collection` | `local_fields_changed` | `not_checked` | `sample_verified` | 是显示生物样本重复模板；新增/删除和下游尚待抽查。 |
| `research-design` | `research-design.blinding-type` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.exempt-consent` | `local_fields_changed` | `not_checked` | `sample_verified` | 否显示首例知情同意日期；是隐藏。 |
| `research-design` | `research-design.indicator-type-level-2` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.intervention-type` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.marketed-product-type` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.maximum-age-secondary-unit` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.minimum-age-secondary-unit` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.random-group` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.random-group-method` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.study-design` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.study-design-subtype` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.transplant` | `not_recorded` | `not_checked` | `inferred_from_initial_tree` | 初版 canonical 候选；按 V1.0 局部性策略排队，尚未独立抽样。 |
| `research-design` | `research-design.vulnerable-group` | `local_fields_changed` | `not_checked` | `sample_verified` | 是显示弱势群体类型；普通类型按局部性假设展开。 |

## V1.0 局部性假设

除研究分类、诊断试验、公开策略、页面跳过、已发现不一致及招募/数据/附件风险条件外，普通动态选项默认只改变所在页；最终不汇合树在各分支下复制后续模板，并标记 `assumption_expanded`。任何现场下游差异都会触发该分支以下局部 DFS。

## 当前未完成队列

- 观察性公开策略的后续代表路线；
- 招募页出现条件、招募状态及境外招募；
- 多中心深层国家/角色/参与单位与重复项模板；
- 每条诊断路线不依赖直接页签的前向末页重放；
- 附件字段标签、必填性和格式的页面级读取（不上传）。
