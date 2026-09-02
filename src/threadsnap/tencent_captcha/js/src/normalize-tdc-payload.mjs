import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import crypto from "node:crypto";
import { parse } from "@babel/parser";
import traverseModule from "@babel/traverse";
import generateModule from "@babel/generator";
import * as t from "@babel/types";

const traverse = traverseModule.default;
const generate = generateModule.default;
const root = path.resolve(import.meta.dirname, "..");
const input = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const reportOutput = output.replace(/\.js$/, ".json");
const source = fs.readFileSync(input, "utf8");
const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
const ast = parse(source, { sourceType: "script" });

const decoderName = ast.program.body.find(
  (node) => t.isFunctionDeclaration(node) && node.params.length === 2 && node.id,
)?.id?.name;
if (!decoderName) throw new Error("string decoder function not found");

// 解码器依赖前置字符串数组及轮转 IIFE。克隆 AST 并只摘除末尾 VM 启动表达式，
// 即可在隔离上下文中安全执行解码前置，而不启动当次 TDC 主程序。
const preludeAst = t.cloneNode(ast, true);
let removedIndex = -1;
for (let index = preludeAst.program.body.length - 1; index >= 0; index -= 1) {
  if (t.isExpressionStatement(preludeAst.program.body[index])) {
    removedIndex = index;
    preludeAst.program.body[index] = t.emptyStatement();
    break;
  }
}
if (removedIndex < 0) throw new Error("final VM invocation candidate not found");

const sandboxWindow = {};
const sandbox = {
  window: sandboxWindow,
  global: sandboxWindow,
  Date,
  Math,
  String,
  Object,
  Array,
  RegExp,
  Number,
  Boolean,
  Error,
  TypeError,
  Int8Array,
  Uint8Array,
  parseInt,
  parseFloat,
  isNaN,
  decodeURIComponent,
  encodeURIComponent,
  escape,
  unescape,
};
const prelude = generate(preludeAst, { compact: true, comments: false }).code;
vm.runInNewContext(prelude, sandbox, { timeout: 5000, filename: "tdc-normalize-prelude.js" });
if (typeof sandbox[decoderName] !== "function") throw new Error(`decoder ${decoderName} is not callable`);

const aliases = new Set([decoderName]);
let changed = true;
while (changed) {
  changed = false;
  traverse(ast, {
    VariableDeclarator(p) {
      if (t.isIdentifier(p.node.id) && t.isIdentifier(p.node.init) && aliases.has(p.node.init.name) && !aliases.has(p.node.id.name)) {
        aliases.add(p.node.id.name);
        changed = true;
      }
    },
    AssignmentExpression(p) {
      if (t.isIdentifier(p.node.left) && t.isIdentifier(p.node.right) && aliases.has(p.node.right.name) && !aliases.has(p.node.left.name)) {
        aliases.add(p.node.left.name);
        changed = true;
      }
    },
  });
}

let replacements = 0;
traverse(ast, {
  CallExpression(p) {
    if (!t.isIdentifier(p.node.callee) || !aliases.has(p.node.callee.name) || !t.isNumericLiteral(p.node.arguments[0])) return;
    let value;
    try {
      value = sandbox[decoderName](p.node.arguments[0].value);
    } catch {
      return;
    }
    if (typeof value !== "string") return;
    p.replaceWith(t.stringLiteral(value));
    replacements += 1;
  },
});

let payloadPath = null;
traverse(ast, {
  StringLiteral(p) {
    let statement = p;
    while (statement.parentPath && !statement.isExpressionStatement()) statement = statement.parentPath;
    if (!statement.isExpressionStatement()) return;
    if (!payloadPath || p.node.value.length > payloadPath.node.value.length) payloadPath = p;
  },
});
if (!payloadPath || payloadPath.node.value.length < 10000) throw new Error("resolved VM payload not found");
let invocationStatement = payloadPath;
while (invocationStatement.parentPath && !invocationStatement.isExpressionStatement()) invocationStatement = invocationStatement.parentPath;
if (!invocationStatement.isExpressionStatement()) throw new Error("resolved VM payload is not under an invocation statement");

const normalized = generate(ast, { comments: false, compact: false }).code + "\n";
fs.writeFileSync(output, normalized);
const report = {
  schemaVersion: 1,
  input: { relativePath: path.relative(root, input).replaceAll("\\", "/"), bytes: Buffer.byteLength(source), sha256: sha256(source) },
  decoderName,
  decoderAliases: [...aliases].sort(),
  replacements,
  removedPreludeExpressionIndex: removedIndex,
  payload: { encodedLength: payloadPath.node.value.length, encodedSha256: sha256(payloadPath.node.value), location: payloadPath.node.loc?.start ?? null },
  output: { relativePath: path.relative(root, output).replaceAll("\\", "/"), bytes: Buffer.byteLength(normalized), sha256: sha256(normalized) },
};
fs.writeFileSync(reportOutput, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ output, reportOutput, decoderName, aliasCount: aliases.size, replacements, payload: report.payload, outputSummary: report.output }, null, 2));
