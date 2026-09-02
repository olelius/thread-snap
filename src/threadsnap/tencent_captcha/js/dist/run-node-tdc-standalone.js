import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);

// src/run-node-tdc-standalone.mjs
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
var root = path.resolve(import.meta.dirname, "..");
var input = path.resolve(process.argv[2]);
var output = path.resolve(process.argv[3] ?? path.join(root, "analysis", "node-tdc-standalone.json"));
var source = fs.readFileSync(input, "utf8");
var sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
var accesses = /* @__PURE__ */ new Map();
var encodingCalls = [];
var challengeEncryptCalls = [];
var jsonStringifyCalls = [];
var fixtureApiCalls = [];
var registeredEvents = /* @__PURE__ */ new Map();
var eventDispatches = [];
var record = (pathName) => accesses.set(pathName, (accesses.get(pathName) ?? 0) + 1);
var noop = () => void 0;
var browserMath = {};
Object.defineProperties(browserMath, Object.getOwnPropertyDescriptors(Math));
Object.defineProperty(browserMath, "tanh", {
  configurable: true,
  writable: true,
  value(value) {
    if (value === 0.7) return 0.6043677771171635;
    if (value === 0.8) return 0.6640367702678489;
    if (value === 0.9) return 0.7162978701990244;
    return Math.tanh(value);
  }
});
var eventTarget = (label) => {
  const listeners = /* @__PURE__ */ new Map();
  return {
    addEventListener(type, callback) {
      if (typeof callback !== "function") return;
      const key = String(type);
      if (!listeners.has(key)) listeners.set(key, /* @__PURE__ */ new Set());
      listeners.get(key).add(callback);
      registeredEvents.set(`${label}.${key}`, (registeredEvents.get(`${label}.${key}`) ?? 0) + 1);
    },
    removeEventListener(type, callback) {
      listeners.get(String(type))?.delete(callback);
    },
    dispatchEvent(event) {
      const item = event ?? {};
      if (!item.type) return true;
      if (!item.target) Object.defineProperty(item, "target", { configurable: true, value: this });
      Object.defineProperty(item, "currentTarget", { configurable: true, value: this });
      eventDispatches.push({ target: label, type: String(item.type), x: item.clientX ?? null, y: item.clientY ?? null, buttons: item.buttons ?? null });
      for (const callback of [...listeners.get(String(item.type)) ?? []]) callback.call(this, item);
      return !item.defaultPrevented;
    },
    _listeners: listeners
  };
};
var storage = () => {
  const values = /* @__PURE__ */ new Map();
  return {
    get length() {
      return values.size;
    },
    key: (index) => [...values.keys()][index] ?? null,
    getItem: (key) => values.get(String(key)) ?? null,
    setItem: (key, value) => values.set(String(key), String(value)),
    removeItem: (key) => values.delete(String(key)),
    clear: () => values.clear()
  };
};
var element = (tagName = "div") => ({
  ...eventTarget(`element:${String(tagName).toLowerCase()}`),
  tagName: tagName.toUpperCase(),
  nodeType: 1,
  style: {},
  children: [],
  childNodes: [],
  appendChild(child) {
    this.children.push(child);
    this.childNodes.push(child);
    return child;
  },
  removeChild: noop,
  setAttribute: noop,
  getAttribute: () => null,
  getBoundingClientRect: () => ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
  canPlayType(type = "") {
    const value = String(type).toLowerCase();
    if (value.includes("theora") || value.includes("mp4v") && !value.includes("mp4a")) return "";
    if (value.includes("m4a") || value.includes("mp4a") && value.includes("audio/mp4")) return "maybe";
    if (/aac|mpeg|mp3|vorbis|opus|wav|flac|webm|avc1|h264|hvc1|hev1|hevc|vp8|vp9|av01/.test(value)) return "probably";
    return "";
  }
});
var canvas = element("canvas");
var canvas2d = {
  fillStyle: "#000000",
  font: "10px sans-serif",
  textBaseline: "alphabetic",
  fillRect: noop,
  clearRect: noop,
  fillText: noop,
  strokeText: noop,
  beginPath: noop,
  arc: noop,
  rect: noop,
  moveTo: noop,
  lineTo: noop,
  quadraticCurveTo: noop,
  bezierCurveTo: noop,
  closePath: noop,
  fill: noop,
  stroke: noop,
  clip: noop,
  save: noop,
  restore: noop,
  rotate: noop,
  translate: noop,
  scale: noop,
  isPointInPath: () => false,
  measureText: (text) => ({ width: String(text).length * 6 }),
  getImageData: () => ({ data: new Uint8ClampedArray(16), width: 2, height: 2 })
};
var webgl = {
  VENDOR: 7936,
  RENDERER: 7937,
  VERSION: 7938,
  SHADING_LANGUAGE_VERSION: 35724,
  getParameter(parameter) {
    return { 7936: "Node Fixture Vendor", 7937: "Node Fixture Renderer", 7938: "WebGL 1.0", 35724: "WebGL GLSL ES 1.0" }[parameter] ?? 0;
  },
  getSupportedExtensions: () => ["ANGLE_instanced_arrays", "EXT_blend_minmax", "EXT_color_buffer_half_float", "EXT_float_blend", "EXT_frag_depth", "EXT_shader_texture_lod", "EXT_texture_filter_anisotropic", "OES_element_index_uint", "OES_standard_derivatives", "OES_texture_float", "OES_texture_float_linear", "OES_texture_half_float", "OES_texture_half_float_linear", "OES_vertex_array_object", "WEBGL_color_buffer_float", "WEBGL_compressed_texture_s3tc", "WEBGL_debug_renderer_info", "WEBGL_debug_shaders", "WEBGL_depth_texture", "WEBGL_draw_buffers", "WEBGL_lose_context", "WEBGL_multi_draw"],
  getExtension: () => null
};
canvas.getContext = (kind) => {
  fixtureApiCalls.push(`canvas.getContext:${kind}`);
  return kind === "2d" ? canvas2d : kind?.includes("webgl") ? webgl : null;
};
canvas.toDataURL = () => {
  fixtureApiCalls.push("canvas.toDataURL");
  return `data:image/png;base64,${"A".repeat(8344)}`;
};
var entryUrl = process.argv[6] ?? "https://www.example.test/fixture";
var location = { href: "https://captcha.gtimg.com/static/template/drag_ele.f15e4d0f.html", origin: "https://captcha.gtimg.com", protocol: "https:", host: "captcha.gtimg.com", hostname: "captcha.gtimg.com", port: "", pathname: "/static/template/drag_ele.f15e4d0f.html", search: "", hash: "", toString() {
  return this.href;
} };
var document = {
  ...eventTarget("document"),
  URL: location.href,
  location,
  referrer: entryUrl,
  cookie: "",
  readyState: "loading",
  visibilityState: "visible",
  hidden: false,
  body: element("body"),
  head: element("head"),
  documentElement: { clientWidth: 360, clientHeight: 360, scrollTop: 0, scrollLeft: 0, clientTop: 0, clientLeft: 0 },
  createElement: (tag) => String(tag).toLowerCase() === "canvas" ? canvas : element(String(tag)),
  createElementNS: (_namespace, tag) => element(String(tag)),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  hasFocus: () => true
};
var pdfMimeTypes = [
  { type: "application/pdf", suffixes: "pdf", description: "Portable Document Format" },
  { type: "text/pdf", suffixes: "pdf", description: "Portable Document Format" }
];
var pluginNames = ["PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer", "Microsoft Edge PDF Viewer", "WebKit built-in PDF"];
var pluginList = pluginNames.map((name) => {
  const plugin = [...pdfMimeTypes.map((mime) => ({ ...mime }))];
  Object.assign(plugin, { name, filename: "internal-pdf-viewer", description: "Portable Document Format", item: (index) => plugin[index] ?? null, namedItem: (type) => plugin.find((mime) => mime.type === type) ?? null });
  return plugin;
});
pluginList.item = (index) => pluginList[index] ?? null;
pluginList.namedItem = (name) => pluginList.find((plugin) => plugin.name === name) ?? null;
var mimeTypeList = pdfMimeTypes.map((mime) => ({ ...mime, enabledPlugin: pluginList[0] }));
mimeTypeList.item = (index) => mimeTypeList[index] ?? null;
mimeTypeList.namedItem = (type) => mimeTypeList.find((mime) => mime.type === type) ?? null;
var navigatorBase = {
  appName: "Netscape",
  userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
  appVersion: "5.0 (Windows)",
  platform: "Win32",
  vendor: "Google Inc.",
  language: "zh-CN",
  languages: ["zh-CN"],
  hardwareConcurrency: 20,
  deviceMemory: 32,
  maxTouchPoints: 0,
  cookieEnabled: true,
  webdriver: false,
  plugins: pluginList,
  mimeTypes: mimeTypeList,
  pdfViewerEnabled: true,
  onLine: true,
  doNotTrack: null,
  connection: { downlink: 1.5, effectiveType: "4g", rtt: 100, saveData: false, addEventListener: noop, removeEventListener: noop },
  mozConnection: null,
  webkitConnection: null,
  mediaDevices: { enumerateDevices: async () => [] },
  geolocation: { getCurrentPosition: (_success, error) => error?.({ code: 1, message: "denied" }) },
  getBattery: async () => ({ charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1, addEventListener: noop, removeEventListener: noop }),
  permissions: { query: async () => ({ state: "prompt", addEventListener: noop }) },
  storage: { estimate: async () => ({ quota: 6442450944, usage: 0, usageDetails: {} }) },
  userAgentData: {
    brands: [{ brand: "Not=A?Brand", version: "99" }, { brand: "Google Chrome", version: "151" }, { brand: "Chromium", version: "151" }],
    mobile: false,
    platform: "Windows",
    getHighEntropyValues: async () => ({ architecture: "x86", bitness: "64", brands: [{ brand: "Not=A?Brand", version: "99" }, { brand: "Google Chrome", version: "151" }, { brand: "Chromium", version: "151" }], fullVersionList: [{ brand: "Not=A?Brand", version: "99.0.0.0" }, { brand: "Google Chrome", version: "151.0.7922.175" }, { brand: "Chromium", version: "151.0.7922.175" }], mobile: false, model: "", platform: "Windows", platformVersion: "10.0", uaFullVersion: "151.0.7922.175", wow64: false })
  },
  gpu: {
    requestAdapter: async () => ({
      features: /* @__PURE__ */ new Set(["depth32float-stencil8", "rg11b10ufloat-renderable", "texture-formats-tier1", "bgra8unorm-storage", "texture-compression-bc", "dual-source-blending", "core-features-and-limits", "float32-filterable", "indirect-first-instance", "float32-blendable", "depth-clip-control", "texture-compression-bc-sliced-3d", "timestamp-query", "clip-distances", "texture-formats-tier2", "shader-f16", "primitive-index", "texture-component-swizzle", "subgroups"]),
      limits: {
        maxTextureDimension1D: 16384,
        maxTextureDimension2D: 16384,
        maxTextureDimension3D: 2048,
        maxTextureArrayLayers: 2048,
        maxBindGroups: 4,
        maxBindGroupsPlusVertexBuffers: 24,
        maxBindingsPerBindGroup: 1e3,
        maxDynamicUniformBuffersPerPipelineLayout: 10,
        maxDynamicStorageBuffersPerPipelineLayout: 8,
        maxSampledTexturesPerShaderStage: 48,
        maxSamplersPerShaderStage: 16,
        maxStorageBuffersPerShaderStage: 16,
        maxStorageTexturesPerShaderStage: 8,
        maxUniformBuffersPerShaderStage: 12,
        maxUniformBufferBindingSize: 65536,
        maxStorageBufferBindingSize: 2147483644,
        minUniformBufferOffsetAlignment: 256,
        minStorageBufferOffsetAlignment: 256,
        maxVertexBuffers: 8,
        maxBufferSize: 2147483648,
        maxVertexAttributes: 30,
        maxVertexBufferArrayStride: 2048,
        maxInterStageShaderVariables: 28,
        maxColorAttachments: 8,
        maxColorAttachmentBytesPerSample: 128,
        maxComputeWorkgroupStorageSize: 32768,
        maxComputeInvocationsPerWorkgroup: 1024,
        maxComputeWorkgroupSizeX: 1024,
        maxComputeWorkgroupSizeY: 1024,
        maxComputeWorkgroupSizeZ: 64,
        maxComputeWorkgroupsPerDimension: 65535,
        maxImmediateSize: 64,
        maxStorageBuffersInFragmentStage: 16,
        maxStorageTexturesInFragmentStage: 8,
        maxStorageBuffersInVertexStage: 16,
        maxStorageTexturesInVertexStage: 8
      },
      isFallbackAdapter: false,
      info: { vendor: "nvidia", architecture: "ampere", device: "", description: "", subgroupMaxSize: 32, subgroupMinSize: 32 },
      requestAdapterInfo: async () => ({ vendor: "nvidia", architecture: "ampere", device: "", description: "", subgroupMaxSize: 32, subgroupMinSize: 32 }),
      requestDevice: async () => ({ features: /* @__PURE__ */ new Set(), limits: {}, lost: new Promise(() => {
      }), destroy: noop })
    })
  }
};
var navigator = new Proxy(navigatorBase, { get(target, key, receiver) {
  record(`navigator.${String(key)}`);
  return Reflect.get(target, key, receiver);
} });
var performanceOrigin = Date.now();
var performance = { timeOrigin: performanceOrigin, now: () => Date.now() - performanceOrigin, timing: {}, getEntriesByType: () => [], memory: { jsHeapSizeLimit: 4294705152, totalJSHeapSize: 1e7, usedJSHeapSize: 8e6 } };
var fixtureVoices = [
  [true, "zh-CN", "Microsoft Huihui - Chinese (Simplified, PRC)"],
  [false, "en-US", "Microsoft Mark - English (United States)"],
  [false, "en-US", "Microsoft Zira - English (United States)"],
  [false, "en-US", "Microsoft David - English (United States)"],
  [false, "zh-CN", "Microsoft Kangkang - Chinese (Simplified, PRC)"],
  [false, "zh-CN", "Microsoft Yaoyao - Chinese (Simplified, PRC)"]
].map(([isDefault, lang, name]) => ({ default: isDefault, lang, localService: true, name, voiceURI: name }));
var voiceReady = false;
var voiceChangeHandler = null;
var speechSynthesis = {
  getVoices: () => voiceReady ? fixtureVoices : [],
  addEventListener: noop,
  removeEventListener: noop,
  get onvoiceschanged() {
    return voiceChangeHandler;
  },
  set onvoiceschanged(handler) {
    voiceChangeHandler = handler;
    setTimeout(() => {
      voiceReady = true;
      if (typeof voiceChangeHandler === "function") voiceChangeHandler();
    }, 0);
  }
};
var windowEvents = eventTarget("window");
var fixtureCrypto = {
  getRandomValues(array) {
    fixtureApiCalls.push(`crypto.getRandomValues:${array?.byteLength ?? 0}`);
    return crypto.webcrypto.getRandomValues(array);
  },
  randomUUID: () => crypto.randomUUID(),
  subtle: {
    async digest(algorithm, data) {
      fixtureApiCalls.push(`crypto.subtle.digest:${data?.byteLength ?? 0}`);
      const bytes = Buffer.from(data.buffer ?? data, data.byteOffset ?? 0, data.byteLength ?? void 0);
      return crypto.webcrypto.subtle.digest(algorithm, bytes);
    }
  }
};
var AnalyserNode = class {
  constructor(context) {
    this.context = context;
    this.fftSize = 2048;
    this.frequencyBinCount = 1024;
    this.minDecibels = -100;
    this.maxDecibels = -30;
    this.smoothingTimeConstant = 0.8;
    this.numberOfInputs = 1;
    this.numberOfOutputs = 1;
    this.channelCount = 2;
    this.channelCountMode = "max";
    this.channelInterpretation = "speakers";
    return new Proxy(this, { get(target, key, receiver) {
      fixtureApiCalls.push(`Analyser.get:${String(key)}`);
      return Reflect.get(target, key, receiver);
    }, set(target, key, value, receiver) {
      fixtureApiCalls.push(`Analyser.set:${String(key)}`);
      return Reflect.set(target, key, value, receiver);
    } });
  }
  connect() {
    return this;
  }
  disconnect() {
  }
  getFloatFrequencyData(array) {
    array.fill(-100);
  }
  getByteFrequencyData(array) {
    array.fill(10);
  }
  getFloatTimeDomainData(array) {
    array.fill(0);
  }
  getByteTimeDomainData(array) {
    array.fill(128);
  }
};
var AudioContext = class {
  constructor() {
    fixtureApiCalls.push("AudioContext.constructor");
    this.baseLatency = 0.01;
    this.outputLatency = 0;
    this.sampleRate = 48e3;
    this.state = "running";
    this.currentTime = 0;
    this.destination = { context: this, maxChannelCount: 2, numberOfInputs: 1, numberOfOutputs: 0, channelCount: 2, channelCountMode: "explicit", channelInterpretation: "speakers" };
    return new Proxy(this, { get(target, key, receiver) {
      fixtureApiCalls.push(`AudioContext.get:${String(key)}`);
      return Reflect.get(target, key, receiver);
    } });
  }
  createAnalyser() {
    fixtureApiCalls.push("AudioContext.createAnalyser");
    return new AnalyserNode(this);
  }
  createOscillator() {
    fixtureApiCalls.push("AudioContext.createOscillator");
    return { type: "sine", frequency: { value: 0, setValueAtTime: noop }, detune: { value: 0 }, connect() {
      return this;
    }, disconnect: noop, start: noop, stop: noop };
  }
  createDynamicsCompressor() {
    fixtureApiCalls.push("AudioContext.createDynamicsCompressor");
    return { threshold: { value: -24, setValueAtTime: noop }, knee: { value: 30, setValueAtTime: noop }, ratio: { value: 12, setValueAtTime: noop }, attack: { value: 3e-3, setValueAtTime: noop }, release: { value: 0.25, setValueAtTime: noop }, reduction: 0, connect() {
      return this;
    }, disconnect: noop };
  }
  createGain() {
    return { gain: { value: 1, setValueAtTime: noop }, connect() {
      return this;
    }, disconnect: noop };
  }
  createBuffer(channels = 1, length = 1024, sampleRate = this.sampleRate) {
    const values = Array.from({ length: channels }, () => new Float32Array(length));
    return { length, duration: length / sampleRate, sampleRate, numberOfChannels: channels, getChannelData: (channel) => values[channel] };
  }
  close() {
    fixtureApiCalls.push("AudioContext.close");
    this.state = "closed";
    return Promise.resolve();
  }
  resume() {
    this.state = "running";
    return Promise.resolve();
  }
};
var OfflineAudioContext = class extends AudioContext {
  constructor(channels = 1, length = 44100, sampleRate = 44100) {
    super();
    this.length = length;
    this.sampleRate = sampleRate;
    this.destination.maxChannelCount = channels;
    this.currentTime = 0;
  }
  startRendering() {
    const data = new Float32Array(this.length);
    for (let index = 0; index < data.length; index++) data[index] = Math.sin(index / 19) * 1e-5;
    const buffer = { length: this.length, duration: this.length / this.sampleRate, sampleRate: this.sampleRate, numberOfChannels: 1, getChannelData: () => data };
    setTimeout(() => this.oncomplete?.({ renderedBuffer: buffer }), 0);
    return Promise.resolve(buffer);
  }
};
Object.defineProperty(AudioContext.prototype, Symbol.toStringTag, { value: "AudioContext" });
Object.defineProperty(OfflineAudioContext.prototype, Symbol.toStringTag, { value: "OfflineAudioContext" });
Object.defineProperty(AnalyserNode.prototype, Symbol.toStringTag, { value: "AnalyserNode" });
var sandbox = {
  ...windowEvents,
  console: { log: noop, warn: noop, error: noop },
  document,
  navigator,
  location,
  localStorage: storage(),
  sessionStorage: storage(),
  screen: { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040, availLeft: 0, availTop: 0, colorDepth: 24, pixelDepth: 24, orientation: { angle: 0, type: "landscape-primary" } },
  performance,
  Math: browserMath,
  crypto: fixtureCrypto,
  speechSynthesis,
  chrome: { app: {}, runtime: {}, loadTimes: void 0, csi: void 0 },
  visualViewport: { width: 1280, height: 900, scale: 1, offsetLeft: 0, offsetTop: 0, pageLeft: 0, pageTop: 0, addEventListener: noop, removeEventListener: noop },
  indexedDB: void 0,
  devicePixelRatio: 1,
  innerWidth: 360,
  innerHeight: 360,
  outerWidth: 516,
  outerHeight: 360,
  pageXOffset: 0,
  pageYOffset: 0,
  getComputedStyle: () => ({}),
  matchMedia: () => ({ matches: false, media: "", addEventListener: noop, removeEventListener: noop }),
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  requestAnimationFrame: (callback) => setTimeout(() => callback(performance.now()), 0),
  cancelAnimationFrame: clearTimeout,
  atob: (value) => Buffer.from(value, "base64").toString("binary"),
  btoa: (value) => {
    const input2 = String(value);
    const result = Buffer.from(input2, "binary").toString("base64");
    encodingCalls.push({
      api: "btoa",
      inputLength: input2.length,
      inputSha256: sha256(input2),
      inputHexPrefix: Buffer.from(input2, "binary").subarray(0, 96).toString("hex"),
      printableRatio: input2.length ? [...input2].filter((character) => {
        const code = character.charCodeAt(0);
        return code >= 32 && code <= 126;
      }).length / input2.length : 1,
      outputLength: result.length,
      outputSha256: sha256(result)
    });
    return result;
  },
  Blob,
  URL,
  TextEncoder,
  TextDecoder,
  JSON: {
    ...JSON,
    stringify(value, replacer, space) {
      const result = JSON.stringify(value, replacer, space);
      jsonStringifyCalls.push({ type: typeof value, outputLength: typeof result === "string" ? result.length : null, output: typeof result === "string" && result.length <= 12e3 ? result : null, stack: new Error().stack });
      return result;
    },
    parse: JSON.parse
  },
  Event: class Event {
    constructor(type, init = {}) {
      this.type = type;
      Object.assign(this, init);
    }
  },
  MouseEvent: class MouseEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.bubbles = init.bubbles ?? true;
      this.cancelable = init.cancelable ?? true;
      this.defaultPrevented = false;
      this.timeStamp = performance.now();
      this.isTrusted = false;
      this.movementX = init.movementX ?? 0;
      this.movementY = init.movementY ?? 0;
      this.offsetX = init.offsetX ?? init.clientX ?? 0;
      this.offsetY = init.offsetY ?? init.clientY ?? 0;
      this.layerX = init.layerX ?? init.clientX ?? 0;
      this.layerY = init.layerY ?? init.clientY ?? 0;
      Object.assign(this, init);
    }
    preventDefault() {
      this.defaultPrevented = true;
    }
    stopPropagation() {
    }
  },
  PointerEvent: class PointerEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.bubbles = init.bubbles ?? true;
      this.cancelable = init.cancelable ?? true;
      this.defaultPrevented = false;
      this.timeStamp = performance.now();
      this.isTrusted = false;
      Object.assign(this, init);
    }
    preventDefault() {
      this.defaultPrevented = true;
    }
    stopPropagation() {
    }
  },
  CustomEvent: class CustomEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.detail = init.detail;
    }
  },
  Image: class Image extends Object {
  },
  HTMLElement: class HTMLElement {
  },
  HTMLCanvasElement: class HTMLCanvasElement {
  },
  WebGLRenderingContext: class WebGLRenderingContext {
  },
  WebGL2RenderingContext: class WebGL2RenderingContext {
  },
  ImageData: class ImageData {
    constructor(data = new Uint8ClampedArray(), width = 0, height = 0) {
      this.data = data;
      this.width = width;
      this.height = height;
    }
  },
  AudioContext,
  webkitAudioContext: AudioContext,
  OfflineAudioContext,
  webkitOfflineAudioContext: OfflineAudioContext,
  Worker: void 0,
  SharedWorker: void 0,
  WebSocket: void 0,
  RTCPeerConnection: class RTCPeerConnection {
    constructor() {
      this.localDescription = null;
      this.onicecandidate = null;
      this.iceGatheringState = "new";
    }
    createDataChannel() {
      return { close: noop };
    }
    async createOffer() {
      return { type: "offer", sdp: `v=0\r
o=- 1 2 IN IP4 127.0.0.1\r
s=-\r
t=0 0\r
a=ice-ufrag:fixture\r
a=ice-pwd:fixturefixturefixture\r
${"a=x-fixture:1\r\n".repeat(22)}` };
    }
    async setLocalDescription(description) {
      this.localDescription = description;
      this.iceGatheringState = "complete";
      setTimeout(() => {
        this.onicecandidate?.({ candidate: { candidate: "candidate:2324087492 1 udp 2113937151 fixture.local 53868 typ host generation 0 ufrag fixture network-cost 999", address: "fixture.local", protocol: "udp", type: "host", toJSON() {
          return { candidate: this.candidate, sdpMid: "0", sdpMLineIndex: 0, usernameFragment: "fixture" };
        } } });
        this.onicecandidate?.({ candidate: null });
      }, 0);
    }
    addEventListener(name, callback) {
      if (name === "icecandidate") this.onicecandidate = callback;
    }
    removeEventListener() {
    }
    close() {
    }
  },
  TCaptchaIframeClientPos: { x: 459, y: 239, width: 360, height: 360 },
  TCaptchaReferrer: entryUrl
};
var challengeEncryptValue;
Object.defineProperty(sandbox, "ChallengeEncrypt", {
  configurable: false,
  enumerable: true,
  get: () => challengeEncryptValue,
  set: (value) => {
    if (typeof value !== "function") {
      challengeEncryptValue = value;
      return;
    }
    challengeEncryptValue = function(...args) {
      const summarizeArgument = (item) => ({ type: typeof item, length: typeof item === "string" || Array.isArray(item) ? item.length : null, sha256: sha256(JSON.stringify(item)), prefix: typeof item === "string" ? item.slice(0, 160) : null });
      const call = { args: args.map(summarizeArgument) };
      try {
        const result = value.apply(this, args);
        call.result = summarizeArgument(result);
        challengeEncryptCalls.push(call);
        return result;
      } catch (error) {
        call.error = { name: error.name, message: error.message };
        challengeEncryptCalls.push(call);
        throw error;
      }
    };
  }
});
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.global = sandbox;
sandbox.globalThis = sandbox;
document.defaultView = sandbox;
document.fonts = { status: "loaded", ready: Promise.resolve(), check: () => true };
sandbox.__nativeFunctionFixtures = [
  AudioContext,
  OfflineAudioContext,
  AudioContext.prototype.createAnalyser,
  AudioContext.prototype.close,
  canvas.getContext,
  canvas.toDataURL
];
vm.runInNewContext(`{
  const originalToString = Function.prototype.toString;
  const fixtures = globalThis.__nativeFunctionFixtures;
  Function.prototype.toString = function () {
    if (fixtures.includes(this)) return "function " + (this.name || "") + "() { [native code] }";
    return originalToString.call(this);
  };
}`, sandbox, { timeout: 1e3, filename: "fixture-native-prelude.js" });
var executionError = null;
try {
  vm.runInNewContext(source, sandbox, { timeout: 2e4, filename: path.basename(input) });
} catch (error) {
  executionError = { name: error.name, message: error.message, stack: error.stack };
}
await new Promise((resolve) => setTimeout(resolve, 200));
document.readyState = "complete";
document.dispatchEvent(new sandbox.Event("DOMContentLoaded"));
sandbox.dispatchEvent(new sandbox.Event("load"));
await new Promise((resolve) => setTimeout(resolve, 1300));
var info = null;
var firstData = null;
var secondData = null;
var apiErrors = {};
for (const [name, callback] of [
  ["getInfo", () => {
    info = sandbox.TDC?.getInfo?.();
  }],
  ["firstData", () => {
    firstData = sandbox.TDC?.getData?.(true);
  }],
  ["setData", () => {
    const drag = Number(process.argv[4] ?? 208.9583523809524);
    sandbox.TDC?.setData?.({ isNewEntry: 0 });
    const scale = 340 / 672;
    const start = { x: (45 + 130 / 2) * scale, y: 72 + (402 + 70 / 2) * scale };
    const emit = (type, x, y, buttons) => {
      const event = new sandbox.MouseEvent(type, { clientX: x, clientY: y, screenX: x, screenY: y, pageX: x, pageY: y, button: type === "mouseup" ? 0 : 0, buttons, which: type === "mouseup" ? 1 : 1, detail: 0, view: sandbox });
      document.dispatchEvent(event);
      sandbox.dispatchEvent(new sandbox.MouseEvent(type, { clientX: x, clientY: y, screenX: x, screenY: y, pageX: x, pageY: y, button: 0, buttons, which: 1, detail: 0, view: sandbox }));
    };
    emit("mousemove", start.x, start.y, 0);
    emit("mousedown", start.x, start.y, 1);
    for (let index = 1; index <= 32; index++) {
      const t = index / 32;
      const eased = 1 - Math.pow(1 - t, 3);
      emit("mousemove", start.x + drag * eased, start.y + Math.sin(t * Math.PI * 2) * 1.25, 1);
      const until = Date.now() + 8;
      while (Date.now() < until) {
      }
    }
    emit("mouseup", start.x + drag, start.y, 0);
    sandbox.TDC?.setData?.({ slideValue: drag, verifyBtnPos: [0, 0, 0, 0], opAreaPos: [10, 72, 350, 315], clientSize: [360, 360] });
    sandbox.TDC?.setData?.({ ft: "" });
  }],
  ["secondData", () => {
    secondData = sandbox.TDC?.getData?.(true);
  }]
]) {
  try {
    callback();
  } catch (error) {
    apiErrors[name] = { name: error.name, message: error.message, stack: error.stack };
  }
}
var summarize = (value) => ({ type: typeof value, length: typeof value === "string" ? value.length : null, sha256: sha256(JSON.stringify(value) ?? "undefined"), prefix: typeof value === "string" ? value.slice(0, 120) : null });
var report = {
  schemaVersion: 1,
  input: { relativePath: path.relative(root, input).replaceAll("\\", "/"), sha256: sha256(source) },
  executionError,
  tdcKeys: sandbox.TDC ? Reflect.ownKeys(sandbox.TDC).map(String).sort() : [],
  apiErrors,
  info,
  firstData: summarize(firstData),
  secondData: summarize(secondData),
  dataChangedAfterSetData: firstData !== secondData,
  challengeEncryptCalls,
  encodingCalls,
  navigatorAccesses: Object.fromEntries([...accesses.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))),
  registeredEvents: Object.fromEntries([...registeredEvents.entries()].sort((a, b) => a[0].localeCompare(b[0]))),
  eventDispatches,
  jsonStringifyCalls,
  fixtureApiCalls
};
fs.writeFileSync(output, `${JSON.stringify(report, null, 2)}
`);
if (process.argv[5]) {
  const rawOutput = path.resolve(process.argv[5]);
  fs.writeFileSync(rawOutput, `${JSON.stringify({ info, firstData, secondData }, null, 2)}
`);
}
console.log(JSON.stringify({ output, executionError, tdcKeys: report.tdcKeys, apiErrors, info, firstData: report.firstData, secondData: report.secondData, dataChangedAfterSetData: report.dataChangedAfterSetData, navigatorAccesses: report.navigatorAccesses }, null, 2));
process.exit(0);
