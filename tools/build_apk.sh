#!/data/data/com.termux/files/usr/bin/bash
# Build + install the ITX subtitle overlay APK entirely on-device.
set -e
APP=$HOME/itx/app
B=$APP/build
AJ=$HOME/tmp/android.jar
KS=$HOME/itx/itx.keystore
cd "$APP"
rm -rf "$B"
mkdir -p "$B/classes" "$B/dex"

echo '--- aapt2 link ---'
aapt2 link -o "$B/app.unsigned.apk" -I "$AJ" --manifest AndroidManifest.xml \
    --min-sdk-version 26 --target-sdk-version 33 --auto-add-overlay

echo '--- javac ---'
javac -source 8 -target 8 -Xlint:-options -classpath "$AJ" -d "$B/classes" \
    $(find src -name '*.java')

echo '--- d8 ---'
d8 --lib "$AJ" --min-api 26 --output "$B/dex" $(find "$B/classes" -name '*.class')

echo '--- package dex ---'
python3 - "$B" <<'PY'
import sys, zipfile, os
b = sys.argv[1]
apk = os.path.join(b, 'app.unsigned.apk')
dex = os.path.join(b, 'dex', 'classes.dex')
with zipfile.ZipFile(apk, 'a', zipfile.ZIP_DEFLATED) as z:
    z.write(dex, 'classes.dex')
print('appended classes.dex')
PY

echo '--- keystore ---'
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -alias itx -keyalg RSA -keysize 2048 \
      -validity 10000 -storepass itx123456 -keypass itx123456 \
      -dname 'CN=ITX Overlay, O=ITX, C=CN' >/dev/null 2>&1
fi

echo '--- sign ---'
apksigner sign --ks "$KS" --ks-pass pass:itx123456 --key-pass pass:itx123456 \
    --out "$B/app.apk" "$B/app.unsigned.apk"
apksigner verify --print-certs "$B/app.apk" | head -4
ls -l "$B/app.apk"
