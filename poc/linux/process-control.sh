#!/usr/bin/env bash

# 由调用脚本 source；使用独立进程组保证 npm/tsx/浏览器子进程一并收口。
BOUNDED_RUNNER_PID=""
BOUNDED_WATCHDOG_PID=""

bounded_process_group_alive() {
  local process_group_id="${1:-}"
  [[ "$process_group_id" =~ ^[0-9]+$ ]] && kill -0 -- "-$process_group_id" 2>/dev/null
}

terminate_bounded_process_group() {
  local process_group_id="${1:-}"
  local kill_after_seconds="${2:-1}"
  bounded_process_group_alive "$process_group_id" || return 0
  kill -TERM -- "-$process_group_id" 2>/dev/null || true
  sleep "$kill_after_seconds"
  if bounded_process_group_alive "$process_group_id"; then
    kill -KILL -- "-$process_group_id" 2>/dev/null || true
  fi
}

start_bounded_process() {
  local timeout_seconds="$1"
  local kill_after_seconds="$2"
  shift 2
  command -v setsid >/dev/null 2>&1 || {
    echo "ERROR: 缺少 setsid，不能保证候选进程树有界退出" >&2
    return 127
  }
  setsid "$@" &
  BOUNDED_RUNNER_PID=$!
  (
    sleep "$timeout_seconds"
    if bounded_process_group_alive "$BOUNDED_RUNNER_PID"; then
      echo "bounded_timeout_seconds=$timeout_seconds;action=term_process_group" >&2
      kill -TERM -- "-$BOUNDED_RUNNER_PID" 2>/dev/null || true
      sleep "$kill_after_seconds"
      if bounded_process_group_alive "$BOUNDED_RUNNER_PID"; then
        echo "bounded_kill_after_seconds=$kill_after_seconds;action=kill_process_group" >&2
        kill -KILL -- "-$BOUNDED_RUNNER_PID" 2>/dev/null || true
      fi
    fi
  ) &
  BOUNDED_WATCHDOG_PID=$!
}

wait_bounded_process() {
  local status=127
  if [[ "$BOUNDED_RUNNER_PID" =~ ^[0-9]+$ ]]; then
    wait "$BOUNDED_RUNNER_PID"
    status=$?
  fi
  if [[ "$BOUNDED_WATCHDOG_PID" =~ ^[0-9]+$ ]]; then
    kill "$BOUNDED_WATCHDOG_PID" 2>/dev/null || true
    wait "$BOUNDED_WATCHDOG_PID" 2>/dev/null || true
  fi
  # 入口进程正常退出后仍清理同组残留的 npm/tsx/浏览器子进程。
  terminate_bounded_process_group "$BOUNDED_RUNNER_PID" 1
  BOUNDED_RUNNER_PID=""
  BOUNDED_WATCHDOG_PID=""
  return "$status"
}

stop_bounded_process() {
  terminate_bounded_process_group "$BOUNDED_RUNNER_PID" 1
  if [[ "$BOUNDED_WATCHDOG_PID" =~ ^[0-9]+$ ]]; then
    kill "$BOUNDED_WATCHDOG_PID" 2>/dev/null || true
  fi
}

run_bounded_process() {
  local timeout_seconds="$1"
  local kill_after_seconds="$2"
  shift 2
  start_bounded_process "$timeout_seconds" "$kill_after_seconds" "$@" || return $?
  wait_bounded_process
}
