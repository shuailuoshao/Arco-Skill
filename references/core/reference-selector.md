# Reference Selector

Reference Selector 只读取正式发布区和用户本轮明确提供的图片，不扫描目录，也不读取 staging。

## 来源与权威

- `managed_arco`：正式 Asset Index 中已获 generation permission 的阿尔可资产。
- `request_scoped_arco`：用户本轮明确指定的临时阿尔可图片；必须 `persistent: false`、`calibrating: false`，且没有 `asset_id`。
- `external_how`：只提供姿势、构图、镜头、光线、场景或风格，不提供阿尔可 WHO。

选择顺序为 Identity、Variant、State/Detail、External HOW。Managed Asset 必须为 `VERIFIED`，文件与 SHA-256 有效，且 `can_be_generation_reference: true`、supported role 相符。字段缺失等价于 false。

同一 role 内先选择 Primary，再按当前 exposure profile 检查 coverage；不足时只加入能补齐缺口的最少 Secondary。Supplemental 只有在仍有缺口且确实贡献新字段时才加入，不机械上传。Asset `inheritance` 必须转换为 Reference Contract 的 `inherit` / `do_not_inherit`，不得丢失。

请求 managed `outfit_reference` 时必须提供 `selected_variant_id`。Selector 只允许选择 `asset.variant_id == selected_variant_id` 的资产，并要求该 Variant 恰好存在一个有 generation permission 的 outfit Primary；缺失 Variant ID、没有候选、没有 Primary 或存在多个 Primary 均 fail closed。Identity 与 Outfit 的 coverage 分开补齐：Identity 资产不能填补 Variant 字段，Variant 资产也不能填补 Identity 字段。

Expression Layer、Body Base、Faceless Composite、debug、staging 与随机工作目录图片不得自动选择。默认本地阿尔可最多 3 张、外部最多 2 张、总输入最多 4 张。

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
