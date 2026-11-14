# IndexTranslate On Xiaomi 15

在 Android 手机上跑**本地实时中英字幕**：中文语音 → 英文大字 + 中文小字对照，
全屏纯白悬浮窗、悬浮于其他 App 之上，全程离线，不上传任何音频。

> 在 **小米 15（Android 16 / HyperOS）** 上完成并验证。整套推理跑在 Termux 里，
> 模型是 B 站 [Index-Echo-S2TT-2B](https://huggingface.co/IndexTeam/Index-Echo-S2TT-2B)，
> 运行时是 [CrispASR](https://github.com/CrispStrobe/CrispASR)。

![字幕界面](itx/h2.png)

## 特性

- **纯本地**：音频只在内存里流转，不落盘、不上传网络
- **实时**：一句中文说完后约 3–7 秒出英文（2B 模型 CPU 推理的物理上限）
- **双向互译**：中→英 / 英→中 自动判断；大字是译文、小字是原文，**上一句与当前句同样式**，各自可换行完整显示
- **全屏白底黑字**：`#FFFFFF` / `#000000`，适合 5 米内观看
- **真悬浮窗**：`TYPE_APPLICATION_OVERLAY`，盖在其他 App 之上，有「隐藏 / 退出」按钮
- **无需 root**：日常使用只要在 Termux 里跑一条命令
- **方向跟随系统**：不强制、不修改任何系统设置

## 快速开始

### 1. 安装 APK

下载 [`release/ITX-Subtitle-1.2.apk`](release/ITX-Subtitle-1.2.apk) 并安装（需允许"安装未知应用"）。

安装后给两个权限（**MIUI 必须两个都给**，否则录音会静默返回全 0）：

```bash
su -c 'appops set com.itx.overlay SYSTEM_ALERT_WINDOW allow'
su -c 'pm grant com.itx.overlay android.permission.RECORD_AUDIO'
su -c 'appops set com.itx.overlay RECORD_AUDIO allow'
su -c 'pm grant com.itx.overlay android.permission.POST_NOTIFICATIONS'
su -c 'cmd deviceidle whitelist +com.itx.overlay'
```

（没有 root 也可以：在系统设置里手动开启"显示在其他应用的上层"、麦克风权限、自启动。）

### 2. 准备引擎

按 [部署指南](docs/deploy.md) 装好 Termux + 模型 + 编译 CrispASR，然后把 `itx/` 下的三个脚本放进手机 `~/itx/`：

```
~/itx/live.py      # 桥接：麦克风 → 增益 → VAD → 模型 → 字幕
~/itx/start.sh     # 启动引擎 + 自动拉起 App
~/itx/stop.sh      # 停止引擎、释放内存
```

### 3. 使用

```bash
bash ~/itx/start.sh
```

约 5 秒后 App 自动弹出并进入字幕模式（状态「● 聆听中」），对着手机说中文即可。

![启动引导](itx/guide.png)

用完点悬浮窗右上角「退出」：

![退出引导](itx/exitp.png)

- App 会先通过本地 socket 通知引擎退出（模型内存释放）；
- 界面显示 `bash ~/itx/stop.sh` 作为兜底（已自动复制到剪贴板）；
- 点「关闭」结束。

## 给 AI Agent 的一键安装

仓库自带面向自动化 agent 的说明与引导脚本，agent 可以直接代你完成部署：

```
AGENTS.md                  agent 必读的约束清单（改代码前看）
docs/agent-install.md      给 agent 的完整部署剧本（含需要发给用户的提示语）
tools/bootstrap_phone.sh   幂等的一键安装脚本
```

在手机的 Termux 里两条命令即可：

```bash
git clone https://github.com/Baizhi-Angelica/IndexTranslate_OnXiaomi.git ~/itx-src
bash ~/itx-src/tools/bootstrap_phone.sh
```

脚本会依次：装系统包 → 装 `hf` → 下模型(2.6 GB) → 编 CrispASR → 编 APK → 装 APK → 授权 → 自检。
没有 root 也能跑，脚本会在安装那步打印出手动授权步骤；需要用户配合的部分（装 Termux、设 SSH 密码、点权限开关）
在 [docs/agent-install.md](docs/agent-install.md) 里都写成了可以直接复制发给用户的话术。

## 工作方式

```
麦克风 16 kHz 单声道
      │  AudioRecord（前台服务，targetSdk 33）
      ▼  TCP 127.0.0.1:17322
  live.py ── 8× 数字增益 → 能量 VAD（静音 0.55s 收尾 / 最长 5s）
      │      音频仅在内存中打包成 WAV
      ▼  HTTP 127.0.0.1:8899
  crispasr --server（index-echo-2b Q8，常驻，7 线程）
      │      中文转写 + 英文翻译（逐句对照）
      ▼  TCP 127.0.0.1:17321（JSON 行）
  悬浮窗 App（大字=译文，小字=原文，中英自动切换）
```

## 项目结构

```
.
├─ README.md                 中文说明（本文件）
├─ README.en.md              English README
├─ docs/
│  └─ deploy.md              新手机从零部署 + 17 条踩坑记录
├─ itx/
│  ├─ live.py                桥接引擎
│  ├─ start.sh / stop.sh     启动 / 停止
│  ├─ app/                   悬浮窗 App 源码（Java）
│  └─ *.png                  界面实拍
├─ release/
│  ├─ ITX-Subtitle-1.2.apk   预编译 APK（最新）
├─ tools/
│  ├─ phone.py               SSH/SFTP 小工具（凭据从 config/phone.env 读取）
│  ├─ build_apk.sh           手机上构建 APK 的完整流程
│  ├─ install_app.sh         安装 + 授权
│  └─ cleanup_ports.sh       清理残留进程
└─ config/
   └─ phone.env.example      连接配置模板（真实值 phone.env 已被 gitignore）
```

## 可调参数（`live.py` 环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ITX_GAIN` | `8` | 麦克风数字增益（原始电平约 -46 dBFS） |
| `ITX_VAD_MIN` | `110` | VAD 绝对阈值 |
| `ITX_SILENCE_MS` | `550` | 静音多久算一句结束 |
| `ITX_MAX_SEG_MS` | `5000` | 单句最长长度 |
| `ITX_THREADS` | `7` | 推理线程数（8 会死锁） |
| `ITX_ASK` | 双向指令 | 覆盖模型指令；改它可固定单向或换目标语言 |

## 双向互译（中 ⇄ 英）

CrispASR 的 `--target-lang` 只暴露 en/ja/es，但 index-echo 本质是"按指令输出三行字幕"的音频大模型，
用 `--ask` 改写指令就能让它翻成**另一种语言**：

- **说中文** → 英文大字 + 中文小字；
- **说英文** → 中文大字 + 英文小字；
- 方向由字幕内容自动判断，不需要任何开关。

指令原文（`itx/live.py` 的 `BIDIR_ASK`）：

```
For each sentence, output three lines: the [MM:SS.CC-MM:SS.CC] timestamp,
the transcript, then the translation into the other language
(Chinese speech -> English; English speech -> Chinese).
```

想固定成单向，启动前用 `export ITX_ASK='...'` 覆盖即可。

## 已知限制

- 单句超过 5 秒会被强制切分，字幕可能分成两条。
- 安静环境偶尔被环境噪声触发，产生空转写（立即返回，不影响使用）。
- 状态栏图标无法被第三方悬浮窗覆盖（系统限制）。
- 首次启动模型加载约 5 秒。
- 同一会话里中英混说时，模型的上下文可能串味，偶发一行错位（重新开始会话即可恢复）。

## 相关项目

- [bilibili/Index-Translate](https://github.com/bilibili/Index-Translate) — 模型与论文
- [CrispStrobe/CrispASR](https://github.com/CrispStrobe/CrispASR) — GGUF 推理运行时
