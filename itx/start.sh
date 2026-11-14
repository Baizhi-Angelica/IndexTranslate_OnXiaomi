#!/data/data/com.termux/files/usr/bin/bash
# 启动实时字幕引擎，就绪后自动把 ITX 字幕 App 拉到前台（无需 root）
ITX=$HOME/itx
LOG=$ITX/live.log

pkill -f 'itx/live.py' 2>/dev/null
pkill -f 'crispasr --server' 2>/dev/null
sleep 1

nohup python "$ITX/live.py" > "$LOG" 2>&1 &
echo "引擎已启动，正在加载模型（约 5 秒）…"

for i in $(seq 1 60); do
  if (exec 3<>/dev/tcp/127.0.0.1/17321) 2>/dev/null; then
    echo "就绪。"
    am start -n com.itx.overlay/.MainActivity >/dev/null 2>&1 \
      && echo "已打开字幕悬浮窗。" \
      || echo "请手动打开「ITX 字幕」App。"
    exit 0
  fi
  sleep 0.5
done
echo "启动超时，请查看日志：tail -f ~/itx/live.log"
