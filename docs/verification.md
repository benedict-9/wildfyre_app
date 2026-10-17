# Verification and acceptance

This record separates checks performed locally, teammate-reported deployment
and user acceptance. It does not treat fixture results or issue closure as
proof of a new live-provider or LinuxONE execution.

## Current verification

| Check | Result and scope |
| --- | --- |
| Backend | 347 offline tests passed on Windows AMD64 / Python 3.12.14. |
| Notebook | Nine tests plus nine subtests passed in the isolated matching scientific environment. |
| Browser states | 37 Edge 155 checks passed with controlled provider/model fixtures. |
| Request deadlines | Both virtual-time checks passed: a valid snapshot can finish at 60s; a stalled request becomes retryable after 75s. |
| Shell/startup | Bash syntax, repository paths with spaces, alternate CWD, dependency/cache reuse, private key input and failure paths passed. |
| Source-model/data reproduction | 65,072 detections and 13,016 corrected windows reproduced; original model evaluation and reload match. |
| Portable-model parity | Exact probabilities/classes on all 4,467 held-out rows and 149 missing/threshold cases. |
| Live-feature parity | All 13,016 historical cell-windows match within 5.684e-14. |
| Actual local application | One process served /app/, API and the real model; sample self-check, map, timing and refresh passed. |
| Mocked-live integration | Current UTC fixture inputs changed the actual model score when FRP changed; this was not a NASA live call. |
| Private release | Authenticated GitHub CLI downloads of forest/parity assets matched the reviewed local bytes. |

Machine-readable evidence:

- [Corrected source model/data](evidence/fire-persistence-verification.json)
- [Portable model and features](evidence/fire-persistence-portable-verification.json)
- [Actual local sample and mocked-live application](evidence/live-persistence-local-verification.json)

Local application checks used the production bundled-model cache, not a
scientific serving stack. The sample score was 0.71. In the mocked-live run,
changing FRP from 10 to 1000 changed the score from 0.67 to 0.5933333333333334.
Earlier one-cell /risk processing was about 5–7ms and startup about 2.3s on
the local machine; these are not s390x performance estimates. Worker memory
was not measured reliably.

The actual sample browser check covered eight widths from 320–1440px without
horizontal overflow, source/attribution popups, paused refresh and operator
scenarios: 95−40−20=35 minutes/HIGH for the sample candidate, zero and negative
windows preserved. Screenshots inspected locally were sample or labelled fixture
states, not remote LinuxONE evidence.

Independent review found two defects that were reproduced with failing tests
and fixed: truncated CSV rows cannot become apparently valid imputed scores,
and snapshots crossing six-hour/midnight UTC boundaries use completion time.
Three later regressions cover offline bundled-model preparation after anonymous
private-release downloads were found to return 404. No additional GitHub
credential is required for normal application startup.

## Earlier provider and LinuxONE evidence

Earlier local live GBIF checks confirmed the Animalia restriction; the final
documentation pass does not claim a new NASA/GBIF live run.

The teammate reported Ubuntu 24.04.5 LTS / s390x, Python 3.12.x, loopback backend
and frontend through SSH, and 267 tests passing for an earlier deployment.
The exact deployed commit and raw logs/screenshots were not supplied. That
handoff does not independently verify later Animalia or model-serving changes.

## Acceptance

WF08 was accepted by the user with LinuxONE inference waived. WF09 implementation
merged in [PR #27](https://github.com/benedict-9/wildfyre/pull/27). On 2026-10-18
SGT the user instructed closing WF09 and proceeding to final documentation
without an additional server check. WF09 is therefore accepted and closed;
actual LinuxONE inference is still unverified.

WF10's final scope is human-facing documentation and repository cleanup.
The user explicitly excluded a three-minute demo script while retaining app
startup. Agent instructions, obsolete implementation/design plans and duplicated
historical readiness narratives are removed from the current tree; Git history
retains them. Operational/model limitations remain in the final docs.


## Final-documentation rehearsal

The documented sample entry point was repeated after cleanup using the existing
pinned backend environment. Model self-check passed, the sample score was 0.71,
and the scenario returned 35 minutes/HIGH. The existing browser checks again
covered eight widths 320–1440 px, popups, source labels, refresh and zero/negative
windows without overflow or browser errors. Startup was 1.93 s in this rehearsal.
The machine-readable application evidence includes this dated check.

All six remaining Markdown files (five project documents plus fixture
attribution) have valid relative links and balanced code fences. Shell syntax
and scoped diff checks passed. Application startup and runtime/export/test code
are retained; no demo walkthrough script was added.
