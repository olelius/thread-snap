import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const basePath = path.resolve(process.argv[2]);
const catalogPath = path.resolve(process.argv[3]);
const sampleName = process.argv[4] ?? "candidate";
const outputPath = path.resolve(process.argv[5]);
const base = JSON.parse(fs.readFileSync(basePath, "utf8"));
const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
const bySignature = new Map(base.handlers.map((handler) => [handler.signature, handler]));
let nextHandlerNumber = Math.max(...base.handlers.map((handler) => Number.parseInt(handler.id.replace(/^H/, ""), 10))) + 1;
const addedHandlers = [];
const opcodes = catalog.cases.map((item) => ({
  opcode: item.opcode,
  handlers: item.primitives.map((primitive) => {
    let handler = bySignature.get(primitive.structuralSha256);
    if (!handler) {
      handler = {
        id: `H${String(nextHandlerNumber).padStart(2, "0")}`,
        signature: primitive.structuralSha256,
        canonicalSource: primitive.canonicalSource,
        samples: [sampleName],
        occurrenceCount: 0,
        occurrences: [],
        reviewStatus: "structurally-derived",
      };
      nextHandlerNumber += 1;
      base.handlers.push(handler);
      bySignature.set(handler.signature, handler);
      addedHandlers.push({ id: handler.id, signature: handler.signature, canonicalSource: handler.canonicalSource });
    }
    if (handler.reviewStatus === "structurally-derived") {
      handler.occurrenceCount += 1;
      handler.occurrences.push({ sample: sampleName, opcode: item.opcode, primitiveIndex: primitive.index, identifierBindings: primitive.identifierBindings });
    }
    return { id: handler.id, identifierBindings: primitive.identifierBindings };
  }),
}));
base.handlerCount = base.handlers.length;
base.samples = base.samples.filter((item) => item.name !== sampleName);
base.samples.push({ name: sampleName, opcodeCount: catalog.opcodeCount, opcodes });
base.extendedFrom = {
  handlerIrSha256: crypto.createHash("sha256").update(fs.readFileSync(basePath)).digest("hex"),
  primitiveCatalogSha256: crypto.createHash("sha256").update(fs.readFileSync(catalogPath)).digest("hex"),
};
fs.writeFileSync(outputPath, `${JSON.stringify(base, null, 2)}\n`);
console.log(JSON.stringify({
  output: outputPath,
  sha256: crypto.createHash("sha256").update(fs.readFileSync(outputPath)).digest("hex"),
  sampleName,
  opcodeCount: catalog.opcodeCount,
  primitiveOccurrenceCount: catalog.primitiveOccurrenceCount,
  handlerCount: base.handlerCount,
  missingCount: 0,
  addedHandlerCount: addedHandlers.length,
  addedHandlers,
}, null, 2));
