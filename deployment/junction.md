# Local Deployment

## Source of truth

唯一可编辑目录：

```text
D:\learn\Arco
```

Codex 安装路径只作为 junction：

```text
C:\Users\shuai\.codex\skills\arco
  → D:\learn\Arco
```

建立前必须确认目标路径不存在。若目标已存在且不是指向该目录的正确 junction，停止并报告，不覆盖。

PowerShell 7 安装示例：

```powershell
New-Item -ItemType Junction `
  -Path 'C:\Users\shuai\.codex\skills\arco' `
  -Target 'D:\learn\Arco'
```

核验：

```powershell
Get-Item -LiteralPath 'C:\Users\shuai\.codex\skills\arco' |
  Select-Object FullName, LinkType, Target
```

如 Skill 未立即出现在 Codex 中，重启 Codex。

## Git

本 Skill 不自动执行 `git init`。框架稳定、准备进行大量角色标定前，建议用户自行决定是否初始化 Git。

Git 提供文件级 diff、版本浏览和回滚；Calibration History 记录领域事实为什么变化。两者互补，不能互相替代。

## 业务隔离

本部署文档不由 `SKILL.md` 运行时路由加载。更换 junction、symlink、copy 或其他部署方式不得改变 Identity、Variant、Calibration、Prompt Compiler 或 Quality Gate。
