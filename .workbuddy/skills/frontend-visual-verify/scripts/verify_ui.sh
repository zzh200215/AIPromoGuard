#!/usr/bin/env bash
# ============================================================
# 一键前端视觉验证（agent-browser + dev-mock）
#
# 用法:
#   bash verify_ui.sh [输出目录] [页面路径...]
#   bash verify_ui.sh docs/ui-verify-2026-10-07 /dashboard /tasks
#
# 行为:
#   1. 检查 preview(5173) 与 mock(8000) 是否在跑，未跑则后台启动
#   2. agent-browser 登录（mock 下任意账号密码可登录）
#   3. 逐页截图（含入场动画等待）到输出目录
#   4. 关闭浏览器
#
# 前置: npm install -g agent-browser && agent-browser install
# 说明: 所有 agent-browser 命令都用 timeout 包一层——首次 open 会因 daemon
#       冷启动握手长时间挂起，这是本机实测过的坑。
# ============================================================
set -u

PROJ_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
FRONTEND="$PROJ_ROOT/frontend"
OUT_DIR="${1:-$PROJ_ROOT/docs/ui-verify-$(date +%Y-%m-%d)}"
shift || true
PAGES=("$@")
if [ ${#PAGES[@]} -eq 0 ]; then
  PAGES=(/dashboard /tasks)
fi

SHOT_TMP=/tmp/fcr-shots
mkdir -p "$OUT_DIR" "$SHOT_TMP"

echo "[1/4] 检查服务..."
started_mock=0
if ! curl -s -o /dev/null "http://localhost:5173/" 2>/dev/null; then
  echo "  preview 未运行，启动中（日志 /tmp/fcr-preview.log）..."
  (cd "$FRONTEND" && npm run preview > /tmp/fcr-preview.log 2>&1 &)
  sleep 12
fi
if ! curl -s "http://localhost:5173/api/v1/health" 2>/dev/null | grep -q '"code"'; then
  echo "  mock API 未运行，启动中（日志 /tmp/fcr-mock.log）..."
  (cd "$FRONTEND" && node dev-mock.mjs > /tmp/fcr-mock.log 2>&1 &)
  started_mock=1
  sleep 4
fi

echo "[2/4] 打开浏览器并登录..."
timeout 90 agent-browser open http://localhost:5173 || { echo "open 失败（重试一次）"; timeout 90 agent-browser open http://localhost:5173; }
timeout 40 agent-browser set viewport 1440 900   # 注意：viewport 是 set 的子命令，非顶层
sleep 2
# 用稳定的 CSS 选择器，不依赖 snapshot 的动态 ref
timeout 40 agent-browser fill 'input[placeholder="用户名"]' "admin"
timeout 40 agent-browser fill 'input[type="password"]' "admin123"
timeout 40 agent-browser click 'button.el-button--primary'
sleep 5
echo "  当前路径: $(timeout 40 agent-browser eval 'location.pathname')"

echo "[3/4] 逐页截图..."
i=0
for page in "${PAGES[@]}"; do
  i=$((i + 1))
  name=$(echo "$page" | sed 's#^/##; s#/#-#g')
  [ -z "$name" ] && name="root"
  if [ "$page" != "/dashboard" ]; then
    timeout 60 agent-browser open "http://localhost:5173$page" || true
  fi
  sleep 4  # 入场动画 + 数据加载（过早截图会拍到动画中间态）
  out="$SHOT_TMP/verify-$i.png"
  timeout 60 agent-browser screenshot --screenshot-dir "$SHOT_TMP" > /dev/null || true
  latest=$(ls -t "$SHOT_TMP"/*.png 2>/dev/null | head -1)
  if [ -n "$latest" ]; then
    cp "$latest" "$OUT_DIR/$(printf '%02d' "$i")-$name.png"
    echo "  ✓ $OUT_DIR/$(printf '%02d' "$i")-$name.png"
  else
    echo "  ✗ $page 截图失败"
  fi
done

echo "[4/4] 收尾..."
timeout 30 agent-browser close > /dev/null 2>&1 || true
if [ "$started_mock" = "1" ]; then
  echo "  提示: mock API 是本脚本启动的，如不再需要可手动停止（任务列表里结束对应进程）"
fi
echo "完成。请用 Read 工具逐张查看截图做视觉检查。"
