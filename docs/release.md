# 0.3.0-rc.1 发布候选说明

这是 Windows 源码 / Codex Skill 候选版本，不是 EXE 安装包。2026-10-06 的 main 源码同步包含功能完善和静止清晰度修复；本次只更新源码，不创建 tag / GitHub Release。

获取当前源码请使用仓库 main 分支的 **Code → Download ZIP**。2026-10-05 生成的本地 0.3.0-rc.1 ZIP 不包含后续清晰度修复；如果需要 Release 附件，须重新生成候选包与校验文件，不能直接复用旧 ZIP。

## 本地验证

从仓库根目录运行，使用已生成项目的本地环境：

```powershell
.\my-deskpet\.venv\Scripts\python.exe ark-codex-skill/tests/test_deskpet.py
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/tests/test_pipeline.py
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/tests/test_extensions.py
python ark-codex-skill/scripts/build_release.py --out release-output
```

打包工具仅收集明确允许的源码、文档、依赖说明以及上游原有安洁莉娜示例。不会包含本地新增角色、设置、日志、虚拟环境或聊天记录。输出源码 ZIP、文件清单和 SHA256SUMS.txt，拒绝覆盖已有输出目录。

## 更新已有项目

更新 Skill 不会更新已经生成的桌宠程序。保留项目和设置，先停止桌宠，再更新 `assets/deskpet-app/` 中的程序文件与新增模块；不要覆盖 `settings.json`、`pets/` 或虚拟环境。已有自启动监听器仍指向原项目。第一次更新程序后需要重启；此后新增角色可以热刷新。

本版保留上游完整画布格式及本 Fork 的 v2 裁剪 / 原始时序格式；不直接支持其他 Fork 的 `groups` 清单。

## 安全导入

```powershell
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/install_deskpet.py "my-deskpet/work/prepared/角色名" --project my-deskpet --name "角色名"
```

同名替换另加 `--replace`。旧版本保留在 `pets/.backups/`，不自动删除。仅安装清单与 PNG 帧；原 WebM 留在素材工作目录。

先完成校验、暂存，然后向运行程序申请 30 秒租约；当前角色冻结后进行短暂目录替换，成功后重新载入缓存。不操作系统启动项或 Codex 数据。菜单、拖动或程序启动中会拒绝请求，请结束操作后重试。

替换失败会尝试恢复旧版本。完成回执超时但程序仍存活时，必须重新取得冻结确认才回滚；否则保留已安装新版本与旧备份，报告无法确认刷新，由用户刷新或重启。进程强制中断可能留下 `.install-lock`：先确认没有导入进程，并检查目标及备份目录，再处理空锁目录；不要在导入期间删除锁。

## 创建正式 GitHub Release 前

1. 检查 diff、测试结果和素材授权范围。
2. 用户确认版本号、发布说明、是否标记预发布及附件。
3. 用户另行授权后创建 tag 和 Release，上传与对应提交一致的源码包及校验值。普通 main 源码同步不等同于创建 Release。

首次候选仅验证 Windows 上的自动化与本机运行。PRTS 的真实 Special 导出、关机重启和多显示器组合仍需相应实机验证，不能用合成素材测试替代这些结论。
