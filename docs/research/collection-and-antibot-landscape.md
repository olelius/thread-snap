# Web 采集与反爬技术版图

## 1. 文档定位

本文用于梳理 Web 数据采集面对访问限制时的主要技术路线、代表性组件、优缺点和适用边界。

- 本文是技术调研，不代表 ThreadSnap 已经选定框架。
- “所有方法”无法字面穷尽；工具、浏览器和平台检测规则会持续变化，本文覆盖主要技术类别和有代表性的组件。
- 本文不提供破解动态签名、伪造设备指纹、自动破解验证码、轮换身份规避封禁等操作配置。
- 是否允许自动采集、可采集的数据范围和频率，应以平台规则、数据授权和实际访问条件为准。

## 2. 反爬系统通常检查什么

现代反爬并不只检查 IP。常见信号包括：

| 层次 | 典型信号 | 说明 |
|---|---|---|
| 网络层 | IP 信誉、自治域、地域、连接频率 | 更换 IP 只能改变其中一部分信号 |
| TLS/HTTP 层 | TLS 握手特征、HTTP 版本、请求头一致性 | 请求头和底层网络栈不一致也可能成为异常 |
| 浏览器层 | JavaScript 环境、浏览器能力、存储状态 | 真实浏览器也可能被识别为自动化 |
| 行为层 | 请求顺序、访问节奏、页面交互和会话轨迹 | 单次请求正常不代表长时间批量访问正常 |
| 账号层 | 登录状态、账号信誉、Cookie 生命周期 | 换 IP 不能消除账号侧限制 |
| 内容层 | URL 模式、重复访问、翻页深度 | 大量连续详情请求本身可能形成明显模式 |
| 完整性层 | 官方应用、设备和二进制完整性证明 | 移动端可能验证请求是否来自官方应用和真实设备 |

因此，不存在只安装一个组件就能稳定解决所有反爬问题的方案。

## 3. 数据获取路线

### 3.1 官方 API、数据授权或数据文件

**代表方式**：开放 API、合作接口、平台导出、定期数据文件。

**优点**

- 字段和调用额度相对明确；
- 最容易形成稳定吞吐量和验收指标；
- 维护成本最低；
- 不需要模拟浏览器。

**缺点**

- 可能不存在；
- 可能收费或需要商务合作；
- 字段范围受平台控制。

### 3.2 普通 HTTP 获取 HTML

**代表组件**

- Python：HTTPX、aiohttp、Scrapy；
- Node.js：Fetch/Undici、Crawlee HttpCrawler；
- Go：标准库 `net/http`、Colly。

**优点**

- 速度快、内存占用低；
- 适合大批量 URL；
- 易于设置超时、连接池和流式响应；
- 容易测试和部署。

**缺点**

- 不执行 JavaScript；
- 动态正文和评论可能不在 HTML 中；
- 依赖会话、临时参数或挑战页面时可能直接失败；
- HTML 结构变化会影响解析。

### 3.3 普通 HTTP 获取结构化数据响应

**代表方式**：在明确允许的访问条件下，使用页面正常加载时返回的 JSON 或其他结构化响应。

**优点**

- 字段结构比 DOM 稳定；
- 数据量小、解析快；
- 常能减少正文与评论的重复请求。

**缺点**

- 未公开请求可能随时变化；
- 可能依赖 Cookie、临时参数、签名或设备状态；
- 即使技术上可访问，也不等于平台允许外部批量调用；
- 不能据此承诺长期兼容。

### 3.4 浏览器网络响应采集

**代表组件**：Playwright、Puppeteer、Selenium/CDP。

**方式**：由浏览器正常加载页面，采集程序监听页面产生的网络响应并提取数据。

**优点**

- 能执行 JavaScript；
- 会话、Cookie 和页面运行环境由浏览器维护；
- 结构化响应通常比 DOM 更容易解析；
- 适合验证页面数据来源。

**缺点**

- 浏览器启动和运行成本高；
- 一个页面可能产生大量资源请求；
- 并发受 CPU 和内存限制；
- 仍可能触发账号、行为和浏览器自动化检测。

### 3.5 浏览器 DOM 采集

**代表组件**：Playwright、Puppeteer、Selenium、Scrapy-Playwright。

**优点**

- 能读取用户实际看到的渲染结果；
- 不依赖理解页面内部数据协议；
- 适合少量复杂交互页面。

**缺点**

- 通常是主要方案中速度最慢的一类；
- 选择器容易受页面改版影响；
- 懒加载、虚拟列表和弹层会增加复杂度；
- 大规模浏览器并发会显著增加机器成本。

### 3.6 页面截图、OCR 和视觉解析

**代表组件**：浏览器截图、OCR 引擎、视觉模型。

**优点**

- DOM 和结构化响应不可用时仍可能读取可见文本；
- 对 Canvas 或图片化内容有价值。

**缺点**

- 速度慢、准确率低于结构化数据；
- 字段关系和评论层级难以可靠还原；
- 成本高，不适合 2000 条/小时的常规主链路。

### 3.7 客户端流量分析

**代表工具**：浏览器开发者工具、Chrome DevTools Protocol、HAR、mitmproxy。

**优点**

- 可以确认正常客户端实际发出了哪些请求；
- 有助于判断正文和评论是否可以通过一个响应取得；
- 能发现重定向、会话过期和挑战响应。

**缺点**

- 只能证明客户端当前版本的行为；
- 应用可能使用证书绑定、设备完整性验证或加密协议；
- 分析结果不等于获得批量调用授权；
- 客户端升级后可能失效。

### 3.8 客户端或协议逆向

**典型内容**：分析动态参数、应用协议、二进制或请求签名。

**优点**

- 在部分场景中能解释普通 HTTP 请求为什么失败；
- 可以用于自有系统、获得授权的兼容性分析和安全测试。

**缺点**

- 开发和维护成本最高；
- 升级后容易失效；
- 可能涉及设备完整性、密钥和法律边界；
- 不适合作为低预算、固定价格和长期稳定的默认交付路线。

## 4. 爬虫框架比较

| 框架 | 语言 | 优点 | 缺点 | 主要定位 |
|---|---|---|---|---|
| Scrapy | Python | 成熟的调度器、中间件、Pipeline、AutoThrottle；适合大量 HTTP 请求 | 与现代浏览器自动化需要额外集成；Twisted 学习成本 | 大规模 HTTP 爬虫 |
| Scrapy-Playwright | Python | 保留 Scrapy 调度和数据管线，同时按请求使用 Playwright | 浏览器内存和生命周期管理更复杂 | HTTP 为主、部分动态页面 |
| Scrapling | Python | HTTP、动态浏览器、Spider、会话、自适应选择器集成度高 | 项目元数据仍标记 Beta；隐蔽性宣传必须目标实测 | 快速搭建混合采集器 |
| Crawlee | Node.js、Python | RequestQueue、HTTP/浏览器采集、并发和资源自适应完整 | 抽象较多；仍需自行实现业务数据模型 | 混合 HTTP/浏览器爬虫 |
| Colly | Go | 高并发、低资源、部署简单 | 动态 JavaScript 页面能力弱；生态偏 HTTP | 高吞吐静态页面 |
| Apache Nutch | Java | 分布式、可扩展、适合大规模索引和搜索 | 架构重，不适合少量指定 URL 的业务系统 | 搜索引擎式广域爬取 |
| 自建异步采集器 | 任意 | 能严格贴合业务，依赖少 | 队列、去重、统计和错误处理都要自己实现 | 范围很窄的固定目标 |

## 5. 浏览器自动化组件比较

| 组件 | 优点 | 缺点 |
|---|---|---|
| Playwright | 多浏览器支持、BrowserContext、网络监听、自动等待较完整 | 浏览器资源成本高；版本和浏览器二进制需要配套 |
| Puppeteer | Chromium/Chrome 生态直接，Node.js 使用简单 | 跨浏览器和多语言覆盖不如 Playwright |
| Selenium | 语言和浏览器覆盖广，企业测试生态成熟 | 对现代网络响应采集和上下文管理通常需要更多封装 |
| Chrome DevTools Protocol | 能直接观察 DOM、Runtime、Network 等底层域 | 协议变化快，抽象层低，维护成本高 |
| 远程浏览器服务 | 将浏览器资源和并发移到独立服务 | 持续费用、隐私和会话托管风险，仍不保证通过风控 |

## 6. 会话、网络与代理类别

### 6.1 固定会话与固定出口

**优点**：行为和登录状态一致，问题容易复现。
**缺点**：单一会话达到平台额度后没有额外容量。

### 6.2 合法账号的多会话

**优点**：业务隔离清晰，可以分别记录失败和授权状态。
**缺点**：需要明确账号授权；多会话不等于可以突破平台总量限制。

### 6.3 企业固定代理

**优点**：统一出口、审计和网络治理。
**缺点**：不提高平台允许的调用额度。

### 6.4 动态代理或 IP 池

**优点**：能改变网络出口，适用于明确允许的地域出口或容灾需求。
**缺点**：IP 信誉和地域不稳定；会话可能异常；平台仍可从账号、设备和行为识别；用于规避封禁时存在明显合规和维护风险。

## 7. 验证码与挑战处理类别

| 方式 | 优点 | 缺点 |
|---|---|---|
| 人工验证 | 准确、实现简单 | 无法形成完全无人值守吞吐 |
| 平台白名单或授权 | 最稳定 | 需要平台合作 |
| 第三方验证码服务 | 可自动化部分挑战 | 准确率、费用、隐私和合规风险；平台会持续升级 |
| 本地 OCR/模型 | 数据不离开本地 | 只适合部分简单图片验证码 |
| 浏览器挑战执行 | 能运行正常 JavaScript 流程 | 不等于一定通过行为检测或连续验证 |

第一版不应把自动验证码破解作为固定验收项。

## 8. 页面变化与数据解析组件

| 类别 | 代表组件 | 优点 | 缺点 |
|---|---|---|---|
| CSS/XPath | Cheerio、Parsel、lxml | 快、可测试 | 页面变化会失效 |
| 自适应选择器 | Scrapling adaptive parser | 能缓解局部 DOM 改版 | 不能修复接口、权限和语义变化 |
| JSON Schema | Ajv、Pydantic、Zod | 能发现字段缺失和类型变化 | 需要维护 Schema |
| 文本/OCR | Tesseract、视觉模型 | 可处理图片化文本 | 成本和误差较高 |
| LLM 提取 | 结构不稳定页面的语义抽取 | 对未知页面灵活 | 慢、费用高、结果需要校验 |

## 9. 调度、并发与可靠性组件

| 类别 | Python | Node.js | 作用 |
|---|---|---|---|
| 任务队列 | Celery、Dramatiq、RQ | BullMQ | 持久任务、并发工作进程 |
| 轻量并发 | asyncio、AnyIO | Promise、p-queue | 单进程 I/O 并发 |
| 请求节奏 | Scrapy AutoThrottle、aiolimiter | Crawlee 内置、Bottleneck | 控制并发和单位时间任务数 |
| 定时任务 | APScheduler | node-cron、BullMQ repeatable jobs | 固定周期触发 |
| 工作流 | Temporal | Temporal | 长任务、恢复和状态编排 |

并发组件只能提高客户端处理能力，不能提高平台允许的访问额度。

## 10. 响应识别、观测与测试

必须具备的工程能力：

- 不只根据状态码判断成功；
- 识别 200 状态的登录页、验证码页和挑战页；
- 校验正文和评论字段；
- 记录每个 URL 的请求次数、耗时和采集通道；
- 统计 401、403、429、重定向和异常空数据；
- 保存不含敏感凭证的错误摘要；
- 对 HTTP、浏览器网络响应和 DOM 三条通道分别统计成功率；
- 使用固定样本做回归测试；
- 通过断点和幂等避免重复访问已完成 URL。

代表组件：

- 日志：Pino、structlog；
- 指标：Prometheus client、OpenTelemetry；
- Schema：Pydantic、Zod、Ajv；
- 测试：pytest、Vitest、Playwright Test。

## 11. 方案优先级

从稳定性、成本和可维护性综合排序：

1. 官方授权接口或数据文件；
2. 普通 HTTP 获取公开 HTML；
3. 在允许范围内读取正常页面产生的结构化响应；
4. 浏览器网络响应采集；
5. 浏览器 DOM 采集；
6. OCR 或视觉解析；
7. 客户端/协议逆向。

顺序越靠后，通常开发、运行和长期维护成本越高，稳定性承诺越困难。

## 12. 对 ThreadSnap 的启示

- 每小时处理 2000 个帖子不是单纯的 Web 框架性能问题；
- 每帖最多十条一级评论能控制数据规模，但仍要验证评论是否与正文一次返回；
- 应先使用真实链接比较 HTTP、浏览器网络响应和 DOM 三种路线；
- 项目技术选型只保留 `Python + FastAPI + Scrapling` 与 `Node.js + TypeScript + Fastify + Crawlee + Playwright` 两个候选；
- 两个候选必须按 `collector-stack-poc-plan.md` 使用统一样本和实测指标决策，不能依据“隐蔽”宣传直接决定；
- 若必须依赖动态签名破解、自动验证码或身份轮换，当前固定预算和长期稳定验收边界需要重新评估；
- 候选框架确定前，本调研不应写成已确认技术路线。

## 13. 主要参考

- [Scrapy 架构](https://doc.scrapy.org/en/master/topics/architecture.html)
- [Scrapy AutoThrottle](https://doc.scrapy.org/en/latest/topics/autothrottle.html)
- [Scrapling 文档](https://scrapling.readthedocs.io/en/latest/)
- [Crawlee JavaScript PlaywrightCrawler](https://crawlee.dev/js/api/playwright-crawler)
- [Crawlee Python 指南](https://crawlee.dev/python/docs/guides)
- [Playwright BrowserContext](https://playwright.dev/docs/api/class-browsercontext)
- [Selenium WebDriver](https://www.selenium.dev/documentation/webdriver/browsers/)
- [Colly 文档](https://go-colly.org/docs/)
- [Apache Nutch](https://nutch.apache.org/)
- [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/)
- [mitmproxy 文档](https://docs.mitmproxy.org/stable/)
- [Cloudflare Bot Detection Engines](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)
- [Google Play Integrity API](https://developer.android.com/google/play/integrity)
