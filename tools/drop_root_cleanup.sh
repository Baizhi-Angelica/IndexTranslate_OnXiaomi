#!/data/data/com.termux/files/usr/bin/bash
# One-off cleanup: kill root-started leftovers and give rotation back to the system.
su -c 'am force-stop com.itx.overlay'
for D in /proc/[0-9]*; do
  CMD=$(su -c "tr '\0' ' ' < $D/cmdline" 2>/dev/null)
  case "$CMD" in
    *"itx/live.py"*) su -c "kill -9 ${D#/proc/}" 2>/dev/null; echo "killed live ${D#/proc/}" ;;
    *"crispasr --server"*) su -c "kill -9 ${D#/proc/}" 2>/dev/null; echo "killed crispasr ${D#/proc/}" ;;
  esac
done
su -c 'settings put system accelerometer_rotation 1'
su -c 'settings put system user_rotation 0'
rm -f /data/local/tmp/itx_rotation.txt ~/itx/rotation.saved
echo '== rotation now =='
su -c 'settings get system accelerometer_rotation; settings get system user_rotation'
echo '== ports =='
python - <<'PY'
import socket
for p in (17321,17322,8899):
    s=socket.socket(); s.settimeout(0.5)
    try: s.connect(('127.0.0.1',p)); print(p,'open')
    except Exception: print(p,'closed')
    finally: s.close()
PY
