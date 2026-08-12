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

- 2026-08-08：Linux 主机的 CPU 型号/核心数和正式项目进程管理方式仍待确认；内存、磁盘、Python 运行时与 PoC 浏览器健康检查已由后续实测补齐，原始入口见 `docs/research/poc-input-intake-2026-08-08.md` 第 4 节。

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
