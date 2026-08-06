# Changelog

## 1.0.3 - 2026-08-06

- Replaces the single structural-only gate with an enforced two-stage confirmation flow.
- Stage one confirms the route, all structural choices, and every value extracted from the research plan.
- Stage two lists all remaining required fields, optional fields, and repeat groups in platform order and requires an explicit user resolution before drafting.
- Keeps red `待用户确认` only for values the user explicitly defers; distinguishes account prefill, real-time dictionaries, and prepared attachments.

## 1.0.2 - 2026-08-06

- Adds a hard structural-confirmation gate before any V1 Markdown or Word filling draft can be rendered.
- Requires explicit user-confirmed option IDs, rejects missing or mismatched confirmations, and adds a confirmation-sheet generator for iterative conditional choices.

## 1.0.1 - 2026-08-06

- Adds explicit `actual_submission` and `test_public` operating modes.
- Actual local submissions retain authorized real project facts; de-identification is required only for tests, public examples, reusable fixtures, or other persistent shared artifacts.
- Adds intake validation and regression tests for the operating-mode boundary.

## 1.0.0 - 2026-08-06

- First public V1 release for researcher-initiated observational research.
- Supports private and ChiCTR-public filling drafts, including applicable English companion fields.
- Adds route-scoped research-design evidence so an interventional V2 mismatch does not block the sampled observational V1 route.
- Adds attachment preparation checklists, real-time dictionary guidance, and classified pending-item prompts.
- Includes deidentified fixtures and regression tests for the ChiCTR-public route and Word color semantics.

## Known limitations

- V1 is `READY_WITH_EXCLUSIONS`; see the installable skill references for evidence levels and deferred routes.
- No submission, upload, approval, or server-side behavior is tested.
