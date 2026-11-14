# AGENTS.md

面向自动化 agent 的仓库说明。人类用户请看 [README.md](README.md)；
替用户部署请照 [docs/agent-install.md](docs/agent-install.md) 执行。

## 这是什么

在 Android（小米 15 / HyperOS，Android 16 验证）上跑**全离线实时中英字幕悬浮窗**：
Termux 里跑 CrispASR + index-echo-2b 做语音翻译，自编 APK 负责全屏白底悬浮窗与麦克风采集。

## 一键安装（在手机 Termux 里执行）

```bash
git clone https://github.com/Baizhi-Angelica/IndexTranslate_OnXiaomi.git ~/itx-src
bash ~/itx-src/tools/bootstrap_phone.sh
```

脚本幂等，可重跑；约 2.6 GB 模型 + 10–20 分钟编译。
可选环境变量：`ITX_PROXY`、`ITX_SKIP_MODELS=1`、`ITX_SKIP_BUILD=1`、`ITX_NO_ROOT=1`。

前置条件（需要用户配合，话术见 docs/agent-install.md）：
Termux 已安装、代理 `127.0.0.1:7890` 可用、`pkg install python git openssh net-tools`、`passwd` + `sshd`。

## 硬约束（改代码时必须保持）

| 约束 | 原因 |
|---|---|
| `crispasr` 固定 `-t 7` | `-t 8` 在本机 cpuset 下**死锁**（实测跑几分钟无输出） |
| `aapt2 link --target-sdk-version 33` | 34+ 会校验 `foregroundServiceType="microphone"`，被 shell 拉起即 `SecurityException` 闪退 |
| 打包 APK 只**追加** `classes.dex` | 重新打包会让 `resources.arsc` 变压缩/不对齐，安装报错 |
| `javac` 用 `-classpath`，不用 `-bootclasspath` | 否则 lambda 报 `cannot find symbol: metafactory` |
| Manifest 必须含 `INTERNET` | 否则连不上 `127.0.0.1` 的本地端口 |
| 录音要同时给权限和 appop | MIUI 上只 `pm grant` 会让 `AudioRecord` 静默返回全 0 |
| 悬浮窗必须**可触摸** | MIUI 会把"全屏且不可触摸"的 overlay 压到 α=0.8，背景透出 |
| `live.py` 的 8× 增益 | 手机原始麦克风电平约 −46 dBFS，不加增益服务端 VAD 直接判"无人说话" |
| 日常流程不依赖 root | 引擎由用户 `bash ~/itx/start.sh` 启动并自动 `am start` 拉起 App |

## 关键路径

```
~/itx-src                 仓库（本仓库）
~/itx/live.py             麦克风 → 增益 → VAD → HTTP → 字幕（桥接）
~/itx/start.sh, stop.sh   启动 / 停止
~/itx/app/                APK 源码，构建产物在 ~/itx/app/build/app.apk
~/crispasr/build/bin/crispasr
~/models/index-echo/      三个 GGUF/bin 模型（2.6 GB）
~/tmp/android.jar         编译用（platform-34-ext7）
~/itx/live.log            运行日志（排障第一入口）
```

## 验收

```bash
~/crispasr/build/bin/crispasr --version
bash ~/itx/start.sh                     # 约 5 秒后 App 自动弹出，状态「● 聆听中」
tail -5 ~/itx/live.log                  # 应有 "text client attached" 与 "level peak=..."
```

## 不要做

- 提交 `config/phone.env`、`config/github.token`、`*.keystore`、`dev/`（已在 `.gitignore`）
- 修改用户的屏幕方向/亮度等系统设置（本项目不再使用 root 改设置）
- 删除与本项目无关的用户文件
- 已存在的模型不要重复下载（先 `ls -l ~/models/index-echo`）
