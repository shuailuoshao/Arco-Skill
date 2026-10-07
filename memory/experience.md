# Engineering experience

## Variant selector must carry explicit resource context

- Symptom: outfit selection sorted all eligible Primary assets and could choose another Variant.
- Root cause: the selector accepted a role but no `selected_variant_id`.
- Fix: require and propagate the Variant ID, filter before ranking, enforce exactly one Primary, and reject cross-Variant contracts.
- Prevention: every future multi-Variant test fixture must include a higher-sorting wrong Variant and assert it never reaches adapter arguments.

## Candidate validation needs an explicit transaction context

- Symptom: validating an assembled future revision with pending History reports revision-chain errors.
- Root cause: the formal validator accepts pending History only when an isolated publication-in-progress marker binds its digest and candidate hashes.
- Fix: build a temporary published-root fixture plus transaction marker; never relax formal History lineage checks.
- Prevention: staging validators should distinguish candidate validation from ordinary formal read-only validation and model the transaction context explicitly.

## Codex image prompts need a byte-safe transport and pre-generation receipt chain

- Symptom: Chinese characters in an immutable task prompt were changed before image generation when raw text passed through the Windows shell/default code page.
- Fix: keep task JSON UTF-8 decoded in Python; carry exact prompt bytes in an ASCII-only Base64 envelope; verify the sent string's UTF-8 SHA-256 immediately before generation; bind task, prompt, ordered references, destination, and output hash in a write-once receipt; require that receipt during acceptance.
- Prevention: never pass raw prompt text through shell stdout or arguments. Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`. Keep invalidated outputs and audit history, but exclude them from compliant formal counts and verdict inputs.
- Safe-resume detail: schema-1 tasks marked invalidated or superseded remain audit-readable without checking their obsolete runner hash; their task digest and preserved evidence still require validation. Cover the first-pending index after migration in tests.

## Image generation retries must follow failure semantics

- Symptom: moderation refusals and unknown provider errors were recorded under a broad tool-failure kind and could create repeated immutable attempts.
- Root cause: retry decisions trusted caller-supplied failure kinds instead of a closed policy keyed by normalized provider error codes.
- Fix: derive failure kind, retry allowance, attempt cap, and backoff from an explicit table; reject conflicting caller classifications; treat safety refusals and unknown errors as terminal; keep network, timeout, and missing-path retries bounded.
- Prevention: pin historical misclassified attempts by exact digest in an append-only capture. Validate every new attempt against the current policy and preserve all prior audit records unchanged.
