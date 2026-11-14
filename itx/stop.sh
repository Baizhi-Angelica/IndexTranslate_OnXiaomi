#!/data/data/com.termux/files/usr/bin/bash
# 停止实时字幕引擎并清理残留（在 Termux 里运行，无需 root）
ITX=$HOME/itx

python - <<'PY'
import socket, time
try:
    s = socket.create_connection(("127.0.0.1", 17321), timeout=2)
    s.sendall(b'{"cmd":"quit"}\n')
    time.sleep(0.4)
    s.close()
    print("已发送退出指令")
except Exception as e:
    print("引擎未在运行：", e)
PY

sleep 1
pkill -f 'itx/live.py' 2>/dev/null
pkill -f 'crispasr --server' 2>/dev/null
rm -f "$ITX/rotation.saved"
echo "已停止（模型内存已释放）"
