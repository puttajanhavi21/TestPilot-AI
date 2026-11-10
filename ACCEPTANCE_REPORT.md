# TestPilot AI - Final Acceptance Audit

Date: 2026-11-10

## Summary

The implemented local workflow passed an independent end-to-end audit against the
controlled loopback API fixture. No critical or high-priority defect was found.
One minor malformed placeholder markup issue was corrected in
`templates/index.html`.

The live Adaption provider was not called during this audit because it requires
an account request and may incur usage. Provider integration was verified with
the installed SDK contract, mocked structured responses, missing-key behavior,
and provider-error behavior.

## Acceptance matrix

| Feature | Test performed | Actual result | Evidence | Status | Required correction |
|---|---|---|---|---|---|
| API input and validation | Submitted valid and invalid JSON through Flask routes; exercised manual creation and OpenAPI upload | Valid input was accepted; malformed, empty, and invalid input returned 400 responses; manual creation opened the review page | `tests/test_routes.py`; browser smoke check; `app.py` input routes | PASS | None |
| Structured AI-generated cases | Supplied a validated mocked AI `Suite` through `/api/generate`; inspected persisted response | Suite and test case were validated by Pydantic and persisted with structured fields including method, endpoint, request, expected status, rules, priority and eligibility | `models/schemas.py`; `services/ai_service.py`; independent acceptance harness | PASS | Live provider generation not tested |
| AI invalid-output handling | Ran mocked invalid JSON followed by valid repair JSON; ran permanently invalid output and provider exception cases | One repair attempt occurred; malformed output was rejected; provider details were not leaked | `tests/test_ai_service.py` | PASS | None |
| Review and edit flow | Created a manual suite, opened it in the browser, and saved a reviewed revision through the API | Unreviewed suite was gated from execution/export; reviewed revision became executable and immutable history was retained | `app.py`; `static/script.js`; `tests/test_routes.py`; browser smoke check | PASS | None |
| Complete workflow | Generated, reviewed, executed, analysed, and exported a suite against a real local fixture | Workflow completed successfully; one real request passed and analysis/export routes returned successfully | Independent acceptance harness; `examples/mock_api.py` | PASS | None |
| Actual HTTP pass/fail | Executed `/health` expecting 200, then executed the same real endpoint expecting 418 | Passing result recorded actual status 200; mismatch recorded `failed` with actual status 200 | `services/engine.py`; independent acceptance harness; `tests/test_execution.py` | PASS | None |
| Generated Pytest execution | Downloaded the generated `.py` file and ran it with a separate `python -m pytest` process against the fixture | Exported test executed a real HTTP request and reported `1 passed` | `services/test_generator.py`; independent acceptance harness | PASS | None |
| Controlled execution isolation | Inspected worker path and ran worker-backed suite execution | Application uses a fixed worker entry point, validated stdin data, no AI-generated code execution, process deadline, bounded request/response behavior and platform resource limits where available | `services/test_executor.py`; `services/worker.py`; `tests/test_execution.py` | PASS | Windows is not a complete hostile-code sandbox; documented limitation remains |
| SQLite persistence | Reopened the Flask application with the same database after the run and reloaded the run/dashboard | Persisted run remained available and dashboard totals reflected stored records after restart | `models/database.py`; independent acceptance harness | PASS | None |
| JSON report | Downloaded `/api/runs/<id>/export.json` and parsed it | HTTP 200; report contained the persisted run ID and evidence | `app.py`; `tests/test_routes.py`; independent acceptance harness | PASS | None |
| PDF report | Downloaded `/api/runs/<id>/export.pdf` and checked PDF signature/EOF | HTTP 200; valid PDF bytes began with `%PDF-` and contained `%%EOF` | `services/report_service.py`; independent acceptance harness | PASS | None |
| Missing API key | Removed `ADAPTION_API_KEY` for an isolated request to `/generate` | HTTP 502 with a clear configuration message; no credential value exposed | `services/ai_service.py`; `tests/test_ai_service.py`; independent acceptance harness | PASS | None |
| Adaption failure | Injected an AI provider failure into `/generate` | HTTP 502 with a safe provider error response; no provider exception body leaked | `app.py`; `tests/test_ai_service.py`; independent acceptance harness | PASS | None |
| SSRF and URL validation | Probed loopback, localhost, private, link-local, metadata, IPv6 loopback and cross-origin targets | Blocked by validation; exact configured loopback fixture exception worked only when explicitly configured | `services/network.py`; `tests/test_security.py`; independent acceptance harness | PASS | None |
| Redirect handling | Exercised redirect behavior in the controlled execution tests | Redirects were not followed and returned evidence preserved the redirect outcome | `services/network.py`; `tests/test_execution.py` | PASS | None |
| Timeouts and response limits | Exercised slow, oversized and non-JSON fixture responses | Timeout/size/error behavior was bounded and recorded without false success | `tests/test_execution.py`; `services/network.py` | PASS | None |
| Secret redaction | Scanned persisted run/report output and logs; exercised runtime secret tests | Runtime secret markers, cookies and sensitive response values were not retained in evidence; logs contained no matching secret values | `services/redaction.py`; `services/worker.py`; `tests/test_execution.py`; log scan | PASS | None |
| Dashboard statistics | Compared dashboard totals with the independent database's stored project, suite, case, run, report and result records | Totals matched actual records; no seeded statistics were used | `models/database.py`; independent acceptance harness | PASS | None |
| Browser navigation and controls | Opened the app in a browser, navigated Overview/New API test/Test suites/Run history/Reports/Settings, and clicked Create manually | Pages rendered and navigation worked; review gating was visible; settings showed real configuration state | Browser smoke check; `templates/index.html`; `static/script.js` | PASS | None |
| Placeholder functionality and misleading messages | Inspected route/UI wiring and empty states; checked that empty dashboard states explicitly state there is no sample data | No unimplemented primary action was found; empty states and execution messages were consistent with actual behavior | `templates/index.html`; `static/script.js`; `README.md` | PASS | None |
| Git-tracked secret audit | Queried Git metadata and scanned project files/logs | The parent Git worktree reports zero tracked project files and the checkout has no committed history, so a tracked-file guarantee cannot be independently established; `.gitignore` excludes `.env`, databases, logs and temp output | `.gitignore`; Git query (`TRACKED_COUNT=0`); repository scan | NOT TESTED | Initialize/use the intended Git repository and run a secret scan before publishing |
| Live Adaption request | No live provider request was made | Not verified in this audit; account-dependent and potentially billable | `test_adaption.py`; `README.md` | NOT TESTED | Run `test_adaption.py` explicitly with an authorized local account if live-provider evidence is required |

## Verification commands

- `.\venv\Scripts\python.exe -m pytest -q --basetemp=tmp\pytest-run`: **92 passed**
- `.\venv\Scripts\python.exe -m pip check`: passed
- `node --check static\script.js`: passed
- Independent acceptance harness: passed real workflow, restart persistence, reports, exported pytest, actual pass/fail, SSRF, missing-key and provider-error checks

The default Windows pytest temporary directory is ACL-restricted in this
environment; the repository-local `--basetemp` option was used to avoid that
environmental failure.

## Final disposition

**PASS with two explicit limitations:** live Adaption traffic and verification
against committed Git-tracked files were not performed. The application is
accepted for the documented local single-user workflow, not as an
internet-facing multi-tenant deployment.
