# 易车腾讯 WAF 完全协议化阶段结论

## 1. 目标与判定标准

本轮把“完全协议化”限定为：运行时不启动 Chrome、不加载腾讯 SDK/TDC 原始脚本，由普通 HTTP 客户端独立完成 challenge 初始化、双图取得、位移计算、行为与 TDC 参数生成、腾讯 verify、易车 `/WafCaptcha` 和原详情正文门禁。

只做到浏览器自动拖动、在 Node 中原样执行动态 TDC 字节码或腾讯 verify 返回 HTTP 200，都不计为完全协议化。腾讯 verify 只有业务 `errorCode="0"` 才算通过；之后还必须关闭易车正文门禁。

## 2. 已确认事实

### 2.1 请求链与字段

- `TCaptcha.js` 构造 prehandle 基础参数，frame 补充语言、入口 URL、媒体能力、WebWorker 能力、版本和 JSONP 回调。
- prehandle 返回当次 `sess`、`tdc_path`、`pow_cfg` 和 `dyn_show_info`；背景与精灵可由普通 HTTP 客户端直接取得。
- 滑块答案是单元素 JSON 数组：`elem_id=1`、`type=DynAnswerType_POS`、`data="X,Y"`。坐标来自当次 `fg_elem_list` 与图片，不是固定距离。
- PoW 为 `MD5(prefix + decimal_counter) == target`；提交 `pow_answer=prefix+counter` 和计算时长。
- verify 使用 form-urlencoded，已确认字段为 `collect/tlg/eks/sess/ans/pow_answer/pow_calc_time`，`vData` 是可选字段。
- 易车 WAF 页面把 `ret/ticket/randstr/seqid` 四行文本提交到 `/WafCaptcha`。

### 2.2 TDC 动态性

- 两次 TDC 响应的脚本长度、SHA-256、`TDC_NAME`、`info/eks`、VM payload 和入口均不同，TDC 不是可长期冻结的静态资产。
- VM payload 使用 base64、signed-varint 和 zigzag 编码。两份样本分别解出 92423 与 96474 个整数，入口分别为 43357 与 35616。
- 两轮解释器分别有 98 和 94 个 opcode case；解析字符串表并内联辅助运算后有 72 个 case 结构完全对应，而且这 72 个编号全部重排。解码和抽象语义识别流程可复用，单轮 opcode 编号表不应固化。
- 仅使用回环页面且拦截全部外部请求的离线浏览器 Oracle 已取得有效 7K 级 `collect`，并确认 `setData` 会改变长度和哈希；当前/冻结样本的动态覆盖分别达到 90/94 与 92/98 个 case。当前样本其余 4 个 case 的静态语义也已明确。
- Node 合成环境曾产出 603 字符 `collect`，同一轮真实浏览器为 7426 字符。差额来自尚未补齐的 Cookie、浏览器异步环境与事件采样，当前 Node 输出没有服务器接受证据。
- 运行时依赖至少包括 Canvas/WebGL、permissions、storage、UA-CH、speechSynthesis、WebRTC、WebGPU、位置、事件监听和定时器。

### 2.3 在线对照

- 既有浏览器对照曾取得腾讯业务成功并触发本地 `/WafCaptcha`，证明图片、拖动、verify 和回调链可以闭合。
- 本轮保存了 verify 原始表单形状；新增在线尝试得到业务 `errorCode=9` 和 `errorCode=12`，没有取得新的成功票据。达到有界取样后停止追加挑战。
- 图像识别暴露两类样本：单一强轮廓，以及“原图纹理区 + 目标缺口区”成对候选。识别器已增加精灵坐标输入、纹理相关和成对轮廓排除规则；三份冻结样本离线回归通过，在线成功仍待下一轮验证。

## 3. 复用边界

### 3.1 可复用

1. AppId 与 endpoint 状态机，但必须受脚本和响应字段哈希门禁约束。
2. prehandle 查询字段集合、双图取得方式、答案 JSON 结构、PoW 算法、verify form 编码与 WAF 四行正文结构。
3. TDC payload 的 base64、signed-varint、zigzag 解码器、解释器结构识别、辅助运算内联和抽象 opcode 目录生成方法。
4. 只使用回环页面的 TDC Oracle、分阶段指令覆盖统计和跨挑战语义差分方法。
5. 图像识别流程、响应分类、差分报告和版本失效门。

### 3.2 只能条件复用

1. `display_width`、精灵坐标和识别阈值必须以当次模板和 prehandle 配置为准。
2. TDC 解释器抽象语义仅在当次 AST 映射成立时复用；两份样本的 72 个完全同构 case 全部改号，不按固定 opcode 编号复用。
3. 轨迹只能复用生成策略，坐标、时间和事件序列必须逐次生成。

### 3.3 每次重取或重算

`sess`、`tdc_path` 全部动态查询值、TDC payload、`TDC_NAME`、`eks/info`、`tokenid`、双图及其签名、目标坐标、`ans`、PoW、`collect`、可选 `vData`、`ticket`、`randstr`、`seqid`、Cookie 和风控状态。

这些一次性结果只可保存为离线差分样本，不跨 challenge 用作运行时输入。

## 4. 当前结论与下一阶段

当前关闭了协议骨架、TDC 外层编码、抽象语义目录与离线动态覆盖，但没有关闭独立 TDC 执行器、纯 HTTP verify、易车 WAF POST 和原正文门禁，因此状态是“完全协议化进行中”，不是“已经完成”。

下一阶段只做自研 VM 执行器和 Node 环境适配；完成本地 Oracle 与 Node 的 `collect` 结构对照后，再用一个新 challenge 做单次纯 HTTP `errorCode=0` 验证。只有该门通过，才继续易车 `/WafCaptcha -> 原详情正文`。

生产行为不变，继续执行 ADR 0058 的控制分类、止损和原任务恢复；本研究不自动进入生产采集器。

## 5. Git 外证据

证据目录：`artifacts/poc/results/yiche-waf-protocolization/20260902-0001/`。

- 严格协议合同：`protocol-contract-v1.json`
- 详细复用矩阵：`reusability-matrix.md`
- 阶段报告：`progress-report.md`
- TDC 结构、运行时、VM 解码：`analysis/*tdc*.json`
- 浏览器 verify 对照：`analysis/accepted-verify-oracle.json`
- 脱敏和原始网络材料：`input/`、`requests/`

该目录由 Git 忽略；仓库只保留本汇总结论和可复核 SHA-256。

| 证据 | SHA-256 |
|---|---|
| `protocol-contract-v1.json` | `ab1e33d3d3c7259093259d3706b178ce6182e82a8cfb518b1e89ca54222edaa6` |
| `reusability-matrix.md` | `fdd45c060a0d5a02b7ed0e604596ee5e49a6b93501fc8c0cd2ebb84c38bb4725` |
| `progress-report.md` | `c71371d0be4da9d962cf84b9914c6be3ceb60497f3c1c53ced3e19b47d68dfe0` |
| `analysis/tdc-vm-decoded.json` | `c37766d9e01c3614138cd7dd7ef72a0ece9012290fc3cedb9e448a82a9f1d3b5` |
| `analysis/live-tdc-vm-decoded.json` | `dcfecbc0844d85689c7a982aea9984069c571b78ec2f70031f12c5b229cf9efc` |
| `analysis/live-tdc-vm-browser-trace.json` | `6f9cc168906a0d4dceaf677ec4d7235e5283f2fe307231fda385c228627ffd8d` |
| `analysis/frozen-tdc-vm-browser-trace.json` | `78f68dde4376d954cd47357d80ff51522805432f992d9ca9954c6f4d76a1aa1c` |
| `analysis/tdc-opcode-cross-challenge.json` | `d1e79b3e1ed45038c2c8f013c34cbd898dbd5b2ac1de2e1ccf55f66067ee8ff2` |
| `analysis/accepted-verify-oracle.json` | `668e8a10e55a7f498e6f6573733649e035d2d725eeee1cd9787407c117a0b3d1` |
