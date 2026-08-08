# Governed Study Bridge

## Purpose

This optional context connects the Skill's China Mainland observational V1
preparation workflow to a user-named `governed-research-workflow` Study. It
prepares drafts only. It does not discover a Study, validate a real protocol,
make a governance decision, submit, upload, or contact an external service.

## Entry Conditions

Proceed only when all conditions are explicit in the current request:

1. The user names one exact Study root and selects `governed_study`.
2. The user selects `actual_submission` or `test_public`.
3. The user identifies the exact protocol and compliance inputs that may be
   read for this preparation task.
4. The user requests China Mainland ethics or medical-research-registration
   material preparation.
5. The supported route remains researcher-initiated and observational.

If any condition is absent, ask only for the missing boundary. Do not search a
workspace, infer a route, read a project, or use an installed System as proof
that the study is eligible or ready.

## Record Locations

| Material | Location | Status |
| --- | --- | --- |
| Current study protocol/design | `03_protocol/` | Authority for the editable protocol. |
| Generated skeleton, confirmation draft, and copyable preparation draft | `03_protocol/derived/ethics_preparation/<package_id>/` | Derived and non-authoritative. |
| Application, submitted snapshot, approval, waiver, consent, amendment, and evidence | `02_registry/compliance/01_ethics_and_consent/` | Source-backed compliance record. |
| Human lifecycle decision references | `00_state/lifecycle/` | Decision/reference layer only. |

A draft must never replace the current protocol or prove an ethics, consent,
registration, access, or institutional fact. Preserve the existing two-stage
user-confirmation rule before generating a copyable filling draft.

## Scope Stops

Stop and return to the System for a causal-design/target-trial review before
using this bridge for a treatment-effect claim. Refuse V1 preparation for a
prospective researcher-assigned, randomized, interventional, product, device,
IVD, non-China, credential-handling, upload, or submission request.

## Currentness And Maintenance

Before every `actual_submission` task, check current official platform,
institutional, ethics-committee, jurisdictional, and project requirements with
the accountable human. An installed template or module manifest is not a
currentness assertion.

Review public source references at least every 90 days. Review immediately
after an official/platform field change, institutional template change,
discovered error or near miss, System authority/path change, or request for a
new study type. A V1 field correction is a Skill patch if this bridge contract
does not change. Any new study type, jurisdiction, intervention route, or
bridge authority change requires a separate Charter.
