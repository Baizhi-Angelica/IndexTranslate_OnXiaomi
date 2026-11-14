#!/data/data/com.termux/files/usr/bin/bash
ITX=$HOME/itx
echo '== close app + stop engine =='
su -c 'am force-stop com.itx.overlay'
bash "$ITX/stop.sh" 2>&1 | tail -2
sleep 3
echo '== state =='
python - <<'PY'
import socket
for p in (17321,17322,8899):
    s=socket.socket(); s.settimeout(0.5)
    try: s.connect(('127.0.0.1',p)); print(p,'STILL OPEN')
    except Exception: print(p,'closed')
    finally: s.close()
PY
echo "app: $(su -c 'pidof com.itx.overlay' || echo stopped)"
echo "rotation: $(su -c 'settings get system accelerometer_rotation; settings get system user_rotation' | tr '\n' ' ')"
free -h | head -2
echo '== files =='
ls ~/itx/*.sh ~/itx/live.py 2>/dev/null
