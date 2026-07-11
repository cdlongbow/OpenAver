# OpenAver - Codex Review Guidelines

## Review guidelines

### Review stages and scope

- Plan review is doc-first. Verify source only for load-bearing assumptions that
  could invalidate architecture or task scope.
- Implementation review is diff-first. Inspect changed hunks, their direct
  callers/consumers, and relevant DoD; do not repeat full plan archaeology.
- Follow-up review is delta-only plus same-root-cause siblings.
- Review statically — do NOT run tests, lint, builds, or coverage. The implementing
  change runs targeted tests pre-commit; pre-merge and CI run the full suite plus
  lint. Trust the review packet's test summary; if edge-case coverage is in doubt,
  read the test file rather than executing it. (Empirically, running them caught 0
  unique issues across 24 reviews while consuming large amounts of context.)
- Expand to repository-wide audit only for exhaustive-coverage claims,
  shared/global infrastructure, concurrency/lifecycle, migrations, security,
  external-service contracts, or when the first contradiction is found.
- Stop expanding when each high-risk claim has direct evidence and no new
  sibling contradiction remains.

### Review focus areas

- Cross-component and cross-thread timing.
- Error/early-return state symmetry and cleanup.
- External-service behavior versus code assumptions.
- Shared/global CSS, lifecycle, serialization, and configuration contracts.
- Architecture drift across multiple entry points.

### Security

- API responses MUST NOT contain `str(e)` or Python exception details. Error messages to frontend must be fixed Chinese strings (e.g. `"操作失敗"`), with details logged server-side via `logger.error()` or `logger.exception()`.
- No SQL injection — all database queries must use parameterized statements.
- No unvalidated user input used directly in file system operations (`open()`, `Path()`, `os.path`).
- No hardcoded secrets, API keys, passwords, or tokens in source code.
- **SSRF is best-effort, NOT a default blocker.** OpenAver's default threat model is a personal, LAN-only tool; external access is delegated to the user's Tailscale / Cloudflare Zero Trust rather than built in (see `feature/epic-synology.md` "存取控制與威脅模型"). The default model does not include a hostile authenticated LAN user; residual browser-origin risks (DNS rebinding / malicious webpages) are handled as defense-in-depth, not merge blockers. Review missing SSRF hardening in **new** backend URL-fetching code as a suggestion/P3, not P0/P1, and do not block a PR solely on absent SSRF guards.
  - Existing mitigations (private-IP rejection, no-redirect-follow, image-host allowlist, LAN opt-in) should not be casually removed or weakened.
  - Still flag clear regressions in already-hardened endpoints, unauthenticated arbitrary-request proxy behavior, or code that contradicts a feature's own stated security contract.

### Path handling

- All `file:///` URI construction and parsing MUST go through `core/path_utils.py`.
- Forbidden patterns outside `path_utils.py`:
  - `path[8:]` or `path[len('file:///'):]` (manual URI strip)
  - `f"file:///{...}"` (manual URI construction)
  - `replace('/', '\\')` for path conversion
  - `startswith('file:///')` + manual handling
- If you see any of these patterns, flag as P0.

### Alpine.js

- `document.querySelector('[x-data]')` without a scoped selector (e.g. `.search-container[x-data]`) is a bug — it selects the sidebar instead of the page component.
- Alpine methods in templates must be called with `()` — `:disabled="!canGoPrev"` is wrong, `:disabled="!canGoPrev()"` is correct.

### i18n

- Strategy: **source locale only + milestone sync**. During development PRs, only `locales/zh_TW.json` is required to be updated.
- Missing keys or entire subtrees in `zh_CN.json`, `ja.json`, or `en.json` during development **are not findings**.
- **Flag these**:
  - hardcoded Chinese UI text in HTML/JS that should use `t()` / `window.t()`
  - `t()` / `window.t()` referencing keys missing from `zh_TW.json`
  - HTML-containing translations rendered without `| safe`
- **Out of scope for i18n review**:
  - `showToast()`, `alert()`, `confirm()`
  - SSE messages
  - `console.*`
  - technical terms such as NFO, API Key, Jellyfin, Proxy
  - browser/platform built-in text
  - **`design-system` and `motion-lab` page demo content** — these are internal dev-reference pages (not in main nav, not user-facing), and demo labels often contain Fluent design tokens (`fluent-decel`, `Acrylic 30px`, `--surface-1` etc.) that should not be translated. Page chrome (nav / page title) still goes through i18n; only demo body text is exempt.
- At milestone/release, all 4 locales must have identical key sets.

### General code quality

- No `console.log` left in production JavaScript (except intentional debug modes).
- Python `except` blocks should not silently swallow errors — at minimum `logger.error()`.
- Avoid introducing new inline `<script>` blocks in templates; prefer separate `.js` files.

### Out of scope (handled by automated tooling)

> **v0.11.11 (feature/96 test-deflation)**: static string/structure existence checks on
> HTML/JS/CSS/Python-literals are the lint layer's job, enforced in CI (`lint-frontend`
> job = `npm run lint` + `npm test` + `ruff check .`). DO NOT spend review attention
> re-verifying them, and DO NOT request pytest tests for them. If a guard of this class
> is missing, the finding is "add a lint rule", not a code-review blocker.

The lint layer (all wired into `npm run lint`):

- **`scripts/static_guard_lint.mjs`** — table-driven static guard engine, ~886 rules,
  9 kinds (`required-string` / `forbidden-string` / `dup-id` / `structure-count` /
  `tag-scan` / `inline-style-token` / `order` / `file-absent` / `paired-string`), with
  scoped matching (anchor-missing = fail-closed RED, brace-balanced method-body windows,
  comment stripping). Covers HTML templates (which eslint cannot parse), JS string
  fingerprints, and Python hardcoded-literal bans. This is the default home for any
  "string X must (not) appear in file Y" guard — including the former pytest guards for
  inline handlers, inline `style=display:none`, native-dialog strings, and clipboard
  optional-chaining, all migrated here.
- **`scripts/css-guard.mjs`** — 41 CSS-block rules (Fluent token families, poster-crop,
  z-index cross-file ordering, vt-anchor, selector scoping, whole-text property scans).
- **`scripts/i18n_lint.mjs`** — used-but-missing i18n keys (RED), 4-locale parity (warn),
  orphan keys (warn), forbidden words in translations (「推薦」「風味」, RED).
- **`scripts/lint-settings-ia.mjs`** — settings.html IA layering (DOM-ancestry lock).
- **ESLint** (`eslint.config.mjs`, flat config, 11 `no-restricted-syntax` groups,
  **17 `SEL_*` constants** — `SEL_SHOW_MODAL`, `SEL_TRACKED_EVENTSOURCE`, `SEL_CLIP_BAN`,
  `SEL_NO_WINDOW_OPEN_PATH`, etc.): anything expressed in the live config is out of review
  scope — consult the config, not a duplicate list here. Scope caveats that ARE still
  review territory: `no-console` covers **search pages only** (`console.error`/`warn`
  allowed); `document.createElement` ban covers **state mixins only**.
- **Stylelint** (`web/static/css/**/*.css`, excluding `tailwind.css`/`design-system.css`):
  `color-no-hex`, bare duration/blur/radius/box-shadow literal bans, selector disallow list.
- **Ruff** (Python — `core/`, `web/`, `windows/` + root scripts; `tests/` excluded):
  `F`, `E722`, `B` (incl. `B904`/`B905`/`B023`), `T201`, `S110`/`S112`.

**Still enforced by pytest** (deliberate KEEPs — flag these in review if violated):
- **`tests/unit/frontend_contracts/`** (6 files) — true cross-file / cross-language
  contracts: API route pairing, layout/lifecycle/animation contracts, and code-shape
  guards (method-body ordering, call-counts, brace-scoped semantics) that string-scan
  lint cannot faithfully express.
- **`[lint-guard: pytest-justified]`-tagged classes** in `tests/unit/test_frontend_lint.py`
  (each tag states its reason), incl. `TestPathContract` — the path_utils contract
  (manual `file:///` strip/construct bans; Python source semantics ruff cannot express).
- The remaining untagged classes in `test_frontend_lint.py` are the **E2E-block**
  (~52 classes guarding user journeys — swipe/keyboard/lightbox/actress flows). They stay
  as pytest until a future E2E branch replaces them with browser journeys; do not request
  their migration to lint, and do not add new classes to this bucket.

(Anything outside the lint layer's expressed rules — formatting, dead code not caught by
ruff `F`, logic — is still in code-review scope.)

### Test bloat policy

DO NOT request new pytest tests for anything the lint layer can express.
If a regression of this class arises, the fix is:
- a new rule row in `scripts/static_guard_lint.mjs` (the engine already exists — adding a
  rule is a table entry, not a new script), or `css-guard.mjs` / `i18n_lint.mjs` / eslint /
  stylelint for their domains — NOT a new TestNoXxx pytest class.
- New string-literal assertions in `tests/**` must carry an inline
  `# [lint-guard: pytest-justified <reason> | migrate → <tool>]` tag; pre-merge SA-pre-6
  flags untagged ones as BLOCKER.
- When migrating a guard to lint, port it at the **same scan granularity** as the original
  (whole-file / element-scoped / attribute-value / method-body window) and prefer
  fail-closed over fail-open — 7 scope-narrowing regressions of exactly this kind were
  caught by review during feature/96.
