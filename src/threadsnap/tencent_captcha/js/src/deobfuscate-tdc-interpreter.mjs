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
const input = path.resolve(process.argv[2] ?? path.join(root, "input", "10-tdc.js-9987ff0d34a7.js"));
const output = path.resolve(process.argv[3] ?? path.join(root, "analysis", "tdc-interpreter-deobfuscated.js"));
const reportOutput = output.replace(/\.js$/, ".json");
const source = fs.readFileSync(input, "utf8");
const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
const ast = parse(source, { sourceType: "script" });

let longestPath = null;
traverse(ast, {
  StringLiteral(p) {
    let statement = p;
    while (statement.parentPath && !statement.isExpressionStatement()) statement = statement.parentPath;
    if (!statement.isExpressionStatement()) return;
    if (!longestPath || p.node.value.length > longestPath.node.value.length) longestPath = p;
  },
});
if (!longestPath || longestPath.node.value.length < 10000) throw new Error("VM payload literal not found");
let invocationStatement = longestPath;
while (invocationStatement && !invocationStatement.isExpressionStatement()) invocationStatement = invocationStatement.parentPath;
if (!invocationStatement?.isExpressionStatement()) throw new Error("VM invocation statement not found");
const removedPayload = {
  encodedLength: longestPath.node.value.length,
  encodedSha256: sha256(longestPath.node.value),
  location: longestPath.node.loc?.start ?? null,
};
invocationStatement.replaceWith(t.emptyStatement());

const functionCandidates = new Map();
traverse(ast, {
  FunctionDeclaration(p) {
    if (p.node.id) functionCandidates.set(p.node.id.name, { params: p.node.params.length, numericCalls: 0 });
  },
  CallExpression(p) {
    if (!t.isIdentifier(p.node.callee) || !t.isNumericLiteral(p.node.arguments[0])) return;
    const candidate = functionCandidates.get(p.node.callee.name);
    if (candidate) candidate.numericCalls += 1;
  },
});
const decoderName = ast.program.body.find(
  (node) => t.isFunctionDeclaration(node) && node.params.length === 2 && node.id,
)?.id?.name;
if (!decoderName) throw new Error("string decoder function not found");

const prelude = generate(ast, { compact: true, comments: false }).code;
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
  TypeError,
  Int8Array,
  Uint8Array,
  parseInt,
  decodeURIComponent,
  encodeURIComponent,
};
vm.runInNewContext(prelude, sandbox, { timeout: 5000, filename: "tdc-prelude.js" });
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
const resolvedValues = new Map();
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
    resolvedValues.set(value, (resolvedValues.get(value) ?? 0) + 1);
    p.replaceWith(t.stringLiteral(value));
    replacements += 1;
  },
});

traverse(ast, {
  MemberExpression(p) {
    if (!p.node.computed || !t.isStringLiteral(p.node.property)) return;
    if (!t.isValidIdentifier(p.node.property.value)) return;
    p.node.computed = false;
    p.node.property = t.identifier(p.node.property.value);
  },
});

const deobfuscated = generate(ast, { comments: false, retainLines: false, compact: false }).code + "\n";
fs.writeFileSync(output, deobfuscated);

const resolvedStrings = [...resolvedValues.entries()]
  .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  .map(([value, count]) => ({ value, count }));
const report = {
  schemaVersion: 1,
  input: { relativePath: path.relative(root, input).replaceAll("\\", "/"), bytes: Buffer.byteLength(source), sha256: sha256(source) },
  removedPayload,
  decoderName,
  decoderAliases: [...aliases].sort(),
  replacements,
  resolvedStrings,
  output: { relativePath: path.relative(root, output).replaceAll("\\", "/"), bytes: Buffer.byteLength(deobfuscated), sha256: sha256(deobfuscated) },
};
fs.writeFileSync(reportOutput, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ output, reportOutput, decoderName, aliasCount: aliases.size, replacements, resolvedStrings, outputSummary: report.output }, null, 2));
