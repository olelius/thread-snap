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

- 2026-08-08：Linux 环境仍缺 CPU、内存、磁盘、语言运行时、浏览器系统依赖和进程管理信息；证据见 `docs/research/poc-input-intake-2026-08-08.md` 第 4 节。

---

## 2026-08-10 — 增加 Linux 双候选独立联通门

**总目标**：在目标服务器执行 2000 条测试前，先用最多 3 条已验证样本独立确认 Linux 环境、网络链路、两个固定框架的自动登录和真实帖子访问；失败时返回完整诊断包后再按证据修复。

**状态**：🟡 密码登录切换已在目标 Linux 生效；提交后仍停留登录页，正在补充可见二次验证诊断

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

**下一步**：生成提交后可见验证诊断热修包；目标服务器覆盖后复跑联通脚本，把新的诊断 `tar.gz` 和 `.sha256` 复制回来，通过脱敏截图和 `login-diagnostic.json` 确定二次验证或账号提示。只有复核为 `ready_for_2000=true` 后才运行首轮 2000 条。

**边界**：联通通过只证明当前服务器具备进入吞吐测试的网络、登录和内容访问条件，不构成 2000 条/小时门禁通过；两个固定候选技术、账号条件和结果契约保持不变。

**关联**：分支 `fix/linux-post-login-diagnostics`；入口 `poc/candidate-a/src/throughput.py`、`poc/candidate-b/src/throughput.ts`。

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
