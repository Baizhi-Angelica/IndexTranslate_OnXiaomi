#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
#  ITX Subtitle — one-shot installer for Termux (idempotent, resumable)
#
#  Intended to be run by a human OR an AI agent:
#      git clone https://github.com/Baizhi-Angelica/IndexTranslate_OnXiaomi.git ~/itx-src
#      bash ~/itx-src/tools/bootstrap_phone.sh
#
#  Every step checks first and skips work that is already done, so re-running
#  after a failure is safe. Options (environment variables):
#      ITX_PROXY    http proxy,        default http://127.0.0.1:7890
#      ITX_SRC      repo checkout dir, default ~/itx-src
#      ITX_SKIP_MODELS=1   do not download the 2.6 GB models
#      ITX_SKIP_BUILD=1    do not build CrispASR / the APK
#      ITX_NO_ROOT=1       never call su (manual permission steps are printed)
# =============================================================================
set -u

REPO_URL=${ITX_REPO:-https://github.com/Baizhi-Angelica/IndexTranslate_OnXiaomi.git}
SRC=${ITX_SRC:-$HOME/itx-src}
ITX=$HOME/itx
MODEL_DIR=$HOME/models/index-echo
CRISPASR_DIR=$HOME/crispasr
CRISPASR=$CRISPASR_DIR/build/bin/crispasr
PROXY=${ITX_PROXY:-http://127.0.0.1:7890}
THREADS=${ITX_THREADS:-7}
PKG=com.itx.overlay

export http_proxy=$PROXY https_proxy=$PROXY
export HF_HUB_DISABLE_XET=1

step() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
ok()   { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [!!] %s\n' "$*"; }
die()  { printf '  [xx] %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
has_root() { [ "${ITX_NO_ROOT:-0}" = "1" ] && return 1; su -c true >/dev/null 2>&1; }

# ---------------------------------------------------------------- 0. sanity
step "0/9 环境检查"
case "$(uname -m)" in
  aarch64) ok "arch aarch64" ;;
  *) warn "非 aarch64（$(uname -m)），预编译产物可能不可用，但仍会尝试" ;;
esac
FREE_KB=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
[ "${FREE_KB:-0}" -gt 8000000 ] || warn "可用空间 $((FREE_KB/1024)) MB，建议 ≥ 8 GB（模型 2.6 GB + 编译产物）"
ok "可用空间 $((FREE_KB/1024/1024)) GB"
if curl -s -m 8 -o /dev/null "https://github.com"; then
  ok "代理可用 ($PROXY)"
else
  warn "通过代理访问 github 失败——请先确认 Clash/mihomo 的 HTTP 端口是 7890（或 export ITX_PROXY=...）"
fi

# ---------------------------------------------------------------- 1. repo
step "1/9 获取仓库"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" pull --ff-only >/dev/null 2>&1 && ok "已更新 $SRC" || ok "使用现有 $SRC"
else
  git clone --depth 1 "$REPO_URL" "$SRC" || die "clone 失败（检查代理）"
  ok "cloned -> $SRC"
fi

# ---------------------------------------------------------------- 2. packages
step "2/9 安装系统包"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python git openssh curl cmake ninja clang openjdk-21 aapt2 d8 apksigner \
  || die "pkg install 失败"
ok "python $(python -V 2>&1 | awk '{print $2}') / cmake $(cmake --version | head -1 | awk '{print $3}') / clang $(clang --version | head -1 | awk '{print $3}')"

# ---------------------------------------------------------------- 3. hf
step "3/9 安装 Hugging Face CLI (hf)"
if have hf && hf --version >/dev/null 2>&1; then
  ok "hf 已安装: $(hf version 2>/dev/null || hf --version 2>/dev/null | head -1)"
else
  pip install -U --no-input huggingface_hub || die "pip install huggingface_hub 失败"
  have hf || die "hf 安装后仍不可用"
  ok "hf $(hf --version 2>/dev/null | head -1)"
fi

# ---------------------------------------------------------------- 4. models
step "4/9 下载模型 (约 2.6 GB)"
mkdir -p "$MODEL_DIR"
if [ "${ITX_SKIP_MODELS:-0}" = "1" ]; then
  warn "ITX_SKIP_MODELS=1，跳过"
elif [ -f "$MODEL_DIR/index-echo-2b-q8_0.gguf" ] \
  && [ -f "$MODEL_DIR/index-echo-2b-decoder-q8_0.gguf" ] \
  && [ -f "$MODEL_DIR/ggml-silero-v6.2.0.bin" ]; then
  ok "三个模型文件已存在，跳过下载"
else
  hf download cstr/index-echo-2b-GGUF \
    index-echo-2b-q8_0.gguf index-echo-2b-decoder-q8_0.gguf \
    --local-dir "$MODEL_DIR" || die "模型下载失败（代理? 空间?）"
  hf download ggml-org/whisper-vad ggml-silero-v6.2.0.bin \
    --local-dir "$MODEL_DIR" || die "VAD 模型下载失败"
  ok "模型就绪"
fi
du -sh "$MODEL_DIR" 2>/dev/null || true

# ---------------------------------------------------------------- 5. android.jar
step "5/9 准备 android.jar（aapt2 自带的太旧）"
mkdir -p "$HOME/tmp"
AJ=$HOME/tmp/android.jar
if [ -f "$AJ" ] && unzip -l "$AJ" 2>/dev/null | grep -q resources.arsc; then
  ok "复用 $AJ"
else
  curl -sL -m 600 -o "$HOME/tmp/platform34.zip" \
    https://dl.google.com/android/repository/platform-34-ext7_r03.zip \
    || die "android.jar 下载失败（文件名必须是 platform-34-ext7_r03.zip）"
  unzip -o -q "$HOME/tmp/platform34.zip" -d "$HOME/tmp/p34" || die "unzip 失败"
  find "$HOME/tmp/p34" -name android.jar -exec cp {} "$AJ" \; || die "android.jar 未找到"
  ok "android.jar $(du -h "$AJ" | cut -f1)"
fi

# ---------------------------------------------------------------- 6. crispasr
step "6/9 编译 CrispASR（首次约 10–20 分钟）"
if [ -x "$CRISPASR" ] && "$CRISPASR" --version >/dev/null 2>&1; then
  ok "已存在: $("$CRISPASR" --version 2>&1 | grep -m1 version)"
elif [ "${ITX_SKIP_BUILD:-0}" = "1" ]; then
  warn "ITX_SKIP_BUILD=1，跳过编译"
else
  [ -d "$CRISPASR_DIR/.git" ] || git clone --depth 1 --shallow-submodules --recursive \
      https://github.com/CrispStrobe/CrispASR.git "$CRISPASR_DIR" || die "CrispASR clone 失败"
  ( cd "$CRISPASR_DIR" \
    && cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_OPENMP=OFF \
    && cmake --build build -j5 ) || die "CrispASR 编译失败"
  [ -x "$CRISPASR" ] || die "编译完成但找不到可执行文件"
  ok "crispasr $(du -h "$CRISPASR" | cut -f1)"
fi

# ---------------------------------------------------------------- 7. app
step "7/9 编译悬浮窗 APK"
mkdir -p "$ITX"
rsync -a --delete "$SRC/itx/app/" "$ITX/app/" 2>/dev/null \
  || cp -r "$SRC/itx/app/." "$ITX/app/"
cp "$SRC/itx/live.py" "$SRC/itx/start.sh" "$SRC/itx/stop.sh" "$ITX/"
chmod +x "$ITX"/*.sh
if [ "${ITX_SKIP_BUILD:-0}" = "1" ]; then
  ok "源码与脚本已就位（跳过编译）"
else
  bash "$SRC/tools/build_apk.sh" >"$HOME/itx/build.log" 2>&1 \
    || { tail -20 "$HOME/itx/build.log"; die "APK 编译失败"; }
  [ -f "$ITX/app/build/app.apk" ] || die "APK 未生成"
  ok "APK $(du -h "$ITX/app/build/app.apk" | cut -f1)"
fi

# ---------------------------------------------------------------- 8. install + grants
step "8/9 安装 APK 并授权"
if [ -f "$ITX/app/build/app.apk" ]; then
  if has_root; then
    su -c "cp $ITX/app/build/app.apk /data/local/tmp/itx.apk && chmod 644 /data/local/tmp/itx.apk"
    su -c "pm install -r -g /data/local/tmp/itx.apk" >/dev/null && ok "APK 已安装"
    su -c "appops set $PKG SYSTEM_ALERT_WINDOW allow" && ok "overlay appop"
    su -c "pm grant $PKG android.permission.RECORD_AUDIO" 2>/dev/null
    su -c "appops set $PKG RECORD_AUDIO allow" && ok "record appop"
    su -c "pm grant $PKG android.permission.POST_NOTIFICATIONS" 2>/dev/null
    su -c "cmd deviceidle whitelist +$PKG" >/dev/null 2>&1 && ok "电池白名单"
  else
    warn "无 root：请手动安装 $ITX/app/build/app.apk"
    warn "并手动开启：显示在其他应用上层 / 麦克风 / 通知 / 电池无限制"
    have termux-open && termux-open --content-type application/vnd.android.package-archive \
      "$ITX/app/build/app.apk" 2>/dev/null || true
  fi
else
  warn "没有 APK，跳过安装（可用 release/ 里的预编译版本）"
fi

# ---------------------------------------------------------------- 9. verify
step "9/9 自检"
[ -x "$CRISPASR" ] && ok "crispasr 可执行"
[ -f "$MODEL_DIR/index-echo-2b-q8_0.gguf" ] && ok "模型文件存在"
[ -f "$ITX/live.py" ] && ok "live.py 就位"
[ -f "$ITX/start.sh" ] && ok "start.sh 就位"
if has_root; then
  su -c "pm list packages $PKG" 2>/dev/null | grep -q "$PKG" && ok "App 已安装 ($PKG)"
fi

cat <<'EOF'

=============================================================================
 安装完成。使用：

   bash ~/itx/start.sh      # 启动引擎 + 自动打开字幕悬浮窗
   bash ~/itx/stop.sh       # 停止并释放模型内存

 首次启动要加载模型（约 5 秒），状态变「● 聆听中」后说中文即可。
 日志：tail -f ~/itx/live.log
=============================================================================
EOF
