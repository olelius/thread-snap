# WORKLOG — 唯一任务账本

<!--
规则：
1. 仓库只保留这一份活动任务账本；最新条目永远放在最上方。
2. 动代码必须更新条目；纯讨论、调研或未改代码的任务不记。
3. 每条只保留总目标、当前状态、验证证据、下一步和必要边界。
4. 上下文压缩、新会话或任务恢复后，先读最新条目，不重查其中已有可复核证据的事实。
5. 详细规范、决策和长日志分别归入 owner 文档、ADR 或被忽略的 runtime artifact，不复制到这里。
-->

## ⏳ 待你裁决

- 2026-08-17：最终服务器存在一块无文件系统、未挂载的 3.6 TiB `/dev/sdb`；格式化并挂载到 `/data` 会清除该设备现有内容，须由用户明确决定后执行。
- 2026-08-17：服务器 `80/443` 已由 `wenmai-nginx-1` 占用；ThreadSnap 首次安装使用独立 `8088` 可避免影响现有服务，是否接入既有 Docker Nginx 和正式域名仍待用户决定。

---

## 2026-08-18 — 提取列表展示并筛选列表类型
**总目标**：让批次列表明确区分来源冻结的“最新回复”和“最新发布”，并支持按该业务维度筛选完整结果集。
**状态**：✅ 提取范围显示独立列表类型标签，筛选由后端按 `list_order` 执行。
**干到哪里了**：
- [x] 批次摘要新增去重后的 `list_orders` 与中文 `list_order_names`，来源名称不再承担表达列表类型的职责。
- [x] `/api/v1` 与 `/internal/v1` 提取列表新增 `list_order` 查询条件，通过来源任务存在性筛选批次；URL 清单不归入最新回复或最新发布。
- [x] 提取列表新增“全部列表类型 / 最新回复 / 最新发布”筛选，筛选状态进入 URL；提取范围在平台名称旁显示短标签。
- [x] 新增接口回归测试覆盖两种列表类型及 URL 清单排除；60 项后端测试、正式代码 Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建、`git diff --check` 通过。
- [x] 本地真实接口确认 9 个现有批次均正确标记为最新回复；真实浏览器确认标签、筛选空结果和 1280px 两行响应式筛选布局生效。
**下一步**：后续产生最新发布批次后，列表会直接显示“最新发布”并可由同一筛选入口查询。
**边界**：不修改数据库结构，不从可编辑来源名称推断列表类型；含多来源的批次按实际包含的列表类型去重展示，筛选语义为“包含该类型”。
**关联**：`docs/design/product-design.md`、`src/threadsnap/app.py`、`src/threadsnap/services.py`、`frontend/src/features/runs/runs-page.tsx`、`tests/test_backend.py`

## 2026-08-18 — 修复圈子采集误传圈子 ID
**总目标**：修复最新回复/最新发布重构后，圈子正式采集把圈子 ID 误传给 URL 解析器，导致已验证来源执行时立即报 `CIRCLE_URL_INVALID`。
**状态**：✅ 最新回复和最新发布正式采集均传递规范化完整来源 URL。
**干到哪里了**：
- [x] 确认失败批次 `20260818-112213-001` 的任务快照和当前来源配置 URL 均合法，根因不是用户配置或平台会话。
- [x] `collect_circle()` 改为复用 `parse_circle_url()` 的 `CircleSource`，并把 `source.url` 传给 `_fetch_circle_page()`，不再传裸圈子 ID。
- [x] 回归测试同时覆盖最新回复分页和最新发布来源 URL，防止 mock 忽略参数再次漏检。
- [x] 59 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建、`git diff --check` 通过；本地后端已重启且健康。
**下一步**：在页面对原失败批次使用“重新提取失败项”创建关联新批次；原失败批次保持不变。
**边界**：不修改或重跑原失败批次，不自动发起平台请求；只修复后续新批次和补提的正式采集参数。
**关联**：`src/threadsnap/collectors/dongchedi.py`、`tests/test_backend.py`

## 2026-08-18 — 用户可见时间统一显示北京时间
**总目标**：修复 SQLite 丢失 UTC 时区标识后，提取列表等页面把 UTC 钟面值直接显示、较北京时间少 8 小时的问题。
**状态**：✅ 数据库继续按 UTC 存储，API 时间带 UTC 标识，前端统一按 `Asia/Shanghai` 显示。
**干到哪里了**：
- [x] 新增统一 `UTCDateTime` ORM 类型：写入时归一化 UTC，SQLite 读取历史及新增无时区值时恢复 UTC；所有持久化时间字段采用同一边界，不只修提取列表。
- [x] `/api/v1` 与 `/internal/v1` 通过现有共享服务返回带 `Z` 或 `+00:00` 的 RFC 3339 时间；前端现有 `formatDate` 据此完成 UTC 到北京时间转换，不依赖部署服务器或浏览器系统时区。
- [x] 新增 SQLite 往返回归测试；58 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建通过。
- [x] 本地真实数据验证：批次 `20260818-112213-001` 的 API 创建时间为 `2026-08-18T03:22:13.496692Z`，页面显示 `2026/08/18 11:22:13`，不再显示错误的 `03:22:13`。
**下一步**：后续新增时间字段继续使用 `UTCDateTime`，接口保留明确时区标识，页面统一按产品时区展示。
**边界**：不改写数据库现有时间数值，也不改变批次编号或定时计划语义；本次不需要数据库结构迁移。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`src/threadsnap/db.py`、`src/threadsnap/models.py`、`tests/test_backend.py`

## 2026-08-18 — 导出模板使用全平台统一 10 位来源键
**总目标**：继续缩短 XLSX 模板标签，并保证现在及以后接入的平台始终共用同一套字段规则。
**状态**：✅ 模板只生成并解析 `s.<10位来源键>.<字段>`；来源键跨平台全局唯一，字段后缀注册表不区分平台。
**干到哪里了**：
- [x] `circles.export_key` 在来源创建时生成并持久化，使用排除易混字符的 10 位键；数据库唯一约束覆盖全部平台，标签不再编码平台代码、来源 UUID 或可修改名称。
- [x] 所有平台继续共用一份 `FIELD_REGISTRY`；新增跨平台回归测试，确认懂车帝与汽车之家来源得到不同短键、相同字段集合和相同 `s.<key>.<field>` 结构。
- [x] 新迁移 `d4c8a7e91f02` 已在真实数据库副本完成“升级 → 降级 → 再升级”：15/15 来源键非空、互异且固定 10 位，重复键写入被唯一约束拦截；真实数据库升级前备份 SHA-256 为 `6FC1EBD0003287BCCCF54E9B927E7B715504D826BE81EB0E6C5F6C35ED78B33F`。
- [x] 57 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建通过；真实浏览器确认 22 个标签均使用新格式，首项 `s.8mb8d48x29.name`，页面不存在 22 位旧格式或平台代码前缀。
- [x] 真实页面 892px 标签表格的 `clientWidth` 与 `scrollWidth` 均为 892px，短标签完整显示且没有横向溢出；真实数据库当前版本为 `d4c8a7e91f02`，15 个来源键全部非空、互异且为 10 位。
**下一步**：后续平台适配器只映射统一字段语义；平台暂时缺少的字段留空，不新增平台专属标签格式。
**边界**：不兼容 22 位来源键或更早的长标签；按已确认的正式数据清理安排，清理后模板必须从当前页面重新复制标签。本次迁移不直接清理现有业务数据。
**关联**：`docs/adr/0021-persist-platform-neutral-export-keys.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`、`src/threadsnap/migrations/versions/d4c8a7e91f02_circle_export_key.py`、`src/threadsnap/templates.py`

## 2026-08-18 — 导出模板改用纯短来源标签
**总目标**：移除导出模板页过时的 `vehicle.name` 字段和包含平台代码、36 位来源 UUID 的冗长标签，改为可读且稳定的短来源标签。
**状态**：✅ 新模板只生成并解析 `source.<22位来源键>.<字段>`，不保留旧字段或旧标签兼容分支。
**干到哪里了**：
- [x] 来源 UUID 完整转换为 22 位 URL-safe Base64 短键，可逆还原且不采用可能碰撞的截断摘要；来源名称标签由 `platform.dongchedi.source.<uuid>.source.name` 缩短为 `source.<source_key>.name`。
- [x] 删除 `vehicle.name` 注册字段、旧 `platform.*.source.*` 与 `platform.*.circle.*` 解析分支；按用户确认的“正式数据会清除”边界，同步简化模板绑定与导出，只按全局唯一来源 ID 寻址。
- [x] 可用字段列表优先展示来源名称和列表顺序中文名称，表头改为“模板标签”，标签支持自然换行；前端请求只提交来源 ID，不再携带标签寻址不需要的平台代码。
- [x] 56 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建通过；模板测试额外确认短键可逆、短标签导出成功、旧长标签被拒绝。
- [x] 隔离后端与真实浏览器页面确认共 22 个字段，首项为 `source.<source_key>.name`，页面不含 `vehicle.name` 或 `platform.` 前缀；最长标签 57 字符，892px 表格视口无横向溢出。
**下一步**：数据清理后重新创建导出模板，统一从页面复制当前短标签，不复用清理前模板文件。
**边界**：不在本次任务中直接清理当前开发数据库或模板文件；不新增来源别名列，不以可修改的来源名称充当寻址键。
**关联**：`docs/adr/0020-use-short-source-keys-in-xlsx-tags.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`、`src/threadsnap/templates.py`、`frontend/src/features/config/config-page.tsx`

## 2026-08-18 — 规则来源按列表顺序二级折叠
**总目标**：把自动提取规则中同一平台的最新回复与最新发布来源从混排列表改为可辨识、可批量操作的二级分组。
**状态**：✅ 平台、列表顺序和来源三级层次已落地，分类全选与原有草稿语义保持一致。
**干到哪里了**：
- [x] 规则来源选择器改为“平台 → 最新回复/最新发布 → 来源”；平台与列表顺序标题分别显示已选数/总数，列表顺序层提供独立全选和半选状态。
- [x] 最内层来源行移除重复的列表顺序徽标，只保留来源名称与复选框；有已选来源的分类默认展开，未选分类保持收起以控制纵向密度。
- [x] 分类全选继续复用平台数量创建和清理规则，字段级 dirty、规则汇总、保存与放弃修改均保持原语义。
- [x] 前端 TypeScript 检查、生产构建和 `git diff --check` 通过；真实页面确认最新回复 `13/14`、最新发布 `0/1` 两个分类及其独立全选可见，临时全选最新发布后分类变为 `1/1`、平台变为 `14/15`，放弃修改后恢复 `0/1` 且保存按钮禁用，未提交测试草稿。
**下一步**：后续新增其他列表顺序时扩展统一分组元数据，不在来源行重新堆叠类型徽标。
**边界**：只调整规则页来源选择器的信息层次和范围全选，不改变规则存储结构、平台统一目标数、调度、批次或来源配置。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-18 — 来源列表滚动区占满剩余高度
**总目标**：修复“来源与圈子”桌面页由固定视口比例造成外层标签页滚动、列表内部高度未占满的问题。
**状态**：✅ 桌面端列表已改为占满工具栏和验证提示以下的剩余高度，并只保留列表内部滚动。
**干到哪里了**：
- [x] 确认根因是列表容器固定使用 `max-h-[min(65svh,680px)]`，同时标签页自身 `overflow-y-auto`，两层高度没有组成完整的 Flex 收缩链。
- [x] 1280px 及以上将来源面板、标签内容和列表视口串成 `h-full/min-h-0/flex-1`；较窄视口继续保留原有最大高度和顺序滚动回退。
- [x] 前端 TypeScript 检查、生产构建和 `git diff --check` 通过；真实 1280×720 页面测得标签面板 `clientHeight=scrollHeight=437`、外层不滚动，列表视口底部与面板底部间距为 0，列表内部 `clientHeight=297`、`scrollHeight=835`，内部滚动有效。
**下一步**：后续配置页新增长列表时复用同一“固定工具栏 + 剩余高度列表视口”布局，不再叠加独立 `svh` 最大高度与外层滚动。
**边界**：只调整来源列表桌面端高度和滚动归属，不改变表格字段、行高、移动端回退、数据读写或验证操作。
**关联**：`docs/design/product-design.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-18 — 区分同圈最新回复与最新发布来源
**总目标**：允许同一平台圈子分别保存“最新回复”和“最新发布”来源，使用用户填写的来源名称区分批次范围，补齐来源级导出字段，并修复他人保存配置后清洁本地草稿被误标为未保存的问题。
**状态**：✅ 来源复合校验、真实列表验证、来源展示、XLSX 来源字段和服务器基线同步均已完成。
**干到哪里了**：
- [x] 懂车帝来源解析同时支持 `/community/<id>` 与 `/community/<id>/dongtai-release` 及各自分页；来源唯一性改为“平台 + 圈子 ID + 版块 + 列表顺序”，既有数据和历史任务迁移为 `latest_reply`。
- [x] 使用当前加密 Session 对圈子 `24729` 执行只读验证：两个入口均返回 30 条，前五个帖子顺序不同，分别识别为 `latest_reply` 和 `latest_publish`；证据位于被忽略的 `artifacts/runtime/circle-feed-sources/real-feed-verification.json`。
- [x] 配置页将“车型”改为“来源名称”，单独显示列表顺序和平台圈子名称；规则、批次列表、批次详情和帖子详情优先展示任务创建时冻结的来源名称，不再用重复的平台圈子名称充当提取范围。
- [x] 新 XLSX 标签使用稳定来源配置 ID，并新增 `source.id`、`source.name`、`source.list_order`、`source.list_order_name`；旧 `circle.<external_id>` 标签继续兼容读取。
- [x] 提取计划 SSE 刷新改为相对旧服务器基线判断本地编辑；双页面实测确认无本地编辑时自动采用远端版本且保存按钮禁用，有本地草稿时保留草稿，放弃后采用最新服务器版本。测试用规则名称已恢复。
- [x] 真实数据库已在备份后升级到 `b73a1d6c42ef`；备份 SHA-256 为 `A84B0135BB0832B592B501F30B4BCD9B868B3358A2A16EF051A84B9066C4C13D`。55 项后端测试、Ruff、前端类型检查与生产构建、`compileall`、`pip check`、`git diff --check` 全部通过。
**下一步**：后续新增来源时分别填写可辨识的来源名称和对应列表 URL；若模板需要区分同圈两类来源，使用新的 `source.<source_id>` 标签和 `source.*` 字段，不再新建旧式圈子 ID 标签。
**边界**：不改写历史批次快照，不把两类来源归并为同一来源；本次不新增批次分组开关或另一套采集流程，既有自动规则、调度和手动提交流程保持不变。
**关联**：`docs/adr/0019-distinguish-circle-feed-sources-and-live-baselines.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/templates.py`、`frontend/src/features/config/config-page.tsx`

## 2026-08-18 — 恢复懂车帝普通动态正文提取
**总目标**：修复富文本标准化后普通动态把整段 `motor_title` 误存为标题、正文为空的回归，同时保留富文本标题与 HTML 正文分离能力。
**状态**：✅ 字段存在性分流、适配器版本、解析测试、快照持久化测试和真实样本复核均已完成。
**干到哪里了**：
- [x] 确认修复前批次正文空值为 0，`dongchedi-dynamic-v2` 生成的批次 `20260817-153109-001` 在 420 条中有 412 条正文为空；目标帖子 `7674878578118377534` 的平台响应为 `thread_title/content` 空、264 字 `motor_title` 和 4 张图片，数据库此前把整段文字写入标题并把正文保存为 `NULL`。
- [x] 适配器升级为 `dongchedi-dynamic-v3`：平台 `content` 有值时保留“`motor_title` 标题 + 标准化 `content` 正文”，`content` 为空时把 `motor_title` 恢复为正文并按平台明确标题或正文第一句生成标题；不依赖文章子类型、字数或标点阈值。
- [x] 新增普通动态解析、平台明确标题、纯媒体空正文和 Worker 持久化回归测试；既有富文本 HTML 清理测试继续通过，隔离数据库确认正文和首句标题进入不可变 `PostSnapshot` 后由详情查询原样返回。
- [x] 使用当前加密 Session 对两个真实帖子各执行一次只读详情验证：普通动态得到 264 字正文和首句标题，富文本帖子保留“我和qq3的故事～”标题、232 字无 HTML 正文；未写入真实业务批次。
- [x] 52 项测试、修改文件 Ruff format、`src/tests` Ruff check、`compileall`、`pip check` 和 `git diff --check` 通过。
**下一步**：后续新批次自动使用 v3 映射；历史批次保持不可变，如需页面出现修复后的正文，应重新执行对应提取规则生成新批次，不直接覆写旧快照。
**边界**：不修改批次 `20260817-153109-001` 的历史数据，不改变圈子发现、评论、媒体 URL、成功判定、前端展示或导出契约。
**关联**：`docs/design/product-design.md`、`src/threadsnap/collectors/dongchedi.py`、`tests/test_backend.py`

## 2026-08-17 — 修正 CentOS Stream 10 显示后端并实装最终服务器
**总目标**：在最终 CentOS Stream 10 x86_64 服务器完成 ThreadSnap 前后端部署，并修复完整离线包在真实安装中发现的系统依赖、路径、SELinux 和运行依赖缺陷。
**状态**：✅ 干净提交生成的完整离线包已在最终服务器安装，前端、API、数据库、Wayland Chromium 和专用 Nginx 均通过完整运行验证。
**干到哪里了**：
- [x] 最终主机确认 12 核、15 GiB 内存、7.8 GiB Swap、CentOS Stream 10 x86_64、Python 3.12.13；程序使用 `/opt/threadsnap`，配置使用 `/etc/threadsnap`，数据使用 `/var/lib/threadsnap`。未挂载且无文件系统的 3.6 TiB `/dev/sdb` 保持不变。
- [x] CentOS 10 已由 Xvfb 修正为 Weston 无头 Wayland；`threadsnap-wayland.service` 稳定创建私有 `wayland-99`，Patchright Chromium 149 以 `headless=False` 完成页面渲染冒烟。
- [x] 真实安装暴露并修复：DNF 强制安装全部递归 RPM 导致系统版本冲突、`/etc/os-release` 覆盖应用版本、暂存 venv 控制台脚本绝对 shebang、缺失 `scrapling[fetchers]` 运行依赖、环境模板 CRLF 污染 HOME、SELinux 将后端误标为静态内容、非标准 HTTP 端口未标记。
- [x] RPM 目录现生成 `createrepo_c` 本地仓库元数据并用 `SYSTEM-PACKAGES.txt` 只请求顶层组件；Python 依赖补齐 `curl-cffi==0.16.0`、`playwright==1.61.0` 与 `scrapling[fetchers]==0.4.12`。
- [x] 新增独立 `threadsnap-nginx.service` 与 `/etc/threadsnap/nginx.conf`，使用 `8088` 避开现有 Docker Nginx 的 `80/443`；既有 `wenmai`、Redis 和 PostgreSQL 容器均保持运行。
- [x] 服务器完整验证通过：三个 ThreadSnap 服务均 `active/enabled`，直连与 Nginx `/health`、SPA、`/internal/v1` 屏蔽、8000 回环绑定、CDP 关闭、Fernet 配置及 Wayland Chromium 全部 PASS。
- [x] SQLite 已自动初始化为 `threadsnap:threadsnap 0600`，共 20 张表，Alembic 版本 `a91c4e7d2f10`；环境文件为 `root:threadsnap 0640`。
- [x] 端口 `8088` 的 firewalld 规则只放行当前 SSH 客户端来源；服务器本机完整 HTTP 验证通过，客户端直连仍未形成 Nginx 访问日志，外部链路还需结合云安全组/运营商链路复核。
- [x] 包内本地 RPM 仓库已在最终服务器实跑，DNF 对全部顶层组件报告无需处理且未触发系统升级；同时修正组装器在 `pipefail` 下以 `tar | grep -q` 校验归档导致 SIGPIPE 假失败的问题。
- [x] 升级路径改为切换 `current` 后显式依次重启 Wayland、后端和专用 Nginx，避免 `enable --now` 对既有服务不重启而让健康检查误验旧 release。
- [x] 从干净提交 `1bc2916dae46b7ca6d8dc84316a60887b2c50139` 生成最终包 `/var/tmp/threadsnap-upload-final/threadsnap-0.1.0-centos-stream-10-x86_64-offline.tar.gz`，大小 `590416473` 字节，SHA-256 为 `1e4a948b390b5aeabf35d9dbc4bb43f554c54e8b971f5f89ff650e424894acc6`；manifest 确认 `fully-offline`、可安装、源码未脏且不含凭证，包内含 50 个 wheel、481 个 RPM 和 311 个浏览器文件。
- [x] 最终 release `/opt/threadsnap/releases/0.1.0-1bc2916dae46` 已通过 `deploy/verify.sh` 全量检查；三个服务均 `active/enabled`，后端仅监听 `127.0.0.1:8000`，专用 Nginx 监听 `0.0.0.0:8088`，现有 `wenmai` Docker 容器及其 `80/443`、Redis、PostgreSQL 端口保持运行。
- [x] 删除服务器旧制包、旧上传和显示测试缓存后，根卷占用从 22 GiB 降至 18 GiB；只保留最终归档及校验文件，已安装 release、配置和数据库不受影响。
- [x] 本轮完整测试 48 项通过；Ruff、compileall、pip check、全部 Linux shell `bash -n` 和 `git diff --check` 通过。
**下一步**：由用户确认云安全组或上游网络是否放行来源 `221.235.64.137/32` 到 TCP `8088`，并决定正式域名/既有反代接入以及 3.6 TiB `/dev/sdb` 的用途；部署链完成后继续执行暂缓的连续三轮 2000 URL 验收。
**边界**：不格式化 `/dev/sdb`；不停止或改写现有 Docker 服务；不把首次失败包或现场手工补丁记为最终交付包；当前只证明部署与运行链通过，不把暂缓的连续三轮 2000 URL 门禁记为完成。
**关联**：`docs/adr/0018-use-headless-wayland-on-centos-stream-10.md`、`docs/deployment/linux-v1.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`、`deploy/linux/`、`pyproject.toml`

## 2026-08-17 — 第一版 Linux 完整离线部署封装
**总目标**：为全新 CentOS Stream 10 服务器提供前后端完整离线部署包、明确的磁盘与目录选择、systemd/Xvfb/Nginx 配置，以及可复核的安装、验证、备份和回滚流程。
**状态**：🟡 Windows 侧制包输入、完整离线组装器和目标机纯离线安装链已实现并通过本地构建与静态契约验证；最终 `fully-offline` 包仍须在兼容 CentOS 制包机组装，随后进入目标主机实装与三轮门禁。
**干到哪里了**：
- [x] 确认正式目标包内置 Python wheelhouse、锁定 Patchright 对应的 Linux Chromium，以及 Python、Nginx、Xvfb 和浏览器共享库 RPM；目标机固定使用 `pip --no-index` 与 `dnf --disablerepo='*'`，不在安装阶段访问 PyPI、浏览器源或 DNF 仓库。
- [x] 新增主机只读探测脚本，统一输出发行版、CPU、内存、`lsblk`、`findmnt`、空间、inode、监听端口、SELinux 与防火墙状态；程序固定使用 `/opt/threadsnap/releases`，配置使用 `/etc/threadsnap`，持久数据默认使用 `/var/lib/threadsnap`，发现独立数据盘时可通过 `--data-dir /data/threadsnap` 切换。
- [x] 新增兼容 Linux 离线组装器、目标机安装器、RPM 本地安装、Fernet 首次生成与升级保留、原子 release/previous 链接、SELinux 处理、systemd 单应用进程、独立 Xvfb、Nginx SPA/API/SSE/WebSocket 与 `/internal/v1` 屏蔽配置。
- [x] 新增部署验证、停服一致性备份、带校验和路径防护的数据恢复、程序级回滚与失败自动恢复；修正 `.env.example` 的认证浏览器模式为 `false`，与源码默认值及 Linux Xvfb 口径一致。
- [x] `scripts/build-linux-deployment-package.ps1 -Version 0.1.0 -AllowDirty` 已在隔离前端目录完成 `npm ci`、TypeScript 检查、2465 modules 生产构建和后端 wheel 构建，生成本地 `artifacts/releases/threadsnap-0.1.0-linux-builder.tar.gz`；开发包 manifest 明确 `source_dirty=true`、`installable=false`，没有伪装为最终 Linux 包。
- [x] 所有 Linux shell 文件通过 Git Bash `bash -n`，PowerShell 制包脚本通过 AST 解析，部署静态契约测试 8/8 通过，覆盖完整离线边界、Chromium/RPM/wheel 收集、Nginx 内部接口与流式代理、单进程/Xvfb、配置一致性和无真实密钥模板。
**下一步**：提交后从干净 Git 基线重建最终 builder 输入包；在与目标服务器相同的 CentOS Stream 10 x86_64/Python 次版本制包机执行 `deploy/assemble-offline-package.sh`，取得含 `wheelhouse/`、`browsers/`、`rpms/` 和 SHA-256 的正式离线包，再先运行 `inspect-host.sh` 决定 `/var/lib` 或独立数据盘，随后实装并完成 Xvfb 认证、重启、备份恢复和连续三轮 2000 URL 验收。
**边界**：本条完成的是可复核的部署封装与制包链，不把 Windows 生成的 builder 输入包记为 Linux 可安装包，也不把尚未执行的 CentOS 离线组装、目标机认证或三轮吞吐记为通过；部署包不含 `.env`、数据库、Fernet 密钥、Cookie、storage state、认证 Profile 或原始 PoC 输入。
**关联**：`docs/adr/0017-package-v1-as-fully-offline-systemd-nginx-release.md`、`docs/deployment/linux-v1.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`、`deploy/linux/`、`scripts/build-linux-deployment-package.ps1`、`tests/test_linux_deployment_package.py`

## 2026-08-17 — 帖子查看标识改为推入推出
**总目标**：修复批次结果行的“当前查看/刚刚查看”标签消失时只淡出并瞬间释放布局宽度，导致帖子标题直接跳位的问题。
**状态**：✅ 标识与标题间距已改为同步横向推入推出，生产构建和真实页面关键帧验证通过。
**干到哪里了**：
- [x] 确认根因不是透明度过渡本身，而是条件卸载时标签宽度、标签右间距和高亮态左内边距同时瞬间归零；单独增加位移动画仍会让标题跳动。
- [x] 使用同一个布局感知标识承接“当前查看”到“刚刚查看”的状态切换；进入和退出同步过渡标签宽度、右间距、轻微横移、透明度及标题容器左内边距，标签卸载后不再发生第二次位移。
- [x] 移除旧的标签 CSS 淡出动画，保留行面与左侧光晕的 1.8 秒定位反馈；启用 `prefers-reduced-motion` 时以零时长立即切换。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2465 modules）和 `git diff --check` 通过；真实页面打开 Sheet 后显示“当前查看”，关闭后显示“刚刚查看”，退出关键帧中标签宽度 `58 → 57.1 → 13.4 → 3.8 → 0.3 → 0`，标题横坐标 `409 → 407.9 → 350.9 → 338.2 → 333.4 → 333` 连续跟随，最终卸载没有二次跳位，控制台错误为 0。
**下一步**：继续第一版 Linux 部署门禁；后续内联状态标签若会增删布局空间，必须同时过渡自身尺寸和相邻内容间距，不能只做透明度或 transform。
**边界**：本次只调整批次结果行查看状态的前端动效，不修改 Sheet 数据、URL 状态、定位时长、表格字段或后端接口。
**关联**：`docs/design/product-design.md`、`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/styles/index.css`

## 2026-08-17 — 修复车型名称恢复原值后仍显示修改
**总目标**：修复车型与圈子页的车型名称输入框在追加字符并删除回原文本后，字段、行和标签仍保持未保存状态的问题。
**状态**：✅ 隐藏关联字段的恢复逻辑已修复，输入恢复原值后的四层 dirty 状态均通过真实页面验证归零。
**干到哪里了**：
- [x] 确认文本比较本身正确；根因是车型名称每次输入都会把隐藏的 `vehicle_id` 清为 `undefined`，删除字符恢复名称后只恢复了可见文本，规范化行签名仍因 `vehicle_id` 不同而判定有修改。
- [x] 车型名称偏离服务端基线时继续解除旧 `vehicle_id` 关联，以支持重新分配车型；输入值精确回到基线名称时同步恢复基线 `vehicle_id`，不会把真实改名误判为未修改。
- [x] 静态复查其余配置输入的更新路径：规则名称、圈子 URL、平台并发、计划时间均不附带这种不可逆隐藏字段清空；同页 URL 输入的追加/删除恢复路径也已真实验证。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2465 modules）和 `git diff --check` 通过；真实页面把首行车型从 `A9L` 改为 `A9LX` 时字段、行、标签和保存按钮进入 dirty，删除 `X` 回到 `A9L` 后 dirty 字段数、dirty 行数和标签圆点均为 0，保存与放弃按钮恢复禁用，测试草稿未提交。
**下一步**：继续第一版 Linux 部署门禁；后续输入控件若联动隐藏标识，恢复可见基线时必须同步恢复完整规范化基线，而不是只比较显示文本。
**边界**：本次只修复前端草稿的车型关联恢复，不修改数据库、保存接口、车型重命名规则、圈子验证或自动参与状态。
**关联**：`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 可用模板支持下载原始 XLSX
**总目标**：在导出模板页的可用模板卡片中增加下载入口，把当前显示的最新原始模板版本保存到用户本地。
**状态**：✅ 模板版本下载接口、卡片按钮、下载文件名和缺失文件错误处理均已完成，并通过真实浏览器下载验证。
**干到哪里了**：
- [x] 新增按模板 ID 与版本 ID 读取原始 XLSX 的下载端点；服务端校验版本确实属于该模板、文件仍存在，并以清理路径保留字符后的“模板名-v版本.xlsx”附件名返回。
- [x] 可用模板卡片在删除操作旁增加带 `Download` 图标和“下载”文案的次要按钮，始终下载卡片当前显示的最新版本；说明文案同步区分下载与删除语义。
- [x] 新增接口测试覆盖正常文件内容、MIME、附件名和缺失版本 404；模板下载只读取原始版本，不创建结果导出记录，也不改变模板可用状态。
- [x] `.vevn\Scripts\python.exe -m compileall -q src tests`、Ruff、34 项后端 unittest、前端 TypeScript 检查、生产构建（2465 modules）和 `git diff --check` 通过；本地后端已使用项目 `.vevn` 重启，`/health` 返回 `status=ok`。
- [x] 真实页面点击“下载”后，浏览器将 `当前全字段测试模板-v1.xlsx` 保存到 `C:\Users\olelius\Downloads\`；文件大小 23767 字节，openpyxl 成功读取 15 个工作表。
**下一步**：继续第一版 Linux 部署门禁；若后续需要选择历史版本下载，再在真实需求出现后增加版本列表，不提前扩展当前卡片。
**边界**：本次下载的是上传保存的原始模板，不是填充批次数据后的结果文件；结果导出仍从批次详情按模板版本生成。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`src/threadsnap/templates.py`、`src/threadsnap/app.py`、`frontend/src/features/config/config-page.tsx`、`tests/test_backend.py`

## 2026-08-17 — 配置实体级修改提示与当前标签放弃修改
**总目标**：在精确字段标识之外补充计划节点、平台卡片和圈子行的实体级未保存提示，并为四个受控配置标签提供只恢复当前标签草稿的“放弃修改”。
**状态**：✅ 四级修改反馈和当前标签恢复操作已完成，类型检查、生产构建与四页真实交互验证通过。
**干到哪里了**：
- [x] 未保存反馈统一为“标签汇总 → 工具栏计数 → 实体汇总 → 具体控件”：规则沿用索引圆点，计划节点编号改为琥珀状态标识，发生变化的平台卡片显示“已修改”，圈子行在序号旁显示圆点并使用极浅琥珀底色；具体输入框、复选框、开关、星期按钮和多选器仍只标记自身差异。
- [x] 自动提取规则、每周计划、平台配置和车型与圈子工具栏均增加“放弃修改”，按钮只在当前标签有草稿时启用，并从最近一次服务端基线恢复当前标签；其他标签草稿不受影响，规则与计划共享 revision 时继续保留另一标签所需的冲突检测语义。
- [x] 即时提交的手动圈子历史和导出模板不创建受控草稿，因此不增加无实际恢复对象的“放弃修改”。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2465 modules）和 `git diff --check` 通过；真实页面分别修改计划星期、平台启用、圈子自动参与和规则名称，确认节点/平台卡片/圈子行/规则索引汇总与具体控件同时定位变化，“放弃修改”后四页 `data-dirty`、标签圆点和实体标识均恢复为 0，测试草稿未提交。
**下一步**：继续第一版 Linux 部署门禁；后续新增配置实体同时接入当前标签恢复、实体汇总和字段级差异三层职责，不再用整卡描边替代精确控件提示。
**边界**：本次只调整前端草稿恢复与修改定位，不改变保存接口、服务端数据、规则版本、计划触发、平台 Session、圈子验证或即时命令语义。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 修复非输入控件未保存外环并移除重复提示
**总目标**：修复星期按钮、开关和复选框虽已识别字段差异却没有绘制可见橙色标识的问题，并移除车型与圈子页重复占高的“请先保存当前编辑”提示卡。
**状态**：✅ 样式根因、重复反馈和上一轮验证缺口均已修复，按钮、开关与复选框已通过真实页面计算样式和视觉验证。
**干到哪里了**：
- [x] 确认差异计算没有漏项：选择星期三后控件已有 `data-dirty=true`、`outline-width: 2px` 和琥珀色 `outline-color`；真正根因是组件基础类的 `outline-none` 仍令计算样式为 `outline-style: none`，因此浏览器不绘制轮廓。
- [x] 非输入控件的 dirty 样式改为显式 `outline-solid`，继续保留 2px 琥珀色外环和 2px 偏移；星期按钮、计划开关和规则平台复选框的实际计算样式均确认变为 `2px solid`。
- [x] 移除车型与圈子页草稿状态下重复出现的保存提示 Alert；批量验证按钮仍在存在草稿时禁用，标签圆点、工具栏“1 项未保存”、字段外环和保存按钮计数继续表达状态与下一步。
- [x] 修正上一轮只断言 `data-dirty` 属性、没有核对最终 CSS 绘制结果的验证缺口；本轮同时检查状态属性、`getComputedStyle` 和真实截图，不再把“进入状态”当成“用户可见”。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2465 modules）和 `git diff --check` 通过；真实页面确认星期按钮、开关、复选框均为 `outline-style: solid`、`outline-width: 2px`，圈子草稿状态的重复提示文案数量为 0，所有临时草稿均通过关闭独立测试页丢弃。
**下一步**：继续第一版 Linux 部署门禁；后续视觉状态验收必须同时覆盖状态属性、最终计算样式和真实截图。
**边界**：本次只修复未保存标识的实际绘制和重复反馈，不改变 dirty 比较、保存事务、批量验证业务条件或后端接口。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 配置表单精确到字段的未保存标识
**总目标**：把配置页橙色未保存提示从规则、节点或整行级别细化到实际发生变化的输入框、复选框、开关、星期按钮和规则多选器，并让恢复原值的控件立即清除标识。
**状态**：✅ 四个可编辑标签的字段级基线比较、精确视觉标识和恢复逻辑已完成，并通过真实页面逐页验证。
**干到哪里了**：
- [x] 自动提取规则按规则名称、平台圈子全选、单个圈子选择和每圈目标数分别比较最近服务端基线；琥珀色边框或轮廓只落在实际变化的控件上，规则索引圆点和工具栏计数继续提供汇总定位。
- [x] 每周计划移除覆盖整个节点卡片的宽泛橙色描边，改为分别标记启用开关、发生变化的星期按钮、时间输入框和规则多选器；新增节点只在节点序号旁显示新增圆点。
- [x] 平台配置按启用开关和内部并发输入框逐字段比较，车型与圈子按车型、URL 和自动参与开关逐字段比较；两页从“修改后永远 dirty”改为规范化草稿与服务端基线比较，恢复原值会同步清除标签圆点、工具栏计数和保存按钮状态。
- [x] 删除项保留区域汇总，新建圈子在序号旁标记且可编辑输入框直接标记；即时提交的手动圈子历史和导出模板不创建表单 dirty 状态。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2465 modules）和 `git diff --check` 通过；真实页面分别修改规则名称、规则平台选择、计划启用、平台启用和圈子自动参与，确认活动标签内每次只有对应控件带 `data-dirty=true`，计划、平台和圈子恢复原值后标识数均回到 0，全部临时草稿均已丢弃且未提交业务数据。
**下一步**：继续第一版 Linux 部署门禁；后续新增受控配置字段必须复用“服务端基线逐字段比较 + 控件级标识 + 标签/工具栏汇总”模式。
**边界**：本次只调整未保存差异的计算和视觉定位，不改变保存接口、校验事务、规则版本、计划触发、圈子验证或即时命令语义。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 精简配置页未保存状态反馈
**总目标**：移除编辑配置时插入标题区下方的全局未保存提示条，避免占用置顶高度和产生布局跳变，同时保留清晰、可定位的未保存状态与离页保护。
**状态**：✅ 全局提示条已移除，分层状态提示、离页确认和保存反馈保持完整，并通过真实页面验证。
**干到哪里了**：
- [x] 配置页标题与标签之间不再渲染全宽警告条；页面编辑前后标签栏高度和纵向位置保持稳定。
- [x] 自动提取规则、每周计划、平台配置和车型与圈子四个可编辑标签在各自存在草稿时显示固定尺寸的琥珀色小圆点，并提供屏幕阅读器“有未保存修改”文本。
- [x] 当前区域工具栏继续显示待保存项数量，规则索引和规则详情继续定位具体修改项，保存按钮继续显示当前标签数量；保存成功 Toast、跨标签草稿保留、配置路由离开确认和浏览器刷新保护保持原行为。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2465 modules）和 `git diff --check` 通过；真实页面临时勾选圈子后确认全局提示文案不存在、标签圆点/“1 项未保存”/保存按钮计数出现，标签栏编辑前后均为 `y=191px`、高度 `40px`，离开配置管理仍弹出放弃确认；随后恢复原选择且未提交测试改动。
**下一步**：继续第一版 Linux 部署门禁；后续配置编辑状态继续使用“标签级圆点 + 区域计数 + 项级标记”的分层反馈，避免增加会推动内容区的全局状态条。
**边界**：本次只调整未保存状态的可见层级和占位方式，不改变草稿生命周期、保存事务、冲突处理、离页阻断、刷新保护或后端接口。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 每周计划节点支持多选规则并合并为单批次
**总目标**：允许一个每周计划节点引用多条已保存自动提取规则；同一触发时刻只创建一个合并批次，重复圈子只执行一次且采用各来源规则目标数的最大值，同时仅把计划卡片原有规则选择器升级为多选。
**状态**：✅ 数据模型、迁移、调度合并语义、原位置多选交互、现有数据库升级与服务重启均已完成。
**干到哪里了**：
- [x] 新增 `schedule_node_rules` 和 `extraction_run_rules` 有序关联表，计划节点与批次分别保存全部规则引用和触发时版本；保留旧单规则列作为首条规则兼容指针，已有单规则节点和历史批次可增量迁移。
- [x] 调度按节点一次性冻结全部规则版本，合并各规则圈子范围；同一圈子只创建一个 `CircleTask`，目标数取来源规则最大值，批次与圈子任务快照记录来源规则；任一所选规则不可用或缺少数量时阻止整次节点触发。
- [x] 前端只把每周计划卡片原规则 Combobox 改为可搜索多选，保留原网格位置、尺寸和其他控件布局；列表显示每条规则的选中状态，至少保留一条规则，多个选择时摘要显示“已选 N 条规则”。
- [x] 新增 ADR 0016，并同步 `AGENTS.md`、`CONTEXT.md`、产品设计和技术路线；定时幂等保持“计划节点 + 计划时刻”，请求哈希纳入全部规则 ID 与版本。
- [x] `.vevn\Scripts\python.exe -m compileall -q src tests`、Ruff、33 项后端 unittest、前端 TypeScript 检查和生产构建（2465 modules）通过；旧版本 `e7a4b9c21d03` 数据库升级到 `a91c4e7d2f10` 的专项验证确认节点引用、历史批次版本、事件及兼容列均保留。
- [x] 现有 `data/threadsnap.db` 已备份到 `artifacts/runtime/threadsnap-before-schedule-multi-20260817-152457.db` 后完成迁移；后端使用项目 `.vevn` 重启，`/health` 返回 `status=ok`，真实提取计划返回 2 个节点且各自原单规则引用完整。真实页面通过原位置选择器临时选中第二条规则，确认显示“已选 2 条规则”和待保存状态，随后恢复原选择且未提交测试改动。
**下一步**：继续第一版 Linux 部署门禁；后续若规则数量达到真实性能门槛，再评估多选列表虚拟化，不提前增加分页或第二套计划保存接口。
**边界**：本次不自动合并不同计划节点，不按数量求和，不改变星期、时刻、启用、删除或保存按钮布局；前端除原规则选择器外不增加新的可见区域。
**关联**：`docs/adr/0016-merge-multiple-rules-per-schedule-node.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`src/threadsnap/migrations/versions/a91c4e7d2f10_schedule_multi_rules.py`、`src/threadsnap/services.py`、`frontend/src/features/config/config-page.tsx`、`tests/test_backend.py`

## 2026-08-17 — 规则主从编辑区占满标签剩余高度

**总目标**：移除自动提取规则页由固定视口高度和最小高度造成的默认外层滚动条，让桌面端主从编辑区填满当前标签剩余工作区，并保留窄屏自然流式布局。
**状态**：✅ 完整高度链已改为弹性布局并通过桌面、窄屏真实页面验证。
**干到哪里了**：
- [x] 确认滚动条不是单纯的 `100%` 继承缺失：规则网格同时使用 `65svh/620px` 固定高度和 `500px` 最小高度，覆盖了外层 `flex-1` 提供的可用高度并主动撑高标签内容区。
- [x] 桌面端将规则面板、表单和主从网格串成 `h-full + min-h-0 + flex-1` 高度链；固定工具栏显式禁止收缩，左右卡片只在各自内容真实溢出时内部滚动，不通过隐藏外层滚动条掩盖溢出。
- [x] 保留小于 `xl` 断点时的单列自然高度：规则索引维持有界高度，编辑器顺序堆叠，标签内容区按实际内容滚动。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实页面在 1680×900 下确认活动标签内容区 `clientHeight=617`、`scrollHeight=617`，工具栏 64px、主从网格自动占用剩余 533px且三者底边对齐；1024×900 下确认网格为单列、左右卡片顺序堆叠，标签内容区按内容滚动且编辑器未裁切。
**下一步**：继续第一版目标 Linux 部署门槛；后续固定工作区继续使用完整弹性高度链，避免在内部业务容器叠加视口比例高度和最小高度。
**边界**：只调整规则标签的响应式高度与滚动归属，不修改规则编辑、保存、版本、计划引用或后端接口语义。
**关联**：`docs/design/product-design.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 拆分自动提取规则与每周计划配置标签

**总目标**：把定义“提取什么”的自动提取规则和定义“何时执行”的每周计划拆成同级配置标签，并让计划页复用其他可编辑配置页的固定工具栏、卡片内容区和独立滚动布局。
**状态**：✅ 两个标签、分区草稿与当前标签保存逻辑已完成并通过真实页面验证。
**干到哪里了**：
- [x] 配置管理由五个标签调整为“自动提取规则、每周计划、平台配置、车型与圈子、手动圈子历史、导出模板”六个同级标签；旧 `?tab=plan` 自动规范化为 `?tab=rules`，侧边栏入口同步指向规则标签。
- [x] 规则与计划共享一个前端提取配置工作区、全局 revision 和 `/extraction-plan` 原子校验，但分别维护草稿与待保存项；保存规则时合并服务器已保存节点，保存计划时合并服务器已保存规则，不提交或清除另一标签草稿，外部 revision 变化时保留旧 revision 触发冲突而不是静默覆盖。
- [x] 每周计划页复用 `ConfigSectionToolbar`、20px 内容间距、14px 圆角和节点卡片布局；新增节点与保存操作位于工具栏，节点增加顺序标识，规则选择器只展示已保存规则，未保存新规则不会提前进入计划引用。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实页面确认六个标签、旧链接重定向、规则页与计划页独立呈现，计划工具栏与首张节点卡片同宽且间距 20px、圆角均为 14px；创建未保存规则后切换计划页，规则草稿保留而计划保存仍禁用，选择器只列出两条已保存规则，临时草稿随后已清理。
**下一步**：继续第一版目标 Linux 部署门槛；后续新增配置职责继续遵守唯一编辑归属和当前标签保存，不复制提取配置保存端点。
**边界**：不修改数据库结构、规则版本、计划冲突、调度触发或后端保存接口语义。
**关联**：`docs/design/product-design.md`、`frontend/src/components/app-shell.tsx`、`frontend/src/router.tsx`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 修复规则头滚动覆盖与右侧面板圆角

**总目标**：修复页面滚动时右侧“规则名称”头部越过规则面板并覆盖“自动提取规则”工具栏的问题，同时恢复右侧面板顶部圆角。
**状态**：✅ 右侧规则面板已改为固定头部与独立滚动正文，并通过滚动层级验证。
**干到哪里了**：
- [x] 确认上一轮只解决了工具栏与主从网格的初始流式间距，没有覆盖右侧 `CardHeader` 自身的 `position: sticky`；内外两层粘性元素都使用 `top: 0` 和相同层级，页面滚动时规则头可能进入外层工具栏区域。
- [x] 移除规则头的粘性定位和毛玻璃合成层，把右侧面板重构为固定头部与仅正文滚动的纵向 Flex 布局；头部显式使用匹配卡片的顶部圆角，外层卡片继续负责圆角裁切。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实页面滚动到 `scrollTop=470` 时，规则头位于工具栏下方重叠区域但 `elementFromPoint` 命中外层工具栏而非规则头，规则头计算样式为 `position: static`、圆角为 `14px`、层级为 `auto`。
**下一步**：继续第一版目标 Linux 部署门槛；后续面板内固定头部继续采用“头部与滚动正文分层”，不嵌套同起点的页面级 sticky。
**边界**：只调整右侧规则面板的滚动容器和视觉裁切，不修改规则编辑、保存、版本或计划引用语义。
**关联**：`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 修复规则编辑区与置顶工具栏重叠

**总目标**：修复提取计划主从规则区的编辑面板覆盖固定工具栏、左侧搜索区被遮挡的问题，保持既有独立滚动与固定工具栏设计。
**状态**：✅ 布局根因已修复并通过构建与真实页面几何验证。
**干到哪里了**：
- [x] 确认原生 `fieldset` 使用 `display: contents` 后不再形成可靠布局盒，导致父级纵向间距无法作用于工具栏和主从网格，二者从同一纵向位置开始渲染；这不是高度继承问题。
- [x] 恢复 `fieldset` 的正常块级布局，清除其浏览器默认边距、边框和内边距，并由其内部 `space-y-5` 明确分隔工具栏与主从网格。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实配置页确认 `fieldset` 计算样式为 `display: block`、外边距为 `0px`，工具栏与搜索框、编辑器重叠量均为 `0px`，规则索引、编辑器和禁用的保存按钮仍正常呈现。
**下一步**：继续第一版目标 Linux 部署门槛；后续需要批量禁用表单时避免在原生 `fieldset` 上使用 `display: contents`。
**边界**：只修复规则区布局流，不修改规则、计划、保存、版本或调度业务语义。
**关联**：`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 扩展规则管理并优化提取计划保存逻辑

**总目标**：让提取计划在规则数量增加后仍能快速定位和编辑，同时保留规则与每周计划节点的原子校验，修复粗粒度脏状态、保存途中覆盖新编辑和恢复归档覆盖草稿等风险。

**状态**：✅ 主从规则编辑与保存状态改造已完成并通过真实页面确认。

**干到哪里了**：
- [x] 自动提取规则改为左侧可搜索规则索引、右侧单规则编辑器；规则索引展示版本、圈子数、计划引用数和逐规则未保存标识，规则区高度稳定且独立滚动。
- [x] 每周计划节点的规则选择改为可搜索 Combobox，展示规则版本与圈子数；新建节点优先引用当前规则。
- [x] 保存仍复用 `/extraction-plan` 的全局 revision 与单事务校验，但前端改为基线差异计算、逐规则/逐节点标识、无差异禁用和待保存项计数；保存期间锁定编辑控件。
- [x] 保存失败保留草稿并定位后端指向的规则或节点；revision 冲突提供保留草稿或重新加载服务器版本；存在草稿时禁止恢复归档规则，避免即时恢复响应覆盖当前编辑。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实配置页面确认规则索引显示 2 条规则的版本、圈子数与计划引用数，清洁状态下“保存全部更改”禁用，点击第二条规则后右侧编辑器从“懂车帝重点车型”切换为“懂车帝特殊车型”，每周节点使用可搜索规则 Combobox，窄屏顺序布局保持全部操作可达。

**下一步**：后续规则数量达到实际性能门槛时再评估虚拟化；当前使用固定高度索引、搜索和单规则渲染，不引入分页或第二套保存端点。

**边界**：不拆分后端保存端点，不改变规则版本生成、计划节点冲突校验、删除/归档或调度语义。

**关联**：`docs/design/product-design.md`、`frontend/src/features/config/config-page.tsx`、`src/threadsnap/services.py`

## 2026-08-17 — 为全部数据列表增加序号列

**总目标**：在提取列表、批次结果和全部配置数据表的首列增加统一序号，方便滚动浏览和沟通定位具体行。

**状态**：✅ 5 张数据表已完成统一序号并通过运行态确认。

**干到哪里了**：
- [x] 提取列表和批次结果按当前筛选、排序及分页偏移连续编号，跨页不从 1 重新开始。
- [x] 车型与圈子、手动圈子历史、导出模板字段按当前展示顺序从 1 编号。
- [x] 空状态列数和批次结果加载骨架已随新增列同步调整；序号保持窄列、居中和等宽数字样式。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实页面确认提取列表、批次结果、车型与圈子、手动圈子历史、导出模板字段均显示“序号”表头，首屏从 1 连续编号，批次结果第 2 页从 51、52、53 继续编号。

**下一步**：后续新增分页表格继续使用完整筛选结果集的连续序号，新增配置表按展示顺序编号。

**边界**：序号仅为前端定位信息，不新增数据库字段，不进入接口、URL 状态或导出模板。

**关联**：`docs/design/product-design.md`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 统一全部数据列表的固定表头与底栏

**总目标**：修复提取列表、批次结果和配置数据表把表头、数据行、分页底栏放进同一滚动流的问题，统一为固定表头、表体独立滚动、分页底栏固定的列表结构。

**状态**：✅ 全部数据表格已统一滚动结构并完成运行态确认。

**干到哪里了**：
- [x] 基础表格移除隐式横向滚动容器并统一提供粘性表头，避免页面滚动层与组件滚动层嵌套后粘性定位失效。
- [x] 提取列表和批次结果表拆分出独立数据视口，分页底栏移到视口之外并固定在列表底部。
- [x] 车型与圈子、手动圈子历史、导出模板字段列表增加独立横纵向数据视口，无分页列表只固定表头。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；真实批次详情数据视口从 `scrollTop=0` 滚至 `1080` 时表头与底栏坐标分别保持 `282px`、`730px`，提取列表从 `0` 滚至 `147` 时分别保持 `542px`、`730px`，车型与圈子列表从 `0` 滚至 `243` 时表头保持 `424px`；手动圈子历史和导出模板字段页也已确认使用统一表格结构并正常呈现。

**下一步**：后续新增数据表格必须复用同一滚动结构，不再由基础表格和页面同时创建滚动容器。

**边界**：本次只统一数据表格的滚动层级和固定区域，不修改查询、筛选、分页、导出或配置业务语义。

**关联**：`docs/design/product-design.md`、`frontend/src/components/ui/table.tsx`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 批次导出操作移至复制按钮旁

**总目标**：把批次详情页底部孤立的导出模板选择器移动到筛选工具栏右侧，与“复制全部”形成相邻的结果输出操作。

**状态**：✅ 导出操作已移动到复制按钮旁并完成运行态确认。

**干到哪里了**：
- [x] 导出模板选择器已移入筛选工具栏末端操作组，并与“复制全部”并排展示。
- [x] 删除结果列表底部的独立导出行，导出 mutation、模板禁用条件和下载行为保持不变。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 通过；目标批次页面在 1680 × 920 桌面视口确认两项操作同一行、间距 8px，导出控件只出现一次，窄屏顺序布局仍保持两项操作相邻。

**下一步**：后续新增结果输出操作时继续复用筛选工具栏末端操作组，不在列表底部增加独立操作行。

**边界**：本次只调整批次详情页操作位置，不修改模板、导出接口、筛选、复制或分页语义。

**关联**：`docs/design/product-design.md`、`frontend/src/features/runs/run-detail-page.tsx`

## 2026-08-17 — 修复懂车帝富文本标题与正文标准化

**总目标**：修复懂车帝富文本帖子把正文 HTML 片段误作标题、正文原样保存标签和图片节点的问题，确保标题字段优先级与正文标准化符合产品字段契约。

**状态**：✅ 富文本标题与正文标准化已完成修复。

**干到哪里了**：
- [x] 以帖子 `7674619924202979865` 复核平台详情接口：`thread_title` 为空、`motor_title` 为真实标题、`content` 为 HTML 富文本；确认现有实现忽略 `motor_title` 并直接对 HTML 执行首句回填是根因。
- [x] 当前数据库共识别到 16 个不同富文本帖子、31 份历史快照存在同类异常；对 16 个帖子进行有界接口复核，全部为 `thread_title` 空、`motor_title` 有值且正文为 HTML。
- [x] 适配器升级为 `dongchedi-dynamic-v2`：标题按 `thread_title`、`motor_title`、纯文本正文首句依次选择；正文去除富文本标签、脚本和媒体节点并保留段落顺序，图片 URL 仍使用独立字段；服务启动时同步平台目录中的当前适配器版本，但不改变用户启用或并发配置。
- [x] 新增富文本真实形状回归用例，覆盖平台标题优先、正文纯文本化、图片字段保留和无标题时纯文本首句回填。
- [x] 修复后直接读取目标帖子得到标题“我和qq3的故事～”、7 段纯文本正文、4 个独立图片 URL 且正文不含 HTML；完整后端测试 32/32 通过，`ruff format --check`、`ruff check`、`compileall`、`pip check` 和 `git diff --check` 通过。

**下一步**：历史批次继续保持不可变；重新提取后由新批次按修复后的适配器生成正确快照。

**边界**：不静默改写已经完成的历史批次；本次只修复后续采集标准化，不改变圈子发现、评论、媒体 URL、状态或执行流程。

**关联**：`docs/design/product-design.md`、`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/services.py`、`tests/test_backend.py`

## 2026-08-17 — 重设计圈子任务弹窗

**总目标**：修复圈子任务 Dialog 只是把原表格搬入弹层造成的层级单薄、重复信息过多和进度表达弱的问题，使其符合数据密集型后台的扫描与响应式体验。

**状态**：✅ 圈子任务弹窗已按平台分组重设计。

**干到哪里了**：
- [x] 使用 `ui-ux-pro-max` 的数据密集型后台与 Dialog 指引，弹窗顶部增加任务总数、成功数、聚合结果进度和异常数，并以统一进度条提供整体反馈。
- [x] 任务列表由重复平台列的普通表格改为平台分组面板：平台头只展示一次名称、圈子数与聚合进度，圈子行展示名称、原帖入口、状态、独立进度及必要结果说明。
- [x] 正常完成说明与错误状态分开表达；桌面端采用三段扫描布局，窄屏自动堆叠，内容区独立滚动并保留统一遮罩、焦点与关闭行为。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 已通过；真实页面已在默认窄屏和 1680×920 桌面视口检查弹窗布局、文案与滚动容器。

**下一步**：后续接入多平台时直接复用当前平台分组，不新增第二套圈子任务展示结构。

**边界**：本次只重设计批次详情中的圈子任务 Dialog，不修改任务状态、进度计算来源、提取执行或数据库语义。

**关联**：`docs/design/product-design.md`、`frontend/src/features/runs/run-detail-page.tsx`

## 2026-08-17 — 压缩全部置顶区并弹窗展示圈子任务

**总目标**：降低配置页、提取列表和批次详情置顶上下文的纵向占用，同时保持标题、说明、摘要、筛选和操作之间的清晰分组；把批次圈子任务移出置顶内容流。

**状态**：✅ 三个基础页面的置顶密度与圈子任务入口已完成调整。

**干到哪里了**：
- [x] 公共页面标题缩短底部留白、说明间距和标题字号层级，应用桌面内容边距由 32px 收敛为 24px；操作区继续允许换行，不把按钮强行挤入单行。
- [x] 配置页缩短标题、标签、内容区和共用工具栏间距，工具栏保留图标、摘要、说明与操作分组；提取列表和批次详情的筛选卡片移除重复的 Card 外层纵向 padding，仅保留控件所需内边距。
- [x] 批次详情把返回入口并入标题上下文，摘要卡片改为紧凑高度；圈子任务从置顶区独立折叠行改为刷新按钮旁的“圈子任务 N”按钮，点击后通过带独立滚动区的 Dialog 展示完整任务表。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 作为提交门禁；按用户要求不执行页面验证。

**下一步**：继续第一版目标 Linux 部署门禁；新增置顶上下文时优先复用当前紧凑间距和独立弹窗详情，不叠加无必要卡片层。

**边界**：本次只调整前端密度、圈子任务展示入口和文档口径，不修改批次、任务、规则、筛选、分页、刷新或删除语义。

**关联**：`docs/design/product-design.md`、`frontend/src/components/app-shell.tsx`、`frontend/src/components/page-header.tsx`、`frontend/src/features/config/config-page.tsx`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`

## 2026-08-17 — 统一配置标签固定工具栏

**总目标**：把“提取计划”和“平台配置”的固定操作区同步为“车型与圈子”已经采用的紧凑卡片工具栏，消除其余标签中的单色平条与孤立按钮。

**状态**：✅ 三个可编辑配置标签已共用同一固定工具栏结构与视觉层级。

**干到哪里了**：
- [x] 新增配置页内部共用的 `ConfigSectionToolbar`，统一圆角、边框、轻阴影、语义图标、摘要徽标、说明和操作区，避免三个标签继续复制同类样式。
- [x] “提取计划”展示规则数量并保留新建、保存操作；“平台配置”补齐标题、配置说明和已接入数量并保留保存操作；“车型与圈子”迁移到同一组件，既有数量、验证、新增和保存行为不变。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 作为提交门禁；按用户要求不执行页面验证。

**下一步**：继续第一版目标 Linux 部署门禁；后续配置标签需要固定标题与主操作时直接复用该工具栏。

**边界**：本次只统一配置标签固定工具栏的展示组件和只读摘要，不修改规则、平台、圈子、Session 或保存逻辑。

**关联**：`docs/design/product-design.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 优化车型与圈子固定工具栏

**总目标**：消除“车型与圈子”固定标题区横贯页面的单色白条观感，让标题说明、数量摘要和主要操作形成清晰且克制的工具栏层级。

**状态**：✅ 工具栏容器、信息层级与设计口径已完成调整。

**干到哪里了**：
- [x] 固定标题区改为与现有卡片体系一致的圆角、细边框、轻阴影和半透明卡片表面，不再使用只有底边框的整条白色背景。
- [x] 左侧加入车型语义图标与当前圈子数量徽标，保留原说明；右侧批量验证、新增和保存操作保持原顺序、状态和行为。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build` 和 `git diff --check` 作为提交门禁；按用户要求不重复执行上一项根级滚动问题的页面验证。

**下一步**：继续第一版目标 Linux 部署门禁；其他标签如出现同类固定操作区，再复用该紧凑卡片工具栏，不新增一次性视觉变体。

**边界**：本次只调整“车型与圈子”固定工具栏的视觉层级与只读数量摘要，不修改圈子编辑、验证、自动参与、保存或删除逻辑。

**关联**：`docs/design/product-design.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 消除应用外壳的根级滚动条

**总目标**：移除多个页面最右侧重复出现的根级纵向滚动条，只保留页面明确划分的数据滚动区。

**状态**：✅ 桌面 inset 高度冲突已定位并修复，应用根高度链、内部滚动区和技术口径已同步。

**干到哪里了**：
- [x] 根因确认不是业务页面缺少 `height: 100%`：上游 `SidebarInset` 在桌面断点自带上下各 `0.5rem` 外边距，应用此前又给它设置 `h-svh`，导致其 margin box 总高为 `100svh + 1rem`，把 `SidebarProvider`、`#root`、`body` 和 `html` 撑出视口并形成所有路由共享的根级滚动条。
- [x] 视口高度改由 `SidebarProvider` 唯一持有；`SidebarInset` 移除重复的 `h-svh`，由 Flex 在桌面 inset 边距内拉伸到剩余高度；`html`、`body` 和 `#root` 固定满高并隐藏根级溢出，业务滚动继续只由各页面已有的数据区承担。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2460 modules）和 `git diff --check` 通过；真实配置页与批次详情页均确认 `html/body/#root` 的 `clientHeight = scrollHeight = 848` 且 `overflow-y: hidden`，详情页内部工作区仍保留按断点定义的滚动能力。

**下一步**：继续第一版目标 Linux 部署门禁；新增页面只复用应用根高度链和页面内滚动区，不在带外边距的子面板重复声明视口高度。

**边界**：本次只修复应用外壳高度所有权与根级溢出，不修改页面信息结构、响应式断点、表格分页、查询或业务数据。

**关联**：`docs/design/technical-route.md`、`frontend/src/components/app-shell.tsx`、`frontend/src/styles/index.css`

## 2026-08-17 — 固定页面工作区并修复搜索置顶

**总目标**：让配置页、提取列表和批次详情的页面上下文与筛选操作保持可见，只滚动数据内容；同时把提取规则平台与批次圈子任务设为默认收起，并消除搜索导致页面回到顶部的问题。

**状态**：✅ 三个基础页面的滚动分区、两处默认折叠、同路由搜索滚动保持、设计口径和真实页面验证完成。

**干到哪里了**：
- [x] 应用外壳改为固定视口高度与内部工作区滚动：全局标题栏不再参与业务页面滚动；配置页固定页面说明、标签栏和当前区块标题/主操作，提取列表固定页面说明与筛选工具栏，数据内容使用独立滚动区。
- [x] 提取规则的所有平台面板统一默认收起，不再因已选圈子自动展开；批次详情的“圈子任务”改为默认收起的折叠面板，标题直接展示任务数量并保留按需展开入口。
- [x] 批次详情在 1280px 及以上固定返回入口、批次摘要、圈子任务入口和帖子搜索筛选，仅滚动帖子结果与导出区；窄屏继续整页顺序滚动，避免固定区域换行后挤占全部结果空间。
- [x] 搜索置顶根因已确认不是整页刷新，而是搜索、筛选和分页写入同一路由查询参数时沿用 TanStack Router 默认滚动重置；提取列表和批次详情的同路由更新现已统一设置 `resetScroll: false`，保留 URL 可恢复性与 TanStack Query 局部列表回查。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2460 modules）和 `git diff --check` 通过；真实页面确认平台默认无圈子行、圈子任务默认无任务表，点击后可展开，标题搜索后批次上下文与折叠状态保持，临时搜索词已清除。截图位于 `artifacts/runtime/fixed-page-workspaces.png`。

**下一步**：继续第一版目标 Linux 部署门禁；新增数据密集页面时复用“固定上下文区 + 独立数据滚动区”，同路由筛选更新继续显式保持滚动位置。

**边界**：本次只调整前端布局、折叠初始状态与路由滚动行为，不修改查询接口、筛选语义、规则选择、圈子任务数据、批次状态或数据库。

**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/components/app-shell.tsx`、`frontend/src/features/config/config-page.tsx`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`

## 2026-08-17 — 压缩提取规则的平台圈子选择区

**总目标**：降低“提取计划”中平台圈子选择区的纵向高度，让多平台规则按平台展开或收起，只展示具备全局自动参与资格的圈子，并去除逐圈重复状态与车型分组造成的空白。

**状态**：✅ 平台折叠、圈子筛选、紧凑满宽布局、响应式标题区、设计口径和真实页面验证完成。

**干到哪里了**：
- [x] 每个平台改用 `Collapsible` 面板；含已选圈子的平台默认展开，其余平台默认收起，平台复选框继续承担当前可选圈子的批量选择，后续多平台仍沿用同一结构。
- [x] 规则区只从 `auto_enabled=true` 的圈子生成列表和平台全选集合；移除逐车型标题及“已验证 · 全局启用”等重复说明，圈子名称直接排入占满内容区的响应式网格。
- [x] 对已被规则选择、后来全局停用的隐藏圈子保持原规则 ID 与平台数量，不因页面隐藏或取消当前可选圈子的批量选择而静默改写历史选择；调度时继续按既有交集规则过滤。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2460 modules）与 `git diff --check` 通过；真实页面确认平台可收起且圈子行随之移除，临时停用 A9L 后平台计数由 `1/14` 变为 `1/13` 且该圈子不再显示，随后已恢复为 14/14 全局启用，规则仍只选择原风云 A9 圈子。最终截图位于 `artifacts/runtime/compact-plan-circle-selector.png`，测试前数据库备份位于 `artifacts/runtime/threadsnap-before-compact-selector-20260817-110851.db`。

**下一步**：继续第一版目标 Linux 部署门禁；后续平台接入时直接复用当前平台折叠与规则多选交互，不新增第二套圈子选择器。

**边界**：本次只调整规则选择区的展示与前端可选集合，不修改圈子验证、全局自动参与写入、规则版本、平台数量、调度交集、数据库结构或现有规则数据。

**关联**：`docs/adr/0015-select-explicit-circles-per-extraction-rule.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`frontend/src/features/config/config-page.tsx`

## 2026-08-17 — 圈子批量验证与首次自动参与

**总目标**：取消新增圈子逐条手动验证的重复操作，让全部待验证配置圈子按受控队列批量验证；首次验证成功自动开启全局自动参与，但重新验证或重新认证不得覆盖用户后来手动关闭的状态。

**状态**：✅ 首次验证持久语义、批量验证 API 与进度、前端交互、数据库迁移、自动化回归和 12 条真实圈子批量验证完成。

**干到哪里了**：
- [x] 圈子新增不可回退的 `first_validated_at`；只有该字段为空的配置圈子在验证成功时自动设置 `auto_enabled=true`。首次成功后字段永久保留，重新验证、重新认证或身份变化后的再次验证只刷新验证结果，不覆盖当前自动参与开关；手动圈子历史不自动参与。
- [x] 新增 `POST /api/v1/circles/validate-unverified`，一次为全部 `unverified` 配置圈子创建或复用验证任务；现有 Worker 继续按持久单任务 FIFO 执行，并避免对排队、运行或等待认证的同一圈子重复建任务。
- [x] “车型与圈子”新增“验证全部待验证”按钮、总进度及成功/失败/等待认证统计；未首次成功的行明确提示“首次通过后自动参与”，已成功过的行显示“重新验证”。存在未保存编辑时禁止批量验证并提示先保存。
- [x] 迁移 `e7a4b9c21d03` 已应用到本地 SQLite；既有已验证圈子补记首次验证时间且保持原开关。真实页面将其余 12 条圈子批量提交后 `12/12` 成功、失败 0、等待认证 0；当前 14 条懂车帝圈子全部已验证且自动参与，现有规则仍只选择原风云 A9 圈子。
- [x] `python -m unittest discover -s tests -v`（29 项）覆盖批量任务复用、首次成功自动开启、手动关闭后重新验证保持关闭；Ruff format/check、`compileall`、`pip check`、前端 `check`、生产构建（2458 modules）与 `git diff --check` 通过。真实页面控制台无 error/warning，截图位于 `artifacts/runtime/bulk-circle-validation-ui.png`；迁移前备份位于 `artifacts/runtime/threadsnap-before-first-validation-20260817-105924.db`。

**下一步**：用户按具体自动提取规则明确勾选需要执行的圈子；自动参与只提供全局执行资格，不自动扩张任何规则范围。

**边界**：批量操作只处理已经保存且状态为 `unverified` 的配置圈子；验证失败和等待认证保留逐条恢复入口，已验证圈子不进入批量任务；验证成功不修改自动提取规则、数量或计划节点。

**关联**：`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`src/threadsnap/migrations/versions/e7a4b9c21d03_circle_first_validation.py`、`src/threadsnap/models.py`、`src/threadsnap/services.py`、`src/threadsnap/worker.py`、`src/threadsnap/app.py`、`frontend/src/features/config/config-page.tsx`、`frontend/src/lib/types.ts`、`tests/test_backend.py`

## 2026-08-17 — 精简提取计划标题并补齐懂车帝圈子清单

**总目标**：移除提取计划页对用户无业务价值的“计划版本”徽标，并把甲方清单中的懂车帝车型圈子链接补齐到当前本地数据库，同时保持规则范围不会因新增圈子自动扩大。

**状态**：✅ 页面精简、14 条目标圈子入库核验、规则范围回归、自动化检查和真实页面验证完成。

**干到哪里了**：
- [x] 提取计划标题区已移除“计划版本 N”徽标；后端与保存载荷中的 `revision` 保留，用于乐观并发控制，不改变规则版本语义。
- [x] 甲方清单 14 条懂车帝圈子全部存在于本地 SQLite：保留已存在且已验证启用的风云 A9/24729，新增 A9L、QQ3 EV、T9L、T11、T9、艾瑞泽8、艾瑞泽8PRO、瑞虎8、瑞虎8PLUS、瑞虎8PRO、瑞虎9、瑞虎7L、风云T7 共 13 条；写入回执位于 `artifacts/runtime/dongchedi-circle-seed-result.json`。
- [x] 13 条新增圈子写入时统一为 `unverified`、`auto_enabled=false`；服务重启后的真实页面随后触发并通过 A9L/8985 验证，当前 A9L 仍未自动参与、其余 12 条新增圈子未验证，现有规则仍只引用原风云 A9 圈子。API 与页面均确认懂车帝显示 `1/14 个圈子`，未把新圈子静默加入既有规则。
- [x] `python -m unittest discover -s tests -v`（28 项）、Ruff format/check、`compileall`、`pip check`、前端 `check`、生产构建（2458 modules）与 `git diff --check` 通过；真实页面 DOM 确认不存在“计划版本”，控制台无 error/warning，截图位于 `artifacts/runtime/plan-circle-seed-ui.png`。

**下一步**：逐条验证新增圈子后，才允许在“车型与圈子”启用自动参与，并由用户在具体提取规则中明确勾选；未验证圈子不会进入定时执行。

**边界**：本次只移除可见徽标并写入用户提供的圈子链接；不把截图链接视作平台可访问性验证，不修改现有规则选择、目标数、计划节点、采集器或 Session。

**关联**：`frontend/src/features/config/config-page.tsx`、`data/threadsnap.db`（本地运行数据，不提交 Git）、`artifacts/runtime/dongchedi-circle-seed-result.json`

## 2026-08-17 — 自动提取规则支持多平台圈子范围

**总目标**：让每条自动提取规则明确勾选需要执行的平台圈子，并为实际选中圈子的各平台设置统一每圈目标数；后续平台和圈子接入时不自动扩张既有规则范围。

**状态**：✅ 规则版本、数据库迁移、页面与集成 API、调度范围、圈子删除保护、前端多选交互、设计口径和真实页面验证完成。

**干到哪里了**：
- [x] 不可变规则版本新增明确圈子 ID 集合；迁移 `c5d1f0a92b34` 把已有规则回填为迁移时全局启用的配置圈子。规则保存严格校验圈子归属、平台接入状态以及“已选平台集合 = 数量键集合”，范围或数量变化生成新版本。
- [x] 调度只为“规则已选 ∩ 平台已启用 ∩ 圈子已验证且全局启用”的来源创建任务，并在批次快照冻结规则圈子 ID、平台数量和实际子任务；已选圈子全部不可执行时记录中文跳过事件，不创建空批次。后续平台启用不再强制所有规则补齐数量，也不自动加入任何旧规则。
- [x] 提取计划规则卡片按平台和车型展示圈子；平台复选框支持全选、部分选中和取消，实际保存明确圈子 ID。只有选中圈子的平台启用每圈目标数；暂未接入平台只读禁用；新规则默认空范围。当前规则已通过迁移保留懂车帝圈子与目标数 30。
- [x] 活动规则当前版本仍选择圈子时阻止删除并返回引用规则名称；先保存移除圈子的规则新版本后可以删除，历史批次与旧规则版本保持可解释。
- [x] `python -m unittest discover -s tests -v`（28 项）、Ruff format/check、`compileall`、`pip check`、前端 `check`、生产构建（2458 modules）和 `git diff --check` 通过；测试覆盖范围版本、删除保护、单规则跨两个已接入平台创建不同目标数子任务以及调度只处理已选圈子。
- [x] 在线 SQLite 备份副本升级到 `c5d1f0a92b34`，确认 `selected_circle_ids` 存在且旧规则回填 1 个圈子；真实本地数据库随后由新后端启动迁移成功。真实浏览器确认平台/圈子复选框和目标数双向联动、临时草稿可放弃、控制台无 error/warning；截图位于 `artifacts/runtime/rule-scope-ui.png`。

**下一步**：继续第一版目标 Linux 部署门禁；后续平台适配器转为已接入后，在“车型与圈子”保存并验证其圈子，再由用户按规则明确选择，不修改既有规则范围。

**边界**：本次只调整定时自动提取规则的来源范围；手动提取仍一次选择一个平台和多个圈子，平台与圈子全局启用状态、FIFO、认证、采集器、结果和导出流程保持不变；计划节点时间仍保持全局唯一。

**关联**：`docs/adr/0015-select-explicit-circles-per-extraction-rule.md`、`src/threadsnap/migrations/versions/c5d1f0a92b34_rule_circle_scope.py`、`src/threadsnap/models.py`、`src/threadsnap/schemas.py`、`src/threadsnap/services.py`、`frontend/src/features/config/config-page.tsx`、`frontend/src/lib/types.ts`、`tests/test_backend.py`

## 2026-08-17 — 调整收缩侧栏品牌图标比例

**总目标**：修复导航栏收缩后品牌图标仍沿用展开态尺寸、在窄侧栏内占比过大且视觉重心偏移的问题，同时保持展开态品牌区尺寸和信息层级不变。
**状态**：✅ 前端样式修复、静态检查、生产构建与构建产物样式契约核验完成。
**干到哪里了**：
- [x] 收缩态品牌容器固定为 `40 × 40px` 并居中，品牌底色图标从 `32 × 32px` 缩小为 `28 × 28px`，内部 Sparkles 从 `16 × 16px` 缩小为 `14 × 14px`；展开态继续使用原有 `44px` 高度、`32px` 图标和完整品牌文字。
- [x] 收缩态同步收紧标题区内边距并清除品牌容器横向内边距，避免只缩小图标后仍由外层盒模型造成偏位；尺寸过渡保持 `200ms ease-out`，系统启用减少动态效果时关闭新增过渡。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2456 modules）与 `git diff --check` 通过；生产 CSS 已确认生成带 `!important` 的收缩态 `size-10`、`size-7`、`size-3.5`、`p-2` 和 `px-0` 规则，避免展开态基础工具类覆盖收缩尺寸。
**下一步**：继续第一版目标 Linux 部署门禁；后续若根据真实屏幕密度微调品牌比例，只调整 `app-shell.tsx` 中收缩态三层尺寸，不改变共享 Sidebar 组件。
**边界**：本次只调整桌面端收缩导航栏的品牌区比例、居中和过渡；不修改展开态布局、移动端 Sheet、导航菜单图标、路由、后端接口或业务数据。
**关联**：`frontend/src/components/app-shell.tsx`

## 2026-08-15 — 移除新建提取 Sheet 的重复关闭图标

**总目标**：修复“新建提取”右侧 Sheet 顶部同时出现框架默认 X 与页面自定义 X 的重复关闭入口，保留具备统一悬停和焦点反馈的页面关闭按钮。

**状态**：✅ 前端修复、静态检查、生产构建和真实 Chrome 关闭路径验证完成。

**干到哪里了**：
- [x] 共享 `SheetContent` 新增默认开启的 `showClose` 参数，现有 Sheet 的框架默认关闭控件保持不变；“新建提取”明确传入 `showClose={false}`，只隐藏该页绝对定位的框架默认 X。
- [x] 标题栏保留 `SheetClose` 包裹的 `ghost` 图标按钮，页脚“关闭”按钮保持原有行为；两者均继续触发同一受控 `onOpenChange(false)` 和输入重置路径。
- [x] 真实 Chrome 打开“新建提取”后检测到标题栏关闭按钮 1 个、页脚“关闭”按钮 1 个、`SheetContent` 直接子关闭按钮 0 个；点击标题栏 X 后退出动画结束，Sheet 节点数量为 0。
- [x] `npm.cmd --prefix frontend run check`、`npm.cmd --prefix frontend run build`（2456 modules）和 `git diff --check` 通过。

**下一步**：继续第一版目标 Linux 部署门禁；后续新增自定义 Sheet 标题栏关闭按钮时，显式使用 `showClose={false}`，避免重复入口。

**边界**：本次只处理“新建提取” Sheet 的重复关闭入口；不修改其他 Sheet 的默认关闭方式、提取提交逻辑、后台接口、输入重置规则或页面动效。

**关联**：`frontend/src/components/ui/sheet.tsx`、`frontend/src/features/runs/new-extraction-sheet.tsx`

## 2026-08-15 — 保留帖子详情 Sheet 关闭时的当前列表位置

**总目标**：帖子详情 Sheet 内切换相邻记录后，关闭 Sheet 不再把背景结果表拉回首次打开位置；用户能在当前视口中立即辨识刚才查看的帖子。

**状态**：✅ 前端交互、设计口径、静态检查、生产构建和用户本地手动验证完成。

**干到哪里了**：
- [x] 关闭 Sheet 时移除对首次打开滚动位置的强制恢复，保持关闭瞬间的背景列表位置；仍以 `preventScroll` 交还焦点，优先落在当前帖子行的“查看”按钮，避免焦点回到已切换前的旧行。
- [x] 当前详情关闭后将对应行标为“刚刚查看”，复用现有主色浅色行面与左侧光晕，在约 1.8 秒后淡出；减少动态效果偏好下保留短暂静态提示，不保留永久选中态，也不向 URL 写入额外状态。
- [x] 同步 `docs/design/product-design.md` 与 `docs/design/technical-route.md`：关闭行为从“回到原位置”更新为“保留关闭瞬间位置”，并明确焦点归还与短暂定位提示。
- [x] `frontend` 执行 `npm.cmd run check`、`npm.cmd run build`（2456 modules）和 `git diff --check` 均通过；用户已在本地手动确认新行为生效。

**下一步**：继续第一版目标 Linux 部署门禁；如需进一步调整定位提示，只修改现有 `post-row-*` 语义样式与时长，不重新引入首次打开位置恢复。

**边界**：本次仅调整帖子详情 Sheet 的关闭位置、焦点归还和短暂定位反馈；不变更后端接口、结果排序、分页、快照内容、遮罩滚动锁定或 URL 数据边界。

**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/styles/index.css`、`docs/design/product-design.md`、`docs/design/technical-route.md`

## 2026-08-15 — 增加帖子详情的背景列表选中轨迹

**总目标**：在帖子详情 Sheet 内切换上一条、下一条时，让背景结果表明确显示当前快照所在行，并以现代、克制的方向性过渡维持空间连续性。
**状态**：✅ 前端交互、设计口径、静态检查、生产构建和真实 Chrome 目标路径验证完成。
**干到哪了**：
- [x] 结果表当前行新增“当前查看”文字标签、语义主色浅色行面与左侧液态光晕；`aria-current` 保证辅助技术可识别，颜色、描边和光晕全部基于既有主题 Token。
- [x] 光晕使用 Motion `layoutId` 的弹簧 `transform` 位移，形成细窄光带和扩散尾迹，而不使用整页水滴或大面积高饱和填充；系统减少动态效果时即时定位。
- [x] 相邻导航建立 `selectionRevealPostId`，目标行在可视区域外才以 `scrollIntoView({ block: 'nearest' })` 最小距离平滑揭示；跨页列表以 `placeholderData` 保留旧布局，关闭 Sheet 仍保留既有打开前滚动复位行为。
- [x] `npm.cmd run check`、`npm.cmd run build`（2456 modules）和 `git diff --check` 通过；真实 Chrome 目标页检测到唯一 `aria-current` 行、当前查看标签、4px 光晕及主题渐变/阴影，点击下一条后详情更新为筛选结果第 21 / 30 条、当前行仍唯一，背景 `scrollY` 保持 `1390`。
**下一步**：用户可在保留的本地详情 Sheet 中直接观察相邻切换的光晕轨迹；后续第一版主线继续目标 Linux 部署门禁。
**边界**：本次不改变帖子排序、后端分页接口、快照内容或 Radix 遮罩滚动锁；跨页不伪造长距离行间动画，只在目标页行出现后标示。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/styles/index.css`、`docs/design/product-design.md`、`docs/design/technical-route.md`

## 2026-08-15 — 修复帖子详情相邻切换按钮闪色

**总目标**：消除帖子快照 Sheet 中上一条、下一条切换时按钮先闪出蓝色底色再更新内容的割裂反馈，同时保持导航顺序、按钮可访问性和详情布局稳定。
**状态**：✅ 前端交互修复、设计口径同步、静态检查、生产构建和用户真实页面确认完成。
**干到哪了**：
- [x] 详情与相邻导航查询使用 TanStack Query `placeholderData` 保留当前快照，避免查询键变化时旧数据清空、按钮临时禁用再恢复。
- [x] 相邻按钮覆盖为局部颜色过渡和中性悬停态；切换期间保持尺寸与背景稳定，仅在被点击箭头内显示 Spinner，并通过 `aria-disabled` 阻止重复切换；关闭 Sheet 时清理等待状态。
- [x] `npm.cmd run check`、`npm.cmd run build`（2456 modules）与 `git diff --check` 通过；用户在现有本地 Chrome 页面手动切换确认蓝色瞬闪已经消失。
**下一步**：继续第一版目标 Linux 部署门禁；后续如调整统一按钮动态，只修改共享变体和语义 Token，不在页面中新增品牌色特例。
**边界**：本次只修改详情 Sheet 的相邻记录切换反馈，不改后端 API、数据库、全局按钮变体或分页按钮行为；现有前后端进程保持运行。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`


## 2026-08-15 — 修复帖子详情 Sheet 背景跳顶与滚轮穿透

**总目标**：打开、关闭或切换帖子快照详情时保持批次详情背景的滚动位置、列表数据和操作焦点，并在 Sheet 打开期间彻底锁定背景滚动。
**状态**：✅ 前端修复、静态检查、生产构建、自动化和真实 Chrome 滚轮验证完成。
**干到哪了**：
- [x] 详情帖子 ID 的同路由查询参数更新显式关闭 TanStack Router 滚动重置；打开前记录背景 `scrollY` 和触发按钮，Sheet 打开与关闭时以 `preventScroll` 转移焦点并同步恢复背景位置。
- [x] 帖子列表 Query Key 只保留分页、搜索、筛选和排序参数，详情选中 ID 不再触发背景列表重新查询；Sheet 内上一条、下一条继续保持背景位置，跨页时才请求必要列表页。
- [x] 纠正上一轮为处理跳顶而加入的 `overflow: unset !important`：恢复 Radix 对 `body` 的 `overflow: hidden`，并通过 `html:has(body[data-scroll-locked])` 锁定实际页面滚动容器；`position: static` 只负责规避背景跳顶。
- [x] `npm.cmd run check`、`npm.cmd run build`（2456 modules）和 `git diff --check` 通过；Patchright 复核 `body/html` 均为 `overflow: hidden`，遮罩滚轮前后背景保持 `8`，Sheet 内滚动从 `0` 增至 `109`。真实 Chrome 中遮罩连续滚轮前后背景保持 `1390`，Sheet 内滚动从 `0` 增至 `96` 时背景仍为 `1390`，关闭后恢复打开时记录的 `963`，焦点返回原“查看”按钮。
**下一步**：用户刷新现有批次详情页，在遮罩区域与 Sheet 内容区域分别滚动复核；后续第一版主线仍进入目标 Linux 部署门禁。
**边界**：本次不修改后端 API、数据库或服务进程；前端页面级正常导航仍使用默认滚动恢复，仅锁定模态 Sheet/Dialog 打开期间的背景滚动。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/styles/index.css`、`docs/design/product-design.md`、`docs/design/technical-route.md`。
## 2026-08-15 — 修复配置保存后的服务端状态回填与圈子删除

**总目标**：修复“车型与圈子”保存后仍保留无 ID 草稿、删除保存后刷新复现的问题，并审计第一版前端所有数据库写操作后的可见列表一致性。
**状态**：✅ 前后端修复、完整自动化、真实 API 与真实 UI 闭环完成；FastAPI PID 27508 和既有 Vite 服务已加载新代码。
**干到哪了**：
- [x] 圈子批量协议新增显式 `deleted_ids`，后端在同一事务内校验并执行新增、修改和删除，返回带真实 ID、车型名称的剩余行以及保存数、删除数；补齐圈子查询、新增、更新、删除资源接口，删除配置不影响历史批次快照。
- [x] “车型与圈子”保存成功后立即用服务端响应重建本地表格与 Query 缓存，再等待 `/vehicles` 回查；删除已保存行会记录真实 ID，删除新草稿只改变本地状态。提取计划、平台配置和圈子配置只在清洁状态下接收 SSE/焦点回查，未提交草稿保持隔离。
- [x] 审计全部前端写操作：计划和平台已直接使用写响应；手动历史、模板、Session、新建批次、补提、结束认证等待和批次删除改为等待相关 Query 刷新后再反馈；异步圈子验证继续由事件/有界回查刷新。结构化后端行错误现在会进入中文 Toast 详情。
- [x] 后端 `unittest discover` 26/26，`ruff format --check`、`ruff check`、`compileall`、`pip check`，前端 `npm run check`、`npm run build`（2456 modules）及 `git diff --check` 全部通过。
- [x] 重启 FastAPI 后完成非破坏真实 API 冒烟：临时圈子新增可见、批量删除数为 1、刷新后消失且原圈子 24729 保留。真实 React 页面再次完成临时圈子“新增→保存取得验证按钮→删除→保存→刷新”，两次 PUT 均为 200，刷新后临时行消失、原圈子保留；证据 `artifacts/runtime/server-state-sync/circle-save-delete-refresh.png`。
**下一步**：用户可直接在当前页面删除目标圈子并点击“保存当前标签”；后续第一版主线仍按既定计划进入目标 Linux 部署门禁。
**边界**：批量请求遗漏某条记录不自动删除，只有 `deleted_ids` 中的明确 ID 执行删除；本次未删除用户现有圈子 24729，真实 UI 验证只创建并清理了临时圈子。
**关联**：`frontend/src/features/config/config-page.tsx`、`frontend/src/lib/api.ts`、`frontend/src/features/runs/`、`frontend/src/features/auth/auth-dialog.tsx`、`src/threadsnap/app.py`、`src/threadsnap/schemas.py`、`src/threadsnap/services.py`、`tests/test_backend.py`、`docs/design/technical-route.md`。

## 2026-08-14 — 平台认证切换为受控 CDP 实时画面

**总目标**：把平台认证 Dialog 的输入空闲后整帧截图中继替换为后端封装的 CDP Screencast，补齐悬停、拖动和组合键路径，并在保持现有 Profile、Session、任务票据和批次恢复边界的前提下降低本地交互等待。
**状态**：✅ Windows 本地实现、自动化验证和真实 UI 联调完成；FastAPI PID 33576 与 Vite PID 33412 已使用新代码重启，目标 Linux 的 Xvfb 与连续三轮部署门禁仍按 ADR 0011 独立保留。
**干到哪了**：
- [x] 后端通过 Patchright `BrowserContext.new_cdp_session` 在进程内启动 `Page.startScreencast`，使用 `1280 × 800`、JPEG 质量 85、逐帧确认和单帧背压替代原 700 毫秒输入超时截图；前端仍只连接短期认证 WebSocket，不开放原始 CDP 端口。
- [x] 前端认证画布新增按动画帧合并的持续指针移动、按下、释放、拖动、滚轮、右键本地菜单抑制、普通文本、组合键和粘贴；高频移动在 WebSocket 缓冲增长时跳过中间位置，画面 DOM 直接更新，避免每帧触发整棵 Dialog React 状态刷新。
- [x] `patchright==1.61.2` 已从传递依赖提升为 `pyproject.toml` 直接锁定依赖；新增 ADR 0014，并同步产品设计、技术路线、部署说明、文档索引和首平台交付链档。
- [x] 后端完整 `unittest discover` 为 25/25，`ruff format --check`、`ruff check`、`compileall`、`pip check` 通过；前端 `npm run check` 和 `npm run build` 通过，生产构建转换 2456 个模块。
- [x] 重启后经 Vite 反向代理收到 `browser_starting → ready → frame`，固定子协议协商为 `threadsnap-auth`，首帧 JPEG 为 127278 字节并以 1000 正常关闭；三个具有明确视觉变化的指针位置在 12.7 至 25.0 毫秒收到变化帧。真实 React 页面将 1280×800 源画面缩小为 1214×759 显示，搜索框 hover 后 49.3 毫秒取得变化帧；点击、测试文本输入和清空通过，浏览器控制台错误/警告为 0。这些延迟只是当前 Windows 回环单连接冒烟值，不作为固定性能指标。
- [x] 高风险日志门禁发现 URL 查询票据会被 Uvicorn 访问日志记录，随后将票据迁移到 `Sec-WebSocket-Protocol` 候选值并只回显固定子协议；错误票据在握手阶段返回 HTTP 403。重启并完成真实 UI 操作后，前后端四份运行日志中的 `ticket=`、Cookie、Authorization、error 和 traceback 命中均为 0。
**下一步**：在目标 Linux 同一服务管理环境中配置 Xvfb，真实创建认证任务，验证 CDP Screencast、完整指针输入、会话门禁和认证后批次续跑，再恢复 ADR 0011 的连续三轮部署验收。
**边界**：CDP Screencast 绑定锁定的 Chromium/Patchright 版本且接口标记为实验性；本次没有开放调试端口、引入 VNC/WebRTC 服务、提交认证截图或保存测试输入，也没有把 Windows 结果外推为 Linux 已验收。变更没有数据库迁移或 Profile/Session 格式变化，回退可直接撤销本任务提交并恢复上一版 WebSocket 截图中继。
**关联**：`src/threadsnap/auth.py`、`frontend/src/features/auth/auth-dialog.tsx`、`tests/test_backend.py`、`pyproject.toml`、`docs/adr/0014-use-controlled-cdp-screencast-for-auth.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/deployment/backend-v1.md`、`docs/chains/first-platform-delivery.md`。

---

## 2026-08-14 — 修复平台认证白屏并完成真实联调

**总目标**：修复近全屏认证 Dialog 中服务器浏览器只显示白色空页的问题，使人工认证入口真实加载官方页面、区分中继与页面状态，并在门禁通过后安全更新 Profile、Session 和等待批次。
**状态**：✅ Windows 本地修复与真实 UI 联调完成；目标 Linux 的 Xvfb/连续三轮部署门禁仍按 ADR 0011 独立保留。
**干到哪了**：
- [x] 真实对照确认同一登录 URL 在 Patchright 无头浏览器和已安装 Chrome 无头模式下均返回 HTTP 200、`Content-Length: 0`，而 Patchright 随附完整 Chromium 有头持久化上下文返回完整登录页；白屏不是 React Dialog、WebSocket 或 Windows 本身导致。
- [x] 认证管理器改为默认启动完整 Chromium 有头持久化上下文，并新增 `starting/loading/ready/validating/failed/completed` 页面生命周期；只有非空可交互 DOM 才进入 `ready`，HTTP 错误、零字节响应和空 DOM 返回稳定错误码及中文原因。
- [x] 每次认证使用独立临时 Profile；正式 Profile 以 Fernet 加密 ZIP 归档保存，成功门禁后关闭浏览器、加密并原子替换 Profile，再恢复对应平台等待队列；校验失败保留旧 Session/Profile 和当前页面，启动时清理异常退出遗留任务目录。
- [x] 前端将“中继已连接”和“页面可操作”分开显示，增加加载失败 Alert、阶段语义色、失败后重新创建浏览器、未就绪时禁用输入与提交，并用 `insert_text` 支持中文/粘贴文本中继。
- [x] 新增 5 个认证专项测试，完整后端 `unittest discover` 为 23/23；`ruff check`、`compileall`、前端 `npm run check` 和 `npm run build` 均通过，生产构建转换 2456 个模块。
- [x] 本地启动独立数据目录的 FastAPI 与 Vite，通过真实页面点击“去认证”后取得官方手机验证码登录页，Dialog 显示“页面可操作 / 中继已连接”；鼠标定位和 11 位测试文本经前端 WebSocket 成功写入服务器浏览器输入框。视觉证据位于被 Git 忽略的 `artifacts/runtime/auth-component-live/auth-dialog-ready.png` 和 `auth-dialog-input-relay.png`，浏览器控制台错误/警告为 0，测试服务和认证浏览器已停止。
**下一步**：在目标 Linux 的同一服务管理环境中配置 Xvfb，真实创建认证任务并完成一次人工认证与圈子门禁，再继续 ADR 0011 保留的连续三轮部署验收；该门禁通过前不把 Windows 结果外推为 Linux 已验收。
**边界**：本次没有输入真实手机号、短信码或账号密码，也没有把登录页可见误记为 Session 门禁已通过；自动化测试覆盖成功提升与失败回滚，真实账号认证仍由项目负责人在目标环境自行完成。
**关联**：`src/threadsnap/auth.py`、`src/threadsnap/config.py`、`frontend/src/features/auth/auth-dialog.tsx`、`frontend/src/components/status-badge.tsx`、`frontend/src/lib/types.ts`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/deployment/backend-v1.md`。

---

## 2026-08-14 — 完成第一版前后端闭环

**总目标**：基于已确认的 React + Vite 控制台方案完成第一版全部前端页面，同时补齐页面联调所需的后端配置、调度、实时信号、筛选分页、结果导航与新数据库基线，形成前后端分离的单平台完整产品闭环。

**状态**：✅ 第一版产品功能与代码闭环完成，Windows 前后端联调和真实 UI 验收通过；⏸ ADR 0011 已暂缓的目标 CentOS 连续三轮仍属于独立部署验收门禁，不在本条中记为通过。

**干到哪了**：
- [x] 新建 `frontend/` React 19、TypeScript、Vite、Tailwind CSS、shadcn/ui、TanStack Router/Query/Table、Lucide 和 Motion 工程；选择性复用 `satnaing/shadcn-admin` 2.2.1 的应用外壳与 UI 原语，并固定上游提交 `e16c87f213a5ba5e45964e9b67c792105ec74d26`、MIT 许可和第三方声明。
- [x] 完成中文化应用外壳、动态收缩侧栏、移动端 Sidebar Sheet、系统/浅色/深色主题、路由懒加载、真实 SSE 连接状态和统一反馈组件；断点实测在 1024、768、640 像素下均无页面级横向溢出。
- [x] 完成提取计划、平台与 Session、车型与圈子、手动圈子历史、导出模板五个配置标签；标签切换保留草稿、离开脏页面确认、保存只提交当前标签，星期与 24 小时制 `HH:mm:ss` 计划节点和可复用规则已真实保存。
- [x] 完成批次列表、新建提取 Sheet、圈子发现与 URL 清单双模式、服务端筛选分页、状态变化高亮、失败项补提、等待认证入口、近全屏 WebSocket 认证 Dialog、结束等待和终态删除确认。
- [x] 完成批次详情、任务进度、帖子服务端筛选排序分页、单条与完整筛选结果批量复制、非安全上下文复制回退、XLSX 导出、快照详情 Sheet，以及跨页上一条/下一条导航。
- [x] 后端新增规则版本与每周计划节点模型、原子计划保存与冲突校验、调度快照、稳定来源位置、集合加载批次摘要、数据库侧去重筛选排序分页、帖子详情/URL/导航接口和进程内有界事件总线；浏览器认证继续使用 WebSocket，普通状态变化由 SSE 信号触发前端回查 `/api/v1`。
- [x] 用全新 Alembic 基线 `8d3806d229c1` 替换未交付的旧基线；唯一临时数据库从零升级后生成 18 张表，`/health`、提取计划和 OpenAPI 事件路由冒烟通过。新 wheel 已确认只包含新迁移，不包含已删除的旧迁移。
- [x] 后端 `ruff format --check`、`ruff check`、`compileall`、`pip check` 通过；业务测试 18/18、PoC 回归 64/64 通过。前端 `npm run check` 和 `npm run build` 通过，生产构建完成 2456 个模块转换。
- [x] 真实浏览器完成深浅主题、导航收缩、配置草稿与离开确认、计划保存、认证窗口、批次列表/详情、等待认证与危险确认、帖子跨页导航、模板字段与批量复制验收；浏览器控制台错误与警告为 0。
- [x] 新增前端开发与同源反向代理部署说明，更新产品设计、技术路线和文档索引；前端只调用 `/api/v1`，后端继续保留回环 `/internal/v1`，未新增 BFF 或第二套业务后端。

**下一步**：第一版不再有待实现的产品功能；准备正式 Linux 部署时恢复目标 CentOS 连续三轮门禁并确认 CPU/进程管理方式，后续两个平台按统一采集器契约分别接入，三个平台完成后再以真实前端生成完全可实现的 Figma 设计稿。

**边界**：本条“第一版完成”指一个平台的前端、后端、调度、认证、批次、结果与导出产品闭环及 Windows 验证；不包含后续两个平台、公网身份权限、Figma 设计稿，也不把暂缓的 CentOS 三轮描述成已验收。

**关联**：`frontend/`、`src/threadsnap/`、`src/threadsnap/migrations/versions/8d3806d229c1_v1_fresh_baseline.py`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/deployment/frontend-v1.md`、`docs/adr/0011-adopt-python-backend-before-deferred-linux-gate.md`、`docs/adr/0012-adopt-shadcn-admin-ui-baseline.md`、`docs/adr/0013-use-versioned-extraction-rules-and-weekly-schedule-nodes.md`。

---

## 2026-08-14 — 第一版前端方案访谈

**总目标**：在既有 `/api/v1` 页面接口和三个基础页面范围内，收敛第一版前端的信息架构、视觉系统、动态交互、框架复用边界和真实 UI 验收口径。

**状态**：✅ 第一版前端方案访谈完成；前端技术栈、信息架构、主要交互、实时状态、表格、主题、配置唯一归属以及自动提取规则与每周计划节点边界均已确认。

**干到哪了**：
- [x] 第一版前端定位为现代、数据密集、桌面优先的内部运营控制台，不增加独立工作台或营销展示页。
- [x] 三个基础页面共用可收缩左侧导航；导航展开、收缩、当前项切换和内容区变化必须连续过渡，动画服务于真实状态并支持系统减少动态效果偏好。
- [x] GitHub 初筛确认 `satnaing/shadcn-admin` 为 MIT 许可的 Vite、React、TypeScript、shadcn/ui 控制台实现，包含响应式、可访问性和内置 Sidebar；其 README 明确说明自身不是 starter，因此当前只作为可复用外壳与组件候选，不直接宣布为项目基线。
- [x] `Kiranism/next-shadcn-dashboard-starter` 同为 MIT 许可且功能更完整，但绑定 Next.js、Clerk、组织、计费和 SSR 数据模式，与第一版受控内网、FastAPI 页面 API 和最小范围相比清理成本更高，当前不作为首选。
- [x] 已确认采用 React、TypeScript、Vite、shadcn/ui、Tailwind CSS、TanStack Router/Query/Table、Lucide 和 Motion for React；选择性复用 `satnaing/shadcn-admin` 的应用外壳和 UI 原语，不整仓继承无关示例业务。
- [x] 已定义 UI 特性保留线：主题 Token、Sidebar/Header、导航状态、响应式 Sheet、表格与弹层原语、键盘触发、状态持久化、宽度/位置过渡和可访问性基础保持；裁剪只作用于 Clerk、示例登录、用户、图表、假数据及无关 SaaS 页面。
- [x] 新增 ADR 0012，并同步技术路线和文档索引；后续实施必须固定上游提交、保留 MIT 许可与来源，并用组件和视觉证据防止 UI 基线在业务裁剪中退化。
- [x] 手动提取入口固定为提取列表页右上角“新建提取”主按钮，打开右侧全高动态 Sheet；Sheet 内承载“圈子发现 / URL 清单”，成功后退出并在列表顶部动态插入新批次，校验失败时保留上下文并定位错误。
- [x] 新建提取 Sheet 采用单页渐进式表单和固定底部操作栏；仅展开当前输入方式的字段并就地显示验证、去重与解析结果。
- [x] Sheet 打开期间分别保留两种输入模式的内容，提交只读取当前模式；关闭、返回或切换页面时直接放弃未提交输入，不显示确认且不跨刷新恢复。
- [x] 配置管理页采用“提取计划、平台配置、车型与圈子、手动圈子历史、导出模板”五个横向动态标签；当前标签进入 URL 状态并支持刷新、前进和后退恢复，不增加第二层侧边导航。
- [x] 批次状态刷新改为 SSE 轻量变化信号驱动：前端收到资源 ID、事件类型和摘要版本后按需回查权威 HTTP 数据；SSE 重连、重新聚焦和网络恢复时完整刷新，并保留六十秒低频兜底与手动刷新。
- [x] 认证画面和输入继续使用 WebSocket，普通批次、验证和 Session 变化使用 SSE；第一版通过进程内事件总线连接同一 FastAPI 进程中的 API、调度器和 Worker，多进程以后再升级跨进程事件通道。
- [x] 代码复核发现当前 `list_runs` 的 50 行刷新约产生 52 至 102 条 SQL 语句；SSE 已减少无变化查询，但事件触发回查仍需改为集合加载圈子任务和队列位置，并在 Worker 并行场景验证 SQLite 锁等待与接口延迟。
- [x] 平台认证画面采用接近全屏的动态 Dialog；平台配置中的 Session 卡片和批次列表“去认证”入口复用同一认证流程组件，但 Session 卡片本身保持紧凑，只展示状态、最近验证时间和操作入口。
- [x] 批次帖子结果区分两种操作：标题在新标签打开平台原帖，“查看”打开占页面约 50% 至 60% 的右侧快照详情 Sheet；Sheet 展示数据库快照、保留列表上下文，并按当前筛选排序支持上一条和下一条。
- [x] 代码复核发现结果接口当前只支持 `offset/limit`，并在服务层加载关联批次全部帖子后于内存去重和切片；前端联调前需补齐后端标题、圈子、可见状态筛选及数据库侧稳定去重分页，避免只搜索当前页或随结果量全量加载。
- [x] 暂定结果表格无复选框；单条复制规范化原帖 URL，批量复制当前完整筛选结果并按汇总规则去重，一行一个 URL。Clipboard API 受内网非安全上下文限制时打开只读、自动选中的手动复制 Dialog，模板字段标签复制复用相同回退。
- [x] 帖子结果表默认列确认为“标题、圈子、作者、发布时间、可见状态、评论数、点赞数、操作”；平台放在批次摘要中，完整 URL 和长内容进入快照详情 Sheet，右侧操作列提供查看与复制链接。
- [x] 帖子结果表确认复用 shadcn/ui 与 TanStack Table 分页组件，前端页码变化通过 TanStack Query 请求后端；默认 50 条，可选 20、50、100 条，后端按完整搜索、筛选、排序和去重结果执行集合分页并返回总数。
- [x] 第一版 UI 文案以中文为主，上游英文示例文案不进入交付界面；仅保留 URL、ID、Session、API、SSE、WebSocket、Excel、XLSX 等必要专业术语，操作名称使用中文动词组合。
- [x] 主题初次访问跟随系统，顶部允许切换浅色、深色和跟随系统并持久化用户选择；复用上游主题 Token，项目新增状态、表格和弹层必须同时覆盖两种主题。
- [x] 国际化实现确认采用中文直接实现，省略完整翻译运行时和语言切换入口；公共文案集中维护，日历与日期显式使用 `zh-CN`，通过专业术语允许清单、自动化 DOM/无障碍文案扫描和真实页面检查拦截上游英文残留。
- [x] 帖子结果默认保持 URL 输入、圈子提交和平台发现的稳定来源顺序；补提成功项回填原失败 URL 的逻辑位置，发布时间、评论数和点赞数可由后端全结果排序，批量复制沿用当前排序。
- [x] 代码复核确认现有 `queue_sequence` 与 `order_index` 只能覆盖任务和单任务顺序；当前按创建时间合并会把补提结果放到后部，前端联调前需补齐跨关联批次的稳定来源位置并用于去重、排序和分页。
- [x] 帖子结果页的搜索、筛选、排序、分页、每页数量和当前详情帖子同步到类型化 URL 查询状态；刷新、前进、后退和分享链接恢复上下文，返回键可关闭详情 Sheet，URL 不保存快照内容或凭证。
- [x] 提取批次列表采用无复选框的数据表格，以“批次编号、提取范围、状态、进度、时间、操作”六组组合列覆盖全部必要信息；普通行进入详情，行内操作独立执行，SSE 更新只过渡实际变化的字段。
- [x] 批次列表筛选栏保留批次编号、状态、触发类型和创建时间范围，右侧提供重置、刷新和新建提取；筛选与分页同步 URL 并由后端对完整集合执行，第一版不增加平台筛选。
- [x] 代码复核确认现有批次列表接口只支持 `offset/limit`；前端联调前需补齐四项筛选、筛选后总数和数据库侧分页，并与现有批次摘要集合查询优化一并验证。
- [x] 失败批次的用户操作统一命名为“重新提取失败项”；确认 Dialog 显示原批次和失败项数量，明确只创建关联批次并保留原快照，“手动补提”继续作为内部领域简称。
- [x] 操作列采用文字与图标的响应式组合；含义明确或空间受限时允许仅图标按钮，但必须提供中文 Tooltip、`aria-label`、焦点态和足够点击区域，特殊业务动作保留文字，危险及过多的次要操作收敛到更多菜单。
- [x] 响应式边界确认为 1280px 完整桌面、1024px 收敛次要信息、768px 切换动态 Sidebar Sheet；窄屏表格保持同一结构并横向滚动，低于 768px 保证基础操作但不另建手机卡片版，认证 Dialog 始终接近全屏。
- [x] 主视觉暂定冷白/深海军蓝表面、靛蓝主色和青色高光，语义状态色保持独立；全部颜色通过浅深主题语义 Token 集中映射，允许在 Figma 或真实 React 页面评审后整体换色而不修改业务组件。
- [x] 第一版暂不制作 Figma，直接以真实 React 页面验证视觉与动态；三个平台全部完成后再采用 code-to-design 建立设计稿，Figma 变量和组件映射必须对应实际前端，新增设计先通过可实现性评审并回到代码验证。
- [x] 第一版不设置独立主观视觉确认阶段，优先完成真实功能闭环和功能完整性；未来感通过统一 Token、公共组件和命名变体维持，同组件同规格必须一致，Dialog、Sheet 等差异只能来自集中定义的用途变体而非页面级单独设计。
- [x] UI 组件采用“上游现有组件、官方 shadcn/ui、应用级组合、确有缺口时新增”的优先级；Alert、AlertDialog、Sonner、Progress、Skeleton、Spinner、Empty、Tooltip 和 Badge 等反馈原语优先复用，页面不重复制作同类视觉组件。
- [x] 用户已把具体反馈组件映射交由实现侧决定；当前按字段错误、业务 Alert、危险确认、成功 Toast、页面进度、加载占位和空状态的语义选用框架组件，后续只在反馈改变业务阻塞或确认流程时再请求产品裁决。
- [x] 配置页的提取计划、平台配置、车型与圈子采用按标签隔离的显式保存；切换标签保留暂存内容，保存只提交当前标签，离开或刷新且存在未保存内容时提示确认，历史和模板独立操作即时提交。
- [x] 全局计划需求已从每日 `HH:mm` 升级为可选星期与 24 小时制 `HH:mm:ss` 的每周循环规则；前端组合 shadcn/ui 星期多选和时间原语，第一版数据库基线、API、分钟调度与幂等契约需直接替换为新模型。
- [x] 自动调度模型改为“每周计划节点选择可复用自动提取规则”：节点只拥有星期、时分秒、启用状态和规则引用，定时数量等业务参数只在“提取计划”规则区编辑；平台配置只拥有接入、并发、启用和 Session，车型与圈子只拥有来源、验证和自动参与资格，跨标签只读引用而不重复编辑。第一版新数据库基线直接由规则持有平台数量，触发批次冻结规则版本快照；新增 ADR 0013。
- [x] 第一版自动提取规则不选择平台、车型或圈子；计划节点触发时读取当时全部已接入、平台已启用且圈子已启用自动提取的来源。提取计划不复制来源选择器，来源资格继续由平台总开关和圈子自动参与开关分别唯一维护。
- [x] 自动提取规则第一版可编辑字段收敛为规则名称和各已接入平台每圈有效结果目标数；规则 ID、版本和更新时间只读。规则不包含平台并发、启用、Session、重试、安全限制、评论数量、发现顺序、时间或来源选择，也不增加规则启用开关；暂未接入平台不显示可编辑数量。
- [x] 规则修改生成同一逻辑规则的新版本，节点未来触发自动使用最新版，批次冻结并展示触发时版本。启用或停用节点只要仍引用规则就阻止归档和删除；解除引用后，从未形成批次的规则可永久删除，已有历史使用的规则只归档并可恢复，历史快照不变。
- [x] 所有启用计划节点按逐日展开后的“星期 + `HH:mm:ss`”全局唯一；多选星期发生任一重叠时整份提取计划保存失败并返回全部冲突定位。停用节点允许暂存重叠但启用时重新校验，系统不自动合并或覆盖冲突节点，调度加载保留防御性检查。
- [x] 第一版采用全新数据库基线；仓库没有需保留的正式 SQLite 数据库，开发与测试数据库重新创建，不转换旧 `times` 或平台自动数量，也不自动生成默认规则。首次使用由用户自行创建规则与节点，后续正式交付后的结构变化再使用新增迁移。
- [x] 新平台接入后默认停用；启用前校验全部启用节点所引用规则是否补齐该平台数量，缺失项只在提取计划编辑，平台页只提供摘要和跳转。节点启用时校验全部已启用平台参数；调度异常缺失时停止整个节点触发，不静默跳过平台或创建不完整批次。

**下一步**：依据已确认产品设计和 ADR 0012/0013 创建 React + Vite 前端工程，固定 `satnaing/shadcn-admin` 上游提交，先落地应用外壳、中文主题基线和三页路由，再按后端契约缺口顺序实现配置、批次列表与批次详情。

**边界**：本条记录已确认的前端产品方向和技术基线；当前仍没有创建前端工程、拉取第三方源码或修改后端接口。实施时只引入本项目实际使用的上游模块，并保持第三方来源与许可证可追溯。

**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/adr/0008-v1-backend-exposes-frontend-and-integration-apis.md`、`src/threadsnap/app.py`。

---

## 2026-08-14 — 完成第一版提取后端

**总目标**：在用户明确暂缓 CentOS 连续三轮门禁的前提下，完成懂车帝动态/最新回复圈子发现、事前固定 2000 条有效样本、持久队列、双接口、认证续跑、结果管理和 XLSX 模板导出后端。

**状态**：✅ 第一版提取后端、Windows 真实闭环和交付验证已完成；目标 CentOS 三轮仍按 ADR 0011 暂缓。

**干到哪了**：
- [x] 圈子 `24729` 已验证 42 页、1259 个唯一动态候选、跨页最新回复顺序与第 43 页空页停止；候选清单 SHA-256 为 `81acb993abf36d8ef19e6c9464d1f5dbab03b3bf84cfe778b4393ae64876d0d1`。
- [x] 事前固定 2000 条有效样本，URL 清单 SHA-256 为 `24f921036677c8d1ce933a81ec10d15a700c765fccf3401121a99787f0f9f21e`；2500 条候选中有 2025 条当前有效且可用字段完整，固定取前 2000 条。
- [x] 新增 Python/FastAPI 应用、SQLAlchemy 领域模型、Alembic 首版迁移、SQLite 第一版持久化、`/api/v1` 和回环限制的 `/internal/v1`。
- [x] 实现全局多时间调度、定时幂等、平台 FIFO、平台内部并发安全收敛、进程重启恢复、认证只阻塞对应平台。
- [x] 实现懂车帝直接 HTTP 列表优先、SSR 不足时浏览器补全、详情与最多 10 条一级评论接口，并按有效结果数继续翻页补足。
- [x] 实现 Fernet 加密平台 Session、既有 Session 有界自动刷新、`waiting_for_auth`、Patchright 服务器官方页面 WebSocket 中继、真实样本验证后续跑。
- [x] 实现手动圈子历史、中文错误、幂等提交、终态删除、只补提失败 URL、原批次与补提结果去重汇总。
- [x] 实现多模板不可变版本、稳定英文标签校验、一帖一行、评论/媒体单元格编号换行、样式复制、冲突错误和结果版本复用。
- [x] 正式采集器真实圈子冒烟为 30/30 有效、0 失败、10.166 秒，摘要 SHA-256 为 `87c10faa23e1a9043015581c56215a917d98ac56c6ca10f4877e64bdca5c44ae`。
- [x] 真实端到端链路的会话导入、圈子保存/验证、手动提取 3/3、结果查询、模板上传和 XLSX 下载 10 个接口全部返回 200/202，摘要 SHA-256 为 `c256ba7aa13fa8862d749459b34ed0f1fdccd497589908e10a670fb9a3077510`。
- [x] ADR 0011 已接受：采用 Python 第一版后端，目标 CentOS 三轮从开发前置调整为暂缓的最终部署验收门禁。
- [x] `python -m unittest discover -s tests -v` 为 18/18，`python -m unittest discover -s poc/shared/tests -v` 为 64/64；`ruff format --check`、`ruff check`、`compileall`、`pip check` 和 `git diff --check` 全部通过。
- [x] 最终源码 wheel 独立安装后由包内 Alembic 资源创建 15 张表；wheel SHA-256 为 `4bec552d1496a5728c2b83c0c97c2a6328de9300ec8385fccf719fa95eec148c`。
- [x] 134 个候选提交文件与本地 33 个真实 Cookie 值比对为 0 命中；Git 中敏感状态文件和具体 Cookie/Bearer 凭证形态均为 0 命中。

**下一步**：前端按 `/api/v1` 联调第一版配置、队列、认证和导出页面；准备最终 Linux 部署时，再恢复目标 CentOS 连续三轮门禁及服务管理验收。

**边界**：本条只宣布第一版提取后端和 Windows 真实闭环，不宣布前端、公网权限、后续两个平台或目标 CentOS 三轮已完成。业务运行目录、Session、模板、导出和原始验证证据均不进入 Git。

**关联**：`src/threadsnap/`、`src/threadsnap/migrations/versions/84d25130bc33_v1_backend_schema.py`、`tests/test_backend.py`、`docs/adr/0011-adopt-python-backend-before-deferred-linux-gate.md`、`docs/deployment/backend-v1.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`。

---

## 2026-08-14 — 第一版后端领域契约与交付边界

**总目标**：把已逐项确认的第一版配置层级、统一调度、平台队列、手动/定时提取、补提、认证阻塞、中文错误和 XLSX 模板规则写入唯一 owner 文档，为技术选型门禁通过后的后端实现提供无歧义契约。

**状态**：✅ 产品和技术业务契约已确认并同步；⏸ 正式后端业务代码继续遵守 ADR 0003 的技术选型前置门禁，尚未在本任务中创建绑定候选栈的生产工程。

**干到哪了**：
- [x] 第一版只有懂车帝可执行；其他平台可以展示和保存配置，但以 `not_integrated` 禁止启用和创建任务。懂车帝功能样本固定为风云A9车友圈 `24729`，范围为动态版块的最新回复顺序。
- [x] 配置拆成一个全局提取时间、每平台共享的自动数量/内部总并发/启用状态，以及车型下的多个平台圈子；手动提取另有本次统一数量和永久手动圈子历史。
- [x] 一个全局调度源创建顶层批次，手动、定时和手动补提按平台严格 FIFO；配置入队后冻结。认证只阻塞对应平台，第一版平台级并发固定为 1，平台内部并发由前端配置并服从后端安全范围。
- [x] 自动重试仍属于原批次且只处理未成功 URL；终态手动补提创建关联批次，前端按圈子展示剩余批次的最新成功结果，不物理合并或改写快照。
- [x] 普通排队中和提取中不提供取消；等待认证可以二次确认“结束本次提取”释放平台队列；终态可以二次确认事务级永久删除。
- [x] 双接口使用稳定英文错误码、后端中文详情、`request_id` 和幂等键；批量车型/圈子保存为全量校验后的单事务写入。
- [x] 多个 XLSX 模板按不可变版本保存，以稳定英文标签绑定字段；标签注册表、上传校验、一个帖子一行、集合单元格格式、样式复制、冲突处理和导出复用规则已写入产品与技术文档。
- [x] 新增 ADR 0009 和 ADR 0010，并同步登录 ADR、双接口 ADR、领域词汇、产品设计、技术路线、首平台链档、文档索引及长期项目约束。
- [x] 项目 `.vevn` 的 64 项 `poc/shared` 测试通过；六组旧口径冲突扫描全部清零，六个关键契约引用均可检索，`git diff --check` 通过。

**下一步**：先用圈子 `24729` 完成动态/最新回复列表身份、分页、顺序、候选 URL 和停止条件 PoC；再事前形成当前可访问的固定 2000 条样本，在目标 CentOS 连续执行三轮硬门禁并形成技术栈 ADR。门禁通过后，按本契约建立数据库迁移、双接口应用层、持久队列、懂车帝适配器、模板导出和第一版前端闭环。

**边界**：2000 URL/小时是技术选型与完工性能门禁，不是业务固定提取数量。圈子验证先匿名访问，只有明确登录或身份异常才进入官方认证；网络、限流和其他平台控制不能直接解释为需要登录。平台安全上下限和正式数据库/Worker/调度/XLSX 依赖仍须由 PoC 与技术栈决定。

**关联**：`docs/adr/0003-package-poc-for-linux-before-formal-development.md`、`docs/adr/0009-global-scheduler-and-platform-fifo.md`、`docs/adr/0010-versioned-tag-driven-xlsx-templates.md`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`。

---

## 2026-08-13 — 第一版自建前端与双接口提取后端

**总目标**：第一版采用自建 Web 前端和一个独立提取后端完成真实前后端闭环；同一后端同时提供页面 API 和稳定集成 API，确保后续客户现有后端可以直接接入而不重构提取领域。

**状态**：✅ 架构口径已确认并同步；ADR 0008 已接受，ADR 0001 的提取领域所有权保持不变。

**干到哪了**：
- [x] 第一版前端只调用提取后端的 `/api/v1` 页面接口，不调用后续集成接口，也不接触平台私有接口和认证数据。
- [x] 同一提取后端通过调用方无关的 `/internal/v1` HTTP/JSON接口向后续客户现有后端提供异步任务能力；两套控制器共用应用层和领域实现。
- [x] 提取后端持续拥有平台适配器、任务调度、Session、检查点、数据库事务、批次状态和XLSX生成，不为两套接口复制业务逻辑。
- [x] 第一版不增加第二个业务后端，不引入服务注册、消息总线、分布式事务或平台采集代理层。
- [x] Candidate A若通过最终门禁，推荐采用单个Python代码库：FastAPI承载两套API，Scrapling负责采集与浏览器Session；API与Worker可独立运行但属于同一服务边界。该映射尚不等同于最终技术栈选型。
- [x] 后续客户现有前后端停用第一版前端入口并复用 `/internal/v1`；提取后端及其数据不迁移、不复制。
- [x] 六份owner、ADR、链档和账本文档的双接口覆盖检查通过，未残留“双业务后端”口径；项目 `.vevn` 的64项 `poc/shared` 测试及 `git diff --check` 通过。

**下一步**：技术栈确认后，先定义共享应用用例以及 `/api/v1`、`/internal/v1` 的资源、异步任务、错误、幂等和调用追踪契约，再建立第一版前端与独立提取后端工程入口；组合验收必须从前端真实触发完整提取闭环，并对集成接口执行独立契约测试。

**边界**：Python直接作为第一版后端是推荐映射，但仍需Candidate A完成最终技术选型门禁；页面API不得成为集成API的别名，集成API也不得暴露给浏览器。第一版不提前引入第二个业务后端或分布式基础设施。

**关联**：`docs/adr/0001-extraction-service-owns-extraction-data.md`、`docs/adr/0008-v1-backend-exposes-frontend-and-integration-apis.md`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`。

---

## 2026-08-13 — 第一版平台登录与 Session 续期优化

**总目标**：把第一版登录方式从“数据库明文保存平台账号密码”调整为“内网客户机浏览器操作服务器官方登录页面、加密 Session、有界自动刷新、认证后自动续跑原批次”，同时保持当前懂车帝单平台基础闭环范围。

**状态**：✅ 产品与技术口径已确认并同步；历史 ADR 0002 已由 ADR 0007 替代，正式实现不接收、不保存目标平台账号密码。

**干到哪了**：
- [x] 产品设计确定第一版只维护一套全局懂车帝 Session；配置页面只显示状态和最近验证时间，提供“登录/更新会话”“清除会话”，不提供平台账号密码输入框。
- [x] 浏览器进程、Profile 和 Session 位于服务器；第一版客户从受控内网客户机的普通浏览器，通过基础测试界面的临时嵌入式入口操作服务器浏览器中的平台官方页面，普通外链和客户机本地登录状态不作为服务器 Session。
- [x] 第一版不建设应用用户、角色、MFA、WAF 或公网远程入口；内部交互使用短期一次性认证任务票据，CDP/VNC 等原始端口不对客户机开放。公网接入仅作为后续可选增强，不进入当前实现与验收。
- [x] 身份异常先暂停新请求并保留触发 URL，每个失败事件只对既有加密 Profile 自动刷新一次；官方页面仍登录且少量门禁通过时从触发 URL 继续。
- [x] 出现登录表单、扫码、短信、验证码、滑块或刷新后门禁失败时，停止新请求并持久化当前索引、触发 URL 和待处理队列，批次转为 `waiting_for_auth`，释放 Worker 和事务；所有依赖同一全局 Session 的新任务暂停采集。
- [x] 客户完成服务器浏览器认证后，系统自动加密替换 Session、关闭临时通道、执行 1 至 3 条门禁并续跑同一批次；认证窗口断开或超时只关闭交互入口，检查点继续等待，不要求人工重试批次。
- [x] Cookie、LocalStorage、浏览器 Profile 等 Session 状态作为敏感凭证加密保存，密钥与数据库分离；接口、日志、错误、导出、截图、测试报告和 Git 不得包含可复用认证数据。
- [x] ADR、领域词汇、产品设计、技术路线、文档索引和首平台工作线已同步；历史 PoC 的本地明文测试配置仅保留为测试证据，不迁移为正式实现规范。
- [x] 文档一致性检查确认八份 owner、链档、PoC说明和账本文档均采用“第一版受控内网浏览器入口、公网后续可选、服务器 Session、`waiting_for_auth` 自动续跑”口径，未发现第一版必须公网鉴权或旧的失败终态/人工重试表述；项目 `.vevn` 的64项 `poc/shared` 测试及 `git diff --check` 通过。

**下一步**：第一版功能开发时先落地平台 Session 状态模型、加密存储边界、`waiting_for_auth` 批次检查点和自动续跑状态机，再接入内网客户机浏览器到服务器浏览器的临时嵌入式交互组件；KasmVNC、noVNC 或其他候选在技术栈和目标 Linux 兼容性确认后选择。

**边界**：本次只确定第一版内网平台认证与 Session 生命周期，不新增多账号、账号轮换、自动接码、验证码识别、长期浏览器托管或公网身份权限，也不扩展当前第一版业务范围。等待认证是持久化批次状态，不长期占用采集进程、数据库事务或公开浏览器控制端口；公网部署留作后续按需增强。

**关联**：`docs/adr/0007-official-login-and-encrypted-platform-session.md`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`。

---

## 2026-08-13 — Candidate A Linux 内容 API 包

**总目标**：把 Windows 已验证的 Scrapling 字段级 HTTP API 提取路径纳入现有 Linux PoC 包，在目标 CentOS 复用已登录 Session，先做最多3条门禁，再对固定输入执行详情、媒体和最多10条一级评论提取；批量阶段不得逐条启动浏览器。

**状态**：✅ 目标 CentOS 首轮2000条已完成复核：可取得详情的1645条字段完整率为100%，355条来源已丢失；确认后的标题、纯媒体和状态规则已写入提取器，0.2.20完整包与免重装补丁均已验证。

**干到哪了**：
- [x] 新增 `poc/linux/run-content-api.sh`：读取 Candidate A 的 `storage-state.json`，先以并发1执行1至3条内容 API 门禁，全部完整后才按 `content_api_concurrency` 启动计划分母；批量阶段只运行 `content_extraction.py` 的 `Spider + FetcherSession`，记录资源指标并打包完整结果。
- [x] 门禁和批量结果现区分 `login`、`captcha`、`challenge`、`rate_limited`、空响应与普通 API 错误；Session 缺失或门禁受控时指向现有 `bootstrap-sms-session.sh candidate-a`，不在2000条计时窗口中自动重登或拼接新轮次。
- [x] 评论完成口径按用户确认改为接口本次实际返回：达到10条或 `has_more=false` 即完成；详情回复数、评论总数和实际返回不一致只保留 `comment_count_consistent` 诊断，`has_more=true` 但游标缺失、接口失败或控制响应仍为不完整。
- [x] Linux 配置、健康检查、README 和构建清单已纳入内容 API 入口及全部本地 Python 依赖；新增结构测试保证门禁先于批量、状态文件复用且运行脚本不包含浏览器 Session 类。
- [x] 当前验证：项目 `.vevn` 的64项 `unittest` 全部通过；Python `compileall`、`pip check`、新增/修改 Shell 的 Bash 语法和 PowerShell 构建脚本解析均通过。
- [x] 从源码提交 `71fbdb19354af63891d64da136d96b5a659d3900` 构建 `artifacts/poc/packages/linux-dual-runner/threadsnap-poc-dual-runner-0.2.19-linux.tar.gz`，外层 SHA-256 为 `721e2f5df9988c90f51e167153fb80a8da4605cbb24d6c542232b412931e931f`；解包后37/37项内部校验通过，13个 Shell 脚本语法和提取目录 Python 编译通过，38个文件中无 `config.json`、`storage-state.json`、输入清单或 `profiles/` 运行状态。
- [x] 针对目标主机已有0.2.17运行状态补充免重装包 `threadsnap-content-api-hotfix-0.2.19.tar.gz`，SHA-256为 `a3f14b3c24ac2b59f97f5dffd4e86ec5aa2d6697ec46a3a35d0097ad7f11f72a`；以0.2.1基础目录合成覆盖验证确认14/14文件、Python编译和3个关键Shell语法通过，且 `.runtime`、配置、输入与Session均保持不变。该补丁累计包含Candidate A所需的0.2.18变更，不补Candidate B的0.2.18文件。
- [x] 目标Linux结果包外层SHA-256 `f8a8fb443c8cf0aaa6e368d8044cfa5f875b0cfea17095ebf34dc5c5e8e19c3c` 与回传值一致，顶层12项以及gate/bulk各4项内部校验全部通过；输入2000条互不重复、结果2000条互不重复且顺序一致，输入SHA-256为原固定清单 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70`。本地脱敏复核摘要已加入人工核对和新分母，位于同目录旁的 `content-api-round-1-20260813T111930+0800-verification.json`，SHA-256为 `d9e18650a2935c6b650523a13ffc4592faf8eda36a16778ae1582641612c10c6`。
- [x] Linux门禁3/3完整；批量并发8在130.243秒形成2000/2000终态，处理15.36 URL/秒、3130次HTTP请求、放大率1.565。全部HTTP 200，无登录/验证码/挑战/限流，页面请求和浏览器进程均为0；最大RSS约83.1MiB。原运行器按旧规则输出1634/2000（81.7%），该原始证据不覆盖。
- [x] 用户复核确认355条空详情对应页面已丢失、9条空正文全部为纯图片帖、2条 `operation_status=2` 页面可见。按确认规则，可取得详情1645条、字段完整1645/1645（100%），来源可用率1645/2000（82.25%）；4987条一级评论均完成接口本次返回判定。600条详情/评论计数差异只作诊断。`operation_status=2` 的官方枚举语义仍未取得，只按已核对样本映射并保留原始值。
- [x] 标题规则确认为：优先平台标题；无平台标题但有正文文字时取第一句话；标题和正文都没有时为空。纯图片或纯视频帖子在媒体URL已正确提取时，空正文和空标题属于完整结果。
- [x] 从源码提交 `68af73f15836d36bbf47b9b8333f4d80821f462e` 构建 `threadsnap-poc-dual-runner-0.2.20-linux.tar.gz`，SHA-256为 `ebc34a439a8ac06018fba832e48f78c60aa9da206578e8e8cb9f6810753f07e1`；37/37项内部校验、Python `compileall` 和敏感运行文件排除通过。另生成仅覆盖解析器与README的 `threadsnap-content-semantics-hotfix-0.2.20.tar.gz`，SHA-256为 `eea8765939fe596305a51e51260b5e935f866a9c54f07a75c4a67b746a8d72cf`；补丁使用独立 `HOTFIX-SHA256SUMS`，在0.2.19完整包上覆盖验证确认3/3项内部校验、完整包原校验清单保持不变、源码一致、Python编译通过，且模拟 `.runtime`、配置、输入和Session 4/4保持不变。

**下一步**：在目标Linux现有0.2.19内容补丁目录覆盖0.2.20免重装补丁；随后事前形成当前可访问的固定2000条新样本，再执行连续轮次。单条P50/P95仍包含队列等待，只作为排队耗时，不解释为HTTP网络延迟。

**边界**：本包只补齐 Candidate A 的 Linux 字段级测试入口，不把 Candidate A 提前宣布为正式技术栈；目标 Linux 的真实验证码、Session寿命、字段完整率和三轮硬门禁仍必须实测。人工滑块/短信初始化位于测试窗口外，批量过程中遇到控制响应停止并保留证据，不用自动重登掩盖单轮身份变化。

**关联**：`poc/linux/run-content-api.sh`、`poc/candidate-a/src/content_extraction.py`、`poc/linux/README.md`、`poc/shared/tests/test_linux_content_package.py`、`docs/research/collector-stack-poc-plan.md`、`docs/research/collector-stack-poc-results.md`、`docs/chains/first-platform-delivery.md`；Linux证据 `artifacts/poc/results/candidate-a/content-api-round-1-20260813T111930+0800/`。

---

## 2026-08-12 — 完成 Candidate A 帖子内容与一级评论 HTTP API 提取测试

**总目标**：在不逐条打开帖子页面、不重复详情请求的前提下，使用现有 Scrapling 登录状态和直接 HTTP API 提取第一版需要的帖子、媒体 URL、状态及最多十条一级评论，同时验证字段完整性与有效速度。
**状态**：✅ 提取器、字段映射、按需评论、完整2000条并发8实测及逐链接Excel结果完成；❌ 原固定输入中空详情、正文真实为空、评论计数差异和未确认状态语义导致严格完整率未达100%

**干到哪了**：
- [x] 新增 `poc/candidate-a/src/content_extraction.py`：登录与storage state继续复用项目既有Scrapling流程；批量阶段只注册 `FetcherSession`，由Spider调度详情与评论API、维护Cookie/TLS/请求头、输出CrawlStats和JSONL，不读取帖子DOM、不启动浏览器。
- [x] 从既有Scrapling浏览器缓存确认真实请求路径为 `/motor/pc/ugc/detail/common` 和 `/motor/pc/ugc/detail/comment_list`；对同一已取到响应的样本做快速对照后确认当前HTTP接口省略 `msToken/a_bogus` 仍返回完整JSON，详情约301ms、评论约279ms，因此首版不生成动态签名。
- [x] 请求策略固定为单请求优先：每帖先且只请求一次详情；`comment_count=0` 直接完成；大于0才请求 `count=10&cursor=0` 的评论首批；首批不足10且 `has_more=true` 才继续游标，空详情直接1请求结束。可见状态复用详情响应，不额外请求。
- [x] 已映射帖子URL、平台帖子ID、标题、作者、发布时间、正文、图片URL、视频URL、评论数、点赞数、圈子、`visible/unknown`、原始状态，以及一级评论ID、作者、内容、时间和点赞；评论按平台顺序最多10条，不采集楼中楼。
- [x] 单帖真实闭环取得578字正文、3图和1条一级评论，2请求、649ms、全部字段完整。20条并发4为20/20完整、2.173秒、9.20条完整URL/秒，其中5条真实零评论只发1请求。
- [x] 最终代码回归100条（原清单偏移620、并发8）为86/100严格完整、5.377秒、15.99条完整URL/秒；12条详情无数据、2条可见纯图片帖正文文本为空。中文字段改为从响应原始字节解析JSON后未再出现编码失真。
- [x] 最终500条（原清单偏移720、并发8）形成500/500唯一终态：19.381秒、处理25.80 URL/秒、严格完整372条、完整速度19.19 URL/秒、703次HTTP请求、放大率1.406、297条只发1请求；全部详情和评论请求均HTTP 200，没有页面请求、浏览器、登录、验证码、限流或动态签名事件。
- [x] 最终500条的128个不完整终态已分类：122条API `status=0` 但详情数据为空；3条有标题和图片但正文文本为空；1条评论API总数为2但只返回1条且无下一页；2条 `operation_status=2` 的语义未验证，按约束保留 `unknown`。83条详情评论计数与评论API当前总数不一致，提取完整性以评论API的 `total_count/cursor/has_more` 单独记录，不静默混同。
- [x] 完整2000条使用原固定清单前2000条、既有Scrapling storage state、并发8，由项目 `content_extraction.py` 从0执行：2000/2000结果、URL唯一且顺序与输入一致；85.394秒、处理23.42 URL/秒、严格完整1587条（79.35%）、完整速度18.58 URL/秒、2989次HTTP请求、放大率1.4945、1012条只发1请求。2000次详情与989次评论请求全部HTTP 200，页面文档请求0、浏览器未启动、未生成动态签名。
- [x] 413个不完整终态已按逐链接结果保留：398条详情数据为空、11条仅正文为空、3条仅 `operation_status=2` 导致可见状态未知、1条评论分页证据不完整；另有458条详情回复数与评论API当前总数不一致，但其中可按评论API分页证据完成的结果未误记为评论缺失。共提取4119个图片URL、0个视频URL和3908条一级评论。
- [x] 已生成逐链接Excel：`artifacts/poc/results/candidate-a/content-full-2000-c8-20260812-210616/content-test-results-2000.xlsx`，包含“测试摘要”“帖子结果”“一级评论”三表；Excel本机只读复核为2001行帖子表、3909行评论表，19位帖子/评论ID按文本完整显示，摘要公式为2000、1587、79.35%和3908。文件SHA-256为 `b19bee197b7160578c47687ae2b41445dd773a09a44e08ae19473a03fbe6ccc0`，更新后的 `SHA256SUMS` SHA-256为 `98c1df9b7771ba96c109e1cee4564264becb8a628a4406473be5748844db2052`。
- [x] 内容提取7项单测及项目全部54项 `unittest` 通过；Python编译、`pip check`、`git diff --check` 和完整2000条结果目录5项SHA-256复核通过。此前最终500条 `SHA256SUMS` 文件SHA-256为 `5e09604a3ba3831f09bfc4f16afcd88d8ffc96d5a12559c78ff3e10f605b869f`。

**下一步**：先核对398条空详情是否为失效输入，并用当前结果事前形成“详情可用且正文非空”的固定功能样本；同时人工确认 `operation_status=2`、正文HTML/纯图片口径和评论计数差异。随后用同一提取器在目标CentOS对新固定样本连续执行三轮字段完整率与速度验证。圈子列表发现仍是独立未决项。
**边界**：18.58条完整URL/秒已超过2000条/小时与十万条/8小时的纯速度门槛，但完整2000条轮次的严格完整率只有79.35%，不能据此宣告第一版完工或正式技术栈选型。评论、标题、作者和圈子字段的真实空值保留为空；正文为空、详情不存在和状态语义未知不按成功掩盖。全部HTTP 200只证明本轮API通道未出现已识别控制，不证明接口、会话条件或动态参数长期不变。
**关联**：实现 `poc/candidate-a/src/content_extraction.py`；测试 `poc/shared/tests/test_content_extraction.py`；单帖 `artifacts/poc/results/candidate-a/content-functional-20260812-02/`；最终回归 `artifacts/poc/results/candidate-a/content-regression-100-offset620-c8-20260812/`；最终500条 `artifacts/poc/results/candidate-a/content-final-500-offset720-c8-20260812/`；完整2000条与Excel `artifacts/poc/results/candidate-a/content-full-2000-c8-20260812-210616/`。

---

## 2026-08-12 — 完成 Candidate B 认证HTTP至2000条验证

**总目标**：让 Candidate B 使用 Crawlee/Playwright 建立认证状态、交接给 `CheerioCrawler + SessionPool` 纯HTTP采集，并按与 Candidate A 相同的3条门禁、并发1、一小时窗口和最多2次有界恢复执行至2000条计划分母。
**状态**：✅ 3条与500条轮次完成；✅ 2000条计划轮执行并真实触发两次恢复；❌ 第1337条再次转空并耗尽恢复预算，剩余663条未请求

**干到哪了**：
- [x] 新增 Candidate B 有界恢复入口：PlaywrightCrawler只负责全新隔离profile登录并导出storage state；目标域未过期Cookie交给Crawlee `CheerioCrawler + SessionPool + persistCookiesPerSession`；`empty/login`首控暂停后重新登录、3条门禁并从触发URL重试，验证码、挑战、限流、登录失败、门禁失败和预算耗尽均停止。
- [x] 3条真实门禁为3/3 `post/success`；总时长18.102秒，6个采集HTTP请求包含3个门禁和3个批量请求，证明Candidate B认证Cookie可交接给直接HTTP，不需要逐URL打开浏览器。
- [x] 500条为500/500终态：452条有效、48条HTTP 404、无登录/空文档/验证码/挑战/限流；181.711秒、503个采集HTTP请求、有效速度2.49 URL/秒、请求放大率1.006。正确性门因48条404失败。
- [x] 2000条实现检查中发现平台静默控制响应标记为 `text/plain`，Crawlee默认在正文分类前拒绝该MIME；已使用框架 `additionalMimeTypes` 接收正文，并修正同进程连续登录的请求唯一键。修正后不再把控制页误记为网络错误。
- [x] 同口径2000条轮次：Session 1在原第626条转为HTTP 200空文档，Session 2恢复该触发URL；Session 2在原第1300条再次转空，Session 3再次恢复；Session 3仅再完成38个终态便在原第1337条转空。最终1337个唯一终态、1092条有效、244条HTTP 404、1条未恢复空文档，剩余663条；两次刷新与两次触发URL恢复均成功，但达到2次预算后停止。
- [x] 该轮总时长488.028秒、1348个采集HTTP请求、按有效结果计算约2.24 URL/秒；`SHA256SUMS`文件SHA-256为 `8f4e2412e6b92563051697bf08b58c56cb9dc5dab83ba012a31ab1a5e5714113`。随后立即尝试上限5次的容量轮，初始Playwright登录即得到空文档且未提交表单，0条进入采集；这证明当前时点连会话初始化也受控，不能用无限重登录承诺2000条完成。
- [x] 项目 `.vevn` 47项Python测试、Python编译、`pip check`、Candidate B类型检查、4个测试文件13项测试和 `git diff --check` 通过；3条、500条和1337个已形成终态的统一结果契约均为0错误，四个结论目录校验清单一致，跟踪文件与公开结果凭证值扫描通过。恢复状态机覆盖触发URL重试、不可恢复验证码和预算耗尽。

**下一步**：不继续立即重复登录。先基于新的当前可访问清单做独立Session的速率/间隔矩阵，并加入登录阶段冷却观察；只有同一预注册策略能在不同时间重复完成2000/2000有效终态，才进入CentOS三轮。Candidate A当前证据优于B，但两者都未通过100%正确性门，也都低于十万条/8小时所需约3.47个有效URL/秒。
**边界**：本任务已经以2000条为计划分母完成测试，不等于产生2000个终态。最多2次恢复是预注册停止规则；剩余663条未请求是方案B失败证据，不能用事后增加无限Session或拼接新轮次改写。`text/plain`是平台响应MIME与Crawlee默认接收范围的适配问题；修复后观察到的HTTP 200空文档才是平台控制证据。
**关联**：门禁 `artifacts/poc/results/candidate-b/auth-http-gate-3-20260812-194725/`；500条 `artifacts/poc/results/candidate-b/auth-http-500-20260812-194757/`；最终2000计划轮 `artifacts/poc/results/candidate-b/bounded-recovery-2000-final-20260812-200550/`；扩展容量轮 `artifacts/poc/results/candidate-b/bounded-recovery-2000-max5-20260812-201419/`。

---

## 2026-08-12 — 完成有界Session恢复的2000条完整验证

**总目标**：使用全新Scrapling认证Session、固定2000条清单、并发1、一小时窗口和最多2次自动恢复，验证 `empty/login` 后重新登录、门禁、触发URL重试和继续队列能否形成完整逐URL终态。
**状态**：✅ 2000/2000终态与两次控制恢复完成；❌ 356条HTTP 404导致统一正确性门失败

**干到哪了**：
- [x] 使用原固定清单SHA-256 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70`，从全新Scrapling隔离profile密码登录开始执行；初始及两次恢复后的3条门禁均为3/3 `post/success`，无二次验证。
- [x] 第一个Session在原清单第708条出现HTTP 200零字节 `empty`；自动登录Session 2后，触发URL第708条重试成功并继续。第二次控制发生在原清单第1466条；Session 3再次通过门禁、重试第1466条成功并完成至第2000条。
- [x] 两次 `empty` 均为 `trigger_recovered=true`，最终2000个不同URL保持原顺序、各有唯一终态、没有最终 `empty/login/captcha/challenge/rate_limited`，剩余0条，未超出2次恢复预算。
- [x] 总时长747.120秒（约12分27秒）；2011个采集HTTP请求＝2000个批量基准请求＋2个控制URL重试＋9个三Session门禁请求，请求放大率1.0055；浏览器登录子请求不计入该HTTP指标。最终有效1644条、有效速度约2.20 URL/秒。
- [x] 356条失败全部为服务器HTTP 404、响应体均10862字节，分布为Session 1的139条、Session 2的125条、Session 3的92条；它们与已恢复的HTTP 200空文档分开统计。最终有效率82.2%，因此本轮不通过2000条100%有效门禁。
- [x] `url-results.jsonl` 为2000行且URL唯一、顺序与输入一致；公开结果6/6校验一致，`SHA256SUMS` 文件SHA-256为 `91502dacb69b0d7a0ea986660e66272c71d5b5c6969a8e45e0f17c834a338c1d`。

**下一步**：依据固定来源池构造新的“当前可访问2000条”清单并记录新哈希，不能从本轮事后删除失败项冒充通过；然后以相同有界恢复配置重新从0执行。Windows单轮通过后仍需目标CentOS连续三轮硬门禁。
**边界**：本轮证明当前条件下最多2次自动Session恢复足以完成2000个URL的终态覆盖，且两次触发URL均恢复；它不证明356条404可采集、不构成100%有效完成，也不等同于目标CentOS三轮验收。有效速度2.20 URL/秒低于十万条/8小时所需约3.47 URL/秒。
**关联**：`artifacts/poc/results/candidate-a/bounded-recovery-2000-20260812-174101/`。

---

## 2026-08-12 — 实现认证HTTP有界Session自动恢复控制

**总目标**：在认证HTTP出现 `empty/login` 时暂停旧Session，通过Scrapling重新登录建立新Session，经3条门禁后从触发URL继续处理，同时限制恢复次数并保留真实请求放大率。
**状态**：✅ 控制器与真实1条闭环验证完成；尚未执行带恢复控制的完整2000条轮次

**干到哪了**：
- [x] 新增 `bounded_session_recovery.py`：HTTP段继续使用 `Spider + FetcherSession`；`empty/login` 触发首控后由Scrapling `AsyncDynamicSession` 建立全新隔离profile和storage state，3条门禁通过后把触发URL放回新段首位，不跳过失败项。
- [x] 恢复次数默认2次、允许0至5次；`captcha/challenge/rate_limited`、登录失败、门禁失败、恢复预算耗尽和一小时窗口耗尽均停止，不形成无限登录循环。
- [x] 最终 `url-results.jsonl` 每个输入最多一个最终结果；所有旧Session控制尝试、门禁和新Session重试保留在 `request-events.jsonl`，并计入采集HTTP请求数与请求放大率；浏览器登录子请求不混入该指标，Session刷新次数单列。`recovery-events.jsonl`记录Session序号、原因、范围和是否恢复，不记录凭证与Cookie。
- [x] 两份历史状态在17:11至17:12再次做3条门禁时均恢复为3/3有效，说明此前冷却探测失败不代表永久失效；当前只确认恢复发生在约数小时后，未测得最短恢复时间。
- [x] 使用仅含无效夹具Cookie的状态执行真实闭环：旧门禁首条为 `login`，控制器自动重新密码登录、无二次验证，新Session门禁3/3，随后原目标URL重试成功；共5个HTTP请求、1次成功Session刷新、最终1/1有效，耗时16.999秒，请求放大率5.0。
- [x] 项目 `.vevn` 47项测试、Python编译、`pip check` 和 `git diff --check` 通过；真实闭环公开结果6/6校验一致，`SHA256SUMS` 文件SHA-256为 `e8ea5ee09bc2eae96e474040829d163daf6fbc5be35f5dd3c51335bb24f32992`。

**下一步**：先用固定有效样本执行低速/间隔矩阵，再选择一个请求节奏运行带最多2次Session恢复的全新2000条轮次；验收看2000个逐URL最终结果、总请求放大率、总时长、Session刷新次数和未恢复控制数，不把分段HTTP 200数量当作通过。
**边界**：自动重新登录目前只在无二次验证的密码登录条件下实测通过；它是有界恢复能力，不证明每次控制都能通过换Session解除，也不替代验证码、挑战或限流处理。旧状态数小时后恢复与重新登录恢复是两个现象，尚未证明二者机制相同。
**关联**：实现 `poc/candidate-a/src/bounded_session_recovery.py`；真实闭环 `artifacts/poc/results/candidate-a/bounded-recovery-login-smoke-20260812-171252/`。

---

## 2026-08-12 — 完成新Scrapling Session未完成段恢复测试

**总目标**：重新由Scrapling建立独立认证Session，先通过3条纯HTTP门禁，再从原固定清单第709条开始执行剩余1292条独立恢复段，并判断旧Session不可用是否等同于自然过期。
**状态**：✅ 新Session恢复访问后在恢复段第767个终态再次转为空文档；剩余525条未发送

**干到哪了**：
- [x] 使用新的Scrapling隔离profile执行密码登录，`submitted=true`、`logged_in=true`、无二次验证；浏览器样本取得真实帖子并导出新的 `storage-state.json`，旧profile和旧失败证据未覆盖。
- [x] 新状态交给 `Spider + FetcherSession` 后，3条门禁为3/3 `post/success`，1.088秒、请求放大率1.0，无登录、空文档、验证码、挑战或限流。
- [x] 以原清单SHA-256 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70`、`offset=708`启动1292条独立恢复段；第767个终态、262.041秒出现HTTP 200零字节 `empty` 并暂停，此前640条有效、126条HTTP 404，剩余525条未请求，请求放大率1.0。
- [x] 首控后只复查门禁中已确认有效的1条样本，立即再次得到HTTP 200零字节，确认不是恢复段第767条单独异常，而是新会话/profile/客户端身份组合已整体转空。
- [x] 匿名核对Cookie到期时间：控制后统计中的2个过期Cookie实际在恢复段开始后约2至5秒即到期，而首控发生在262秒；首控附近没有Cookie到期，因此现有证据不支持把本次转变简化为客户端Cookie自然到期。
- [x] 门禁、恢复段和停控复查分别为5/5、6/6、5/5校验一致；`SHA256SUMS` 文件SHA-256依次为 `a7eb46ffe734a3f649afb807801d097edd1b1bf68eea170aaa88e88c7fec0e13`、`ee36e7517e2e6ee8c68d4aedf4bdb4fce9f9250ca4d86df90a40727b3ba47e72`、`8aece299b2d06ac49b5bd9fbc67601c71883e2b9310993b3835d0bb4d3e3cc40`。

**下一步**：不再刷新Session续跑剩余525条。使用新的独立Session/profile为每个实验臂执行固定有效样本的速率与间隔矩阵，至少比较当前约3请求/秒、1请求/秒和分批暂停；以首控请求序号和首控时间区分请求量、持续时间与请求速率影响。
**边界**：新Session恢复成功只证明旧项目身份不可用且刷新身份可以暂时恢复，不证明旧Session是自然过期；本轮同时更换了Session与profile，账号、profile、HTTP客户端身份和速率仍未被单独控制。恢复段不得与旧Session前708条合并为2000条通过。
**关联**：登录 `artifacts/poc/results/candidate-a/auth-recovery-bootstrap-20260812-141852/`；门禁 `artifacts/poc/results/candidate-a/auth-recovery-preflight-20260812-141852/`；恢复段 `artifacts/poc/results/candidate-a/auth-recovery-offset708-20260812-141852/`；停控复查 `artifacts/poc/results/candidate-a/auth-recovery-postcontrol-20260812-141852/`。

---

## 2026-08-12 — 完成2000条未完成段冷却恢复探测

**总目标**：在2000条主轮次暂停一段时间后，验证原认证Session是否自然恢复；若恢复，则从原固定清单第709条开始执行剩余1292条独立恢复段。
**状态**：✅ 冷却后原Session仍为静默空文档；剩余1292条未发送

**干到哪了**：
- [x] 认证HTTP入口新增 `--offset`，支持以 `--offset 708 --limit 1292`选择原2000清单的未完成段；输出同时记录原清单SHA-256、偏移量和本段清单SHA-256，且明确恢复段不与前段拼成同一持续轮次。
- [x] 在不刷新认证、不更换profile和不改变HTTP配置的条件下，先对原清单中本轮曾成功的已知有效样本执行1条冷却恢复探测。
- [x] 探测仍返回HTTP 200、正文0字节、`empty/failed`，约0.228秒即触发首控暂停；原storage state中31个目标域Cookie仍有效、3个已过期，但Cookie存在不构成访问恢复证明。
- [x] 因首条阶段门失败，没有向第709条后的1292条发送请求，避免把已确认空响应放大；单纯等待没有解除当前项目Session/profile/客户端身份组合的静默控制。
- [x] 结果目录5/5校验一致，`SHA256SUMS` 文件SHA-256为 `7528b47f999ed1f44bfe5513cdc36680170d3188aeca7e128dfe3b1ddba0a44d`。
- [x] 项目 `.vevn` 43项测试、Python编译、`pip check` 和 `git diff --check` 通过；偏移708/长度1292的参数解析已有回归覆盖。

**下一步**：若继续第709条后的恢复实验，先重新建立认证Session并以3条验证，再以 `--offset 708 --limit 1292`启动“新Session恢复段”；该结果单独报告，不改写旧Session冷却失败，也不与前708条合并为2000条通过。
**边界**：当前只证明本次等待时长后原Session未自然恢复，尚未测得最短恢复时间或永久失效；不持续轮询，不把Cookie数量误写为Session有效。
**关联**：`artifacts/poc/results/candidate-a/cooldown-session-probe-20260812-140937/`。

---

## 2026-08-12 — 完成 Candidate A 认证 HTTP 2000条持续轮次诊断

**总目标**：在开发电脑使用固定2000条清单、认证Session、Scrapling纯HTTP、并发1执行持续轮次；首次出现登录/空文档/验证码/挑战/限流时暂停，并分析控制作用层级。
**状态**：✅ 2000条轮次已真实启动并在第708个终态按首控规则暂停；未通过2000/2000门禁

**干到哪了**：
- [x] 认证HTTP入口上限扩展至2000条，继续使用 `Spider + FetcherSession + Request/Response`、每URL一次请求和框架 `pause()`；补齐框架快速收口时 `crawl_result.paused` 尚未置位的兼容判定、首控序号和首控前成功数。
- [x] 旧认证状态在运行前首条即返回HTTP 200零字节空文档，未启动2000条；保留旧profile后使用项目自有Scrapling浏览器重新密码登录，无二次验证，刷新状态后3条复检为3/3有效。
- [x] 固定清单SHA-256 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70` 的主轮次执行到第708个终态：568条有效帖子、139条HTTP 404、第708条HTTP 200零字节 `empty`；228.635秒触发暂停，剩余1292条未请求，请求放大率1.0。
- [x] 停控后同一HTTP认证状态复访历史空URL和本轮刚成功过的已知有效URL，两者均为HTTP 200零字节；项目Scrapling浏览器同profile复访也为 `empty`。这排除单一坏URL作为停止原因，并确认控制已影响项目HTTP和项目浏览器profile。
- [x] 同一电脑、同一网络下，用户日常Chrome重新导航到固定帖子后仍实时显示标题、正文和评论；因此纯IP全局封锁不符合现有证据，更合理的范围是项目测试账号/会话/profile/客户端身份组合。当前尚不能细分账号信誉、会话绑定或客户端身份评分。
- [x] 核心结果和 `control-analysis.json` 6/6校验一致，`SHA256SUMS` 文件SHA-256为 `bab8b1f9f246e0f109b3b0fbee46d643c467287307917549a8ce0e14a806e521`；未保存Cookie值、Cookie名称、账号或完整控制URL。
- [x] 项目 `.vevn` 42项测试、Python编译、`pip check`、`git diff --check` 和差异凭证扫描通过；快速首控时框架暂停标志滞后的情况已有回归覆盖。

**下一步**：不续跑剩余1292条，也不把刷新Session后的分段结果拼成同一轮。先设计“会话身份隔离/刷新条件/低速间隔”因果矩阵，使用更小固定样本分别验证账号、profile、HTTP客户端身份和请求速率；确认可持续条件后再从0开始新的2000条轮次。
**边界**：本轮是开发电脑预筛，不是目标CentOS三轮硬门禁；568个有效结果除以228.637秒约2.48 URL/秒只代表控制前速度，不能外推十万条/夜。139条404仍属于输入可用性问题，与第708条静默空文档控制分开统计。
**关联**：主轮次 `artifacts/poc/results/candidate-a/auth-http-2000-20260812-133930/`；认证刷新 `artifacts/poc/results/candidate-a/auth-refresh-before2000-20260812-133857/`；刷新后复检 `artifacts/poc/results/candidate-a/auth-http-pre2000-refreshed-20260812-133921/`。

---

## 2026-08-12 — 完成 Candidate A 认证 HTTP 500条并发1实测

**总目标**：在认证HTTP三样本通过后，对同一固定500条执行并发1、每URL一次请求的完整测试；出现首次登录/空文档/验证码/挑战/限流时由Scrapling暂停剩余队列，并以有效帖子证明分析速度和风控。
**状态**：✅ 500/500请求和终态结果已完成；未观察到风控，但因101条HTTP 404未通过500条100%有效门禁

**干到哪了**：
- [x] 认证探针扩展到最多500条，保持 Scrapling `Spider + FetcherSession + Request/Response`、并发1和请求放大率1.0；新增 `Spider.pause()` 首次控制停止、部分轮次覆盖率、停止原因、HTTP状态分布和框架导出证据。
- [x] 运行前同一认证状态用固定清单前3条回归为3/3 `post/success`；随后对输入 SHA-256 `cbb34154b1614e417c24f049844288864f139683c62a419cdab5b172e878822a` 的500个不同URL完整执行。
- [x] 主轮次500/500产生结果：399条HTTP 200且通过帖子ID与正文证据，101条HTTP 404；有效完成率79.8%，总时长166.031秒，处理速度约3.01 URL/秒、有效速度约2.40 URL/秒，请求数500、请求放大率1.0。
- [x] 未出现 `login`、`empty`、`captcha`、`challenge` 或 `rate_limited`，Spider未触发暂停；101条404分布于全部10个连续50条区间，没有随运行时间形成控制切换边界，且正文长度均10862字节。
- [x] 两条404有界复查仍返回相同HTTP 404、正文长度和SHA-256 `6b55e232c77f377133617a55d0ec7b1b77a039243fd5f7323637489cfd94ca76`；历史 Candidate B 500条转变轮次记录的24条HTTP 404全部与本轮重合。当前把它归入输入不可访问/标准404，不写成已确认风控，也不直接断言具体删除原因。
- [x] 结果目录5/5校验一致，更新后 `SHA256SUMS` 文件 SHA-256 为 `d423c86b0c0f89b4172d07301643b30fa63b7b2bee2e9b08ce06bdf0c0ae5954`；项目 `.vevn` 41项测试、Python编译、`pip check` 和 `git diff --check` 通过；单请求P50/P95从批量入队计时，包含排队等待，不作为网络延迟。

**下一步**：对101条HTTP 404做有界的已登录可见页面/来源索引复核；确认当前不可访问的输入从固定池替换并生成新清单哈希，再用同一认证HTTP配置重跑500条100%有效阶段门。之后才验证并发2/4/8和目标CentOS。
**边界**：本轮证明当前认证Session在166秒、并发1内没有观察到已识别风控，并不证明长期会话、评论接口、动态参数、十万条/夜或CentOS；399/500未达到交付正确性门，不能只按2.40有效URL/秒宣告通过。
**关联**：结果 `artifacts/poc/results/candidate-a/auth-http-500-20260812-132210/`；运行前回归 `artifacts/poc/results/candidate-a/auth-http-pre500-20260812-132155/`。

---

## 2026-08-12 — 完成 Candidate A 认证 HTTP 首版三样本验证

**总目标**：从已认证浏览器状态建立 Scrapling 纯 HTTP Session，先以最多3条、并发1验证帖子有效内容与首个风控形态，并把可由框架承担的采集职责收敛到框架。
**状态**：✅ 本机认证 HTTP 首版通过；下一阶段仍需独立制定中等负载与会话寿命验证

**干到哪了**：
- [x] 当前日常 Chrome 的帖子页面已确认登录可见，但该浏览器未开启 CDP，项目没有直接读取或复制其 Cookie；本轮由 Scrapling `AsyncDynamicSession` 使用项目既有测试账号建立独立认证状态，密码登录成功、无二次验证，单帖取得 `post/success`，并显式导出被 Git 忽略的 `storage-state.json`。
- [x] 新增 `session_handoff.py`：只把 Playwright storage state 中适用于目标域、未过期的 Cookie 在内存中转为 `curl_cffi` Cookie 容器；结果只记录数量，不输出 Cookie 名称和值。
- [x] 新增 `authenticated_http_probe.py`：固定使用 Scrapling `Spider + FetcherSession + Request/Response`，最多3条、并发1、每 URL 一次请求；Spider 调用框架状态码阻断检测并保留项目 HTTP 200 登录/空文档/挑战内容分类，终态不自动重试。
- [x] 框架可承担的抓取职责已交给 Scrapling：Session 生命周期、TLS/请求头模拟、Cookie 请求、Spider 调度、Request/Response、CrawlStats 和 `ItemList.to_jsonl()` 导出；项目仅保留 URL/帖子 ID 契约、正文真实性、细分风控分类、脱敏事件、摘要与校验清单。
- [x] 认证 HTTP 框架化复跑结果为3/3 `post/success`，总时长1.169秒、有效速度约2.57 URL/秒、请求放大率1.0；39个源 Cookie 中32个目标域有效、2个已过期、5个非目标域；三条均为HTTP 200，框架状态码阻断与项目内容阻断均为否，未出现登录、验证码、挑战或限流。
- [x] 结果目录5/5校验一致，`SHA256SUMS` 文件 SHA-256 为 `7fb8dda314b753af0366362dbcf590e456e36f062878aa3ad8152ba864627e20`；项目 `.vevn` 38项测试、Python `compileall` 均通过。

**下一步**：继续使用同一认证 HTTP 架构，先制定独立的会话寿命与固定中等样本阶段门；只有有效完成率保持100%才递增负载/并发。评论接口、动态参数和500条持续负载不与本次3条结果拼接。
**边界**：3条、约1.17秒只证明认证主文档的小样本可行性，不能外推500条、十万条/夜、评论接口或CentOS；本轮未直接导出当前日常Chrome会话，也未证明平台内部具体风控评分原因。
**关联**：认证初始化 `artifacts/poc/results/candidate-a/auth-bootstrap-20260812-130809/`；框架化HTTP结果 `artifacts/poc/results/candidate-a/auth-http-framework-20260812-131028/`。

---

## 2026-08-12 — 完成新浏览器与匿名 HTTP 会话对照

**总目标**：解释500条 `login` 是否来自未处理指纹，并用新浏览器、Chrome模拟HTTP直连及首页匿名Cookie预热对同一帖子做分层验证。
**状态**：🟡 匿名浏览器与匿名HTTP均确认登录门；等待真实已认证浏览器会话后继续HTTP状态交接试验

**干到哪了**：
- [x] 已核对500条实现：Candidate A 使用 `impersonate="chrome"` 与 `stealthy_headers=true`；Candidate B 使用 CheerioCrawler、SessionPool 和 Cookie 持久化。上一轮确实没有登录Cookie或浏览器状态，但不是完全没有TLS/请求头指纹处理。
- [x] 全新应用内浏览器分别打开固定联通样本和另一条已知帖子，两条都直接进入 `/login-required?redirect=...` 并显示手机验证码/密码登录表单，没有帖子正文；当前只连接了应用内浏览器，没有可控制的已登录Chrome会话。
- [x] Candidate A HTTP对照启用Chrome模拟、隐蔽请求头、中文语言头和站点来源头；直接访问帖子为文章HTTP302后登录页HTTP200。使用同一HTTP会话先访问首页取得5个匿名Cookie，再访问帖子，仍为相同登录结果。
- [x] 两组结果只保存路径模板、正文长度、Cookie数量和名称哈希，未保存Cookie值、Cookie名称、页面正文或完整查询串；证据校验清单已写入被忽略的 `artifacts/poc/results/`。
- [x] 当前已确认主文档在页面运行前就被服务器重定向；`msToken`、`a_bogus` 和评论分页参数不是当前主文档登录的直接阻塞点。
- [x] 两个有效证据目录的 `SHA256SUMS` 均复核通过；四份修改文档可按UTF-8读取，`git diff --check` 和差异凭证值扫描通过。浏览器检查结束后已关闭本轮临时标签页。

**下一步**：先在受控浏览器中形成可复访的真实认证帖子会话，再使用同一条样本顺序执行浏览器复访与最小认证状态HTTP复访；状态值只保存在被忽略的临时文件，不回显、不进入结果报告或Git。未登录成功前不再扩大HTTP样本或并发。
**边界**：当前证据只说明现有Chrome模拟与匿名Cookie不足，尚不能单独区分账号认证、网络出口和平台策略的影响；不把新浏览器也进入登录误写成HTTP框架缺陷，也不把首页HTTP200当作帖子可访问。
**关联**：`artifacts/poc/results/candidate-a/browser-http-session-probe-20260812T071759+0800/`；`artifacts/poc/results/candidate-a/browser-http-session-probe-known-url-20260812T071923+0800/`。

---

## 2026-08-11 — 完成纯直接 HTTP 双候选500条预筛

**总目标**：实现 A/B 不含浏览器兜底的直接 HTTP 批量入口，在当前开发电脑对同一固定500条执行一次并发1实测，并以有效帖子证明而非队列速度形成结论。
**状态**：✅ 本机纯匿名直接 HTTP 500条已完成并判定失败；不升并发、不打Linux包

**干到哪了**：
- [x] Candidate A 新增 `http_throughput.py`，使用 Scrapling `Spider + FetcherSession(impersonate="chrome")`；Candidate B 新增 `http-throughput.ts`，使用 Crawlee `CheerioCrawler + SessionPool`。两端均固定单HTTP会话、每URL一次请求、无浏览器启动或状态导入，并输出相同的环境、输入、逐URL、请求事件、摘要和校验清单。
- [x] 3条冒烟已确认阶段门失败：A为3条`login`，B为1条`challenge`和2条`login`。按用户明确要求仍继续执行一次完整500条；未增加失败兜底或其他通道。
- [x] 500条结果目录的5/5内部校验均一致，输入文件 SHA-256 同为 `cbb34154b1614e417c24f049844288864f139683c62a419cdab5b172e878822a`；两端均500条结果、500条请求事件、HTTP通道100%、请求放大率1.0、浏览器未启动、统一契约错误0。
- [x] Candidate A 为0/500、500条`login`，总时长71.803秒，原始处理速度约6.96 URL/秒，首次控制约0.312秒；Candidate B 为0/500、497条`login`、2条`captcha`、1条`challenge`，总时长74.580秒，原始处理速度约6.70 URL/秒，首次控制约1.004秒。两端有效链接速度均为0。
- [x] 已复核本轮逐URL P50/P95起点不一致：A含Spider队列等待，B从实际导航计时；该差异不影响总时长、最终分类和0条有效结果。B入口已改为后续同样从批量提交时计时，本轮报告不使用P50/P95做候选比较。
- [x] 结论已同步到技术路线、PoC计划、首个平台链档和 `docs/research/collector-stack-poc-results.md`；原始URL与结果继续只保存在被Git忽略的 `artifacts/poc/`。
- [x] 本机验证通过：项目 `.vevn` Python 35项、Candidate B 10项、Python `compileall`、TypeScript类型检查、`pip check`、`git diff --check`、新入口零浏览器路径断言和差异凭证值扫描均通过。

**下一步**：当前匿名直接HTTP分支到此结束。若继续研究直接HTTP，建立新的“认证条件下纯HTTP”独立实验，先以3条固定样本验证会话建立、身份一致性和帖子证明；3条全部有效后再重新制定500条负载，不与本轮匿名结果拼接。
**边界**：当前结果只绑定本机、当前网络出口、匿名主文档访问和本轮时间；不外推认证纯HTTP、评论动态参数或CentOS。原始处理速度是控制页速度，不代表有效采集能力；并发2/4/8和Linux打包均因正确性门失败而停止。
**关联**：A结果 `artifacts/poc/results/candidate-a/direct-http-500-20260811T234144+0800/`；B结果 `artifacts/poc/results/candidate-b/direct-http-500-20260811T234144+0800/`；输入 SHA-256 `cbb34154b1614e417c24f049844288864f139683c62a419cdab5b172e878822a`。

---

## 2026-08-11 — 补齐直接 HTTP/Spider 的风控与吞吐验证路线

**总目标**：不改变 Scrapling 与 Crawlee 两个候选和统一成功契约，把此前未进入大批量入口的直接 HTTP/Spider 通道纳入公平预筛，并用有效链接速度、首次控制时间和会话一致性决定是否进入目标 Linux。
**状态**：🟡 owner 文档已同步；等待实现 A/B 最小直接 HTTP 批量入口并执行本地预筛

**干到哪了**：
- [x] 已核对当前实现：Candidate A 吞吐使用 `AsyncDynamicSession`，Candidate B 吞吐使用 `PlaywrightCrawler` 且未启用 `SessionPool`；`FetcherSession`、`CheerioCrawler` 目前只在冒烟或诊断路径出现，因此现有2000/500条证据只代表浏览器批量路径。
- [x] 技术路线和 PoC 计划已明确新的同框架访问通道：A 使用 `Spider + FetcherSession(impersonate="chrome")`，B 使用 `CheerioCrawler/HttpCrawler + SessionPool`；阶段内不启动浏览器、不导入浏览器状态，也不在 HTTP 失败后切换浏览器。
- [x] 已增加风控与速度记录口径：首次 `login/empty/captcha/challenge/rate_limited` 的时间和已完成数、持续有效 URL/秒、P50/P95、请求放大率、HTTP 会话寿命及最终分类分布；HTTP 通道占比必须为100%，HTTP 200、队列完成和请求发送数均不计为有效完成。
- [x] 已固定动态参数边界：阶段 2A 只解析页面主文档及其内嵌状态，不请求评论接口；评论动态参数、纯 HTTP 参数实现和浏览器运行时参数方案后续按独立实验组验证，不与当前结果拼接。
- [x] 现有 v0.2.18 全新隔离会话和浏览器单并发包继续保留，不覆盖既有失败证据；本地直接 HTTP 结果只做预筛，正式结论仍要求目标 CentOS 三轮2000条硬门禁。
- [x] 文档验证已通过：`git diff --check` 无格式错误，四份修改文档均可按 UTF-8 读取且 owner 引用存在；源码事实复核定位到 Candidate A 的 `AsyncDynamicSession` 导入和 Candidate B 的 `PlaywrightCrawler` 吞吐入口，差异中未发现动态令牌值。

**下一步**：在新开发任务中先实现两个不改统一输出契约的批量入口：Candidate A `http_throughput.py` 使用 `Spider + FetcherSession`，Candidate B `http-throughput.ts` 使用 `CheerioCrawler/HttpCrawler + SessionPool`。先对现有固定联通样本并发1验证帖子 ID 与标题/正文存在性，再对同一固定前500条按 `1 -> 2 -> 4 -> 8` 递进预筛；通过后才生成目标 Linux 包。
**边界**：本步不把浏览器作为初始化、参数生成或失败兜底，也不把完整正文、一级评论或动态签名实现并入当前访问 PoC；不提交真实 URL、Cookie、令牌、完整查询串或请求体；“10条/秒”和“十万条/夜”只是扩展压力目标，当前硬门槛仍为三轮各2000 URL/小时且100%有效完成。
**关联**：技术路线 `docs/design/technical-route.md`；PoC owner `docs/research/collector-stack-poc-plan.md`；工作线 `docs/chains/first-platform-delivery.md`。

---

## 2026-08-11 — 复核双候选空文档转变并增加会话实测单并发诊断

**总目标**：保持 Scrapling 0.4.12 与 Crawlee 3.18.0/Playwright 1.62.1 不变，用同批500条目标 Linux证据确认 `empty` 形态，再以主动验证有效的候选隔离会话和并发1判断持续并发是否是主要触发条件。
**状态**：🟡 Candidate A 现有会话主动探测已确认首条 HTTP 200 空文档，同一旧浏览器资料的短信入口等待控件超时；全新资料初始化修复已完成本机验证，等待 v0.2.18 目标 Linux 实测

**干到哪了**：
- [x] A/B 转变结果目录各自9/9校验一致，输入文件 SHA-256 同为 `cbb34154b1614e417c24f049844288864f139683c62a419cdab5b172e878822a`。A 为0/500成功、95个`login`、405个`empty`、274秒/退出0；B 为71/500成功、1个`login`、405个`empty`、23个HTTP404、224秒/退出0。
- [x] A/B 首次 `empty` 分别出现在约64.2秒与69.2秒；A正文0字节，B为浏览器给零正文补出的39字节空HTML骨架。405个最终空文档有393个输入相同，双方立即重试均未出现 `empty -> post`。
- [x] B 在 A 已进入大面积空文档后从同一出口仍先取得71条成功，排除纯 IP 统一阻断；A 登录预检成功后批量页面立即跳转登录且 Cookie 名称形态未整体消失，说明 A 另有旧会话/并发上下文连续性问题。
- [x] 已增加候选独立的 `test-single-concurrency.sh`：固定前500条、并发1、最长2400秒，并记录是否在500条对应的900秒比例观察线内完成；A/B 各自运行和各自打包。
- [x] 目标 Linux 复现 v0.2.16 把 `storage-state.json` 超过1800秒直接判为需重新初始化；该文件年龄不等于服务端会话失效。本次已改为先用同一候选和首条 URL 做窗口外真实探测，`post/success` 时复用现有状态，实际进入登录类或探测失败时才停止并提示初始化。
- [x] 短信初始化脚本在候选退出非零时输出脱敏的结果分类与阶段布尔证据，不再只留下后续脚本的旧状态报错；操作说明要求重新初始化与单并发诊断用 `&&` 串联，避免前一步失败后误启动后一步。
- [x] v0.2.17 Candidate A 主动探测结果目录 9/9 校验一致：会话年龄70193秒，Scrapling首条样本取得HTTP 200但分类为`empty/failed`，批量请求数0、运行器退出4；同一旧资料随后打开登录入口，主文档HTTP 200且DOM/load完成、待定请求0，但短信控件等待`TimeoutError`，`sms_page_ready=false`。这确认现有资料当前不可复用，但尚不单独归因为自然过期或平台控制。
- [x] A/B 短信初始化现均使用本次输出目录下的全新浏览器资料，不注入旧 Cookie、缓存或客户端状态；仅在短信登录和原始帖子证明成功且浏览器关闭后整体替换候选主资料，失败保留旧资料。结果新增 `error_stage`、脱敏控件计数、`bootstrap_profile_mode` 与 `session_promoted`。
- [x] 当前变更的本机门禁已通过：项目 `.vevn` Python 33项（含旧状态放行主动探测、登录/空文档阻断、真实帖子放行及新旧资料原子替换）、Python编译与`pip check`，Candidate B 9项与TypeScript类型检查，两个 Shell 入口的 Bash 语法和`git diff --check`均通过；v0.2.16 的真实 Chrome/Playwright 单并发夹具证据继续保留。
- [x] 源码提交 `cb6f0bfc5fe4786cec34576c3ef29f8a05b8559f` 已生成 v0.2.18 完整包与免重装包，均归档在 `H:\ThreadSnap\artifacts\poc\packages\linux-dual-runner\`：完整包 `threadsnap-poc-dual-runner-0.2.18-linux.tar.gz` 的 SHA-256 为 `d77f8917afce386acae14d016d9f84ce13fad66d9564e3a0c19c87a35f19f1c7`、包内33/33一致；免重装包 `threadsnap-fresh-sms-profile-hotfix-0.2.18.tar.gz` 的 SHA-256 为 `f1ac7d89b08cef4e5111f8e3e75421c27d6f88cbb28de50af3373ad587e2de5f`、6/6成员与源码一致、Shell入口权限`0755`；两包均为零已知凭证标记且不安装依赖。
- [x] 源码提交 `866f28ea665400c5489e5ad4ca0310b61cd13524` 已生成 v0.2.16 完整包与免重装包：完整包 SHA-256 为 `f56e62a84022df1328c3a06c62d1723831bb464b385ab2611d1923ba7ff25b58`、包内31/31一致；免重装包 SHA-256 为 `201b936d87101af9fa3cdfa272e12dd1374826ba78a2294288c23ed573fde794`、4个成员完整、Shell入口权限`0755`；两包均为零已知凭证标记。
- [x] 修正源码提交 `870285ec4a64456d8799a02fa7d5f8a43742e89d` 已生成 v0.2.17 完整包与免重装包：两包统一归档在 `H:\ThreadSnap\artifacts\poc\packages\linux-dual-runner\`；完整包 `threadsnap-poc-dual-runner-0.2.17-linux.tar.gz` 的 SHA-256 为 `941ec71be681cdcb3007484c8bd4b4a6acc089a92caeedcaf72a4bb195712145`、包内32/32一致；免重装包 `threadsnap-session-reuse-hotfix-0.2.17.tar.gz` 的 SHA-256 为 `1a018327faf74b2cd8f812e8ece20f7f46f9f35d86f0a7720d0c3fbea3f2c665`、5/5运行文件与源码一致、Shell入口权限`0755`；两包均为零已知凭证标记且不安装依赖。

**下一步**：生成并覆盖 v0.2.18 免重装包后，目标 Linux 执行 `bootstrap-sms-session.sh candidate-a && test-single-concurrency.sh candidate-a`；确认终端先输出 `bootstrap_profile=candidate-a;mode=fresh_isolated`、登录成功后 `session_promoted=candidate-a;value=true`，再进入500条。Candidate B 随后独立执行相同步骤。
**边界**：单并发500条只验证触发条件和速度余量，不替代正式三轮2000条；会话文件年龄只作信息证据，是否有效以目标访问结果为准；当前23条真实404不计为平台控制，正式轮次前从输入池替换并产生新清单哈希；不共享 A/B 会话，不修改固定框架或成功契约。
**关联**：转变结果 `artifacts/poc/results/candidate-{a,b}/access-transition-*`；结果报告 `docs/research/collector-stack-poc-results.md`；入口 `poc/linux/test-single-concurrency.sh`。

---

## 2026-08-10 — 复核目标 Linux 首轮 2000 条双候选结果

**总目标**：保持 Scrapling 与 Crawlee/Playwright 两个固定候选不变，按统一校验器复核目标 Linux 首轮 2000 条结果，区分队列处理、有效帖子证明、平台控制和运行器生命周期问题。
**状态**：🟡 首轮双候选吞吐门禁均未通过；定向诊断与运行器收口已完成本机验证，等待目标 Linux 固定 500 条证据

**干到哪了**：
- [x] 已完整复制并校验 `artifacts/poc/results/candidate-a/round-1-20260810T204251+0800/` 与 `artifacts/poc/results/candidate-b/round-1-20260810T210023+0800/`；两份 `SHA256SUMS` 均为 8/8 一致，其文件自身 SHA-256 分别为 `4ca6c73387d36fc2f8628c188c1c1643882d5b5caed5da07d31687e34a1cfb8d` 和 `811bac33f94d7697e6b590bada706360f4316b7c9034da6c667d4d8c12c6e9d5`。
- [x] 两候选输入均为 2000 个不同 URL，顺序一致，输入清单 SHA-256 均为 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70`；两边结果均为 2000 个不同输入哈希，无缺失、额外或重复结果。
- [x] Candidate A 在 1052 秒内写完结果但有效帖子证明为 0/2000：374 个 `login/blocked`、1626 个 `empty/failed`，帖子 ID 匹配率和内容证明率均为 0%。前约 4 分钟主要为登录重定向，随后主要转为停留输入地址的空文档；登录预检成功不能外推为并发页面继续持有有效访问状态。
- [x] Candidate B 的 Crawlee 队列在约 925.738 秒内处理完 2000 项，但统一契约只有 315/2000 `post/success`（15.75%）：另有 1580 个 `empty`、22 个 `login` 和 83 个 `error`。前约 7 分钟取得绝大多数成功，之后响应几乎整体转为 `empty`；队列日志的“2000 succeeded”只表示处理器完成，不表示帖子访问成功。
- [x] Candidate B 在队列完成后未退出，最终由人工 TERM 收口，`runner_exit_code=143`、总时长 6744 秒且超出 3600 秒窗口；汇总、环境、逐 URL、请求事件、资源指标和校验值已保留。该退出缺陷独立于 15.75% 的访问契约失败。
- [x] 首轮结论和证据入口已写入 `docs/research/collector-stack-poc-results.md`；原始 URL 和逐请求数据继续只保存在被 Git 忽略的 `artifacts/poc/`。
- [x] 两个候选均已增加 `access-diagnostics.jsonl`：每种 `login/empty` 最多记录 3 条 URL 哈希、最终路径类型、文档长度与哈希、DOM 形态、控制标记、主文档状态链以及 Cookie 数量/名称集合哈希，不保存完整 URL、页面正文、Cookie 名称/值或凭证。
- [x] Candidate B 在 Crawlee 队列返回后刷新完成标记并显式退出；Linux 包装器使用独立进程组，在入口退出、硬截止或信号中断时以 TERM/KILL 收口 npm、tsx 和浏览器后代。
- [x] 项目 `.vevn` Python 23 项、Candidate B 9 项、Python 编译、TypeScript 类型检查、Bash 语法、`pip check`、暂存内容格式检查已通过；本机真实 Chrome/Playwright 合成夹具分别确认 A/B 可落盘 `empty` 诊断，B 在队列完成后正常退出。
- [x] 源码提交 `2913d3bd00c75c2e32e6625c1e7eca327c192d0e` 已生成 v0.2.15 完整包与免重装热修包：完整包 SHA-256 为 `70ac81c451eac1a84cf1e65be7519f9407a986d5741a60c59f22d16af43a126d`、包内 29/29 校验一致；热修包 SHA-256 为 `6b5c4cc85dbb6dc9c780179f4042905b85237a97bb611d5faac244daade52ceb`、10 个成员完整、4 个 Shell 入口权限均为 `0755`；两包已复核零已知凭证标记。

**下一步**：不覆盖本轮失败证据；在目标 Linux 覆盖免重装热修包后执行 `./poc/linux/test-access-transition.sh`。脚本按原顺序取前 500 条、A/B 各使用 1200 秒窗口并返回诊断压缩包；复核真实 `access-diagnostics.jsonl` 与退出码后，再决定是否重新启动三轮 2000 条硬门禁。
**边界**：当前只确认两候选在本轮配置下失败；`empty` 的具体平台判定信号尚未取证，不把它直接写成已确认验证码或限流。不得用 Crawlee 队列统计替代统一结果契约，也不得把人工 TERM 后生成的完整目录改写为通过。
**关联**：结果目录 `artifacts/poc/results/candidate-{a,b}/round-1-*`；报告 `docs/research/collector-stack-poc-results.md`；输入清单 SHA-256 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70`。

---

## 2026-08-10 — 修复 Candidate A 已认证帖子导航等待完整 load

**总目标**：保持 Scrapling 与 Crawlee/Playwright 两个固定候选不变，让 Candidate A 在已认证会话下完成最多3条联通门，并保留与 Candidate B 相同的帖子 ID 和内容证明契约。
**状态**：✅ 目标 Linux 双候选联通门已通过；允许进入首轮2000条吞吐测试

**干到哪了**：
- [x] 已校验目标 Linux 结果包 `connectivity-20260810T200311+0800.tar.gz`：外层 SHA-256 为 `56a9c0ca02ff065f3a8a460238e98cbf0ffffaf3f9e7aa399f00434169579ed6`，22/22 内部校验一致；`session_state_copied` 对 A/B 均为 `true`，网络基线全部通过。
- [x] Candidate B 使用复制的会话完成3/3 `post/success`，完成率、帖子 ID 匹配率和内容证明率均为100%；这确认账号、会话、3条样本和服务器网络均可用。Candidate A 在已认证首帖的 Scrapling `page.goto(wait_until=load)` 满90秒，尚未进入登录分类和逐 URL 队列。
- [x] Candidate A 的登录确认与逐 URL 访问现统一通过 Scrapling `page_setup` 把首次 `goto` 及框架随后固定的 `wait_for_load_state(load)` 映射为 `domcontentloaded`；资源过滤、固定短等待、帖子 ID 和标题/正文成功契约保持不变。
- [x] 联通脚本现把已启动但未写登录结果的非零退出记录为 `runner_failed_before_login_result`；汇总在候选退出或契约错误时优先返回 `inspect_candidate_runtime_or_contract_error`，不再误报 `runner_not_started` 或登录问题。
- [x] 项目 `.vevn` 的联通定向13项通过；真实 Chrome + Scrapling 本地夹具在永不完成的子文档下于625ms返回 HTTP 200并取得1个内容证明节点，复现并验证 DOM 就绪处理层级。
- [x] 全量验证为项目 `.vevn` Python 21项、Candidate B 8项、两端编译/类型、Bash语法、`pip check`、`git diff --check` 和凭证形态扫描通过。完整包 `threadsnap-poc-dual-runner-0.2.14-linux.tar.gz` 的 SHA-256 为 `5dad34b78539927143c63672ec708559a123406b2efff74d79655e3e428aa932`，源码提交为 `db0c0b7f35ddbd14509ddc201cc34ba4d8b1a605`，25/25 内部校验一致且校验清单无 CR 字节。免重装包 `threadsnap-candidate-a-dom-ready-hotfix-0.2.14.tar.gz` 的 SHA-256 为 `1a67b6583b9e79a424d80f216d0f5027f4c1e050a33c92ce547ad1dbc8954128`，4个运行文件与提交内容一致，Shell 入口权限为 `0755`，不安装依赖且不含凭证。
- [x] 目标 Linux 结果包 `connectivity-20260810T203827+0800.tar.gz` 的外层 SHA-256 为 `06a2161568a2c3ed4c39c4c3a203a9a76a8a62f1c3c1271b17dc37a6dc15422b`，23/23 内部校验一致；预检、浏览器、DNS/TCP/TLS/HTTP 和 A/B 会话复制均通过。Candidate A/B 各自3/3均为 `post/success`，完成率、帖子 ID 匹配率和内容证明率均100%，未恢复控制数和契约错误均为0，最终 `ready_for_2000=true`、`next_action=run_2000_url_test`。

**下一步**：目标 Linux 执行 `./poc/linux/run-all.sh round-1`，按同一固定2000条清单先后运行 Candidate A/B；每个候选独立拥有一小时窗口。复制回两个结果目录后校验 `SHA256SUMS` 并形成首轮对比结论。
**边界**：不更换两个候选，不跳过内容契约，不重复短信登录；本轮 Candidate B 3/3成功只关闭其联通分支，不外推 Candidate A 或2000条结果。
**关联**：分支 `codex/fix-candidate-a-dom-ready-navigation`；入口 `poc/candidate-a/src/throughput.py`、`poc/linux/test-connectivity.sh`、`poc/shared/finalize_connectivity.py`。

---

## 2026-08-10 — 修复 Linux 联通门的候选会话交接

**总目标**：保持 Scrapling 与 Crawlee/Playwright 两个固定候选不变，让短信初始化保存的两份独立会话真实进入最多 3 条的联通门，再据此决定是否启动 2000 条测试。
**状态**：🟡 v0.2.13 会话交接热修包已完成；等待目标 Linux 覆盖后复跑联通门

**干到哪了**：
- [x] 已校验目标 Linux 结果包 `connectivity-20260810T164845+0800.tar.gz`：外层 SHA-256 为 `f5ad41ad630986b1d553a71eacc4c3ac3d0218e5faed60bdaa3b25114b71b28a`，23/23 内部校验一致；DNS/TCP/TLS/HTTP 全部通过，但最终 `ready_for_2000=false`。
- [x] 两个短信初始化结果本身已成功；本轮联通失败的共同根因是 `prepare_connectivity_config.py` 把运行目录切到新的 `profiles/connectivity-candidate-*`，却没有复制原候选 `storage-state.json`。Candidate B 因此重新进入密码登录并触发二次短信验证；Candidate A 在同一未认证入口等待 `load` 满 90 秒。该结果不构成候选框架失败。
- [x] 联通准备阶段现按原始 `config.json` 位置解析 A/B 各自 `profile_dir`，每轮删除旧联通隔离目录、只复制当前 `storage-state.json` 并保持 `0600`；源状态缺失时不沿用旧副本。`prepare.log` 新增不含状态值的 `session_state_copied` 布尔证据。
- [x] 项目 `.vevn` 的联通配置测试已新增“两个候选状态分别复制且不回显内容”和“源状态缺失时删除陈旧副本”，定向 10 项通过；候选技术和普通吞吐逻辑未改变。
- [x] 完整包 `threadsnap-poc-dual-runner-0.2.13-linux.tar.gz` 的 SHA-256 为 `80ef1170aa610100e215537fd89a914660597985e7ad261365bddc9005772594`，包内源码提交为 `b80dd98824e5d96ec4748e6d8cd0f1810cb6a272`，25/25 内部校验一致且 `SHA256SUMS` 的 CR 字节为 0。免重装包 `threadsnap-connectivity-session-handoff-hotfix-0.2.13.tar.gz` 的 SHA-256 为 `24037abedac9d8f07569505e41c5376892162d8e49b3fba3909a4e97761c7983`，代码成员与提交内容一致、不安装依赖且清单声明零凭证。

**下一步**：目标 Linux 覆盖 v0.2.13 免重装包后直接复跑 `test-connectivity.sh`，先确认 `prepare.log` 中 A/B 的 `session_state_copied=true`，再以汇总 `ready_for_2000` 决定是否进入 2000 条。
**边界**：不重复短信登录、不共享 A/B 会话、不把状态文件、Cookie、动态码或真实凭证放入热修包、Git、日志或结果；当前结果只证明联通脚本没有使用已认证状态，尚未形成 2000 条结论。
**关联**：分支 `codex/fix-connectivity-session-handoff`；入口 `poc/shared/prepare_connectivity_config.py`、`poc/linux/test-connectivity.sh`。

---

## 2026-08-10 — 为纯命令行 Linux PoC 增加可视验证码人工入口

**总目标**：保持 Scrapling 与 Crawlee/Playwright 两个固定候选不变，在纯命令行目标服务器的原浏览器上下文中完成人工可视验证；确认短信实际进入倒计时后再读取动态码并保存候选隔离会话。
**状态**：🟡 v0.2.12 验证码图片路由修复包已完成；等待目标 Linux 复核 Candidate A/B

**干到哪了**：
- [x] 根据目标 Linux `POST /send_activation_code/v2/` HTTP 200 后加载验证中心、`verification_visible=true` 且 `countdown_visible=false` 的共同证据，把阻塞定位为短信发送前的可视验证；不再继续修改导航或点击定位。
- [x] 候选 A/B 均增加回环 CDP 启动参数、可视验证等待状态、十分钟有界等待及 `visual_verification_required`、`manual_verification_completed`、`sms_send_confirmed` 结果字段；检测到可视验证时不提前读取短信码。
- [x] `poc/linux/bootstrap-sms-session.sh` 为 A/B 分配独立默认端口 9222/9223，并输出 Windows SSH 隧道与 `chrome://inspect` 操作入口；CDP 只绑定 `127.0.0.1`，不增加 Linux 桌面或 VNC 依赖。
- [x] 已同步技术路线、首个平台链档、PoC 计划和 Linux README；明确本入口只用于 PoC 初始化，正式验证码及会话续期方案仍未决。
- [x] 本机验证通过：项目 `.vevn` 运行 Python 16 项测试及候选 A 语法检查；Candidate B 8 项测试及 TypeScript 类型检查通过；Git Bash `bash -n`、`git diff --check` 和已知真实凭证扫描通过。真实浏览器检查分别得到 `candidate_a_cdp_page_target=ready` 与 `candidate_b_cdp=ready`，证明 Scrapling 和 Crawlee 启动链均实际开放可由 DevTools发现的回环 CDP 端点。
- [x] 首次 `0.2.11` 完整包复核发现 Windows 构建脚本以 CRLF 写入 `SHA256SUMS`，Linux `sha256sum -c` 会把行尾 `\r` 解释为文件名；已在版本化构建脚本中固定为 UTF-8/LF 并补回归断言，首次包及其哈希作废后重新生成。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.11-linux.tar.gz`，SHA-256 为 `1cc8a3c08286dbaef35aa4eafca86381daf308bf7f3e810c2517bcd56b77a890`，包内源码提交为 `bf20e32bd677cb96ace3bd361a86551f0c80c36e`；Linux `sha256sum -c` 25/25 通过、`SHA256SUMS` 的 CR 字节为 0、真实凭证匹配为 0。免重装包 `threadsnap-manual-captcha-cdp-hotfix-0.2.11.tar.gz` 的 SHA-256 为 `bea1de19f9113abf1c93047b69e28af3d9e1bf024ecec9aff8609985319e668c`，5/5 文件成员、零真实凭证、不安装依赖且短信入口权限为 `0755`。
- [x] 目标 Linux 已通过 9222 SSH 隧道在 Windows Chrome DevTools 显示 Candidate A 原浏览器登录页和滑块容器，证明 CDP、隧道和远程页面入口生效；滑块报 `[5202] 图片加载失败`，同时页面 Logo 缺图。源码回溯确认 Candidate A 短信入口调用含 `image` 的通用登录过滤器，Candidate B 短信入口也显式拦截 `image`；根因是 PoC 自身资源路由，不是隧道或候选框架。
- [x] Candidate A 新增短信初始化专用资源集合，仅从原过滤规则放行 `image`/`imageset`；Candidate B 的短信初始化只继续拦截 `media`/`font`。普通密码诊断和2000条吞吐路径保持原资源策略，两个候选技术不变。
- [x] 本机真实浏览器图片夹具分别得到 `candidate_a_sms_captcha_image=loaded;requests=1` 和 `candidate_b_sms_captcha_image=loaded;requests=1`；Candidate A 同时修正短任务关闭页面时导航诊断定时器产生的 `TargetClosedError` 清理噪声。项目 `.vevn` 运行 Python 17 项测试及语法检查通过，Candidate B 8 项测试及类型检查通过，Git Bash 语法、`git diff --check` 和已知凭证扫描通过。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.12-linux.tar.gz`，SHA-256 为 `736249f7962eca5255990db3b06a1a2226156229ec7ed9e9b82f62d77616a624`，包内源码提交为 `3a810a0e797a601de1d7dc874891712d9af773c0`；Linux `sha256sum -c` 25/25 通过、`SHA256SUMS` 的 CR 字节为 0、真实凭证匹配为 0。免重装包 `threadsnap-captcha-image-routing-hotfix-0.2.12.tar.gz` 的 SHA-256 为 `2cc5f9c03a4894cce3ecdeb286875a79c7e3dce6f46e355ff917f24ae6ab06e7`，5/5 文件成员、零真实凭证、不安装依赖且短信入口权限为 `0755`。

**下一步**：目标 Linux 在现有目录覆盖 v0.2.12 免重装包后先运行 Candidate A，复核验证码图片、验证后倒计时和会话复访；A 通过后以 9223 对 Candidate B 执行相同步骤，两个候选会话均成功后再运行独立联通门。
**边界**：CDP 人工操作不计入 2000 条计时窗口；两个候选不共享资料目录或会话；验证码、动态码、Cookie、挑战数据及真实凭证不进入 Git、日志或结果包；目标 Linux 复核通过前不声明联通门通过。
**关联**：分支 `fix/captcha-image-routing`；入口 `poc/linux/bootstrap-sms-session.sh`、`poc/candidate-a/src/throughput.py`、`poc/candidate-b/src/throughput.ts`。

---

## 2026-08-10 — 增加 Linux 双候选独立联通门

**总目标**：在目标服务器执行 2000 条测试前，先用最多 3 条已验证样本独立确认 Linux 环境、网络链路、两个固定框架的自动登录和真实帖子访问；失败时返回完整诊断包后再按证据修复。

**状态**：🟡 v0.2.10 点击后平台响应证据包已完成；等待目标 Linux 分别复跑候选 A/B

**干到哪了**：

- [x] 新增 `poc/linux/test-connectivity.sh`，顺序执行预检、浏览器健康检查、DNS/TCP/TLS/HTTP 基线、候选 A Scrapling 登录访问、候选 B Crawlee/Playwright 登录访问和统一结果校验；联通阶段固定并发为 1、最多 3 条、每个候选最多一次访问尝试，不启动 2000 条任务。
- [x] 从 Windows 已认证诊断中选出两个候选共同成功过的 3 条样本，保存到被 Git 忽略的 `artifacts/poc/inputs/connectivity-urls.txt`；数量为 3，SHA-256 为 `9265717feb359f8fa855eaa1582fcc56322d7ce1ed8e9b06c7a8145ff799d99e`。
- [x] 联通脚本无论成功或失败都会生成 `connectivity-results/connectivity-<timestamp>.tar.gz` 和 `.sha256`；汇总以 `ready_for_2000` 和 `next_action` 区分运行时/浏览器、网络路径、登录跳转与内容访问问题，临时明文配置在退出时删除且不进入结果包。
- [x] 本机合成端到端已验证：网络基线为 `transport_ready=true`，候选 A/B 均为 1/1 `post/success`，最终 `ready_for_2000=true`；Python 联通配置与汇总单元测试新增 2 项并通过。
- [x] 已生成 `artifacts/poc/packages/linux-dual-runner/copy-to-linux/` 与标准包 `threadsnap-poc-dual-runner-0.2.1-linux.tar.gz`；标准包 SHA-256 为 `6fad4bca38209fbbf749aae6132713080a835526397a6dbe490e24b131f9a44f`，包内源码提交为 `55896234ff6a79c82c19ff7aceddfe8aa88c8915`，24 项内部校验全部一致。标准包凭证扫描为 0；被 Git 忽略的复制目录 sidecar 已核对为 3 条联通样本与 2000 条吞吐输入。
- [x] 目标 CentOS Stream 10 首次返回：Python 3.12.12、x86_64、glibc 2.39、根分区可用 56G、内存可用 13GiB、Swap 可用 7.8GiB；预检、两个浏览器健康检查和网络 HTTP 200 均通过，排除系统版本、磁盘和内存作为当前阻塞。
- [x] 候选 A 失败原因为联通入口在启动 Scrapling 前未导出安装时使用的 `.runtime/browsers`，因而错误查找 `/root/.cache/ms-playwright/.../chrome`；候选 B 已完成 1 条请求。修复把共享浏览器路径提前到两个候选之前，并增加脚本顺序回归测试；联通脚本同时输出阶段名，并对健康检查和每个候选设置 TERM/KILL 有界超时，避免无输出等待和残留进程，候选技术保持不变。
- [x] 已生成修复包 `threadsnap-poc-dual-runner-0.2.2-linux.tar.gz`，SHA-256 为 `cfc21c5166bd5c02bc4164de24af58626b831c8ab924a086da52926ba6b022c1`，包内源码提交为 `69ceda16c74d19217bc86a9fb7d5f2cc31ec3959`；24/24 内部校验、浏览器路径顺序、有界超时和标准包零真实凭证均已复核。
- [x] 已接收修复路径后的 Linux 联通包：外层 SHA-256 `f406609bc101b063536e7db66167314c3e23be49e6cea6cea77572e052ba132b` 与 21/21 包内校验一致；两个候选均 `submitted=true`、`logged_in=false`，3 条样本均为 `login/blocked` 且 `request_count=0`，候选 B 的 crawler `1 succeeded` 仅表示登录页请求完成。
- [x] 已确认页面默认处于手机验证码登录，旧实现检测到验证码输入框后点击“最后一个按钮”并未可靠选择密码模式；候选 A/B 均改为点击可见且文字精确为“密码登录”的选项，等待账号和密码输入框可见后再填充，并记录 `password_login_selected`。
- [x] 本机真实浏览器夹具已复现“帖子 302 到默认手机验证码页 → 点击密码登录 → 填写提交 → 持久会话复访帖子”的完整链路；Scrapling 与 Crawlee/Playwright 均为 `password_login_selected=true`、`logged_in=true`，随后 1/1 帖子结果为 `success` 且 `request_count=1`。
- [x] 已生成 `threadsnap-poc-dual-runner-0.2.3-linux.tar.gz`，SHA-256 为 `8022bdfa852b852fb7cc7d06958ad3809e83cf98b5e1335bd50256cb25f942fb`，包内源码提交为 `b2af26f289f86cf6e32c596b409f60a98568714a`；24/24 内部校验、两个候选密码登录定位、2000+3 输入数量和标准包零真实凭证均已复核。
- [x] 已接收 v0.2.3 热修后的 Linux 联通包：外层 SHA-256 `5b22368e6e5de4f4344f9e325507200aac63110af215d9c5204ec3cf708474f6` 与 21/21 包内校验一致；两个候选均 `password_login_selected=true`、`submitted=true`，但仍为 `logged_in=false`、`verification_required=true`，3 条结果均 `request_count=0`。密码模式切换已被证实，不再把当前结果归因于未点击密码登录。
- [x] 联通模式新增每个候选的 `login-diagnostic.json` 和条件性 `login-page-redacted.png`：验证信号改为可见正文及可见短信码、验证码、滑块或验证容器；只保存最终路径、查询参数名、标准化提示和控件布尔值，截图前清空输入框并遮盖账号相关文本。两个候选的手机验证失败夹具均生成诊断和脱敏截图，正常密码登录持久会话回归仍为 1/1 `success`。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.4-linux.tar.gz`，SHA-256 为 `a11691a8684ea8e96a2742fdc15fea7df6f61ce25b5354dcf70836344009a9f7`，包内源码提交为 `0be70740b313d323fd8f0a1f8f0d9e0b55b94dde`；24/24 内部校验、2000+3 输入数量、诊断入口和标准包零真实凭证均已复核。
- [x] 已生成免重装热修包 `threadsnap-post-login-diagnostics-hotfix-0.2.4.tar.gz`，SHA-256 为 `49558584ba964ea49a2ae57fc257ed1d0d5b97389fc37082b42c0b53f0230ab3`；包内固定为 4 个运行文件和 1 个说明文件，成员校验 5/5、真实凭证匹配为 0，覆盖现有 v0.2.3 目录后不触发依赖安装。
- [x] 已接收 v0.2.4 Linux 联通结果：外层 SHA-256 `a050e128cab4b996d6e8639118a1cdd0457d737e2c4cff967a84fbd3edf5d1bd` 与 23/23 包内校验一致，结果包零凭证匹配。候选 B 已切换密码登录并提交，脱敏截图明确显示“为保证账号安全，请使用手机验证码登录”，3 条结果均为 `login/blocked`；这已确认当前账号在该服务器访问条件下被要求二次短信验证，不是密码模式选择错误。
- [x] 候选 A 在诊断动作前的首个帖子导航等待 `load` 满 90 秒，未生成逐 URL 结果；源码保持 Scrapling 不变，把登录入口改为与吞吐请求一致地丢弃图片、字体等非必要资源。真实浏览器夹具加入永不完成的图片资源后，候选 A 仍成功生成强制短信验证诊断，候选 A/B 正常密码登录持久会话回归仍均为 1/1 `success`；Python 13 项、Node 8 项及两端类型/编译检查通过。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.5-linux.tar.gz`，SHA-256 为 `de59facf949f78e1925901794eebb7fd77b73cc0f02b5ad1023e862f89fe0552`，包内源码提交为 `6a1f09e8db285da6584a8875ba17a05e52a3b1f2`；24/24 内部校验、2000+3 输入数量和标准包零真实凭证均已复核。免重装包 `threadsnap-sms-verification-hotfix-0.2.5.tar.gz` 的 SHA-256 为 `99423c8f24e61ab065cbad1982302da2f72282e1ba94950039420d2dc59b3eda`，成员 3/3、零凭证匹配且不安装依赖。
- [x] 新增 `poc/linux/bootstrap-sms-session.sh`：只允许从 SSH 交互终端顺序初始化候选 A/B；每个候选点击发送后读取一次动态码，成功时保存权限为 `0600` 的隔离 `storage-state.json`，普通登录和吞吐入口在新进程启动时显式加载该状态。动态码不写入配置、标准输出、结果 JSON 或浏览器自动填充状态。
- [x] 手动短信初始化合成端到端已覆盖两个固定框架：候选 A/B 均完成“短信提交成功 → 初始化进程退出 → 新进程加载状态 → 同一帖子 1/1 `success`”；以独立动态码扫描完整运行目录匹配为 0。正式项目的验证码与会话续期方式已记入链档未决项，本 PoC 手动入口不构成正式方案。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.6-linux.tar.gz`，SHA-256 为 `c7c69de3dcf0a95efab1f73d790559487b1e9663c17741b82973a048c4905d6a`，包内源码提交为 `80a47a01c95b79daa3ac7c6811333ae2025fef34`；25/25 内部校验、短信入口成员和标准包零真实凭证均已复核。免重装包 `threadsnap-interactive-sms-bootstrap-hotfix-0.2.6.tar.gz` 的 SHA-256 为 `356cebbfc3e0fb5f935055372632fbc17739fdaf03fef4fc97d85522a7c5a6dd`，成员 4/4、零凭证匹配且不安装依赖。
- [x] 目标 Linux 首次执行 v0.2.6 候选 A 时只输出启动阶段，回溯停在 Scrapling 以原始帖子 URL 启动的首次 `page.goto(load)`，发送按钮尚未被点击；该回溯只证明导航链未完成，不能单独证明最终画面仍是文章页。两个候选的短信入口现统一由帖子 URL 构造同源登录页，保留原帖子 ID 作为登录后内容判定目标，并输出主文档状态、`DOMContentLoaded/load`、`sms_page_ready`、`sms_request_clicked` 阶段。本机合成端到端确认 A/B 均完成短信初始化、退出后新进程 1/1 复访成功，且初始化前未认证帖子请求数为 0；Python 15 项、Node 8 项及两端类型/编译检查通过。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.7-linux.tar.gz`，SHA-256 为 `c859ba195c2a91aba5c9d549d471bac9b64d212ef7e0ba777dee347abdfd774a`，包内源码提交为 `8c97bae06bf8f3c224a493bcc58cef8549af1e2d`，25/25 内部校验一致且零真实凭证。免重装包 `threadsnap-sms-login-navigation-hotfix-0.2.7.tar.gz` 的 SHA-256 为 `9ddcb3caa5561f335f858e50ef3f7b00215cbf5f392687f915988d9ca3db4d45`，5 个文件成员、零真实凭证且不安装依赖。
- [x] 目标 Linux 覆盖 v0.2.7 后，候选 A 已返回登录主文档 HTTP 200 并触发 `DOMContentLoaded`，但未触发 `load`，随后人工中止；这确认原始帖子仅是重定向来源，实际阻塞位于登录页 DOM 就绪后的剩余加载阶段，短信按钮尚未进入。两个候选现仅对首次 `/login-required` 页面执行 250ms 稳定等待，输出未完成资源类型并调用 `window.stop()` 后继续框架原有页面动作；本机永不完成子文档夹具中 A/B 均完成短信初始化及新进程 1/1 持久会话复访。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.8-linux.tar.gz`，SHA-256 为 `4159cf791e33bb5fc0882b04e73455282569059e6681f510a8574d7929e67865`，包内源码提交为 `9cc22cf9f639e61777185dba78aa150eb79feed2`，25/25 内部校验一致且零真实凭证。免重装包 `threadsnap-login-load-stop-hotfix-0.2.8.tar.gz` 的 SHA-256 为 `f3bb5c8d827483fb2e7273395096976ffe80f5948b030197d4096bdad3f6c45e`，5/5 文件成员、零真实凭证、不安装依赖，且归档内短信入口权限已固定为 `0755`。
- [x] 目标 Linux 的 v0.2.8 输出显示未完成资源为 `fetch:2,script:2,xhr:4`，`window.stop()` 已执行但 Scrapling/Playwright 的 `goto(wait_until=load)` 仍等待，短信按钮依然未进入。现已删除该错误层级的处理：候选 A 在 Scrapling `page_setup` 中仅为短信入口把首次 `goto` 和随后固定稳定性检查映射为 `domcontentloaded`，候选 B 通过 Crawlee 原生 `gotoOptions.waitUntil` 使用相同条件；本机永不完成子文档夹具中 A/B 均进入短信动作，退出后新进程均为 1/1 持久会话复访成功。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.9-linux.tar.gz`，SHA-256 为 `d69472239637323e1196d1275e8e90a20a79ce824908facccc62c25de66cf023`，包内源码提交为 `14a19514dfca803b38d1aa9bfe3406dba0b4b9f6`，25/25 内部校验一致且零真实凭证。免重装包 `threadsnap-sms-dom-ready-hotfix-0.2.9.tar.gz` 的 SHA-256 为 `5ee98eb1a412fb5150e1a9b6c44c070cfa7f248ca9164b5db299511e3acbac87`，5/5 文件成员、零真实凭证、不安装依赖且短信入口权限为 `0755`。
- [x] 目标 Linux 的 v0.2.9 候选 A 已输出 `sms_page_ready` 和 `sms_request_clicked`，证明 DOM 就绪导航与点击链生效；用户随后确认候选 A/B 手机端均未收到动态码。两个候选现同步在点击后等待 5 秒，输出脱敏的 XHR/fetch 请求方法、响应状态和无查询参数路径，并记录按钮倒计时、附加验证与标准化可见警告；本机夹具已验证 A/B 均能记录短信接口 POST/200 和倒计时，再完成动态码登录及新进程 1/1 复访。
- [x] 已生成完整包 `threadsnap-poc-dual-runner-0.2.10-linux.tar.gz`，SHA-256 为 `75a0ee376ec56bf933557dd12154d9f965f7fff30284ceee331ae2d493774720`，包内源码提交为 `e4f04c106d39a1d4c547816c343c409075ba2d54`，25/25 内部校验一致且零真实凭证。免重装包 `threadsnap-sms-send-evidence-hotfix-0.2.10.tar.gz` 的 SHA-256 为 `983095759fd0d820c492450f0cc66720a46f5306e7412065590e66b556b44d98`，5/5 文件成员、零真实凭证、不安装依赖且短信入口权限为 `0755`。

**下一步**：目标 Linux 覆盖 v0.2.10 免重装包后，分别执行候选 A/B 至 `sms_send_evidence`；依据两者的请求路径、HTTP 状态、倒计时和可见提示，判定事件触发、平台接受、附加验证或短信投递层。取得动态码并保存两份会话后复跑联通门；只有复核为 `ready_for_2000=true` 后才运行首轮 2000 条。

**边界**：联通通过只证明当前服务器具备进入吞吐测试的网络、登录和内容访问条件，不构成 2000 条/小时门禁通过；两个固定候选技术、账号条件和结果契约保持不变。

**关联**：分支 `fix/sms-send-evidence`；入口 `poc/linux/bootstrap-sms-session.sh`、`poc/candidate-a/src/throughput.py`、`poc/candidate-b/src/throughput.ts`。

---

## 2026-08-08 — 建立可直接迁移到 Linux 的双候选 2000 条认证测试运行器

**总目标**：保持 Scrapling 与 Crawlee/Playwright 两个固定候选不变，提供配置驱动、可复制到目标 Linux 的同清单 2000 条/一小时测试程序，自动完成登录、访问、资源采样、结果校验和校验值生成。

**状态**：🟡 运行器与源码测试包已完成；等待目标 Linux 执行真实 2000 条轮次

**干到哪了**：

- [x] 候选 A 新增 Scrapling `AsyncDynamicSession` 并发运行器；候选 B 新增 Crawlee `PlaywrightCrawler` 并发运行器。两者均在各自持久配置中自动登录，把浏览器启动和登录计入一小时窗口，逐 URL 即时写入统一结果与请求事件。
- [x] 运行配置固定为一个明文 `config.json`，可设置同一套测试账号、2000 条输入、窗口、超时、重试和候选并发数；标准源码压缩包只包含占位模板，真实配置作为被 Git 忽略的 Linux 复制目录 sidecar 保存，不进入代码、日志或结果。
- [x] Linux 脚本覆盖预检、锁定依赖安装、浏览器安装、启动标记、浏览器健康检查、资源采样、候选单跑/顺序双跑、统一校验和轮次 `SHA256SUMS`；结果目录遵循 `results/<candidate>/<round>-<timestamp>/`。
- [x] 打包器只在跟踪文件无未提交修改时生成标准压缩包，并把精确 Git 提交写入 `PACKAGE-MANIFEST.json`，避免测试包与源码身份脱节。
- [x] 已生成 `artifacts/poc/packages/linux-dual-runner/copy-to-linux/`：标准包 `threadsnap-poc-dual-runner-0.2.0-linux.tar.gz` 的 SHA-256 为 `e86cc54c761af98d59e53148bf9a61a9be0ec7aa5395cfa271e451dd89ae8147`，包内源提交为 `ad65cb06c64df4c79095de07577b2cc5931fe311`，20 项内部校验全部一致；标准包凭证扫描为 0，sidecar 已确认含非空本地配置和 2000 条输入。
- [x] 截止时间内未启动的 URL 以 `deadline_not_started`、`request_count=0` 如实落盘并使轮次失败；已落盘结果可用于中断后只补齐缺失 URL，不把排队、超时或清单外结果计为完成。
- [x] 本机仅执行 1 条合成 URL 的顺序端到端验证，候选 A/B 均得到 1/1 `post/success`，统一契约校验均为 `passed=true`；未在 Windows 启动 2000 条负载。

**下一步**：把 `artifacts/poc/packages/linux-dual-runner/copy-to-linux/` 完整复制到目标 Linux，校验并解压后先运行预检、安装和健康检查，再按 A、B 顺序执行首轮 2000 条；依据 `summary.json`、逐 URL 证据和资源峰值判断，而不是依据小样本外推。

**边界**：当前 Windows 生成的是锁定版本的联机安装源码包，便于立即验证目标主机；它不冒充已在兼容 Linux 生成的最终离线依赖包。明文配置只位于 Git 忽略的操作目录，标准 `tar.gz`、Git、日志和结果仍不含凭证。

**关联**：分支 `feat/linux-poc-runner`；入口 `poc/linux/run-all.sh`；打包脚本 `scripts/build-linux-poc-package.ps1`。

---

## 2026-08-08 — 建立两个固定候选的自动登录与持久会话

**总目标**：保持 Scrapling 与 Crawlee/Playwright 技术不变，使用同一套合法测试账号分别完成自动密码登录，保存候选隔离的本地浏览器配置，并在清除凭证环境后复用会话验证四层真实样本。

**状态**：✅ Windows 登录阶段 1 完成；四层样本 3 条成功、1 条真实 404

**干到哪了**：

- [x] 候选 A 使用 Scrapling `DynamicSession` 自动切换密码登录、提交凭证并经过 SSO 回调回到真实文章页；候选 B 使用 Crawlee `PlaywrightCrawler` 完成相同链路。两者登录结果均为 `post/success`，Cookie 数量均为 39，未出现验证码。
- [x] 账号密码只通过子进程环境变量传入并在命令结束时清除；候选各自的持久浏览器配置位于被 Git 忽略的 `artifacts/poc/profiles/`，登录结果只保存占位化路径、Cookie 数量与名称哈希，代码、日志、报告和 Git 均无凭证字段或凭证值。
- [x] 清除凭证环境后，候选 A/B 分别复用自己的持久配置运行同一四层清单；两者结果完全一致：3 条取得帖子 ID 与内容证明并标记 `success`，同一 `/article/19位` 样本由服务器返回 404 并标记 `error/failed`，成功样本复访仍成功。
- [x] 原始结果位于 `artifacts/poc/results/candidate-{a,b}/login-001/` 和 `authenticated-diagnostic-001/`；诊断 JSONL 的 SHA-256 分别为 `fa637653df7d14124df1839c2a4a873698f6dd5af5ed58f321944dacecad105a`、`157d251de59a3dd71a9b7db25aad963c0f34b61a24512b981248f4cd7f0177d9`。
- [x] 提交前验证：Python 单元测试 6 项、登录/诊断脚本 `py_compile`、`pip check` 通过；Node 单元测试 8 项、TypeScript 类型检查、锁文件安装和生产依赖审计通过，审计为 0 个漏洞；`git diff --check` 与凭证形态扫描通过。

**下一步**：先依据来源索引复核该 404 链接在测试时是否仍为约定有效输入，并用登录模式执行不少于 200 条的低并发正确性预筛；只有固定清单本身有效且两个候选均取得内容证明后，再讨论 2000 条吞吐。

**边界**：不更换候选技术；不把真实 404 归因于框架；登录模式的新轮次不与匿名结果拼接；不在聊天之外再次复制凭证，不把账号、密码、Cookie 值或授权头写入项目文件。

**关联**：分支 `feat/poc-authenticated-session`；候选入口 `poc/candidate-a/src/login.py`、`poc/candidate-b/src/login.ts`。

---

## 2026-08-08 — 修正重定向与会话处理并完成固定框架诊断

**总目标**：保持 Scrapling 与 Crawlee/Playwright 候选组件不变，查明 JSVM 挑战后出现 `302 /login-required` 的原因，补齐重定向链、会话连续性和浏览器网络证据，再重新判定匿名访问能力。

**状态**：✅ Windows 访问链诊断完成；原“匿名访问已确认需要登录”结论撤回

**干到哪了**：

- [x] 原生 Playwright 的全新无 Cookie 上下文停留在文章地址 `200` 的空 JSVM 页面，没有跳转也没有建立 Cookie；这只能证明挑战未完成，不能作为帖子访问结果。
- [x] 使用候选 B 固定的 Crawlee `PlaywrightCrawler` 单通道复核后，挑战脚本建立 19 个匿名 Cookie，随后文章文档请求真实收到 `302` 并进入 `/login-required`；登录页不是结果分类器自行生成。
- [x] 在同一 Crawlee 浏览器上下文先访问首页建立 18 个匿名 Cookie，再访问文章仍收到相同 `302`；因此“只缺首页预热”已被排除，但业务必须登录、设备状态不足或自动化响应分流仍未区分。
- [x] 详细的占位化响应链保存在 `artifacts/runtime/poc-redirect-diagnostics/initial-findings.json`；没有记录 Cookie 值、凭证或完整 URL。
- [x] 核对 2694 条来源索引：规范 URL 与原始 URL 的路径 ID 均 2694/2694 匹配 `article_id`，排除归一化取错 ID；同时发现输入包含 `/article`、`/ugc/article` 与 16/19 位 ID 四层，修正原先只取前 3 条且公共契约只接受 `/ugc/article` 的我方处理缺口。
- [x] 固定四层诊断清单：种子 `threadsnap-poc-diagnostic-20260808-v1`，清单 SHA-256 `22390fcd84492c5d7da6c66215a95aced0ae52196d116cf20434c7d7af3dac12`；候选 A/B 均完成静态会话、首页预热、持久匿名会话、四层首访和同会话复访。
- [x] 两候选的浏览器链一致：文章主文档由服务端返回 `302 /login-required`，随后登录页 `200`；XHR/fetch 只有登录、安全和验证码类请求，内容接口尚未启动。内置 Chromium、本机正式 Chrome、系统代理路径和进程级直连映射均复现该链，排除最终 URL 分类误判、单纯跳转跟随错误、只缺首页预热、浏览器内核选择和系统代理作为单一原因。
- [x] 使用候选 A 无头浏览器从首页真实点击当前可见文章链接，弹出的文章文档仍收到 `302` 后进入登录页，排除“直接打开 URL 而非站内点击”作为原因；候选 A 的 18 个 Cookie 名称哈希全部包含于候选 B 的 19 个中，B 只多稳定的 SSO 状态 Cookie，两者结果相同，排除两框架因不同挑战 Cookie 缺失而产生当前差异。
- [x] 使用当前可公开索引的文章做外部基线：候选 A/B 静态通道均取得 `200` 挑战页，但挑战执行后的浏览器通道仍收到相同 `302`；独立匿名浏览器也进入同一登录页。当前只能确认站点按匿名设备/网络上下文在挑战后执行服务端分流，尚不能从黑盒响应进一步区分具体判定信号，也不能据此认定业务固有要求登录。
- [x] 修复候选无关的三个处理缺口：公共契约支持两种真实文章路径；阶段 1 增加路径/ID 长度分层抽样；候选 B 的单 URL 网络超时改为记录错误并继续整轮。诊断参数支持正式 Chrome和进程级直连对照，候选组件保持不变。
- [x] 提交前验证：项目 `.vevn` 下 Python 单元测试 6 项与 `py_compile`、`pip check` 通过；候选 B 锁文件 `npm ci`、Node 单元测试 8 项、TypeScript 类型检查通过；npm 官方 registry 生产依赖审计为 0 个漏洞，`git diff --check` 通过。

**下一步**：目标 Linux 环境信息和接入条件就绪后，先在其不同网络出口用同一四层清单与公开基线重跑阶段 1；只有 Linux 匿名普通浏览器基线能打开文章时，才继续比较两个固定候选的运行差异。若 Linux 基线同样由服务端 `302`，再由项目负责人确认站点当前匿名访问条件，不提前进入 2000 URL 阶段 2。

**边界**：不替换 Scrapling、Crawlee、CheerioCrawler 或 PlaywrightCrawler；不把当前错误处理方式归因于框架；不根据最终登录 DOM 单独推断业务登录要求；不进入阶段 2。

**关联**：分支 `feat/poc-redirect-session-diagnostics`；原始证据位于 `artifacts/poc/results/candidate-{a,b}/diagnostic-*` 与 `public-index-*`，占位化摘要位于 `artifacts/runtime/poc-redirect-diagnostics/`。

---

## 2026-08-08 — 固定首轮样本并完成候选 A/B 匿名访问冒烟

**总目标**：从已接收的 2694 条真实 URL 输入池固定首轮 2000 条清单，建立候选无关的结果契约和校验器，并用同一小样本验证 Scrapling 与 Crawlee/Playwright 的匿名访问行为。

**状态**：⚠️ 首次配置结果已保留；“需要登录”解释已由上方任务撤回并重新诊断

**干到哪了**：

- [x] 固定首轮 2000 条不同 URL：种子 `threadsnap-poc-round-1-20260808-v1`，算法为 `SHA-256(seed + NUL + URL)` 排序取前 2000 条，清单 SHA-256 为 `4558a54cbe96259c1a64d6fda02658b3b344b8a269fcd85ea32a793572ea5d70`；本地清单与清单元数据位于 `artifacts/poc/inputs/round-1-urls.txt`、`round-1-manifest.json`。
- [x] 建立统一响应分类、结果一致性校验、确定性抽样和跨候选合成夹具；证据：`.vevn\Scripts\python.exe -m unittest discover -s poc\shared\tests -v` 通过 4 项，`npm.cmd test` 通过 7 项，`npm.cmd run typecheck -- --pretty false`、`pip check`、锁文件 `npm ci`、npm 生产依赖审计和 `git diff --check` 均通过，审计结果为 0 个漏洞。
- [x] 候选 A 使用 Python 3.11.4、Scrapling 0.4.12；同一 3 条 URL 的 HTTP 与动态通道最终均为登录页，最终成功 0、未恢复平台控制 3、契约错误 0；证据：`artifacts/poc/results/candidate-a/smoke-001/`，`SHA256SUMS` 的 SHA-256 为 `6cd01030ad846e325f96084b6694cb34a77bbb7482550b6ea1a2edb8e3c3a922`。
- [x] 候选 B 使用 Node.js 22.17.0、Crawlee 3.18.0、Playwright 1.62.1；同一 3 条 URL 的 HTTP 通道均识别为挑战页，浏览器通道最终均为登录页，最终成功 0、未恢复平台控制 3、契约错误 0；证据：`artifacts/poc/results/candidate-b/smoke-001/`，`SHA256SUMS` 的 SHA-256 为 `d28138b56981ff33b87251c19adacee48cfdebab3ffbe8e5622fde742157cba3`。
- [x] 真实 URL、HTML 捕获、逐 URL 结果和日志全部位于被 Git 忽略的 `artifacts/poc/`；Git 只新增原型、合成夹具、锁文件和文档，不提交真实链接、凭证或运行结果。

**下一步**：由上方“修正重定向与会话处理”任务接管；先用两个固定候选完成重定向和持久匿名会话诊断，再确定阶段 1 的正确访问条件。

**边界**：本次 3 条冒烟不能外推吞吐或选择正式技术栈；不把 HTTP 200、挑战页或登录页计为帖子成功；不在 Git、日志或结果结构中保存账号、密码、Cookie 或令牌。

**关联**：分支 `feat/poc-smoke-validator`；代码入口 `poc/README.md`；PoC owner `docs/research/collector-stack-poc-plan.md`。

---

## 2026-08-08 — 分离采集框架 PoC 与第一版功能验收

**总目标**：第一版保留圈子发现和 URL 清单两种输入并完成全部基础功能；当前优先用已收到的真实 URL 清单验证候选采集框架的访问吞吐和风控表现。

**状态**：✅ 口径已确认，文档已同步

**干到哪了**：

- [x] 第一版明确保留圈子列表自动发现与已知帖子 URL 清单导入，两者复用同一详情采集和批次流程；证据：`docs/design/product-design.md` 第 3、6、10 节。
- [x] 当前 PoC 最小通过标准固定为：每轮 2000 个不同真实 URL，一小时内最终完成率、帖子 ID 匹配率和内容证明完整率均为 100%，未恢复风控数为 0；证据：`docs/research/collector-stack-poc-plan.md` 第 6、7 节和 ADR 0006。
- [x] 明确 HTTP 200 不单独代表成功；每个 URL 必须核对帖子标识并至少取得标题或正文存在性证明之一，不得把验证码、挑战页、登录页或异常空响应当作成功。
- [x] `functional-samples.csv` 从当前 PoC 必需输入改为后续第一版功能回归的可选基准；当前必需输入只有 `artifacts/poc/inputs/throughput-urls.txt`，运行结果写入各轮 `url-results.jsonl`、`summary.json` 等文件。

**下一步**：从 2694 条输入池固定第一轮 2000 条 URL、随机种子和清单哈希；随后实现候选 A/B 的最小访问冒烟与统一结果校验器。

**边界**：当前 PoC 不提前实现圈子列表、主评论、数据库、前端或导出；PoC 通过不代表第一版完工。

**关联**：分支 `docs/poc-priority-scope`；ADR `docs/adr/0006-split-collector-access-poc-from-v1-functional-acceptance.md`。

---

## 2026-08-08 — 接收并整理懂车帝 PoC 输入

**总目标**：从甲方工作簿的“懂车帝”工作表生成符合 PoC 吞吐规范的本地 URL 输入池，并记录目标 Linux 已确认环境，不混入其他平台或伪造功能期望字段。

**状态**：✅ 完成

**干到哪了**：

- [x] 使用工作表 `懂车帝!A1:L2699` 的 2698 行 URL；证据：`artifacts/poc/inputs/intake-report.json` 记录工作表、范围和源文件哈希。
- [x] 生成 2694 条不同规范化帖子 URL；证据：`throughput-urls.txt` 行数与唯一数均为 2694，格式检查为 0 个异常，SHA-256 为 `82d7f4bdb766ba8d7246b04ab18e7a0a358c92616398f3eab576ef711f3f2701`。
- [x] 排除 2 条账号主页并合并 2 条重复帖子记录；证据：本地来源索引记录原工作表行号，Git 摘要不保存完整真实 URL。
- [x] 保存源索引、接收报告、输入清单与原始文件副本；证据：`input-manifest.json` 中 6 个文件的 SHA-256 已逐项复算一致，且 `artifacts/poc/inputs/` 经 `git check-ignore` 确认为忽略路径。
- [x] 从截图确认 CentOS Stream 10（Coughlan）、x86_64、glibc 2.39；CPU、内存、磁盘和运行时等仍标记为未确认。
- [x] 没有生成正式 `functional-samples.csv`；原因：工作簿不含人工确认的可见状态、正文存在性、登录要求和确认时间，来源评论数只能作为候选筛选条件。

**下一步**：由上方“分离采集框架 PoC 与第一版功能验收”任务接管；当前不再等待圈子 URL 或 `functional-samples.csv`。

**边界**：真实 URL、原始工作簿、追溯索引和环境截图只保存在被 Git 忽略的 `artifacts/poc/inputs/`；Git 仅提交数量、规则、环境摘要和哈希。

**关联**：分支 `docs/poc-input-intake`；摘要 `docs/research/poc-input-intake-2026-08-08.md`。

---

## 2026-07-30 — 对齐 forged-in-prod 项目流控制

**总目标**：将 ThreadSnap 的项目恢复、决策传递、验证、多 Agent、反过度工程和长任务控制规则，与 `SPHINX998/forged-in-prod` 的七种模式保持方法一致，同时适配 Codex 和现有仓库文档，不引入 Claude 专用平行配置。

**状态**：✅ 完成

**干到哪了**：

- [x] 固定上游基线为 `31c80e763541e1526aa9f6ca8692bd344ddff62d`；证据：`git ls-remote` 与临时浅克隆的 `git rev-parse HEAD` 一致。
- [x] 核对上游七种模式、五个模板、starter 规则、PowerShell/Unix 安装器和 Claude Stop hook；证据：临时克隆文件树共包含根方法论、`starter/` 和 `templates/`。
- [x] 确认不能直接运行上游 starter；证据：starter 写入 `CLAUDE.md`、`.claude/settings.json` 和 Claude `Stop` hook，会与本项目的 `AGENTS.md` 和现有进度入口形成平行事实源。
- [x] 建立根目录唯一账本、首个平台链档、验证阶梯、记忆门槛、Agent 回执、反过度工程和长任务规则；证据：`docs/process/README.md` 对七种模式逐项映射，旧 `current-progress.md` 已迁移且无残留引用。
- [x] 建立 Codex/Git 兜底；证据：PowerShell 与 Unix 安装脚本均将当前仓库 `core.hooksPath` 校验为 `.githooks`，两个 shell 文件通过 `sh -n`。
- [x] 完成 hook 正反测试；证据：隔离临时仓库中，只有 `sample.py` 时提交退出码为 1，补充并暂存 `WORKLOG.md` 后提交退出码为 0。
- [x] 完成仓库检查；证据：27 个文本文件通过 UTF-8 严格解码，18 个流程必需路径存在，5 个 ADR 均为 `accepted`，PoC/runtime 忽略规则、陈旧路径扫描和 `git diff --check` 通过。
- [x] 修正产品设计末尾遗留的 CSV/XLSX 冲突；证据：功能正文与商务范围现统一为从数据库快照导出 XLSX。

**下一步**：等待甲方提供懂车帝固定样本清单和最终 Linux 主机环境信息，再按 `docs/chains/first-platform-delivery.md` 与 PoC 计划启动两个候选原型。

**边界**：不复制 `.claude/`；不声称 Git pre-commit hook 等同于 Claude 的会话结束 hook；不为尚未发生的事故编造项目记忆。

**关联**：分支 `docs/forged-workflow-control`；ADR `docs/adr/0005-adopt-forged-in-prod-workflow-control.md`。

---

## 2026-07-30 — 完善项目文档读取与事实源规则

**总目标**：让新任务按类型读取正确的仓库事实源，避免只依赖 `AGENTS.md`、历史对话或全局记忆。

**状态**：✅ 完成

**干到哪了**：

- [x] 新增 `docs/README.md` 文档索引并补充 `AGENTS.md` 强制读取矩阵；证据：PR #2 已合并，merge commit 为 `a686ad5c3c38ba2b60319d1ad998796843b5f81f`。
- [x] 完成 UTF-8、引用路径、ADR 状态、PoC 忽略规则和 `git diff --check` 检查。

**下一步**：由本条上方的新任务接管，不再维护第二份当前进度文档。
