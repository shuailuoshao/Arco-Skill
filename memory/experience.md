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
