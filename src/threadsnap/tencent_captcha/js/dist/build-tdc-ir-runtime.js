import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);
import {
  __toESM,
  require_lib,
  require_lib2,
  require_lib3,
  require_lib4
} from "./chunk-SQQ7JM6X.js";

// src/build-tdc-ir-runtime.mjs
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
var rawPath = path.resolve(process.argv[2]);
var interpreterPath = path.resolve(process.argv[3]);
var irPath = path.resolve(process.argv[4]);
var sampleName = process.argv[5] ?? "live";
var outputPath = path.resolve(process.argv[6] ?? path.join(root, "analysis", `${sampleName}-tdc-ir-runtime.js`));
var rawSource = fs.readFileSync(rawPath, "utf8");
var interpreterSource = fs.readFileSync(interpreterPath, "utf8");
var ir = JSON.parse(fs.readFileSync(irPath, "utf8"));
var sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
var sample = ir.samples.find((item) => item.name === sampleName);
if (!sample) throw new Error(`sample ${sampleName} missing from handler IR`);
var handlerById = new Map(ir.handlers.map((item) => [item.id, item]));
var interpreterAst = (0, import_parser.parse)(interpreterSource, { sourceType: "script" });
var protocolPreludeAssignments = [];
traverse(interpreterAst, {
  AssignmentExpression(p) {
    const left = p.node.left;
    if (!t.isMemberExpression(left) || !t.isIdentifier(left.object, { name: "window" })) return;
    if (!t.isStringLiteral(p.node.right) && !t.isFunctionExpression(p.node.right) && !t.isArrowFunctionExpression(p.node.right)) return;
    const assignment = t.cloneNode(p.node, true);
    if (t.isFunctionExpression(assignment.right) || t.isArrowFunctionExpression(assignment.right)) {
      if (assignment.right.params.length === 0) {
        assignment.right = t.functionExpression(null, [], t.blockStatement([t.returnStatement(t.newExpression(t.identifier("Date"), []))]));
      } else if (assignment.right.params.length === 2 && assignment.right.params.every((item) => t.isIdentifier(item))) {
        const [nameParam, argsParam] = assignment.right.params;
        assignment.right = t.functionExpression(null, [t.cloneNode(nameParam), t.cloneNode(argsParam)], t.blockStatement([
          t.returnStatement(t.callExpression(t.memberExpression(t.memberExpression(t.identifier("Date"), t.cloneNode(nameParam), true), t.identifier("apply")), [t.identifier("Date"), t.cloneNode(argsParam)]))
        ]));
      }
    }
    protocolPreludeAssignments.push(generate(t.expressionStatement(assignment), { compact: true, comments: false }).code);
  }
});
if (protocolPreludeAssignments.length < 4) throw new Error(`protocol prelude assignments incomplete: ${protocolPreludeAssignments.length}`);
var vmSwitch = null;
traverse(interpreterAst, {
  SwitchStatement(p) {
    const count = p.node.cases.filter((item) => t.isNumericLiteral(item.test)).length;
    if (!vmSwitch || count > vmSwitch.count) vmSwitch = { path: p, count };
  }
});
if (!vmSwitch || vmSwitch.count < 40) throw new Error("VM switch not found in interpreter");
var discriminant = vmSwitch.path.node.discriminant;
if (!t.isMemberExpression(discriminant) || !t.isIdentifier(discriminant.object) || !t.isUpdateExpression(discriminant.property) || !t.isIdentifier(discriminant.property.argument)) throw new Error("unexpected VM switch discriminant");
var codeName = discriminant.object.name;
var pcName = discriminant.property.argument.name;
var innerFunction = vmSwitch.path.getFunctionParent();
if (!innerFunction) throw new Error("inner VM function not found");
var outerFunction = innerFunction.parentPath.getFunctionParent();
if (!outerFunction || outerFunction.node.params.length < 5 || !outerFunction.node.params.every((item) => t.isIdentifier(item))) throw new Error("outer VM factory not found");
var outerParams = outerFunction.node.params.map((item) => item.name);
var recursiveName = null;
if (outerFunction.parentPath.isAssignmentExpression() && t.isIdentifier(outerFunction.parentPath.node.left)) recursiveName = outerFunction.parentPath.node.left.name;
if (outerFunction.parentPath.isVariableDeclarator() && t.isIdentifier(outerFunction.parentPath.node.id)) recursiveName = outerFunction.parentPath.node.id.name;
if (!recursiveName) throw new Error("recursive VM factory binding not found");
var regsName = null;
var undefinedName = null;
var exceptionStackName = null;
var localNames = [];
innerFunction.traverse({
  VariableDeclarator(p) {
    if (p.getFunctionParent() !== innerFunction || !t.isIdentifier(p.node.id)) return;
    localNames.push(p.node.id.name);
    if (t.isArrayExpression(p.node.init) && p.node.init.elements.length === 8 && p.node.init.elements.some((item) => t.isIdentifier(item, { name: codeName }))) regsName = p.node.id.name;
    else if (t.isUnaryExpression(p.node.init, { operator: "void" })) undefinedName = p.node.id.name;
    else if (t.isArrayExpression(p.node.init) && p.node.init.elements.length === 0 && !exceptionStackName) exceptionStackName = p.node.id.name;
  }
});
if (!regsName || !undefinedName || !exceptionStackName) throw new Error(`VM locals incomplete regs=${regsName} undefined=${undefinedName} stack=${exceptionStackName}`);
var currentErrorName = null;
innerFunction.traverse({
  CatchClause(p) {
    if (currentErrorName || !t.isIdentifier(p.node.param)) return;
    const caught = p.node.param.name;
    p.traverse({
      AssignmentExpression(assignment) {
        if (!currentErrorName && t.isIdentifier(assignment.node.left) && t.isIdentifier(assignment.node.right, { name: caught })) currentErrorName = assignment.node.left.name;
      }
    });
  }
});
if (!currentErrorName) throw new Error("current VM error binding not found");
var transpile = (canonicalSource, bindings) => {
  const ast = (0, import_parser.parse)(canonicalSource, { sourceType: "script", allowReturnOutsideFunction: true });
  traverse(ast, {
    Identifier(p) {
      const original = bindings[p.node.name];
      if (!original) return;
      if (p.parentPath.isCatchClause() && p.key === "param") return;
      p.replaceWith(t.memberExpression(t.identifier("v"), t.stringLiteral(original), true));
      p.skip();
    }
  });
  const code = generate(ast, { compact: true, comments: false }).code;
  const returns = ast.program.body.some((item) => t.isReturnStatement(item));
  return { code, returns };
};
var opcodeEntries = sample.opcodes.map((opcode) => {
  const handlers = opcode.handlers.map((occurrence) => {
    const definition = handlerById.get(occurrence.id);
    if (!definition) throw new Error(`handler ${occurrence.id} missing`);
    const transpiled = transpile(definition.canonicalSource, occurrence.identifierBindings);
    return `{id:${JSON.stringify(occurrence.id)},returns:${transpiled.returns},run:function(v){${transpiled.code}}}`;
  });
  return `${JSON.stringify(opcode.opcode)}:[${handlers.join(",")}]`;
});
var allBindings = /* @__PURE__ */ new Set();
for (const opcode of sample.opcodes) for (const handler of opcode.handlers) for (const original of Object.values(handler.identifierBindings)) allBindings.add(original);
var config = { codeName, pcName, regsName, undefinedName, exceptionStackName, currentErrorName, recursiveName, outerParams, localNames, allBindings: [...allBindings].sort() };
var rawAst = (0, import_parser.parse)(rawSource, { sourceType: "script" });
var payloadPath = null;
traverse(rawAst, {
  StringLiteral(p) {
    let statement = p;
    while (statement.parentPath && !statement.isExpressionStatement()) statement = statement.parentPath;
    if (!statement.isExpressionStatement()) return;
    if (!payloadPath || p.node.value.length > payloadPath.node.value.length) payloadPath = p;
  }
});
if (!payloadPath || payloadPath.node.value.length < 1e4) throw new Error("VM payload not found");
var invocationStatement = payloadPath;
while (invocationStatement.parentPath && !invocationStatement.isExpressionStatement()) invocationStatement = invocationStatement.parentPath;
if (!invocationStatement.isExpressionStatement() || !t.isCallExpression(invocationStatement.node.expression) || !t.isCallExpression(invocationStatement.node.expression.callee)) throw new Error("VM invocation shape not found");
var factoryInvocation = invocationStatement.node.expression.callee;
factoryInvocation.callee = t.callExpression(t.identifier("__tdcCreateVm"), [t.stringLiteral(payloadPath.node.value)]);
var invocation = generate(invocationStatement.node, { compact: true, comments: false }).code;
var runtime = `
${protocolPreludeAssignments.join("\n")}
(function(w){try{var n=Date.now?Date.now:function(){return +new Date();};if(w&&!w.__TDC_PROTECT_T0)w.__TDC_PROTECT_T0=n();}catch(e){}})(window);
function __tdcDecode(payload){
  var binary=atob(payload),signed=[],i;
  for(i=0;i<binary.length;i++){var byte=binary.charCodeAt(i);signed.push(byte>127?byte-256:byte);}
  var out=[];
  for(i=0;i<signed.length;){var value=0,shift=0,complete=false;
    for(var count=0;count<5&&i<signed.length;count++){var item=signed[i++];value|=(item&127)<<shift;if(item>=0){complete=true;break;}shift+=7;}
    if(!complete)throw new Error("unterminated signed varint");out.push((value>>>1)^-(value&1));
  }
  return out;
}
var __tdcOpcodeHandlers={${opcodeEntries.join(",")}};
var __tdcConfig=${JSON.stringify(config)};
function __tdcCreateVm(payload){
  var code=__tdcDecode(payload),errorPcStack=[],savedPc;
  function factory(offset,capturedArgs,globalObject,constants,errorHandler){
    return function vmFunction(){
      var v=Object.create(null),name;
      for(name of __tdcConfig.allBindings)v[name]=void 0;
      v.Object=Object;v.String=String;v.Array=Array;
      v[__tdcConfig.codeName]=code;v[__tdcConfig.pcName]=offset;v[__tdcConfig.recursiveName]=factory;
      v[__tdcConfig.outerParams[0]]=offset;v[__tdcConfig.outerParams[1]]=capturedArgs;v[__tdcConfig.outerParams[2]]=globalObject;v[__tdcConfig.outerParams[3]]=constants;v[__tdcConfig.outerParams[4]]=errorHandler;
      v[__tdcConfig.undefinedName]=void 0;v[__tdcConfig.exceptionStackName]=[];
      v[__tdcConfig.regsName]=[globalObject,constants,capturedArgs,this,arguments,vmFunction,code,0];
      while(true){
        try{
          while(true){
            var opcode=code[++v[__tdcConfig.pcName]],handlers=__tdcOpcodeHandlers[opcode];
            if(!handlers)throw new Error("unknown opcode "+opcode+" at "+v[__tdcConfig.pcName]);
            for(var h of handlers){var result=h.run(v);if(h.returns)return result;}
          }
        }catch(error){
          if(v[__tdcConfig.exceptionStackName].length>0){savedPc=v[__tdcConfig.pcName];errorPcStack=[];}
          v[__tdcConfig.currentErrorName]=error;errorPcStack.push(v[__tdcConfig.pcName]);
          if(v[__tdcConfig.exceptionStackName].length===0)throw errorHandler?errorHandler(error,v[__tdcConfig.regsName],errorPcStack):error;
          v[__tdcConfig.pcName]=v[__tdcConfig.exceptionStackName].pop();errorPcStack.pop();
        }
      }
    };
  }
  return factory;
}
${invocation}
`;
fs.writeFileSync(outputPath, runtime.trimStart());
console.log(JSON.stringify({ output: outputPath, sha256: sha256(fs.readFileSync(outputPath)), bytes: Buffer.byteLength(runtime.trimStart()), sampleName, opcodeCount: sample.opcodeCount, handlerCount: ir.handlerCount, protocolPreludeAssignmentCount: protocolPreludeAssignments.length, config }, null, 2));
