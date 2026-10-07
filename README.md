# Arco 稳定运行工作区

- [技能入口](SKILL.md)
- [图片审阅工作室](apps/artwork-review/README.md)
- [本机部署说明](deployment/junction.md)

正式事实在 character、variants，参考资产在 assets，运行策略在 runtime。scripts 保留生产与维护工具，历史测试夹具在 scripts/fixtures。
自动归档只管理作品，不登记角色证据或修改角色事实。

## 仓库内容

本仓库保存代码、文档及正式参考资产，包括角色与服装事实、参考图片、运行策略、生产与维护脚本，以及图片审阅工具。

作品图片与原始参考（`作品/`）、历史归档（`archive/`）、运行输出（`output/`）和临时标定资料（`calibration/staging/`、`calibration/preparations/`、`calibration/transactions/`）只保存在本机，已排除 Git。Python 虚拟环境及审阅工具的本机数据库和缓存也不会上传。

完整的本机作品索引位于 `作品/索引.md`，历史归档索引位于 `archive/索引.md`。克隆仓库不会包含这些资料；读取已有作品或运行依赖历史归档的检查时，需要另行准备对应本机数据。
