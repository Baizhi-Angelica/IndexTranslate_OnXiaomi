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
| 不要删掉 `BIDIR_ASK` | `--target-lang` 只有 en/ja/es；双向（中⇄英）靠 `--ask` 改写指令实现，删了就只剩单向 |
| `BIDIR_ASK` 的译文判据必须锚定**转写文本**（“第 1 行含汉字 → 第 2 行必须英文”） | 让模型自己判断源语言时，它会把一部分中文当成英文，然后把中文“翻译”成中文（同一句输出两遍）；实测旧写法 61 条字幕里 26 条没有译文，按字符判据后回归集全过 |
| `live.py` 解析按**行序**（第 1 行转写、其余译文），不要再按文字的语种配对 | 模型严格照 `BIDIR_ASK` 输出后，行序就是唯一可靠的语义；按语种配对会把中文转写当成大字译文显示 |
| 队列必须**丢最旧、留最新**（`ITX_QUEUE_MAX`，默认 3；`ITX_STALE_S`，默认 20） | 连续说话时模型追不上，应该优先显示最近的话；排队 15 秒再显示旧片段没有意义 |
| 每次请求带 `max_tokens`（`ITX_MAX_TOKENS`，默认 160） | 服务端默认上限 2000，解码跑飞时一段能拖几十秒；160 足够两行字幕，且不影响正常输出 |
| App 在引擎断开时**不要** stop/release `AudioRecord` | MIUI 会把同一进程里重新打开的录音**永久静音**（所有帧为 0，日志 `AudioRecordImpl: [audioRecordData][mute]`）；只能保持录音对象、继续 `read` 丢弃并重连，靠 `stop.sh` 的 force-stop 真正释放麦克风 |

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
