# research-ethics

`research-ethics` is a Codex skill for turning a Chinese medical research plan into a reviewable, platform-ordered registration filling draft.

It creates a **copyable preparation document**, not a submission. It never logs in, saves, submits, completes a registration, or uploads attachments on behalf of a user.

## V1.0 scope

Supported:

- Researcher-initiated clinical research → observational research.
- Diagnostic trial: yes or no.
- Two publication strategies: two platforms not public, or public on the Chinese Clinical Trial Registry (ChiCTR).
- Chinese fields plus the applicable ChiCTR English companion fields.
- Repeated groups, attachment preparation requirements, real-time dictionary guidance, and explicit evidence levels.

Deferred to V2:

- Interventional research.
- Product-registration routes: drugs, devices, IVDs, and special medical-purpose foods.

The current release is `READY_WITH_EXCLUSIONS`: it is based on documented sampling and locality assumptions, not a claim that every possible platform combination has been replayed live.

## Install in Codex

Copy the skill folder into your Codex skills directory:

```text
<CODEX_HOME>/skills/research-ethics/
```

The installable directory is [`skill/research-ethics`](skill/research-ethics). Do not install the repository root as a skill.

## Use

In a Codex conversation, ask for example:

> Use `$research-ethics` to read my research plan and create a platform-ordered copy/paste draft for an observational study.

The skill will:

1. identify the V1 route and stop for V2 routes;
2. extract only supported candidate values from the plan;
3. ask for missing real-world facts;
4. generate Markdown and Word filling drafts in platform order.

Word output semantics:

- blue: a proposed value or selection;
- red: `待用户确认` (requires confirmation);
- black: labels, choices, sources, instructions, attachment rules, and platform evidence.

Each unresolved item is classified as one of: real-world fact, platform rule, mapping gap, or real-time platform dictionary.

## Safety and privacy

- Check all generated values against the current platform page before submission.
- Do not treat the output as ethics approval, legal advice, or final platform guidance.
- Do not commit research plans, screenshots, source HTML, account data, credentials, or real filling drafts to this repository.
- Attachments are listed as preparation requirements only; the skill never uploads them.

## Validation

From `skill/research-ethics`, run:

```powershell
py -3.13 scripts\validate_atomic_schema.py references\registration-tree.yaml
py -3.13 scripts\validate_dfs_ledger.py
py -3.13 scripts\validate_v1_artifacts.py
py -3.13 scripts\check_v1_skill_readiness.py
py -3.13 tests\test_chictr_public_e2e.py
```

See `references/v1-acceptance.md` and `references/chictr-public-route-acceptance.md` for the exact V1 evidence boundary.

## License

Released under the [MIT License](LICENSE).
