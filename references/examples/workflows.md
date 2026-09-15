# 示例工作流

以下内容全部是流程示例，不是阿尔可的真实设定，不得写入 Character Bible。

## Director：资料充足

用户提出已标定 Variant、半身、雨夜便利店和安静表情。Skill 读取 portrait + upper_body 所需 Identity/Variant facts，确认 request readiness，外部参考只继承构图与雨夜光线，然后输出简短解析和一条完整 Prompt。不额外加入剧情人物。

## Designer：方向未定

用户只说“想做一张夏日阿尔可”。Skill 先给海边黄昏、便利店午后、夏祭夜景三个不同方向，每个只说明场景、动作、构图、光色和氛围。用户选择后再检查目标 Variant 与 exposure profile，最后编译 Prompt。

## Reviewer：Variant 缺失

用户要求一套库中不存在的服装，但没有提供阿尔可对应服装图。Skill 不自行设计该服装，提示改用现有 Variant，或提供真实阿尔可参考并进入 Calibration。

## External HOW

用户提供阿尔可标准图和另一角色的构图参考。Skill 从阿尔可资料读取 WHO，只从外部图继承姿势、人物位置、镜头、光线和氛围；外部人物的发色、瞳色、身材、服装与专属配饰不进入 Prompt。

## Request-scoped Identity Override

用户明确要求“本次改成蓝眼睛”。Skill 可为本次 Prompt 使用 override，并在解析中说明瞳色偏离标准 Identity、Character Bible 未修改。下一请求恢复标准 Identity。若用户要求以后都改变，则进入 Identity Change Calibration。

## Calibration

用户提供新的官方素材并明确要求标定。Skill 先记录可见 Observation，再排除夕阳、透视和遮挡影响，比较已有证据，展示字段变化、状态提议、冲突和资产登记预览。用户确认后才建立 staging、验证、发布，并生成 History 与完成标记。
