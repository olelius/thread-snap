#!/usr/bin/env bash
set -euo pipefail

target_pid="$1"
output="$2"
interval="${3:-5}"
printf 'timestamp,pid_count,browser_process_count,total_cpu_percent,total_rss_kb\n' > "$output"

while kill -0 "$target_pid" 2>/dev/null; do
  family=" $target_pid "
  changed=1
  while [[ "$changed" == 1 ]]; do
    changed=0
    while read -r pid ppid; do
      [[ -n "$pid" ]] || continue
      if [[ "$family" == *" $ppid "* && "$family" != *" $pid "* ]]; then
        family+="$pid "
        changed=1
      fi
    done < <(ps -eo pid=,ppid=)
  done
  metrics="$(ps -eo pid=,comm=,%cpu=,rss= | awk -v family="$family" '
    index(family, " " $1 " ") { count++; cpu += $3; rss += $4; if ($2 ~ /(chrome|chromium)/) browsers++ }
    END { printf "%d,%d,%.2f,%d", count+0, browsers+0, cpu+0, rss+0 }
  ')"
  printf '%s,%s\n' "$(date --iso-8601=seconds)" "$metrics" >> "$output"
  sleep "$interval"
done
