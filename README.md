# Ark Codex Skill · 共享桌宠改进版

用明日方舟干员的 PRTS 基建模型制作透明 Windows 桌宠，也可以让多个角色共享一套程序。本仓库发布的是可安装的 Codex Skill、桌宠源码模板和素材工具，不是打包好的 EXE 安装程序。

当前源码候选版本为 **0.3.0-rc.1**。2026-10-06 的 `main` 源码更新包含可配置漫游、全部动作 / 可选 Special、安全角色安装与热刷新、源码打包工具，以及静止人物和字幕清晰度修复。本次同步不创建 GitHub Release 或 tag，旧本地 ZIP 不代表最新源码；请使用当前 `main` 的 **Code → Download ZIP**。参见 [更新记录](CHANGELOG.md) 和 [发布候选说明](docs/release.md)。

## 原项目与致谢

**原项目地址：[AstrariaX/Ark-codex-skill](https://github.com/AstrariaX/Ark-codex-skill)**

本项目 Fork 自 AstrariaX 的 Ark Codex Skill，在原桌宠模板上修复问题并增加功能。感谢原作者提供的 Skill、PRTS 导出脚本与桌宠模板。此改进版并非原作者的官方发布。

改进版仓库：[tinhkho0yktyc-maker/Ark-codex-skill](https://github.com/tinhkho0yktyc-maker/Ark-codex-skill)。

## 本次改进

- 共享桌宠库：右键切换角色，分别保存位置、大小和动作倍速。
- 字幕宽度与角色缩放分离，设置立即生效；悬停查看完整任务、模型、进度及 Token 信息。
- 兼容新旧 Codex 日志，后台增量读取；区分本轮 Token 与会话累计 Token。
- 无操作约 40–60 秒自动坐下、90 秒自动睡觉；手动选择的状态优先，新任务可以唤醒自动休息。
- 自动漫游：随机短距离行走、停顿与方向变化；行走与放松之间有约 140ms 转场，停下保留朝向，自动漫游待机将源片长停帧限为 120ms。互动、拖动、菜单和休息期间暂停，可随时关闭；非漫游及手动动作保留源时间戳。
- 角色缩放、动作切换、显示器和 DPI 变化后约束到屏幕工作区。
- 桌宠、托盘、监听器与轻量守护父进程分别做单实例和身份校验；异常退出退避恢复，正常退出不强行拉起。
- 登录后监听 Codex/ChatGPT；支持计划任务与注册表备用入口，日志轮转和原子设置保存。
- 日常运行环境与素材工具环境分离。
- 新素材转换保留原 WebM 帧及时间戳，裁去透明外边缘，并记录原画布偏移；兼容上游固定帧率素材。
- 附带 97 项隔离回归测试，使用临时生成的非游戏素材，不需要本机新增干员文件。
- “动作与移动”设置支持活动频率、散步比例、最远距离和休息上下限，随机原地动作播放 1–3 个完整周期；原有自动休息可单独关闭。
- 全部动作可播放一次，之后恢复原状态。真实存在的 Special 才显示，不用 Interact 冒充。
- 安全安装器校验全部 PNG、清单、时间戳与偏移；支持运行中冻结 / 刷新，同名替换明确授权并保留备份。

自动启动与自动漫游默认关闭，由用户在菜单中开启。

漫游位置使用连续小数坐标，并根据本窗口的实际物理像素位置补偿 DPI 取整。角色和字幕先绘制为同一张缓存的透明图层，再以预乘 RGBA 插值整体平移，避免整窗和文字在 150% 缩放下跳格。位移计时器参考屏幕刷新率（60–180Hz 范围），动作仍受原有 20/30/60fps 上限控制，不补造动画帧；这不是严格的显示器垂直同步保证。

插值只在实际自动移动期间启用。停下后，显示偏移对齐物理像素，避免放松动作和字幕持续变软；内部连续坐标和保存位置保持不变。单独预览 Move 动画不被视为移动。新增清晰度测试覆盖 100%、125%、150%、175%、200% 缩放。

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

把**同一个干员、同一款皮肤**的 WebM 放在 `my-deskpet/work/webm/<角色名>/`。文件名需包含动画名：`Relax`、`Interact`、`Move`、`Sit`、`Sleep`，还可包含可选 `Special`。PRTS 导出的 `Default` 常是 110 字节坏文件，不用于动作映射；Special 缺席正常，已提供但损坏会报错。

例如：

```powershell
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/process_webm.py --src "my-deskpet/work/webm/凯尔希·思衡托" --name "凯尔希·思衡托" --out "my-deskpet/work/prepared/凯尔希·思衡托"
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/validate_deskpet.py "my-deskpet/work/prepared/凯尔希·思衡托" --allow-inactive --out "my-deskpet/work/凯尔希预览.png"
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/install_deskpet.py "my-deskpet/work/prepared/凯尔希·思衡托" --project my-deskpet
```

安装完成后可直接右键 **桌宠库** 选择新角色，不必重启新版本程序；也可使用 **刷新桌宠库**。转换过程中不改原 WebM，失败不留下半成品角色，也不会覆盖已存在的角色目录。同名安装必须显式加 `--replace`，旧素材保留在 `pets/.backups/`；替换失败尝试恢复。若回执不确定且无法重新冻结运行程序，会保留新版本和旧备份并明确报告，不盲目操作播放中的素材。旧程序第一次升级仍需重启，见发布说明。

若解码得到不透明黑底，工具会明确报错。优先重新导出带透明通道的素材；仅在确实需要近似去黑底时使用 `--recover-black`，并检查轮廓、阴影和预览。它不是无损透明恢复。

### 从 PRTS 自动导出

```powershell
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/scripts/prts_export.py "浊心斯卡蒂" --skin "升华" --out "my-deskpet/work/webm/浊心斯卡蒂"
```

不写 `--skin` 使用默认时装。导出脚本在上游实现的基础上指定透明 VP9 编码，并兼容 Playwright 的下载文件名属性。网页默认 `video/webm` 导出在部分新版 Chromium 上会选用 AV1；即使标有 `alpha_mode=1`，也可能实际没有透明数据。对这样的黑底文件近似抠图会误删深色部分，优先使用此脚本重新导出，再用不带 `--recover-black` 的标准流程转换。

导出依赖 PRTS 查看器的页面结构与浏览器 VP9 支持。脚本会先对首个有效动作录制一次编码器预热，并丢弃这次临时录制，避免冷启动漏掉开头的动作帧。已在 Windows Chrome 上实测凯尔希·思衡托五种有效基建动作的透明导出；其他角色、皮肤与浏览器组合仍需实际验证。网站改版或下载失败时可手动导出，但务必检查实际透明通道，不能仅以文件扩展名或 alpha 标记判断。

## 操作与启动

- 单击互动，双击切换迷你模式。
- 右键解锁后可以拖动；松开恢复之前的状态。
- 右键选择坐下、放松、睡觉，手动状态不会被自动休息覆盖。
- 右键 **自动漫游** 开关移动；设置中调整速度、动作倍速与 20/30/60fps 播放上限。
- 设置 → **动作与移动** 调整散步比例、最远距离、休息上下限、活动频率。0% 散步只做原地动作；活动频率不改变动画倍速。
- 右键 **全部动作（播放一次）** 可预览全部可用动作，Move 预览不改变位置；播放完恢复原状态。只有角色确实提供 Special 才显示特殊动作。
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
.\my-deskpet\.tools-venv\Scripts\python.exe ark-codex-skill/tests/test_extensions.py
```

三组测试分别覆盖运行行为、素材往返及扩展 / 导入 / 发布。保留原有日志、身份、防抖与透明回归，并新增完整动作、漫游范围、冻结租约、替换恢复、回执不确定和发布白名单校验。浏览器测试需要本机 Chrome/Edge，否则跳过。测试不会修改已运行桌宠的设置、启动项或 Codex 会话。实际关机重启、多显示器和真实 PRTS Special 导出仍需对应环境验证。

v2 素材格式说明见 [manifest 参考](ark-codex-skill/references/manifest.md)。

## 版权、许可与发布范围

- 原代码和上游示例来自 [AstrariaX/Ark-codex-skill](https://github.com/AstrariaX/Ark-codex-skill)，保留原作者归属和来源。
- 上游目前未提供明确的 LICENSE。本 Fork 不擅自为原作者代码增加 MIT、Apache 等许可证；注明来源不等于获得额外再分发授权。
- 《明日方舟》角色与动画素材版权归原权利人，PRTS 资料遵循其适用许可。保留上游“个人学习、自用、请勿商业发布”的说明。
- 此 Fork 继承原仓库的历史与安洁莉娜示例素材；未额外上传本机新增的凯尔希、斯卡蒂素材、虚拟环境、日志、设置或聊天记录。
- 如需商用、在 GitHub 以外分发素材或重新授权，请先获得对应权利人的许可。

详见 [NOTICE.md](NOTICE.md)。
