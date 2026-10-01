# Ark Codex Skill · 共享桌宠改进版

用明日方舟干员的 PRTS 基建模型制作透明 Windows 桌宠，也可以让多个角色共享一套程序。本仓库发布的是可安装的 Codex Skill、桌宠源码模板和素材工具，不是打包好的 EXE 安装程序。

## 原项目与致谢

**原项目地址：[AstrariaX/Ark-codex-skill](https://github.com/AstrariaX/Ark-codex-skill)**

本项目 Fork 自 AstrariaX 的 Ark Codex Skill，在原桌宠模板上修复问题并增加功能。感谢原作者提供的 Skill、PRTS 导出脚本与桌宠模板。此改进版并非原作者的官方发布。

改进版仓库：[tinhkho0yktyc-maker/Ark-codex-skill](https://github.com/tinhkho0yktyc-maker/Ark-codex-skill)。

## 本次改进

- 共享桌宠库：右键切换角色，分别保存位置、大小和动作倍速。
- 字幕宽度与角色缩放分离，设置立即生效；悬停查看完整任务、模型、进度及 Token 信息。
- 兼容新旧 Codex 日志，后台增量读取；区分本轮 Token 与会话累计 Token。
- 无操作约 40–60 秒自动坐下、90 秒自动睡觉；手动选择的状态优先，新任务可以唤醒自动休息。
- 自动漫游：随机短距离行走、停顿与方向变化；互动、拖动、菜单和休息期间暂停，可随时关闭。
- 角色缩放、动作切换、显示器和 DPI 变化后约束到屏幕工作区。
- 桌宠、托盘、监听器与轻量守护父进程分别做单实例和身份校验；异常退出退避恢复，正常退出不强行拉起。
- 登录后监听 Codex/ChatGPT；支持计划任务与注册表备用入口，日志轮转和原子设置保存。
- 日常运行环境与素材工具环境分离。
- 新素材转换保留原 WebM 帧及时间戳，裁去透明外边缘，并记录原画布偏移；兼容上游固定帧率素材。
- 附带 43 项隔离回归测试，使用临时生成的非游戏素材，不需要本机新增干员文件。

自动启动与自动漫游默认关闭，由用户在菜单中开启。

## 环境要求

- Windows 10/11，Python 3.10+（推荐 3.12）。
- 日常桌宠仅需 PySide6-Essentials，安装到项目内的 `.venv`。
- 制作新角色需 FFmpeg 和 ffprobe 在 PATH 中；素材工具使用独立 `.tools-venv`，包含 Pillow、Playwright。
- 自动从 PRTS 导出时需要访问 [PRTS Wiki](https://prts.wiki)；已下载 WebM 可直接导入，无需再次访问网站。

## 方法一：让 Codex 使用 Skill

对 Codex 说：

```text
安装 GitHub 仓库 tinhkho0yktyc-maker/Ark-codex-skill 里的 ark-codex-skill skill
```

已经安装同名旧 Skill 时，请先备份再更新。更新 Skill 不会自动升级你此前生成的桌宠项目；不要直接覆盖旧项目中的设置或角色素材。

安装后可以说：

```text
用 ark-codex-skill 制作干员 浊心斯卡蒂 的桌宠，皮肤用 升华
```

或者：

```text
把这些 WebM 导入已有的共享桌宠项目，角色是 凯尔希·思衡托
```

添加角色应复用已有项目，不需要再生成一套独立运行环境。

## 方法二：不用 Codex，手动生成桌宠

在本仓库网页点击 **Code → Download ZIP**，解压后打开仓库目录中的 PowerShell。以下命令从仓库根目录执行：

```powershell
python ark-codex-skill/scripts/scaffold_deskpet.py --target my-deskpet
python ark-codex-skill/scripts/setup_env.py my-deskpet
.\my-deskpet\启动桌宠.bat
```

模板保留了原仓库自带的予愿安洁莉娜示例，因此无需先下载新角色即可启动。若未安装 Python，请使用 [Python 官方下载](https://www.python.org/downloads/windows/)；遇到依赖报错可使用 Python 3.12。

脚手架拒绝覆盖非空目录。添加角色请按下一节操作；要重新生成项目，请选择新的空目录。

## 导入自己的 WebM

先安装独立素材工具：

```powershell
python ark-codex-skill/scripts/setup_env.py my-deskpet --tools
ffmpeg -version
ffprobe -version
```

已有系统 Chrome/Edge、不想额外下载 Chromium，可以在第一条命令末尾加 `--skip-browser`。

把**同一个干员、同一款皮肤**的 WebM 放在 `my-deskpet/work/webm/<角色名>/`。文件名需包含动画名：`Relax`、`Interact`、`Move`、`Sit`、`Sleep`。PRTS 导出的 `Default` 常是 110 字节坏文件，不用于动作映射。

例如：

```powershell
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/process_webm.py --src "my-deskpet/work/webm/凯尔希·思衡托" --name "凯尔希·思衡托" --out "my-deskpet/pets/凯尔希·思衡托"
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/validate_deskpet.py "my-deskpet/pets/凯尔希·思衡托" --allow-inactive --out "my-deskpet/work/凯尔希预览.png"
```

重新启动桌宠后，右键 **桌宠库** 选择新角色。转换过程中不改原 WebM，失败不留下半成品角色，也不会覆盖已存在的角色目录。重处理同名角色时，请先输出到新目录，确认预览后关闭桌宠、保留旧素材，再替换。

若解码得到不透明黑底，工具会明确报错。优先重新导出带透明通道的素材；仅在确实需要近似去黑底时使用 `--recover-black`，并检查轮廓、阴影和预览。它不是无损透明恢复。

### 从 PRTS 自动导出

```powershell
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/prts_export.py "浊心斯卡蒂" --skin "升华" --out "my-deskpet/work/webm/浊心斯卡蒂"
```

不写 `--skin` 使用默认时装。导出依赖 PRTS 查看器的页面结构，网站改版或下载失败时可手动导出六段动画，再使用同一转换流程。自动导出脚本沿用上游实现，此次发布未重新做线上 PRTS 导出测试。

## 操作与启动

- 单击互动，双击切换迷你模式。
- 右键解锁后可以拖动；松开恢复之前的状态。
- 右键选择坐下、放松、睡觉，手动状态不会被自动休息覆盖。
- 右键 **自动漫游** 开关移动；设置中调整速度、动作倍速与 20/30/60fps 播放上限。
- **随 Codex 启动** 或托盘 **开机自启动** 是可选项，开启后注册当前用户登录任务与备用启动项；检测到 Codex/ChatGPT 才显示桌宠和托盘。
- 托盘 **隐藏桌宠** 关闭小人，本次宿主运行期间不会立即重拉；**显示桌宠** 可恢复。
- 托盘 **退出** 停止整套监听。之后可双击“启动托盘”快捷方式，或运行项目内 `codex_pet_launcher.pyw` 恢复。
- 同一用户的自启动入口指向一个项目；更换项目目录后，需要重新设置自动启动。

创建桌面和开始菜单快捷方式（可选）：

```powershell
python ark-codex-skill/scripts/create_shortcuts.py --project my-deskpet
```

## 常见问题

**为什么六个 WebM 只有三个待机选项？** 六段源动画不等于六个待机模式。`Relax` 映射放松/待机，`Sit` 和 `Sleep` 是休息选项；`Move` 用于拖动和漫游，`Interact` 用于单击互动，坏的 `Default` 不使用。

**把播放上限改成 60fps，就能让旧角色更流畅吗？** 不能凭空补帧。上游示例仍是原来的固定帧率素材；只有重新从 WebM 转换为 v2 时间戳素材，才能恢复源视频本来有的帧。动作倍速只改变时长，不提升素材帧率。

**字幕仍被省略怎么办？** 调整字幕条宽度，或悬停查看完整内容；字符很多时仍会用省略号。字幕只读本地 Codex rollout 日志，多会话优先显示最近更新的运行中会话，不保证总是前台聊天。

**看不到桌宠怎么办？** 先用托盘“显示桌宠”，再运行 `调试运行.bat`。检查项目内 `pet_error.log`、`pet_runtime.log`、`watcher.log`、`autostart.log`。这些日志可能含个人路径，不要未经检查直接公开。

## 开发与验证

```powershell
.\my-deskpet\.venv\Scripts\python.exe ark-codex-skill/tests/test_deskpet.py
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/tests/test_pipeline.py
```

第一组 33 项测试覆盖日志解析、进程身份、恢复与窗口行为；第二组 10 项测试覆盖脚手架、透明转换和失败清理，包括真实 FFmpeg 合成 WebM 的往返测试。测试不会修改已运行桌宠的设置、启动项或 Codex 会话。实际关机重启、不同显示器组合与线上 PRTS 导出仍需在对应环境验证。

v2 素材格式说明见 [manifest 参考](ark-codex-skill/references/manifest.md)。

## 版权、许可与发布范围

- 原代码和上游示例来自 [AstrariaX/Ark-codex-skill](https://github.com/AstrariaX/Ark-codex-skill)，保留原作者归属和来源。
- 上游目前未提供明确的 LICENSE。本 Fork 不擅自为原作者代码增加 MIT、Apache 等许可证；注明来源不等于获得额外再分发授权。
- 《明日方舟》角色与动画素材版权归原权利人，PRTS 资料遵循其适用许可。保留上游“个人学习、自用、请勿商业发布”的说明。
- 此 Fork 继承原仓库的历史与安洁莉娜示例素材；未额外上传本机新增的凯尔希、斯卡蒂素材、虚拟环境、日志、设置或聊天记录。
- 如需商用、在 GitHub 以外分发素材或重新授权，请先获得对应权利人的许可。

详见 [NOTICE.md](NOTICE.md)。
