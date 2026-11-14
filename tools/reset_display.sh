#!/data/data/com.termux/files/usr/bin/bash
# Restore the display to normal and make sure nothing is left running.
ITX=$HOME/itx
su -c 'am force-stop com.itx.overlay' 2>/dev/null
python - <<'PY'
import socket, time
try:
    s = socket.create_connection(("127.0.0.1", 17321), timeout=2)
    s.sendall(b'{"cmd":"quit"}\n'); time.sleep(0.4); s.close()
    print("quit sent")
except Exception as e:
    print("engine not running:", e)
PY
su -c 'settings put system accelerometer_rotation 1'
su -c 'settings put system user_rotation 0'
rm -f "$ITX/rotation.saved"
echo "rotation -> auto (accelerometer_rotation=1, user_rotation=0)"
