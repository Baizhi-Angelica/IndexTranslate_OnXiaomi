#!/data/data/com.termux/files/usr/bin/bash
APK=$HOME/itx/app/build/app.apk
PKG=com.itx.overlay
su -c "cp $APK /data/local/tmp/itx.apk && chmod 644 /data/local/tmp/itx.apk"
su -c "pm install -r -g /data/local/tmp/itx.apk" 2>&1 | tail -3
echo '== grants =='
su -c "appops set $PKG SYSTEM_ALERT_WINDOW allow"
su -c "appops get $PKG SYSTEM_ALERT_WINDOW"
su -c "pm grant $PKG android.permission.RECORD_AUDIO" 2>&1
su -c "pm grant $PKG android.permission.POST_NOTIFICATIONS" 2>&1
su -c "cmd deviceidle whitelist +$PKG" 2>&1
su -c "dumpsys package $PKG" 2>/dev/null | grep -E 'RECORD_AUDIO|POST_NOTIFICATIONS|versionName' | head -6
echo '== done =='
