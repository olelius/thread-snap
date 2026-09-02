import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);
import {
  __toESM,
  require_lib,
  require_lib2,
  require_lib3,
  require_lib4
} from "./chunk-SQQ7JM6X.js";

// src/deobfuscate-tdc-interpreter.mjs
var import_parser = __toESM(require_lib(), 1);
var import_traverse = __toESM(require_lib4(), 1);
var import_generator = __toESM(require_lib3(), 1);
var t = __toESM(require_lib2(), 1);
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import crypto from "node:crypto";
var traverse = import_traverse.default.default;
var generate = import_generator.default.default;
var root = path.resolve(import.meta.dirname, "..");
var input = path.resolve(process.argv[2] ?? path.join(root, "input", "10-tdc.js-9987ff0d34a7.js"));
var output = path.resolve(process.argv[3] ?? path.join(root, "analysis", "tdc-interpreter-deobfuscated.js"));
var reportOutput = output.replace(/\.js$/, ".json");
var source = fs.readFileSync(input, "utf8");
var sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
var ast = (0, import_parser.parse)(source, { sourceType: "script" });
var longestPath = null;
traverse(ast, {
  StringLiteral(p) {
    let statement = p;
    while (statement.parentPath && !statement.isExpressionStatement()) statement = statement.parentPath;
    if (!statement.isExpressionStatement()) return;
    if (!longestPath || p.node.value.length > longestPath.node.value.length) longestPath = p;
  }
});
if (!longestPath || longestPath.node.value.length < 1e4) throw new Error("VM payload literal not found");
var invocationStatement = longestPath;
while (invocationStatement && !invocationStatement.isExpressionStatement()) invocationStatement = invocationStatement.parentPath;
if (!invocationStatement?.isExpressionStatement()) throw new Error("VM invocation statement not found");
var removedPayload = {
  encodedLength: longestPath.node.value.length,
  encodedSha256: sha256(longestPath.node.value),
  location: longestPath.node.loc?.start ?? null
};
invocationStatement.replaceWith(t.emptyStatement());
var functionCandidates = /* @__PURE__ */ new Map();
traverse(ast, {
  FunctionDeclaration(p) {
    if (p.node.id) functionCandidates.set(p.node.id.name, { params: p.node.params.length, numericCalls: 0 });
  },
  CallExpression(p) {
    if (!t.isIdentifier(p.node.callee) || !t.isNumericLiteral(p.node.arguments[0])) return;
    const candidate = functionCandidates.get(p.node.callee.name);
    if (candidate) candidate.numericCalls += 1;
  }
});
var decoderName = ast.program.body.find(
  (node) => t.isFunctionDeclaration(node) && node.params.length === 2 && node.id
)?.id?.name;
if (!decoderName) throw new Error("string decoder function not found");
var prelude = generate(ast, { compact: true, comments: false }).code;
var sandboxWindow = {};
var sandbox = {
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
  encodeURIComponent
};
vm.runInNewContext(prelude, sandbox, { timeout: 5e3, filename: "tdc-prelude.js" });
if (typeof sandbox[decoderName] !== "function") throw new Error(`decoder ${decoderName} is not callable`);
var aliases = /* @__PURE__ */ new Set([decoderName]);
var changed = true;
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
    }
  });
}
var replacements = 0;
var resolvedValues = /* @__PURE__ */ new Map();
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
  }
});
traverse(ast, {
  MemberExpression(p) {
    if (!p.node.computed || !t.isStringLiteral(p.node.property)) return;
    if (!t.isValidIdentifier(p.node.property.value)) return;
    p.node.computed = false;
    p.node.property = t.identifier(p.node.property.value);
  }
});
var deobfuscated = generate(ast, { comments: false, retainLines: false, compact: false }).code + "\n";
fs.writeFileSync(output, deobfuscated);
var resolvedStrings = [...resolvedValues.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([value, count]) => ({ value, count }));
var report = {
  schemaVersion: 1,
  input: { relativePath: path.relative(root, input).replaceAll("\\", "/"), bytes: Buffer.byteLength(source), sha256: sha256(source) },
  removedPayload,
  decoderName,
  decoderAliases: [...aliases].sort(),
  replacements,
  resolvedStrings,
  output: { relativePath: path.relative(root, output).replaceAll("\\", "/"), bytes: Buffer.byteLength(deobfuscated), sha256: sha256(deobfuscated) }
};
fs.writeFileSync(reportOutput, `${JSON.stringify(report, null, 2)}
`);
console.log(JSON.stringify({ output, reportOutput, decoderName, aliasCount: aliases.size, replacements, resolvedStrings, outputSummary: report.output }, null, 2));
