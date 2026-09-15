# Body proportion tooling repair and staging revalidation

- Goal: repair Identity Fact → Prompt Compiler propagation and revalidate `cal-20260914T100205Z-77878a` without publication.
- Decision: keep candidate data frozen; use explicit `UNCERTAIN` working-fact opt-in, never compile `TODO_CALIBRATION`.
- Changes: added pure body-fact mapping/semantic guard, isolated historical Identity/Casual fixtures, and compiler/runtime documentation.
- Verification: Runtime 29/29; fixture blockers 3/3 (combined 21/21); full regression 88/88; body staging, formal, history, skill and 51 managed hashes PASS/UNCHANGED.
- Stop: publication, Live Smoke Test, image generation and remote upload were not executed.
