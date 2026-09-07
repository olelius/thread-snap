# Third-party notices

## React Bits

首页统计卡片与侧栏品牌的局部光晕、首页首次数字过渡参考并改编 React Bits 的
`SpotlightCard`、`CountUp` TypeScript 版本；保留项目主题和统计语义，不引入整站背景引擎。

- Project: <https://github.com/DavidHDev/react-bits>
- Pinned revision: `0e69e737242df1d257b4e5e399b01ae1d7901375`
- Copyright (c) 2026 David Haz
- License: MIT + Commons Clause License Condition v1.0（非纯 MIT）
- 完整许可与来源：[react-bits.txt](frontend/public/third-party/react-bits.txt)，随两种前端构建一并发布。
- 本地适配：主题语义色、无重渲染的指针坐标、键盘焦点和减少动态效果；计数只用于已取得的真实值，后续刷新不重播。

## forged-in-prod

ThreadSnap 的项目流控制规则和模板结构参考：

- Project: `SPHINX998/forged-in-prod`
- Source: <https://github.com/SPHINX998/forged-in-prod>
- Pinned revision: `31c80e763541e1526aa9f6ca8692bd344ddff62d`
- License: MIT

```text
MIT License

Copyright (c) 2026 SPHINX998

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## PaddlePaddle / PaddleNLP

本地轻量文字舆情分析使用 PaddlePaddle、PaddleNLP、UIE-Senta-Nano 与
UTC-Nano：

- PaddlePaddle: <https://github.com/PaddlePaddle/Paddle>
- PaddleNLP: <https://github.com/PaddlePaddle/PaddleNLP>
- License: Apache License 2.0

## json-repair

DeepSeek 严格工具参数的结构恢复使用 `json-repair`：

- Project: <https://github.com/mangiucugna/json_repair>
- Version: `0.62.0`
- License: MIT

```text
MIT License

Copyright (c) 2023 Stefano Baccianella

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Babel / esbuild

腾讯验证码 TDC 的平台无关生产运行时使用 Babel 解析与转换 JavaScript AST，并在发布前
使用 esbuild 生成不携带 `node_modules` 的 Node.js bundle：

- Babel parser, traverse, generator and types: <https://github.com/babel/babel>
- Versions: `7.28.3` / `7.28.4`
- esbuild: <https://github.com/evanw/esbuild>
- Version: `0.25.9`
- License: MIT
