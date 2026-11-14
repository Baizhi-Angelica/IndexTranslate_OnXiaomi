#!/data/data/com.termux/files/usr/bin/bash
ITX=$HOME/itx

kill_by_port() {
  local port_hex=$1
  su -c "for p in /proc/[0-9]*; do ls -l \$p/fd 2>/dev/null | grep -q 'socket:\[.*\]' || continue; done" >/dev/null 2>&1
  # simpler: use ss-like scan via /proc/net/tcp inode list
  local inodes
  inodes=$(su -c "cat /proc/net/tcp /proc/net/tcp6" 2>/dev/null | awk -v p=":$port_hex" '$2 ~ p"$" {print $10}' | sort -u)
  for ino in $inodes; do
    [ -z "$ino" ] && continue
    local pid
    pid=$(su -c "ls -l /proc/*/fd/* 2>/dev/null | grep 'socket:\[$ino\]' | head -1 | sed -n 's|.*/proc/\([0-9]*\)/fd.*|\1|p'")
    if [ -n "$pid" ]; then
      echo "port $port_hex inode $ino -> pid $pid ($(su -c "cat /proc/$pid/cmdline" | tr '\0' ' ' | cut -c1-60))"
      su -c "kill -9 $pid" 2>/dev/null
    fi
  done
}

echo '== cleanup by port =='
kill_by_port 43A9
kill_by_port 43AA
kill_by_port 22C3
sleep 1
python - <<'PY'
import socket
for p in (17321, 17322, 8899):
    s = socket.socket(); s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", p)); print(p, "STILL OPEN")
    except Exception:
        print(p, "closed")
    finally:
        s.close()
PY
