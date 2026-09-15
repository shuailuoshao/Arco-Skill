# Intrinsic Feature Filtering

目标是把图片中的“画面现象”与角色本身的“稳定固有特征”分开。

## 分析链

```text
Image
→ Visual Observation
→ Rendering / Pose / Perspective Check
→ Intrinsic Feature Hypothesis
→ Cross-image Comparison
→ Evidence Status Proposal
```

## Observation

`observation` 只记录图片实际可见内容，例如“发尾在该图中呈暖粉偏橙”。不得在观察句中偷塞角色固有结论。

对容易受画面条件影响的字段检查：

- 光照、环境色和反射；
- 姿势、动态和服装挤压；
- 透视、镜头距离与广角变形；
- 遮挡、裁切和细节不可见；
- 表情造成的脸部形变；
- 风格化绘制或夸张。

## Intrinsic Interpretation

`intrinsic_interpretation` 是排除上述因素后的候选解释，必须保留置信等级、支持证据和冲突证据。它仍是 hypothesis，只有跨图比较和用户确认后才能成为当前事实。

## Evidence Status

- 单张图片的视觉观察通常最多支持 `UNCERTAIN`。
- `VISUAL_CONSENSUS` 默认需要至少两个独立 `source_group_id`。
- 同一原图的裁剪、放大、调色或重导出不算独立证据。
- `CANON` 需要官方对该具体事实的明确设定；“图片是官方的”本身不够。
- 新证据使已有共识不可靠时，提议降级为 `UNCERTAIN` 并记录 History。

## 存放位置

复杂 Observation 保存在 Calibration proposal 和最终 History。Character Bible 只保存确认后的稳定 intrinsic fact，避免每个简单字段机械携带渲染分析结构。
