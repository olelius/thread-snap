# 易车腾讯 WAF 完全协议化最终结论

## 1. 判定

本轮 `P0-P5` 全部通过，“完全协议化研究”已完成。这里的严格口径是：不启动 Chrome，不执行腾讯 `TCaptcha.js`、frame/dy 脚本或原始 TDC 脚本，以普通 HTTP、图像算法和自研 IR/VM 完成：

`当前易车 WAF -> prehandle -> 当次双图 -> 位移 -> PoW -> TDC IR -> collect/eks -> 腾讯 verify -> 易车 /WafCaptcha -> 原 URL 正文`。

动态 `tdc.js` 仍是逐 challenge 的协议响应，必须取得；实现只把它解析成 payload、入口、常量、opcode 与结构 handler 映射，再交给自研 VM，不把供应商脚本放入执行路径。

## 2. 最终证据

### 2.1 自研 TDC（P3）

- 已建立 base64、signed-varint、zigzag payload 解码、外壳归一化、解释器结构提取、canonical handler 签名、IR 编译、自研 VM 与 Node 环境适配。
- 冻结与动态基线分别包含 98 和 94 个 opcode；72 个同构 case 的数字编号全部重排，证明必须按结构映射而不是固定 opcode 表。
- 第三个动态 94-opcode 样本中，自研 IR 与原响应在离线 Chrome Oracle 下具有相同 TDC API、环境访问与 Base64 明文块长度。
- 新 101-opcode 外壳把 174056 字符 payload 间接藏在字符串数组中；归一化器成功解析，IR 自动吸收新增的“寄存器间大于等于”结构，总计 75 个 handler。
- 该 101-opcode 自研运行时在线生成 6590 字符 `collect`，腾讯业务接受；随后另一份新 94-opcode/74-handler challenge 也被接受。P3 因服务器业务成功而关闭，不再以和 Chrome 逐字节相同作为门槛。

### 2.2 腾讯纯 HTTP verify（P4）

- 101-opcode challenge：背景 29794 字节、精灵 26933 字节；识别为 `sourceX=448/sourceY=176`，PoW counter 为 158867；verify HTTP 200、`errorCode="0"`。
- 完整 P5 中的新 challenge：背景 43970 字节、精灵 41333 字节；识别为 `sourceX=358/sourceY=136`，PoW counter 为 79544；verify 再次 HTTP 200、`errorCode="0"`。
- 两轮均由普通 HTTP + 自研 TDC 路径完成；业务成功而非仅 HTTP 200 是接受门。

### 2.3 易车 WAF 与原正文（P5）

- 同一易车 FetcherSession 首个详情请求命中当前 WAF，取得当次 169 字符 `seqid`。
- 随即新建腾讯 challenge 并取得 463 字符 ticket、4 字符 randstr；四行正文提交 `/WafCaptcha` 返回 HTTP 200。
- 重载原 URL 返回 HTTP 200、100469 字节正文；WAF 分类为 false，帖子身份与正文/媒体证明成立。
- 从命中 WAF 到正文门禁关闭实测 5.221 秒，这是单次环境观测。
- POST 前后 Cookie 名称和值哈希均没有变化；本轮放行是既有风险状态与当次 `seqid/ticket` 的服务端更新，不是产生一个可长期复用的新 Cookie。
- 对照轮次使用“旧 ticket + 后取得的新 seqid”，POST 同为 200，但重载仍为 WAF。通过轮次严格采用“当前 WAF/seqid -> 新 challenge/ticket -> POST -> reload”。因此同轮顺序属于协议合同。

## 3. 可复用结果

1. AppId、endpoint 状态机和严格成功分类。
2. prehandle 参数构造、JSONP 解析、双图 URL/精灵几何解析。
3. 纹理与轮廓结合的位移识别算法；每张新图仍重新计算。
4. `DynAnswerType_POS` 答案 JSON、MD5 PoW、verify form-urlencoded 和 WAF 四行正文格式。
5. TDC 直接/间接外壳归一化、payload 解码、结构 handler 目录、opcode 重映射、IR 编译、自研 VM 和环境适配层。
6. 缓出轨迹生成策略、响应分类、版本漂移门和原正文验收门。

## 4. 每次 challenge 必须重取或重算

`sess`、`tdc_path` 动态参数、payload/入口/opcode 映射、`eks/info`、环境采样、事件轨迹、`collect`、双图、坐标、PoW、ticket、randstr、seqid、Cookie 快照和服务端风险状态。

旧 ticket、旧 seqid、旧 collect、旧 eks、旧图片或坐标只用于离线回归，不作为新 challenge 输入。WAF 放行结果也不应被解释成一个可以长期保存并跨轮复用的验证码 Cookie。

## 5. 失效门

以下任一变化都触发重新冻结与目标场景验证：AppId、prehandle 字段、图片/模板几何、TDC 外层 AST 家族、payload 编码、入口形状、新 handler 结构、答案 data type、verify 字段或 errorCode 语义、WAF 四行模板、seqid 形状、正文分类标志、Node 环境画像。

IR 扩展器会把未知结构标成 `structurally-derived`；它仍需经过腾讯 `errorCode="0"` 和易车正文门，而不是仅凭 AST 生成即宣布兼容。

## 6. 生产决策

本次关闭的是隔离研究门。生产继续执行 ADR 0058 的控制分类、首控止损、静默或人工恢复，当前不接入自动验证码链。若以后进入生产，需要单独确认产品范围、ADR、版本探针、熔断回退、敏感材料生命周期、负载与易车正式 500 条影响验收。

## 7. Git 外证据

证据根目录：`artifacts/poc/results/yiche-waf-protocolization/20260902-0001/`。

| 证据 | SHA-256 |
|---|---|
| `acceptance.json` | `302fe545003ab48a8fc75388762c6b48a43bd3cca5f7086d0324286f7b4aa76d` |
| `protocol-contract-v1.json` | `a7331f09d26ff1df840f3485d48322eac47f83485afec626e6a52f30b19d7cde` |
| `progress-report.md` | `5c6a847af544c0a0e7ded75f94162c3ad04905b2307676b60a9b1e1d4cdc2a32` |
| `reusability-matrix.md` | `becbdc26cba665487962e1d6b57c89da3a732e63d6d581da6c84a6bc95ef7637` |
| `requests/pure-http-attempt-ir-v2/report.json` | `a994a5d8012aa2812963ae8780a2add94bf02fa575444b2479236b54c2d7faa4` |
| `requests/yiche-waf-gate-v2/tencent/report.json` | `0b4c9474d5149a10a37a78a65a13d1b07bb4c40f779ba641e9ffe2cf5a6441e1` |
| `requests/yiche-waf-gate-v2/report.json` | `9b15ef19345d88f8e7b7b72d108314cb659b37b254b323ef21dc7ae401b34a83` |
| `requests/pure-http-attempt-ir-v2/analysis/tdc-handler-ir-candidate.json` | `b9e56c656933a026c02658699471c4277f2ee70475e3b9b3d53217e88f5a4983` |

原始 ticket、sess、表单、图片、正文与 Cookie 证据仅保存在被 Git 忽略的目录；仓库文档只记录脱敏字段、哈希和门禁结论。
