# 给 AI Agent 的安装指引（Termux + 本机实时字幕）

> 目标读者是**替用户部署本项目的 AI agent**。你负责绝大部分操作，用户只做三件事：
> **① 装 Termux → ② 在 Termux 里粘一段初始化命令（含设密码）→ ③ 在设置里点几个开关（仅在没有 root 时）**。
> 每一步需要用户动手时，本文都给出了可以直接复制发给用户的话术。

---

## 0. 开始前：问用户三个问题

把下面这段原样发给用户：

> 为了帮你装好，我需要确认三件事：
> 1. 手机上装了 **Termux** 吗？（没有的话我给你链接，1 分钟装好）
> 2. 手机 **root** 了吗？（有 root 我可以全自动授权；没有也没关系，我带你点几下设置）
> 3. 你手机上的代理（Clash/mihomo）**HTTP 端口是 7890** 吗？不是的话告诉我端口号。

根据回答分支：
- 没装 Termux → 走第 1 步；
- 有 root → 第 5.1 节全自动；
- 没 root → 第 5.2 节，由你带用户点设置。

---

## 1. 用户操作 ①：安装 Termux

发这段给用户：

> 请安装 **F-Droid 版 Termux**（不要用应用商店的老版本）：
> <https://f-droid.org/packages/com.termux/>
> 装好后**打开一次**，等它出现 `~ $` 提示符（首次初始化约 1 分钟），然后告诉我"好了"。

> 本项目**不依赖任何 Termux 插件**（Termux:API / Termux:GUI / Termux:Boot 都不需要）。
> Play 商店版本也能用，但它没有 `RUN_COMMAND`，插件生态不可用——本项目用不到，所以无所谓。

---

## 2. 用户操作 ②：一键初始化 Termux

把下面**整段**发给用户，让他一次性粘贴进 Termux 回车（这是用户唯一需要"打字"的地方）：

```bash
pkg update -y
pkg install -y python git openssh net-tools
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
printf 'export http_proxy=http://127.0.0.1:7890\nexport https_proxy=http://127.0.0.1:7890\n' >> ~/.bashrc
passwd
sshd
echo "================ 手机信息 ================"
whoami
ifconfig 2>/dev/null | grep -E 'inet (192|10|172)\.'
echo "=========================================="
```

同时告诉用户：

> 粘贴回车后会有一次 `passwd` 提示，**输入两次密码**（屏幕不显示，正常），这是给我 SSH 登录用的。
> 最后会打印 `用户名` 和 `IP`，把这两行发给我即可。

预期输出示例：

```
u0_a403
        inet 192.168.1.23  netmask 255.255.255.0  broadcast 192.168.1.255
```

要点：
- `sshd` 成功时输出 `sshd started` 之类，端口固定 **8022**；
- 用户名形如 `u0_a403`，**每台机器不同**；
- 如果 `ifconfig` 打印的是 `127.0.0.1` 或空，让用户连上 Wi-Fi 再看，或改用 `ifconfig wlan0`；
- 想省掉密码这一步，可以用第 2.1 节的密钥方式。

### 2.1（可选，更安全）改用 SSH 密钥

你在电脑上生成一对密钥，把公钥给用户粘贴：

```bash
# 用户在 Termux 里粘贴（把 <PUBKEY> 换成你生成的公钥）
mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '<PUBKEY>' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
```

有了密钥就不需要 `passwd`，也能避免密码进配置文件。

---

## 3. 你（agent）如何找到手机

优先级从高到低：

1. **用户给的 IP**（最快）；
2. Windows：`arp -a` 看局域网邻居，找 8022 端口开放的那个：
   ```powershell
   Get-NetTCPConnection -LocalPort 8022 -ErrorAction SilentlyContinue
   # 或逐个探测
   foreach ($i in 1..254) { $ip="192.168.1.$i"; if((Test-NetConnection $ip -Port 8022 -WarningAction SilentlyContinue).TcpTestSucceeded){ $ip } }
   ```
3. 手机侧：`ifconfig wlan0` 或系统设置 → WLAN → 当前网络 → IP。

> Android 普通应用读不了 netlink，`ip -4 addr` 会 `Permission denied`；**用 `ifconfig`**（`pkg install net-tools`）。

---

## 4. 你（agent）执行：连上并一键部署

```bash
ssh -p 8022 u0_a403@192.168.1.23
# 或在电脑上用本仓库的 helpers（凭据放 config/phone.env，已 gitignore）
python tools/phone.py "uname -a"
```

进到手机后，两条命令完成部署：

```bash
git clone https://github.com/Baizhi-Angelica/IndexTranslate_OnXiaomi.git ~/itx-src
bash ~/itx-src/tools/bootstrap_phone.sh
```

`bootstrap_phone.sh` 是**幂等**的，失败可重跑。它依次完成：

| 步骤 | 内容 | 备注 |
|---|---|---|
| 0 | 环境检查 | 架构、空间、代理连通性 |
| 1 | clone/更新仓库 | `~/itx-src` |
| 2 | `pkg install` | python/git/openssh/curl/cmake/ninja/clang/openjdk-21/aapt2/d8/apksigner |
| 3 | 安装 `hf` | `pip install huggingface_hub` |
| 4 | 下载模型 2.6 GB | 已有则跳过；`HF_HUB_DISABLE_XET=1` |
| 5 | 下载 `android.jar` | `platform-34-ext7_r03.zip`（文件名别写错） |
| 6 | 编译 CrispASR | 7 线程，约 10–20 分钟 |
| 7 | 编译 APK | 全在手机上完成 |
| 8 | 安装 APK + 授权 | 有 root 自动，无 root 打印手动步骤 |
| 9 | 自检 | 逐项打印 ok/警告 |

可选环境变量：`ITX_PROXY`（默认 7890）、`ITX_SKIP_MODELS=1`、`ITX_SKIP_BUILD=1`、`ITX_NO_ROOT=1`。

---

## 5. 权限：这是"用不起来"的头号原因

### 5.1 有 root（全自动，bootstrap 已做）

```bash
su -c 'appops set com.itx.overlay SYSTEM_ALERT_WINDOW allow'
su -c 'pm grant com.itx.overlay android.permission.RECORD_AUDIO'
su -c 'appops set com.itx.overlay RECORD_AUDIO allow'      # MIUI 关键：只 pm grant 会静音
su -c 'pm grant com.itx.overlay android.permission.POST_NOTIFICATIONS'
su -c 'cmd deviceidle whitelist +com.itx.overlay'
```

### 5.2 没有 root：由你带用户点（用户操作 ③）

先帮用户把设置页调出来（你在手机上执行，用户只需点开关）：

```bash
am start -a android.settings.action.MANAGE_OVERLAY_PERMISSION -d package:com.itx.overlay
am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:com.itx.overlay
```

然后发这段给用户（逐条打勾）：

> 请打开「ITX 字幕」的设置，把这 5 项都打开：
> 1. **显示在其他应用上层 / 悬浮窗** → 允许
> 2. **权限 → 麦克风** → 允许（小米：选"仅在使用中允许"或"始终允许"）
> 3. **通知** → 允许
> 4. **省电策略 / 电池** → 无限制
> 5. （小米/红米）**自启动** → 允许
> 弄好回我一句"好了"。

如果之后"有字幕界面但永远不出字"，**先回来检查第 2 项**：MIUI 上只给运行时权限、不给录音 appop 时，
`AudioRecord` 会静默返回全 0，表现就是"麦克风在跑但识别不出东西"。

---

## 6. hf（Hugging Face CLI）在 Termux 里怎么装

```bash
pkg install -y python
pip install -U huggingface_hub
hf --version            # 老版本是 huggingface-cli --version
```

国内/慢网加速：

```bash
pip install -U -i https://pypi.tuna.tsinghua.edu.cn/simple huggingface_hub
```

使用前必须设代理（否则 `hf download` 直接失败）：

```bash
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
export HF_HUB_DISABLE_XET=1        # 关键：否则报 "To use optimized download using Xet storage..."
```

下载单个仓库里的指定文件：

```bash
hf download cstr/index-echo-2b-GGUF \
  index-echo-2b-q8_0.gguf index-echo-2b-decoder-q8_0.gguf \
  --local-dir ~/models/index-echo
```

校验（大小必须对得上）：

```bash
ls -l ~/models/index-echo
# index-echo-2b-q8_0.gguf            702 MB（音频塔）
# index-echo-2b-decoder-q8_0.gguf   2.0 GB（Qwen3.5 解码器）
# ggml-silero-v6.2.0.bin            885 KB（VAD）
```

> 断点续传：重复执行同一条命令即可；它只会补缺失的分片。

---

## 7. 验收清单（必须逐条通过）

```bash
# 1) 引擎可执行
~/crispasr/build/bin/crispasr --version | head -3

# 2) 模型识别一次（会花 20 秒左右，应输出中英交替文本）
cd ~/models/index-echo
~/crispasr/build/bin/crispasr -m index-echo-2b-q8_0.gguf \
  --backend index-echo --target-lang en -t 7 \
  -f ~/crispasr/samples/paraformer_zh.wav -otxt -of "$HOME/tmp/smoke"
cat "$HOME/tmp/smoke.txt"

# 3) App 已安装
su -c 'pm list packages com.itx.overlay'    # 无 root 可省略

# 4) 端到端
bash ~/itx/start.sh
# 预期：约 5 秒后 App 自动弹出，状态「● 聆听中」；说中文 3–7 秒后出英文字幕
tail -5 ~/itx/live.log      # 应能看到 "text client attached" 与 "level peak=..."
```

通过标准：
- `smoke.txt` 里有中文原句 + 英文翻译；
- `live.log` 每 5 秒有一行 `level peak=...`，说话时 peak 明显变大（>2000）；
- 悬浮窗是纯白底、黑字，不再透出下层界面。

---

## 8. 故障对照表（agent 按症状查）

| 症状 | 先查 | 处理 |
|---|---|---|
| `hf` 报 Xet 错误 | `echo $HF_HUB_DISABLE_XET` | `export HF_HUB_DISABLE_XET=1` |
| `hf download` 超时 | `curl -I https://huggingface.co` | 设代理；确认 7890 是 HTTP 混合端口 |
| CrispASR 编译报找不到 cmake | `cmake --version` | `pkg install -y cmake ninja` |
| crispasr 跑几分钟没输出 | 线程数 | **必须 `-t 7`，`-t 8` 会死锁** |
| `aapt2 link` 报 `failed to load include path` | `~/tmp/android.jar` | 重新下 `platform-34-ext7_r03.zip` |
| 安装 APK 报 `resources.arsc ... aligned` | 打包方式 | 不要重打包 APK，只 `zipfile.ZipFile(...,'a')` 追加 `classes.dex` |
| App 一开就闪退 | `targetSdk` | `aapt2 link` 必须 `--target-sdk-version 33` |
| App 永远"等待 Termux" | Manifest 是否有 `INTERNET` | 加 `android.permission.INTERNET` |
| 有界面、状态"聆听中"，但说话不出字 | `tail ~/itx/live.log` 里 `level peak=` | 若 peak 很小（<200）→ 录音权限/appop 没给全；若 peak 正常但 `seg ... 0 pair(s)` → 服务端没检测到语音，确认 8× 增益 |
| 第二次打开不出字 | `pgrep -f 'itx/live.py'` | 旧进程占端口；`bash ~/itx/stop.sh` 后重开 |
| 退出后内存没降 | `pgrep -f crispasr` | 跑 `bash ~/itx/stop.sh` |

---

## 9. 禁止事项（会直接把环境搞坏）

1. **不要**用 `-t 8` 跑 crispasr（必死锁），固定 `-t 7`；
2. **不要**用 `zip`/`jar` 重新打包已生成的 APK（`resources.arsc` 会失配导致装不上），只追加 `classes.dex`；
3. **不要**把 `--target-sdk-version` 提到 34+（前台服务类型校验会让 App 闪退）；
4. **不要**把 `config/phone.env`、`config/github.token`、`*.keystore`、`dev/` 提交进仓库；
5. **不要**改用户的屏幕方向、亮度、系统设置（本项目已不使用任何 root 修系统设置）；
6. **不要**删手机上的任何与本项目无关的文件；
7. 模型下载超过 2 GB 时，**已存在就不要再下**，先 `ls -l` 检查。
