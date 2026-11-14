# 新手机部署指南（从零到可以说话出字幕）

> 目标机型是 **小米 15（Android 16 / HyperOS V816）**，但这套流程对大多数 Android 13+ 手机适用。
> 全程只需要手机本身 + 一个可用的 HTTP 代理（本文用手机本机的 Clash，端口 `7890`）。

---

## 0. 前置条件

| 项目 | 要求 |
|---|---|
| Android | 13 及以上（本项目在 Android 16 上验证） |
| 存储 | ≥ 8 GB 可用（模型 2.6 GB + 编译中间产物 + 预留） |
| 内存 | ≥ 8 GB（模型常驻约 3–4 GB） |
| 代理 | 手机上有可用的 HTTP 代理，默认假设 `http://127.0.0.1:7890`（Clash / mihomo） |
| root | **不需要**（最终方案完全不依赖 root，仅首次授权 App 权限时用一下更省事） |

---

## 1. 安装 Termux

推荐 **F-Droid 版**（`com.termux`）。关掉"从 Google Play 安装"的旧版本也可以，但要注意：

- Play 版**没有** `RunCommandService`（`com.termux.RUN_COMMAND` 不存在），所有 Termux 插件/widget 方案都不可用；
- Play 版与 F-Droid 插件的签名不同，`sharedUserId` 会把两者分到不同 UID，`Termux:GUI` / `Termux:API` 这类插件连不上（本项目最终没有用任何插件，所以两者都能跑）。

安装后先打开一次 Termux，等它初始化 `$PREFIX`。

### 设置代理

```bash
export http_proxy="http://127.0.0.1:7890"
export https_proxy="http://127.0.0.1:7890"
# 想持久化就写进 ~/.bashrc
echo 'export http_proxy="http://127.0.0.1:7890"'  >> ~/.bashrc
echo 'export https_proxy="http://127.0.0.1:7890"' >> ~/.bashrc
```

验证：

```bash
curl -sI -m 10 https://huggingface.co | head -1
```

> 没有代理时下载模型/依赖会直接失败。Clash 的"混合端口"就是 7890。

### 基础包

```bash
pkg update -y
pkg install -y python git openssh curl
```

> 本项目用 SSH 从电脑远程调试：`sshd` 起在 8022 端口，`passwd` 设个密码即可。
> ```bash
> passwd
> sshd
> ```

---

## 2. 下载模型（约 2.6 GB）

```bash
export HF_HUB_DISABLE_XET=1      # 关键：否则 hf 会要求安装 hf_xet 而报错
mkdir -p ~/models/index-echo

hf download cstr/index-echo-2b-GGUF \
  index-echo-2b-q8_0.gguf index-echo-2b-decoder-q8_0.gguf \
  --local-dir ~/models/index-echo

hf download ggml-org/whisper-vad ggml-silero-v6.2.0.bin \
  --local-dir ~/models/index-echo
```

下载完应是：

```
~/models/index-echo/index-echo-2b-q8_0.gguf           702 MB   (音频塔)
~/models/index-echo/index-echo-2b-decoder-q8_0.gguf  2.0 GB    (Qwen3.5 解码器)
~/models/index-echo/ggml-silero-v6.2.0.bin           885 KB    (VAD)
```

> **坑**：`hf` 默认走 Xet 存储，Termux 上会报
> `Invalid value: To use optimized download using Xet storage, you need to install the hf_xet package`。
> 设 `HF_HUB_DISABLE_XET=1` 即可。

---

## 3. 编译 CrispASR（推理引擎）

CrispASR 是目前唯一能跑 index-echo GGUF 的运行时（`--backend index-echo`）。

```bash
pkg install -y cmake ninja
git clone --depth 1 --shallow-submodules --recursive \
    https://github.com/CrispStrobe/CrispASR.git ~/crispasr
cd ~/crispasr
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_OPENMP=OFF
cmake --build build -j5        # 7 核手机约 8–15 分钟
```

产物：`~/crispasr/build/bin/crispasr`。

验证（用仓库自带的中文样例，13 秒）：

```bash
cd ~/models/index-echo
~/crispasr/build/bin/crispasr -m index-echo-2b-q8_0.gguf \
  --backend index-echo --target-lang en -t 7 \
  -f ~/crispasr/samples/paraformer_zh.wav -otxt -of /tmp/test
cat /tmp/test.txt
```

应输出「中文原句 + 英文翻译」交替的多行文本。

> **坑 1**：`-t 8` 会死锁（跑几分钟无输出）。**固定 7 线程**。
> **坑 2**：同时开两个 crispasr 会吃满 14 GB 内存并疯狂换页——调试时务必先 `pkill -f crispasr`。
> **坑 3**：Termux 没有 `/tmp`，脚本里用 `$HOME/tmp`。

---

## 4. 编译悬浮窗 APK（全在手机上，不用电脑）

需要的工具链 Termux 源里都有：

```bash
pkg install -y openjdk-21 aapt2 d8 apksigner
```

`aapt2` 自带的 `android.jar` 太旧（解析 `allowBackup` 等属性会报错），需要一份新的：

```bash
cd ~/tmp
curl -sL -o platform34.zip https://dl.google.com/android/repository/platform-34-ext7_r03.zip
unzip -o -q platform34.zip -d p34
find p34 -name android.jar -exec cp {} ~/tmp/android.jar \;
```

> **坑**：Google 仓库里没有 `platform-34_r03.zip` 这个名字，正确文件是 `platform-34-ext7_r03.zip`。
> 完整列表可以抓 `https://dl.google.com/android/repository/repository2-3.xml`。

然后构建（脚本在 `tools/build_apk.sh`，手机上路径 `~/build_apk.sh`）：

```bash
cd ~/itx/app
aapt2 link -o build/app.unsigned.apk -I ~/tmp/android.jar \
    --manifest AndroidManifest.xml --min-sdk-version 26 --target-sdk-version 33 --auto-add-overlay
javac -source 8 -target 8 -Xlint:-options -classpath ~/tmp/android.jar -d build/classes \
    $(find src -name '*.java')
d8 --lib ~/tmp/android.jar --min-api 26 --output build/dex $(find build/classes -name '*.class')
# 关键：用「追加」方式塞 dex，不要重新打包整个 APK
python3 -c "import zipfile;z=zipfile.ZipFile('build/app.unsigned.apk','a',zipfile.ZIP_DEFLATED);z.write('build/dex/classes.dex','classes.dex');z.close()"
keytool -genkeypair -keystore ~/itx/itx.keystore -alias itx -keyalg RSA -keysize 2048 \
    -validity 10000 -storepass itx123456 -keypass itx123456 -dname 'CN=ITX Overlay, O=ITX, C=CN'
apksigner sign --ks ~/itx/itx.keystore --ks-pass pass:itx123456 --key-pass pass:itx123456 \
    --out build/app.apk build/app.unsigned.apk
```

> **坑 1**：`--target-sdk-version` 必须是 **33**。34+ 时 `foregroundServiceType="microphone"`
> 会要求"服务必须在前台启动"，被 shell 拉起直接抛 `SecurityException` 闪退。
> **坑 2**：重打包 APK 会让 `resources.arsc` 变成压缩且不对齐，安装报
> `Targeting R+ requires the resources.arsc of installed APKs to be stored uncompressed and aligned`。
> 用 `zipfile.ZipFile(..., 'a')` **追加** `classes.dex` 即可保留原对齐。
> **坑 3**：`javac` 用 `-classpath`（不要 `-bootclasspath`），否则 lambda 会报
> `cannot find symbol: metafactory`。

---

## 5. 安装并授权

```bash
su -c 'cp ~/itx/app/build/app.apk /data/local/tmp/itx.apk && chmod 644 /data/local/tmp/itx.apk'
su -c 'pm install -r -g /data/local/tmp/itx.apk'
su -c 'appops set com.itx.overlay SYSTEM_ALERT_WINDOW allow'
su -c 'pm grant com.itx.overlay android.permission.RECORD_AUDIO'
su -c 'appops set com.itx.overlay RECORD_AUDIO allow'      # MIUI 关键：只 pm grant 不够
su -c 'pm grant com.itx.overlay android.permission.POST_NOTIFICATIONS'
su -c 'cmd deviceidle whitelist +com.itx.overlay'
```

> **坑 1**：MIUI 的录音权限是 appop 控制的，只 `pm grant` 时 `AudioRecord` 会返回**全 0**（不报错）。
> **坑 2**：悬浮窗同理，必须 `appops set SYSTEM_ALERT_WINDOW allow`。

---

## 6. 部署脚本到 `~/itx`

把仓库里的 `itx/live.py`、`itx/start.sh`、`itx/stop.sh` 传到手机 `~/itx/`：

```bash
python tools/phone.py --put itx/live.py  /data/data/com.termux/files/home/itx/live.py
python tools/phone.py --put itx/start.sh /data/data/com.termux/files/home/itx/start.sh
python tools/phone.py --put itx/stop.sh  /data/data/com.termux/files/home/itx/stop.sh
# 或直接 scp -P 8022 ...
chmod +x ~/itx/*.sh
```

（远端路径就是 `$HOME`：`/data/data/com.termux/files/home/itx/`。）

---

## 7. 使用

```bash
bash ~/itx/start.sh
```

脚本会：启动 `live.py` → 拉起 `crispasr --server` → 等模型就绪（约 5 秒）→
自动 `am start` 打开「ITX 字幕」App → 悬浮窗直接进入字幕模式（状态「● 聆听中」）。

说话 → 约 2.5–4 秒后出英文大字 + 中文小字（5 秒语音段）。用完点悬浮窗「退出」→「关闭」。

```bash
bash ~/itx/stop.sh     # 兜底停止 + 释放内存
tail -f ~/itx/live.log # 看实时日志
```

---

## 8. 踩坑总表

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | `hf download` 报 `Invalid value ... hf_xet` | 默认走 Xet | `export HF_HUB_DISABLE_XET=1` |
| 2 | `Termux:GUI` 永远连不上 | 插件要求与客户端**同 UID**（`peerCredentials.uid`），Play 版 Termux 签名不同 → 两个 shared user | 放弃插件方案，自写 APK |
| 3 | App 查不到 Termux 包（`NameNotFoundException`） | Android 11+ 包可见性 | Manifest 加 `<queries><package android:name="com.termux"/></queries>` |
| 4 | 用 root 拉起引擎时 `bash: No such file or directory` | KernelSU 的 app-initiated `su` 在 App 的 mount namespace 里看不到 Termux 私有目录 | 最终方案：不用 root，用户手动跑 `start.sh` |
| 5 | 悬浮窗只有 80% 不透明，背景透出下层 App | MIUI 把「全屏且不可触摸」的 `TYPE_APPLICATION_OVERLAY` 强制压到 α=0.8 | 去掉 `FLAG_NOT_TOUCHABLE`，窗口改为可触摸 |
| 6 | App 一打开就闪退 | Android 14 对 `foregroundServiceType="microphone"` 的前台服务做前台状态校验 | `targetSdk=33` + `startForeground(id, notif)` 两参重载 |
| 7 | 麦克风有数据但全是 0 | `AudioRecord` 创建后**没调用 `startRecording()`** | 补上并检查 `RECORDSTATE_RECORDING` |
| 8 | 服务端 VAD 判定"无人说话"，0.1 秒返回空 | 手机麦克风原始电平约 **-46 dBFS** | 桥接层加 **8× 数字增益 + 削波**（`ITX_GAIN`） |
| 9 | 推理几分钟不出结果 | `-t 8` 在 7 核 cpuset 下死锁 | 固定 `-t 7` |
| 10 | 第二次打开 App 不出字 | 旧 `live.py` 仍占端口，新的绑定失败；且旧实例的 `crispasr` 可能已被后来的启动脚本 `pkill` 掉 | 启动前先杀干净旧进程 + 端口重试绑定 |
| 11 | 引擎莫名退出 | 12 秒无客户端看门狗把端口探测连接当成"App 已断开" | 忽略 3 秒内的瞬时连接，超时放宽到 30 秒 |
| 12 | App 一直停在"等待 Termux" | 重写 Manifest 时**漏了 `INTERNET` 权限**，连接 127.0.0.1 直接失败 | 补回 `INTERNET` |
| 13 | 隐藏后再打开回到引导页 | 重建悬浮窗时没恢复 `connected` 状态 | 创建后调 `applyConnectedUi(connected)` |
| 14 | 模型把译文和原文顺序颠倒 / 中英混在一行 | index-echo 的输出格式不完全稳定 | `live.py` 按**行序**解析（第 1 行转写、其余译文），并清理时间戳、重复行 |
| 15 | `am start` 弹"Termux 想要打开 ITX 字幕" | MIUI 的后台启动拦截 | 首次点"始终允许"，或由 `start.sh` 触发（可控） |
| 16 | 电脑端 `curl github.com` 全失败 | 电脑没有代理/没有外网 | 所有下载都通过手机 `7890` 代理完成 |
| 17 | `adb` 没有、`ssh 8022` 连不上 | Termux 的 sshd 未启动 | `sshd`，端口 8022，用户名是 `u0_aXXX` |
| 18 | 引擎重启后 App 录音全是 0 | MIUI 会把同一进程里 stop/release 后重新打开的 `AudioRecord` 永久静音（logcat：`AudioRecordImpl: [audioRecordData][mute]`） | App 保持录音对象、断开时继续 `read` 丢弃并重连；`stop.sh` 用 force-stop 关 App 才真正释放麦克风 |
| 19 | 引擎断开时 App 空转抢 CPU | 旧版麦克风线程在无连接时反复重连/重开录音，实测 62% CPU、发热降频 | 同上：保持录音 + 有节奏地重连，断开时 CPU 约 3.5% |

---

## 9. 语言方向（双向）

`--target-lang` 只暴露 en/ja/es，但 index-echo 是按指令输出的音频大模型，`--ask` 可整体改写指令。

**关键：不要让模型自己判断"这是中文还是英文"。** 实测它会把一部分中文听成英文，然后执行"中文→中文"，把同一句原样输出两遍——61 条真实字幕里有 26 条没有译文，而且是否触发跟说话人音色有关。现在的指令把译文方向**锚定在转写出来的文字**上：

```
Output exactly two lines for each sentence, with no timestamps.
Line 1: the transcript in the language actually spoken.
Line 2: the translation into the other language. If line 1 contains Chinese
characters, line 2 must be English. If line 1 is fully English, line 2 must be
Chinese. Never repeat line 1 as line 2.
```

- 说中文 → 英文大字 + 中文小字
- 说英文 → 中文大字 + 英文小字
- 模型先写第 1 行，再按"第 1 行有没有汉字"决定第 2 行，绕开了它对音频语种的误判；回归集 35 条只剩 1 条 0.3 秒的"嗯。"没译文
- 想固定单向：`export ITX_ASK='For each sentence, output the transcript, then the English translation.'`

相关文件：`live.py` 的 `BIDIR_ASK`、`order_pairs()`（按行序配对，不按字符集猜角色）。
