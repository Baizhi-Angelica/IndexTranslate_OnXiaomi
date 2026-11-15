# 项目笔记（交接用）

> 最后更新：2026-11-15。覆盖 v1.2 → v1.3 的关键决策、实测数据、失败尝试和踩坑。
> **先读这份，再看 `AGENTS.md` 和 `README.md`。** 这里记录的是"为什么这样做"，以及哪些路已经证明走不通。

## 0. 当前状态（一句话）

小米 15（Android 16 / HyperOS，SM8750 / 骁龙 8 Elite）上，Termux 里跑
CrispASR 0.8.53 + Index-Echo-2B Q8（音频塔 671 MB + 解码器 1.9 GB + Silero VAD），
自编 APK 负责全屏白色悬浮窗和麦克风采集；**当前版本 v1.3，端到端约 2.5–4 秒/句**。
GitHub Release：<https://github.com/Baizhi-Angelica/IndexTranslate_OnXiaomi/releases/tag/v1.3>

## 1. 真实耗时结构（先看这个，别瞎优化）

干净状态、7 线程、4 秒语音片段，`INDEX_ECHO_BENCH=1` 实测：

| 阶段 | 时间 | 说明 |
|---|---:|---|
| mel + 音频编码（AuT） | ~0.84 s | 与音频长度近似线性，约 0.21 s/秒音频 |
| 解码器预填充 | ~0.83 s | 音频 token + prompt；短句固定开销占比更高 |
| 自回归生成 | ~2.18 s | 约 45–60 token；**内存带宽瓶颈** |
| **合计** | **~3.9 s** | 2 秒短句约 2.6–3.1 s |

结论：**生成占 ~56%**。把编码+预填充全部干掉，最多也只省 1.6 s（3.9 → 2.3 s），
生成那 2.2 s 仍然在。所以"NPU 加速预填充"不是银弹。

线程数实测：`-t 7` 最好；5/6/7 差异在噪声内；**`-t 8` 会死锁**（项目硬约束）。

## 2. v1.3 做了什么（以及不要改回去的地方）

### 2.1 中文被误判成英文（最大问题）

- 旧 `--ask` 写的是 "the translation into the other language"，把"翻成哪种语言"交给模型自己判断。
- Index-Echo 会先把一部分中文听成英文，然后执行"中文 → 中文"：同一句中文重复两遍，没有译文。
- 真实会话日志：**61 条字幕里 26 条没有译文**，且是否触发跟说话人音色强相关
  （同一句"好的，先生…白葡萄酒"，冰糖/苏打音色失败，白桦音色成功）。
- 修法：让译文方向锚定在**转写文本**上，而不是音频语种：
  "第 1 行是转写；第 1 行含汉字 → 第 2 行必须是英文；第 1 行全英文 → 第 2 行必须是中文；
  不许把第 1 行重复成第 2 行"。
- 35 条 TTS 回归集：34 条出译文；唯一失败是 0.3 秒的"嗯。"（低于 VAD 最小语音，实际不会送进模型）。
- `live.py` 的 `order_pairs()` 按**行序**解析（第 1 行转写、其余译文），不再按字符集猜角色。

> **不要**回退到"让模型猜语种"或"按 CJK/拉丁字符拆分再配对"，这两个都是已证伪的旧方案。

### 2.2 连续说话时字幕越拖越旧

- 旧队列 `Queue(maxsize=8)` 满了丢**最新**的片段，旧句子堵在前面，延迟越积越大。
- 现在的策略：**丢最旧、保最新**，默认只保留最新 3 段（`ITX_QUEUE_MAX=3`），
  等待超过 `ITX_STALE_S=20` 秒的片段直接跳过。
- 每次请求带 `max_tokens=160`（`ITX_MAX_TOKENS`），防止解码跑飞拖几十秒。
- 日志里会打印 `queue full: drop oldest …`、`(queued N)`，排障先看这些。

### 2.3 App 空转与 MIUI 静音坑

- 现象：引擎断开后旧版 App 仍抱着麦克风不停重连，实测 **62% CPU、86°C、整机 load 20**，
  下一次推理直接慢十倍（一段 4 秒语音要 35 秒）。
- 修复后：保持录音对象、低频重连，断开时 CPU 约 **3.5%**，引擎重启后录音自动恢复。
- **MIUI 坑**：`AudioRecord` 一旦 `stop()`/`release()`，在同一进程里重新打开，
  系统会让它永久返回全 0 帧；logcat 里是 `AudioRecordImpl: [audioRecordData][mute]`。
  实测 `release + new`、`stop + startRecording` 两种重开方式都会被静音。
- 因此 App 的策略是：**录音对象只开一次，引擎断开时继续 `read` 丢弃数据并重连**；
  真正释放麦克风只能靠 `stop.sh` 里的 `force-stop` 关掉整个 App 进程。
- 已知遗留：点「退出」时 `doExit()` 会 `stopRecording()`，而 audioLoop 可能在同一进程里
  又 `openRecorder()`，留下一个被静音的会话。**遇到说话没反应**：`stop.sh` + `start.sh`
  重启一次 App 进程即可。彻底修法是退出时停止循环/杀进程（尚未在 1.3 里做）。

### 2.4 不要缩短 5 秒分段

- 5 秒是"不把长句切碎"的底线。切到 2–3 秒时，模型会自己补全甚至编造后半句
  （实测："这样一个小翻译模型，虽然不是很强大" 切到 3 秒后，模型补出"但已经可以翻译一些简单的句子了"）。
- 所以优化方向是"丢旧保新 + 防跑飞"，不是切短。

## 3. 已证伪 / 已否决的优化路线

### 3.1 提示词/参数微调（无收益）

实测均无可测收益：线程 3/4/5/6/7、把 prompt 从 ~75 token 压到 ~30 token、
`max_tokens` 64/96/160/400、温度 0/0.3/0.6/0.9。正常输出都在 EOS 结束，时间由音频长度和输出 token 决定。

### 3.2 "只输出译文"模式（模型做不到）

给 CrispASR 服务端加 per-request `ask` 字段并重编后，试了 4 种"只输出译文/一行"的写法：
**模型仍然先输出原文再输出译文**，输出 token 没有减少，耗时只从 3.9 s 降到 3.7 s，
且部分写法退化成中文重复。该补丁已还原，没有留在仓库里。

### 3.3 Q4/Q5 量化（owner 已否决）

官方有 Q4_K_M，但实测精度从 **99% 掉到 90%**，翻译质量不可接受，已撤版。
**未经 owner 同意不要再试量化**；如果将来量化，必须用 35 条回归集同时看质量和延迟。

### 3.4 NPU（Hexagon / QNN / Genie）——目前不可行

网上流传的说法（NNAPI 一键开、CrisperWeaver、GGUF 直接喂 GenieX）与仓库事实不符：

- CrispASR 仓库里**没有 NNAPI 集成**；`--gpu-backend` 只接受 `cuda|vulkan|metal|cann|cpu`。
- 仓库里有实验性的 `ggml-hexagon` 后端源码，但**没有接进 CLI**，需要 Hexagon SDK、
  为 HTP 编译的 ops 库、以及签名/unsigned PD；不是改个编译开关的事。
- Termux 侧实测：
  - `dlopen("/vendor/lib64/libOpenCL.so")` 被 Android linker 拒绝：
    `is not accessible for the namespace "(default)"`；
  - Termux 的 Vulkan loader 只能枚举到 `Mesa swrast`（软件设备），
    设 `VK_ICD_FILENAMES=/vendor/lib64/hw/vulkan.adreno.so` 仍然是 `Found no drivers`。
- QNN/Genie 的模型格式与 GGUF 不兼容；Index-Echo 是"AuT 音频塔 + connector + Qwen3.5 解码器"
  的自定义架构，Qualcomm AI Hub 没有现成支持；把音频特征从 QNN 预填充后把 KV 交回
  llama.cpp 做 decode 也没有通道（KV 格式/量化不互通）。
- 收益上限也有限：即使预填充和编码全免费，3.9 s 只降到 2.3 s，decode 仍是内存带宽瓶颈。

**结论：下个月前不要赌 NPU。** 真要做，按"独立 APK + 全模型转 QNN/Genie"立项，按周计。

### 3.5 Vulkan / OpenCL 在 Termux 的现状

- 系统里有 `vulkan.adreno.so` 和 Adreno 830，但 Termux 进程拿不到 vendor 驱动命名空间；
  Termux 的 loader 只看到软件 swrast。
- 要试，只能做"链接系统 `libvulkan.so` + 系统 loader"的定制构建，失败概率高，
  且移动 GPU 对 batch=1 decode 未必更快。属于"值得花半天验证，失败就放弃"的级别。

## 4. 环境与工具链的坑

### 4.1 手机侧

- SSH：Termux `sshd`，端口 **8022**；凭据放 `config/phone.env`（已 gitignore，不要提交）。
- 启动：`bash ~/itx/start.sh`；停止：`bash ~/itx/stop.sh`（会 force-stop App）。
- 录音权限：MIUI 上 `pm grant` 和 `appops set … RECORD_AUDIO allow` **两个都要**，
  只给一个会静默返回全 0。
- 模型/构建：CrispASR 源码在 `~/crispasr`，模型在 `~/models/index-echo`；
  编译约 10–20 分钟，`-DGGML_NATIVE=OFF` 可做可移植构建。
- 日志：`~/itx/live.log`（桥接）、`~/itx/engine.log`（服务端）。

### 4.2 电脑侧（Windows）

- 代理：`http://127.0.0.1:7890`（HTTP/HTTPS/SOCKS 同端口）。
- Git push：`gh` 的 credential helper 在沙箱里会因 Cygwin 创建信号管道失败；
  临时用 `https://x-access-token:<token>@github.com/...` 推，推完把 remote 还原，
  不要把 token 写进 `.git/config` 或提交。
- Chrome headless 渲染 HTML 幻灯片：沙箱里需要 `danger-full-access`（mojo 需要命名管道）；
  且 `--window-size` 包含约 96 px 浏览器 chrome，按 1080 渲染会切掉页脚——
  按 1200 渲染再裁到 1920×1080。
- 视频项目（B 站介绍）在仓库外的 `../IndexTranslate_v1.3_视频`：
  网页渲染幻灯片 + MiMo TTS「茉莉」+ 真机录屏（`live_demo.py` + `demo_feed.py` + `screenrecord`）+ ffmpeg 合成。

## 5. 复现与验证

### 5.1 基本验收

```bash
~/crispasr/build/bin/crispasr --version        # ggml backends: cpu
bash ~/itx/start.sh                             # 约 5 秒后 App 自动弹出
tail -5 ~/itx/live.log                          # 应看到 "text client attached" / "pcm listening"
```

说一句中文，约 3–4 秒后应出现「英文大字 + 中文小字」；说英文则反过来。

### 5.2 回归测试（语言方向）

手机上已有：

- `~/itx/bench.py`：起一个独立服务（8898 端口），批量跑目录里的 WAV，输出 OK/MISS；
- `~/itx/ttssegs*`：35 条 MiMo TTS 测试音频（中文 / 英文 / 中英混说 / 不同音色）；
- `~/itx/ask_b.txt`：当前使用的 `--ask` 指令。

```bash
cd ~/itx
BENCH_DIR=$HOME/itx/ttssegs python bench.py            # 用默认 BIDIR_ASK
BENCH_DIR=$HOME/itx/ttssegs python bench.py ask_b.txt B  # 指定指令
```

验收线：34/35 以上；唯一可接受失败是 0.3 秒的"嗯。"（低于 VAD 最小语音）。

### 5.3 分阶段计时

```bash
INDEX_ECHO_BENCH=1 ~/crispasr/build/bin/crispasr --server ... 2>engine.log
grep index_echo_bench engine.log
```

会打印 `mel / audio_encode / connector / decoder_prefill / decoder_generate` 各阶段耗时。

## 6. 已知遗留 / 下一步

1. **App 退出后同进程重开录音会静音**（见 2.3）。恢复：`stop.sh` + `start.sh`。
   彻底修法：退出时 `running=false`，并延迟杀进程；需要改 Java + 重打 APK（同签名覆盖安装）。
2. **B 站视频未发布**；成片、封面、投稿信息在 `../IndexTranslate_v1.3_视频/out` 与 `B站投稿信息.md`。
3. **聚会实测**：下个月导师聚会后，建议收集 `live.log`（尤其 `raw:`、`queue full`、`level peak=0`），
   再决定是否调 `ITX_QUEUE_MAX` / `ITX_SILENCE_MS`。
4. **速度**：Q4 已被否决；NPU 需独立立项；不要再花时间在 prompt/线程/短切片上。

## 7. 交接检查清单

- [ ] `crispasr --version` 正常，`ggml backends: cpu`
- [ ] `bash ~/itx/start.sh` 能弹出 App，状态「● 聆听中」
- [ ] 说一句中文能出「英大 + 中小」，说英文能反向
- [ ] `tail ~/itx/live.log` 无 `level peak=0` 长串（有则重启 App 进程）
- [ ] 手机剩余空间 > 10 GB，模型文件大小对得上
- [ ] 没有把 `config/phone.env`、token、keystore 提交进仓库
