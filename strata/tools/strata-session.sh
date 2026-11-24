#!/bin/sh
# 推論機（Strata）の会話の状態を、止める前に保存し、起動した後に戻す（2026-11-14）。
# Save the conversation state of a Strata server before it stops and restore it after it starts.
# 起動し直しのたびに会話を頭から読み直すのを避ける（4.4 万トークンで読み直し 115 秒 → 復元 1 秒）。
# systemd の drop-in（30-session.conf.example）の ExecStop と ExecStartPost から呼ぶ。失敗しても起動と停止は止めない。
# Needs patch 0001 (session files with a layer split) and the server's slot_save_path set to $D.
U=${STRATA_URL:-http://127.0.0.1:8741}
F=${STRATA_SESSION_FILE:-session.bin}
D=${STRATA_SESSION_DIR:-/var/lib/strata/sessions}
log(){ echo "strata-session: $*"; }
tokens(){ curl -s -m 5 $U/slots | sed -n "s/.*\"n_prompt_tokens\": *\([0-9]*\).*/\1/p"; }
case "$1" in
save)
  n=$(tokens); [ -z "$n" ] && { log "save: 推論機が答えない"; exit 0; }
  [ "$n" -lt 4000 ] && { log "save: 会話が短い（$n トークン）ので保存しない"; exit 0; }
  r=$(curl -s -m 70 -X POST -H "Content-Type: application/json" -d "{\"filename\":\"$F\"}" "$U/slots/0?action=save")
  log "save: $n トークン → $(echo "$r" | cut -c1-200)"
  ;;
restore)
  [ -f "$D/$F" ] || { log "restore: 保存が無い"; exit 0; }
  [ -n "$(find "$D/$F" -mtime +7)" ] && { log "restore: 保存が 7 日より古いので戻さない"; exit 0; }
  i=0; while [ $i -lt 60 ]; do curl -s -m 3 $U/health | grep -q "\"loaded\": true" && break; i=$((i+1)); sleep 3; done
  [ $i -ge 60 ] && { log "restore: 推論機が 3 分で立ち上がらなかった"; exit 0; }
  n=$(tokens); [ "${n:-0}" -gt 0 ] && { log "restore: もう会話が始まっている（$n トークン）ので戻さない"; exit 0; }
  r=$(curl -s -m 120 -X POST -H "Content-Type: application/json" -d "{\"filename\":\"$F\"}" "$U/slots/0?action=restore")
  log "restore: $(echo "$r" | cut -c1-200)"
  ;;
esac
exit 0
