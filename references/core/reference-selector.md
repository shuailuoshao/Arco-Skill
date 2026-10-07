# Reference Selector

Reference Selector 只读取正式发布区和用户本轮明确提供的图片，不扫描目录，也不读取 staging。

## 来源与权威

- `managed_arco`：正式 Asset Index 中已获 generation permission 的阿尔可资产。
- `request_scoped_arco`：用户本轮明确指定的临时阿尔可图片；必须 `persistent: false`、`calibrating: false`，且没有 `asset_id`。
- `external_how`：只提供姿势、构图、镜头、光线、场景或风格，不提供阿尔可 WHO。

选择顺序为 Identity、Variant、State/Detail、External HOW。Managed Asset 必须为 `VERIFIED`，文件与 SHA-256 有效，且 `can_be_generation_reference: true`、supported role 相符。字段缺失等价于 false。

普通低层 Selector 同一 role 内先选择 Primary，再按当前 exposure profile 检查 coverage；不足时只加入能补齐缺口的最少 Secondary。Supplemental 只有在仍有缺口且确实贡献新字段时才加入，不机械上传。Asset `inheritance` 必须转换为 Reference Contract 的 `inherit` / `do_not_inherit`，不得丢失。

普通低层 Selector 请求 managed `outfit_reference` 时必须提供 `selected_variant_id`。Selector 只允许选择 `asset.variant_id == selected_variant_id` 的资产，并要求该 Variant 恰好存在一个有 generation permission 的 outfit Primary；缺失 Variant ID、没有候选、没有 Primary 或存在多个 Primary 均 fail closed。Identity 与 Outfit 的 coverage 分开补齐：Identity 资产不能填补 Variant 字段，Variant 资产也不能填补 Identity 字段。

正常生产按 [分离参考与分析确认](reference-analysis.md) 选择获准的着装 Faceless Composite 和表情 PNG。Body Base 仅保留为本地证据，禁止进入参考预览或生图输入；选择器与适配器均检查其资产 ID、路径和图片哈希，排除旧合同及同图副本。完整立绘不作为默认回退；debug、staging 和随机目录图片仍不自动选择。本地阿尔可最多 3 张、外部最多 2 张、总输入最多 5 张，同一文件只输入一次。

稳定 Variant 选择错误码为 `VARIANT_SELECTION_REQUIRED`、`VARIANT_REFERENCE_NOT_FOUND`、`VARIANT_PRIMARY_MISSING` 与 `VARIANT_PRIMARY_CONFLICT`。生成后的 managed Outfit Contract 必须保留 `variant_id`；Request Readiness 若发现 Outfit Contract 属于其他 Variant，返回 `CONFLICT`。

## Reference Contract

```yaml
reference_id: request-arco-01
source_scope: request_scoped_arco
path: D:/references/arco.png
role: identity_reference
authority: user_request
selection_reason: explicitly_provided_for_this_request
confidence: high
persistent: false
calibrating: false
inherit: [identity, hair, eyes, face]
do_not_inherit: [scene, lighting]
coverage:
  profiles: [portrait]
  visible_fields: [identity, hair, eyes, face]
  view_angles: [front]
  occluded_fields: []
```

`inherit` 与 `do_not_inherit` 不得重叠。External HOW 的 inherit 不得包含 identity、hair、eyes、face、body proportions、outfit 或 Variant。

分离生产入口依据已分析的表情视角选择相容图层，可使用获准 Secondary 服装图提供该视角；每层许可、SHA-256、Variant 和 coverage 分别复核。透明表情层只有与无五官图联合覆盖脸部时才能 READY。
