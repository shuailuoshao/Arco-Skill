# Calibration Workflow

Calibration 是唯一允许改变 Character Bible 的路径。

新增、补全或混搭服装先按 [服装准备流程](outfit-preparation.md) 收集素材、确认设计并试穿；最终参考包及发布预览获用户认可后，才进入本文件的正式 staging 与事务规则。独立背面身份标定也采用专属预览和确认。

普通只读 Prompt 不扫描 staging。新 Calibration、正式写入、publication 与 recovery 才检查目标级 `calibration-lock.yaml`。manifest 保存 base revision 与所有发布/保护文件的 base hash；publication preflight 若发现漂移，进入 `STALE_STAGING` 且不得写入。Windows 多文件发布使用 rollback snapshot 与逐文件 after-hash，任一中途失败进入 `RECOVERY_REQUIRED`。

## 1. 显式进入

只有用户明确要求标定、入库、新增 Variant/State、更新证据或永久修改 Identity 时进入。普通 Prompt 中出现的新图片不会自动触发写入。

## 2. 分析与预览

1. 登记候选资产的来源、权威、source group、角度和 roles。
2. 按 [intrinsic-filtering.md](intrinsic-filtering.md) 建立 Visual Observation。
3. 与当前 YAML 事实和已有证据比较。
4. 给每个 claim 提议 `TODO_CALIBRATION`、`UNCERTAIN`、`VISUAL_CONSENSUS` 或 `CANON`。
5. 在对话中展示新增、修改、冲突、未确认、状态变化和拟复制资产。
6. Identity Core 变化必须醒目标记 `Identity Change`。

确认前不得创建 staging、复制正式资产或修改任何当前数据。

## 3. 用户确认

用户必须对完整预览作出明确确认。一次充分确认即可，不机械重复询问。若用户只批准部分变更，重新生成缩小后的预览再确认。

## 4. Staging

确认后创建 `calibration/staging/<calibration-id>/`，其中包含：

- 候选 YAML 与 Markdown；
- 待发布图片；
- history 草案；
- `publish-manifest.yaml`；
- 目标文件备份目录。

ID 使用 `cal-<UTC-YYYYMMDDTHHMMSSZ>-<6hex>`。

每个被修改实体 revision 增加一次，并将 `last_calibration_id` 设为本次 ID。同一实体一次修改多个字段仍只增加一次 revision。

## 5. 验证与发布

先验证 staging 的完整候选状态，再使用 `scripts/publish_calibration.py` 执行恢复型发布：

```text
prepared → publishing → history_pending → complete
                                  ↘ rollback_required
```

发布不是跨文件 ACID 事务。脚本通过同卷单文件 `os.replace`、逐文件哈希、备份、manifest 状态、History 和完成标记实现可恢复性。

只有 `calibration/history/<id>.yaml` 与 `<id>.complete` 同时存在，才算完成。

## 6. 恢复

任何运行前检查 staging manifest。存在非 `complete` 状态时，停止使用 Character Bible：

```powershell
python scripts/publish_calibration.py status calibration/staging/<calibration-id>
python scripts/publish_calibration.py recover calibration/staging/<calibration-id> --strategy resume
python scripts/publish_calibration.py recover calibration/staging/<calibration-id> --strategy rollback
```

恢复前根据 manifest 与当前哈希判断已发布、未发布或发生未知漂移。未知漂移进入 `rollback_required`，不猜测覆盖。

成功恢复或回滚后再次运行完整 validator。失败 staging 保留，直到恢复完成或用户明确要求清理。

## 7. History

History append-only，保存事实演变原因，不作为当前事实源。每个 target 包含 `entity_ref`、`revision_before`、`revision_after`、changed fields、before、after 和状态变化。

状态升级和降级都必须留痕。纠正旧 History 时新增一条记录，不改旧文件。
