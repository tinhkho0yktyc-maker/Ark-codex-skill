# 明日方舟共享桌宠

多个角色共用一套透明 Windows 桌面程序。模板保留原仓库预置的予愿安洁莉娜；其他角色放在各自的 `pets/<角色名>/` 目录中，右键“桌宠库”切换。

## 原项目与致谢

**原项目地址：[AstrariaX/Ark-codex-skill](https://github.com/AstrariaX/Ark-codex-skill)**

感谢 AstrariaX 提供的原 Skill、导出脚本和桌宠模板。本程序来自 [tinhkho0yktyc-maker/Ark-codex-skill 改进版](https://github.com/tinhkho0yktyc-maker/Ark-codex-skill)，并非原作者的官方发布。上游没有明确的 LICENSE，本改进版未自行为其代码添加 MIT 等许可证。《明日方舟》素材属于原权利人，PRTS 内容适用其相关许可，保留个人学习、自用、请勿商业发布的说明。

## 首次运行

通过 Skill 的 `scripts/setup_env.py <项目目录>` 安装项目内 `.venv`，然后双击“启动桌宠.bat”。依赖为 PySide6-Essentials，不需要向全局 Python 安装。

新项目的自动启动、自动漫游默认关闭。右键菜单“设置...”或托盘菜单可以按需开启；请勿直接使用其他电脑的 `settings.json`。

## 操作

- 单击互动；双击切换迷你模式。
- 解锁后拖动播放移动动画，松开恢复之前的状态。
- 坐下、放松、睡觉是手动状态；再次互动可以解除。
- 无操作约 40–60 秒自动坐下，90 秒自动睡觉；新任务可唤醒自动休息，手动状态优先。
- 右键“自动漫游”控制随机短距离行走；行走与待机有约 140ms 转场，停下保留朝向，自动漫游待机把原片长停帧限为 120ms。互动、拖动、菜单和休息时暂停；非漫游及手动动作保持原时序。
- 设置可调整漫游速度、动作倍速、播放上限、字幕长度、字号与宽度。

漫游使用亚像素坐标与物理像素/DPI 补偿，角色和字幕整体插值移动。移动刷新参考屏幕刷新率，动作播放仍保留原 20/30/60fps 上限；缓存透明图层避免每次位移重绘字体。它不保证严格垂直同步，也不能消除源动画本身的步行动作起伏。
- 字幕宽度不随角色缩放变化；悬停查看完整任务、模型、进度和 Token。
- 每个角色分别保存位置、大小与倍速；显示器或 DPI 变化后限制在工作区。

## 素材导入

制作工具位于所安装 Skill 或源码仓库的 `scripts/`，不是桌宠运行目录。工具依赖放在项目内 `.tools-venv`；需要 FFmpeg/ffprobe。

```text
python <Skill目录>/scripts/setup_env.py <项目目录> --tools
<项目目录>/.tools-venv/Scripts/python.exe <Skill目录>/scripts/process_webm.py --src <WebM目录> --name <角色名> --out <项目目录>/pets/<角色名>
<项目目录>/.tools-venv/Scripts/python.exe <Skill目录>/scripts/validate_deskpet.py <项目目录>/pets/<角色名> --allow-inactive --out <项目目录>/work/预览.png
```

路径有空格时用双引号包围。一个输入目录只放一个角色/皮肤的 Relax、Interact、Move、Sit、Sleep 动画。Default 经常是坏文件，不映射为第六种模式。转换拒绝覆盖旧角色；重做时先输出到新目录，保留旧素材并检查预览后再替换。

v2 素材保留源帧时间戳与透明画布偏移，仍兼容旧固定帧率素材。默认 60fps 是播放刷新上限，不能给原来 20fps 的示例补帧；动作倍速也不是帧率。遇到黑底优先使用仓库的 VP9 透明导出脚本重新导出；网页默认 AV1 文件即使标记 alpha，也可能没有真实透明数据。`--recover-black` 只是可选近似修复，可能误删深色细节，需要人工检查。

## 随 Codex 启动与恢复

开启后，当前用户登录延迟 10 秒启动监听器；检测到 Codex/ChatGPT 才显示桌宠和托盘。宿主关闭超过 8 秒后关闭桌宠与托盘，监听器等待下次启动。

- 计划任务 `ArkCodexDeskpetWatcher` 与备用注册表项 `CodexDeskpetWatcher` 指向当前项目。
- 进程按项目做单实例与身份校验。异常退出由监听器或轻量守护父进程退避恢复，最长 60 秒。
- 托盘“隐藏桌宠”和桌宠“完全退出”不会在当前宿主运行期间立即重拉；托盘“显示桌宠”可以恢复。
- 托盘“退出”结束整套程序。下次登录或手动启动监听器后才恢复。
- 移动项目目录后需要重新配置自动启动；同一用户使用一个活动自启动项目。

可用 Skill 的 `scripts/create_shortcuts.py --project <项目目录>` 创建“打开桌宠”和“启动托盘”快捷方式。

## 状态、日志与隐私

监控器只读 `CODEX_HOME/sessions`，未设置 CODEX_HOME 时读取当前用户的 `~/.codex/sessions`，不会修改 Codex 数据。本轮 Token 和会话累计 Token 分开；长工具调用不因为日志短暂安静就显示结束。多会话优先最近更新的运行中会话，不保证与前台聊天页完全一致。

看不到小人时先用托盘“显示桌宠”，再双击“调试运行.bat”。日志为 `pet_error.log`、`pet_runtime.log`、`watcher.log`、`autostart.log` 等，超过约 1 MiB 轮转。

设置、日志和进程身份文件属于本机状态。分享项目时不要上传 `.venv`、`.tools-venv`、`settings.json`、日志、PID、flags、`*.process.json` 或 Codex 会话。新增角色素材的分享还需确认对应授权。
