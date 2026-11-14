#!/data/data/com.termux/files/usr/bin/bash
python - <<'PY'
import ast
ast.parse(open('/data/data/com.termux/files/home/itx/live.py').read())
print("AST_OK")
PY
bash ~/build_apk.sh 2>&1 | grep -E 'error|app.apk' | tail -4
bash ~/install_app.sh 2>&1 | grep -E 'Success|RECORD_AUDIO: granted' | tail -2
