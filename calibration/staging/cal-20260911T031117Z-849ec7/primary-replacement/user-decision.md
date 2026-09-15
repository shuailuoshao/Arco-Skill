# User adjudication — verbatim excerpts and execution scope

以下为本轮用户原始裁决的逐字节文本摘录（不是全文转录）；完整对话仍为原始来源。

> 确认选择：
>
> Candidate A
>
> 作为新的 Identity Primary。

> Candidate A
> crop_box: [680,0,760,640]
> dimensions: 760×640

> 原因：
>
> - outfit leakage = LOW
> - face / eyes / bangs / hair-origin 保留完整
> - 作为 portrait / WHO anchor 最合适
> - 粉色发梢与完整发长不足可由 Secondary 补充

> 当前 old primary candidate
> 和其他 crop candidates
> 仅保留在 staging comparison / history 中，
> 不要作为最终 Primary 发布。

> preferred_for:
>
> - portrait
>
> 不要宣称它独立覆盖：
>
> - upper_body
> - full_body
> - back_view

> 保持：
>
> identity-p01
> = full-body Secondary
>
> identity-p03
> = supplemental / alternate Secondary
>
> 不要修改其 source family / provenance 结论。

> Candidate A
> expression leakage: HIGH
>
> 但本次接受该剩余风险，
> 因为当前没有更干净且更低服装污染的官方候选。

> - expression should not be inherited by default
> - future prompt compiler and expression resolver should override expression via text / semantic selection
> - this asset is accepted primarily for WHO anchoring, not default expression transfer

> 不要因此修改 Expression Library。

> 不要为了延续旧报告机械保持 READY。

> GLOBAL_REFERENCE_READINESS:
> 不得高于 PARTIAL

> 不要执行 publication。
> 等待我下一次明确：
> 确认发布 Identity Calibration

## Approved implementation boundary

用户选择“仅替换并如实报告（推荐）”，随后明确要求执行已批准计划：

> 针对 `cal-20260911T031117Z-849ec7`，仅替换 staging Primary、更新关联草案并重新验证。按本轮裁决，不修复既有 Runtime 缺陷；任何影响发布条件的问题必须报告为阻断项。

> 对发现的既有 Runtime 缺陷或其他范围外问题不静默修复；保留失败证据，结论为 `NOT_READY_FOR_IDENTITY_PUBLICATION`。

本记录仅保存在 staging，不构成 publication 或正式 History。
