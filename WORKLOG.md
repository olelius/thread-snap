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

## 2026-08-30 — 汽车之家验证码完成后自动续跑
**总目标**：纠正验证码/访问验证被错误当成重新登录的恢复路径，并在人工验证完成后自动保存更新状态、恢复原任务。
**状态**：✅ 代码、状态路由、自动续跑、错误分类、owner 文档、完整验证和本地服务加载均已完成。
**干到哪里了**：
- [x] 数据库确认批次 `20260830-185206-001` 的上游来源原为 `PLATFORM_CHALLENGE` / `PLATFORM_CAPTCHA_REQUIRED`，旧恢复入口却统一传入 `fresh=true`；全新 Profile 丢失登录态后，当前补提批次4项转成 `AUTH_REQUIRED`，另3项会话刷新后的限频被外层错误包装为 `TASK_INTERNAL_ERROR`。
- [x] 批次恢复按错误类型分流：验证码或访问验证强制继承现有加密 Profile并打开检查点触发URL；真实 `AUTH_REQUIRED` 才使用全新 Profile打开官方登录页。前端明确展示当前为验证码恢复，并隐藏无效的“使用全新登录环境”操作。
- [x] 认证中继记录实际验证页；验证页返回原站后自动导出并加密保存 Session/Profile、关闭窗口、调用既有 `resume_platform` 将等待任务恢复为队列状态。未观察到可确认跳转时仍保留“保存 Session”作为人工兜底。
- [x] 会话刷新后的验证码、访问验证、限频等 `CollectorFailure` 复用同一分类器，不再泄漏为 `TASK_INTERNAL_ERROR`。
- [x] 完整后端218/218、Ruff、compileall、pip check、前端TypeScript和2468模块生产构建、`git diff --check`全部通过；本地后端已加载新代码并返回`/health=ok`，当前真实等待批次路由探针返回`AUTH_REQUIRED + fresh_profile=true`，证明登录与验证码路径已分离。脱敏回执位于`artifacts/runtime/autohome-challenge-resume-20260830/summary.json`。
**下一步**：完成Git自动收尾；当前历史补提批次已在旧逻辑下把正式Profile覆盖为匿名状态，需要一次重新登录取得服务器Session，之后新发生的验证码恢复将复用登录Profile并在验证完成后自动续跑。
**边界**：系统只观察人工验证页是否返回原站，不自动求解验证码；既有批次错误码、快照和已保存匿名Profile不做历史改写。
**关联**：`src/threadsnap/auth.py`、`src/threadsnap/worker.py`、`frontend/src/features/auth/auth-dialog.tsx`、`docs/design/product-design.md`

---

## 2026-08-30 — 汽车之家平台控制改为原任务人工恢复
**总目标**：确认汽车之家新手动批次在 4 并发和 1 并发仍于候选冻结前失败的真实原因；把验证码和访问验证从终态失败改为可恢复暂停，并让人工会话入口直接打开原始触发 URL。
**状态**：✅ 根因诊断、恢复状态机、精确触发 URL、owner 文档、完整验证、本地服务加载、合并和分支清理均已完成。
**干到哪里了**：
- [x] 只读数据库确认：批次 `20260830-174901-001` 冻结并发4、`0/30`、错误 `PLATFORM_CHALLENGE`；批次 `20260830-175005-001` 冻结并发1、`0/30`、同一错误且约0.6秒终止，因此并发不是该轮失败的充分解释，也不存在“0并发才可访问”的合理语义。
- [x] 浏览器与直连分层诊断确认：当前完整加密汽车之家 Profile 打开原圈子仍进入 `safety.autohome.com.cn`；直连传输只导入 storage state Cookie，并使用 curl_cffi 的通用 Chrome 拟态。Session 不是伪造值，但“已保存”不证明当前访问验证已解除，平台具体风控判定条件不可从响应反推。
- [x] 共享 Worker 把 `PLATFORM_CHALLENGE` 与 `PLATFORM_CAPTCHA_REQUIRED` 归入 `waiting_for_auth`，持久化原始触发 URL、保留已完成结果并释放 Worker；限流继续保持独立分类，不冒充登录问题或无限强刷。
- [x] 批次“处理会话”现在携带 `run_id`；后端只从该批次真实 `waiting_for_auth` 任务读取检查点 URL，并让全新服务器浏览器直接打开该 URL。Session 保存仍只检查结构并恢复同一任务，未新增圈子、帖子或点赞预检。
- [x] 新增访问验证暂停、精确触发 URL 定位和非等待批次拒绝三条回归；完整后端217/217、Ruff、compileall、pip check、前端 TypeScript 与2468模块生产构建、`git diff --check` 全部通过。
- [x] 后端已加载修复分支，`/health=ok`、Vite代理健康；OpenAPI包含`run_id`，以既有失败批次只读调用恢复入口返回`409/RUN_AUTH_TASK_NOT_FOUND`，证明非等待任务不会创建浏览器。脱敏诊断与运行回执位于`artifacts/runtime/autohome-control-diagnosis-20260830/summary.json`。
- [x] 修复已由 PR #236 合并到 `main`，功能分支与远程分支均已清理；合并后的本地服务继续返回健康状态。
**下一步**：用户在后续批次出现访问验证时点击“处理会话”，系统直接打开实际触发 URL；完成平台页面操作并保存 Session 后，原任务从原 URL 续跑。
**边界**：本修复建立可恢复状态，不承诺规避平台控制；用户仍需在官方页面完成平台要求的实际操作。既有失败批次和快照保持不可变，新代码只作用于后续任务。
**关联**：`src/threadsnap/worker.py`、`src/threadsnap/auth.py`、`frontend/src/features/auth/auth-dialog.tsx`、`docs/design/product-design.md`

---

## 2026-08-30 — Session 保存与采集访问门禁分离
**总目标**：人工认证窗口只取得并保存服务器浏览器 Session，不再用当前页面、圈子首帖、评论、点赞或用户身份接口判断“登录是否成功”；真实访问条件继续由原任务在原 URL 判断。
**状态**：✅ 代码、界面语义、领域合同、完整验证、本地真实 Session 保存路径、合并和分支清理均已完成。
**干到哪里了**：
- [x] 根因确认：旧 `finish` 流程在导出 storage state 后仍创建平台采集器，以已配置圈子首帖执行 `validate_auth/validate_circle`；汽车之家详情被实时安全验证页拦截时，系统因此把“Session 已取得”误报为“登录状态校验未通过”。
- [x] 三平台共享认证完成操作现只检查 storage state 可持久化结构并加密保存 Session；不判断当前页面 URL，不创建采集器，不预访圈子、帖子、评论、点赞或用户端点。结构错误和持久化错误仍保留独立错误码，旧正式 Session 在新状态保存失败时保持不变。
- [x] Session 保存后恢复同一平台队列，原任务按原 URL 执行实际采集门禁；汽车之家可信点赞和易车账号身份条件仍属于真实任务，不被删除、隐藏或伪造为认证窗口成功结论。
- [x] 配置页改为“Session 已保存 / 最近保存时间 / 获取或更新 Session”，认证窗口按钮改为“保存 Session”，并明确“已保存”不等于页面登录或采集访问已经验证。
- [x] 新增“不调用汽车之家采集验证器仍完成保存”、结构无效保留旧 Session、持久化失败分层等回归；全仓215/215通过，Ruff、compileall、pip check、前端TypeScript与生产构建（2468模块）以及 `git diff --check` 通过。
- [x] 本地后端加载新代码后，以既有加密 Profile 真实创建汽车之家认证任务并立即保存：消息序列为 `browser_starting → ready → validating → completed`，任务与页面均为 `completed`，Session 保存时间已更新，后端 `/health=ok`；脱敏回执位于 `artifacts/runtime/session-capture-boundary-20260830/summary.json`。
- [x] ADR 0051、领域词汇、产品设计、技术路线、部署验收步骤、后续平台链档及旧 ADR 修订关系已同步。
- [x] 功能修复已由 PR #234 合并为 `main@7c4ffd9`，功能分支与远程分支均已清理；合并后的本地后端继续返回 `/health=ok`。
**下一步**：无代码、文档、验证、本地服务或 Git 缺口；用户在官方页面操作完成后直接点击“保存 Session”，实际任务自行判断原 URL。
**边界**：storage state 至少包含结构有效的 Cookie 才构成可保存 Session；这一检查只证明数据可持久化，不证明账号登录或任一业务端点可访问。历史批次、原 URL 和冻结候选保持不变。
**关联**：`docs/adr/0051-separate-session-capture-from-collection-probe.md`、`src/threadsnap/auth.py`、`frontend/src/features/auth/auth-dialog.tsx`

---

## 2026-08-30 — 固定圈子候选并持久重试原 URL
**总目标**：确保每圈结果与同次页面清单、截图中的前 N 个候选严格对应；任何瞬时访问错误只重试原来源或原帖子 URL，绝不使用列表后续帖子补位。
**状态**：✅ 三平台采集器、共享 Worker、领域合同、完整验证、真实原 URL 复访、合并和本地服务加载均已完成。
**干到哪里了**：
- [x] 根因确认：旧采集器按最终成功数循环，候选网络失败后继续读取 N+1 帖子；即使前端隐藏异常，结果身份也已经与原截图前 N 个卡片不一致。
- [x] 懂车帝、汽车之家和易车统一按来源顺序冻结前 N 个去重候选；详情失败不再向后补位。适配器版本分别升级为 `dongchedi-dynamic-v6`、`autohome-club-v5`、`yiche-community-v4`。
- [x] 共享 Worker 把 `PLATFORM_NETWORK_ERROR` 转为同任务持久重试：候选错误重试完全相同的帖子 URL，候选冻结前的来源错误重试原来源 URL；2秒起、最高60秒退避，失败数保持0，当前批次占据同平台 FIFO 队首并可在服务重启后恢复。
- [x] 新增三平台不补位合同、候选网络重试、来源网络重试和连续5xx归一化回归；全仓215/215通过，Ruff、compileall、pip check、前端TypeScript检查、2468模块生产构建和 `git diff --check` 通过。
- [x] 对历史批次 `20260830-144510-001` 中两个原始超时帖子 URL 做当前Session只读直连复访，2/2均取得 `visible` 且正文或媒体证明成立、失败0；未访问任何后续替代帖，脱敏回执位于 `artifacts/runtime/fixed-candidate-retry-20260830/summary.json`。
- [x] ADR 0050、领域词汇、产品设计、技术路线、截图链档、首平台与后续平台链档已统一固定候选口径。
- [x] 功能修复已经PR #232合并为 `main@181deab`，功能分支和远程分支均已清理；本地后端重启后 `/health=ok`，平台接口返回汽车之家 `autohome-club-v5`、懂车帝 `dongchedi-dynamic-v6`、易车 `yiche-community-v4`，三者后台传输均为 `direct_http`。
**下一步**：无代码、文档、验证、本地服务或Git缺口；之后新圈子批次直接使用固定候选和原URL持久重试语义。
**边界**：登录失效继续进入认证恢复；验证码、限流和平台明确的删除、身份冲突或内容不成立不是网络成功假设，仍按既有控制或终态合同处理。历史批次和截图保持不可变。
**关联**：`docs/adr/0050-freeze-circle-candidates-without-replacement.md`、`src/threadsnap/worker.py`、`src/threadsnap/collectors/`

---

## 2026-08-30 — 成功任务最终失败计数归零
**总目标**：从数据源头消除“来源已正常补足并成功，但任务或批次仍累计候选失败数”的矛盾，使三平台共享 Worker 只把终态未解决失败计入业务失败数。
**状态**：✅ Worker语义、正反回归、owner文档、完整后端验证、合并和本地服务加载均已完成。
**干到哪里了**：
- [x] 根因确认：Worker分段进度把每次候选错误立即累加到 `failed_count`，终态又直接按检查点失败记录数赋值；即使后续候选补足目标并进入 `success`，计数仍残留并聚合到批次。
- [x] 三平台共享 Worker 现于运行中保持业务失败数0；终态 `success` 与 `waiting_for_auth` 写入0，只有 `partial_success` 或 `failed` 写入未解决候选失败数。候选URL、错误码和错误消息继续保存在任务检查点用于服务端诊断。
- [x] 新增补足与未补足两条集成回归：前者验证运行中及终态任务/批次失败数均为0且检查点仍有诊断，后者验证目标不足仍为 `partial_success`、失败数1。
- [x] 完整后端210/210通过；目标文件Ruff、compileall、pip check和 `git diff --check` 通过。
- [x] 功能修复已经PR #230合并为 `main@7ec318b`；本地后端重启后 `/health` 返回 `ok`，后续新任务已加载修正后的共享 Worker。
**下一步**：无代码、文档、验证、本地服务或Git缺口；后续新批次直接使用新失败计数语义。
**边界**：历史批次保持冻结，不改写既有数据库；前端兼容逻辑继续把修复前已成功达标的历史任务显示为失败数0。真实未达标、部分成功和失败任务仍如实显示失败数及重新提取入口。
**关联**：`src/threadsnap/worker.py`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`

---

## 2026-08-30 — 成功达标批次隐藏已替换候选诊断
**总目标**：来源任务成功达到配置有效结果数量时，批次列表、详情摘要和来源任务弹窗只显示正常成功结果，不再把过程中已经由后续候选补足的内部失败记录显示为异常、跳过或待确认。
**状态**：✅ 现场根因、前端展示、owner文档和真实批次页面验收均已完成。
**干到哪里了**：
- [x] 现场批次 `20260830-144510-001` 为懂车帝14个来源、420/420成功；A9L与T11各有一个候选详情请求发生约21秒网络连接超时，系统均继续发现并补足30/30。数据库中的2条 `PLATFORM_NETWORK_ERROR` 是内部诊断，不是未完成结果或评论待确认。
- [x] 批次列表在成功达标时不再显示候选失败提示；详情摘要把用户可见失败项派生为0；来源任务弹窗只统计未达标或失败来源，成功达标行不再显示已替换候选数量。内部 `failed_count` 和检查点保持不可变，仍可用于服务端排障。
- [x] 产品设计和技术路线明确“自动重试/向后补足属于原批次正常流程”，成功达标时不向用户展示异常、跳过或待确认文案。
- [x] 前端TypeScript检查与生产构建通过，Vite转换2468个模块；1680×900真实批次页面确认“失败项0、失败来源0个”，页面中“存在异常 / 异常候选 / 待确认”均为0命中，脚本错误0。截图与脱敏回执位于 `artifacts/runtime/recovered-candidate-display/`。
- [x] 展示修复已经PR #228合并为 `main@ea4d2fc`，功能分支与远程分支均已清理；合并后后端健康且Vite继续加载合并后的同一页面代码。
**下一步**：无代码或本地页面缺口；保留真实网络失败诊断但不污染成功达标批次的业务展示。
**边界**：未达到目标、任务失败或批次部分成功时继续如实显示失败项并提供重新提取；本次不改写历史数据库计数和检查点。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/features/runs/runs-page.tsx`、`docs/design/product-design.md`

---

## 2026-08-30 — 统一三平台可配置内部总并发
**总目标**：修复汽车之家和易车并发值保存成功后回退为1的问题，使两平台与懂车帝复用相同的1～8保存、批次冻结和运行限流逻辑。
**状态**：✅ 代码、配置持久化、文档、回归验证和本地服务加载均已完成。
**干到哪里了**：
- [x] 根因确认：汽车之家和易车注册表均发布 `max_concurrency=1`，配置接口因此把用户输入2收敛回1；汽车之家采集器内部还固定写死 `self.concurrency=1`，即使只放开接口也不会真正并发。
- [x] 两平台注册上限统一为8；汽车之家改为使用传入值创建共享有界信号量，易车继续复用既有参数化信号量。三个已接入平台现均发布1～8范围，保存值由跨来源任务、来源内详情和即时重试共同共享，不按圈子倍增。
- [x] 默认值保持既有语义：懂车帝默认2，汽车之家和易车默认1；当前本地用户配置已按本次操作保存为三平台各2，其中汽车之家与懂车帝启用、易车保持停用。配置保存后再次完整重启后端，接口和SQLite仍返回2及范围1～8。
- [x] 146项定向测试和完整后端208/208通过；Ruff、compileall、pip check、前端TypeScript检查与生产构建通过，Vite转换2468个模块；`git diff --check`与SQLite `PRAGMA integrity_check=ok`通过。
- [x] 本地后端已重启并返回 `/health=ok`；脱敏验收回执位于 `artifacts/runtime/platform-concurrency-unification/summary.json`。
- [x] 功能修复已经PR #226合并为 `main@b1bba19`，功能分支和远程分支均已清理；合并后本地服务继续返回三平台当前值2、范围1～8。
**下一步**：无代码、配置或本地服务缺口；页面刷新后会从后端读取三个平台注册范围1～8和当前值2。
**边界**：历史批次继续保留创建时并发快照；汽车之家与易车正式500条生产验收尚未关闭，本次证明配置和有界执行链一致，不把任意部署环境下的8并发描述为已完成容量验收。
**关联**：`docs/adr/0049-unify-configurable-platform-internal-concurrency.md`、`src/threadsnap/collectors/registry.py`、`src/threadsnap/collectors/autohome.py`

---

## 2026-08-30 — 主评论改为非阻塞帖子附属快照
**总目标**：汽车之家和易车在帖子身份及正文或媒体有效时正常保存结果，不再因评论数量、分页终止标记或评论响应差异淘汰整帖、补量或展示异常状态。
**状态**：✅ 代码、合同、真实双样本、完整回归和本地服务加载均已完成。
**干到哪里了**：
- [x] 根因复核：批次 `20260830-120826-001` 的32个候选全部由 `POST_COMMENTS_INCOMPLETE` 门禁淘汰；逐条审计中30条列表回复数与详情一级评论数一致，另2条数量不同但帖子身份、正文和点赞均有效。
- [x] 汽车之家升级为 `autohome-club-v4`，易车升级为 `yiche-community-v3`；两平台均最多保存当前取得的10条一级评论，评论为空、数量差异、分页后续、终止标记缺失或评论响应不可用均不再增加失败数或触发向后补量，评论身份不一致时只丢弃评论数据。
- [x] 固定500验收合同同步取消评论完整性整帖门禁；ADR 0048、领域词汇、产品设计、技术路线、后续平台链档和验收计划已统一新口径。
- [x] 74项定向合同测试通过；真实复跑历史候选 `115873433`（列表6/详情6）和 `115124729`（列表3/详情2）均生成 `visible` 正常记录，回执位于 `artifacts/runtime/nonblocking-comments-20260830/real-autohome-results.json`。
- [x] 完整后端208/208、任务范围Ruff、compileall、pip check、前端TypeScript检查与生产构建通过，Vite转换2468个模块；`git diff --check`通过。全仓Ruff另检出的6个旧PoC导入排序问题均位于本任务未修改文件，不影响生产代码与正式测试检查结果。
- [x] 本地后端重启后 `/health` 返回 `ok`，平台接口确认汽车之家 `autohome-club-v4` 已启用、易车 `yiche-community-v3` 已接入且保持用户原有停用状态；懂车帝继续为 `dongchedi-dynamic-v5`。
- [x] 功能提交 `5a64481` 已经PR #224合并为 `main@ea80e04`，功能分支与远程分支均已清理。
**下一步**：无代码、文档、验证、本地服务或Git收尾缺口。
**边界**：历史批次及既有失败计数保持不可变；登录失效、验证码、限流、帖子身份冲突和正文或媒体缺失继续按既有控制与失败合同处理。
**关联**：`docs/adr/0048-treat-primary-comments-as-nonblocking-post-enrichment.md`、`src/threadsnap/collectors/autohome.py`、`src/threadsnap/collectors/yiche.py`

---

## 2026-08-30 — 账号 Session 成功状态文案与操作入口同步
**总目标**：消除账号认证已经通过但平台卡片仍显示通用“可用 / 登录更新”造成的未刷新错觉。
**状态**：✅ 根因、展示修复、真实页面验证和自动化检查全部完成。
**干到哪里了**：
- [x] 实时后端确认懂车帝 Session 为 `available`，最近校验时间已更新为 `2026-08-30T03:59:40.374028Z`；认证完成消息已执行全查询失效刷新，因此不是 Session 未保存或查询缓存未刷新。
- [x] 账号 Session 的 `available/valid` 改为显示“登录有效”，操作入口按状态切换为“登录 / 重新登录 / 更新登录”；访问会话继续单独显示“未初始化 / 可用 / 已失效”和对应操作。
- [x] 前端 TypeScript 检查与生产构建通过，Vite 转换2468个模块；1680×900真实配置页确认汽车之家和懂车帝显示“登录有效 / 更新登录”，易车显示“已失效 / 重新登录”，页面脚本错误0，Git外截图位于 `artifacts/runtime/account-session-status-label/status.png`。
**下一步**：无代码或验证缺口；易车仍按既有流程完成一次新账号登录。
**边界**：只修正账号/访问会话的展示语义和状态化按钮，不改变后端状态码、Session 门禁或认证恢复流程。
**关联**：`frontend/src/features/config/config-page.tsx`、`docs/design/product-design.md`

---

## 2026-08-30 — 三平台账号认证与直连 HTTP 采集统一
**总目标**：把易车从仅证明页面可访问的会话改为与懂车帝、汽车之家一致的账号登录 Session，并移除三平台普通来源验证和帖子提取中的浏览器依赖及失败回退。
**状态**：✅ 代码、状态迁移、真实直连样本和回归验证已完成；当前历史易车访问会话已明确标记失效，等待用户在配置页完成一次新的易车账号登录。
**干到哪里了**：
- [x] 前提复核：汽车之家 `autohome-club-v3` 原本已经全程直连 HTTP；懂车帝15个现有来源首页均以登录Session直连取得完整30/30，浏览器回退触发0次；证据位于 Git 外 `artifacts/poc/results/collector-http-unification-20260830/`。
- [x] 易车升级为 `yiche-community-v2`：冻结公开 PC `v311` 签名合同，列表/圈子身份直接请求官方业务接口；详情严格解析一次 HTTP 203 Cookie 挑战；一级评论直接请求同款接口。未知协议、第二次异常、验证码、限流和身份冲突均失败关闭，不启动 Chromium 补量。
- [x] 易车注册改为 `account_login`，官方登录页、加密Profile/Session、真实账号门禁、`waiting_for_auth`、有界刷新、原批次续跑和平台FIFO全部复用共享认证状态机；账号门禁同时要求非空 `username` Cookie 与官方用户消息接口非空 `userId`。启动时不含账号身份的历史易车会话保留加密状态但标记 `invalid`，前端显示“登录 Session / 登录更新”。
- [x] 懂车帝移除 `DynamicSession` 列表回退并升级 `dongchedi-dynamic-v5`；SSR行数不足直接返回 `CIRCLE_HTTP_ROWS_INCOMPLETE`。平台注册统一公开 `background_transport=direct_http`；浏览器只属于认证状态机的人工登录/有界Session刷新和用户明确开启且平台支持的页面证据。
- [x] 真实零浏览器样本：易车瑞虎8直连返回50条列表、详情内容/媒体和评论成功，当前匿名历史会话被账号门禁正确拒绝；懂车帝风云A9和汽车之家A9来源验证均成功。三组验证前后 Chromium 进程均为0。
- [x] 1680×900真实配置页确认易车显示“登录 Session / 已失效 / 登录更新”，不再出现“访问会话”，页面脚本错误0；Git外回执与截图位于 `artifacts/runtime/platform-http-auth-unification/`。
- [x] 完整后端208/208（113.652秒）、Ruff、compileall、pip check、前端TypeScript检查与生产构建通过，Vite转换2468个模块；`git diff --check`通过。
**下一步**：在“平台配置”对易车执行“登录/更新”，扫码或账号登录后点击“完成并校验”；通过账号身份门禁后，再按既有计划运行易车正式500/500生产验收。
**边界**：本任务移除的是普通采集浏览器，不删除共享人工认证浏览器，也不删除懂车帝显式页面证据浏览器；易车当前不支持圈子页面证据。正式500条不与历史访问会话样本拼接。
**关联**：`docs/adr/0047-use-account-login-and-direct-http-for-yiche.md`、`src/threadsnap/collectors/yiche.py`、`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/collectors/registry.py`

---

## 2026-08-28 — 分离易车访问会话与后台无头验证
**总目标**：修复易车普通来源验证弹出系统浏览器，并纠正把易车 `available` 访问会话误写成账号登录认证的产品与界面语义。
**状态**：✅ 后台验证显示模式与交互会话模式已解耦，易车访问会话已独立建模并通过真实无头验证、页面交互和全量回归。
**干到哪里了**：
- [x] 根因确认：Worker 创建易车采集器时错误复用了人工交互会话的 `auth_browser_headless=false`，所以普通来源验证启动可见 Chromium；易车 `validate_auth()` 只检查目标页可访问性，从未证明账号身份，Session `available` 也只表示访问门禁最近通过。
- [x] 平台注册表新增后台浏览器模式和 `authentication_mode`；易车后台验证/提取固定无头，只有用户主动初始化或更新访问会话时保留 CDP 有头交互，汽车之家与懂车帝继续标记为 `account_login`。
- [x] 平台配置页把易车显示为“访问会话、初始化/更新”，明确“不代表账号已经登录”；账号平台仍显示“登录 Session、登录/更新”，批次与验证状态统一显示“等待平台会话/处理会话”。
- [x] 真实瑞虎8来源验证任务 `01a047aa-a82e-7cba-a788-69a536ab6a93` 成功；进程采样89次确认 Chromium 主进程含 `--headless`，回执位于 `artifacts/runtime/yiche-hidden-validation/runtime-validation.json`。
- [x] 1680×900真实页面确认三平台会话卡片语义和易车交互Dialog，无脚本错误；截图位于 `artifacts/runtime/yiche-hidden-validation/session-modes.png` 与 `access-session-dialog.png`，SHA-256分别为 `49e514a9f62317ca38f7e5047e1d50ec50eb0b7a0f03f1d7bba655772ade6b28`、`fcec77c48eb49e56c10ecb5f8538f408302346c2eb4c475bb5954eb39ce8d68d`。
- [x] 完整后端210/210（111.602秒）、Ruff、compileall、pip check、前端TypeScript检查和生产构建通过，Vite转换2468个模块；`git diff --check`通过。
- [x] 功能提交 `f6564a1` 已经PR #220合并为 `main@bbcb5dd`，功能分支已清理；合并后本地服务健康，能力API返回易车 `authentication_mode=access_session`，真实瑞虎8重新验证任务 `01a047b9-d142-76ce-af9f-5acb2858cf2a` 成功，当前页面再次确认三平台模式和3个可用会话且无脚本错误。Git外回执位于 `artifacts/runtime/yiche-hidden-validation/post-merge-validation.json`。
**下一步**：无业务、代码、文档或本地服务恢复缺口；易车正式500/500仍按既有独立生产验收计划执行。
**边界**：不移除易车对 Chromium 页面运行时动态签名和真实XHR的依赖；后台只改为无界面运行。访问会话可用不等于账号已登录，不新增账号字段，也不输出Cookie、令牌或Profile内容。
**关联**：`CONTEXT.md`、`src/threadsnap/collectors/registry.py`、`src/threadsnap/worker.py`、`frontend/src/features/config/config-page.tsx`、`docs/design/product-design.md`

---

## 2026-08-28 — 补录三平台圈子来源并按平台折叠展示
**总目标**：把用户截图中的汽车之家、懂车帝和易车圈子来源录入当前本地配置，并把持续增长的来源长表改为按平台展开和收起。
**状态**：✅ 21 条缺失来源已原子补录，现有来源增至 37 条；来源与圈子页已按三平台折叠分组并通过真实页面交互验证。
**干到哪里了**：
- [x] 对截图中的 36 个有效链接按平台稳定来源身份去重：懂车帝 14 条和汽车之家 A9 已存在；保留额外的懂车帝风云A9“最新发布”独立来源，仅新增汽车之家 13 条和易车 8 条。
- [x] `/api/v1/circles/batch` 一次提交完整剩余来源且删除 0 条；回查为汽车之家 14、懂车帝 15、易车 8，共 37 条，16 条原已验证来源保持原状态，21 条新增来源为未验证且不自动参与。
- [x] “来源与圈子”按平台配置顺序派生折叠分组，组标题展示来源数、已验证数与本组未保存数；默认展开首个平台，支持展开/收起全部、组内新增以及修改平台后移入目标组，仍复用原跨平台批量保存事务。
- [x] 真实 1680×900 页面无脚本错误，默认/全部展开/全部收起时可见数据行分别为 14/37/0；1024px 视口横向溢出保持在来源列表内部，页面主体未产生横向滚动。截图和脱敏录入回执位于 `artifacts/runtime/platform-source-import/`，回执 SHA-256 为 `1c37f69e10c11ac825d9b94ff3cb342f50bf5be5f1fd163aa393fca452fbbfde`。
- [x] 完整后端 209/209（111.866秒）、Ruff、compileall、pip check、前端 TypeScript 检查与生产构建通过，Vite 转换 2468 个模块；SQLite `PRAGMA integrity_check=ok`，`git diff --check` 通过。
- [x] 功能提交 `1fb68fb` 及账本证据提交 `3cff5f8` 已经 PR #218 合并为 `main@b1600f9`，功能分支已清理；合并后服务健康，本地与远端 main 一致且工作区清洁，37 条来源及默认/全部展开 14/37 行再次通过 API 和真实页面复核。
**下一步**：代码和录入范围均已完成；待各平台 Session 可用时，由用户按需要执行“验证全部待验证”，首次验证通过后系统会自动开启对应来源的自动参与。
**边界**：本次不创建验证或提取批次，不把未验证来源提前启用；“无”的易车单元格不创建占位来源，不改变既有懂车帝最新发布来源及已验证来源状态。
**关联**：`frontend/src/features/config/config-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`

---

## 2026-08-28 — 修复认证空值Cookie误判与错误阶段展示
**总目标**：修复浏览器已登录且门禁通过后，合法空值Cookie被Session结构校验拒绝，并被界面误报为页面加载失败的问题。
**状态**：✅ 空值Cookie合同、认证阶段错误分类和前端提示均已修复；真实汽车之家认证、加密Session恢复及新URL批次已完成闭环。
**干到哪里了**：
- [x] 现场任务 `01a0474e-8d8f-701e-a971-4401d818093b` 证明认证页面HTTP 200且错误发生在完成校验后的Session写入；`中继已断开`是任务进入失败终态后的结果，不是起因。
- [x] `SessionStore`现要求Cookie的`name/domain/path`为非空字符串、`value`键存在且为字符串，并接受浏览器合法导出的空字符串值；真正缺字段或类型错误仍以`SESSION_INVALID`拒绝。
- [x] 浏览器关闭前新增Session结构预检；持久化异常使用`AUTH_SESSION_SAVE_FAILED`及“平台会话保存失败”，前端失败状态改为“认证处理失败”，不再归类为页面加载失败。
- [x] 新增空值Cookie导入、缺失value拒绝、认证完成后空值持久化及持久化异常分类测试；7项定向回归通过，Python Ruff和前端TypeScript检查通过。
- [x] 产品设计、技术路线和项目记忆已同步。
- [x] 完整后端209/209（111.474秒）、Ruff、compileall、pip check、前端TypeScript检查和生产构建通过，Vite转换2468个模块，`git diff --check`通过。
- [x] 修复分支服务重启后复用现有加密Profile，真实认证任务 `01a04757-7455-73ee-94cb-8fc5b0ed0030` 完成；汽车之家Session恢复为`available`，加密状态含29项结构有效Cookie且未发现无效结构。
- [x] 新URL批次 `20260828-154857-001`（运行ID `01a04757-e5bd-76e1-b20b-f0485df40dd7`）完成1/1、失败0，帖子115843786再次保存点赞数19，SQLite完整性为ok；Git外脱敏回执位于 `artifacts/runtime/auth-empty-cookie-fix/summary.json`。
- [x] 功能提交 `5ab73f0` 已推送至PR #216，PR范围仅包含本任务9个代码、测试与owner文档文件。
- [x] PR #216已合并为 `main@f6c5911`，功能分支已清理；合并后服务健康、本地与远端main一致，汽车之家适配器v3、认证能力、Session可用状态及批次 `20260828-154857-001` 的点赞数19均再次通过API复核。
**下一步**：无业务、代码、文档或本地恢复缺口；后续按既定计划执行汽车之家认证模式正式500/500生产验收。
**边界**：不记录或输出Cookie值、账号信息、认证票据和Profile内容；原失败认证任务只作为不可复用的运行时证据。
**关联**：`src/threadsnap/session_store.py`、`src/threadsnap/auth.py`、`frontend/src/features/auth/auth-dialog.tsx`、`docs/memories/browser-cookie-empty-value.md`

---

## 2026-08-28 — 汽车之家登录认证与可信帖子点赞数
**总目标**：把汽车之家帖子点赞数从历史空值修正为登录后可验证的真实数值，并复用现有官方认证、加密Session和认证续跑链，避免把匿名占位零值保存为真实数据。
**状态**：✅ `autohome-club-v3` 已完成实现、真实登录门禁、加密Session和点赞读取闭环；独立真实URL批次已把页面动态值 `19` 保存为帖子快照。
**干到哪里了**：
- [x] 根因确认：同一汽车之家帖子在匿名页面显示点赞 `0`，用户登录后显示 `19`；上一批次中的“—”来自v2明确写入 `like_count=null`，不是数据库把0显示成空值。
- [x] 汽车之家registry已开启认证能力并配置官方登录入口与真实论坛探针；继续复用服务器Profile、加密Session、CDP认证Dialog、有界刷新、`waiting_for_auth`和平台FIFO，不新增账号密码配置。
- [x] 首次真实登录暴露并定位校验误报：详情HTML的 `toolbar-praise strong` 是固定加载占位0，登录后由页面脚本调用 `/club/zan/list` 动态更新；旧实现读取了更新前HTML并用异步回复框节点误判登录状态。
- [x] 详情采集现以 `clubUserShow + autouserid + sessionlogin` 的一致非游客Cookie组合证明Session，并按页面同款点赞列表接口读取主帖值；认证后空列表保存数字0，唯一主帖项保存非负整数，认证拒绝进入等待，接口结构、无效值或冲突以 `POST_LIKE_COUNT_INVALID` 失败关闭。
- [x] ADR 0046、领域词汇、产品设计、技术路线、后续平台链档、正式500计划和文档索引已同步；历史批次保持不可变，汽车之家正式500改为认证Session模式从零执行。
- [x] 汽车之家专项、认证能力API及Worker/API/XLSX本地闭环共27项定向测试通过；Ruff通过。真实匿名详情复核返回 `authentication_required`，未再把页面占位0作为结果。
- [x] 用户通过ThreadSnap认证Dialog完成官方登录后，临时Profile证明三项平台登录Cookie身份一致；修正门禁从已配置论坛首帖验证通过，已登录同帖115843786的页面同款点赞接口返回19。Session与Profile均加密持久化，明文任务目录为0。
- [x] 本地服务已重启为 `autohome-club-v3 + authentication=true + session=available`；独立URL批次 `20260828-152435-001`（运行ID `01a04741-9633-781c-baf7-0501b1d763d2`）完成1/1、失败0，数据库和详情API均保存帖子115843786点赞数19，SQLite完整性为ok。
- [x] 完整后端206/206（107.575s）、PoC shared 84/84通过；本次Python范围Ruff、compileall、pip check、`git diff --check`、前端TypeScript检查和生产构建均通过，Vite转换2468个模块。Git外回执位于 `artifacts/runtime/autohome-auth-like/summary.json`；PoC全目录仍有两个未修改测试文件的既有导入排序告警。
- [x] 功能提交 `af10701` 已推送至PR #214，PR范围仅包含本任务12个代码、测试及owner文档文件。
- [x] PR #214已合并为 `main@66ccc1b`，功能分支已清理；合并后本地服务健康，适配器v3、认证能力、Session可用状态及批次 `20260828-152435-001` 的帖子115843786点赞数19均再次通过API复核，本地与远端main一致。
**下一步**：无业务、代码、文档或本地恢复缺口；后续独立执行汽车之家认证模式正式500/500生产验收。
**边界**：不输出、复制或提交账号密码与Session内容，不回写批次 `20260828-144055-001` 的历史空点赞数；正式500/500仍是独立生产验收门。
**关联**：ADR 0046、`src/threadsnap/collectors/autohome.py`、`src/threadsnap/collectors/registry.py`、`tests/test_autohome_collector.py`

---

## 2026-08-28 — 保留汽车之家跨论坛聚合帖并修正批次失败展示
**总目标**：修复汽车之家圈子列表把平台明确聚合的跨论坛帖子误判为错帖的问题，使所选来源的实际前N条按顺序进入快照，并分别保留发现来源与帖子原始论坛身份。
**状态**：✅ `autohome-club-v2` 已实现双身份校验和展示；合并后的本地服务已创建风云A9正式修复批次并完成30/30、失败0，原批次保持不可变。
**干到哪里了**：
- [x] 根因确认：批次 `20260828-135151-001` 的两个 `WRONG_POST` 候选均由风云A9列表返回，列表来源身份为论坛7853，而APP跳转及详情稳定原始归属分别为论坛8563和8666；旧合同错误地要求发现来源与原始归属相等。
- [x] 采集器现分别校验列表来源身份、帖子ID、APP声明的原始论坛和详情身份；有完整聚合证明的跨论坛帖子计入结果，缺少聚合证明或同层身份再次冲突时仍以 `WRONG_POST` 失败关闭。
- [x] 结果 `raw_status` 保存 `discovery_bbs_id/type`、详情 `bbs_id/type` 和 `cross_forum_aggregate`；批次列表与详情显示“跨论坛”、发现来源和原始论坛ID，成功且达到目标数的历史候选失败改称“跳过异常候选”。
- [x] ADR 0045、领域词汇、产品设计、技术路线、后续平台链档、验收计划和文档索引已同步；既有批次不回写，正式500条继续从零执行且固定19场景标签合同不扩张。
- [x] 修改后真实风云A9前30条重放在6.973秒内完成30/30、失败0；原先被跳过的帖子115775128与115912264分别以发现论坛7853、原始论坛8563/8666保留在第7和第21位，有序帖子ID SHA-256为 `10ae698b4c884a4fd427a054e0893b0050c1e40015ec60af1e95beb852dfe0a5`，Git外回执位于 `artifacts/runtime/autohome-cross-forum-feed/summary.json`。
- [x] 汽车之家专项22/22、完整后端202/202（107.706s）、PoC shared 84/84通过；本次Python范围Ruff、全量compileall、pip check、`git diff --check`、前端TypeScript检查和生产构建通过，Vite转换2468个模块。
- [x] 功能提交 `dd71321` 已经PR #212合并为 `main@af2ff54`；本地与远端`main`一致，汽车之家运行时适配器确认为 `autohome-club-v2`。
- [x] 合并后正式手动批次 `20260828-144055-001`（运行ID `01a04719-9bd9-7048-a2e4-7abe597f245f`）于14:41:01完成30/30、失败0；帖子115775128和115912264均持久化为发现论坛7853、原始论坛8563/8666，当前动态列表位置分别为第10和第22条。原批次 `20260828-135151-001` 仍为成功30/30、历史候选失败2，未被回写。
- [x] 正式批次API返回30条、跨论坛标记2条，SQLite `PRAGMA integrity_check=ok`；真实页面显示2个“跨论坛”标记，帖子详情同时显示“发现来源 A9 · 最新回复”和“原始归属 跨论坛聚合 · 论坛 ID 8563”。Git外回执与页面截图位于 `artifacts/runtime/autohome-cross-forum-feed/`。
**下一步**：无业务、代码、文档或本地恢复缺口；只需合并本次账本收尾记录并清理文档分支。
**边界**：不改写原批次及其失败历史，不把没有APP聚合证明的普通论坛错配放行，不改变平台并发、认证、页面证据、舆情或正式500条验收分母。
**关联**：ADR 0045、`src/threadsnap/collectors/autohome.py`、`frontend/src/features/runs/`、`tests/test_autohome_collector.py`

---

## 2026-08-28 — 修复口碑浏览器通用错误不重试且丢失诊断
**总目标**：修复口碑巡检中 Patchright 通用 `Error` 被直接落为内部错误、既不保留故障阶段也不执行既有一次有界重试的问题，并通过正式补跑链恢复当日瑞虎9缺失结果。
**状态**：✅ Patchright通用错误已进入阶段诊断与既有一次有界重试；本地正式关联补跑已恢复瑞虎9，原批次保持不可变且关联结果达到27/27。
**干到哪里了**：
- [x] 从本地批次 `RP-S-20260828-9797` 确认瑞虎9为 `REPUTATION_VALIDATION_INTERNAL_ERROR`、`attempt_count=1`、证据目录未创建；错误发生在证据写入前，且底层文本被 `_validation_error()` 收敛为类型名 `Error`。
- [x] 懂车帝口碑适配器现为页面上下文、页面创建、导航、标题等待、布局冻结、DOM测量和证据截图维护明确阶段；Patchright 通用错误写入不含Session的服务端阶段诊断，并转换为 `REPUTATION_BROWSER_RUNTIME_ERROR + retryable=true`，复用现有最多一次重试。
- [x] 浏览器上下文关闭失败只记录运维诊断，不再覆盖已取得的结果或原始异常；前端和数据库继续只接收稳定中文业务错误，不暴露底层运行时文本。
- [x] 新增回归证明底层错误文本只进入服务日志、业务错误不泄漏细节且标记为可重试；既有进度回归继续证明暂时错误第二次尝试终态前不进入完成分子。
- [x] 口碑专项21/21、完整后端199/199（120.926s）通过；Ruff、compileall、pip check、`git diff --check`、前端TypeScript检查与生产构建（2468 modules）通过。
- [x] 修改后使用当前本地加密Session真实复核瑞虎9：5.469秒取得3.85分、同级第3、口碑量831、评价篇数831、差评率24%，指标区域PNG SHA-256为 `944c564e2ce911f22ac1156fa510cdd47b66440e18a657eaaeadd16a152e3e48`；回执位于Git外 `artifacts/runtime/reputation-browser-error-retry/`。
- [x] 本地后端重启到修复提交后，正式“补跑失败项”创建 `RP-R-20260828-055455-02F4`；13:55:01完成1/1结果和1/1证据，瑞虎9为3.85分、同级第3、口碑量831、评价篇数831、差评率24%，证据文件存在且实际哈希与数据库同为 `944c564e2ce911f22ac1156fa510cdd47b66440e18a657eaaeadd16a152e3e48`。
- [x] 原批次 `RP-S-20260828-9797` 仍为原始 `partial_success + 26/27 + 失败1`，原失败行仍保存 `REPUTATION_VALIDATION_INTERNAL_ERROR`；关联视图现为 `resolved=27`、`unresolved=0`、`linked_status=success`、证据27/27，SQLite `PRAGMA integrity_check=ok`。
- [x] 功能提交 `9f9e7a7` 已精确暂存5个目标文件并推送到PR #211；远端报告可合并，敏感模式扫描0命中。
**下一步**：无业务或本地恢复缺口；按项目自动收尾授权合并PR #211并清理分支，随后以合并后的`main`复核本地健康和关联结果。
**边界**：不覆盖或重算原批次，不扩大重试次数，不把全部异常都标为暂时错误，不记录Session、Cookie或令牌；本次不改变口碑指标与证据合同。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`tests/test_reputation.py`、`docs/memories/patchright-error-classification.md`

---

## 2026-08-27 — 修复易车认证完成校验的 Patchright 回调错误
**总目标**：修复易车认证窗口在“完成并校验”阶段报 `_pw_impl_instance_` 并错误显示页面加载失败的问题，让已加载的官方页面能进入真实 Session 校验。
**状态**：✅ 易车页面响应回调已改为普通 Python 函数；认证页加载、CDP 画面、完成校验和 Session 更新已在本地真实服务贯通，内部校验异常也不再误报页面加载失败或向前端泄露运行时细节。
**干到哪里了**：
- [x] 通过本地认证 WebSocket 复现易车页面可正常加载、CDP Screencast 可正常出帧，排除认证页、浏览器启动、WebSocket 和 CDP 画布故障。
- [x] 将截图异常精确定位到 `YicheCollector._navigate()` 的 `page.on("response", responses.append)`；Patchright 1.61.2 会在事件回调上缓存 `_pw_impl_instance_`，内置方法对象不支持写入该属性。
- [x] 回调改为可被 Patchright 缓存内部包装器的普通函数，并增加模拟 `_pw_impl_instance_` 写入的显式回归；旧的内置方法写法会在该测试中直接失败。
- [x] 认证校验器未预期异常现返回 `AUTH_VALIDATION_INTERNAL_ERROR + validation_failed`，保留当前浏览器供重试，只把异常类型写入服务日志，不再把内部异常文字发送到页面。
- [x] 易车与认证专项34/34、完整后端198/198（107.547s）通过；Ruff、compileall、pip check、`git diff --check`、前端 TypeScript 检查与生产构建（2468 modules）通过。
- [x] 当前本地认证 WebSocket 真实贯通 `browser_starting → ready → frame → validating → completed`，官方根页 HTTP 200，完成后 Session 更新，未再出现 `_pw_impl_instance_` 或 `AUTH_BROWSER_FAILED`。
**下一步**：按项目授权自动完成Git收尾，随后以合并后的 `main` 重启本地后端并复核前端代理、易车状态和认证画面。
**边界**：不保存或输出用户认证凭证；真实登录是否通过仍取决于用户在官方页面完成认证，本修复只处理本地运行时对象错误。
**关联**：`src/threadsnap/collectors/yiche.py`、`tests/test_collector_contract.py`、ADR 0007、ADR 0014

---

## 2026-08-27 — 发布易车本地适配器并修正“未接入”状态
**总目标**：让已经完成本地开发与公共业务闭环的易车适配器在配置页真实显示“已接入”，允许用户显式启用，同时保留正式生产验收的独立证据边界。
**状态**：✅ 易车 `yiche-community-v1` 已从休眠注册改为 `available`、默认停用、并发上限1；旧数据库在新构建启动时自动升级接入状态，不自动启用、不扩张既有规则。
**干到哪里了**：
- [x] 确认截图中的“未接入”来自 registry 的硬编码 `not_integrated` 及 bootstrap 强制回退，不是前端缓存、数据库损坏或用户配置错误。
- [x] collector registry 现把易车声明为 `available`；bootstrap沿用 `main` 已合入的发布状态同步语义，使已有数据库从旧休眠值升级，并保留未来撤回时的活动任务收口能力。
- [x] 易车配置页状态、开关、认证入口和公共任务链按真实发布状态开放；默认 `enabled=false`，升级不创建任务，页面证据与视频地址刷新能力仍按实际保持关闭。
- [x] 扩展既有 ADR 0044 覆盖易车，把适配器代码可用状态与正式500条生产验收分开；产品设计、技术路线、后续平台计划、链档、部署说明和文档索引已同步，ADR 0043 的500条证据合同继续有效。
- [x] 在 `main@f0b6757` 汽车之家已经发布的新基线上重放，保留懂车帝、汽车之家和易车均为 `available` 的当前事实；撤回回归改用临时registry状态验证，不依赖当前必须存在休眠平台。
- [x] 重放后三平台专项51/51、后端完整发现测试196/196通过（105.848s）；Ruff、compileall、pip check、`git diff --check`、前端 TypeScript 检查和生产构建通过，Vite转换2468个模块。
- [x] 真实旧库升级冒烟先把汽车之家与易车都写为 `not_integrated`，重启后 `/health=ok`，三个平台注册均为 `available`；后两个平台保持 `enabled=false`，易车显式启用返回200、并发收敛为1，认证任务返回202。
- [x] 独立终审结论 `confirmed`、无剩余P1/P2：易车专项32/32、后端196/196（106.370s）、PoC shared 84/84、前端构建2468模块；隔离真实UI显示已接入3/3且控制台0异常，11个变更文件的5类敏感模式扫描0命中。回执位于Git外 `artifacts/runtime/agents/yiche-release-review/`。
**下一步**：无业务实现缺口；按项目授权自动完成Git收尾，并刷新当前本地后端与前端运行状态。
**边界**：本次发布的是已经交付的易车帖子适配器，不自动启用平台、不启用易车口碑巡检、不把尚未执行的正式500条写成已通过；汽车之家已发布状态保持不变。
**关联**：`docs/adr/0044-separate-local-adapter-publication-from-formal-sample-acceptance.md`、`src/threadsnap/collectors/registry.py`、`src/threadsnap/services.py`、`tests/test_yiche_integration.py`

---

## 2026-08-27 — 发布汽车之家本地接入状态
**总目标**：纠正汽车之家本地开发已经完成但配置页仍显示“未接入”的状态错位，让已实现适配器通过正常平台注册、启用、任务与Worker路径运行，同时保留正式500条验收缺口。
**状态**：✅ 汽车之家本地适配器已发布为 `available`，既有数据库可由bootstrap自动提升，配置页允许显式启用；正式500条环境验收仍独立保留。
**干到哪里了**：
- [x] 根因确认不是前端缓存：`autohome-club-v1` 在collector registry中被明确写为 `not_integrated`，且bootstrap只会降级未发布平台、不会把既有数据库状态提升为新发布状态。
- [x] 汽车之家registry改为 `available`，继续默认停用、并发上限1、页面证据与认证能力关闭；bootstrap以registry同步适配器发布状态，提升时保留用户启用选择，撤回时仍关闭平台并收口活动任务。
- [x] 本地组合测试改走正常平台Worker领取路径，不再直接调用私有平台头；新增既有数据库状态提升、默认停用、显式启用、并发收敛和统一手动任务测试。
- [x] 产品设计、技术路线、后续平台链档、验证计划、部署说明与ADR 0044统一分离“本地适配器发布”和“正式500条环境验收”；易车状态未变，既有规则和来源不自动扩张。
- [x] 显式设置独立工作树 `PYTHONPATH` 后，汽车之家及相关配置/Worker专项测试 `23 / 23 OK`；首次测试误读主工作区editable安装的旧代码，已定位并纠正测试入口。
- [x] 完整后端 `196 / 196 OK`、PoC共享测试 `84 / 84 OK`；`ruff check src tests`及本次PoC测试、`compileall -q src tests poc/shared/tests`、`pip check`、`git diff --check`、前端 `npm run check` 与生产构建（2468 modules）均通过。PoC全目录Ruff另报告2个未修改文件的既有导入排序问题，不属于本次差异。
- [x] 隔离数据库真实启动 `127.0.0.1:18000`：`/health=ok`，汽车之家首次GET为 `available + enabled=false + autohome-club-v1`；PUT启用返回200、`enabled=true`，并发输入8收敛为1。
- [x] 功能提交 `fb0d8fc` 经PR #207合并为 `main@e71cfa5`；本地主工作区后端已重启，`8000/health`与前端代理`5173/health`均为`ok`，两条平台API都返回汽车之家 `available + enabled=false + autohome-club-v1 + concurrency=1`，当前接入数为2/3。
**下一步**：按正式环境验收计划完成汽车之家冻结500条与可持续访问验证；该工作不回退本地“已接入”状态。
**边界**：`available` 表示本地适配器和公共业务闭环已发布，不声明真实500/500、正式环境可持续访问、页面证据、认证或口碑指标已经验收；平台仍由用户显式启用。
**关联**：`src/threadsnap/collectors/registry.py`、`src/threadsnap/services.py`、`docs/adr/0044-separate-local-adapter-publication-from-formal-sample-acceptance.md`

---

## 2026-08-27 — 实现易车社区适配器与公共接入闭环
**总目标**：在不复制批次、调度、存储、API、前端和导出能力的前提下，以真实易车页面证据接入第二个平台帖子采集。
**状态**：✅ 易车适配器、休眠门禁与公共业务链已在 `main@cac1b91` 的汽车之家共享抽象上完成重放和本地门禁。真实500条冻结清单与正式运行门未执行，平台仍为 `not_integrated` 且不可启用。
**干到哪里了**：
- [x] 复用 `main` 已有 collector registry/Protocol、验收 Provider 和媒体能力合同，只为易车补充真实解析器、URL规范化、认证入口与保守能力声明；懂车帝和汽车之家既有行为保持原合同。
- [x] 易车适配器按真实页面的两个列表顺序、50条列表响应、圈子与帖子联合身份、结构化正文、原图、直连MP4和最多10条一级评论映射；动态签名不逆向，使用 Patchright 页面引导并监听真实XHR。
- [x] TencentCaptcha/WAF、平台业务码、429、空响应、错帖、私有区混淆和未验证评论翻页组合均失败关闭；挑战页不计有效结果，认证等待保留已完成检查点。
- [x] services、worker、auth 和前端统一读取平台注册项；易车解析器已注册但 `adapter_status=not_integrated`，bootstrap会把历史误开放状态降回休眠，平台启用、运行、认证和Worker入口均遵守数据库门禁。休眠期允许暂存来源但不验证、不自动参与；发布后手动提取、每周/循环计划、平台FIFO、详情、主评论与XLSX复用既有公共链。
- [x] Review补齐：评论API业务错误优先检查、请求contentId身份、可靠终止证明和业务码分类；圈子冻结 `forum_id + seo_name + forum_name`，现有external_id继续保存slug；列表冻结首个total；详情核对最终URL与圈子；易车本地时间按Asia/Shanghai解释；完整成功链标记visible并保存脱敏证明；主文档先识别WAF再分类HTTP，最初203只有在捕获到最终URL对应的后续主文档200时继续，否则验证码进入认证等待、普通文档保持HTTP错误。
- [x] bootstrap回退未发布平台时同步把遗留 `queued`、`running` 和 `waiting_for_auth` 圈子任务以稳定 `PLATFORM_NOT_INTEGRATED` 收口并重新聚合批次，清空该平台活跃队列且不修改既有成功终态历史。
- [x] 易车尚无页面证据能力，后端在手动与计划任务快照中按平台注册能力规范化为关闭并保留请求语义，前端在纯易车范围禁用并说明；手动切换平台同时清除已选圈子和两类URL输入，避免隐藏旧平台输入。
- [x] 重放后本地门禁：三平台与汽车之家/易车业务组合专项 `64 / 64 OK`；完整后端 `195 / 195 OK`（114.025s）；`ruff check src tests`、`compileall -q src tests`、`pip check`、前端 `npm run check`、`npm run build`（2468 modules）及 `git diff main...HEAD --check` 均通过。
**下一步**：在重放后新HEAD上做独立复核；随后以事前冻结的500个不同有效URL从头执行易车正式 `500 / 500`、真实页面配置/任务/XLSX闭环和环境证据；补齐当前未观察的0条、10+及多页评论覆盖或如实保留缺口。
**边界**：未把动态请求头、追踪ID、真实业务清单、页面原文或Session写入Git；未实现口碑指标；未用 `hasMore`/`totalPage` 的不可靠值终止；未把本地fixture或单样本解析升级为正式500条通过。
**关联**：`src/threadsnap/collectors/base.py`、`src/threadsnap/collectors/yiche.py`、`docs/chains/later-platform-delivery.md`、`docs/research/later-platform-onboarding-plan.md`

---

## 2026-08-27 — 汽车之家本地接入开发与休眠门禁
**总目标**：在独立工作树中完成汽车之家本地接入开发，确认真实论坛来源、两个列表顺序和字段合同，贯通统一采集与固定500验收入口，并只让正式500/500决定平台何时启用。
**状态**：✅ 本地适配器、实际视频URL、评论终止门禁、固定500执行器、界面门禁和共享业务组合闭环已完成；真实500/500尚未执行，因此平台注册仍正确保持 `not_integrated`。
**干到哪里了**：
- [x] 从真实 `iCAR V27论坛` 确认“最后回复”与“最新发布”两个列表关系；两个顺序各发现51页，102次列表请求形成5080条观察，按稳定帖子ID合并为2540个候选。Git外 `sources.json` 与候选文件SHA-256分别为 `e4718647b0d05ba2924f83eaea671699986569ec255a7b9ab5208c574f2c0f91`、`ef31856f52756270d08be9a6d08ba85d172e20f66facecf614967de284c940f7`。
- [x] 匿名详情预检共325次请求：295条有效、7条社区身份不符、22条挑战、1条验证码，首次访问验证出现在选择序号303；未重试、未冻结正式清单，预检manifest SHA-256为 `9f1d9b44a657d8f0361a66df3378c6c4a228547fa9b1b1f577d8bf1037eccdc7`。
- [x] 新增共享采集器协议、平台注册表和 `autohome-club-v1` 适配器；后端、Worker、认证路由及前端平台能力均从注册表读取。汽车之家保持 `not_integrated`、默认停用、并发硬限1；待验收来源不显示可运行验证或自动参与，未声明认证能力时不显示Session入口。
- [x] 适配器交叉校验列表、URL、详情帖子ID和论坛ID；正文、实际图片或同视频ID的实际URL才构成内容证明。真实AHVP脚本和GPI响应证明 `api/gpi` 的四个 `qualities[*].copy` 为带签名HTTPS MP4，生产解析器真实回放4/4；播放器脚本与响应SHA-256分别为 `7ce834de152e4243ff7f3869235853dadfb392fb88bb7cda61d27be3f57dc4e4`、`3c94daf6e2916df86155d7a36b69f8d9bd9a39768ad87a6291ecf4e35a5c807a`。
- [x] 前10条SSR一级评论及一页终止证明、显式删除三态、控制响应首条止损、重复/无界分页停止均有专项测试；不足10条且仍有下一页时以 `POST_COMMENTS_INCOMPLETE` 失败，不再让不完整评论入库。单条和批量来源验证同时过滤未接入平台，遗留队列在Worker侧再次拒绝。
- [x] 新增固定500验收CLI、平台中立文件合同、汽车之家生产Provider和只读复核器；正式入口无可缩小分母参数，逐 seed 绑定最新回复与最新发布，19个场景逐项记录观察或缺口，首控后只保留控制项与其余 `not_requested`，始终形成500个唯一终态。合成CLI只验证工具合同，没有冒充真实500运行。
- [x] 使用休眠适配器known URL fixture真实贯通Worker、持久化、批次/帖子详情API和XLSX，并证明常规Worker不领取 `not_integrated` 任务且测试后门禁未打开；本地组合闭环与线上启用条件已分开。
- [x] 用户提供的飞书业务正文解析出239个文档块：汽车之家来源类型为论坛，单次“最新回复”首页业务目标为50条；真实车型URL的owner是关联表“说明汇总”A1:D14，但该表匿名访问要求登录。正文SHA-256为 `4cc78ef40bcfbda4ed9b77be2d869b878236fea3ba091915e3bb3510aa113a11`；业务50条不改变接入验收500分母。
- [x] 项目虚拟环境后端完整发现测试最终163/163、PoC共享测试84/84、Ruff、compileall、pip check和 `git diff --check` 通过；前端TypeScript检查与生产构建通过，Vite共转换2468个模块。
**下一步**：在新的冷却访问窗口或经真实样本证明的正式汽车之家Session模式下，从零复核并冻结500个候选，完整运行真实500/500；通过后才把平台注册切换为 `available`。
**边界**：本地开发完成不等于平台已启用；本轮295条有效预检和合成500工具测试都不与正式结果拼接，不把HTTP 200、标题或未解析视频ID当有效内容；未修改服务器、未启用汽车之家、未生成正式500清单、未执行口碑映射或新增口碑指标。
**关联**：`poc/shared/later_platform_acceptance.py`、`src/threadsnap/collectors/autohome_acceptance.py`、`docs/chains/later-platform-delivery.md`、`docs/research/later-platform-onboarding-plan.md`、Git外 `artifacts/runtime/autohome-onboarding/`

---

## 2026-08-27 — 固化后续两平台500条接入验收口径
**总目标**：把汽车之家、易车接入所需输入责任、500条验收分母、项目自生成样本与映射、真实缺失及延期口碑指标写入唯一owner文档，并与懂车帝既有2000条门禁分开。
**状态**：✅ 需求口径、技术合同、执行计划、跨任务链档和ADR已同步，真实平台接入与500条运行留待后续实现任务执行。
**干到哪里了**：
- [x] ADR 0043确认汽车之家与易车按平台分别使用项目从社区页面发现、现时复核并事前冻结的500个不同帖子URL验收；两个平台不合并分母，不再要求外部提供2000条URL或功能样本表。
- [x] 最新回复和最新发布入口改由项目通过真实页面点击或导航取得并分别保存；易车已标记来源按真实缺失保留，不生成占位来源，也不阻塞其他存在来源。
- [x] 项目自行生成分层功能样本、访问条件证据及两平台各27款口碑车型映射候选；映射仍经过现有草稿、真实三门禁和显式发布，不按名称自动绑定。
- [x] 汽车之家、易车的口碑评价篇数和差评率来源延期；两个指标及同期证据合同关闭前，不启用对应平台正式口碑巡检，不把当前27项分母扩张为81。
- [x] 新增后续平台链档和接入验证计划，并在产品设计、技术路线、领域词汇、文档索引、首平台链和口碑链中建立唯一引用；懂车帝既有2000条证据及目标CentOS连续三轮门禁保持不变。
- [x] 使用项目 `.vevn` 对10份目标Markdown执行本地引用存在性检查，结果 `missing_refs=0`；`git diff --check` 和差异敏感模式扫描通过。
**下一步**：按 `docs/chains/later-platform-delivery.md` 先盘点两平台真实社区来源与两个列表顺序，再实现适配器并分别生成500条冻结样本执行正式验收。
**边界**：本次只调整并固化文档合同，未访问汽车之家或易车、未生成真实URL清单、未建立Session、未实现适配器，也未宣称500条验收或三平台口碑已经完成。
**关联**：`docs/adr/0043-use-project-discovered-500-sample-gate-for-later-platforms.md`、`docs/chains/later-platform-delivery.md`、`docs/research/later-platform-onboarding-plan.md`

---

## 2026-08-27 — 服务器以应用最小包升级循环计划版本
**总目标**：把当前 `main` 的循环计划、独立循环批次列表和跨类型同秒调度能力更新到目标服务器，同时复用既有离线依赖与运行环境，不重新组装或安装完整依赖载荷。
**状态**：✅ 服务器已由 `0.1.0-8a7ede86679d` 增量升级到 `0.1.0-82d4712919f6`，数据库迁移、服务、内外网接口和回滚链均已验证。
**干到哪里了**：
- [x] 升级前只读确认四个服务均为 `active`、数据库完整性为 `ok`、Alembic 为 `b7d2f4a6c803`，提取、校验、舆情、口碑及删除链活动任务均为 0；当前完整离线包 SHA-256 仍为 `935b0b59ea088a5bfaf60bf0ed92d85713bcc60e7b331efdbb4b3709b829a643`。
- [x] 本地确认 `8a7ede8..82d4712` 之间 `pyproject.toml`、前端 package/lock、`deploy/linux` 和制包脚本均未变化；生成仅含应用 wheel、37 个前端生产文件及兼容元数据的 544,570 字节最小包，SHA-256 为 `cb2a2aa85120b3a0d36ca26fc5f37dd0f90f297f836d2a39693efd6fba1eb44c`，不含 wheelhouse、浏览器、RPM、模型或 `node_modules`。
- [x] 服务器复核最小包外层 SHA、42 项内部校验、目标迁移文件和旧完整包依赖清单；通过 XFS reflink 复用已安装 venv，只强制替换 ThreadSnap 自身 wheel 和前端静态文件，明确跳过依赖安装，旧 release 保留为 `previous`。
- [x] 首次切换中新后端 8000 已健康，但 Nginx 即时探测与 `Requires=` 停止传播发生竞态，自动回滚恢复旧 release 与升级前数据库；确认回滚后四服务、8000/8088 和数据库 `b7d2f4a6c803` 均正常，再按“Nginx 先停、后端切换、分别等待健康”的顺序完成最终切换。
- [x] 最终备份位于 `/var/lib/threadsnap/backups/minimal-release-upgrade/20260827-110014-finalize/`，SHA-256 为 `78e77b4f8eab376bfbf69a53590425f8766338a76c648a2c6212f9ec032a8476` 且完整性为 `ok`；升级后 Alembic 为 `c3f7a1d9e402`，新增三列齐全，既有 3 个节点均保持 `weekly`。
- [x] 完整 `deploy/verify.sh` 通过应用、Wayland、Nginx、SPA、接口隔离、端口、Fernet、有头 Chromium 和离线本地模型；四服务均为 `active`，`pip check` 无破损依赖，公网 `/health` 和 SPA 返回 200、`/internal/v1` 返回 404。`/api/v1/extraction-plan` 已返回 `recurring_nodes`，手动/定时列表为 48 批、循环列表为 0 批；最终汇总 `final-verification.json` 的 SHA-256 为 `478cc37b20e68f1773da1e864c4a1252c654292f4e8dc7baf3a499135ae6bd83`。
**下一步**：无；服务器后续按 `82d4712` 的计划与列表合同运行，完整离线依赖包继续保留为安装与回滚基线。
**边界**：未重组 1.2 GiB 完整离线包，未下载或安装 Python/浏览器/RPM/模型依赖，未创建或补跑业务批次，未修改现有配置与历史数据；公网 Quick Tunnel 地址仍是临时观测值。
**关联**：远端 release `/opt/threadsnap/releases/0.1.0-82d4712919f6`、远端最小包目录 `/var/tmp/threadsnap-minimal-upgrade-82d4712/`、本地运行证据 `artifacts/runtime/remote-minimal-upgrade-20260827-105151-corrected/`

---

## 2026-08-27 — 将循环计划批次拆为独立导航与列表
**总目标**：修正把循环计划放入“提取列表”触发方式筛选的界面误解，为循环计划批次提供独立侧边栏入口、列表路由和对应详情路由，同时保持与定时批次页面一致的能力。
**状态**：✅ 两个列表已在导航、路由和服务端数据范围上完全分开，并继续复用同一套列表与详情实现。
**干到哪里了**：
- [x] 侧边栏新增“循环计划列表”：`/runs` 只展示 `manual`、`scheduled`，`/recurring-runs` 只展示 `recurring`；循环列表不再依赖“全部触发方式”中的循环选项，也不显示只属于手动批次的“新建提取”。
- [x] 两个列表复用 `RunListPage`，两个详情路由复用 `RunDetail`；循环批次从 `/recurring-runs/$runId` 进入详情，侧边栏选中状态、顶部标题、返回入口和删除后去向均回到循环计划列表。
- [x] 批次列表 API 增加可重复 `trigger_types` 集合过滤并保留单值 `trigger_type`；真实本地数据验证提取列表为 33 个且类型只有 `manual,scheduled`，循环列表为 0 个，数据库完整性为 `ok`。
- [x] 后端完整回归 140 项、Ruff、compileall、pip check、前端 TypeScript 检查、生产构建（2468 modules）和 `git diff --check` 通过；真实页面验证两个侧边栏入口、各自选中状态、固定服务端查询范围、循环详情路由与返回、空状态均正确，控制台和页面错误均为 0。
**下一步**：无；后续循环计划实际触发后，批次只进入独立循环计划列表。
**边界**：列表与详情在信息架构上分开但不复制业务组件；不提供手动创建循环批次入口，不改变调度、采集、批次历史或数据库结构；SSH 服务器保持原状。
**关联**：`docs/adr/0041-separate-recurring-run-list-navigation.md`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`、`artifacts/runtime/separate-recurring-runs-20260827-101717/`

---

## 2026-08-27 — 允许定时与循环计划同秒创建独立批次
**总目标**：允许每周定时节点与循环节点在同一实际触发秒共同保存并分别创建类别批次，同时保持同类型节点排重、稳定平台 FIFO 和运行期异常数据兜底。
**状态**：✅ 跨类型同秒配置、独立批次、稳定入队、同类型排重、运行期兜底和完整本地验收均已完成。
**干到哪里了**：
- [x] 提取计划冲突键改为“节点类型 + 星期 + 实际触发秒”：每周与循环节点同秒允许保存，两个每周节点或两个循环节点同秒仍整份配置零写入，并在错误详情返回计划类型和全部冲突位置。
- [x] 跨类型同秒触发分别创建 `scheduled` 和 `recurring` 独立批次，各自冻结规则与运行快照；调度器显式按每周、循环稳定排序入队，同一平台继续使用既有 FIFO，不新增平台并发或跨批次合并。
- [x] 调度器增加运行期同类型冲突复检；异常持久数据中的同类型冲突节点分别记录 `blocked` 事件且整组不创建批次，补齐原产品设计已有但代码缺失的防御门禁。
- [x] 4 项专项测试通过，覆盖跨类型同秒双批次与队列顺序、每周同类型保存冲突、循环同类型保存冲突、异常持久数据阻断和既有节点幂等；后端完整回归 142 项、Ruff、compileall、pip check、前端 TypeScript 检查和 Vite 生产构建（2468 modules）全部通过。
- [x] 当前口径、产品设计、技术路线、首平台链档、长期约束及新 ADR 0042 已同步；旧 ADR 保留并由新决策精确替代跨类型全局唯一部分。
- [x] 隔离应用以真实 `/api/v1/extraction-plan` 保存每周与循环同秒节点返回 200；调度后形成两个 `created` 事件和两个独立排队批次，队列顺序为 `scheduled=1`、`recurring=2`。随后提交两个同秒每周节点返回 400 且 revision 保持 2；证据位于 `artifacts/runtime/cross-type-same-second-20260827-103916/verification.json`，SHA-256 为 `17909dee544fd27726751d45ac03c812869d82b79c1adc97206da5f9ac6f430a`。
**下一步**：无；按项目自动收尾授权提交、推送、合并并清理功能分支。
**边界**：本次允许的是跨类型同时触发和分别入队，不让同一平台并发采集；同类型实际触发秒继续唯一，停机错过节点仍不补跑，历史批次和数据库结构不变。
**关联**：`docs/adr/0042-allow-cross-type-same-second-schedules.md`、`src/threadsnap/services.py`、`src/threadsnap/scheduler.py`、`tests/test_backend.py`

---

## 2026-08-27 — 增加循环计划与独立循环批次类型
**总目标**：在既有每周计划旁增加同样交互结构的循环计划，以星期、同日开始/结束时刻和分钟间隔生成采集触发点，并让循环计划批次与定时批次按类型分开、页面能力保持一致。
**状态**：✅ 配置合同、数据库基线、调度触发、批次类型、前端页面和本地验收均已完成。
**干到哪里了**：
- [x] 循环节点按“开始时刻 + n × 间隔”展开且不超过结束时刻；开始必触发，结束仅在恰好命中时触发。循环节点限制为同一自然日、开始早于结束、间隔为 1 到 1440 的正整数分钟，并与全部启用的每周或循环节点按“星期 + 实际触发秒”统一排重。
- [x] 复用版本化自动提取规则、全局 revision、`/extraction-plan` 单事务、节点—规则关联、调度事件、快照和采集执行链；`schedule_nodes` 以 `node_type` 区分 `weekly`/`recurring`，循环节点增加结束时刻和间隔字段。真实本地数据库升级到 Alembic `c3f7a1d9e402` 前已在线备份，升级后完整性为 `ok`，既有 2 个每周节点保持为 2 个且无异常循环行。
- [x] 每周节点继续创建 `scheduled`/“定时提取”批次，循环节点创建独立 `recurring`/“循环计划”批次；提取列表增加循环计划筛选，列表、详情、进度、重试、导出和删除继续复用同一批次组件与业务能力。
- [x] 配置页增加“循环计划”同级标签，复用每周计划的工具栏、节点卡片、星期按钮、规则多选、启用开关、未保存提示、保存和放弃合同，只将单一时刻替换为开始、结束和间隔字段，并显示触发次数及结束时刻是否命中的即时预览。
- [x] 后端完整回归 139 项、Ruff、compileall、pip check、前端 TypeScript 检查和生产构建通过；真实页面验证 09:00—18:00/60 分钟为 10 次并命中结束，120 分钟为 5 次且最后一次 17:00、不触发结束。1440 与 1280 宽度节点卡片均无横向溢出，循环批次筛选可见，控制台和页面错误均为 0。
**下一步**：无；循环计划按保存后的节点进入既有全局调度器。
**边界**：不支持跨午夜时间段，不补跑停机期间错过的触发点，不新增第二套采集链或批次详情页；本次只迁移并验证本地数据库，未更新 SSH 服务器。
**关联**：`docs/adr/0040-add-recurring-window-schedule-nodes.md`、`src/threadsnap/schedule_times.py`、`frontend/src/features/config/config-page.tsx`、`artifacts/runtime/recurring-schedule-20260827-093734/`

---

## 2026-08-26 — 删除并重建服务器今日口碑巡检 Worker
**总目标**：删除服务器已有的今日正式口碑巡检，释放同日调度身份，并由真实定时协调器创建和执行新的今日巡检 Worker。
**状态**：✅ 旧批次已按正式删除链清除，新 Worker 已由 `ReputationCoordinator` 创建并完成27/27巡检、证据和汇报。
**干到哪里了**：
- [x] 变更前只读确认今日只有一个正式根批次 `01a03bcb-b708-7250-8cb9-f72ea8cfc3a9`（`RP-S-20260826-C3A9`），原状态为成功、27/27结果、27/27证据、汇报成功，且没有排队或运行中的口碑 Worker。
- [x] SQLite在线备份、完整批次目录和释放前身份行位于服务器 `/var/lib/threadsnap/backups/reputation-today-recreate/20260826-175922/`；备份数据库完整性为 `ok`、SHA-256为 `35da1419452dab0985da982eb8a5fa92ce5834f759928c0719f1b3a486a655766`，27条结果、27条证据及29个文件均进入清单并通过校验。
- [x] 旧批次经正式删除作业 `01a03d82-a923-7f44-a90d-21353daaa845` 清除，作业状态为 `success`、文件分母29；随后在后端停止窗口精确释放唯一墓碑和 `deleted` 调度事件，旧详情接口返回404、旧批次数据库记录为0，删除作业审计记录继续保留。
- [x] 后端恢复后，真实 `ReputationCoordinator` 按原计划时刻 `2026-08-26 10:00 Asia/Shanghai` 创建唯一同日延迟批次 `01a03d83-78a0-7199-a119-8e58f3fe0d99`（`RP-S-20260826-0D99`）；`source_type=scheduled`、`run_type=daily`、`idempotency_key=reputation:2026-08-26:daily`、并发7，运行进度实测经过7/27、18/27和27/27。
- [x] 新批次终态为成功：27/27结果全部成功、失败0、27/27证据完成、TXT和XLSX均已生成且汇报状态成功；数据库完整性为 `ok`，今日正式事件唯一且状态为成功，新详情接口返回HTTP 200。
- [x] 停止后端时被联动停止的专用Nginx曾因10秒停止超时进入 `failed`，已重置并单独启动；最终 `threadsnap`、`threadsnap-nginx`、`threadsnap-wayland`、`threadsnap-cloudflared-quick` 全部为 `active`，后端、8088 Nginx、公网 `/health` 均为 `ok`，公网SPA返回HTTP 200，重启后后端日志未见 Traceback、Exception 或 Error。
**下一步**：无；服务器今日正式口碑巡检现以新批次为唯一当前结果。
**边界**：未创建合成测试运行，未修改程序、范围版本、平台配置或既有前日基线；旧批次内容只保留在独立审计备份中，新批次由正式调度链重新访问页面并形成独立证据。
**关联**：服务器备份 `/var/lib/threadsnap/backups/reputation-today-recreate/20260826-175922/`、删除作业 `01a03d82-a923-7f44-a90d-21353daaa845`、新批次 `01a03d83-78a0-7199-a119-8e58f3fe0d99`

---

## 2026-08-26 — 修复舆情关系校验错误的纠错请求序列化
**总目标**：让云端模型首次返回业务关系矛盾结果时，系统能够按既有上限正常构造并发送一次纠错请求，而不是被 Pydantic 异常上下文的 JSON 序列化再次打断。
**状态**：✅ 本地修复、目标服务器最小增量升级和内外网验证均已完成。
**干到哪里了**：
- [x] SSH 只读核对批次`20260826-160003-001`确认采集420/420成功、AI分析419项完成和1项失败；原始模型结果违反“非负面不得包含负面类型”的关系合同，随后在构造纠错请求时因`ValidationError.errors()`的`ctx.error`保留`ValueError`对象而触发`Object of type ValueError is not JSON serializable`。
- [x] 纠错详情提取显式使用`include_context=False`，保留错误类型、位置和中文消息，同时排除不可序列化的异常实例；既有一次纠错调用上限、候选哈希、原始输入和严格工具合同保持不变。
- [x] 回归测试使用真实`SentimentFeedback.model_validate()`构造“非负面但含负面类型”的`ValidationError`，证明纠错请求可生成、包含具体关系错误且不携带`ctx`异常对象；原有普通`ValueError`路径继续通过。
- [x] 专项测试1项、后端完整回归136项、Ruff、compileall、pip check和`git diff --check`通过。
- [x] 服务器从release`0.1.0-b599ad93203e`升级到`/opt/threadsnap/releases/0.1.0-8a7ede86679d`，`previous`保留旧release；新离线包SHA-256为`935b0b59ea088a5bfaf60bf0ed92d85713bcc60e7b331efdbb4b3709b829a643`，1004项内部校验通过。除ThreadSnap自身wheel外，138个依赖wheel、309个浏览器文件、485个RPM、12个模型文件及前端和部署文件均与旧包逐文件一致；两个应用wheel的唯一内容差异为`threadsnap/sentiment.py`。
- [x] 升级前SQLite在线备份位于`/var/lib/threadsnap/backups/sentiment-validation-serialization/20260826-173654/`，SHA-256为`5f7fb01e2da02f33c3538915cc2237a3b6a62560297e9e56bd44ec8483ba0839`且完整性为`ok`；升级后Alembic仍为`b7d2f4a6c803`、数据库完整性为`ok`，历史失败分析保持原状态且未重跑。
- [x] 服务器真实运行时重新构造同类`ValidationError`，纠错请求成功生成两条消息、保留`value_error`且不含`ctx`；完整`deploy/verify.sh`通过服务、Nginx、SPA、接口隔离、端口、Wayland Chromium、本地模型和凭证边界，四个服务均为`active`，公网临时隧道`/health`与SPA均返回HTTP 200。
**下一步**：无；未来同类模型关系违约会进入既有一次纠错调用，既有失败记录保持不可变。
**边界**：不放宽模型结果合同，不在本地改写矛盾结论，不增加第三次调用，不修改或自动重跑历史批次。
**关联**：`src/threadsnap/sentiment.py`、`tests/test_backend.py`、`docs/chains/sentiment-analysis.md`、远端分析`01a03d15-f1b9-7bc8-a011-5fee2340c148`

---

## 2026-08-26 — 未开售车型口碑暂无状态与补跑链当前结果修复
**总目标**：把页面确实尚无口碑数据的未开售车型显示为正常“页面暂无”，同时保留真正采集或解析失败的异常语义，并让补跑成功结果成为当前批次展示结果。
**状态**：✅ 本地采集、补跑链聚合、列表与详情展示、数据库和真实页面验证均已完成；SSH 远端未更新。
**干到哪里了**：
- [x] 真实检查风云T7评分页确认车型身份正确、仅有预售价且无正式售价，页面评分和评价数均为0，五项展示指标缺失，负面评价接口正负样本均为0；原始页面测量与截图位于`artifacts/runtime/reputation-presale-no-data/`。
- [x] 懂车帝口碑适配器升级为`dongchedi-reputation-v8-presale-not-available`：仅在页面五项均缺失、页面状态明确评分/评价数为0、启用负面率时接口计数也为0三组信号一致时返回`not_available`；已有任一指标或信号冲突仍按评价篇数缺失异常处理。
- [x] 定时根批次详情按车型和平台从原批次及补跑链选择当前最佳结果，成功补跑可以替换当前展示中的旧失败行，但原批次状态及失败补跑继续保留为不可变审计记录；列表和详情分别展示当前链状态与原批次状态。
- [x] 本地对`RP-S-20260826-C8A8`执行一次精确补跑，新批次`RP-R-20260826-082906-B6BB`成功；当前链为成功、27/27完整、27/27证据，风云T7五项均显示“页面暂无”、状态成功且证据可查看，页面与控制台错误均为0。
- [x] 后端完整回归136项、Ruff、compileall、pip check、前端TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；修复后数据库备份完整性为`ok`，审计摘要位于`artifacts/runtime/reputation-presale-no-data/20260826-162826/final-verification.json`。
**下一步**：远端服务器代码与数据维持原状，待用户明确要求更新时再部署并补跑对应远端批次。
**边界**：不把普通字段缺失一律降级为“页面暂无”；原始批次和历史补跑不覆盖、不删除；本次未连接或修改SSH服务器。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`src/threadsnap/reputation.py`、`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/adr/0039-use-score-page-review-article-count.md`

---

## 2026-08-26 — 补齐 AI 配置逐字段未保存提示
**总目标**：让后加入的“AI 舆情”受控配置复用每周计划等页面的未保存视觉合同，明确定位发生变化的配置卡片和具体字段。
**状态**：✅ 字段级标识、卡片与标签汇总、恢复基线和离页保护均已完成真实页面验证。
**干到哪里了**：
- [x] 模型、云端并发、Base URL、API Key、品牌、重点产品和补充说明分别与最近一次服务端响应比较；实际变化的输入控件显示琥珀色边框与焦点环。
- [x] “模型连接”和“舆情判定对象”卡片分别汇总本卡修改数，页面工具栏和保存按钮展示全页待保存字段总数，既有标签圆点与离页保护继续复用同一 dirty 状态。
- [x] 重点产品仍按保存时的逐行规范化结果比较，只有尾部换行或临时空行时不误报未保存；字段恢复服务端基线后对应提示立即清除。
- [x] 前端 TypeScript 检查、Vite 生产构建（2468 modules）和 `git diff --check` 通过；真实页面逐项验证7类字段、双卡片计数、标签圆点、保存按钮计数、恢复原值、放弃修改和站内离页确认，控制台与页面错误均为0，材料位于`artifacts/runtime/config-dirty-indicators/20260826-155136/`。
**下一步**：无。
**边界**：不改变 AI 配置接口、保存规范化、模型验证状态、凭证处理或提取批次开关语义；即时提交的历史与模板操作仍不引入表单 dirty 状态。
**关联**：`frontend/src/features/config/config-page.tsx`、`docs/design/technical-route.md`

---

## 2026-08-26 — 修复口碑负数差值导致详情页崩溃
**总目标**：修复旧指标清理迁移对口碑指标字符串叶子的错误类型转换，并让历史批次和未来批次都保持稳定的指标文本合同。
**状态**：✅ 代码、修复迁移、本地与目标服务器既有数据及真实页面均已完成，进入自动Git收尾。
**干到哪里了**：
- [x] 对比全部3个本地批次后确认：8月24日无基线差值，8月25日90个差值均为字符串，8月26日的瑞虎8和吉利银河M9口碑量差值 `"-1"` 被转成整数 `-1`，触发前端对数字调用 `.replace()`。
- [x] 根因定位为 `a6c9e2f4b701` 在递归清除旧键时对每个字符串叶子再次执行 `json.loads()`；`"-1"` 会变成整数而 `"+1"` 保持字符串，因此只在负数变化项暴露。
- [x] 原迁移改为只在数据库JSON容器边界解码；新增 `b7d2f4a6c803` 修复既有结果和冻结基线的 `raw/value/baseline_raw/baseline_value/delta` 文本类型，前端同时把运行时差值显式转成字符串后展示。
- [x] 使用迁移前数据库分别验证从 `d8f4a2b6c901` 经过修正原迁移到新head、以及从已受影响的 `a6c9e2f4b701` 执行修复迁移，两条路径均为head `b7d2f4a6c803`、错误类型0、旧键0、数据库完整性 `ok`。
- [x] 本地业务库升级后又从升级前在线备份精确恢复10个结果字段和6个冻结基线字段的原始文本精度；当前数据库完整性为 `ok`。
- [x] 后端完整回归134项、Ruff、compileall、pip check、前端TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；新增测试明确证明新批次负数差值仍保存为字符串 `"-1"`。
- [x] 本地真实详情页HTTP 200，批次与瑞虎8正常显示，错误边界、页面异常和控制台错误均为0；验证截图位于`artifacts/runtime/reputation-metric-text-fix/local-fixed-page.png`。
- [x] 目标服务器升级到release `/opt/threadsnap/releases/0.1.0-5e13e5f12f5c`，Alembic为`b7d2f4a6c803`；从原升级前备份精确恢复6个结果字段和2个冻结基线字段，54条结果的指标文本错误类型为0，数据库完整性为`ok`，新生成负数差值类型为字符串。
- [x] 服务器升级前数据库备份位于`/var/lib/threadsnap/backups/reputation-metric-text/20260826-153823/`且SHA-256校验通过；四个服务均为`active`，公网`/health`与详情页HTTP 200，批次`RP-S-20260826-C3A9`无错误边界、页面异常或控制台错误，瑞虎8和吉利银河M9均返回字符串差值`"-1"`。
**下一步**：无。
**边界**：不改变指标数值、比较方向、历史批次身份、证据或新指标口径；计数型 `positive_count/negative_count` 继续保持整数。
**关联**：`src/threadsnap/migrations/versions/a6c9e2f4b701_review_article_count.py`、`src/threadsnap/migrations/versions/b7d2f4a6c803_normalize_reputation_metric_text.py`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/memories/json-migration-container-boundary.md`、`artifacts/runtime/reputation-metric-text-fix/`

---

## 2026-08-26 — 口碑第四指标改为评价篇数并清除旧数据
**总目标**：把口碑详情中的第四数量指标替换为评分页“全部评分”的口碑评价篇数，并彻底清除原车型圈子帖子总量的采集代码、业务数据和派生产物。
**状态**：✅ 采集、比较、前端、汇报、XLSX、迁移及本地与目标服务器既有数据均已切换完成。
**干到哪里了**：
- [x] 已确认评分页服务端状态 `props.pageProps.reviewListData.total_count` 对应“全部评分·共N篇”；保存的真实哈弗大狗页面解析为评价篇数2092、评价人数2047，证明两者是独立指标。
- [x] 真实适配器升级为 `dongchedi-reputation-v7-review-article-count`：评价篇数在同一评分页三次稳定测量中读取并保存评分页来源URL；删除车型圈子页请求、路径身份校验、错误码和相关字段，不再增加额外HTTP请求。
- [x] 后端指标键、前日比较、合成场景、正文汇报、固定XLSX及前端表格统一为 `review_article_count` / “口碑评价篇数”；首个新批次没有历史基线，后续按前日冻结值比较。
- [x] Alembic `a6c9e2f4b701` 递归清除81条既有结果和2份有效基线中的旧键，删除旧TXT、XLSX后按新模板重建3个历史终态批次；当前库旧结果键0、旧基线键0，3份XLSX的H列表头均为“口碑评价篇数”，数据库完整性为`ok`。
- [x] 升级前SQLite在线备份和口碑文件备份位于`artifacts/runtime/review-article-count-20260826/20260826-145506-before-cleanup/`，数据库SHA-256为`68437c4d2824fd93b7e4acc66e4e58d48bf8f5188205c117f5898921e97e8c15`。
- [x] 后端完整回归131项、Ruff、compileall、pip check、前端TypeScript检查、生产构建（2468 modules）和`git diff --check`通过。
- [x] 干净提交`9b2beb8ab11baf7e70bb8bcbf652168d10230948`已部署为服务器release `/opt/threadsnap/releases/0.1.0-9b2beb8ab11b`；服务器54条结果和1份有效基线旧键均为0，两份历史终态TXT、XLSX已按新模板重建，H列表头均为“口碑评价篇数”，数据库完整性为`ok`。
- [x] 服务器升级前在线备份数据库及141个口碑文件，数据库SHA-256为`e2008bbfc448bfcae62d83355aebb0f4fc1c5f31ef31ee48304bd97a6647ac67`，审计与回滚材料位于`/var/lib/threadsnap/backups/review-article-count/20260826-150822/`；离线包SHA-256为`b2f1633e0f412082bac98078c62c350b1f44bc25e08601abf91dbfc9cb8f96c5`。
- [x] 服务器`threadsnap`、`threadsnap-nginx`、`threadsnap-wayland`、`threadsnap-cloudflared-quick`均为`active`；本机后端、Nginx及公网Quick Tunnel `/health`均为`ok`，公网SPA返回HTTP 200。
**下一步**：无。
**边界**：旧值与新指标业务语义不同，不迁移、不回填、不作为首个新批次基线；论坛帖子提取模块的圈子配置、任务和页面证据保持不变。
**关联**：`docs/adr/0039-use-score-page-review-article-count.md`、`src/threadsnap/reputation_dongchedi.py`、`src/threadsnap/migrations/versions/a6c9e2f4b701_review_article_count.py`、`artifacts/runtime/review-article-count-20260826/`

---

## 2026-08-26 — 口碑内部车型身份平台中立化迁移
**总目标**：把既有27款口碑车型从绑定懂车帝平台ID的 `dcd-*` 内部身份迁移为平台中立的 `rep-*` 身份，并保持验证、历史批次、前日基线和证据链完整。
**状态**：✅ 本地与目标服务器的当前草稿、已发布版本、历史验证、真实批次、证据路径和已生成证据包均已完成迁移并恢复服务。
**干到哪里了**：
- [x] 迁移前使用SQLite在线备份并复制全部172个口碑文件；备份数据库 `PRAGMA integrity_check=ok`，SHA-256为 `0f8eee6284d20edd4e9bfae63da8e4ed5feb3be6b829f6ff847d2b3539a29372`，27项旧新ID映射、原始初始化清单的更正版及回滚材料位于 `artifacts/runtime/reputation-internal-id-normalization/20260826-133710/`。
- [x] 精确迁移1份当前草稿、1份已发布范围、102条映射验证、81条巡检结果、批次目标键和前日基线；重算验证映射哈希及6次验证运行输入哈希，数据库所有表行数保持不变，口碑表中27个旧ID残留为0。
- [x] 164个证据目录全部改为新ID；137个数据库引用文件均存在且SHA-256一致，另外27张未引用历史图只改目录身份而未删除；两个既有证据ZIP重建后CRC通过且不含旧ID，下载SHA-256分别为 `5c4ba49439979ec512b4490a262566e3a1123f5566e5ce58a9d191998ca7e463` 和 `157b468e11f00f1883c5098f8337cf899acf99bf3bafc8be52fa7820572ccf7d`。
- [x] 真实后端和前端代理 `/health` 均为 `ok`；范围API返回修订17、27/27个 `rep-*` 唯一身份、0个 `dcd-*` 车型身份、27/27映射已验证且平台车型ID保持不变；三个批次详情均保持成功、27/27结果和27/27证据。
- [x] 目标服务器按最小数据变更执行：不升级程序、不调整配置，只停后端约5秒并迁移27个旧身份、135个证据目录、1份已生成证据包及其数据库关联；保留6个既有 `rep-*` 新增车型。范围修订由9变为10，最终33/33身份均为唯一 `rep-*`，55条验证尝试、54条结果、54条证据及所有表行数保持不变，109个数据库引用文件存在且哈希一致，旧身份表行和目录均为0，数据库完整性与证据包CRC通过。
- [x] 服务器迁移前数据库在线备份SHA-256为 `ad4191caf559d1ee33a6692deb71909c8935a087c54f044bced22d1f9cf4648a5`，完整口碑文件备份141个，审计与回滚材料位于 `/var/lib/threadsnap/backups/reputation-id-normalization/20260826-141911/`。迁移后 `threadsnap`、`threadsnap-wayland`、`threadsnap-nginx`、`threadsnap-cloudflared-quick` 均为 `active`，本机后端、Nginx与公网Quick Tunnel健康检查均为 `ok`；公网范围API连续返回修订10、33个 `rep-*`、0个 `dcd-*`。
**下一步**：无。
**边界**：原始业务输入CSV和迁移前证据包只在审计备份中保留，不改写其他模块的懂车帝帖子、评论或截图身份；以后初始化键和新增车型ID必须平台中立。
**关联**：`CONTEXT.md`、`docs/design/product-design.md`、`artifacts/runtime/reputation-internal-id-normalization/20260826-133710/`、服务器审计目录 `/var/lib/threadsnap/backups/reputation-id-normalization/20260826-141911/`

---

## 2026-08-26 — 修复配置页多行编辑与模板列表扩张
**总目标**：让“AI 舆情”的重点产品按正常多行文本方式编辑，并让“可用模板”卡片在桌面双栏中服从左侧上传卡片高度，避免模板增多时持续撑高页面。
**状态**：✅ 前端修复、类型检查、生产构建和差异检查均已完成。
**干到哪里了**：
- [x] 重点产品输入框改为独立保存编辑期原始文本，回车产生的尾部换行和临时空行不再被每次输入时立即删除。
- [x] 脏状态比较和保存请求仍按行去除首尾空白、忽略空行；保存成功或放弃修改后，输入框与服务端规范化列表重新同步。
- [x] 桌面双栏高度改由左侧上传卡片的自然内容决定，右侧“可用模板”卡片等高跟随；标题区保持固定，模板列表只在卡片内容区纵向滚动，不再使用偏高的固定值或随模板数量扩张。
- [x] 前端 TypeScript 检查通过，Vite 生产构建成功（2468 modules），`git diff --check` 通过。
**下一步**：无。
**边界**：不改变后端重点产品列表合同、保存时规范化规则、去重规则、AI 判定行为或模板上传、下载、隐藏行为。
**关联**：`frontend/src/features/config/config-page.tsx`

---

## 2026-08-26 — 按批次控制 AI 分析与圈子页面截图
**总目标**：修复圈子原始截图顶部文字冲突，并把 AI 分析与圈子页面截图从全局/强制行为改为自动提取规则和手动批次的显式选项。
**状态**：✅ 规则版本、手动提交、定时合并、Worker、截图渲染、迁移和真实页面均已完成验证。
**干到哪里了**：
- [x] 自动提取规则新增“AI 舆情分析”和“圈子页面截图”两个版本化开关；手动圈子发现新增同名开关，URL 清单保留 AI 开关且截图明确不可用。多规则命中同一来源时数量取最大值，两个开关分别按任一贡献规则开启即开启，并冻结到批次与圈子任务快照。
- [x] “AI 舆情”配置页移除全局业务开关，只保留模型、连接、并发、判定对象和连接测试。批次关闭 AI 时帖子进入 `analysis_disabled`；批次要求 AI 但模型未验证或失效时进入可恢复的 `analysis_paused`，测试成功后恢复。
- [x] 截图关闭的任务不注册页面证据、不传捕获回调、不关联卡片或生成成果；截图开启而 AI 关闭时不等待模型，直接生成无红框成果。零负面页面直接复制原始 PNG，专项测试证明成果与原图字节一致。
- [x] 圈子捕获取消隐藏滚动条、禁用动画/过渡等注入 CSS，只回到平台原始页首并等待布局稳定。生产模式真实捕获风云 A9 首页得到30张卡片、`1425 × 11126`文档和 SHA-256 `73bcc8122d69130fd65cab7b4f548df7b9c0ed2e388c653e8924f1ce6d578e3b`，顶部导航、面包屑和圈子标题无文字冲突；证据位于`artifacts/runtime/extraction-output-switches-20260826-102834/`。
- [x] SQLite 在线备份后升级到 Alembic `d8f4a2b6c901`，既有8个规则版本两个开关均按兼容默认值开启，升级前备份完整性`ok`且 SHA-256 为`3fd466dfdfe3d50c9ff22a92e37ae47844c14f36e32d29581ab3abcf596de0f4`。完整后端回归131项、截图专项9项、Ruff、compileall、pip check、前端TypeScript检查、生产构建和`git diff --check`均通过。
- [x] 真实前端验证规则页两个开关均可见且默认开启，手动 Sheet 两个开关可见，URL 清单截图开关禁用，AI 配置页无全局开关；浏览器控制台和页面错误均为0。后端`127.0.0.1:8000/health`与前端`127.0.0.1:5173/`均返回200。
**下一步**：无。
**边界**：既有规则迁移后保持原行为；开关只影响新建批次，历史批次、原始证据和历史成果不追溯改写。截图关闭不补拍；AI 关闭但截图开启时不推断舆情，后续人工有效结论仍可生成新成果版本。
**关联**：`docs/adr/0038-freeze-ai-and-screenshot-options-per-batch.md`、`src/threadsnap/migrations/versions/d8f4a2b6c901_extraction_output_switches.py`、`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/screenshots.py`、`src/threadsnap/sentiment.py`、`src/threadsnap/services.py`、`src/threadsnap/worker.py`、`frontend/src/features/config/config-page.tsx`、`frontend/src/features/runs/new-extraction-sheet.tsx`、`artifacts/runtime/extraction-output-switches-20260826-102834/`

---

## 2026-08-25 — 口碑巡检时间调整为每日10:00
**总目标**：把固定的每日正式口碑巡检计划点从北京时间12:00调整为10:00，同时保持终态立即汇报、时间只读和历史批次不可变。
**状态**：✅ 后端调度、前端展示、测试和当前设计口径均已切换为每日10:00，真实服务已加载生效。
**干到哪里了**：
- [x] 后端唯一计划常量改为`10:00:00`，调度查建、计划时点范围冻结、同日补触发和月末替代日检均沿用该计划点；正式创建事件文案同步为10:00，汇报仍在批次终态后立即生成，不增加独立汇报时点或用户配置。
- [x] 前端只读摘要从调度API展示“每日 10:00 正式巡检”，无API数据时的兜底也改为10:00；`CONTEXT.md`、产品设计、技术路线和口碑链档的当前口径已同步，链档保留此前12:00决策并追加本次变更记录。
- [x] 口碑调度生命周期测试在09:59验证未到期、10:00验证创建、10:01验证幂等和终态汇报；`python -m unittest tests.test_reputation`通过18项，`ruff check src tests`、前端`npm run check`、生产构建（2468 modules）和`git diff --check`通过。
- [x] 重启真实后端后，`/api/v1/reputation/schedule`返回`inspection_time=10:00:00`且`report_time=null`；真实页面显示10:00、控制台和页面错误均为0，数据库`PRAGMA integrity_check=ok`，材料位于`artifacts/runtime/reputation-schedule-10am/20260825-213651/`。
- [x] 重启前后2026-08-25正式根批次和调度事件均保持1条；既有`RP-S-20260825-DAF2`仍保留其历史计划时刻12:00，未因新时间重复创建或追溯改写。后端与前端代理健康检查均为`ok`。
**下一步**：下一自然日由真实协调器在北京时间10:00创建正式巡检批次。
**边界**：时间仍为产品固定只读值，不进入帖子提取计划或新增编辑入口；新计划点只影响未来计划事件，历史批次和证据保持不变。
**关联**：`src/threadsnap/reputation.py`、`frontend/src/features/reputation/reputation-page.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`、`artifacts/runtime/reputation-schedule-10am/20260825-213651/`

---

## 2026-08-25 — 再次清除并由真实定时流程重跑今日巡检
**总目标**：清除今日正式批次`RP-S-20260825-82C4`，完整释放同日调度身份，再由真实定时协调器创建并跑完新的今日批次。
**状态**：✅ 旧批次已清除，新批次由真实定时流程补触发并以27/27成功终态完成。
**干到哪里了**：
- [x] 删除前使用SQLite在线备份数据库并复制旧批次全部30个交付文件；备份数据库`PRAGMA integrity_check=ok`，SHA-256为`79a2efb52defc128f7906fe974b1dafa80c0e4c1e686b8ad5d93a4fc7a954795`，材料位于`artifacts/runtime/reputation-scheduled-recreate/20260825-212222/`。
- [x] 旧批次`01a038f6-d55e-7867-8831-bb898a2182c4`经正式删除链完成，删除作业`01a03916-33db-7e7f-ad28-0be7ff4ee868`状态为`success`；随后在后端停止窗口精确释放该批次墓碑及残留的`deleted`调度事件，旧详情接口返回404、旧数据库记录为0。
- [x] 后端恢复后，`ReputationCoordinator`按原计划时间`2026-08-25 12:00 Asia/Shanghai`自动创建唯一正式根批次`01a03918-2120-7993-873d-4afe20aedaf2`（`RP-S-20260825-DAF2`）；`source_type=scheduled`、`run_type=daily`、`idempotency_key=reputation:2026-08-25:daily`并标记同日补触发，冻结基线仍为`01a0346a-b2e6-7296-8aaf-dbc7d52010f4`。
- [x] API先观察到`4/27`，真实页面截得`8/27`和8条已提交结果，后续日志记录`12、13、14、15、16、17、18、19、20、21、22、23、25、26、27`，证明进度按执行项持续提交而非终态统一生成；证据为同一审计目录下`new-run-intermediate-4-of-27.json`、`new-run-progress.png`和`progress.json`。
- [x] 新批次27款全部成功，五项指标字段27/27（差评率26项有值、1项按零评价保存`not_available`）、页面证据27/27、汇报状态`success`；XLSX为表头加27行，证据ZIP含27张PNG和`manifest.json`且CRC检查通过，数据库完整性为`ok`。
- [x] 真实前端列表仅显示新编号并展示成功、`27/27`和证据`27/27`，详情展示差评率和完整终态；后端`127.0.0.1:8000/health`与前端代理`127.0.0.1:5173/health`均为`ok`，截图为同一审计目录下`new-run-list-final.png`和`new-run-detail-final.png`。
**下一步**：无。
**边界**：当前数据库只保留一个2026-08-25正式根批次和一条关联成功调度事件；旧批次删除作业与离线备份保留用于审计，基线批次保持不变。
**关联**：`WORKLOG.md`、新批次`01a03918-2120-7993-873d-4afe20aedaf2`、删除作业`01a03916-33db-7e7f-ad28-0be7ff4ee868`、`artifacts/runtime/reputation-scheduled-recreate/20260825-212222/`

---

## 2026-08-25 — 口碑巡检逐车型实时进度
**总目标**：把正式口碑巡检从整批结束后统一写入改为车型平台执行项终态后逐项持久化，让列表和详情在运行中显示真实进度与已完成结果。
**状态**：✅ 逐项事务、重试终态计数、SSE摘要、页面增量展示和终态冻结边界均已完成。
**干到哪里了**：
- [x] 真实适配器增加完成回调但继续按冻结输入顺序返回最终列表；每个成功、部分成功或无需再重试的失败项单独事务写入指标、证据和聚合计数，事务提交后发布带成功数、失败数和证据数的`reputation.run.changed`。首轮暂时错误保持未完成，只在第二次尝试终态后计数；整批终态事务不再删除并重写全部结果。
- [x] 前端事件桥新增`reputation.run.changed`和`reputation.scope.changed`监听，精确失效口碑列表、对应详情或范围缓存，并保留三秒活动态轮询兜底；无新增用户配置，运行中详情会按冻结范围顺序逐步出现已提交行和证据，批次状态仍为`running`，汇报仍只读取全部执行项终态后的冻结输入。
- [x] 新增27车型权威进度测试，逐次读取数据库得到严格`1..27`序列并核对逐项事件；另覆盖首轮可重试错误不提前增加失败数、第二次成功记录`attempt_count=2`，以及HTTP优先兼容路径每目标只回调一次。完整`unittest discover`通过129项，`ruff check src tests`、前端TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；全仓Ruff仍报告`poc/`下6个既有导入排序问题，本次未改这些PoC文件。
- [x] 使用生产数据库在线副本和真实平台适配器建立隔离日检`RP-S-20260826-3965`，API与真实页面在运行中观察到`10、12、14、16、18、20、22、24、26、27`，每次结果行数与完成分子一致；截图`running-progress.png`明确显示运行中`10/27`及10条已提交结果。隔离浏览器按无头模式触发平台已知零字节/超时边界，27项最终均失败，但仍完整证明成功与失败共用逐项进度合同；隔离数据库`PRAGMA integrity_check=ok`，材料位于`artifacts/runtime/reputation-linear-progress/20260825-210130/`。
- [x] 生产数据库未修改；隔离后端和前端已停止，现有后端`127.0.0.1:8000/health`与前端代理`127.0.0.1:5173/health`均为`ok`。
**下一步**：无；下一次真实正式巡检会直接按新合同展示运行中增量进度。
**边界**：进度分子定义为已提交终态执行项，不是已启动浏览器任务数；并发完成和三秒前端回查可能让视觉数字一次跳过一至数项，但数据库与事件仍逐项提交。运行恢复沿用同一批次身份重新执行未冻结批次，最终汇报与文件保持整批终态后生成。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/reputation_dongchedi.py`、`frontend/src/components/event-bridge.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`、`artifacts/runtime/reputation-linear-progress/20260825-210130/`

---

## 2026-08-25 — 删除并由真实定时流程重建今日巡检
**总目标**：删除旧今日批次`RP-S-20260825-5AF9`，释放同日调度身份后由正式协调器重新创建并执行今日12:00巡检。
**状态**：✅ 旧批次已删除，新批次由真实调度同日补触发并以27/27成功终态完成。
**干到哪里了**：
- [x] 删除前使用SQLite在线备份数据库并复制旧批次2个交付文件；备份数据库`PRAGMA integrity_check=ok`，SHA-256为`51e8630f5c10dde20ee6245165e6fea3da1d958ce9b2f25b9002686452a7adc7`，材料位于`artifacts/runtime/reputation-scheduled-recreate/20260825-204646/`。
- [x] 旧批次`01a03713-4599-7da1-940e-b8416ef25af9`经正式删除链完成，删除作业`01a038f5-987d-7d71-8ec5-03d2e124cb62`状态为`success`，旧详情接口与数据库记录均已消失。
- [x] 在后端停止期间精确移除2026-08-25日检墓碑和旧调度事件；后端恢复后，`ReputationCoordinator`按原计划时间`2026-08-25 12:00 Asia/Shanghai`自动创建唯一正式根批次`01a038f6-d55e-7867-8831-bb898a2182c4`（`RP-S-20260825-82C4`），`source_type=scheduled`、`schedule_type=daily`、`idempotency_key=reputation:2026-08-25:daily`并标记同日补触发。
- [x] 新批次冻结现有完整基线`01a0346a-b2e6-7296-8aaf-dbc7d52010f4`，真实采集27款全部成功；五项指标27/27、页面证据27/27、汇报状态`success`，XLSX含27行五指标列，证据ZIP含27张区域PNG且清单全部`complete`，数据库完整性为`ok`。
- [x] 真实前端列表确认旧编号0处、新编号1处并展示“正式调度·同日补触发”；详情确认27行、差评率表头1处、无“历史未采集”、控制台与页面错误均为0，截图为同一审计目录下`new-run-list.png`和`new-run-detail.png`。
- [x] 后端`127.0.0.1:8000/health`与前端代理`127.0.0.1:5173/health`均恢复为`ok`。
**下一步**：无。
**边界**：当前数据库只保留一个2026-08-25正式根批次；旧批次删除作业记录与离线备份保留用于审计，现有完整基线批次保持不变。
**关联**：`WORKLOG.md`、新批次`01a038f6-d55e-7867-8831-bb898a2182c4`、删除作业`01a038f5-987d-7d71-8ec5-03d2e124cb62`、`artifacts/runtime/reputation-scheduled-recreate/20260825-204646/`

---

## 2026-08-25 — 直接刷新现有基线初始化数据
**总目标**：按用户明确指令直接更新当前真实验收基线批次，使原27款车型基线结果全面包含现行五项指标和同期页面证据。
**状态**：✅ 原基线ID、结果ID和计划日期保持不变，数据库、TXT、XLSX与证据ZIP已同步刷新并完成真实页面验收。
**干到哪里了**：
- [x] 目标批次仍为`01a0346a-b2e6-7296-8aaf-dbc7d52010f4`（`RP-A-20260824-153642-10F4`）；直接写回原27条结果，结果ID全部保留，并补写当前发布范围版本`01a03455-be81-7f9d-b16b-46e46bd750d4`。
- [x] 2026-08-25 19:53:05至19:55:01按当前适配器重新采集口碑分、排名、口碑量、圈子内容量和差评率；首轮26项成功，风云A9L因一次页面CSP竞争单项重采成功，最终27/27成功、五项字段27/27、页面证据27/27。风云T7差评率由接口明确零评价保存为`not_available`，零跑A10为`37%`（好评214、差评128）。
- [x] 写库前使用SQLite在线备份并复制原基线全部30个产物文件；备份数据库`PRAGMA integrity_check=ok`，SHA-256为`8e3fb5105007bcc6e8a2540583fb6348535fd7ffaa22e0b632dbefe860f58bb0`，回滚材料位于`artifacts/runtime/reputation-baseline-direct-refresh/20260825-195219/`。
- [x] 写库后数据库完整性为`ok`，原27个结果ID逐项一致；XLSX含27行和五指标列，证据ZIP含27张区域PNG且清单全部`complete`。真实前端确认27行均无“历史未采集”、基线不显示前日涨跌、控制台与页面错误均为0，截图为同一审计目录下`baseline-after-refresh.png`。
- [x] 后端`127.0.0.1:8000/health`与前端代理`127.0.0.1:5173/health`均返回`ok`。
**下一步**：无。
**边界**：这是用户指定的一次性历史数据库直改；批次计划日期仍为2026-08-24，但各结果明确保留本次实际采集时间。2026-08-25已完成日检的冻结基线快照、比较结果和汇报未被追溯重算。
**关联**：`WORKLOG.md`、基线批次`01a0346a-b2e6-7296-8aaf-dbc7d52010f4`、`artifacts/runtime/reputation-baseline-direct-refresh/20260825-195219/`

---

## 2026-08-25 — 口碑巡检默认增加差评率指标
**总目标**：复用现有懂车帝车型ID取得APP口碑标签中的差评率，并将其作为无需用户配置的默认巡检内容进入前日比较、详情、汇报和XLSX。
**状态**：✅ APP接口采集、第五指标冻结、反向红绿比较、历史兼容、页面与导出均已完成。
**干到哪里了**：
- [x] 懂车帝适配器升级为`dongchedi-reputation-v6-negative-rate`；使用现有`platform_vehicle_id`作为APP接口`series_id`，按稳定标签身份读取好评数和差评数，以`差评数/(好评数+差评数)`四舍五入为整数百分比，并校验返回车系身份。只使用固定APP客户端参数和请求头，不增加用户配置、Cookie、令牌或设备指纹。
- [x] 差评率作为第五个独立反向指标持久化并进入严格前日基线：下降为改善绿色、上升为恶化红色、持平中性；汇报、详情表格和固定版式XLSX同步增加该字段。旧批次保持不可变并显示“历史未采集”，评价总数为0时保存`not_available`语义。
- [x] 对当前已发布范围版本`01a03455-be81-7f9d-b16b-46e46bd750d4`的27款车型逐项实测：26款有值，风云T7评价总数为0因而暂无比例，接口失败0项；零跑A10复核为`128/(214+128)=37%`。脱敏明细位于`artifacts/runtime/reputation-negative-rate/live-27-api-audit.json`。
- [x] 隔离实例真实触发两个批次，SQLite中各27/27条结果均包含差评率对象且首批API与数据库JSON一致；真实页面确认表头1处、下降绿色、上升红色、控制台与页面错误均为0，XLSX第I列为“差评率”且首行值与API一致。证据位于`artifacts/runtime/reputation-negative-rate/isolated-20260825-verify/`。
- [x] 完整127项后端测试、Ruff全仓检查、前端TypeScript检查、生产构建（2468 modules）和`git diff --check`通过。
**下一步**：无；下一次正式巡检开始冻结差评率，第二个连续自然日开始显示有效红绿差值。
**边界**：现有口碑指标区域PNG继续只证明网页可见的口碑分、排名和口碑量；差评率以APP接口来源URL及好评/差评计数追溯，不改写历史截图、历史结果或既有车型ID映射。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`src/threadsnap/reputation.py`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`frontend/src/lib/types.ts`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 口碑巡检新增圈子内容量指标
**总目标**：使用口碑平台车型ID对应的圈子URL取得内容总量，并将其作为独立指标进入巡检表格、前日比较、汇报和XLSX。
**状态**：✅ 轻量采集、身份校验、红绿比较、历史兼容、页面与导出均已完成。
**干到哪里了**：
- [x] 懂车帝适配器升级为`dongchedi-reputation-v5-circle-content`；正式执行项使用共享Session请求`/community/{platform_vehicle_id}`，校验最终圈子路径ID后解析“共N条内容”，请求占用既有执行项并发槽且不打开额外浏览器标签页。
- [x] 圈子内容量作为第四个独立正向指标持久化，进入严格前日基线、差值方向、汇报和固定版式XLSX；上升浅绿、下降浅红、持平中性。旧批次保持不可变，详情新列显示“历史未采集”，首个新批次不回填历史值。
- [x] 真实共享Session核验风云A9L平台车型ID`8985`对应`https://www.dongchedi.com/community/8985`，2026-08-25 17:27取得圈子内容量`7457`，脱敏结果位于`artifacts/runtime/reputation-circle-content/live-circle-result.json`。
- [x] `python -m unittest tests.test_reputation`通过14项，Ruff、前端TypeScript检查、生产构建和`git diff --check`通过；真实历史批次页面确认新表头1处、27行均为“历史未采集”、控制台错误0，截图位于`artifacts/runtime/reputation-circle-content/ranking-history.png`。
**下一步**：无；下一次正式巡检开始写入圈子内容量，第二个连续自然日开始显示有效红绿差值。
**边界**：圈子内容量与口碑评价人数不合并；现有口碑指标区域PNG仍证明口碑分、排名和口碑量，圈子统计保存经身份校验的来源URL，不改写历史截图或历史结果。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`src/threadsnap/reputation.py`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 下移口碑证据截图顶部边界
**总目标**：移除指标区域截图顶部误带入的平台装饰横条，同时完整保留车型身份和三项指标。
**状态**：✅ 截图矩形、定向回归和单车型真实平台验收已完成。
**干到哪里了**：
- [x] 指标矩形顶部安全边距由20px收紧为4px、底部由20px扩展为36px，截图窗口整体下移16px且保持原高度；左右仍为20px。
- [x] 车型标题、口碑分、排名、口碑量四个稳定DOM框仍共同决定截图并集，三次稳定测量、越界校验和单张PNG合同不变。
- [x] 适配器版本升级为`dongchedi-reputation-v4-trimmed-region`，历史证据保持不可变，新验证与新巡检使用新边界。
- [x] 定向矩形测试和Ruff通过；真实重验`01a03821-dcf7-76a1-b5ad-60ca97621f92`成功生成`1282×378`风云A9区域图，顶部装饰横条已消失、车型标题与三项指标完整、底部同步下移，SHA-256为`F6D220641D448CFA9EA186D187296E408BC9E13045138BB8181CD2EB8C066B11`，证据位于`artifacts/runtime/reputation-evidence-top-boundary/fengyun-a9-region.png`。
**下一步**：无。
**边界**：不裁改历史PNG，不修改证据查看器、指标解析、截图分母或下载链路。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`tests/test_reputation.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 证据查看器接入应用主题语义色
**总目标**：消除固定黑色查看器与系统外壳的割裂，同时让浅色、深色和跟随系统主题都使用同一套语义色合同。
**状态**：✅ 主题令牌改造及浅色、深色真实页面验收已完成。
**干到哪里了**：
- [x] Dialog容器、标题区、图片舞台、侧栏、指标卡、文字和边框全部改用`background/card/muted/border/foreground`主题令牌。
- [x] 浅色主题下标题区与侧栏为白色、图片舞台为浅蓝灰；深色主题自动使用既有深色令牌，不硬编码白色或黑色。
- [x] 品牌色仅使用`primary`表达证据图标、眉题、悬停和键盘焦点，成功证据继续使用带深色适配的语义绿色。
- [x] TypeScript检查和生产构建（2468 modules）通过；Patchright分别切换浅色与深色主题，确认Dialog表面、文字、边框和语义色同步变化，两处入口图片加载和当前标签页行为正常且控制台错误0；浅色预览为`ranking-evidence-dialog.png`，深色预览为`evidence-card-dialog.png`。
**下一步**：无。
**边界**：不修改Dialog布局、证据内容、查看入口、采集或下载逻辑。
**关联**：`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 证据查看器改为中性石墨灰配色
**总目标**：降低证据Dialog大面积深蓝带来的压迫和单色感，让截图成为视觉主体并与系统浅色外壳自然衔接。
**状态**：✅ 石墨灰分层、局部品牌蓝和真实页面预览验收已完成。
**干到哪里了**：
- [x] 标题区、图片舞台和信息侧栏由同色深蓝调整为三个明度层级的中性石墨灰。
- [x] 品牌蓝缩减到证据图标、眉题和键盘焦点；成功状态继续使用语义绿色，未增加装饰性色。
- [x] 图片舞台网格和光晕改为无彩色白灰，侧栏指标卡使用独立灰阶表面，保持原布局和信息合同。
- [x] TypeScript检查和生产构建（2468 modules）通过；Patchright确认两处入口图片加载、当前标签页行为和历史标签均正常，石墨灰三层表面对比清晰且控制台错误0，预览位于`artifacts/runtime/reputation-all-screenshots-dialog/ranking-evidence-dialog.png`。
**下一步**：无。
**边界**：不修改Dialog尺寸、证据内容、查看入口、采集或下载逻辑。
**关联**：`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 重构口碑证据查看器视觉层级
**总目标**：修正截图Dialog固定全屏高度导致的大面积空白和单调版式，在不改变证据内容及打开方式的前提下提升图片查看体验。
**状态**：✅ 自适应布局、深色图片舞台、证据信息侧栏和真实页面视觉验收已完成。
**干到哪里了**：
- [x] Dialog取消固定92svh高度，改为最大高度约束和内容自适应，宽幅指标截图不再悬浮在大面积空白顶部。
- [x] 建立标题、平台、截图主体和元数据三级层次；图片使用深色网格舞台，侧栏集中展示三项指标、角色、采集时间、格式和完整SHA-256。
- [x] 桌面端使用图片与250px信息侧栏并列，小屏自动堆叠；两处入口继续复用同一Dialog并保持当前标签页。
- [x] TypeScript检查和生产构建（2468 modules）通过；Patchright确认排名表与证据卡片两处入口保持当前标签页、图片加载成功、Dialog由约92svh固定高度收缩为内容高度、侧栏信息完整且控制台错误0，截图位于`artifacts/runtime/reputation-all-screenshots-dialog/`。
**下一步**：无。
**边界**：不修改截图文件、采集规则、证据接口、下载链路或历史批次。
**关联**：`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 巡检全量截图与站内证据查看
**总目标**：客户将口碑巡检证据范围改为全部车型平台执行项，并要求截图在站内Dialog查看而不是打开新标签页。
**状态**：✅ 全量证据策略、直接浏览器链路、站内Dialog与真实页面验收已完成。
**干到哪里了**：
- [x] 普通日检、首次基线、月末、补跑和隔离合成场景统一将冻结范围内全部执行项标记为必需证据；当前单平台27款新批次分母为27。
- [x] 正式巡检关闭HTTP优先分支，全部目标直接在原有受控浏览器页面上下文完成指标读取、三次稳定测量和唯一指标区域截图，未改变截图区域与文件合同。
- [x] 排名表“查看截图”和页面证据卡片改为复用接近全屏的站内图片Dialog；旧批次零证据显示“历史未要求”，不改写或补拍历史数据。
- [x] 3项针对性后端测试、Ruff、TypeScript检查和生产构建（2468 modules）通过；Patchright确认排名表与证据卡片均在当前标签页打开同一Dialog、图片成功加载、旧批次标签正确且控制台错误0，证据位于`artifacts/runtime/reputation-all-screenshots-dialog/`。
**下一步**：无。
**边界**：历史批次按创建时冻结规则保持不变；每项仍只保存一张指标区域PNG，证据包、XLSX、哈希与缺失语义沿用既有实现。
**关联**：`src/threadsnap/reputation.py`、`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 复用新增对话框修改车型信息
**总目标**：为车型与映射的每一行增加修改按钮，用同一个车型对话框维护已有草稿信息。
**状态**：✅ 前后端编辑链路、映射失效规则和真实页面保存回滚验收已完成。
**干到哪里了**：
- [x] 每行操作区增加低强调度“修改”按钮且不再叠加重复悬浮提示；点击后复用新增车型Dialog并预填车系、车型、项目组、角色、平台车型ID、URL和展示名。
- [x] 增加带revision门禁的逐车型PATCH；内部车型ID保持不变，平台ID重复、URL身份错误或过期revision时整次零写入。
- [x] 身份展示、项目组或角色变化保留已验证映射；映射任一字段变化时清除旧验证与指标并回到待验证，发布后才影响未来批次。
- [x] 角色修改不移动车型在完整映射序列中的位置，并按显示顺序重新计算角色序号。
- [x] 针对性后端测试、Ruff、前端检查与构建通过；真实页面确认27/27行均有修改入口，Dialog预填正确，实际保存及回滚成功，原数据、车型ID和已发布版本均保持不变，控制台无错误。
**下一步**：无。
**边界**：本次修改当前范围草稿，不改写已发布版本或历史批次；列表正文仍是只读展示。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/lib/types.ts`、`src/threadsnap/app.py`、`src/threadsnap/reputation.py`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 巡检详情沿用车型与映射顺序
**总目标**：排名数据和页面证据按批次冻结时“车型与映射”的完整顺序显示，不再按重点或竞品角色重新分组。
**状态**：✅ 详情接口、排名数据和页面证据已统一沿用车型与映射顺序，真实批次验收通过。
**干到哪里了**：
- [x] 详情接口按运行绑定的不可变范围版本 `snapshot.vehicles` 顺序排列结果，同车型多平台再按冻结平台顺序排列。
- [x] 没有范围版本的旧测试批次保留原角色与组内序号排序兜底，不使用当前草稿改写历史批次顺序。
- [x] 回归样本改为重点和竞品交错的车型映射顺序，并断言详情结果逐项一致。
- [x] 后端完整123项测试、Ruff、TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；Patchright确认实际批次`RP-S-20260825-5AF9`的API与DOM共27行均逐项匹配车型与映射顺序、控制台错误0，证据位于`artifacts/runtime/reputation-result-scope-order/`。
**下一步**：无。
**边界**：本次不修改既有批次、范围版本或当前草稿数据，也不增加临时排序控件。
**关联**：`src/threadsnap/reputation.py`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 移除新增车型的项目组默认值
**总目标**：新增车型时由用户明确填写项目组归属，不预填或由接口静默补入“奇瑞项目组”。
**状态**：✅ 已移除前端和接口默认值，空值门禁与真实页面验收通过。
**干到哪里了**：
- [x] 新增车型表单的项目组归属初始值改为空；现有车型列表仍只读显示已保存归属。
- [x] 新增车型接口取消项目组默认值，缺少字段或仅含空白均拒绝创建，保存时继续去除首尾空白并限制80字符。
- [x] 后端完整123项测试、Ruff、TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；Patchright确认弹窗项目组值为空、只缺该字段时确认按钮禁用、字段缺失返回422、仅空白返回400、控制台错误0，证据位于`artifacts/runtime/reputation-project-group-no-default/`。
**下一步**：无。
**边界**：既有27款“奇瑞项目组”数据不变；旧快照缺字段兼容和一次性CSV初始化回填规则不变。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`src/threadsnap/reputation.py`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 将项目组归属改为新增时填写、列表只读
**总目标**：纠正项目组归属交互；输入框只出现在“新增车型”对话框，车型列表只展示归属文本。
**状态**：✅ 表格内联输入和逐车型修改接口已移除，新增表单与现有数据保留，真实页面验收通过。
**干到哪里了**：
- [x] “项目组归属”列改为普通文本，不再显示输入边框、保存按钮或逐行编辑状态；表格最小宽度同步收紧。
- [x] 新增车型对话框继续提供1至80字符的项目组输入，新车型创建后随范围草稿和版本快照保存；默认值已由后续条目移除。
- [x] 删除未被需求支持的逐车型PATCH接口和项目组独立发布差异计数，并增加接口测试确认列表不能内联修改。
- [x] 完整123项后端测试、Ruff、TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；Patchright确认表格项目组输入框0个、只读“奇瑞项目组”单元格27个、新增对话框项目组输入1个、PATCH返回405、控制台错误0，证据位于`artifacts/runtime/reputation-project-group-readonly/`；输入默认值已由后续条目移除。
**下一步**：无。
**边界**：现有27款仍全部归属“奇瑞项目组”；本次不修改或发布实际范围数据。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/app.py`、`frontend/src/features/reputation/reputation-page.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 增加车型项目组归属维护
**总目标**：为每款车型增加项目组归属，用自由文本区分后续不同项目组，并将现有车型统一初始化为“奇瑞项目组”。
**状态**：✅ 数据回填、新增表单、只读列表展示和范围版本保存均已完成；交互已由后续条目纠正为仅新增时填写。
**干到哪里了**：
- [x] 车型范围草稿与后续不可变版本增加 `project_group`；现有27款通过Alembic迁移回填“奇瑞项目组”并仅递增当前草稿revision，已发布版本1保持原快照不变。
- [x] 新增车型请求保存1至80字符的项目组归属；列表只读显示该值，不提供逐车型修改接口。
- [x] 新增车型表单提供项目组输入，发布确认区逐车展示归属；输入默认值已由后续条目移除。
- [x] 完整124项后端测试、Ruff、TypeScript检查、生产构建（2468 modules）和`git diff --check`通过；隔离旧库验证草稿revision从6升级到7且已发布快照不被改写。
- [x] 实际数据库升级前已备份至`artifacts/runtime/reputation-project-group/threadsnap-pre-migration.db`（SHA-256 `e88d66fb897d6ebc405e59f0305e7126609a4296b882162227546273b2634e1e`）；现有27款全部回填“奇瑞项目组”，界面证据位于同目录。
**下一步**：无。
**边界**：项目组当前只属于车型范围管理和版本快照，不新增项目组字典、筛选或巡检汇报分组；本次验收已恢复全部实际车型为“奇瑞项目组”，没有发布新范围版本。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/app.py`、`src/threadsnap/migrations/versions/c7e3a1d9b402_reputation_project_group.py`、`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/lib/types.ts`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 移除巡检批次总数底栏并接入按需分页
**总目标**：删除巡检批次表格底部重复的总数提示，并让长期累积的批次通过简洁的服务端分页浏览。
**状态**：✅ 总数底栏已移除，超过20条时才出现分页导航。
**干到哪里了**：
- [x] 删除“共 N 个独立巡检批次”底栏；当前只有2条数据时表格卡底部不再显示总数或单页分页。
- [x] 巡检批次固定每页20条，页码写入URL并转换为后端 `offset/limit`；切换标签时重置页码，删除后页码越界时自动回到最后一个有效页。
- [x] 只有总数超过20条时显示“第 X / Y 页”和上/下一页操作，不增加当前没有业务必要的每页数量选择器。
- [x] 前端TypeScript检查和生产构建（2468 modules）通过；Patchright真实页面确认旧总数提示为0、单页分页按钮为0，并通过网络拦截构造21条总数验证第二页请求为 `offset=20&limit=20`、末页下一页禁用且控制台错误为0，证据位于 `artifacts/runtime/reputation-runs-pagination/`。
**下一步**：无。
**边界**：分页模拟只拦截浏览器响应，未修改生产数据库；本次不改变批次创建、筛选、排序、删除或详情逻辑。
**关联**：`frontend/src/router.tsx`、`frontend/src/components/app-shell.tsx`、`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/design/product-design.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 移除车型表格底部重复提示
**总目标**：去掉车型与映射表格底部重复显示的验证分母和新增/历史车型删除规则说明。
**状态**：✅ 提示条已移除，表格内容直接延伸到卡片底边。
**干到哪里了**：
- [x] 删除“已验证27/27 · 新增车型在发布前可永久删除，已有历史车型仅停用并保留既有版本与批次”整条底部区域。
- [x] 验证数量继续由上方启用数量、验证操作状态表达；永久删除与历史停用的差异继续在逐行操作Tooltip和二次确认框中明确展示。
- [x] 前端TypeScript检查、生产构建和`git diff --check`通过；Patchright真实页面确认旧提示文案为0且表格卡底部不再保留提示高度，证据位于`artifacts/runtime/reputation-scope-footer-hint-removed/`。
**下一步**：无。
**边界**：只删除重复界面提示，不修改验证、删除、停用、恢复或发布逻辑。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`docs/design/product-design.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 分离口碑摘要操作区与表格卡片
**总目标**：按配置管理的视觉结构，把口碑页面的上方摘要/操作区与下方数据表格拆成独立卡片，并同时覆盖巡检批次与车型映射两个标签。
**状态**：✅ 两个标签均已形成清晰的上下两卡结构。
**干到哪里了**：
- [x] “车型与映射”把标题、启停数量、说明和四个操作保留在独立头卡；车型表格、滚动区和底部验证说明进入独立表格卡，不再出现同一卡片内的无语义空带。
- [x] “巡检批次”同步拆分：固定12:00巡检摘要与最近计划事件位于独立头卡，批次表格和总数说明位于独立表格卡。
- [x] 两页统一使用12px卡片间距，表格卡继续填满剩余高度、独立滚动并吸附表头；未改变巡检、验证、发布、新增或移除业务合同。
- [x] 前端TypeScript检查和生产构建（2468 modules）通过，`git diff --check`通过；Patchright在1680×900真实页面测得两个标签卡片间距均为12px、上下卡片不重叠、控制台错误0，证据位于`artifacts/runtime/reputation-split-toolbar-cards/`。
**下一步**：无。
**边界**：只调整口碑两个列表标签的容器层级和间距，不修改表格字段、数据、接口或生产范围。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`docs/design/product-design.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 重构车型与映射维护页并补齐新增/移除闭环
**总目标**：移除无操作价值的版本展示，按配置表格样式改为固定维护头部和独立滚动表格，并提供可用的车型新增、删除、停用及恢复入口。
**状态**：✅ 前后端维护闭环、发布差异门禁和真实页面验收均已完成。
**干到哪里了**：
- [x] 移除“已发布版本”等三张统计卡，表格卡改为占满可用高度；固定头部左侧统一标题、启用/停用数量与说明，右侧按验证、新增、批量映射、发布组织按钮，表格正文独立滚动且表头吸附。
- [x] 新增车型由服务端生成不可复用内部ID并原子保存当前平台映射，初始为待验证；新增弹窗完整覆盖车系、车型、角色、平台车型ID、展示名和URL。
- [x] 逐行移除按真实历史引用判定：未进入版本或批次的草稿车型二次确认后永久删除，已有历史车型只停用并保留身份、版本和批次，停用行提供恢复入口；映射验证和真实验收只处理启用车型。
- [x] 发布预览改为启用范围，并实际计算新增、停用、角色/顺序、名称和映射差异；全部启用映射已验证且确有业务变更时才开放发布，避免重复发布同一范围。
- [x] 完整123项后端测试通过；Ruff、Python编译、`pip check`、前端TypeScript检查、生产构建（2468 modules）及`git diff --check`通过。Patchright在1680×900真实页面确认版本文案0处、新增入口可见、27个移除入口、表头`position=sticky`、历史停用提示及新增字段齐全，证据位于`artifacts/runtime/reputation-vehicle-maintenance/`。
**下一步**：无。
**边界**：本次没有修改生产范围数据或发布新版本；现有27款已进入历史版本，因此当前移除入口均明确执行停用，只有以后新建且尚未发布的车型才会永久删除。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/app.py`、`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/lib/types.ts`、`tests/test_reputation.py`、`docs/design/product-design.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 移除车型范围草稿技术提示
**总目标**：移除车型表格上方会被误解为业务变更状态的裸 revision 与常驻操作说明，只保留实际可执行操作。
**状态**：✅ “当前范围草稿 · revision”及重复说明已移除，工具栏与表格直接衔接。
**干到哪里了**：
- [x] 核对当前页面和后端范围接口：没有车型新增、停用或删除入口，现有操作仅为批量修改平台映射、重新验证和发布版本。
- [x] 确认 `revision` 是保存、验证和发布的并发控制号；重新验证也会令其递增，不能把 `revision 6` 解释为新增、删除或六次业务变更。
- [x] 移除常驻的“当前范围草稿 · revision”与验证说明，保留批量粘贴映射、发布版本和重新验证三个操作；技术 revision 继续在请求中使用，不改变冲突保护。
- [x] 前端生产构建通过（2468 modules），`git diff --check` 通过；Patchright 在 1680×1000 真实页面确认旧文案为0、三个操作仍可见、表格首列16px边距保持、控制台错误0，证据位于 `artifacts/runtime/reputation-scope-caption-removed-20260825/`。
**下一步**：无。
**边界**：本次只移除误导性的技术提示，不新增车型维护能力，也不修改映射、验证、发布或 revision 并发合同。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`docs/design/product-design.md`

---

## 2026-08-25 — 统一口碑巡检新增表格视觉合同
**总目标**：让巡检批次、车型与映射及批次排名数据表与应用既有表格保持同一视觉层级、对齐规则和交互反馈。
**状态**：✅ 三张口碑表格的视觉、交互及首末列边距已统一，真实页面像素复核通过。
**干到哪里了**：
- [x] 确认新增页面本来已经复用公共 `Table` 组件，但页面级样式仍有实质差异：角色顺序误用高强调实心徽标、指标列居中、详情冻结列遮蔽表头与悬停底色、批次整行缺少键盘焦点，且三张表首末单元格仍为8px，没有与卡片工具栏和说明区的16px内容边线对齐。
- [x] 角色顺序改为共享的低强调圆点、文字和等宽序号；口碑分、排名、口碑量统一右对齐，独立图标操作居中，文字操作右对齐，表头和卡片层级归一。
- [x] 巡检批次、车型与映射、排名数据三张表的首列表头和数据统一左留16px、末列表头和数据统一右留16px；中间列保持8px，车型与映射工具栏、表格首列及排名说明区现在共享同一内容边线。
- [x] 批次行补齐 `tabIndex`、焦点反馈和回车进入；详情冻结列表头与行悬停背景连续，不再形成白色断层。
- [x] 前端生产构建通过（2468 modules），`git diff --check` 通过；Patchright 在 1680×1000 真实页面逐项确认三张表首末表头和数据格均为16px、冻结列悬停正常、控制台错误0，既有提取批次表仍保持原样，证据位于 `artifacts/runtime/reputation-table-edge-spacing-20260825/`。
**下一步**：无。
**边界**：只统一表格视觉和既有交互合同，不修改巡检数据、角色语义、指标比较、映射验证或批次处理逻辑。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`frontend/src/features/reputation/reputation-role-label.tsx`、`frontend/src/styles/index.css`、`docs/design/product-design.md`

---

## 2026-08-25 — 移除车型与映射页采集器成功提示
**总目标**：移除已经成为正常运行前提的“真实采集器已接入”常驻提示，减少无操作价值的信息占位。
**状态**：✅ 正常接入状态不再显示提示卡，阻断性未就绪状态仍保留异常提示。
**干到哪里了**：
- [x] 车型与映射页不再把适配器版本和“已接入”作为常驻成功信息；范围版本、车型分母、映射验证状态和操作区直接相邻展示。
- [x] 没有删除后端能力状态：`real_adapter_status=not_configured`时仍显示“真实采集器尚未就绪”异常提示，避免把真实阻断也一起隐藏。
- [x] 前端TypeScript与生产构建通过（2467 modules），`git diff --check`通过；Patchright在1680×1000真实页面确认成功提示和适配器版本文案消失、范围表格正常、控制台错误0，证据位于`artifacts/runtime/reputation-adapter-banner-removed-20260825/`。
**下一步**：无。
**边界**：只精简正常状态下的页面信息层级，不修改采集器能力API、映射验证、发布门禁或异常提示语义。
**关联**：`frontend/src/features/reputation/reputation-page.tsx`、`docs/design/product-design.md`

---

## 2026-08-25 — 口碑汇报改为巡检终态立即生成
**总目标**：取消没有业务价值的固定汇报等待时点，在正式巡检取得可靠终态后立即生成正文、TXT和XLSX。
**状态**：✅ 终态触发汇报已部署，今天12:00真实批次的等待门槛已清除并成功补生成。
**干到哪里了**：
- [x] 12:00只负责创建正式巡检；协调器在同一执行轮取得成功、部分成功或失败终态后立即进入汇报生成，恢复轮询也会立即处理历史`waiting`或有重试预算的失败产物，不再比较独立汇报计划时点。
- [x] 新批次`report_planned_at`保持空值，日程API保留兼容字段但返回`report_time=null`；前端日程改为“巡检完成后立即生成汇报”，详情移除“等待定时汇报”和计划生成时间文案。
- [x] 已部署并重启后端；真实批次 `RP-S-20260825-5AF9` 在12:00:13终态，旧版12:30门槛已清除，于12:05:59成功生成TXT/XLSX，API确认`report_status=success`、`report_planned_at=null`，8000后端和5173代理健康均为`ok`。
- [x] 新增协调器同一轮“执行→终态→汇报成功”回归；完整122项后端测试、Ruff、Python编译、`pip check`、前端生产构建（2467 modules）和`git diff --check`通过。Patchright真实前端确认新日程文案、汇报正文和TXT/XLSX入口可见，旧等待文案消失、控制台错误0，证据位于`artifacts/runtime/reputation-terminal-report-20260825/`。
**下一步**：无。
**边界**：汇报仍只读取终态冻结数据；运行中不生成半成品，全部失败仍按原合同只形成失败记录，证据ZIP继续按需生成且不阻塞汇报。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/reputation_scheduler.py`、`frontend/src/features/reputation/reputation-page.tsx`、`frontend/src/features/reputation/reputation-detail-page.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 将口碑固定日程调整为12:00并完成真实定时验收
**总目标**：把口碑正式巡检调整到12:00，并通过后台协调器的真实到点触发证明定时链生效。
**状态**：✅ 固定日程已调整为12:00巡检、12:30汇报，真实到点批次27/27成功。
**干到哪里了**：
- [x] 后端调度、同日补触发、范围版本冻结、汇报计划和状态文案统一使用12:00/12:30；前端只读日程与发布说明同步更新，领域词汇、产品设计、技术路线和口碑链档已归一。
- [x] 部署新时点后，通过正式删除链清除当天旧测试批次，再精确移除当天删除墓碑与旧计划事件；12:00前确认当天正式批次、墓碑、计划事件均为0，期间未调用调度检查、批次创建或执行接口。
- [x] 后台协调器于 `2026-08-25 12:00:04 +08:00` 自动创建正式批次 `01a03713-4599-7da1-940e-b8416ef25af9`（`RP-S-20260825-5AF9`），计划时点12:00、`delayed=false`、并发2；12:00:13完成27/27，失败0，冻结2026-08-24真实初始化基线，按需证据0/0，12:30汇报保持等待状态。
- [x] 完整121项后端测试、口碑调度定向回归、Ruff、Python编译、`pip check`、前端生产构建（2467 modules）和`git diff --check`通过；运行中API返回12:00:00/12:30:00。
**下一步**：无需保持对话；后台服务继续运行并在12:30生成该批次汇报。
**边界**：日程仍为只读固定配置，不新增用户可编辑计划；本次验收只由真实后台定时器创建批次，未以手动调用替代到点触发。
**关联**：`src/threadsnap/reputation.py`、`frontend/src/features/reputation/reputation-page.tsx`、`tests/test_reputation.py`、`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 修复口碑详情禁用下载按钮结构
**总目标**：修正“证据 ZIP”无下载内容时与TXT/XLSX按钮内部结构不一致造成的图标、文字和高度错位。
**状态**：✅ 禁用按钮已与可下载按钮统一为直接flex子项结构，生产页面实机验证通过。
**干到哪里了**：
- [x] 根因确认：可下载分支由链接直接继承按钮布局，禁用分支却额外包裹普通`span`，使图标和文字脱离按钮的水平flex排列；现已移除该中间层，保留原禁用语义。
- [x] 前端TypeScript与生产构建通过（2467 modules）；Patchright在1680×1000页面确认TXT、XLSX和证据ZIP均高32px、顶部误差小于1px、图标文字水平同轴，控制台错误0。
- [x] 验证回执与页面截图位于 `artifacts/runtime/reputation-download-layout-20260825/`。
**下一步**：无。
**边界**：只修复禁用下载按钮DOM与视觉对齐，不改变证据ZIP生成条件、下载权限或批次数据。
**关联**：`frontend/src/features/reputation/reputation-detail-page.tsx`

---

## 2026-08-25 — 口碑日检改为HTTP取数后按需启动浏览器
**总目标**：普通日检不再为无需截图的车型打开浏览器，先轻量取数和比较，只为实际需要证据的项建立浏览器上下文。
**状态**：✅ HTTP优先两阶段适配器已完成，当前27项真实范围验证为27次HTTP、0个浏览器目标且指标合同一致。
**干到哪里了**：
- [x] 懂车帝普通日检通过共享Session Cookie和Chrome拟态HTTP Session直接访问车型URL，从UTF-8 SSR HTML解析稳定车型身份、同级评分当前行、口碑分、排名和评价量；不加载浏览器页面、图片或前端脚本。
- [x] 完成前日比较后只把命中重点车型口碑分或排名变化规则的项送入Patchright；浏览器阶段重新取得该项指标并在同一上下文截图，最终不跨HTTP与浏览器时点拼字段。首次基线、月末和映射验证因全量留证直接走浏览器，避免重复请求。
- [x] 当前生产范围以并发2做只读真实验证：27/27 HTTP解析成功，总耗时7.8秒，浏览器目标0；口碑分和排名与10:30正式批次均0差异。回执位于 `artifacts/runtime/reputation-http-first-20260825/live-http-verification.json`。
- [x] 新增SSR字段合同、仅证据目标进入浏览器及正式批次路由回归；完整121项后端测试、Ruff、Python编译、`pip check` 和 `git diff --check` 通过。
- [x] 后端已使用项目虚拟环境重启并加载新代码；8000后端、5173前端和Vite代理 `/health` 均为 `ok`，前端HTTP 200，服务继续保持运行。
**下一步**：开发范围内无剩余项；保留服务运行，由下一个普通日检按新链路自动执行HTTP取数和按需截图。
**边界**：HTTP解析或网络暂时错误仍按原规则有界重试，不以全量浏览器兜底掩盖失败；需要截图的项仍必须用浏览器形成同一上下文指标与证据。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`src/threadsnap/reputation.py`、`tests/test_reputation.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-25 — 精简口碑批次详情首屏
**总目标**：移除口碑批次详情中低频调度审计信息卡，把首屏空间还给结果、证据和汇报。
**状态**：✅ 独立信息卡已移除，危险操作已收进标题区更多菜单，生产页面实机验证通过。
**干到哪里了**：
- [x] 移除计划巡检时间、计划汇报时间、范围版本和前日基线组成的整块常驻信息卡；这些值继续由后端与API持久化，不改变调度、基线或产物逻辑。
- [x] 失败项补跑和删除关联链保留原能力，改放到标题状态徽标后的“更多批次操作”菜单；删除仍使用二次确认，不把危险动作作为首屏主按钮。
- [x] 前端TypeScript与生产构建通过（2467 modules）；Patchright在1680×1000生产页面确认信息卡消失、更多菜单可打开且删除入口可见，控制台错误0，证据位于 `artifacts/runtime/reputation-detail-density-20260825/`。
**下一步**：无。
**边界**：只调整详情信息层级，不修改批次数据、调度时间、冻结基线、失败项补跑或删除语义。
**关联**：`frontend/src/features/reputation/reputation-detail-page.tsx`、`docs/design/product-design.md`

---

## 2026-08-25 — 口碑正式调度闭环与真实初始化基线修正
**总目标**：完成固定10:00正式口碑巡检、10:30终态汇报、失败项补跑、关联链删除和生产前端闭环，并确保真实初始化数据承担次日前日基线。
**状态**：✅ 正式调度生产闭环、并发2真实日检、前日比较、汇报与交付文件均已完成；昨日27/27真实初始化批次已正确冻结为今日基线。
**干到哪里了**：
- [x] 新增正式日程事件、调度水位、运行根链、计划时间、范围版本、并发快照、基线快照、派生产物状态、删除墓碑和两阶段删除作业数据库基线；迁移执行 `upgrade → downgrade → upgrade` 往返通过。
- [x] 后端实现北京时间10:00幂等触发、同日补触发、跨日只记漏触发、10:30等待终态、终态后立即生成TXT/XLSX、失败项关联补跑、按需区域证据ZIP和整链删除恢复；正式批次对普通平台任务采用非抢占优先，失败项补跑保持普通FIFO。
- [x] 修正基线资格错误：`real_acceptance` 真实初始化批次允许作为严格前一自然日基线，同日存在正式批次时仍优先正式结果；新增回归测试证明下一次正式运行直接进入日常比较而非重复初始化。详情页同时明确区分“前日基线已冻结”和“目标基线日无可用数据”。
- [x] 生产正式批次 `01a036b5-3be4-7bf3-97c8-9b47ed4ffd98`（`RP-S-20260825-FD98`）已冻结 `2026-08-24` 初始化批次 `01a0346a-b2e6-7296-8aaf-dbc7d52010f4` 的27项结果，并按平台配置并发2重新执行：27/27成功，约69秒终态；19项口碑分和19项排名可比较且持平，16项口碑量变化，日检无口碑分或排名变化，因此截图分母为0而不是重复全量截图。
- [x] 10:30到点时批次仍运行，系统按合同等待；终态后于 `2026-08-25 10:30:49 +08:00` 自动生成汇报。UTF-8 TXT为1211字节，固定XLSX为27行、0张非必要图片；实际汇报逐项列出16个口碑量变化并单列8个页面暂无口碑分或排名的车型。
- [x] 前端把含糊的“延迟执行”改为带说明的“同日补触发”，无证据触发时显示“无需截图”，规范值相同显示“较前日持平/名次持平”而不误写下降0。Patchright实机验证基线、类型、27/27、无需截图和持平文案，控制台错误0；截图与回执位于 `artifacts/runtime/reputation-baseline-repair-20260825-102938/`。
- [x] 错误的并发8重复初始化运行在修复前已做一致性数据库备份并隔离原文件；备份SHA-256为 `1918a0be83010847db8180df36a3a3a259c083210ba11ccb003b4427891dc670`，`PRAGMA integrity_check=ok`，修复回执与最终API快照同目录保留。
- [x] 完整119项后端测试、Ruff、Python编译、`pip check`、前端TypeScript与生产构建（2467 modules）和 `git diff --check` 通过；后端8000、前端5173及Vite代理健康均为`ok`。
**下一步**：开发范围内无剩余口碑正式调度缺口；保留服务运行并观察下一个自然日10:00自动触发属于生产运行观察，不是新增开发门。
**边界**：当前真实运行范围仍只有已接入的懂车帝；其他两个目标平台须在各自适配器、映射和容量门禁完成后再扩展，不把当前27项描述为未来三平台81项。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/reputation_scheduler.py`、`src/threadsnap/reputation_dongchedi.py`、`frontend/src/features/reputation/`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-24 — 口碑证据改为单张必要区域截图
**总目标**：所有口碑页面证据只保留用户指定的车型口碑指标区域，不再生成、展示或打包完整长截图。
**状态**：✅ 代码、产品/技术口径与生产历史证据均已收敛为单一指标区域截图；现有真实验收批次仍为27/27且无完整长截图残留。
**干到哪里了**：
- [x] 真实适配器改为在三次稳定测量后直接按DOM矩形截图，不再先截完整长页再裁图；兼容字段指向同一张区域PNG。
- [x] 前端排名数据和页面证据只打开指标区域截图，移除“完整原页”文案与入口；证据ZIP每项只写一个 `region.png`。
- [x] 增加 `reputation-compact-evidence` 运维命令，将历史验证尝试和巡检证据统一指向区域图并清理不再引用的长图与旧证据ZIP。
- [x] 生产收敛完成：55个成功验证尝试与27个巡检证据均为单一路径/单一哈希，移除82个旧文件，`data/reputation` 下 `full.png` 为0；真实验收批次27/27，兼容入口返回相同区域PNG。
- [x] 两项相关后端测试、Ruff、前端TypeScript和 `git diff --check` 通过；人工查看风云A9区域图确认只含车型名称及指定口碑指标卡片；生产证据ZIP为 `reputation-evidence-region-v1`，27项仅含27张 `region.png`，无 `full.png`。
**下一步**：继续实现10:00正式调度与10:30汇报；所有未来口碑证据沿用单一区域截图合同。
**边界**：帖子提取的原始页面证据不在本次变更范围；本规则只作用于独立口碑巡检模块。
**关联**：`src/threadsnap/reputation_dongchedi.py`、`src/threadsnap/reputation.py`、`frontend/src/features/reputation/`、`docs/design/product-design.md`

---

## 2026-08-24 — 真实URL验收批次可见化
**总目标**：把已完成的27款真实页面验证结果作为可查看、可下载的口碑巡检验收批次呈现，同时避免重复访问和重复截图。
**状态**：✅ 首轮真实验证25/27后仅补跑2个失败项，最终27/27；真实验收批次、页面证据、TXT与XLSX均已生成并可由生产前端查看。
**干到哪里了**：
- [x] 真实验证运行 `01a03461-01ab-76be-b552-10c4bf43557c` 完成25/27；只补跑艾瑞泽8和瑞虎8，运行 `01a03466-cc32-7d9f-a0b8-cabb2589b2a2` 用时7.8秒且2/2成功，没有重复截图其余25项。
- [x] 新增 `reputation-real-acceptance` 运维命令，按已发布范围核对映射哈希与证据SHA-256，复用既有真实结果创建独立 `real_acceptance` 批次，不再次访问平台；前端显示“真实验收”标识。
- [x] 生产批次 `01a0346a-b2e6-7296-8aaf-dbc7d52010f4`（`RP-A-20260824-153642-10F4`）为成功，结果27/27、逻辑证据27/27、TXT HTTP 200、XLSX HTTP 200且文件4,470,483字节。
- [x] 相关后端单测、Ruff、前端TypeScript与 `git diff --check` 通过。
**下一步**：继续实现并验收10:00正式调度、10:30汇报时点和正式基线选择；真实验收批次不冒充计划首跑。
**边界**：该批次只冻结已经完成的真实映射验证尝试，不提供通用立即巡检、不重新请求平台、不消费正式日期幂等键。
**关联**：`src/threadsnap/reputation.py`、`src/threadsnap/cli.py`、`frontend/src/features/reputation/`、`docs/chains/reputation-inspection.md`

---

## 2026-08-24 — 垂媒口碑巡检隔离纵切与懂车帝真实映射
**总目标**：在现有应用外壳中实现独立口碑巡检前后端、车型范围草稿、可重复合成验收链及懂车帝27款真实页面映射验证。
**状态**：✅ 数据库、双API、范围初始化/映射、三场景合成运行、真实适配器、27款映射验证、排名/证据/汇报UI及真实浏览器验收已完成；⏳ 首个范围等待用户显式发布，10:00正式调度、10:30产物与真实基线首跑仍待下一阶段完成。
**干到哪里了**：
- [x] 新增 Alembic `e1f7a9c4d203` 及范围草稿/版本、巡检运行、车型平台结果、逻辑证据模型；迁移 `upgrade → downgrade → upgrade` 往返通过。
- [x] 新增 `/api/v1/reputation/*` 与 `/internal/v1/reputation/*` 能力、列表、详情、三因子隔离测试、证据、TXT/XLSX/ZIP下载、范围、映射预览/原子保存、真实映射验证及发布门禁接口；真实适配器能力现返回 `available`。
- [x] `threadsnap reputation-init --file` 原子校验27款、14/13角色分母、唯一键和连续顺序；仓库增加空CSV模板与Schema。后续映射按单平台四列Tab数据预览，错误行零写入。
- [x] 三个确定性场景均真实生成27项：基线与月末证据27/27，日常混合证据6/6；网页和XLSX按业务方向红绿并辅以箭头文字，TXT保持纯文本，证据ZIP包含原始PNG、manifest和SHA256SUMS。
- [x] 前端新增顶级“口碑巡检”，内部分为“巡检批次 / 车型与映射”，详情分为“排名数据 / 页面证据 / 汇报结果”；复用现有密度、色板、卡片、表格和深链，并加入180～300ms克制动效与减少动态效果支持。
- [x] 完整117项后端测试、Ruff、Python编译、`pip check`、前端TypeScript/生产构建（2467 modules）和 `git diff --check` 通过；生产后端、Vite与代理健康均为`ok`。
- [x] Patchright在1600×1000真实触发日常混合测试并检查列表、排名、证据、汇报、范围和错误预览，页面无脚本异常；证据位于 `artifacts/runtime/reputation-ui/verification.json`，SHA-256 `5a8963df2ffb74299b90ca25ce327bde272a192548de6897f53c4e78c554093d`。
- [x] 用户提供的27个懂车帝URL已整理为Git忽略的UTF-8 CSV并原子初始化生产范围；真实浏览器合同探测27/27通过，确认业务排名来自“同级车评分”当前行而非顶部全站 `No.N`，历史截图数值只作核对、不覆盖实时值。
- [x] 新增 `dongchedi-reputation-v1` 有头Patchright适配器、URL/稳定ID/展示名身份门禁、三次指标与矩形稳定测量、完整原页和同源指标裁图、SHA-256、映射验证运行/尝试迁移、失败项有界重试和前端“验证全部真实页面”入口；生产映射首轮23/27后只重试4个失败项，最终草稿27/27验证通过。
- [x] 生产真实验证运行 `01a03446-63cf-733e-95dc-f60b1fa0826b` 在并发8下61秒完成23项，修正懒加载文档高度误判后运行 `01a03448-08bf-7817-9a28-489560b9669d` 仅重验4项并在10秒内4/4成功；响应证据位于 `artifacts/runtime/reputation-real-adapter-20260824/`，数据库草稿revision为4。
- [x] 当前27项完整原页与指标图文件均按数据库SHA-256复核通过，汇总 `evidence-verification.json` SHA-256 为 `327ec1522095c18ad9de2fe0ce6835c7cfc9c2335d2092d5e3d999f642cde79c`；1600×1000真实UI显示27/27、实时指标、证据入口和首发全量复核框，控制台0错误，截图SHA-256分别为 `534c694ec32e87ab768f622f3e7a7324d063a6928181c341489d4c9880e8f096` 与 `418e1634b3373e8a8bf4ea2e54d529b21ea864a146d4031f8911096bdf7c5e41`。
- [x] 首发确认框明确表述为“供后续10:00正式巡检按计划时点冻结使用”，避免把尚待实现的正式调度误报为已经生效；前端TypeScript与生产构建再次通过。
**下一步**：用户在“车型与映射”逐项查看实时三指标与指标证据后点击“发布首个范围”；随后实现并验收10:00正式调度、10:30汇报/固定XLSX/证据ZIP和首个27/27真实基线，不以映射验证或合成测试替代正式首跑。
**边界**：测试手动按钮仍只由后端三因子能力开放且不访问平台；真实映射验证不创建正式巡检批次、不建立前日基线、不触发10:30汇报。当前27款仅覆盖懂车帝，其他平台全部接入后的完整映射门禁仍为届时第一优先级。
**关联**：`src/threadsnap/reputation.py`、`frontend/src/features/reputation/`、`tests/test_reputation.py`、`docs/templates/reputation-scope-v1.*`、`docs/adr/0032-separate-reputation-inspection-from-post-extraction.md`、`docs/adr/0036-isolate-synthetic-reputation-test-runs.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-24 — 垂媒口碑巡检需求澄清与领域建模
**总目标**：在不污染现有帖子提取批次语义的前提下，逐项确认垂媒口碑日检、月检、跨期比较、页面证据和汇报规则，形成可实现、可验收的产品与技术设计。
**状态**：✅ 核心需求访谈、领域建模、产品与技术合同、ADR及整体冲突检查已完成；尚未进入功能实现。
**干到哪里了**：
- [x] 确认新增独立“口碑巡检”一级业务入口，每次执行创建独立口碑巡检批次；批次详情使用“排名数据 / 页面证据 / 汇报结果”三个同级视图。
- [x] 明确口碑巡检不复用现有提取批次作为领域对象，但复用同一应用外壳、前端技术栈、调度与状态基础设施及可复用组件。
- [x] 在领域词汇、产品设计和 ADR 0032 中记录上述边界，避免后续把口碑指标误加为帖子批次第三个结果标签。
- [x] 确认每个自然月最后一天只创建一个月末巡检批次：只采集一次全量车型与平台数据，同时承担前一日比较、全量页面证据和 10:30 当日汇报，不重复创建日常巡检批次。
- [x] 确认前日比较严格使用前一个自然日的最终有效结果；缺失时不跨日寻找替代值，不计算变化、不标色、不以变化触发截图，并把缺失作为独立异常。
- [x] 确认口碑分、排名和口碑量逐指标独立比较与着色；方向冲突时不合成总体结论，汇报为“表现分化”并分别说明改善项和下降项。
- [x] 确认日检页面证据只由重点14款车型的口碑分或排名变化触发；口碑量单独变化不截图，但继续着色并进入汇报；月末仍覆盖27款车型 × 3个平台全量证据。
- [x] 确认日检只截实际发生口碑分或排名变化的“车型 × 平台”组合，不连带截取同车型未变化平台；月末分母按批次冻结的车型数与实际平台数计算。
- [x] 确认车型范围、重点或竞品角色及三平台映射采用配置化、版本化方案；未来批次使用最新版，历史批次冻结创建时版本且不因配置删除而改变。
- [x] 确认当前只处理已经接入的一个平台，当前月末证据分母修正为27；三目标平台全部接入后，完整且已验证的三平台车型映射门禁作为第一优先级，门禁通过后月末分母才扩展为81。
- [x] 确认每个车型平台组合独立执行并进行有界自动重试；单项失败不终止其他项，批次按全部执行项汇总为成功、部分成功或失败，成功结果保持不可变且不以旧值补缺。
- [x] 确认“重新巡检失败项”创建新的关联补跑批次，只处理尚未成功的执行项；原批次及证据永不覆盖，页面可汇总当前关联结果但数据库不物理合并。
- [x] 确认平台明确暂无保存为 `not_available`，允许执行项成功；采集异常缺失保存为 `unknown`，按可靠指标覆盖形成部分成功或失败。两者都不填旧值，月末均保留同期页面证据。
- [x] 确认巡检批次创建时冻结前一自然日当时可用的关联结果版本；晚到补跑不追溯修改后续批次的差值、颜色、页面证据或汇报输入。
- [x] 确认成功批次生成正常汇报；部分成功仍生成醒目标记的“不完整汇报”并列出缺失分母；全部失败只生成失败记录，补跑不自动改写已发汇报。
- [x] 确认10:30到点但巡检未终态时汇报进入等待；批次终态后立即生成并记录实际时间和延迟标识，不读取运行中数据生成半成品，巡检与汇报状态分开。
- [x] 确认日报按平台只列任一指标变化的车型；口碑量变化进入正文但不附日检证据，只有口碑分或排名变化才附证据，异常与缺失单列。
- [x] 确认月末汇报沿用日报前日变化规则，只增加月末标识和全量页面证据摘要；当前不增加月初月末、月均值或整月趋势统计。
- [x] 确认车型使用不可变内部ID，平台ID、URL和展示名称作为显式映射；名称只作展示与候选提示，同名不同代际或业务对象使用不同车型ID，历史冻结当时名称和映射。
- [x] 确认失效平台映射停止访问旧URL并进入“映射待修复”；系统只提示候选，必须由用户确认身份并验证后生成新范围版本，其他车型继续巡检。
- [x] 确认当前版本不提供通用“立即巡检”；每日计划只创建唯一正式完整批次，仅保留映射验证和失败项补跑，二者不触发独立10:30汇报或改变冻结基线。
- [x] 确认当前版本固定北京时间10:00巡检、10:30汇报，月末同一10:00以月末批次替代日常批次；前端只读展示，不加入帖子提取每周计划或新增时间配置。
- [x] 确认口碑巡检模块内部设置“巡检批次 / 车型与映射”同级页面；车型范围归本模块编辑，共享平台连接与Session仍由现有平台配置唯一拥有并在巡检模块只读引用。
- [x] 确认证据以不可变完整原页为事实来源，并从同一原页按已验证DOM边界派生指标区域图；前端和表格默认使用派生图并可查看原页，两者共用一个逻辑证据身份。
- [x] 确认10:30汇报只在系统内生成，支持查看、复制和下载；当前不自动发送企业微信、邮件或其他外部渠道，也不增加接收人和送达状态。
- [x] 确认口碑巡检XLSX使用系统固定版式，按批次平台范围动态生成列并在备注嵌入指标区域证据；不复用帖子模板标签或增加用户上传模板。
- [x] 确认指标与证据状态分离；必需证据失败保留成功指标但使批次总体部分成功，原页存在时本地重建派生图，原页缺失时只允许新关联补跑形成新时点证据。
- [x] 确认首次正式巡检标记为基线初始化批次：不计算变化或着色，对当前车型平台范围全量留证；若恰逢月末只使用同一批次与证据。
- [x] 确认XLSX每个车型只使用备注列一个单元格；单平台锚定指标图，多平台把1至3张指标图组成一张带平台名称的预览图后锚定该单元格，独立证据不合并。
- [x] 确认历史巡检不自动过期；人工删除按每日正式批次及全部关联补跑和产物整体清理，后续已冻结结果不重算并只保留编号、日期、删除时间和结果哈希墓碑。
- [x] 确认范围草稿验证通过后仍需用户显式“发布新版本”；每日10:00只冻结唯一已发布版本，无当前版本时记录配置错误且不创建空批次。
- [x] 确认映射必须在同一次受控页面访问中同时通过车型身份、指标解析和页面证据门禁，并以同一上下文连续三次稳定测量及原页/派生图哈希证明。
- [x] 确认排名保存并比较榜单或分类范围身份；范围变化记为 `not_comparable`，不判升降，重点车型单独留证并在汇报中列为排名口径变化。
- [x] 确认口碑指标按平台可见原始文字解析的Decimal规范值比较；等价格式不算变化，隐藏高精度不着色、不截图、不汇报。
- [x] 确认服务停机漏过10:00时同一北京时间自然日补建唯一延迟正式批次，月末保持月末类型；跨日只记录漏触发，不补拍历史页面，下一批次按前日基线缺失处理；日期与计划批次类型作为稳定幂等键。
- [x] 确认批次删除使用不可变清单和同盘隔离区执行两阶段作业；数据库提交前失败恢复文件并保留原数据，提交后隔离区清理失败只进入可重试状态，不撤销逻辑删除；ADR 0034记录该边界。
- [x] 确认同日延迟批次按发布历史冻结计划时刻10:00生效的范围版本；恢复前新发布版本只影响下一次巡检，10:00没有已发布版本时当天不补建批次。
- [x] 确认失败项补跑重新执行完整车型平台项；关联结果不跨尝试拼接指标或证据，按完整成功、部分成功、失败排序并在同等级取最新单一版本，下一日基线冻结该版本。
- [x] 确认汇报正文下载为与复制内容一致的UTF-8 TXT，数据与证据继续使用固定版式XLSX，完整原页走证据入口；当前不增加DOCX、PDF、HTML或ZIP汇报包。
- [x] 确认删除墓碑继续占用原巡检日期和计划批次类型的幂等身份，不允许删除后重建或同日补触发；后续未创建批次视为无前日基线，已冻结批次只标记来源已删除。
- [x] 确认证据支持单项原页PNG、指标区域PNG和批次级独立ZIP下载；ZIP按日检实际证据或月末全量范围打包既有不可变PNG，并携带manifest与SHA256SUMS，缺失项只记原因且不与TXT/XLSX混装。
- [x] 确认当前单平台直接使用固定预算：单次页面访问90秒、暂时性错误最多重试1次、整批从实际开始起45分钟；只做一次真实27车型闭环和自动化超时故障测试，不设独立多轮PoC。
- [x] 确认口碑量规范为“条”并保留原始文字、单位和可见精度；区分exact、rounded、lower_bound，只有同语义才比较，语义变化记为不可比较且不单独触发日检截图。
- [x] 确认映射连续性按平台稳定车型身份判断；稳定ID不变时续比，稳定ID变化或首次接入只为该车型平台项建立新映射基线并全量留证，其他项继续正常比较。
- [x] 确认批次列表以每日正式批次根节点为顶层行，补跑折叠到关联链；默认当前月按计划日期倒序，首版只提供日期、日检或月末、原状态和批次编号筛选。
- [x] 确认口碑巡检不长期等待认证或提供运行中取消；Session失效项快速记为auth_required，完成共享配置认证后显式补跑。执行项采用受控并发，普通日检目标5分钟、当前单平台首次/月末目标15分钟，45分钟保留为异常硬上限。
- [x] 确认口碑巡检批次冻结并直接复用现有平台内部并发，当前默认2、范围1至8；指标、页面、截图和重试共用执行项槽位，并与帖子提取共享平台总容量，不新增口碑或浏览器并发配置。
- [x] 确认每日正式口碑批次使用非抢占高优先级：不打断已开始帖子请求，只优先领取随后释放的平台槽位；失败项补跑和映射验证保持普通FIFO。ADR 0035记录对ADR 0009的窄例外。
- [x] 确认批次详情默认进入排名数据，证据和汇报摘要可深链到URL视图；排名表按冻结范围的重点、竞品和组内固定顺序展示，临时排序不回写配置，各类异常在指标单元格直接显示。
- [x] 确认巡检、正文、TXT、XLSX和证据ZIP状态分离；派生文件失败自动重试1次，随后只基于冻结输入重建失败产物，生成器升级追加版本，晚到补跑不改写成功产物。
- [x] 确认证据ZIP按需生成并缓存：批次终态只冻结清单和输入哈希，首次下载幂等创建唯一生成任务；10:30汇报、TXT和XLSX不等待ZIP，当前不做定时预生成。
- [x] 确认范围发布前后展示变更数量、下一生效时间、预计分母和新映射基线数量；只有调度冻结前已提交版本进入当天批次，不提供立即应用到运行中批次或重算当天结果。
- [x] 确认排名表左侧固定角色、车系、车型，每个平台固定口碑分、排名、口碑量、状态或证据四列；比较细节收敛在单元格，未来三平台横向滚动，XLSX继续三指标加单一备注。
- [x] 确认每种历史派生文件默认下载首次成功发布版；生成器升级形成的重建版显示版本、输入、原因与哈希并只供显式选择，不允许替换默认或改变当日汇报快照。
- [x] 确认证据进度按车型平台逻辑项统计，原页和指标图不重复计份；列表显示逻辑完整数，详情分别展示可靠指标、原页、派生图和逻辑完整度，并按平台分组失败与缺失。
- [x] 确认车型范围草稿按重点与竞品分组排序，支持拖拽和键盘移动；角色切换追加到目标组末尾，筛选时禁用排序，排序无需重验映射但必须发布后才影响未来批次。
- [x] 确认汇报始终保留每个冻结平台分组；可比较无变化、无可比较结果和混合异常使用不同文案，只有全部平台均可比较、均无变化且无异常时才显示全局无变化提示。
- [x] 确认日常与月末共用同一批次列表，只用类型徽标区分；月末不整行染色，基线初始化和延迟执行作为附加徽标，运行状态保留独立状态色。
- [x] 确认只对本地未提交改动和进行中的保存或验证启用离开保护；已保存未发布草稿可以直接离开，发布前必须保存并基于最新revision重新预览，任何离开或保存都不自动发布。
- [x] 确认首次27款车型由人工复核的结构化清单通过一次性命令原子导入全新业务数据库；截图只作核对，不直接OCR建库，导入全量校验14款重点与13款竞品并记录源文件哈希，平台映射仍须真实验证。
- [x] 确认后续映射按单个平台批量粘贴四列数据，只以内部车型ID匹配；保存前预览，本次行集事务全有或全无，未包含车型不变，“保存并验证”只验证实际变化项且失败不回滚草稿。
- [x] 确认一次性初始化清单使用固定十列表头的UTF-8 CSV并允许BOM；仓库只保存空模板、Schema和校验规则，实际文件按路径导入，数据库只记录原始字节SHA-256和摘要而不保存CSV副本。
- [x] 确认首个范围版本复用增强发布确认框，全量展示27款身份、角色、顺序、当前平台映射、验证时间与证据；27项验证仍绑定当前内容且用户主动确认后才发布，不新增独立审批页或双人审批。
- [x] 确认映射验证不按天数自动过期；身份关键映射字段、实际稳定身份或验证合同变化时失效，角色、排序、Session及未证明身份变化的单次网络或认证失败不撤销既有有效验证。
- [x] 确认批量映射验证默认只重试失败项；暂时网络或超时每次操作最多自动重试1次，认证失败等Session更新，身份错误先修映射；各次尝试完整重走门禁并保留历史，不跨尝试拼接或创建巡检批次。
- [x] 确认首个范围发布后只由下一个10:00计划事件启动正式基线初始化；当前单平台以原批次27项可靠成功、逻辑证据27/27、15分钟内完成和10:30全套产物及真实前端闭环作为首跑验收门，部分失败不重复整批且不算通过。
- [x] 确认测试环境增加“手动运行测试”按钮，使用隔离测试数据库和三组确定性虚拟数据复用正式处理链，验证网页与XLSX红绿、TXT纯文本、汇报与证据规则；该能力不访问平台或进入正式批次、基线和调度。ADR 0036记录生产隔离边界。
- [x] 整体检查通过：当前owner文档引用路径全部存在，CONTEXT中的109个领域术语无重复，ADR 0032至0036均为已接受，决策链表格列数一致，无冲突标记、异常韩文字符或未闭合代码围栏；正向合同检查确认当前单平台27、未来三平台门禁后才81、测试创建端点生产不注册、合成结果不进入基线、网页与XLSX有颜色而TXT纯文本，`git diff --check`通过。
**下一步**：另起功能实现任务，先建立口碑领域数据库基线、比较与结构化汇报核心，再用隔离合成适配器和“手动运行测试”打通列表、排名、证据、TXT与XLSX纵向闭环；该闭环通过后再接当前真实平台和10:00正式调度。
**边界**：当前只沉淀已确认的架构与术语；附件中的流程文字是需求输入，尚未逐项确认的数值和规则不视为实现合同。
**关联**：`CONTEXT.md`、`docs/adr/0032-separate-reputation-inspection-from-post-extraction.md`、`docs/adr/0033-preserve-full-reputation-page-and-derived-metric-region.md`、`docs/adr/0034-use-quarantined-two-phase-deletion-for-reputation-batches.md`、`docs/adr/0035-prioritize-official-reputation-runs-without-preemption.md`、`docs/adr/0036-isolate-synthetic-reputation-test-runs.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/reputation-inspection.md`

---

## 2026-08-24 — 负面截图使用完整原图底图
**总目标**：保留现有帖子去重、卡片边界恢复和负面红框逻辑，只把关联截图成果底图从卡片裁片拼接改为完整原始页面证据。
**状态**：✅ v4 渲染、版本合同、真实批次重建、像素级验证和前后端检查均已完成；目标 Linux 发布门禁保持未决。
**干到哪里了**：
- [x] 渲染器升级为 `v4-full-page-evidence-background`：按关联结果首次引用证据的稳定顺序，一张原始物理分页生成一张同宽高成果页；不裁切、缩放、重排或增加标题栏，既有 5 px 负面红框和卡片边界恢复不变。
- [x] 渲染前校验原图 SHA-256；成果清单升级为 v2 并记录来源证据、来源批次、物理页码、捕获时间和原图哈希。渲染器及页面身份进入输入哈希，旧成果保留，新规则生成不可变新版本。
- [x] 新增完整原页、多物理页、框外像素一致和原图不变回归；全部 111 项后端测试、Ruff、Python 编译、`pip check`、后端 wheel、前端 TypeScript 检查、生产构建（2465 modules）和 `git diff --check` 通过。
- [x] 重建前以 SQLite 在线备份保存 `artifacts/runtime/full-page-negative-screenshots-20260824-153130/threadsnap-before-full-page-rebuild.db`，SHA-256 `13f866f3eb54b84e1a80f433c41bcb2253080dd67d9ab6c85c827f9ad7be94e4`。
- [x] 最新批次 `20260824-150229-001` 的 14/14 成果组均从 v1 升为 v2，覆盖 420 条帖子、85 个负面框和 14 张完整原页；页面均宽 1440 px、高 9,752～12,576 px。逐页重新生成期望图后确认成果像素精确等于“完整原图 + 现有红框”，原图哈希全部保持不变。
- [x] 脱敏验证记录为 `artifacts/runtime/full-page-negative-screenshots-20260824-153130/verification.json`，SHA-256 `1db794669d7a8c93322582fb432553c76d6cdb88ea85453c0382ff40873df8e9`；wheel SHA-256 `31454c2bcc8ee145575670ab66f4cbe5f01650a4ef9a1f55155a3ace1b27f214`，后端与 Vite 代理健康均为 `ok`。
**下一步**：在目标 CentOS Stream 10 离线环境复跑最大原页编码/解码、连续查看、成果包、备份恢复和 Pillow wheel 门禁；v3 的 30,000 px 裁片候选值不沿用为当前规则。
**边界**：一个成果组仍只有一个逻辑当前成果；被当前去重结果引用的每张物理分页各形成一张完整成果页。没有页面证据的历史“成功但零条”任务继续使用兼容占位，真实原页存在时不进入占位路径。
**关联**：`src/threadsnap/screenshots.py`、`tests/test_screenshots.py`、`docs/adr/0031-render-negative-artifacts-on-full-page-evidence.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/circle-screenshot-artifacts.md`

---

## 2026-08-24 — 舆情假运行状态防护
**总目标**：消除模型返回后解析、结构修正或落库异常被 Worker 静默吞掉而永久停留“分析中”的状态，并限制流式请求和自动恢复的调用放大。
**状态**：✅ 异常终态、DeepSeek 绝对总时限、有界孤儿恢复、owner 文档、完整验证和现场单条恢复均已完成。
**干到哪里了**：
- [x] 现场批次 `20260824-142552-001` 的 420 条提取全部成功，419 条舆情完成、1 条长期 `analysis_running`；目标分析没有结束时间、错误、用量、请求 ID 或原始响应，进程 32 个舆情线程均空闲。证据只能确认异常已逸出且被循环静默吞掉，不能把具体根因确定为提供方格式；既有格式纠正本身最多执行一次。
- [x] Worker 在领取事务内登记线程持有的分析 ID；解析、纠正、结果保存等阶段的未预期异常统一记录堆栈并持久化为 `analysis_failed / ANALYSIS_INTERNAL_ERROR`，不再遗留假运行状态。
- [x] DeepSeek 保留 30 秒逐块读取超时并新增 60 秒单次绝对总时限，持续心跳或碎片流也不能无限延长请求；网络重试、截断重试和合同纠正的既有上限保持不变。
- [x] 五秒看门狗只处理数据库为运行中但已无本进程线程持有的孤儿任务；真实活跃请求不重排，孤儿首次恢复排队、重复失联转为失败，避免重复付费无限放大。
- [x] 新增回归验证绝对总时限、后处理 `KeyError` 明确落库、活跃任务不被看门狗误收、进程内与重启恢复共用一次上限；完整 111 项自动化测试、Ruff、Python 编译、`pip check`、`git diff --check` 和后端 wheel 构建通过。
- [x] 脱敏验证记录为 `artifacts/runtime/sentiment-running-watchdog-20260824/verification.json`，SHA-256 `9ae660cc0ad1231df9cfda76eeeb87cc38e4ecff1492a50bcd4b0eefe8407094`；wheel SHA-256 为 `7c9faaa66e9872d8fdea4c019719189b09fdc4cab63cff1f7a93659df7af3518`，两者均位于 Git 忽略目录。
- [x] 经使用者明确要求，先用 SQLite 在线备份保存 `artifacts/runtime/rerun-t9l-20260824-145608/threadsnap-before-rerun.db`（SHA-256 `006eb5b055aaff30ea9ae15704bbfe83f21ba392d43972a3fba531a82fe6734b`），再重启当前 `main` 后端；唯一孤儿分析以 1 次 DeepSeek 调用完成，`retry_count=0`、无格式纠正、无传输重试、无本地结构恢复，耗时 2468 毫秒、总计 1583 Token，结果为 `negative / product_complaint`，目标批次最终 420/420 `analysis_completed`。
- [x] 重跑脱敏证据为 `artifacts/runtime/rerun-t9l-20260824-145608/verification.json`，SHA-256 `8084fa58658b5ae6dcc549c8a0c260e62c107e78c1ac9e26bdebbc5a32adafdf`；后端和 Vite 代理健康均为 `ok`，前端代理详情已返回 AI 负面结果且无错误码。
**下一步**：无当前代码或运行状态缺口；继续观察后续批次是否出现 `ANALYSIS_INTERNAL_ERROR` 或重复孤儿标记，以真实堆栈区分解析、结构修正和落库异常。
**边界**：60 秒是单次 DeepSeek 请求上限，不是整条任务含退避和重试的总时长；看门狗不抢占仍被执行线程持有的请求，也不把未证实的现场异常伪装成已确认的 JSON 格式问题。
**关联**：`src/threadsnap/sentiment.py`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`、`artifacts/runtime/sentiment-stuck-20260824-142552-pyspy.txt`

---

## 2026-08-24 — 批次永久删除进行中反馈
**总目标**：消除永久删除执行数据库级联、文件清理和关联截图成果重建期间页面无反馈的假死观感。
**状态**：✅ 同步删除链路、详情页加载反馈、文档和真实页面状态验证均已完成；正式业务数据未删除。
**干到哪里了**：
- [x] 确认删除请求会依次收集页面证据路径、事务级删除批次及级联数据、清理导出与原始证据文件，并对仍有其他贡献批次的截图成果组同步重建；前端此前立即关闭确认框且只在全部完成后导航，因而长时间停留在原详情页且没有可见状态。
- [x] 永久删除确认 Dialog 在请求期间保持打开，标题、说明、状态行和确认按钮统一切换为“正在永久删除”，同时禁用取消、重复提交和 Escape 关闭；失败后保留 Dialog 并恢复操作，成功后沿原路径刷新并返回列表。
- [x] 视觉反馈复用现有 AlertDialog、语义色、边框、间距与 `LoaderCircle`，仅使用克制的旋转状态并支持减少动态效果，不增加全屏遮罩、伪进度条或新组件。
- [x] 前端 TypeScript 检查、生产构建（2465 modules）和 `git diff --check` 通过；真实页面拦截 DELETE 并延迟响应后确认 Dialog 标题、状态说明、双按钮禁用及 `aria-busy=true`，截图为 `artifacts/runtime/delete-run-loading-20260824/delete-pending.png`，SHA-256 `3c5566b8c31fa0f11c000ee65851fc2470815e01bca596ad38257e81930ad594`。验证后批次 `20260824-132715-001` 及其 420 条帖子仍在，未发送正式删除请求。
**下一步**：无当前代码缺口；进入 Git 自动收尾。
**边界**：本次只补足删除等待反馈，不改变后端同步删除、截图成果重建、事务和文件生命周期语义。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`src/threadsnap/app.py`、`src/threadsnap/screenshots.py`

---

## 2026-08-24 — DeepSeek Strict 尾部坏 JSON 通用结构门禁
**总目标**：纠正“提供方 Strict Tool 足以保证结构正确”的错误假设，用不改变模型语义的通用结构恢复覆盖同类 JSON 错误族，并恢复现场 420 条批次。
**状态**：✅ 根因、通用结构门禁、DeepSeek 独立超时、现场恢复、owner 文档、依赖许可和完整验证均已完成；目标批次 420/420 分析完成，全库持久分析失败为 0。
**干到哪里了**：
- [x] 批次 `20260824-132715-001` 使用 `deepseek-text-v5-strict-tool`，首轮完成的 419 条中 1 条失败（0.239%）；两次付费调用都正常结束并把字符串枚举输出为未加引号的 `non_negative`，均在第 70 列触发 `JSONDecodeError`。这不是旧 JSON Object 路径；提供方官方 Strict 声明与正式批量结果不一致，7/7 小样本能力探测不足以外推零尾部错误。当前没有证据把该错误归因于 32 并发。
- [x] DeepSeek 保留 Beta Strict Tool 和最小七字段作为上游降错层；标准解析失败后由固定 `json-repair==0.62.0` 生成通用候选，并在错误点附近枚举有界单结构字符编辑。候选相对原参数只允许增删 JSON 标点、引号、转义符和空白；中文、英文、数字等任一语义字符变化立即拒绝。
- [x] 候选必须唯一通过无重复字段、精确七字段、禁止额外字段、Pydantic 类型/枚举、业务关系、后端模态补齐和输入身份校验。缺引号、缺逗号、缺数组闭合、尾逗号、未加引号字段名均有回归覆盖；前后说明、重复字段、Schema 外枚举、缺字段、语义改写或多个有效结果仍进入一次有界模型纠正，不按错误形状继续加替换规则。
- [x] 可无损恢复的首个参数直接形成结果，保存原始坏参数和解析错误、标记 `locally_recovered=true`，不增加付费调用；成功持久化统一清除旧错误码和错误正文。DeepSeek 文字流读取边界从共享 600 秒独立收紧为 30 秒，千问多模态仍保持 600 秒。
- [x] 原失败分析 `01a0323d-8824-750c-9263-ec1e1df85250` 从保存的第二次坏参数无付费恢复为 `analysis_completed/non_negative`，两次失败审计继续保留；另一个超过 15 分钟的运行项在 Worker 重启后 2.438 秒完成。批次最终 420/420 `analysis_completed`，全库 962 完成、419 禁用、0 失败，14/14 截图成果组均 `ready`。
- [x] 恢复前使用 SQLite 在线备份生成 `artifacts/runtime/deepseek-strict-regression-20260824/threadsnap-before-general-recovery.db`，SHA-256 `4cb93860ed413f1409c8a713a96e57be417f1630dc1da45da0994186aeecc283`；`json-repair` 版本和 MIT 许可已进入项目依赖与第三方声明，后端 wheel 构建通过。
- [x] 全部 108 项后端测试、DeepSeek 专项 5 项、`ruff check src tests`、Python 编译、`pip check`、后端 wheel、前端 TypeScript 检查与生产构建（2465 modules）及 `git diff --check` 通过；后端与 Vite 代理健康均为 HTTP 200。脱敏验证记录为 `artifacts/runtime/deepseek-strict-regression-20260824/verification.json`，SHA-256 `5029ed2ba49199034e27453973a937d20c1b04afbd19fecb0d8432fb8464e55c`。
**下一步**：后续批次分别统计提供方原生合法、唯一无损本地恢复、模型关系纠正、传输重试和最终失败的分母；若出现无法在不改变语义字符的前提下形成唯一完整合同的错误，保留失败证据后按新的错误层级决策，不放宽为猜测式业务修正。
**边界**：本次新增的通用结构恢复只用于 DeepSeek Strict Tool 参数，千问和本地模型协议未改；它可以把可证明的纯结构问题从最终失败中吸收，但不伪造不可恢复的观点、分类或依据，也不承诺外部服务、网络、限流和内容策略永久零故障。
**关联**：`src/threadsnap/sentiment.py`、`pyproject.toml`、`THIRD_PARTY_NOTICES.md`、`tests/test_backend.py`、`docs/adr/0030-treat-provider-strict-output-as-untrusted.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-24 — DeepSeek 专属 Strict Tool 结构化输出
**总目标**：在不改变千问和本地模型协议的前提下，为 DeepSeek 采用生成侧严格结构约束、最小模型字段与后端确定性补齐，消除反复坏 JSON 导致的分析失败和重复 Token。
**状态**：✅ 模型专属适配、正式能力探测、真实失败恢复、owner 文档和完整验证均已完成；当前目标批次 60/60 分析完成，数据库持久分析失败为 0。
**干到哪里了**：
- [x] 正式配置 `https://api.deepseek.com` / `deepseek-v4-flash` 的能力探测确认普通 `response_format=json_schema` 返回 HTTP 400；Beta Strict Tool 会拒绝非法 Schema，7/7 次有效调用通过，覆盖非流式、流式和完整舆情字段。探测记录为 `artifacts/runtime/deepseek-strict-schema-probe-20260824/result.json`，SHA-256 `d18c5fa13061449087b1cf2851861e4188f1417426f03ab479955691c17da074`。
- [x] 结构化输出按模型独立适配：千问继续 JSON Object 与完整多模态合同，本地继续 UIE-Senta/UTC 管线；只有 DeepSeek 改走 `/beta/chat/completions`、`strict=true` 的单一强制函数和 `finish_reason=tool_calls`，不支持该协议的代理在连接测试阶段失败且不静默降级。
- [x] DeepSeek 原生参数收缩为相关性、命中对象、情感、分类、文字依据和总结七个语义字段；文字状态与图片/视频数量及 `not_requested` 由后端按实际输入补齐。Strict Tool 通过后仍执行 Pydantic 和业务关系校验，关系违约最多纠正一次，不进行第三次调用或永久重排队；旧单括号候选恢复退出 DeepSeek 当前生产路径。
- [x] 正式配置测试通过且 revision 保持 23，当前 DeepSeek 已启用、验证状态 `valid`、云端并发 32。原失败分析 `01a031e8-aa72-78b8-a2bf-12781c4e5f10` 使用新协议一次完成，`retry_count=0`、`locally_recovered=false`，原生响应无 `modalities` 且后端补齐完整统一合同；历史两次失败候选继续保留。
- [x] 现场批次 `20260824-115511-001` 复核为 60/60 `analysis_completed`、0 失败；全库为 542 条完成、419 条禁用、0 条失败。旧失败链两次共 2923 Token，新严格工具单次 1423 Token，该失败样本总 Token 减少约 51.3%。重试前数据库备份 SHA-256 为 `f45ba37167cd62cbfb302262ee00e0e709ba722f7ec3fa1fcf968c38d0afe574`。
- [x] 全部 107 项后端测试、DeepSeek 专项 7 项、`ruff check src tests`、Python 编译、`pip check`、前端 TypeScript 检查与生产构建（2465 modules）及 `git diff --check` 通过；后端和 Vite 代理健康均为 HTTP 200。脱敏验证记录为 `artifacts/runtime/deepseek-strict-tool-migration-20260824/verification.json`，SHA-256 `a3a33f9a289dd214f94513aef7bb145d05660667730b46ac602d1a5f345a8f82`。
**下一步**：后续真实 DeepSeek 批次按首次 Schema 拒绝、业务关系纠正、传输重试和最终失败分别统计；新增受控模型先做能力探测，再增加自己的 `output_mode`，不复用未经验证的 DeepSeek 协议。
**边界**：本次只改变 DeepSeek 输出传输与其最小原生合同，千问和本地模型行为保持原样；Strict Tool 消除已见的括号、层级、类型和额外字段错误，但网络、限流、内容策略和业务关系仍按现有有界失败语义留痕，不把“当前失败为 0”误写成外部服务永久零故障保证。
**关联**：`src/threadsnap/sentiment.py`、`tests/test_backend.py`、`docs/adr/0029-use-model-specific-strict-output-adapters.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-24 — 批次结果按实际来源精确多选
**总目标**：把批次详情中的圈子自由输入改为当前批次实际来源下拉，并明确区分最新回复与最新发布，支持多来源组合筛选。
**状态**：✅ 后端来源身份、三个结果接口、前端多选、文档、真实页面与完整验证均已完成。
**干到哪里了**：
- [x] 帖子接口从当前批次及关联补提的真实圈子任务生成来源选项；稳定键由平台、来源 ID、版块和列表顺序组成，同一来源的补提任务自动去重，来源改名后仍显示当前名称。
- [x] 批次详情移除“搜索圈子”自由输入，改为可搜索多选下拉；每项同时显示来源名称、圈子名称及“最新回复/最新发布”，未选择时表示全部来源，选择后写入可恢复的 URL 查询状态并回到第一页。
- [x] 帖子列表、批量复制和详情上一条/下一条统一接受重复 `source_key`，避免页面结果与复制、导航范围不一致；旧 `circle` 查询参数只保留接口兼容。
- [x] 自动化新增最新回复与最新发布双来源样本，覆盖来源选项、单选、多选、批量复制和导航；全部 105 项后端测试、Ruff、Python 编译、`pip check`、前端 TypeScript 检查、生产构建（2465 modules）及 `git diff --check` 通过。
- [x] 真实历史批次 `20260818-154456-001` 返回 11 个实际来源；页面确认“最新发布”选项、多选勾选、URL 恢复和两来源结果 70 条联动。截图为 `artifacts/runtime/run-source-multiselect-20260824/two-sources-selected.png`，SHA-256 `941fae5b7c9c3bebd8d67f1c0dbfc3ca4bc5cc65f13e856eaa13dfb9f8faacdc`；后端、Vite 页面和代理健康分别为 `ok`、HTTP 200、`ok`。
**下一步**：无当前代码缺口；后续新增平台仍只需按统一圈子任务契约提供平台、来源 ID、版块和列表顺序。
**边界**：来源选项只来自批次实际任务，不把配置页全部来源混入历史批次；不同列表顺序即使属于同一圈子也保持独立可选。
**关联**：`src/threadsnap/app.py`、`src/threadsnap/services.py`、`frontend/src/features/runs/run-detail-page.tsx`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`

---

## 2026-08-24 — AI 云端同时分析任务数与共享连接池
**总目标**：把固定 2 路的云端 AI 分析改成部署后可调的有界并发，并避免高并发下为每条请求重复建立 HTTP 客户端。
**状态**：✅ 数据库、后端 Worker、共享连接池、配置 API、前端控件、正式实例升级和验证均已完成；当前 DeepSeek 云端并发为 16。
**干到哪里了**：
- [x] `sentiment_configs.cloud_concurrency` 持久化为 1～64、默认 8；配置 API 返回范围，旧调用省略字段时保留当前值。单独修改并发不关闭分析、不使连接验证失效，也不增加判定对象版本。
- [x] Worker 在保存后动态增加任务槽位或暂停超出新值的槽位，后续领取立即服从新值，已发出的请求继续完成；本地 PaddleNLP 无论云端保存值为何仍固定一个推理槽位。
- [x] 云端请求改为复用线程安全的 `httpx.Client`，总连接与保活连接上限均为 64；全部槽位继续共享既有 429 冷却和有界重试。
- [x] “AI 舆情”页面增加“同时分析任务数”数值输入和 4/8/16/32 快捷值，明确显示 1～64 范围；真实页面显示当前值 16，浏览器控制台页面错误为 0，截图为 `artifacts/runtime/ai-concurrency-20260824/config-page.png`。
- [x] 正式数据库从 `a2d7e9f103bc` 升级到 `d4e8f6a1b203`，升级前备份 SHA-256 为 `9e28fd34b126ecc11e699ecf553ba4dae817868cbd2c5f949fa553bbc5485aec`；隔离数据库完成 `upgrade → downgrade → upgrade`，验证新增列和回退删除列。
- [x] 全部 104 项后端测试、`ruff check src tests`、Python 编译、`pip check`、前端 TypeScript 检查与生产构建（2465 modules）及 `git diff --check` 通过；后端和 Vite 代理健康均为 `ok`，当前数据库分析失败为 0。脱敏验证记录为 `artifacts/runtime/ai-concurrency-20260824/verification.json`，SHA-256 `abe040ec757ce0ad7ee0aa7cc0ca9680cbd7cfd0a0fdd6bbd1243c2a21ffc3fa`。
**下一步**：使用下一次同规模真实批次记录 16 并发下的 AI 总耗时、P50/P95、429、重试和最终失败分布；只有同分母证据表明仍有净收益时再提高到 32。
**边界**：本次没有为性能测试额外创建帖子或调用付费模型；64 是 ThreadSnap 单进程、线程 Worker 和 SQLite 架构的应用保护上限，不代表提供方账号上限，也不承诺耗时线性下降。
**关联**：`src/threadsnap/sentiment.py`、`src/threadsnap/migrations/versions/d4e8f6a1b203_add_sentiment_cloud_concurrency.py`、`frontend/src/features/config/config-page.tsx`、`docs/adr/0028-configure-bounded-sentiment-cloud-concurrency.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-24 — DeepSeek 重复坏 JSON 有界恢复与存量失败清零
**总目标**：消除 DeepSeek 正常结束流中稳定复现的单括号 JSON 错误，同时保证持续错误不会形成无限模型循环或无限用量。
**状态**：✅ 代码、真实存量恢复、截图成果重建与完整验证均已完成；当前数据库持久分析失败为 0。
**干到哪里了**：
- [x] 现场批次 `20260824-102857-001` 共 150 条，首次 JSON 语法错误 5 条；旧纠正链修复 3 条，另 2 条纠正响应与首次响应 SHA-256 完全相同，均为 `modalities` 少一个结束括号导致 `summary` 错层，不是网络截断。
- [x] 格式纠正不再把坏响应作为 assistant 历史提交，只保留原始输入、错误候选哈希、具体错误和合同；模型调用固定最多 2 次，不永久重排队。
- [x] DeepSeek 第二次仍为该实证错误时只构造 1 个补 `}` 候选；候选必须立即成为精确根字段对象并重新通过完整 Pydantic、字段关系和输入身份校验，不修改任何观点、枚举、数组、索引或哈希。
- [x] 自动化替身连续两次返回逐字相同坏 JSON，验证 Worker 只调用 2 次、保存 2 条失败候选、标记 `locally_recovered=true` 并形成完整结果；其他错误仍有界结束。
- [x] 数据库全部 3 条持久失败均通过同一只读门禁后原位恢复为 `analysis_completed`，保留原提示词版本、两次原始响应和错误审计；恢复前一致性备份为 `artifacts/runtime/sentiment-bounded-recovery-20260824/threadsnap-before-recovery.db`，SHA-256 `e19d64343c2f6c0378e43f458bb014b650d2025e46034d41c6f5ddc8d29958ba`，报告为同目录 `recovery-report.json`。
- [x] 当前批次 API 复核为 150/150 `analysis_completed`、0 失败；5/5 截图成果均 `ready`，150 条成果卡片、26 条负面。后端 `/health`、前端和 Vite `/health` 代理均为 HTTP 200。
- [x] 全部 102 项后端测试、`ruff check src tests`、Python 编译、`pip check`、前端 TypeScript/Vite 构建（2465 modules）及 `git diff --check` 通过。
**下一步**：后续真实批次继续统计首次违约、干净纠正成功和单候选恢复分母；只有出现新的可复核错误族时才单独设计窄规则，不扩展通用猜测式 JSON 修复。
**边界**：本次没有第三次模型调用、第二模型裁决或语义改写；单条任务模型调用上限为 2，本地结构候选上限为 1，候选不唯一或完整合同失败即明确结束。
**关联**：`src/threadsnap/sentiment.py`、`tests/test_backend.py`、`docs/adr/0027-use-bounded-clean-correction-and-structural-recovery.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-23 — 全页证据坐标漂移与整卡框选修复
**总目标**：消除全页截图阶段页面重排造成的渐进式卡片裁切，并确保负面红框覆盖完整帖子卡片。
**状态**：✅ 根因、采集预防、历史证据校正渲染、当前批次重建、视觉验收与完整验证均已完成。
**干到哪里了**：
- [x] 对批次 `01a02b0c-e9cf-7dd8-9bdc-354770f679d8` 的原图、DOM 矩形和成果裁片逐条比对：第 1 条纵向误差为 0px，第 16 条为 29px，第 30 条为 54px；DOM 卡片宽约 869.86px，而全页 PNG 中可见卡片宽为 880px。确认全页截图隐藏滚动条后可用宽度增加，引发图片网格逐卡重排和累计纵向漂移，不是舆情帖子关联错误。
- [x] 生产采集器在取最终矩形前主动进入无滚动条、无动画、无平滑滚动的页首布局，确认滚动位置归零并连续取得三次稳定布局，再读取卡片矩形和生成全页 PNG。
- [x] 渲染器升级为 `v3-pixel-aligned-card-boundaries`：从不可变原始证据像素恢复卡片可见边界，恢复失败时保守使用原矩形；校正只创建新成果版本，不改写原始截图、原清单或历史成果。
- [x] 当前批次两个圈子成果均由 v1 重建为 v2：QQ3 EV 为 30 条/4 条负面/1 片 `880×10985`，风云 A9L 为 30 条/6 条负面/1 片 `880×11527`；逐片和 ZIP SHA-256 全部复核一致。QQ3 首/中/末源裁片分别为 `[211,586,880,393]`、`[211,6336,880,372]`、`[211,11452,880,393]`。
- [x] 成果分片 URL 增加版本号与文件 SHA-256；保留长期不可变缓存的同时，每次重建都会产生新 URL，浏览器不会继续复用旧版本图片。
- [x] 原尺寸视觉核对确认此前标出的第 14～18 条及末页卡片标题、正文、媒体、时间与评论/点赞/收藏/分享栏均完整，4 个负面红框覆盖整卡；证据为 `artifacts/runtime/card-crop-diagnosis-20260823/current-v2-cards-14-18.png`、`current-v2-last-cards.png` 和 `current-run-v2-verification.json`。
- [x] 截图专项 8 项及全部 102 项后端测试通过；`ruff check src tests`、Python 编译、`pip check`、前端 TypeScript/Vite 构建（2465 modules）通过，后端 `/health` 与 Vite 代理 `/health` 均为 `ok`。全仓 Ruff 另发现 15 个既有 `artifacts/deployment/`、`poc/` 脚本导入排序问题，未改动无关范围。
**下一步**：目标 Linux 离线包仍按截图业务总账执行真实捕获、2000 卡片、Chromium 解码、备份恢复和回滚门禁；同时复核无滚动条冻结布局在目标 Chromium 上的矩形/PNG 一致性。
**边界**：舆情结论与帖子绑定继续使用平台帖子 ID，不依赖截图 OCR 或裁片位置；本次只修复证据坐标和成果边界。原始证据及历史成果版本保持不可变。
**关联**：`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/screenshots.py`、`tests/test_screenshots.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/circle-screenshot-artifacts.md`

---

## 2026-08-23 — 成果图移除逐卡溯源条
**总目标**：负面框选成果只保留原始帖子卡片像素和负面红框，不在图片中插入“贡献批次/捕获时间”信息条。
**状态**：✅ 渲染器、查看器摘要、测试、owner 文档、完整验证及现有成果重建均已完成。
**干到哪里了**：
- [x] 渲染器移除每张卡片顶部 28px 溯源条，分片高度与卡片坐标改按原始裁片真实高度计算；负面红框仍绘制在原始卡片边界内。
- [x] 逐卡 `run_number`、`captured_at` 继续保留在版本卡片审计项、成果 manifest 和 API，不修改数据库追溯能力。
- [x] 查看器顶部统一显示贡献批次数与捕获时间范围，不在长图内重复显示技术时间。
- [x] 定向渲染测试已验证首卡高度等于原始 350px、卡片顶部为原始像素、红框像素仍存在且逐卡审计字段不丢失。
- [x] 渲染器版本 `v2-original-card-pixels` 纳入输入哈希；像素规则变化会创建新版本，旧文件不覆盖。当前 QQ3 EV 成果已从 v1 重建为 v2，30 条、4 条负面、1 个分片，首卡由 419px 回归原始 391px；逐卡 `run_number`/`captured_at` 仍在 manifest。
- [x] 6 项截图专项和全部 100 项后端测试、Ruff、Python 编译、`pip check`、前端 TypeScript/Vite 构建（2465 modules）及 `git diff --check` 通过；后端、前端和 Vite 代理均为 HTTP 200。视觉核对确认卡片连续、红框保留、溯源条消失，证据为 `artifacts/runtime/remove-card-provenance-20260823/verification.json`，SHA-256 `50b6b903fc52136608ea1b9f469108359882e9cea51db0b5bec5ebc53e1bedd5`。
**下一步**：目标 Linux 离线包仍按截图业务总账的既有门禁执行 2000 卡片、备份恢复和回滚验证。
**边界**：原始页面证据和旧成果版本保持不可变；当前成果重建会生成新版本，ZIP 与逐文件哈希随新版本更新。
**关联**：`src/threadsnap/screenshots.py`、`tests/test_screenshots.py`、`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/lib/types.ts`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/circle-screenshot-artifacts.md`

---

## 2026-08-23 — 云端舆情严格输出合同与带错纠正
**总目标**：只有原生符合 ThreadSnap JSON Schema 的云端模型输出才能成为 AI 舆情结果；首次违约向同一模型反馈具体错误并要求按原合同重新生成一次。
**状态**：✅ 严格解析、单次带错纠正、文档同步、全量验证与本地运行实例重启均已完成。
**干到哪里了**：
- [x] 现场确认批次 `01a02aea-1c8e-7e12-bd08-7d176f47ce32` 为 29/30 完成；“OTA升级啦”两次返回完全相同的 473 字符响应，`summary` 错嵌入 `modalities` 且根对象未闭合，旧逻辑原样重发后仍失败。
- [x] 云端解析收紧为标准 JSON 对象和完整 Pydantic/媒体身份合同；Markdown 围栏、字段错层、同义枚举、字符串依据、一基索引、错误哈希及额外字段均不再本地改写。
- [x] DeepSeek 严格通过其根字段与 `modalities.text` 后，后端只追加未发送媒体的数量和 `not_requested`，不修改任何模型负责字段。
- [x] 首次格式违约保存 `MODEL_RESPONSE_ERROR` 审计，并使用“原输入 + 原始候选 + 具体校验错误 + 原合同”纠正一次；第二次重新执行全部校验，仍违约则失败。真实故障形状已由自动化替身复现并验证纠正闭环。
- [x] 千问与 DeepSeek 提示词版本分别升级为 `v3-strict-output` 与 `deepseek-text-v3-strict-output`；连接测试也执行严格 `{"ok":true}` 合同及一次带错纠正。
- [x] 100 项后端测试、Ruff、Python 编译、`pip check`、前端 TypeScript/Vite 生产构建（2465 modules）和 `git diff --check` 通过；后端已重启，后端 `/health`、前端 HTTP 和 Vite `/health` 代理均为 200。脱敏验证记录为 `artifacts/runtime/sentiment-strict-output-20260823/verification.json`，SHA-256 `a10e169294ed6a2ba40f159d9156d21cc7f39dd3f75546925bac9a01d4b834a3`。
**下一步**：无代码缺口；当前历史失败条目保持原始审计，可由使用者人工判定，或在另行确认一次外部模型用量后执行受控重跑。
**边界**：本次不自动重写历史分析结果，也不为当前失败条目静默发起新的付费请求；既有原始响应与历史归一化审计保持不变。
**关联**：`src/threadsnap/sentiment.py`、`src/threadsnap/poc/sentiment.py`、`tests/test_backend.py`、`tests/test_sentiment_poc.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-23 — 圈子页面证据与负面框选成果业务实现
**总目标**：把实际圈子来源的冻结页面证据、详情快照、当前有效舆情结论和单圈负面框选成果贯通为可追溯、可补提合并、可版本化的批次详情能力。
**状态**：✅ Windows 业务开发与本地验收完成；目标 CentOS Stream 10 的 2000 卡片、离线依赖、备份恢复和发布验收仍是上线门禁。
**干到哪里了**：
- [x] 新增两次 Alembic 迁移以及页面证据、页面卡片、稳定成果组、贡献关系、不可变版本、有序分片和版本卡片审计模型；原图、清单、成果、ZIP 和逐文件 SHA-256 统一进入 `data/screenshots/`。
- [x] 懂车帝生产采集器按任务精确来源 URL 使用资源开启的 Patchright 冻结同一 DOM，等待字体、全部卡片图片终态及连续三次布局/身份稳定，再一次取得清单、卡片矩形和原始全页 PNG；平台捕获通道串行，详情按平台内部并发有界批量执行并保持冻结顺序。
- [x] 重启续跑先校验原图和清单哈希并复用冻结候选；URL 清单不进入截图链路，历史批次显示 `not_collected`，最新回复与最新发布保持独立来源，正常零结果和错误零条分离。
- [x] 原批次与补提按关联链和来源身份形成稳定成果组；只拼接实际入库卡片，逐卡增加贡献批次和捕获时间，全部当前有效结论齐备后生成，负面整卡红框，超过 30,000 px 时按卡片边界无损分片并提供一个 ZIP。
- [x] 补提、人工修正、恢复 AI、后续 AI 结论变化和贡献批次删除都会生成或重建当前版本；历史版本保留，最后一个贡献删除后清理成果组；成果状态不改写提取与舆情状态。
- [x] 页面与内部 API 已提供成果组、原始证据、分片、打包下载和本地重建；批次详情复用“链接结果 / 页面截图”页签，支持成果/原图切换和接近全屏查看，提取列表显示紧凑截图摘要，没有新增顶级导航。
- [x] 生产采集器真实抓取最新回复与最新发布各 30 条，均为 30/30 唯一 ID，PNG 解码尺寸分别为 `1425×10575`、`1425×10680`；证据见 `artifacts/runtime/circle-screenshot-business-20260823/live-capture/verification.json`。
- [x] 隔离业务夹具真实渲染 3 条、2 条负面、1 个成果分片；页面卡片、成果弹层和原始全页切换均通过且图片完成解码，证据见 `artifacts/runtime/circle-screenshot-business-20260823/ui-verification.json` 与三张 UI PNG。
- [x] 100 项后端测试、Ruff、前端 TypeScript/Vite 生产构建、正式数据库迁移、后端 `/health` 和 Vite `/health` 代理均通过。
**下一步**：把当前代码、Pillow 12.3.0 wheel 和既有 R9/R10 同分母输入组装进目标 Linux 离线包，执行真实页面捕获、2000 卡片分片/解码、备份恢复、贡献删除清理和回滚；通过后冻结跨平台单片上限并发布。
**边界**：30,000 px 仍是 Windows 已验证候选上限；本次真实抓取只生成 Git 忽略的验收证据，没有创建业务批次或发送舆情模型请求。历史批次不补拍，现有业务快照保持不变。
**关联**：`src/threadsnap/screenshots.py`、`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/worker.py`、`src/threadsnap/app.py`、`frontend/src/features/runs/run-detail-page.tsx`、`tests/test_screenshots.py`、`docs/chains/circle-screenshot-artifacts.md`

---

## 2026-08-22 — 圈子页面证据 Windows PoC
**总目标**：以真实圈子页面和 2000 卡片等价负载关闭页面清单、原始证据、补提成果、版本、分片及备份恢复的 Windows 可行性门禁。
**状态**：✅ Windows R1～R10 当前范围全部通过；目标 Linux R9/R10 尚待同分母复测，业务实现尚未开始。
**干到哪里了**：
- [x] 真实最新回复与最新发布各取得 30 条完整页面证据，清单、唯一帖子 ID、裁片和详情输入均为 30/30 一致；两类来源分别生成原始全页截图，待加载和破图均为 0。
- [x] 真实最新回复第 1、2 页合计 60 个不同帖子，跨页重复 0，详情成功与 ID 匹配 60/60。
- [x] 受控失败补位保留 2 条原始诊断并从后续候选补足 50；媒体门禁准确区分已加载、平台占位、待加载和破图。
- [x] 隔离成果组验证 `40 → 47 → 50`，人工修正后负面数 `8 → 9`，删除 7 条贡献后重建为 43；零负面、明确零结果和错误零条状态分离。
- [x] 2000 卡片生成 25 个无损分片，最大 29,988 px，0 切卡、0 遗漏；编码 20.683 s，渲染峰值 253,800,448 bytes，Chromium 解码 25/25 一致。
- [x] 隔离备份恢复逐文件哈希不一致数为 0；成果生成前后原始页面证据哈希保持不变。
- [x] 结果、分母、环境、哈希和 Git 外入口已写入 `docs/research/circle-screenshot-poc-results.md`；失败轮按 PoC 规则保留诊断。
**下一步**：把同一 R9/R10 输入和依赖打包到目标 CentOS Stream 10，复测 2000 卡片分片、Chromium 解码、备份恢复和清理；两端通过后冻结跨平台单片上限，再进入数据库迁移和业务实现。
**边界**：30,000 px 当前只是 Windows 候选上限；本轮没有修改业务代码、正式数据库或现有批次，没有把 Session、Cookie、原始截图和本地成果包提交 Git。
**关联**：`docs/research/circle-screenshot-poc-plan.md`、`docs/research/circle-screenshot-poc-results.md`、`docs/chains/circle-screenshot-artifacts.md`、`artifacts/poc/results/circle-screenshot/windows-r1-r2-20260822T222556+0800/`、`artifacts/poc/results/circle-screenshot/windows-r3-20260822T222817+0800/`、`artifacts/poc/results/circle-screenshot/windows-r4-r10-20260822T223232+0800/`

---

## 2026-08-22 — 圈子页面证据与关联截图成果设计
**总目标**：把实际圈子列表任务的页面证据、帖子字段、舆情结果和负面框选成果统一为可追溯、可补提合并、可版本化的批次详情能力。
**状态**：✅ 需求压力测试、领域词汇、产品与技术合同、ADR、跨工作线口径和 PoC 门禁已完成；业务实现尚未开始。
**干到哪里了**：
- [x] 明确截图数量跟随批次内每个实际圈子来源的有效目标与冻结页面清单，不采用固定 30 条；只为本次提交的最新回复或最新发布来源生成，URL 清单不生成。
- [x] 明确同一受控浏览器读取同时产出圈子页面清单与原始全页证据，随后与详情采集流水化；原始证据要求帖子卡片文字、媒体和布局完整，平台原生占位可接受，待加载、空白或破图不接受。
- [x] 明确关联补提批次按稳定“关联圈子成果组”聚合；最终成果按实际持久化帖子去重和稳定排序，以原始证据中的卡片像素裁剪合成，并披露各贡献批次和采集时间。
- [x] 明确直接复用现有当前有效舆情结果，全部证据化帖子取得有效结论后才生成；负面框选整张卡片，零负面和正常零结果仍产生成果，提取、舆情和截图成果保持独立状态。
- [x] 明确成果采用不可变版本；人工结论变化、AI 结果恢复、补提和贡献批次删除都会生成新版本。前端只展示当前版本，历史文件与哈希保留；最后一个贡献批次删除后清理成果组文件。
- [x] 明确普通规模交付单张 PNG，超过实测门限时按帖子卡片边界无损分片；前端连续查看并提供一个打包下载，保持每圈最高 2000 条的既有提取上限。
- [x] 新增 ADR 0026、专属链档和 PoC 计划，并同步领域词汇、产品设计、技术路线、首个平台交付链、舆情链和文档索引。
**下一步**：按 `docs/research/circle-screenshot-poc-plan.md` 先执行真实最新回复/最新发布页面的同步清单与原始证据 PoC，再以 2000 条等价卡片负载确定分片高度、渲染内存上限和浏览器通道资源权重；门禁通过后进入数据库迁移、后端流水线和批次详情页实现。
**边界**：本条只完成设计和可执行 PoC 计划，没有修改业务代码、数据库、现有批次或平台数据；历史批次不回填旧截图，后续补提只能覆盖新取得证据的帖子并显式披露历史缺口。
**关联**：`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/adr/0026-use-synchronized-page-evidence-and-related-screenshot-artifacts.md`、`docs/chains/circle-screenshot-artifacts.md`、`docs/chains/first-platform-delivery.md`、`docs/chains/sentiment-analysis.md`、`docs/research/circle-screenshot-poc-plan.md`

---

## 2026-08-21 — DeepSeek 文字状态合同修复
**总目标**：让 DeepSeek 原始响应按 ThreadSnap 统一文字状态枚举返回，并避免已完成分析因同义状态值整批失败。
**状态**：✅ 提示词合同、兼容归一化、自动化检查和30条真实重跑均已完成。
**干到哪里了**：
- [x] 现场核对批次 `20260821-142151-001` 的 30 条 DeepSeek 分析全部为 `MODEL_RESPONSE_ERROR`；原始 JSON 均可解析，其中 28 条 `modalities.text.status=analyzed`、2 条为 `completed`，根因是 JSON Object 只保证 JSON 语法，而旧提示词没有给出文字状态枚举。
- [x] DeepSeek 提示词升级为 `deepseek-text-v2`，明确只允许 `absent`、`processed`、`unprocessed`，禁止已观察到的同义值并附完整 JSON 形状示例。
- [x] 解析层对 `analyzed` / `completed` 这两个明确表示“分析已完成”的同义值唯一归一为 `processed`，同时继续原样保存提供方响应；相关性、情感、类型、总结和依据不改写。
- [x] 4 条定向测试与 Ruff 已通过，覆盖提示词枚举、JSON 示例、两个真实同义值及既有文字媒体补全路径。
- [x] 94 项后端测试、Ruff、compileall、pip check 和 `git diff --check` 全部通过。
- [x] 先备份数据库和30条原失败审计，再只重放“瑞虎8油耗”一条；DeepSeek 原始 JSON 已按 `deepseek-text-v2` 返回 `modalities.text.status=processed`，规范化结果同为 `processed`，任务为 `analysis_completed`。证据为 `artifacts/runtime/deepseek-text-status-contract-20260821/single-live-verification.json`，SHA-256 `183dab4de4200adcd9fba2f99263919fab261b4c0b107110a1405b2acb86c48d`。
- [x] 用户明确要求后，先再次备份30条当前状态，再将同批次30条全部重排；最终30/30 `analysis_completed`，提示词版本均为 `deepseek-text-v2`，模型原始与规范化 `modalities.text.status` 均为30/30 `processed`，0复用、0失败。请求耗时最小782 ms、P50 1648 ms、P95 2078 ms、最大2359 ms；总用量24069 Token。证据为 `artifacts/runtime/deepseek-rerun-all-20260821-144939/final-verification.json`，SHA-256 `965ed79f9d57e7f60e129a33b07b269c4e5a76231fa5251bd9d5e11a370011be`。
**下一步**：无。
**边界**：不增加第二次付费重试；仅修复 DeepSeek 纯文字路径，千问多模态和本地 Nano 合同保持不变；两次重跑前的原始响应与数据库备份均保存在被 Git 忽略的 runtime artifact。
**关联**：`src/threadsnap/sentiment.py`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-21 — 任务级失败批次手动补提修复
**总目标**：让“部分成功/失败”批次在任务级异常未生成逐 URL 失败记录时，仍能按真实缺口执行“重新提取失败项”。
**状态**：✅ 任务级失败补提、跨批次去重和历史批次验证均已完成。
**干到哪里了**：
- [x] 现场确认批次 `20260821-134921-001` 计划 420 条、已保存 230 条、实际缺口 190 条；12 个非成功任务中有 1 个已达 30/30，其余 11 个任务应补提 190 条，但检查点 `failed_urls` 均为空。
- [x] 补提计划保留明确失败 URL 路径；无逐 URL 失败记录时，URL 清单从原输入排除已保存 URL，圈子任务按目标缺口继续发现并携带已保存帖子 ID 跳过重复；已完成目标的异常任务不再进入补提。
- [x] Worker 分开计算“本补提任务已保存帖子”和“原批次跨任务跳过帖子”，避免跳过集合被误计为新任务完成量。
- [x] 3 条目标回归测试通过，覆盖原逐 URL 重试、圈子任务级失败和 URL 清单任务级失败；实时数据库备份上的真实用例生成 11 个补提任务、计划数 190，证据为 `artifacts/runtime/manual-retry-task-fallback-20260821/verification.json`。
- [x] 92 项后端测试、Ruff、compileall、pip check 和 `git diff --check` 通过；后端已以 PID `89472` 重启，后端 `/health` 与前端 `5173` 代理 `/health` 均为 `ok`，原批次仍保持 `partial_success`、230/420。
**下一步**：无；用户可在原批次点击“重新提取失败项”创建 11 个圈子、合计 190 条的关联补提批次。
**边界**：隔离验证只在 SQLite 备份上创建补提批次，没有修改现有业务数据库，也没有向平台发出采集请求；原批次快照保持不变。
**关联**：`src/threadsnap/services.py`、`src/threadsnap/worker.py`、`tests/test_backend.py`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`

---

## 2026-08-21 — 本地舆情推理期间页面响应性修复
**总目标**：消除本地 PaddleNLP 初始化/推理挤占页面 API、SQLite 短写竞争以及运行批次首次空响应长期停留造成的列表加载缓慢和假空状态。
**状态**：✅ CPU 预算、SQLite 争用、数据版本刷新和页面加载反馈均已完成。
**干到哪里了**：
- [x] 现场证据确认 PaddleNLP 默认按主机一半核心数创建 CPU 推理线程；同一时段舆情配置写入出现 `sqlite3.OperationalError: database is locked`，批次详情首次取得 0 条后又缺少运行期刷新。
- [x] UIE-Senta 与 UTC Taskflow 继续复用同一专用 Predictor 线程，但各自显式限制为 2 个 CPU 数学线程；环境只允许在 1～4 范围内覆盖。
- [x] SQLite 保持 WAL，增加 15 秒有界 `busy_timeout`；短写竞争等待释放，达到边界时页面 API 返回 `503 DATABASE_BUSY` 与 `Retry-After: 1`。
- [x] 帖子查询键纳入批次 `summary_version`，运行批次即使首屏为空也每 3 秒刷新；批次和帖子读取超过 20 秒后结束加载并显示中文错误与重试，不再把待响应状态显示为 0 条。
- [x] 2 线程真实组合基准：本地模型验证 5.25 秒，同时 23 次批次列表读取 23/23 成功，P50 19.6 ms、P95 81.5 ms、最大 1.357 s；证据为 `artifacts/runtime/local-sentiment-responsiveness-20260821/benchmark.json`，SHA-256 `7ecb7d9a4395d2fbcaeb343472157bed7071f9cd79a77908a58a0f9dc82542ca`。
- [x] 90 项后端测试、Ruff、compileall、pip check、前端 TypeScript 与生产构建、`git diff --check` 均通过；真实浏览器确认列表显示 20 个批次、详情显示 230 条/5 页且控制台 0 错误。
- [x] 最新后端已在 `127.0.0.1:8000` 重启，后端 `/health`、前端 `5173` 代理 `/health` 均为 HTTP 200，代理批次列表 20 条、实测 39.1 ms。
**下一步**：无；进入 Git 自动收尾。
**边界**：仍采用已接受的单进程、单 Predictor 线程和 SQLite 架构；本次不增加第二后端、消息中间件或用户可见性能配置。
**关联**：`src/threadsnap/local_sentiment.py`、`src/threadsnap/db.py`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`、`docs/adr/0024-add-local-text-sentiment-option.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-21 — DeepSeek 云端纯文字舆情选项
**总目标**：在既有舆情模型下拉栏增加 DeepSeek 云端文字分析，同时保持千问多模态、本地轻量模型和人工结论优先级不变。
**状态**：✅ DeepSeek 独立连接、纯文字请求、结果归一化和配置界面均已实现。
**干到哪里了**：
- [x] 模型下拉新增 `deepseek-v4-flash`；选择后使用独立的 DeepSeek Base URL/API Key，不覆盖既有千问连接，密钥仍只进入加密存储。
- [x] DeepSeek 请求只包含判定对象、标题和正文，固定关闭 thinking，启用 JSON Object、流式响应及流式用量；不解析或发送图片、视频 URL。
- [x] 后端把未提交给模型的实际图片、视频画面和视频音频统一补为 `not_requested`，保留模型原始文字结论、中文总结、依据、用量和请求 ID。
- [x] 输入指纹排除媒体变化；DeepSeek 继续复用云端 Worker、有界重试、失败审计、筛选和人工修正规则。
- [x] Alembic 新迁移完成 `head → ab4d92e7c601 → head` 往返，验证既有千问连接保持不变；证据位于 `artifacts/runtime/deepseek-migration-20260821-134215/`。
- [x] 87 项后端测试、Ruff、compileall、pip check、前端 TypeScript 检查与生产构建、`git diff --check` 均通过。
- [x] 真实页面确认下拉栏同时展示千问、DeepSeek 和本地 Nano；切换 DeepSeek 后显示默认 `https://api.deepseek.com`、纯文字边界和独立 Key 输入，无控制台错误；后端与 Vite 代理 `/health` 为 HTTP 200。
**下一步**：部署环境填入 DeepSeek Key 后执行一次显式连接测试，再由用户决定是否启用；本次不消耗真实 DeepSeek 额度。
**边界**：DeepSeek 路径只分析标题和正文，详情媒体仍独立展示；本次不新增自由模型名、余额查询、额外 Worker 或媒体代理。
**关联**：`docs/adr/0025-add-deepseek-cloud-text-sentiment-option.md`、`src/threadsnap/sentiment.py`、`src/threadsnap/models.py`、`src/threadsnap/migrations/versions/c6f1e2a93b47_deepseek_sentiment_connection.py`、`frontend/src/features/config/config-page.tsx`、`tests/test_backend.py`

---

## 2026-08-21 — 本地舆情 Predictor 线程归属修复
**总目标**：修复本地轻量模型在配置测试成功后由后台 Worker 分析时全批次进入“分析暂停”的问题，并恢复原暂停队列。
**状态**：✅ Predictor 线程归属和失效期间任务状态均已修复，原批次 30 条全部恢复完成。
**干到哪里了**：
- [x] 现场确认批次 `20260821-111121-001` 的 30 条任务均为 `analysis_paused`，配置被自动关闭并标记为 `invalid`，首个真实错误为 `本地文字模型执行失败：'paddle.base.libpaddle.DenseTensor' object has no attribute 'numpy'`。
- [x] 同一模型目录在独立进程内可完成连接验证和负面样本分析，排除模型文件缺失、内容错误和外部额度问题；根因是配置测试在线程 A 创建并缓存 Paddle Predictor，后台 Worker 在线程 B 复用，而 Predictor 不能跨创建线程稳定使用。
- [x] `LocalSentimentAnalyzer` 新增单消费者专用推理线程，配置测试、模型创建和 Worker 分析统一投递到该线程；应用关闭时先停止 Worker，再关闭推理线程。
- [x] 新增调用线程不同但 Predictor 执行线程唯一的回归测试，目标测试与 Ruff 已通过。
- [x] 运行配置失效期间继续入库的新任务由 `analysis_disabled` 修正为 `analysis_paused`，从而在重新测试并启用后与既有暂停任务一并恢复；用户主动关闭产生的禁用任务仍不回刷。
- [x] 使用真实已下载 Paddle 模型验证“主调用线程测试 + 另一调用线程分析”成功，得到 `negative`、媒体 `not_requested`，未再出现 `DenseTensor.numpy` 错误。
- [x] 后端重新测试得到 `valid` 并启用本地模型；对当次异常遗留的 20 条误标禁用任务，在精确限定批次、模型和 revision 后恢复排队，修复前数据库备份为 `artifacts/runtime/local-sentiment-thread-recovery-20260821-112227/threadsnap-before-recovery.db`（SHA-256 `0c4b05516bb14ec61dc44866fc89a92f2a79681903b2cfa6abb1630cae3705f4`）。
- [x] 批次 `20260821-111121-001` 最终为 30/30 `analysis_completed`、0 暂停、0 禁用、0 失败；配置 revision 18 为 `enabled=true`、`validation_status=valid`，后端及前端代理 `/health` 均为 `ok`。
- [x] 84 项后端测试、Ruff 和 compileall 通过。
**下一步**：无；进入 Git 自动收尾。
**边界**：本地模型仍为单路串行推理；本次不改变云端模型两个消费者的并发策略，也不扩大舆情任务范围。
**关联**：`src/threadsnap/local_sentiment.py`、`src/threadsnap/app.py`、`tests/test_local_sentiment.py`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`、`docs/adr/0024-add-local-text-sentiment-option.md`

---

## 2026-08-21 — 本地轻量文字舆情模型选项
**总目标**：把无需外部 API、只分析标题与正文的轻量模型作为受控选项接入现有舆情闭环，并自动排除图片和视频分析。
**状态**：✅ 本地轻量文字选项、离线部署链路和界面已实现并通过必要验证。
**干到哪里了**：
- [x] 模型下拉新增 `paddlenlp-local-text-nano-v1`；选择后隐藏云端 URL/Key，保留原加密连接配置，并要求本地模型显式测试成功后才能启用。
- [x] 本地管线使用 UIE-Senta-Nano 抽取配置对象、观点和依据，UTC-Nano 执行情感与负面类型分类；保存两个模型原生 JSON，并生成统一结果与中文模板总结。
- [x] 本地任务只读取标题和正文，不调用云端 API，不解析媒体播放地址，图片/视频覆盖统一为 `not_requested`，用量记录为零计费 Token。
- [x] 详情页用中文展示本地模型与“未参与分析”，不展示空的媒体依据区；人工判定、筛选和既有状态优先级保持不变。
- [x] Linux 完整离线包加入已转换模型的组装、安装和离线推理验证，目标服务器不从模型仓库下载。
- [x] 项目虚拟环境使用 PaddlePaddle 3.3.1、PaddleNLP 3.0.0b4 和 aistudio-sdk 0.1.3 完成真实正负面推理；两条样本分别得到 `negative` / `non_negative`，媒体均为 `not_requested`，原始结果同时包含 UIE、UTC 情感与 UTC 分类输出。
- [x] 83 项后端测试、Ruff、compileall、pip check、前端 TypeScript 检查与生产构建、`git diff --check` 均通过。
**下一步**：无；进入 Git 自动收尾。
**边界**：本地 Nano 不是生成式大模型；总结为固定模板，别名、隐含指代和复杂语境能力弱于云端 Omni Plus；本地推理进程内串行。
**关联**：`docs/adr/0024-add-local-text-sentiment-option.md`、`src/threadsnap/local_sentiment.py`、`src/threadsnap/sentiment.py`、`frontend/src/features/config/config-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`、`deploy/linux/`

---

## 2026-08-21 — 人工判定与人工修正文案区分
**总目标**：让详情入口准确表达首次给出人工结论和修改已有结论两种不同操作。
**状态**：✅ 动态文案已实现。
**干到哪里了**：
- [x] 没有有效舆情结论时，详情按钮、Dialog 标题、备注字段、失败提示和保存按钮统一显示“人工判定”。
- [x] 已有 AI、继承人工或人工结论时，同一组文案统一显示“人工修正”；后端权限和追加修订规则保持不变。
- [x] 前端类型检查与生产构建通过；真实禁用帖子验证“人工判定”入口和 Dialog 三处文案，已有人工结论帖子验证“人工修正”入口和 Dialog 三处文案，均符合预期。
**下一步**：无；进入 Git 收尾。
**边界**：只调整操作语义，不新增状态、接口或数据库字段。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-21 — 舆情截断响应单次自动重试
**总目标**：让模型流在 JSON 完成前中断时自动恢复一次，同时控制付费请求放大并保留首次失败证据。
**状态**：✅ 截断识别、单次重试、失败审计和终态分类已实现。
**干到哪里了**：
- [x] SSE 聚合显式记录 `[DONE]` 和结束原因；缺少正常结束标志、以长度限制结束，或 JSON 命中未闭合字符串/容器尾部缺失时，Worker 延迟一秒完整重请求一次。
- [x] 新增 `attempt_failures` 持久字段和迁移，保存首次失败的请求 ID、用量、耗时、原始响应和原因；第二次仍截断时以 `MODEL_STREAM_INCOMPLETE` 结束。
- [x] 普通结构校验和媒体部分结果继续不重试；并发2、429共享冷却和其他传输重试规则不变。
- [x] 10 项针对性测试通过，覆盖首次截断后成功、仅调用两次、审计留存、缺少 `[DONE]` 及截断/普通畸形区分；Ruff、编译和 `git diff --check` 通过。
- [x] SQLite 迁移完成 `head → f2a9c41d7e30 → head` 往返，当前业务库版本为 `ab4d92e7c601` 且字段存在；后端重启后 `/health` 返回 HTTP 200。
**下一步**：无；进入 Git 收尾。
**边界**：截断重试最多一次且必须从完整输入重新请求，不能续写缺失 JSON；不增加前端重新分析按钮。
**关联**：`src/threadsnap/sentiment.py`、`src/threadsnap/poc/sentiment.py`、`src/threadsnap/models.py`、`src/threadsnap/migrations/versions/ab4d92e7c601_sentiment_attempt_failures.py`、`tests/test_backend.py`、`tests/test_sentiment_poc.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-20 — 视频连续播放地址优先级修正
**总目标**：解决详情视频在首段缓冲末尾持续等待的问题，同时保持浏览器 URL 直连和后端不代理媒体的边界。
**状态**：✅ 播放地址选择已修正；按使用者要求不执行测试。
**干到哪里了**：
- [x] 现场确认最高码率主地址原始带宽和 MP4 结构正常，但主 CDN 缺少 `Accept-Ranges`，真实 Chrome 在约 22 秒缓冲边界停住；同画质备用地址支持连续字节范围请求并可播放完整 32.02 秒。
- [x] 采集器保持最高码率优先，在相同码率内改为优先 `BackupPlayUrl`、缺失时回退 `MainPlayUrl`；详情展示和模型调用共同复用该解析结果。
- [x] 产品设计、技术路线、舆情链档和既有契约断言已同步；未引入媒体下载、转存或后端代理。
**下一步**：无；按使用者要求直接完成 Git 收尾，不执行自动化或页面测试。
**边界**：本次只修正平台返回的等价播放地址优先级，不降低清晰度，不增加候选 URL 探测请求。
**关联**：`src/threadsnap/collectors/dongchedi.py`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-20 — 详情视频打开即预缓冲
**总目标**：减少详情视频首次点击播放时因只预加载元数据造成的等待。
**状态**：✅ 播放器已改为取得当前临时地址后由浏览器立即预缓冲，并保持用户主动播放。
**干到哪里了**：
- [x] 详情 `<video>` 从 `preload="metadata"` 调整为 `preload="auto"`，同时启用 `playsInline`；媒体继续由浏览器直连 CDN，后端不增加视频下载或代理流量。
- [x] 产品设计中相互冲突的 `preload="metadata"` / `preload="none"` 旧口径已统一，技术路线同步为预缓冲但不自动播放。
- [x] 按使用者要求跳过测试用例和页面验收；前端 TypeScript 静态检查与 `git diff --check` 通过。
**下一步**：无；本任务进入 Git 收尾。
**边界**：`preload="auto"` 是浏览器加载提示，实际缓冲量仍由浏览器和网络策略决定；本次不调整平台最高码率选择策略。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`

---

## 2026-08-20 — 舆情结果清空、付费队列恢复与视频时效输入修复
**总目标**：在余额补充后清空既有舆情结果并只重跑原 30 条分析范围，同时避免历史视频临时 URL 过期造成付费请求空响应。
**状态**：✅ 30 条既有范围已完成重新分析；最终为 30/30 `analysis_completed`、0 失败，服务与配置均已恢复。
**干到哪里了**：
- [x] 现场分母为 2910 条帖子、30 条已有舆情任务、17 条完成、13 条余额不足暂停和 1 条人工修订；没有分析记录的另外 2880 条历史帖子未进入本次付费回刷。
- [x] 停止 Worker 后通过 SQLite 在线备份 API 保存 `artifacts/runtime/sentiment-full-reset-20260820-220632/threadsnap-before-reset.db`（SHA-256 `63030B6CAD4C84EE3CA840C95E3672F157EE2B31AB27FDFEF390DB7D455B7B95`），随后清空 30 条 AI 结果/原始响应/用量和 1 条人工修订，并把 30 条原任务恢复排队。
- [x] 一次最小连接测试从原 `403 insufficient_quota` 恢复为 `valid`，配置重新启用；初次续跑确认历史快照视频 URL 已返回 HTTP 403，而按 `video_id` 直接 HTTP 刷新的当前 URL 返回 HTTP 206 `video/mp4`。
- [x] 模型 Worker 在付费请求前复用现有直接 HTTP 媒体刷新器，只替换本次请求输入、不改写帖子快照；同一视频的等价 dcarvod CDN 主机纳入稳定身份去重。提供方把已完成模态写成 `relevant`/`present` 时，只在汇总状态和计数可唯一确认的条件下本地归一化。
- [x] “来源搜索仍按任务快照平台圈子名匹配、与当前来源名展示不一致”的问题已登记到 `docs/chains/first-platform-delivery.md`，本任务不顺带修改筛选语义。
- [x] 两个受控消费者完成全部 30 次真实模型请求：18 条直接通过，12 条仅因提供方把冗余结构字段写成 `present`/`relevant`、对象式匹配项或复制错误 URL 哈希而进入结构失败；随后只使用已经保存的原始响应、后端权威媒体索引和输入身份做确定性恢复，没有追加模型请求，最终 30/30 `analysis_completed`、0 失败。
- [x] 本地后端已加载最终代码；配置为 revision 14、`enabled=true`、`validation_status=valid`，后端 `/health` 与 Vite `/health` 代理均返回 `ok`。
- [x] 79 项后端测试通过；本任务 5 个 Python 文件 Ruff 格式与静态检查、`compileall`、`pip check` 和 `git diff --check` 均通过。全仓格式检查另命中 7 个任务外既有文件，本任务未顺带重排。
**下一步**：无；本任务进入 Git 收尾，不再触发本批次模型请求。
**边界**：只重跑原有 30 条任务，不新建历史回刷；媒体仍由模型服务读取当前 URL，ThreadSnap 不下载、转存或代理视频；有效模型观点和原始依据不做业务改写。
**关联**：`src/threadsnap/poc/sentiment.py`、`src/threadsnap/sentiment.py`、`src/threadsnap/app.py`、`tests/test_sentiment_poc.py`、`tests/test_backend.py`、`docs/chains/sentiment-analysis.md`、`docs/chains/first-platform-delivery.md`、`docs/design/technical-route.md`

---

## 2026-08-20 — 来源名称实时展示与列表类型标识
**总目标**：让来源名称修改后同步反映到历史批次展示和后续导出，并在帖子结果中明确区分“最新回复”与“最新发布”。
**状态**：✅ 后端当前名称解析、删除回退、列表类型字段、前端展示、必要测试和本地重启均已完成。
**干到哪里了**：
- [x] 批次摘要、来源任务、帖子列表和帖子详情通过稳定 `circle_id` 批量读取来源当前名称；来源已删除或关联失效时继续使用任务创建时名称快照，不改写历史任务。
- [x] 帖子 API 增加 `list_order` 与中文 `list_order_name`；结果表“圈子”列改为“来源”，在当前名称旁显示“最新回复/最新发布”标签，详情来源摘要同步显示列表类型。
- [x] `source.name` 导出字段改用来源当前名称，任务名称快照继续仅承担追溯和回退职责；产品设计和技术路线已同步。
- [x] 2 项针对性后端测试、受影响 Python 文件 Ruff 检查、前端 TypeScript 检查和 `git diff --check` 通过。
- [x] 本地后端已重启；真实历史批次 API 与页面均显示当前名称“风云A9”和“最新发布”，Vite 健康代理返回 HTTP 200；截图位于 `artifacts/runtime/live-source-labels-20260820/run-detail.png`。
**下一步**：无；本任务进入 Git 收尾。
**边界**：名称仅作为可变展示属性跟随配置；URL、列表顺序、数量和其他实际执行参数仍使用批次快照。
**关联**：`src/threadsnap/services.py`、`src/threadsnap/templates.py`、`frontend/src/features/runs/run-detail-page.tsx`、`frontend/src/lib/types.ts`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`

---

## 2026-08-20 — 详情 Sheet 自动加载视频
**总目标**：打开含视频的帖子详情 Sheet 后直接获取当前播放地址并创建播放器，去掉必须再次点击“加载视频”的冗余步骤。
**状态**：✅ 自动加载、失败重试、显式刷新、前端构建和真实页面验收均已完成。
**干到哪里了**：
- [x] 视频详情组件改为挂载即请求媒体解析接口；关闭窗口聚焦自动刷新和自动重试，组件卸载后释放前端查询缓存，重新打开时由后端短缓存合并有效期内的重复解析。
- [x] 加载期间显示局部进度，失败后原按钮变为“重试加载”，成功后保留“刷新播放地址”；播放器只预加载元数据并保持用户手动播放。
- [x] `npm.cmd run check` 与 `npm.cmd run build` 通过；后端 `/health` 和 Vite `/health` 代理均返回 HTTP 200。
- [x] 在真实批次 `01a01e38-eb72-7d5c-9055-f5201c2bd70f` 打开视频帖子详情后，未点击媒体按钮即出现播放器和到期时间；后端同步记录媒体解析 `POST 200` 与同源播放入口 `GET 307`，截图位于 `artifacts/runtime/detail-video-auto-load-20260820/sheet-auto-loaded.png`。
**下一步**：无；本任务进入 Git 收尾。
**边界**：只改变详情打开后的前端触发时机；媒体仍由浏览器经同源无正文重定向后直连 CDN，后端不下载、转存或代理视频，不自动播放。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-20 — 视频播放地址改为直接 HTTP 解析
**总目标**：去除帖子详情加载与视频帖采集中的 Chromium 启动，使用平台实际 HTTP 接口直接把快照 `video_id` 解析为当前播放 URL。
**状态**：✅ 直接解析、最高码率选择、真实媒体可达性、无新增浏览器进程和服务重启均已完成。
**干到哪里了**：
- [x] 一次有界网络取证确认平台网页先请求 `motor/pc/common/token` 获取三天播放授权，再请求 VOD `GetPlayInfo`；后者 JSON 返回三档 `MainPlayUrl`/`BackupPlayUrl`。省略网页动态生成的 `msToken` 与 `a_bogus` 后，两个真实视频 ID 的两段请求仍均返回 HTTP 200。
- [x] 懂车帝适配器新增两段直接 HTTP 解析，只返回最高码率主地址；详情显式加载和采集时 `video_play_info` 为空的回退均改用该方法，原 `VideoUrlResolver` 及其帖子页面导航、媒体请求观察和 Chromium 生命周期已经移除。
- [x] 真实视频 ID 解析取得 1 个 `v26-microapp-dcar.dcarvod.com` 地址，单字节 Range 请求返回 `206 Partial Content`、`video/mp4` 且仅接收 1 字节；调用前后浏览器进程均为 19，没有新增 PID，证据位于 `artifacts/runtime/direct-video-url-investigation/direct-http-proof.json`。
- [x] 76 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查、生产构建和 `git diff --check` 通过；测试显式断言媒体解析接口不调用 `sync_playwright`。
- [x] 本地后端已使用 `H:\ThreadSnap\.vevn\Scripts\python.exe` 重启；后端 `/health` 与 Vite `/health` 代理均为 `ok`。真实帖子媒体解析接口在 373ms 内返回 1 个播放地址和 1 个同源播放入口，调用前后浏览器进程保持 19，没有新增 PID。
**下一步**：无；本任务进入 Git 收尾。
**边界**：视频播放仍由用户浏览器直连 CDN；ThreadSnap 只请求授权和播放信息 JSON，不下载、转存或代理媒体。认证、Session 有界恢复及圈子 SSR 不足回退的既有浏览器边界保持不变，本次仅去除常规视频链路误用的浏览器。
**关联**：`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/worker.py`、`tests/test_backend.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`、`docs/research/sentiment-analysis-poc-results.md`

---

## 2026-08-20 — 详情视频时效 URL 刷新与无 Referer 播放
**总目标**：修复历史帖子详情中的视频地址过期后无法加载，同时坚持 URL 直连且不让 ThreadSnap 下载、代理或保存视频文件。
**状态**：✅ 按需刷新、稳定媒体去重、无正文重定向、前端显式加载和真实 Chrome 播放验收均已完成。
**干到哪里了**：
- [x] 现场确认帖子 `7675753962574168601` 的两条快照 CDN URL 均返回 HTTP 403；路径签名中的到期时间表明有效期约一小时。重新解析所得 URL 在无 Referer 的单字节 Range 请求中返回 `206 Partial Content` 与 `video/mp4`，携带本地页面 Referer 时仍返回 403，因此问题同时包含地址过期和 CDN 来源限制。
- [x] 新增按帖子显式解析接口：只使用数据库原帖 URL 与现有平台 Session，复用完整 Chromium 观察媒体请求并阻断媒体正文；结果按忽略查询和已验证 CDN 路径签名的稳定身份去重，最多缓存 256 个且受五分钟、到期前一分钟和四十五分钟上限约束，原快照不改写。
- [x] 新增同源播放地址：只对刚缓存 URL 返回 `307`、`Referrer-Policy: no-referrer` 和 `Cache-Control: no-store`，浏览器随后直接访问 CDN；后端不读取媒体正文。前端打开详情时不访问平台，只有点击“加载视频”后才解析并创建播放器，支持显式刷新、中文失败提示和原帖入口。
- [x] 自动化回归覆盖当前 URL 返回、路径签名去重、短缓存复用、播放重定向响应头及数据库快照不变；75 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查、生产构建和 `git diff --check` 全部通过。
- [x] 本地后端已用 `H:\ThreadSnap\.vevn\Scripts\python.exe` 重启；后端 `/health`、Vite `/health` 代理均为 `ok`。真实 Chrome 点击加载后播放器显示实际首帧和 `0:00 / 0:07` 时长，验收截图位于 `artifacts/runtime/video-url-refresh-20260820/chrome-video-loaded.png`。
**下一步**：无；本任务进入 Git 收尾。
**边界**：本次没有调用千问、没有下载或转存完整视频、没有改写历史帖子快照；同源 GET 只返回重定向响应，媒体流量仍由浏览器直达 CDN。
**关联**：`src/threadsnap/worker.py`、`src/threadsnap/app.py`、`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-20 — 批次详情筛选栏桌面布局修复
**总目标**：修复宽桌面下八组筛选/操作控件挤压标题搜索框的问题，在可容纳时保持紧凑单行并在较窄宽度有序换行。
**状态**：✅ 常规宽屏与超宽屏布局、owner 文档、自动检查和真实页面验收均已完成。
**干到哪里了**：
- [x] 确认首个“小方框”实际为被压缩的“搜索帖子标题”输入框；根因是七组固定列、约 300px 操作区和 12px 列间距共同耗尽容器宽度，只有 `1fr` 首列承担收缩。
- [x] 1536px 以上改用八列紧凑网格：标题搜索最小 180px，圈子、状态、排序和方向按内容缩减，导出选择由 192px 收敛为 144px，组间距统一为 8px；较窄视口回退四列或两列。
- [x] `npm.cmd run check --prefix frontend`、`npm.cmd run build --prefix frontend` 与 `git diff --check` 通过；在真实批次 `01a01e38-eb72-7d5c-9055-f5201c2bd70f` 的 1680×900 和 1536×900 视口确认八组控件均为单行、标题输入完整、操作可达且无横向溢出，截图保存于 `artifacts/runtime/run-toolbar-layout-20260820/`。
- [x] 用户的 2560px 截图暴露标题列使用 `1fr` 会独占全部剩余宽度；现仅在 ≥2000px 将标题搜索框封顶 360px，以弹性留白分隔筛选组和右侧操作区，同时保留 1536–1999px 的弹性八列布局。已在 2560×1292 与 1536×900 实页复验，截图保存于 `artifacts/runtime/run-toolbar-ultrawide-20260820/`。
- [x] 相邻状态筛选的网格间距计算值虽为 8px，但通用 `SelectTrigger` 的 `w-fit + nowrap + px-3 + gap-2` 最小内容宽度会越过 125/130px 固定轨道，视觉间距因此只剩 1–4px。工具栏直属下拉框现改为填满列宽、允许收缩，并使用 8px 横向内边距和 4px 图文间距；1536px 与 2560px 实测五个筛选框之间均恢复为精确 8px，截图保存于 `artifacts/runtime/run-toolbar-spacing-20260820/`。
**下一步**：无；本任务进入 Git 收尾。
**边界**：只调整批次详情筛选栏的响应式尺寸与间距，不改变筛选、复制、导出或批次数据逻辑。
**关联**：`frontend/src/features/runs/run-detail-page.tsx`、`docs/design/product-design.md`、`docs/design/technical-route.md`

---

## 2026-08-20 — 舆情真实批次结构兼容、媒体去重与受控并发
**总目标**：修复真实千问批次全部结构校验失败、同一视频重复提交和单消费者处理过慢的问题，同时避免额外无效模型请求。
**状态**：✅ 修复、全量本地验证、真实队列安全暂停和本地服务恢复均已完成；没有新增千问请求。
**干到哪里了**：
- [x] 现场证据确认模型已返回可用语义，但 `evidence` 使用字符串、无输入模态使用 `skipped`、媒体索引从 1 开始且音频顶层返回通用 `processed`，与本地严格 Schema 不一致；旧 Worker 对同一完整多模态输入原样重试一次，造成两条失败各耗时约 146/154 秒。
- [x] 模型输入、输入指纹、模态校验、视频解析和详情展示按忽略签名查询的稳定媒体身份去重；同一路径的四个签名 URL 只提交和展示首个，原始快照不改写。
- [x] 提示词升级为 `v2`，明确依据数组、零基索引、无输入模态和状态枚举；本地只归一化可由输入唯一确定的形状并继续保存原始响应，不改写模型的相关性、情感、类别、总结或依据文字。
- [x] 舆情 Worker 固定两个消费者，只串行化 SQLite 短领取事务；取消结构和媒体部分结果的整请求重复发送，仅保留可重试传输错误的有界退避。
- [x] 真实失败中另有 1 条 HTTP 429 在旧逻辑下重试 3 次；修复后两个消费者共享 `Retry-After` 或默认 30 秒冷却，单条 429 最多重试一次，避免并发演变为连续限流请求。
- [x] 74 项后端 `unittest`、Ruff、`compileall`、`pip check`、前端 TypeScript 检查、生产构建和 `git diff --check` 通过，全部使用本地替身，未调用千问 API。
- [x] 变更前真实队列为 10 条失败、1 条运行中、19 条排队；已校验备份到 `artifacts/runtime/sentiment-runtime-fix-20260820-162700/threadsnap-before-pause.db`（SHA-256 `1D0397306E50FB891E5BF0B3F0B3A1E8C75E6BC9C5B7A78C532D1E078DE089AB`），随后把该批次 30 条统一转为可恢复暂停、配置关闭并升级到提示词 `v2`，9 份结构失败原始响应保持不变，429 失败原本没有响应正文。
- [x] 修复版后端已恢复：后端 `/health`、Vite `/health` 代理均为 `ok`，前端 HTTP 200；最新批次 API 返回 30 条暂停任务、11 条含视频帖子和 0 个稳定媒体重复 URL，启动与检查未领取任务。
**下一步**：由使用者在“AI 舆情”配置页显式重新开启分析；系统会把 30 条暂停任务恢复排队，并以两个消费者、稳定媒体去重、结构归一化和共享 429 冷却继续处理。真实完成/部分/失败分布需等待该付费批次运行后观察。
**边界**：不增加模型调用、不改写历史帖子快照或模型观点、不把并发做成用户配置；当前真实队列由使用者显式重新开启后才恢复。
**关联**：`src/threadsnap/sentiment.py`、`src/threadsnap/worker.py`、`src/threadsnap/services.py`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-20 — 舆情模型域名兼容代理 Fake-IP
**总目标**：修复公网模型域名在透明代理 Fake-IP DNS 下被 SSRF 校验误判，恢复连接测试入口。
**状态**：✅ 已完成窄修复并重启本地后端；未触发模型连接测试或千问请求。
**干到哪里了**：
- [x] 现场确认业务空间域名被本机 DNS 映射为 `198.18.0.17`，直接无凭证 HTTPS 请求返回预期 `401`，证明域名与 TLS 链路可达，失败发生在本地模型请求前。
- [x] 公网地址校验只对“HTTPS 域名的 DNS 结果”兼容 RFC 2544 `198.18.0.0/15`；直接填写该网段 IP、回环、私网、链路本地和云元数据地址仍拒绝，HTTP 客户端继续验证域名证书且不跟随重定向。
- [x] 新增纯本地回归用例覆盖域名 Fake-IP 放行与字面 Fake-IP 拒绝；未携带或发送 API Key。
**下一步**：由用户在页面按需点击“测试连接”；该操作会产生一次最小文字模型调用，本次修复过程未代为执行。
**边界**：不扩大到其他保留或私有网段，不关闭 SSRF 防护，不改变模型请求、密钥、队列或重试逻辑。
**关联**：`src/threadsnap/sentiment.py`、`tests/test_sentiment_poc.py`、`docs/design/technical-route.md`

---

## 2026-08-20 — 舆情反馈正式功能闭环
**总目标**：把已确认的在线多模态舆情合同接入现有提取链路，完成配置、持久分析、列表/详情展示和随机人工修正。
**状态**：✅ 本地功能实现与组合验证完成；生产环境真实模型调用和目标服务器升级作为后续部署验收，不在本次重复消耗外部 Token。
**干到哪里了**：
- [x] 新增舆情数据库迁移、单例运行配置、逐帖子持久分析任务与追加式人工修订；API Key 复用 Fernet 加密且读取接口只返回是否已配置，连接变化自动关闭并清除验证状态。
- [x] 新增窄 OpenAI 兼容流式客户端和独立单线程 Worker；保存原始响应、规范化结论、模态覆盖、对象/提示词/模型版本、输入指纹、用量、耗时、请求 ID、重试与错误证据，结构与媒体身份校验不重判模型观点。
- [x] 帖子入库自动进入排队或禁用；实现关闭、暂停、恢复、重启回收、有界传输/结构/媒体重试、同内容人工继承和完整 AI 精确复用。关闭期间的新快照保持禁用，不绕过开关复用历史结论。
- [x] 采集链路在 `video_play_info` 未返回 URL 但存在 `vid` 时，按提取任务懒启动并复用完整 Chromium，阻断媒体正文、观察播放请求和 DOM 播放地址；ThreadSnap 不下载、中转或转码视频。
- [x] 新增 `/api/v1` 与 `/internal/v1` 配置、连接测试、列表筛选、详情和人工修订接口；列表增加舆情结果/来源/状态同列展示和结果、状态两个服务端筛选。
- [x] 配置页新增“AI 舆情”页签；详情 Sheet 分段展示中文总结、分类、文字/图片/视频画面与音频依据，图片懒加载、视频 `preload=none` 直连，人工修正使用 viewport 级 Dialog 且只在允许终态开放。
- [x] 自动化组合路径覆盖“保存密钥但不回显 → 连接测试 → 启用 → 入库排队 → 模拟真实结构响应 → 列表/详情 → 人工设置/恢复 → 密钥轮换自动关闭 → 关闭期间禁止复用”；完整 71 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查、生产构建和 `git diff --check` 通过。
- [x] 真实浏览器验证“AI 舆情”配置页、负面列表及 AI 来源标签、详情中文依据/媒体区域和覆盖 Sheet 的全局人工修正 Dialog；验证使用本地模拟已完成结果，没有新增千问请求。
**下一步**：在正式 HTTPS 入口写入生产加密配置，显式完成一次连接测试和一条受控真实组合路径，再按现有离线升级流程生成目标服务器升级包；该步骤会产生外部 API 用量并单独记录。
**边界**：本次不增加余额/费用查询、本地模型、自由模型名、重新分析、历史回刷、媒体下载或评论输入；真实 API Key、签名媒体 URL、原始响应和本地 UI 数据均保持在 Git 外。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/sentiment-analysis.md`、`docs/adr/0022-use-hosted-multimodal-api-for-sentiment-feedback.md`、`docs/adr/0023-use-validated-runtime-config-for-sentiment-service.md`

---

## 2026-08-20 — 舆情正式接入产品与技术合同
**总目标**：在 PoC 完成后收敛模型配置、判定对象、有效结果、分析状态、列表/详情交互和人工修订边界，为前后端进入同一实现基线。
**状态**：✅ 需求访谈已完成并写入 owner 文档；数据库、Worker、接口和页面尚未实现。
**干到哪里了**：
- [x] 模型服务确定为可持久化的“AI 舆情”配置：API Key 以 Fernet 加密且只写不读，受控模型下拉首版只有 `qwen3.5-omni-plus-2026-03-15`，显式最小文字测试成功后才能开启；允许经过 SSRF 防护的公网 HTTPS OpenAI 兼容代理，不增加余额查询、本地 HTTP 模型或自由模型名。
- [x] 判定对象收缩为目标品牌、14 个重点车型和选填补充说明；常见别名、品牌服务及帖子实际相关性由模型结合语境判断。有效结果明确为负面、非负面或不相关，后端只校验结构和模态覆盖，不做关键词重判。
- [x] 分析状态补齐暂停和禁用：关闭时已发出请求继续，排队和关闭期间新帖进入禁用，重新开启只影响未来新帖；配置错误暂停并在配置测试通过后恢复。第一版不自动回刷历史、不提供重新分析。
- [x] 列表增加舆情结果及来源标签，并分别提供结果和分析状态筛选；人工修正只在详情的全局 Dialog 中进行，备注选填，负面次要类型可多选，所有修订追加保存且人工始终优先。
- [x] 详情沿用现有 Sheet，按中文段落展示总结和分模态依据，并以浏览器懒加载图片、点击后直连播放视频；ThreadSnap 不为展示下载或代理媒体，失败时提供原帖入口。
- [x] 补充记录一次真实图文请求：HTTP 200、5,681 ms、Prompt 2,041、Completion 463、Total 2,504 Token、图片 1/1 processed；原始尾部围栏与视频样本一致，本地确定性恢复成功。证据位于 Git 忽略目录 `artifacts/poc/results/sentiment-qwen3-5-omni-plus-image-text/20260820T033138Z/summary.json`。
**下一步**：按 `docs/design/technical-route.md` 的接口合同进入功能分支，先实现视频 `vid` 播放 URL 回退与模型配置/任务/结果数据库基线，再实现 Worker、列表筛选、详情媒体和人工修订 Dialog，最后触发真实“提取入库 → 自动分析 → 列表/详情 → 人工修正”组合路径验收。
**边界**：本条只完成正式接入合同和 PoC 事实同步，不把文档、连接测试或单样本结果表述为功能交付；API Key、签名 URL 和模型原始响应继续留在 Git 外，远程纯 HTTP 页面不得写入 API Key。
**关联**：`CONTEXT.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/adr/0023-use-validated-runtime-config-for-sentiment-service.md`、`docs/chains/sentiment-analysis.md`、`docs/research/sentiment-analysis-poc-results.md`

---

## 2026-08-19 — 在线多模态舆情反馈受控 PoC
**总目标**：在不由 ThreadSnap 下载视频且严格限制千问调用次数的前提下，完成真实视频 URL 获取、公开可达性和端到端多模态反馈验证。
**状态**：✅ PoC 已按 30 条 URL 传输样本、1 次千问调用、0 次自动重试完成；证据支持保持 URL 直传并进入最小实现。
**干到哪里了**：
- [x] 从真实圈子列表扫描 171 条详情取得 30 条视频；30/30 有 `vid`、0/30 有 `video_play_info`。使用现有加密 Session 启动完整 Chromium，在请求层阻断 77 次媒体正文请求后，30/30 取得播放器直接 URL。
- [x] 30/30 个 URL 在无 Cookie、无 Referer 的 `HEAD` 请求中返回 HTTP 200 和 `video/mp4`；视频时长最小/中位/最大为 7/22/117 秒，Content-Length 最小/中位/最大为 1,231,606/4,178,614/20,059,134 字节。
- [x] 唯一一次 `qwen3.5-omni-plus-2026-03-15` 请求使用 A9L 的 42 秒视频，HTTP 200、耗时 15,122 ms；用量为 Prompt 25,882、Completion 535、Total 26,417，其中视频 24,950、音频 296、文字输入 636 Token。
- [x] 模型真实反馈命中 A9L、`non_negative`、视频画面 `processed` 1/1、视频音频 `speech` 1/1。原始 JSON 尾部多出 Markdown 围栏；原始严格结构失败，本地仅移除围栏后通过 Pydantic 校验，两个状态分别保留。
- [x] 新增 `src/threadsnap/poc/sentiment.py` 和 5 项自动化测试；调用账本在请求前记账并阻止第 2 次请求。原始样本、签名 URL、配置、响应和日志均留在被 Git 忽略的 `artifacts/poc/`。
- [x] 事实报告写入 `docs/research/sentiment-analysis-poc-results.md`，并修正 Qwen-Omni 必须流式接收、JSON Object 加本地 Schema 校验及本轮零重试口径。
- [x] 验证通过：70 项后端测试、Ruff、`compileall`、`pip check`、`git diff --check` 和候选提交文件凭证扫描；三个关键 PoC 产物均由 `git check-ignore` 确认为忽略状态。
**下一步**：进入最小实现，先把“`video_play_info` 为空且 `vid` 存在时，以完整 Chromium 阻断媒体正文并读取播放 URL”的路径收敛到采集器契约，再实现持久舆情任务、窄模型客户端、结果落库、接口与页面。
**边界**：30 是 URL 传输验证分母，模型验证分母只有 1；不得宣称 30/30 模型成功，也不外推静音、失效签名或模态冲突表现。当前没有引入视频下载、中转、对象存储、转码、抽帧或 ASR。
**关联**：`docs/research/sentiment-analysis-poc-results.md`、`docs/research/sentiment-analysis-poc-plan.md`、`docs/adr/0022-use-hosted-multimodal-api-for-sentiment-feedback.md`、`docs/chains/sentiment-analysis.md`

---

## 2026-08-19 — 在线多模态舆情反馈技术设计
**总目标**：明确帖子负面/非负面及负面类型分析应采用的技术路线、媒体输入、人工复核、结果继承、失败边界和正式实现前 PoC。
**状态**：✅ 需求与技术设计已确认并写入 owner 文档；尚未运行真实视频 PoC，也未实现数据库、队列、接口或页面。
**干到哪里了**：
- [x] 确认该需求不是对话型智能体：每条帖子以一次在线多模态 API 请求同时分析完整标题、正文、全部图片 URL 和全部视频 URL，不使用本地小模型、Agent 框架、RAG、工具、联网搜索或第二模型复核。
- [x] 第一轮 PoC 固定百炼 OpenAI 兼容接口和 `qwen3.5-omni-plus-2026-03-15`；视频由提供方直接读取 URL 并分别报告画面与音频覆盖，ThreadSnap 不下载、中转、转码、抽帧或 ASR。
- [x] 分析采用同一应用进程内的独立持久任务和 Worker，提取与分析状态分离；保存原始模型响应、规范化字段、版本、请求追踪、用量、耗时和失败证据，程序只校验结构与模态覆盖。
- [x] 有效结论优先级确定为“当前人工修正 > 内容未变化时继承的人工判定 > 当前或精确复用的完整 AI 反馈”；人工复核随机发生，不设置强制复核比例、召回率、误判率、漏判上限或多人一致性流程。
- [x] 只读样本基线记录为 2880 个帖子快照、842 个不同帖子、1939 个含图片快照、0 个含视频快照；因此 PoC 前必须另取至少 30 条真实视频帖子，事实报告只统计 URL 获取、画面/音频覆盖、结构、耗时、用量、成本和失败分布。
- [x] 已建立 `docs/adr/0022-use-hosted-multimodal-api-for-sentiment-feedback.md`、`docs/chains/sentiment-analysis.md` 和 `docs/research/sentiment-analysis-poc-plan.md`，并同步 `CONTEXT.md`、产品设计、技术路线及文档索引。
**下一步**：在 `artifacts/poc/inputs/sentiment-analysis/` 收集至少 30 条真实视频帖子，在 Git 外配置 API 后按 PoC 计划运行；报告完成后再决定进入实现，或针对有证据的 URL 失败另立媒体传输决策。
**边界**：当前没有提交业务代码或数据库迁移；PoC 不评价 AI 情感与类别是否客观正确，不因 URL 失败自动下载视频，也不把文档设计写成已交付功能。
**关联**：`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/adr/0022-use-hosted-multimodal-api-for-sentiment-feedback.md`、`docs/chains/sentiment-analysis.md`、`docs/research/sentiment-analysis-poc-plan.md`

## 2026-08-18 — 目标服务器快速离线升级到当前版本
**总目标**：在不重新下载系统、Python 和 Chromium 依赖的前提下，把目标 CentOS 服务器升级到当前 `main`，并按已确认边界清空旧业务数据库。
**状态**：✅ 当前干净提交已完成服务器内离线重封装、版本切换和运行验证。
**干到哪里了**：
- [x] 通过 SSH 核对目标机仍保留已验证的完整离线包；旧包 SHA-256 为 `1e4a948b390b5aeabf35d9dbc4bb43f554c54e8b971f5f89ff650e424894acc6`，当前提交与旧发布之间的 Python、前端依赖锁定文件及 Linux 部署脚本均未变化。
- [x] 从干净提交 `801c79c956699c7ab7c47c3a29acf12968846e1a` 生成 385259 字节业务构建包，在目标机复用旧包的 `wheelhouse`、Chromium、RPM 和系统包清单，形成 `/var/tmp/threadsnap-upgrade-801c79c/threadsnap-0.1.0-801c79c-centos-stream-10-x86_64-offline.tar.gz`；大小 `590440857` 字节，SHA-256 为 `7f210027dc250801cdc73dcb50724bc5b34c8a7c9557d887db9bf77f98eb6929`，884 项内部校验通过。
- [x] 停服前确认活跃批次为 0；停止后端后清除 `threadsnap.db` 及 WAL/SHM，再由当前版本初始化全新 20 表基线。基础平台与调度配置按程序基线建立，历史规则、来源、批次和帖子数据未保留。
- [x] 当前指针已切换到 `/opt/threadsnap/releases/0.1.0-801c79c95669`，previous 保留为 `0.1.0-1bc2916dae46`；后端停服窗口约 20 秒，`threadsnap`、`threadsnap-wayland`、`threadsnap-nginx` 均为 active。
- [x] 安装器快速验证和切换后二次验证均通过：后端与 Nginx `/health`、SPA、内部接口屏蔽、8000 回环绑定、CDP 关闭、Fernet 配置及有头浏览器模式全部 PASS；启动后十分钟范围内没有 warning 级日志。
**下一步**：如需从当前客户端直接访问 `8088`，继续核对上游端口映射或安全组；服务器 firewalld 已按既有规则仅允许当前 SSH 来源，但本次客户端直连仍未形成 Nginx 访问日志。连续三轮 2000 URL 最终吞吐门禁仍独立待执行。
**边界**：本次没有联网下载目标机依赖，没有改动既有 Docker Nginx 的 `80/443`，没有格式化未挂载的 3.6 TiB 数据盘，也不把安装健康验证记为最终吞吐验收。
**关联**：`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`、`docs/deployment/linux-v1.md`

## 2026-08-18 — 导出单元格统一换行与宽高自适应
**总目标**：让模板导出的所有字段都在单元格内换行，并让实际写入区域的列宽和行高适配本次导出内容。
**状态**：✅ 全字段换行、列宽估算和自动行高处理均已实现并通过完整验证。
**干到哪里了**：
- [x] 所有实际写入的数据单元格统一设置自动换行，不再只处理评论、图片和视频集合字段。
- [x] 实际写入列按模板表头与本次最长内容估算宽度，中文按双宽计算并限制在 8 至 60 字符宽，避免长正文把整张表横向撑开。
- [x] 实际写入的数据行清除模板固定行高，让 Excel 等表格软件依据换行后的内容自动计算行高；未写入的模板区域、公式、图表和说明保持不变。
- [x] 导出回归覆盖普通标题、评论集合、多行正文、模板固定窄列和固定行高；65 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查、生产构建及 `git diff --check` 均通过。
**下一步**：用下一份实际业务模板导出并观察极端长文本在 60 字符列宽上限下的展示效果；如需调整上限，只修改统一常量，不改变字段规则。
**边界**：XLSX 不保存可由 `openpyxl` 精确执行的 Excel 渲染级列宽自动计算，本实现采用可复现的内容宽度估算；只调整本次实际写入的列和数据行。

## 2026-08-18 — 手动提取与规则来源分类默认收起
**总目标**：让新建手动提取按“最新回复、最新发布”分类选择已配置来源，并把手动提取与自动规则的列表类型分类统一为默认收起。
**状态**：✅ 两处列表类型分类均支持三态全选、已选计数和默认收起，来源提交结构保持不变。
**干到哪里了**：
- [x] 新建提取只展示当前平台来源，并按“最新回复、最新发布”生成独立折叠分类；分类标题显示 `已选数/总数`，复选框支持全选、取消全选和半选，展开后仍可逐项多选。
- [x] 两个手动分类首次打开均默认收起；分类全选不强制展开，关闭弹窗继续沿用既有重置语义，不提交任何测试批次。
- [x] 自动提取规则的列表顺序分类不再因已有选中来源自动展开；分类组件绑定规则 ID，切换规则后即使平台层保持展开，也会为新规则恢复默认收起。
- [x] 65 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建通过；真实运行页面确认手动分类初始为“最新回复 0/14、最新发布 0/1”，最新发布全选后变为 `1/1` 且展开项选中，自动规则已有 `13/14` 和 `1/14` 选中来源时分类仍保持收起。
**下一步**：后续新平台沿用当前平台过滤和列表顺序分组，不新增平台私有选择结构；实际来源数量增大到现有滚动容器不足时再评估搜索，不提前增加第二套选择器。
**边界**：只调整来源选择的信息层级、批量选择和默认展开状态；不改变来源 ID、手动批次结构、规则版本、每圈数量、提交接口或提取执行语义。
**关联**：`docs/design/product-design.md`、`docs/chains/first-platform-delivery.md`、`frontend/src/features/runs/new-extraction-sheet.tsx`、`frontend/src/features/config/config-page.tsx`

## 2026-08-18 — 认证续跑跨过已完成列表页
**总目标**：修复圈子任务认证中断后已有首屏结果时，续跑把“当前页全部已处理”误判为“平台没有更多内容”，导致未继续到下一页补足目标数的问题。
**状态**：✅ 已区分真实空页与已完成页，续跑会跨过检查点覆盖的页面继续发现未完成帖子。
**干到哪里了**：
- [x] 复核真实批次 `20260818-154456-001`：QQ3 EV 目标 40、检查点 30、失败 0，却以“平台没有更多可用内容”结束；同一来源实时解析为 1918 条、64 页，第 1、2、3 页各 30 条且相邻页帖子 ID 无重复。
- [x] 确认其他来源正常的差异是执行阶段：认证前两个来源已经完成，QQ3 EV 在第三个任务处理完首屏后进入认证，后续来源在认证恢复后从零开始；旧逻辑仅在 QQ3 EV 续跑首屏全部命中检查点时触发误判。
- [x] 采集器仅在页面实际没有行时立即结束；页面有行但全部命中检查点时，只要平台声明仍有下一页就继续翻页，到末页后才按实际数量结束。
- [x] 新增“首屏三条均已完成、第二页存在三条新帖”的续跑回归测试；真实 QQ3 EV 页面用当前首页 30 个 ID 作为检查点，修复后实际请求第 1、2 页并取得剩余 10 条。
- [x] 65 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建通过。
- [x] PR #109 已合并为 `e441d22`，本地后端已从合并后的 `main` 重启；`/health` 返回 `status=ok`，批次列表接口可正常读取。
**下一步**：在下一次真实认证中断与恢复场景中观察任务跨过已完成列表页并补足剩余数量；既有终态批次保持不可变。
**边界**：不改写批次 `20260818-154456-001` 的既有 430 条快照和终态；不在真实空页后继续探测，也不改变分页大小、来源顺序、去重或认证门禁。
**关联**：`docs/design/product-design.md`、`docs/chains/first-platform-delivery.md`、`src/threadsnap/collectors/dongchedi.py`、`tests/test_backend.py`

## 2026-08-18 — 认证续跑与运行批次实时刷新进度
**总目标**：修复等待认证批次恢复后长期停留在旧完成数、偶发直到刷新页面才显示最终进度的问题。
**状态**：✅ 后端分段持久化权威进度并补齐状态事件，前端对活跃批次增加短周期回查兜底。
**干到哪里了**：
- [x] 确认两层根因：采集器原先整批返回后才写入快照，所以认证前的 `3/10` 在剩余 7 条全部结束前不会变化；终态只依赖单次 `run.changed` SSE 回查，错过有效回查后要等 60 秒兜底或手动刷新。
- [x] 圈子发现和 URL 清单采集新增进度回调；目标数不超过 20 时逐条提交，更大批次每 10 条提交，事务内同时写帖子、主评论、任务检查点和批次聚合，认证续跑沿用原任务累计值且终态重复应用保持幂等。
- [x] 认证恢复为排队、Worker 开始运行、分段进度提交和最终聚合均发送 `run.changed`；SSE 仍只发送轻量信号，前端继续以 HTTP 返回为权威数据。
- [x] 提取列表和批次详情在存在 `queued`、`running` 或 `waiting_for_auth` 批次时每 3 秒兜底回查，全部终态后恢复 60 秒低频兜底。
- [x] 新增认证恢复事件及任务结束前 `1 → 2 → 3` 分段持久化/事件回归测试；64 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查和生产构建通过。
- [x] 真实前端运行时插入一次性等待认证夹具验证兜底：页面先显示 `3/10`，不发送 SSE、仅在数据库改为 `4/10` 后 4.2 秒内自动显示 `4/10`；夹具删除后同样自动从列表消失，数据库未保留测试批次。
**下一步**：重启本地后端后，在提取列表发起或观察下一条真实批次，确认列表无需手动刷新即可连续显示分段进度与终态。
**边界**：不创建替代批次、不改写既有终态快照；小批量逐条提交，大批量按 10 条提交以控制 SQLite 事务与 SSE 频率。
**关联**：`docs/design/product-design.md`、`src/threadsnap/collectors/dongchedi.py`、`src/threadsnap/worker.py`、`frontend/src/features/runs/runs-page.tsx`、`frontend/src/features/runs/run-detail-page.tsx`、`tests/test_backend.py`

## 2026-08-18 — 认证画布交互不再重复创建浏览器
**总目标**：修复提取列表认证 Dialog 中点击登录输入框会重新加载认证浏览器、导致账号和验证码持续失焦的问题。
**状态**：✅ 认证任务生命周期与父页面查询刷新解耦，重复关闭浏览器上下文保持幂等。
**干到哪里了**：
- [x] 确认根因：画布获得焦点会触发提取列表查询刷新，父组件重渲染产生新的 `onOpenChange` 回调；该回调间接改变认证启动 Effect，导致每次交互重复请求 `POST .../auth/tasks?fresh=true`、创建新任务并重置倒计时。
- [x] 认证 Dialog 改用最新回调引用处理完成和关闭，不再让父组件回调对象身份参与认证启动依赖；平台、入口类型或真正的打开状态变化仍按原规则创建任务。
- [x] 后端关闭认证浏览器时先清空任务引用，并仅忽略 Patchright 明确的“目标已经关闭”错误，避免快速替换任务时 `BrowserContext.close` 竞态返回 500；其他浏览器异常继续上抛。
- [x] 新增已关闭上下文清理回归测试；62 项后端测试、Ruff、`compileall`、`pip check`、前端 TypeScript 检查、生产构建和 `git diff --check` 通过。
- [x] 真实提取列表使用批次 `20260818-142155-001` 验证：认证画布连续点击 3 次后仍为同一任务，倒计时继续递减且后端没有新增认证 POST/WebSocket；平台一次返回零字节页后仅由显式“重新创建认证浏览器”创建新任务，随后官方手机号验证码登录页恢复并保持可操作。
**下一步**：用户在当前保持打开的登录页完成手机号/验证码或密码登录，再执行“完成并校验”恢复原批次。
**边界**：不记录、读取或回显用户输入；只稳定认证任务生命周期和浏览器清理，不改变全新 Profile、Session 晋升门禁或批次续跑语义。
**关联**：`frontend/src/features/auth/auth-dialog.tsx`、`src/threadsnap/auth.py`、`tests/test_backend.py`

## 2026-08-18 — 等待认证批次直接进入全新登录环境
**总目标**：避免中途认证失效的批次再次打开已被采集门禁判定失效的旧 Profile，让“去认证”直接进入可重新登录的空白环境。
**状态**：✅ 批次认证入口默认创建全新隔离 Profile，平台配置中的主动认证仍保留既有 Profile 复用语义。
**干到哪里了**：
- [x] 认证 Dialog 新增入口级 `freshOnOpen` 语义；提取列表和批次详情的等待认证入口首个请求直接使用 `fresh=true`，页面加载失败后的重新创建也继续保持全新环境。
- [x] 全新环境显示“检测到批次中途认证失效”说明和既有状态标记；普通平台配置认证未传该参数，仍可复用正式 Profile 并手动切换全新环境。
- [x] 61 项后端测试、前端 TypeScript 检查和生产构建通过；真实批次 `20260818-142155-001` 在 3/10 等待状态点击“去认证”后，首屏直接显示官方手机号验证码登录页、`全新登录环境` 标记和认证失效说明，未再次展示旧圈子登录外观；当前源码重启后浏览器 `user-data-dir` 位于 `data/auth-profiles/dongchedi/tasks/<task-id>`，测试产生的错误 `None/` Profile 已在确认进程退出和路径位于工作区后清理。
**下一步**：用户在当前全新环境完成官方登录并执行“完成并校验”，门禁通过后同一批次按检查点续跑剩余 7 条。
**边界**：全新临时 Profile 在门禁通过前不替换正式 Profile 或 Session；关闭、失败或超时保持原批次 `waiting_for_auth`，不丢失已有 3 条快照。
**关联**：`CONTEXT.md`、`docs/adr/0007-official-login-and-encrypted-platform-session.md`、`docs/design/product-design.md`、`docs/design/technical-route.md`、`docs/chains/first-platform-delivery.md`、`frontend/src/features/auth/auth-dialog.tsx`

## 2026-08-18 — 认证窗口支持全新登录环境
**总目标**：处理旧浏览器 Profile 仍显示登录外观、但采集凭证已经失效时造成的认证误判，让用户直接进入不继承旧状态的登录环境。
**状态**：✅ 认证 Dialog 可创建全新隔离 Profile，旧正式 Profile 与 Session 在新门禁通过前保持不变。
**干到哪里了**：
- [x] 认证任务接口新增 `fresh=true`；请求全新环境时仅结束当前临时认证任务并创建新任务，不清理当前正式 Session。
- [x] Profile 准备流程新增 `inherit_current=False` 路径，空白任务目录不解密或复制正式 Profile；任务通过既有采集门禁后才按既有原子流程晋升为正式状态。
- [x] 认证 Dialog 始终提供“使用全新登录环境”，门禁失败后突出该入口并提示旧登录状态未通过采集校验；全新任务在头部显示状态标签。
- [x] 回归测试覆盖空白 Profile 不继承旧标记、正式加密 Profile 保留、普通认证任务复用及全新任务替换；61 项后端测试、正式代码 Ruff、`compileall`、`pip check`、前端 TypeScript 检查与生产构建、`git diff --check` 通过。
- [x] 真实浏览器确认普通环境显示入口，点击后 URL 回到官方登录页并呈现手机号验证码登录表单和“全新登录环境”标签；正式 Session 最近验证时间仍为 `2026-08-18 13:53:38`，服务重启清理未完成的测试临时环境后健康。
**下一步**：用户遇到旧登录外观但校验失败时，直接选择“使用全新登录环境”并重新登录，门禁通过后等待任务按原检查点续跑。
**边界**：不保存账号、密码或验证码；全新环境不提前覆盖、删除或降级当前正式 Profile 与 Session，关闭或服务重启只清理未晋升的明文任务目录。
**关联**：`CONTEXT.md`、`docs/design/product-design.md`、`src/threadsnap/auth.py`、`src/threadsnap/app.py`、`frontend/src/features/auth/auth-dialog.tsx`、`tests/test_backend.py`

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
