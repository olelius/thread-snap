import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);
import {
  __toESM,
  require_lib,
  require_lib2,
  require_lib3,
  require_lib4
} from "./chunk-SQQ7JM6X.js";

// src/catalog-tdc-primitives.mjs
var import_parser = __toESM(require_lib(), 1);
var import_traverse = __toESM(require_lib4(), 1);
var import_generator = __toESM(require_lib3(), 1);
var t = __toESM(require_lib2(), 1);
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
var traverse = import_traverse.default.default;
var generate = import_generator.default.default;
var root = path.resolve(import.meta.dirname, "..");
var input = path.resolve(process.argv[2]);
var output = path.resolve(process.argv[3] ?? path.join(root, "analysis", "tdc-primitive-catalog.json"));
var source = fs.readFileSync(input, "utf8");
var ast = (0, import_parser.parse)(source, { sourceType: "script" });
var sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
var helperFunctions = /* @__PURE__ */ new Map();
var helperConstants = /* @__PURE__ */ new Map();
var collectHelpers = () => {
  helperFunctions.clear();
  helperConstants.clear();
  traverse(ast, {
    VariableDeclarator(p) {
      if (!t.isIdentifier(p.node.id) || !t.isObjectExpression(p.node.init)) return;
      for (const property of p.node.init.properties) {
        if (!t.isObjectProperty(property)) continue;
        const key = t.isIdentifier(property.key) ? property.key.name : t.isStringLiteral(property.key) ? property.key.value : null;
        if (key === null) continue;
        const identity = `${p.node.id.name}.${key}`;
        const value = property.value;
        const returnStatement = (t.isFunctionExpression(value) || t.isArrowFunctionExpression(value)) && t.isBlockStatement(value.body) ? value.body.body.at(-1) : null;
        const harmlessPrelude = (t.isFunctionExpression(value) || t.isArrowFunctionExpression(value)) && t.isBlockStatement(value.body) ? value.body.body.slice(0, -1).every((item) => t.isVariableDeclaration(item)) : false;
        if ((t.isFunctionExpression(value) || t.isArrowFunctionExpression(value)) && t.isBlockStatement(value.body) && harmlessPrelude && t.isReturnStatement(returnStatement) && returnStatement.argument && value.params.every((param) => t.isIdentifier(param))) {
          helperFunctions.set(identity, { params: value.params.map((param) => param.name), expression: returnStatement.argument });
        } else if (t.isStringLiteral(value) || t.isNumericLiteral(value) || t.isBooleanLiteral(value) || t.isNullLiteral(value)) {
          helperConstants.set(identity, value);
        }
      }
    }
  });
};
var memberIdentity = (node) => {
  if (!t.isMemberExpression(node) || !t.isIdentifier(node.object)) return null;
  const key = !node.computed && t.isIdentifier(node.property) ? node.property.name : t.isStringLiteral(node.property) ? node.property.value : null;
  return key === null ? null : `${node.object.name}.${key}`;
};
var substitute = (expression, params, args) => {
  const map = new Map(params.map((name, index) => [name, args[index] ?? t.identifier("undefined")]));
  const wrapper = t.file(t.program([t.expressionStatement(t.cloneNode(expression, true))]));
  traverse(wrapper, {
    Identifier(p) {
      if (!p.isReferencedIdentifier() || !map.has(p.node.name)) return;
      p.replaceWith(t.cloneNode(map.get(p.node.name), true));
      p.skip();
    }
  });
  return wrapper.program.body[0].expression;
};
for (let pass = 0; pass < 12; pass += 1) {
  collectHelpers();
  let changed = 0;
  traverse(ast, {
    CallExpression: {
      exit(p) {
        const helper = helperFunctions.get(memberIdentity(p.node.callee));
        if (!helper) return;
        p.replaceWith(substitute(helper.expression, helper.params, p.node.arguments));
        changed += 1;
      }
    },
    MemberExpression(p) {
      if (p.parentPath.isCallExpression({ callee: p.node })) return;
      const value = helperConstants.get(memberIdentity(p.node));
      if (!value) return;
      p.replaceWith(t.cloneNode(value, true));
      changed += 1;
    }
  });
  if (changed === 0) break;
}
var vmSwitch = null;
traverse(ast, {
  SwitchStatement(p) {
    const count = p.node.cases.filter((item) => t.isNumericLiteral(item.test)).length;
    if (!vmSwitch || count > vmSwitch.count) vmSwitch = { path: p, count };
  }
});
if (!vmSwitch || vmSwitch.count < 40) throw new Error("VM switch not found");
var splitStatement = (statement) => {
  if (t.isBreakStatement(statement)) return [];
  if (t.isExpressionStatement(statement) && t.isSequenceExpression(statement.expression)) {
    return statement.expression.expressions.map((expression) => t.expressionStatement(expression));
  }
  return [statement];
};
var canonicalize = (value) => {
  const identifiers = /* @__PURE__ */ new Map();
  const visit = (item, parent = null, parentKey = null) => {
    if (Array.isArray(item)) return item.map((child) => visit(child, parent, parentKey));
    if (!item || typeof item !== "object") return item;
    if (item.type === "Identifier") {
      const isStaticMemberProperty = parent?.type === "MemberExpression" && parentKey === "property" && !parent.computed;
      const isStaticObjectKey = (parent?.type === "ObjectProperty" || parent?.type === "ObjectMethod") && parentKey === "key" && !parent.computed;
      if (isStaticMemberProperty || isStaticObjectKey) return { type: "Identifier", name: item.name };
      if (!identifiers.has(item.name)) identifiers.set(item.name, `I${identifiers.size}`);
      return { type: "Identifier", name: identifiers.get(item.name) };
    }
    const result = {};
    for (const [key, child] of Object.entries(item)) {
      if (["start", "end", "loc", "extra", "leadingComments", "trailingComments", "innerComments"].includes(key)) continue;
      result[key] = visit(child, item, key);
    }
    return result;
  };
  return visit(value);
};
var canonicalSource = (statement) => {
  const wrapper = t.file(t.program([t.cloneNode(statement, true)]));
  const identifiers = /* @__PURE__ */ new Map();
  traverse(wrapper, {
    enter(p) {
      delete p.node.extra;
      delete p.node.leadingComments;
      delete p.node.trailingComments;
      delete p.node.innerComments;
    },
    Identifier(p) {
      const parent = p.parent;
      const isStaticMemberProperty = t.isMemberExpression(parent) && p.key === "property" && !parent.computed;
      const isStaticObjectKey = (t.isObjectProperty(parent) || t.isObjectMethod(parent)) && p.key === "key" && !parent.computed;
      if (isStaticMemberProperty || isStaticObjectKey) return;
      if (!identifiers.has(p.node.name)) identifiers.set(p.node.name, `I${identifiers.size}`);
      p.node.name = identifiers.get(p.node.name);
    }
  });
  return {
    source: generate(wrapper.program.body[0], { compact: true, comments: false }).code,
    bindings: Object.fromEntries([...identifiers.entries()].map(([original, canonical]) => [canonical, original]).sort((a, b) => a[0].localeCompare(b[0])))
  };
};
var cases = vmSwitch.path.node.cases.filter((item) => t.isNumericLiteral(item.test)).map((item) => {
  const primitives = item.consequent.flatMap(splitStatement).map((statement, index) => {
    const code = generate(statement, { compact: true }).code;
    const canonical = canonicalize(statement);
    const normalized = canonicalSource(statement);
    return { index, source: code, sourceSha256: sha256(code), canonicalSource: normalized.source, identifierBindings: normalized.bindings, astStructuralSha256: sha256(JSON.stringify(canonical)), structuralSha256: sha256(normalized.source) };
  });
  return {
    opcode: item.test.value,
    primitiveCount: primitives.length,
    primitiveSequenceSha256: sha256(JSON.stringify(primitives.map((primitive) => primitive.structuralSha256))),
    primitives
  };
});
var allPrimitives = cases.flatMap((item) => item.primitives);
var report = {
  schemaVersion: 1,
  input: { relativePath: path.relative(root, input).replaceAll("\\", "/"), sha256: sha256(source) },
  opcodeCount: cases.length,
  primitiveOccurrenceCount: allPrimitives.length,
  uniquePrimitiveCount: new Set(allPrimitives.map((item) => item.structuralSha256)).size,
  cases
};
fs.writeFileSync(output, `${JSON.stringify(report, null, 2)}
`);
console.log(JSON.stringify({ output, sha256: sha256(fs.readFileSync(output)), opcodeCount: report.opcodeCount, primitiveOccurrenceCount: report.primitiveOccurrenceCount, uniquePrimitiveCount: report.uniquePrimitiveCount }, null, 2));
