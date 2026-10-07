---
source_entity: variants.school-uniform
source_revision: 1
---

# 校服 / School Uniform

新增标定 `cal-20261001T031544Z-8df760`。结构化事实以 `variant.yaml` 为准。

- 用户提供并确认的本地原始立绘 `アルコ_a_l_6602.png`，官方出处未核实。
- Primary `school-uniform-primary` 仅提供服装参考，图中的无五官脸、发型和动作不随服装继承。
- 十项可见工作事实为单图观察；相关 field_ref 从 outfit.silhouette 到 outfit.footwear，evidence_ids 为 `school-uniform-primary`。
- 未知背面对应 field_ref `outfit.back_structure`；不推定不可见的衬衫、后片和鞋侧细节。
- 格纹方向与裙摆展开程度受姿势和透视影响；袜口金色横条、胸前蝴蝶结和金色纽扣是重点保留细节。
- 常服继续作为独立 Variant；新增服装不修改角色身份或表情库。
