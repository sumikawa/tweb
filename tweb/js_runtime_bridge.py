from __future__ import annotations


def _bridge_source() -> str:
  return r"""
const window = globalThis;
const self = globalThis;
window.window = window;
window.self = self;
window.parent = window;
window.top = window;
window.opener = null;
window.frames = {
  get length() {
    return document.querySelectorAll('iframe').length;
  },
  item(index) {
    const frame = document.querySelectorAll('iframe')[Number(index) || 0];
    return frame ? frame.contentWindow : null;
  },
};
self.parent = window.parent;
self.top = window.top;
self.opener = window.opener;
self.frames = window.frames;
class EventTarget {
  addEventListener(type, callback) {
    __twebAddEventListener(this, type, callback);
  }
  removeEventListener(type, callback) {
    __twebRemoveEventListener(this, type, callback);
  }
  dispatchEvent(event) {
    return __twebDispatchEventOnTarget(this, event);
  }
  attachEvent(name, callback) {
    const type = String(name || '').replace(/^on/i, '');
    this.addEventListener(type, callback);
  }
  detachEvent(name, callback) {
    const type = String(name || '').replace(/^on/i, '');
    this.removeEventListener(type, callback);
  }
}
window.EventTarget = EventTarget;
self.EventTarget = EventTarget;
class Node extends EventTarget {}
Node.DOCUMENT_NODE = 9;
Node.DOCUMENT_TYPE_NODE = 10;
Node.ELEMENT_NODE = 1;
Node.TEXT_NODE = 3;
Node.COMMENT_NODE = 8;
Node.DOCUMENT_FRAGMENT_NODE = 11;
Node.DOCUMENT_POSITION_DISCONNECTED = 0x01;
Node.DOCUMENT_POSITION_PRECEDING = 0x02;
Node.DOCUMENT_POSITION_FOLLOWING = 0x04;
Node.DOCUMENT_POSITION_CONTAINS = 0x08;
Node.DOCUMENT_POSITION_CONTAINED_BY = 0x10;
Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC = 0x20;
const NodeFilter = {
  SHOW_ALL: 0xFFFFFFFF,
  SHOW_ELEMENT: 0x1,
  FILTER_ACCEPT: 1,
  FILTER_REJECT: 2,
  FILTER_SKIP: 3,
};

class Document extends Node {}
class Element extends Node {}
class HTMLElement extends Element {}
class HTMLHtmlElement extends HTMLElement {}
class HTMLHeadElement extends HTMLElement {}
class HTMLBodyElement extends HTMLElement {}
class HTMLAnchorElement extends HTMLElement {}
class HTMLButtonElement extends HTMLElement {}
class HTMLCanvasElement extends HTMLElement {}
class HTMLFormElement extends HTMLElement {}
class HTMLIFrameElement extends HTMLElement {}
class HTMLImageElement extends HTMLElement {}
class HTMLInputElement extends HTMLElement {}
class HTMLMediaElement extends HTMLElement {}
class HTMLAudioElement extends HTMLMediaElement {}
class HTMLVideoElement extends HTMLMediaElement {}
class HTMLLabelElement extends HTMLElement {}
class HTMLLinkElement extends HTMLElement {}
class HTMLMetaElement extends HTMLElement {}
class HTMLOptionElement extends HTMLElement {}
class HTMLScriptElement extends HTMLElement {}
class HTMLSelectElement extends HTMLElement {}
class HTMLStyleElement extends HTMLElement {}
class HTMLTemplateElement extends HTMLElement {}
class HTMLTextAreaElement extends HTMLElement {}
class HTMLTitleElement extends HTMLElement {}
class HTMLDialogElement extends HTMLElement {}
class Text extends Node {}
class Comment extends Node {}
class DocumentFragment extends Node {}
class ShadowRoot extends DocumentFragment {}
class DocumentType extends Node {}
class SVGElement extends Element {}

window.Node = Node;
self.Node = Node;
window.NodeFilter = NodeFilter;
self.NodeFilter = NodeFilter;
window.Document = Document;
self.Document = Document;
window.Element = Element;
self.Element = Element;
window.HTMLElement = HTMLElement;
self.HTMLElement = HTMLElement;
window.HTMLHtmlElement = HTMLHtmlElement;
self.HTMLHtmlElement = HTMLHtmlElement;
window.HTMLHeadElement = HTMLHeadElement;
self.HTMLHeadElement = HTMLHeadElement;
window.HTMLBodyElement = HTMLBodyElement;
self.HTMLBodyElement = HTMLBodyElement;
window.HTMLAnchorElement = HTMLAnchorElement;
self.HTMLAnchorElement = HTMLAnchorElement;
window.HTMLButtonElement = HTMLButtonElement;
self.HTMLButtonElement = HTMLButtonElement;
window.HTMLCanvasElement = HTMLCanvasElement;
self.HTMLCanvasElement = HTMLCanvasElement;
window.HTMLFormElement = HTMLFormElement;
self.HTMLFormElement = HTMLFormElement;
window.HTMLIFrameElement = HTMLIFrameElement;
self.HTMLIFrameElement = HTMLIFrameElement;
window.HTMLImageElement = HTMLImageElement;
self.HTMLImageElement = HTMLImageElement;
window.HTMLInputElement = HTMLInputElement;
self.HTMLInputElement = HTMLInputElement;
window.HTMLMediaElement = HTMLMediaElement;
self.HTMLMediaElement = HTMLMediaElement;
window.HTMLAudioElement = HTMLAudioElement;
self.HTMLAudioElement = HTMLAudioElement;
window.HTMLVideoElement = HTMLVideoElement;
self.HTMLVideoElement = HTMLVideoElement;
window.HTMLLabelElement = HTMLLabelElement;
self.HTMLLabelElement = HTMLLabelElement;
window.HTMLLinkElement = HTMLLinkElement;
self.HTMLLinkElement = HTMLLinkElement;
window.HTMLMetaElement = HTMLMetaElement;
self.HTMLMetaElement = HTMLMetaElement;
window.HTMLOptionElement = HTMLOptionElement;
self.HTMLOptionElement = HTMLOptionElement;
window.HTMLScriptElement = HTMLScriptElement;
self.HTMLScriptElement = HTMLScriptElement;
window.HTMLSelectElement = HTMLSelectElement;
self.HTMLSelectElement = HTMLSelectElement;
window.HTMLStyleElement = HTMLStyleElement;
self.HTMLStyleElement = HTMLStyleElement;
window.HTMLTemplateElement = HTMLTemplateElement;
self.HTMLTemplateElement = HTMLTemplateElement;
window.HTMLTextAreaElement = HTMLTextAreaElement;
self.HTMLTextAreaElement = HTMLTextAreaElement;
window.HTMLTitleElement = HTMLTitleElement;
self.HTMLTitleElement = HTMLTitleElement;
window.HTMLDialogElement = HTMLDialogElement;
self.HTMLDialogElement = HTMLDialogElement;
window.Text = Text;
self.Text = Text;
window.Comment = Comment;
self.Comment = Comment;
window.DocumentFragment = DocumentFragment;
self.DocumentFragment = DocumentFragment;
window.ShadowRoot = ShadowRoot;
self.ShadowRoot = ShadowRoot;
window.DocumentType = DocumentType;
self.DocumentType = DocumentType;
window.SVGElement = SVGElement;
self.SVGElement = SVGElement;

function Audio(src = '') {
  const audio = document.createElement('audio');
  if (src) {
    audio.src = src;
  }
  return audio;
}
window.Audio = Audio;
self.Audio = Audio;

function __twebCreateAudioParam(initialValue = 1) {
  return {
    value: Number(initialValue) || 0,
    setValueAtTime(value, _time = 0) {
      this.value = Number(value) || 0;
      return this;
    },
    linearRampToValueAtTime(value, _time = 0) {
      this.value = Number(value) || 0;
      return this;
    },
    exponentialRampToValueAtTime(value, _time = 0) {
      this.value = Number(value) || 0;
      return this;
    },
    setTargetAtTime(value, _time = 0, _timeConstant = 0) {
      this.value = Number(value) || 0;
      return this;
    },
    cancelScheduledValues(_time = 0) {
      return this;
    },
  };
}

function __twebCreateAudioNode(extra = {}) {
  return Object.assign({
    context: null,
    connect() {
      return this;
    },
    disconnect() {},
  }, extra);
}

class AudioContext {
  constructor() {
    this.currentTime = 0;
    this.state = 'running';
    this.destination = __twebCreateAudioNode({ context: this });
  }
  createGain() {
    return __twebCreateAudioNode({
      context: this,
      gain: __twebCreateAudioParam(1),
    });
  }
  createBufferSource() {
    return __twebCreateAudioNode({
      context: this,
      buffer: null,
      loop: false,
      playbackRate: __twebCreateAudioParam(1),
      start() {},
      stop() {},
    });
  }
  createMediaElementSource(mediaElement) {
    return __twebCreateAudioNode({
      context: this,
      mediaElement,
    });
  }
  resume() {
    this.state = 'running';
    return Promise.resolve();
  }
  suspend() {
    this.state = 'suspended';
    return Promise.resolve();
  }
  close() {
    this.state = 'closed';
    return Promise.resolve();
  }
}

window.AudioContext = AudioContext;
window.webkitAudioContext = AudioContext;
self.AudioContext = AudioContext;
self.webkitAudioContext = AudioContext;

const navigator = {
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
  appVersion: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
  language: 'ja-JP',
  languages: ['ja-JP', 'ja'],
  platform: 'MacIntel',
  vendor: 'Google Inc.',
  productSub: '20030107',
  cookieEnabled: true,
  onLine: true,
  webdriver: false,
  maxTouchPoints: 0,
  hardwareConcurrency: 8,
  deviceMemory: 8,
  connection: {
    effectiveType: '4g',
    downlink: 10,
    rtt: 50,
    saveData: false,
    addEventListener() {},
    removeEventListener() {},
    onchange: null,
  },
  clearAppBadge() {
    return Promise.resolve();
  },
  setAppBadge() {
    return Promise.resolve();
  },
  scheduling: {
    isInputPending() {
      return false;
    },
  },
  userAgentData: {
    brands: [
      { brand: 'Chromium', version: '137' },
      { brand: 'Google Chrome', version: '137' },
      { brand: 'Not/A)Brand', version: '24' },
    ],
    mobile: false,
    platform: 'macOS',
    getHighEntropyValues() {
      return Promise.resolve({
        architecture: 'x86',
        bitness: '64',
        model: '',
        platform: 'macOS',
        platformVersion: '10.15.7',
        uaFullVersion: '137.0.0.0',
        fullVersionList: [
          { brand: 'Chromium', version: '137.0.0.0' },
          { brand: 'Google Chrome', version: '137.0.0.0' },
        ],
        wow64: false,
      });
    },
  },
};
class PushSubscription {
  constructor(options = {}) {
    this.options = options;
  }
  unsubscribe() {
    return Promise.resolve(true);
  }
  toJSON() {
    return {};
  }
}

class PushManager {
  getSubscription() {
    return Promise.resolve(null);
  }
  subscribe(options = {}) {
    return Promise.resolve(new PushSubscription(options));
  }
}

class ServiceWorkerRegistration {
  constructor() {
    this.active = null;
    this.installing = null;
    this.waiting = null;
    this.navigationPreload = {
      enable() {
        return Promise.resolve();
      },
      disable() {
        return Promise.resolve();
      },
      getState() {
        return Promise.resolve({ enabled: false });
      },
      setHeaderValue(_value) {
        return Promise.resolve();
      },
    };
    this.pushManager = new PushManager();
  }
  unregister() {
    return Promise.resolve(true);
  }
  showNotification(_title, _options = {}) {
    return Promise.resolve();
  }
  update() {
    return Promise.resolve();
  }
}

class ServiceWorkerContainer extends EventTarget {
  constructor() {
    super();
    this.controller = {
      postMessage(_message) {},
    };
    this.ready = Promise.resolve(new ServiceWorkerRegistration());
  }
  getRegistration() {
    return Promise.resolve(null);
  }
  getRegistrations() {
    return Promise.resolve([]);
  }
  register(_scriptURL, _options = {}) {
    return Promise.resolve(new ServiceWorkerRegistration());
  }
  startMessages() {
    return Promise.resolve();
  }
}

window.ServiceWorkerRegistration = ServiceWorkerRegistration;
self.ServiceWorkerRegistration = ServiceWorkerRegistration;
window.PushManager = PushManager;
self.PushManager = PushManager;
window.PushSubscription = PushSubscription;
self.PushSubscription = PushSubscription;
navigator.serviceWorker = new ServiceWorkerContainer();
const __twebPluginArray = [
  {
    name: 'Chrome PDF Viewer',
    filename: 'internal-pdf-viewer',
    description: 'Portable Document Format',
  }
];
const __twebMimeTypeArray = [
  {
    type: 'application/pdf',
    suffixes: 'pdf',
    description: 'Portable Document Format',
  }
];
navigator.plugins = {
  length: __twebPluginArray.length,
  item(index) {
    return __twebPluginArray[index] || null;
  },
  namedItem(name) {
    return __twebPluginArray.find((plugin) => plugin.name === String(name)) || null;
  },
  refresh() {},
  0: __twebPluginArray[0],
};
navigator.mimeTypes = {
  length: __twebMimeTypeArray.length,
  item(index) {
    return __twebMimeTypeArray[index] || null;
  },
  namedItem(name) {
    return __twebMimeTypeArray.find((entry) => entry.type === String(name)) || null;
  },
  0: __twebMimeTypeArray[0],
};
navigator.permissions = {
  query(_descriptor) {
    return Promise.resolve({ state: 'prompt', onchange: null });
  }
};
navigator.storage = {
  estimate() {
    return Promise.resolve({ quota: 1073741824, usage: 0 });
  },
  getDirectory() {
    return Promise.resolve({
      getDirectoryHandle() {
        return Promise.resolve(this);
      },
      getFileHandle() {
        return Promise.resolve({
          createWritable() {
            return Promise.resolve({
              write() {
                return Promise.resolve();
              },
              close() {
                return Promise.resolve();
              },
            });
          },
        });
      },
    });
  },
};
navigator.clipboard = {
  writeText(_value) {
    return Promise.resolve();
  },
  readText() {
    return Promise.resolve('');
  }
};
const __twebGeolocationError = {
  code: 1,
  PERMISSION_DENIED: 1,
  POSITION_UNAVAILABLE: 2,
  TIMEOUT: 3,
  message: 'Geolocation is unavailable in tweb QuickJS runtime',
};
const geolocation = {
  getCurrentPosition(_success, error, _options = {}) {
    __twebEnqueueTimer(() => {
      if (typeof error === 'function') {
        error(__twebGeolocationError);
      }
    }, 0);
  },
  watchPosition(_success, error, _options = {}) {
    __twebEnqueueTimer(() => {
      if (typeof error === 'function') {
        error(__twebGeolocationError);
      }
    }, 0);
    return 1;
  },
  clearWatch(_watchId) {},
};
navigator.geolocation = geolocation;
navigator.sendBeacon = function(url, data = '') {
  const headers = new Headers();
  const body = __twebSerializeBody(data, headers);
  const normalizedHeaders = __twebNormalizeHeaders(headers);
  if (!normalizedHeaders.cookie) {
    const cookieValue = __twebGetCookieString();
    if (cookieValue) {
      normalizedHeaders.cookie = cookieValue;
    }
  }
  __twebEnqueueTimer(() => {
    try {
      __twebHttpRequest('POST', String(url), String(body), JSON.stringify(normalizedHeaders));
    } catch (_error) {}
  });
  return true;
};
window.navigator = navigator;
self.navigator = navigator;
window.GeolocationPositionError = function GeolocationPositionError() {};
window.GeolocationCoordinates = function GeolocationCoordinates() {};
window.GeolocationPosition = function GeolocationPosition() {};
window.Geolocation = function Geolocation() {};
window.Geolocation.prototype = geolocation;
window.GeolocationPositionError.prototype = __twebGeolocationError;
self.GeolocationPositionError = window.GeolocationPositionError;
self.GeolocationCoordinates = window.GeolocationCoordinates;
self.GeolocationPosition = window.GeolocationPosition;
self.Geolocation = window.Geolocation;

const trustedTypes = {
  createPolicy(_name, rules = {}) {
    return {
      createHTML(value) {
        return rules.createHTML ? rules.createHTML(value) : String(value);
      },
      createScript(value) {
        return rules.createScript ? rules.createScript(value) : String(value);
      },
      createScriptURL(value) {
        return rules.createScriptURL ? rules.createScriptURL(value) : String(value);
      },
    };
  }
};
window.trustedTypes = trustedTypes;
self.trustedTypes = trustedTypes;

const scheduler = {
  postTask(callback, _options = {}) {
    return new Promise((resolve, reject) => {
      __twebEnqueueTimer(() => {
        try {
          resolve(callback());
        } catch (error) {
          reject(error);
        }
      }, 0);
    });
  },
  yield() {
    return Promise.resolve();
  },
};
window.scheduler = scheduler;
self.scheduler = scheduler;

const navigation = {
  get currentEntry() {
    return {
      url: window.location ? window.location.href : '',
      index: 0,
      key: 'tweb',
      id: 'tweb',
      sameDocument: true,
      getState() {
        return history.state;
      },
    };
  },
  transition: null,
  canGoBack: false,
  canGoForward: false,
  navigate(url) {
    history.pushState(null, '', url);
    return {
      committed: Promise.resolve(navigation.currentEntry),
      finished: Promise.resolve(navigation.currentEntry),
    };
  },
  reload() {
    return {
      committed: Promise.resolve(navigation.currentEntry),
      finished: Promise.resolve(navigation.currentEntry),
    };
  },
  updateCurrentEntry() {},
  traverseTo() {
    return {
      committed: Promise.resolve(navigation.currentEntry),
      finished: Promise.resolve(navigation.currentEntry),
    };
  },
  back() {
    history.back();
    return {
      committed: Promise.resolve(navigation.currentEntry),
      finished: Promise.resolve(navigation.currentEntry),
    };
  },
  forward() {
    history.forward();
    return {
      committed: Promise.resolve(navigation.currentEntry),
      finished: Promise.resolve(navigation.currentEntry),
    };
  },
  entries() {
    return [this.currentEntry];
  },
  addEventListener(_type, _callback) {},
  removeEventListener(_type, _callback) {},
};
window.navigation = navigation;
self.navigation = navigation;

const __twebCustomElementsRegistry = new Map();
const customElements = {
  define(name, constructor) {
    __twebCustomElementsRegistry.set(String(name), constructor);
  },
  get(name) {
    return __twebCustomElementsRegistry.get(String(name));
  },
  whenDefined(name) {
    return Promise.resolve(__twebCustomElementsRegistry.get(String(name)));
  },
};
window.customElements = customElements;
self.customElements = customElements;
class Notification {
  static permission = 'default';
  static requestPermission() {
    return Promise.resolve('default');
  }
}
window.Notification = Notification;
self.Notification = Notification;
const screen = {
  width: 1280,
  height: 720,
  orientation: {
    angle: 0,
    type: 'landscape-primary',
    addEventListener() {},
    removeEventListener() {},
  },
};
window.screen = screen;
self.screen = screen;
const performance = {
  now() {
    return Date.now();
  },
  mark() {},
  measure() {
    return { duration: 0 };
  },
  clearMarks() {},
  clearMeasures() {},
  getEntriesByType() {
    return [];
  },
  getEntriesByName() {
    return [];
  },
  timing: {
    navigationStart: 0,
  },
};
window.performance = performance;
self.performance = performance;
const CSS = {
  escape(value) {
    return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
  },
  supports(_property, _value) {
    return true;
  }
};
window.CSS = CSS;
self.CSS = CSS;
const chrome = {
  runtime: {},
  loadTimes() {
    return {};
  },
  csi() {
    return {};
  },
};
window.chrome = chrome;
self.chrome = chrome;
function __twebDefineBuiltinMethod(target, name, implementation) {
  Object.defineProperty(target, name, {
    value: implementation,
    writable: true,
    configurable: true,
  });
}
if (!Array.prototype.flatMap) {
  __twebDefineBuiltinMethod(Array.prototype, 'flatMap', function(callback, thisArg = undefined) {
    return this.map((value, index, array) => callback.call(thisArg, value, index, array)).flat();
  });
}
if (!Array.prototype.at) {
  __twebDefineBuiltinMethod(Array.prototype, 'at', function(index) {
    const length = this.length >>> 0;
    let offset = Number(index) || 0;
    if (offset < 0) {
      offset += length;
    }
    if (offset < 0 || offset >= length) {
      return undefined;
    }
    return this[offset];
  });
}
if (!String.prototype.replaceAll) {
  __twebDefineBuiltinMethod(String.prototype, 'replaceAll', function(searchValue, replaceValue) {
    if (searchValue instanceof RegExp) {
      if (!searchValue.global) {
        throw new TypeError('replaceAll requires a global RegExp');
      }
      return String(this).replace(searchValue, replaceValue);
    }
    return String(this).split(String(searchValue)).join(String(replaceValue));
  });
}
if (!String.prototype.normalize) {
  __twebDefineBuiltinMethod(String.prototype, 'normalize', function(_form = 'NFC') {
    return String(this);
  });
}
function __twebStringReceiver(value) {
  return value == null ? '' : String(value);
}
if (!Object.hasOwn) {
  Object.hasOwn = function(target, key) {
    if (target == null) {
      throw new TypeError('Cannot convert undefined or null to object');
    }
    return Object.prototype.hasOwnProperty.call(Object(target), key);
  };
}
const Intl = globalThis.Intl || {};
class Locale {
  constructor(tag = 'en-US') {
    this.baseName = String(tag || 'en-US');
    const [language = 'en', script = '', region = ''] = this.baseName.split('-');
    this.language = language;
    this.script = script;
    this.region = region;
  }
  maximize() {
    const rtlLanguages = new Set(['ar', 'dv', 'fa', 'he', 'iw', 'ku', 'ps', 'sd', 'ug', 'ur', 'yi']);
    return {
      script: this.script || (rtlLanguages.has(this.language) ? 'Arab' : 'Latn')
    };
  }
  toString() {
    return this.baseName;
  }
}
if (!Intl.Locale) {
  Intl.Locale = Locale;
}
if (!Intl.NumberFormat) {
  Intl.NumberFormat = class {
    format(value) {
      return String(value);
    }
  };
}
if (!Intl.Collator) {
  Intl.Collator = class {
    constructor(_locale = undefined, _options = undefined) {}
    compare(left, right) {
      const a = String(left);
      const b = String(right);
      if (a < b) {
        return -1;
      }
      if (a > b) {
        return 1;
      }
      return 0;
    }
  };
}
if (!Intl.DateTimeFormat) {
  Intl.DateTimeFormat = class {
    format(value) {
      return String(value);
    }
  };
}
if (!Intl.PluralRules) {
  Intl.PluralRules = class {
    select(value) {
      return Number(value) === 1 ? 'one' : 'other';
    }
  };
}
window.Intl = Intl;
self.Intl = Intl;
const __twebBase64Alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
function btoa(value = '') {
  let output = '';
  const input = String(value);
  for (let index = 0; index < input.length; index += 3) {
    const byte1 = input.charCodeAt(index) & 255;
    const byte2 = input.charCodeAt(index + 1);
    const byte3 = input.charCodeAt(index + 2);
    const enc1 = byte1 >> 2;
    const enc2 = ((byte1 & 3) << 4) | ((Number.isFinite(byte2) ? byte2 : 0) >> 4);
    const enc3 = Number.isFinite(byte2) ? (((byte2 & 15) << 2) | ((Number.isFinite(byte3) ? byte3 : 0) >> 6)) : 64;
    const enc4 = Number.isFinite(byte3) ? (byte3 & 63) : 64;
    output +=
      __twebBase64Alphabet.charAt(enc1) +
      __twebBase64Alphabet.charAt(enc2) +
      __twebBase64Alphabet.charAt(enc3) +
      __twebBase64Alphabet.charAt(enc4);
  }
  return output;
}
function atob(value = '') {
  let output = '';
  const input = String(value).replace(/=+$/, '');
  for (let index = 0; index < input.length; index += 4) {
    const enc1 = __twebBase64Alphabet.indexOf(input.charAt(index));
    const enc2 = __twebBase64Alphabet.indexOf(input.charAt(index + 1));
    const enc3 = __twebBase64Alphabet.indexOf(input.charAt(index + 2));
    const enc4 = __twebBase64Alphabet.indexOf(input.charAt(index + 3));
    const chr1 = (enc1 << 2) | (enc2 >> 4);
    const chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
    const chr3 = ((enc3 & 3) << 6) | enc4;
    output += String.fromCharCode(chr1);
    if (enc3 >= 0 && enc3 !== 64) {
      output += String.fromCharCode(chr2);
    }
    if (enc4 >= 0 && enc4 !== 64) {
      output += String.fromCharCode(chr3);
    }
  }
  return output;
}
window.atob = atob;
window.btoa = btoa;
self.atob = atob;
self.btoa = btoa;
const __twebLocation = JSON.parse(__twebGetLocation());
const __twebCookieJar = new Map();
function __twebApplyLocation(nextHref) {
  __twebRecordNavigationAttempt(nextHref);
  if (!__twebAllowNavigation()) {
    return;
  }
  Object.assign(__twebLocation, __twebParseResolvedUrl(nextHref));
}
function __twebResolveLocationTarget(value) {
  return __twebResolveUrl(__twebLocation.href, String(value));
}
function __twebParseResolvedUrl(value) {
  const match = String(value).match(/^([a-zA-Z][a-zA-Z0-9+.-]*:)?(?:\/\/([^/?#]*))?([^?#]*)(\?[^#]*)?(#.*)?$/) || [];
  const protocol = match[1] || '';
  const host = match[2] || '';
  const pathname = match[3] || '/';
  const search = match[4] || '';
  const hash = match[5] || '';
  const hostname = host.split(':')[0] || '';
  const origin = protocol && host ? `${protocol}//${host}` : '';
  return { href: String(value), protocol, host, hostname, pathname, search, hash, origin };
}
function __twebSetCookie(value) {
  const source = String(value || '');
  const firstPart = source.split(';', 1)[0];
  if (!firstPart || !firstPart.includes('=')) {
    return;
  }
  const [name, ...rest] = firstPart.split('=');
  const cookieName = name.trim();
  if (!cookieName) {
    return;
  }
  __twebCookieJar.set(cookieName, rest.join('=').trim());
}
function __twebGetCookieString() {
  return Array.from(__twebCookieJar.entries())
    .map(([name, value]) => `${name}=${value}`)
    .join('; ');
}
let __twebNextObjectUrlId = 1;
const __twebObjectUrls = new Map();

function __twebReadObjectUrlText(url) {
  const value = __twebObjectUrls.get(String(url));
  if (value === undefined) {
    return null;
  }
  if (value instanceof Blob) {
    return new TextDecoder().decode(value._bytes);
  }
  if (typeof value === 'string') {
    return value;
  }
  if (value instanceof Uint8Array) {
    return new TextDecoder().decode(value);
  }
  if (value instanceof ArrayBuffer) {
    return new TextDecoder().decode(new Uint8Array(value));
  }
  if (ArrayBuffer.isView(value)) {
    return new TextDecoder().decode(
      new Uint8Array(value.buffer, value.byteOffset || 0, value.byteLength || 0)
    );
  }
  return String(value);
}

class URL {
  constructor(input, base = __twebLocation.href) {
    Object.assign(this, __twebParseResolvedUrl(__twebResolveUrl(String(base), String(input))));
    __twebAttachUrlSearchParams(this);
  }
  toString() {
    return this.href;
  }
  toJSON() {
    return this.href;
  }
  static createObjectURL(value) {
    const url = `blob:tweb-${__twebNextObjectUrlId++}`;
    __twebObjectUrls.set(url, value);
    return url;
  }
  static revokeObjectURL(value) {
    __twebObjectUrls.delete(String(value));
  }
  static canParse(input, base = __twebLocation.href) {
    try {
      new URL(input, base);
      return true;
    } catch (_error) {
      return false;
    }
  }
}
window.URL = URL;
self.URL = URL;
const location = {
  get href() { return __twebLocation.href; },
  get protocol() { return __twebLocation.protocol; },
  get host() { return __twebLocation.host; },
  get hostname() { return __twebLocation.hostname; },
  get pathname() { return __twebLocation.pathname; },
  get search() { return __twebLocation.search; },
  get hash() { return __twebLocation.hash; },
  get origin() { return __twebLocation.origin; },
  get state() { return history.state; },
  get query() { return Object.fromEntries(new URLSearchParams(__twebLocation.search).entries()); },
  assign(value) { __twebApplyLocation(__twebResolveLocationTarget(value)); },
  replace(value) { __twebApplyLocation(__twebResolveLocationTarget(value)); },
  toString() { return this.href; },
  valueOf() { return this.href; },
  reload() {
    __twebRequestReload(__twebLocation.href);
  }
};
window.location = location;
self.location = location;
window.origin = location.origin;
self.origin = location.origin;
window.name = '';
self.name = '';
window.innerWidth = 1280;
window.innerHeight = 720;
self.innerWidth = 1280;
self.innerHeight = 720;
window.devicePixelRatio = 1;
self.devicePixelRatio = 1;
window.visualViewport = {
  width: 1280,
  height: 720,
  scale: 1,
  offsetLeft: 0,
  offsetTop: 0,
  addEventListener() {},
  removeEventListener() {},
};
self.visualViewport = window.visualViewport;
window.isSecureContext = true;
self.isSecureContext = true;
window.scrollX = 0;
window.scrollY = 0;
window.pageXOffset = 0;
window.pageYOffset = 0;
self.scrollX = 0;
self.scrollY = 0;
self.pageXOffset = 0;
self.pageYOffset = 0;
const console = {
  log(...args) { __twebConsoleLog('log', ...args.map(String)); },
  warn(...args) { __twebConsoleLog('warn', ...args.map(String)); },
  error(...args) { __twebConsoleLog('error', ...args.map(String)); }
};
window.console = console;
self.console = console;
function reportError(error) {
  __twebHandleAsyncError(error);
}
window.reportError = reportError;
self.reportError = reportError;

function __twebRandomByte() {
  return Math.floor(Math.random() * 256);
}

function __twebBytesToBase64(bytes) {
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

const crypto = {
  getRandomValues(array) {
    for (let index = 0; index < array.length; index += 1) {
      array[index] = __twebRandomByte();
    }
    return array;
  },
  randomUUID() {
    const hex = [];
    for (let index = 0; index < 16; index += 1) {
      hex.push((__twebRandomByte() + 256).toString(16).slice(-2));
    }
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`;
  },
  subtle: {
    digest(algorithm, data) {
      let bytes;
      if (data instanceof Uint8Array) {
        bytes = data;
      } else if (data instanceof ArrayBuffer) {
        bytes = new Uint8Array(data);
      } else if (ArrayBuffer.isView(data)) {
        bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      } else {
        throw new TypeError('Unsupported digest input');
      }
      const normalized = typeof algorithm === 'string'
        ? algorithm
        : (algorithm && algorithm.name ? algorithm.name : '');
      const digestBytes = __twebDecodeBase64ToUint8Array(
        __twebCryptoDigest(String(normalized), __twebBytesToBase64(bytes))
      );
      return Promise.resolve(digestBytes.buffer.slice(0));
    },
  },
};
window.crypto = crypto;
self.crypto = crypto;

class TextEncoder {
  encode(value = '') {
    const bytes = [];
    for (const char of String(value)) {
      const codePoint = char.codePointAt(0);
      if (codePoint <= 0x7f) {
        bytes.push(codePoint);
      } else if (codePoint <= 0x7ff) {
        bytes.push(
          0xc0 | (codePoint >> 6),
          0x80 | (codePoint & 0x3f),
        );
      } else if (codePoint <= 0xffff) {
        bytes.push(
          0xe0 | (codePoint >> 12),
          0x80 | ((codePoint >> 6) & 0x3f),
          0x80 | (codePoint & 0x3f),
        );
      } else {
        bytes.push(
          0xf0 | (codePoint >> 18),
          0x80 | ((codePoint >> 12) & 0x3f),
          0x80 | ((codePoint >> 6) & 0x3f),
          0x80 | (codePoint & 0x3f),
        );
      }
    }
    return Uint8Array.from(bytes);
  }
}

class TextDecoder {
  constructor() {
    this._pending = [];
  }
  decode(value = [], options = {}) {
    if (value instanceof ArrayBuffer) {
      value = new Uint8Array(value);
    } else if (ArrayBuffer.isView(value)) {
      value = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    }
    const stream = !!(options && options.stream);
    const bytes = this._pending.concat(Array.from(value || []).map((code) => Number(code) & 0xff));
    const output = [];
    let index = 0;
    while (index < bytes.length) {
      const first = bytes[index];
      let needed = 0;
      let codePoint = 0;
      if (first <= 0x7f) {
        needed = 1;
        codePoint = first;
      } else if ((first & 0xe0) === 0xc0) {
        needed = 2;
        codePoint = first & 0x1f;
      } else if ((first & 0xf0) === 0xe0) {
        needed = 3;
        codePoint = first & 0x0f;
      } else if ((first & 0xf8) === 0xf0) {
        needed = 4;
        codePoint = first & 0x07;
      } else {
        output.push('\uFFFD');
        index += 1;
        continue;
      }
      if (index + needed > bytes.length) {
        if (stream) {
          break;
        }
        output.push('\uFFFD');
        index += 1;
        continue;
      }
      let valid = true;
      for (let offset = 1; offset < needed; offset += 1) {
        const next = bytes[index + offset];
        if ((next & 0xc0) !== 0x80) {
          valid = false;
          break;
        }
        codePoint = (codePoint << 6) | (next & 0x3f);
      }
      if (!valid) {
        output.push('\uFFFD');
        index += 1;
        continue;
      }
      output.push(String.fromCodePoint(codePoint));
      index += needed;
    }
    this._pending = stream ? bytes.slice(index) : [];
    return output.join('');
  }
}

window.TextEncoder = TextEncoder;
window.TextDecoder = TextDecoder;
self.TextEncoder = TextEncoder;
self.TextDecoder = TextDecoder;

function __twebExtractCharset(value) {
  if (!value) {
    return '';
  }
  const match = String(value).match(/charset\s*=\s*['"]?\s*([a-z0-9._-]+)/i);
  return match ? String(match[1]).toLowerCase() : '';
}

const __twebEventListeners = new WeakMap();
const __twebMutationObservers = [];
const __twebNodeCache = new Map();
let __twebDocumentReadyState = 'loading';
let __twebActiveElement = null;
let __twebCurrentAsyncCallbackLabel = '';
window.__twebLastAsyncCallbackLabel = '';
window.__twebSuppressedEventCallbackErrors = [];

function __twebGetListenerBucket(target, type, create = false) {
  let buckets = __twebEventListeners.get(target);
  if (!buckets) {
    if (!create) {
      return null;
    }
    buckets = Object.create(null);
    __twebEventListeners.set(target, buckets);
  }
  if (!buckets[type]) {
    if (!create) {
      return null;
    }
    buckets[type] = [];
  }
  return buckets[type];
}

function __twebAddEventListener(target, type, callback) {
  if (!callback) {
    return;
  }
  if (!callback.__twebDebugLabel) {
    callback.__twebDebugLabel = `event:${String(type)}`;
  }
  const bucket = __twebGetListenerBucket(target, String(type), true);
  if (!bucket.includes(callback)) {
    bucket.push(callback);
  }
}

function __twebRemoveEventListener(target, type, callback) {
  const bucket = __twebGetListenerBucket(target, String(type));
  if (!bucket) {
    return;
  }
  const index = bucket.indexOf(callback);
  if (index >= 0) {
    bucket.splice(index, 1);
  }
}

function __twebTargetHasEventInterest(target, type) {
  if (!target) {
    return false;
  }
  const normalizedType = String(type);
  const bucket = __twebGetListenerBucket(target, normalizedType);
  if (bucket && bucket.length > 0) {
    return true;
  }
  return typeof target[`on${normalizedType}`] === 'function';
}

function __twebDispatchEventOnTarget(target, event) {
  if (!event.target) {
    event.target = target;
  }
  if (!event.__twebPath) {
    event.__twebPath = __twebBuildEventPath(event.target);
  }
  event.currentTarget = target;
  const bucket = __twebGetListenerBucket(target, String(event.type)) || [];
  for (const callback of bucket.slice()) {
    __twebInvokeEventCallback(callback, event);
    if (event.__twebImmediatePropagationStopped) {
      break;
    }
  }
  const handler = target ? target[`on${event.type}`] : null;
  if (handler && !event.__twebImmediatePropagationStopped) {
    __twebInvokeEventCallback(handler, event);
  }
  return !event.defaultPrevented;
}

function __twebFormatCallbackError(error, fallbackLabel = '') {
  const callbackLabel = error && typeof error.__twebCallbackLabel === 'string'
    ? error.__twebCallbackLabel
    : fallbackLabel;
  const stack = error && typeof error.stack === 'string'
    ? error.stack.trim()
    : '';
  if (error === undefined || error === null) {
    return callbackLabel ? `null [callback=${callbackLabel}]` : 'null';
  }
  if (typeof error === 'string') {
    return callbackLabel ? `${error} [callback=${callbackLabel}]` : error;
  }
  if (error && typeof error.message === 'string' && error.message) {
    const base = callbackLabel ? `${error.message} [callback=${callbackLabel}]` : error.message;
    if (!stack) {
      return base;
    }
    return stack.startsWith(error.message) ? stack : `${base}\n${stack}`;
  }
  const fallback = String(error);
  return callbackLabel ? `${fallback} [callback=${callbackLabel}]` : fallback;
}

function __twebDispatchEventOnTargetIgnoreCallbackErrors(target, event) {
  if (!event.target) {
    event.target = target;
  }
  if (!event.__twebPath) {
    event.__twebPath = __twebBuildEventPath(event.target);
  }
  event.currentTarget = target;
  const bucket = __twebGetListenerBucket(target, String(event.type)) || [];
  for (const callback of bucket.slice()) {
    try {
      __twebInvokeEventCallback(callback, event);
    } catch (error) {
      window.__twebSuppressedEventCallbackErrors.push(
        __twebFormatCallbackError(error, `event:${event.type}`)
      );
    }
    if (event.__twebImmediatePropagationStopped) {
      break;
    }
  }
  const handler = target ? target[`on${event.type}`] : null;
  if (handler && !event.__twebImmediatePropagationStopped) {
    try {
      __twebInvokeEventCallback(handler, event);
    } catch (error) {
      window.__twebSuppressedEventCallbackErrors.push(
        __twebFormatCallbackError(error, `event:${event.type}`)
      );
    }
  }
  return !event.defaultPrevented;
}

function __twebBuildEventPath(target) {
  const path = [];
  let current = target;
  while (current) {
    path.push(current);
    if (current === window) {
      break;
    }
    if (current === document) {
      current = window;
      continue;
    }
    if (current.nodeType === Node.DOCUMENT_FRAGMENT_NODE && current.host) {
      current = current.host;
      continue;
    }
    current = current.parentNode || (current.ownerDocument || null);
  }
  if (!path.includes(window)) {
    path.push(window);
  }
  return path;
}

function __twebNodesEqual(left, right) {
  if (left === right) {
    return true;
  }
  if (!left || !right || left.nodeType !== right.nodeType || left.nodeName !== right.nodeName) {
    return false;
  }
  if (left.nodeType === Node.TEXT_NODE || left.nodeType === Node.COMMENT_NODE) {
    return left.textContent === right.textContent;
  }
  if (left.nodeType === Node.DOCUMENT_TYPE_NODE) {
    return left.name === right.name;
  }
  if (left.nodeType === Node.ELEMENT_NODE) {
    const leftNames = left.getAttributeNames ? left.getAttributeNames().sort() : [];
    const rightNames = right.getAttributeNames ? right.getAttributeNames().sort() : [];
    if (leftNames.length !== rightNames.length) {
      return false;
    }
    for (let index = 0; index < leftNames.length; index += 1) {
      if (leftNames[index] !== rightNames[index]) {
        return false;
      }
      if (left.getAttribute(leftNames[index]) !== right.getAttribute(rightNames[index])) {
        return false;
      }
    }
  }
  const leftChildren = Array.from(left.childNodes || []);
  const rightChildren = Array.from(right.childNodes || []);
  if (leftChildren.length !== rightChildren.length) {
    return false;
  }
  for (let index = 0; index < leftChildren.length; index += 1) {
    if (!__twebNodesEqual(leftChildren[index], rightChildren[index])) {
      return false;
    }
  }
  return true;
}

function __twebDispatchReadyEvent(type) {
  if (__twebTargetHasEventInterest(document, type)) {
    __twebDispatchEventOnTarget(document, new Event(type));
  }
  if (__twebTargetHasEventInterest(window, type)) {
    __twebDispatchEventOnTarget(window, new Event(type));
  }
}

function __twebDispatchReadyEventIgnoreCallbackErrors(type) {
  if (__twebTargetHasEventInterest(document, type)) {
    __twebDispatchEventOnTargetIgnoreCallbackErrors(document, new Event(type));
  }
  if (__twebTargetHasEventInterest(window, type)) {
    __twebDispatchEventOnTargetIgnoreCallbackErrors(window, new Event(type));
  }
}

function __twebInvokeEventCallback(callback, event = null) {
  const previousLabel = __twebCurrentAsyncCallbackLabel;
  __twebCurrentAsyncCallbackLabel = callback && callback.__twebDebugLabel
    ? callback.__twebDebugLabel
    : (event ? `event:${event.type}` : '');
  const callbackTarget = event && event.currentTarget ? event.currentTarget : window;
  if (typeof callback === 'function') {
    try {
      callback.call(callbackTarget, event);
    } catch (error) {
      if (error && !error.__twebCallbackLabel && __twebCurrentAsyncCallbackLabel) {
        try {
          error.__twebCallbackLabel = __twebCurrentAsyncCallbackLabel;
        } catch (_error) {}
      }
      window.__twebLastAsyncCallbackLabel = __twebCurrentAsyncCallbackLabel || '';
      window.__twebLastAsyncError = error;
      throw error;
    } finally {
      __twebCurrentAsyncCallbackLabel = previousLabel;
    }
  } else if (callback && typeof callback.handleEvent === 'function') {
    try {
      callback.handleEvent.call(callback, event);
    } catch (error) {
      if (error && !error.__twebCallbackLabel && __twebCurrentAsyncCallbackLabel) {
        try {
          error.__twebCallbackLabel = __twebCurrentAsyncCallbackLabel;
        } catch (_error) {}
      }
      window.__twebLastAsyncCallbackLabel = __twebCurrentAsyncCallbackLabel || '';
      window.__twebLastAsyncError = error;
      throw error;
    } finally {
      __twebCurrentAsyncCallbackLabel = previousLabel;
    }
  } else {
    __twebCurrentAsyncCallbackLabel = previousLabel;
  }
}

function __twebHandleAsyncError(error) {
  if (error && !error.__twebCallbackLabel && __twebCurrentAsyncCallbackLabel) {
    try {
      error.__twebCallbackLabel = __twebCurrentAsyncCallbackLabel;
    } catch (_error) {}
  }
  window.__twebLastAsyncCallbackLabel = __twebCurrentAsyncCallbackLabel || '';
  window.__twebLastAsyncError = error;
  if (typeof window.onerror === 'function') {
    try {
      window.onerror(String(error && error.message ? error.message : error), '', 0, 0, error);
    } catch (_error) {}
  }
}

function __twebDispatchWindowMessage(targetWindow, sourceWindow, message, targetOrigin = '*') {
  const origin = String(targetOrigin) === '*'
    ? ((sourceWindow && sourceWindow.location && sourceWindow.location.origin) || location.origin)
    : String(targetOrigin);
  __twebEnqueueTimer(() => {
    __twebDispatchEventOnTarget(
      targetWindow,
      new MessageEvent('message', {
        data: message,
        origin,
        source: sourceWindow || window,
        ports: [],
      })
    );
  });
}

function __twebCreateIframeWindow(frameElement) {
  const frameDocument = document.implementation.createHTMLDocument('');
  const frameLocation = {
    href: 'about:blank',
    protocol: 'about:',
    host: '',
    hostname: '',
    pathname: 'blank',
    search: '',
    hash: '',
    origin: 'null',
    assign() {},
    replace() {},
    reload() {},
    toString() { return this.href; },
    valueOf() { return this.href; },
  };
  const frameWindow = new EventTarget();
  const parentWindow = Object.create(window);
  parentWindow.postMessage = function(message, targetOrigin = '*') {
    __twebDispatchWindowMessage(window, frameWindow, message, targetOrigin);
  };
  parentWindow.parent = parentWindow;
  parentWindow.top = parentWindow;
  parentWindow.window = parentWindow;
  parentWindow.self = parentWindow;
  Object.assign(frameWindow, {
    document: frameDocument,
    location: frameLocation,
    origin: frameLocation.origin,
    parent: parentWindow,
    top: parentWindow,
    frameElement,
    navigator,
    postMessage(message, targetOrigin = '*') {
      __twebDispatchWindowMessage(frameWindow, window, message, targetOrigin);
    },
    focus() {},
    blur() {},
  });
  frameWindow.window = frameWindow;
  frameWindow.self = frameWindow;
  frameDocument.defaultView = frameWindow;
  frameDocument.location = frameLocation;
  return frameWindow;
}

function __twebRefreshIframeWindow(frameElement) {
  const frameWindow = frameElement.contentWindow;
  if (!frameWindow) {
    return null;
  }
  const frameLocation = frameWindow.location;
  const target = frameElement.getAttribute('src') || 'about:blank';
  const resolved = target === 'about:blank'
    ? __twebParseResolvedUrl('about:blank')
    : __twebParseResolvedUrl(__twebResolveLocationTarget(target));
  frameLocation.href = resolved.href;
  frameLocation.protocol = resolved.protocol;
  frameLocation.host = resolved.host;
  frameLocation.hostname = resolved.hostname;
  frameLocation.pathname = resolved.pathname;
  frameLocation.search = resolved.search;
  frameLocation.hash = resolved.hash;
  frameLocation.origin = resolved.origin || 'null';
  frameWindow.origin = frameLocation.origin;
  return frameWindow;
}

function __twebFlushMutationObserver(observer) {
  if (!observer._scheduled || !observer._records.length) {
    observer._scheduled = false;
    return;
  }
  observer._scheduled = false;
  const records = observer.takeRecords();
  if (records.length) {
    observer.callback(records, observer);
  }
}

function __twebQueueMutationRecord(record) {
  __twebMutationObservers.forEach((entry) => {
    const { observer, target, options } = entry;
    if (!target || !record.target) {
      return;
    }
    const isTarget = record.target === target;
    const isDescendant = !!options.subtree && typeof target.contains === 'function' && target.contains(record.target);
    if (!isTarget && !isDescendant) {
      return;
    }
    if (record.type === 'attributes' && !options.attributes) {
      return;
    }
    if (record.type === 'characterData' && !options.characterData) {
      return;
    }
    if (record.type === 'childList' && !options.childList) {
      return;
    }
    observer._records.push(record);
    if (!observer._scheduled) {
      observer._scheduled = true;
      __twebEnqueueMicrotask(() => __twebFlushMutationObserver(observer));
    }
  });
}

function __twebRecordAttributeMutation(target, attributeName) {
  __twebMarkNamedWindowPropertiesDirty(attributeName);
  __twebQueueMutationRecord({
    type: 'attributes',
    target,
    attributeName: String(attributeName),
  });
}

function __twebRecordCharacterDataMutation(target) {
  __twebQueueMutationRecord({
    type: 'characterData',
    target,
  });
}

function __twebRecordChildListMutation(target, addedNodes = [], removedNodes = []) {
  __twebMarkNamedWindowPropertiesDirty();
  __twebQueueMutationRecord({
    type: 'childList',
    target,
    addedNodes,
    removedNodes,
  });
}

function __twebParseStyle(text) {
  const result = {};
  String(text || '')
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
    .forEach((part) => {
      const index = part.indexOf(':');
      if (index < 0) {
        return;
      }
      const name = part.slice(0, index).trim();
      const value = part.slice(index + 1).trim();
      if (name) {
        result[name] = value;
      }
    });
  return result;
}

function __twebSerializeStyle(styleMap) {
  return Object.entries(styleMap)
    .map(([name, value]) => `${name}: ${value}`)
    .join('; ');
}

function __twebDataKeyToAttribute(name) {
  return `data-${String(name).replace(/[A-Z]/g, (part) => `-${part.toLowerCase()}`)}`;
}

function __twebAttributeToDataKey(name) {
  return String(name)
    .slice(5)
    .replace(/-([a-z])/g, (_match, part) => part.toUpperCase());
}

function __twebPropertyToAttribute(name) {
  if (name === 'className') {
    return 'class';
  }
  if (name === 'htmlFor') {
    return 'for';
  }
  return String(name).replace(/[A-Z]/g, (part) => `-${part.toLowerCase()}`);
}

const __twebReflectedProperties = new Set([
  'id',
  'className',
  'href',
  'src',
  'alt',
  'title',
  'name',
  'type',
  'value',
  'checked',
  'disabled',
  'width',
  'height',
  'hidden',
  'target',
  'rel',
  'role',
  'placeholder',
]);

function __twebMeasureNode(node) {
  const width = Number(node.width) || (node === document.body || node === document.documentElement ? window.innerWidth : 320);
  const height = Number(node.height) || (node === document.body || node === document.documentElement ? window.innerHeight : 24);
  return { width, height };
}

function __twebCreateCanvasContext(canvas) {
  return {
    canvas,
    drawImage() {},
    putImageData() {},
    getImageData(_x, _y, width, height) {
      return {
        width: Number(width) || canvas.width || 1,
        height: Number(height) || canvas.height || 1,
        data: []
      };
    }
  };
}

function __twebCreateCssRule(ruleText) {
  const cssText = String(ruleText || '').trim();
  return {
    cssText,
    selectorText: cssText.split('{')[0].trim()
  };
}

function __twebParseCssRules(cssText) {
  const source = String(cssText || '').trim();
  if (!source) {
    return [];
  }
  const matches = source.match(/[^{}]+\{[^{}]*\}/g) || [];
  if (matches.length > 0) {
    return matches.map((rule) => __twebCreateCssRule(rule));
  }
  return [__twebCreateCssRule(source)];
}

function __twebEnsureStyleSheet(node) {
  if (node.tagName !== 'STYLE') {
    return null;
  }
  if (!node.__twebStyleSheet) {
    const cssRules = [];
    node.__twebStyleSheet = {
      cssRules,
      insertRule(ruleText, index = cssRules.length) {
        const nextIndex = Math.max(0, Math.min(Number(index) || 0, cssRules.length));
        cssRules.splice(nextIndex, 0, __twebCreateCssRule(ruleText));
        return nextIndex;
      },
      deleteRule(index) {
        cssRules.splice(Number(index) || 0, 1);
      }
    };
    node.__twebStyleSheet.styleSheet = {
      get cssText() {
        return cssRules.map((rule) => rule.cssText).join('\n');
      },
      set cssText(value) {
        cssRules.splice(0, cssRules.length, ...__twebParseCssRules(value));
      }
    };
  }
  if (!node.__twebStyleSheetInitialized) {
    node.__twebStyleSheetInitialized = true;
    __twebParseCssRules(node.textContent || '').forEach((rule) => {
      node.__twebStyleSheet.cssRules.push(rule);
    });
  }
  return node.__twebStyleSheet;
}

function __twebCallOwnMethod(target, name, args = []) {
  const descriptor = Object.getOwnPropertyDescriptor(target, name);
  if (!descriptor || typeof descriptor.value !== 'function') {
    throw new TypeError(`${name} is not implemented`);
  }
  return descriptor.value.apply(target, args);
}

let __twebNextTimerId = 1;
let __twebTimerQueue = [];
let __twebMicrotaskQueue = [];
let __twebNextTimerOrder = 1;
let __twebCurrentTime = 0;

function __twebEnqueueTimer(callback, delay = 0, repeatDelay = null) {
  if (callback && !callback.__twebDebugLabel) {
    callback.__twebDebugLabel = repeatDelay == null ? 'timer:timeout' : 'timer:interval';
  }
  const id = __twebNextTimerId++;
  const normalizedDelay = Math.max(0, Number(delay) || 0);
  __twebTimerQueue.push({
    id,
    callback,
    dueTime: __twebCurrentTime + normalizedDelay,
    order: __twebNextTimerOrder++,
    repeatDelay: repeatDelay == null ? null : Math.max(0, Number(repeatDelay) || 0)
  });
  return id;
}

function __twebClearTimer(id) {
  __twebTimerQueue = __twebTimerQueue.filter((entry) => entry.id !== id);
}

function __twebGetCurrentTime() {
  return __twebCurrentTime;
}

function __twebHasPendingTimer(maxDueTime = null) {
  if (!__twebTimerQueue.length) {
    return false;
  }
  if (maxDueTime === null) {
    return true;
  }
  for (const entry of __twebTimerQueue) {
    if (entry && entry.dueTime <= maxDueTime) {
      return true;
    }
  }
  return false;
}

function __twebGetNextTimerDelay() {
  if (!__twebTimerQueue.length) {
    return null;
  }
  let nextDueTime = null;
  for (const entry of __twebTimerQueue) {
    if (!entry) {
      continue;
    }
    if (nextDueTime === null || entry.dueTime < nextDueTime) {
      nextDueTime = entry.dueTime;
    }
  }
  return nextDueTime === null ? null : Math.max(0, nextDueTime - __twebCurrentTime);
}

function __twebRunNextTimer(maxDueTime = null) {
  if (!__twebTimerQueue.length) {
    return false;
  }
  let nextIndex = 0;
  for (let index = 1; index < __twebTimerQueue.length; index += 1) {
    const candidate = __twebTimerQueue[index];
    const current = __twebTimerQueue[nextIndex];
    if (
      candidate.dueTime < current.dueTime ||
      (candidate.dueTime === current.dueTime && candidate.order < current.order)
    ) {
      nextIndex = index;
    }
  }
  const [entry] = __twebTimerQueue.splice(nextIndex, 1);
  if (!entry) {
    return false;
  }
  if (maxDueTime !== null && entry.dueTime > maxDueTime) {
    __twebTimerQueue.splice(nextIndex, 0, entry);
    return false;
  }
  __twebCurrentTime = entry.dueTime;
  try {
    __twebInvokeEventCallback(entry.callback);
  } catch (error) {
    __twebHandleAsyncError(error);
  }
  if (entry.repeatDelay !== null) {
    __twebTimerQueue.push({
      id: entry.id,
      callback: entry.callback,
      dueTime: __twebCurrentTime + entry.repeatDelay,
      order: __twebNextTimerOrder++,
      repeatDelay: entry.repeatDelay
    });
  }
  return true;
}

function __twebEnqueueMicrotask(callback) {
  const id = __twebNextTimerId++;
  __twebMicrotaskQueue.push({ id, callback });
  return id;
}

function __twebRunNextMicrotask() {
  const entry = __twebMicrotaskQueue.shift();
  if (!entry) {
    return false;
  }
  try {
    __twebInvokeEventCallback(entry.callback);
  } catch (error) {
    __twebHandleAsyncError(error);
  }
  return true;
}

function setTimeout(callback, _delay, ...args) {
  return __twebEnqueueTimer(() => callback(...args), _delay);
}

function clearTimeout(id) {
  __twebClearTimer(id);
}

function requestAnimationFrame(callback) {
  return __twebEnqueueTimer(() => callback(__twebCurrentTime), 16);
}

function cancelAnimationFrame(id) {
  __twebClearTimer(id);
}

function setInterval(callback, _delay, ...args) {
  return __twebEnqueueTimer(() => callback(...args), _delay, _delay);
}

function clearInterval(id) {
  __twebClearTimer(id);
}

function requestIdleCallback(callback, options = undefined) {
  const timeout = options && Number.isFinite(Number(options.timeout))
    ? Math.max(0, Number(options.timeout))
    : 1;
  return __twebEnqueueTimer(
    () => callback({ didTimeout: false, timeRemaining() { return 50; } }),
    timeout,
  );
}

function cancelIdleCallback(id) {
  __twebClearTimer(id);
}

function queueMicrotask(callback) {
  __twebEnqueueMicrotask(callback);
}

window.setTimeout = setTimeout;
window.clearTimeout = clearTimeout;
window.requestAnimationFrame = requestAnimationFrame;
window.cancelAnimationFrame = cancelAnimationFrame;
window.setInterval = setInterval;
window.clearInterval = clearInterval;
window.requestIdleCallback = requestIdleCallback;
window.cancelIdleCallback = cancelIdleCallback;
window.queueMicrotask = queueMicrotask;
self.setTimeout = setTimeout;
self.clearTimeout = clearTimeout;
self.requestAnimationFrame = requestAnimationFrame;
self.cancelAnimationFrame = cancelAnimationFrame;
self.setInterval = setInterval;
self.clearInterval = clearInterval;
self.requestIdleCallback = requestIdleCallback;
self.cancelIdleCallback = cancelIdleCallback;
self.queueMicrotask = queueMicrotask;

class Storage {}

function __twebCreateStorage() {
  const values = new Map();
  const storage = Object.create(Storage.prototype);
  const syncProperty = (key) => {
    Object.defineProperty(storage, key, {
      configurable: true,
      enumerable: true,
      get() {
        return values.get(key);
      },
      set(value) {
        values.set(key, String(value));
      },
    });
  };
  Object.defineProperties(storage, {
    [Symbol.toStringTag]: {
      configurable: true,
      value: 'Storage',
    },
    length: {
      configurable: true,
      enumerable: false,
      get() {
        return values.size;
      },
    },
    clear: {
      configurable: true,
      enumerable: false,
      value() {
        Array.from(values.keys()).forEach((key) => {
          values.delete(key);
          delete storage[key];
        });
      },
    },
    getItem: {
      configurable: true,
      enumerable: false,
      value(key) {
        key = String(key);
        return values.has(key) ? values.get(key) : null;
      },
    },
    key: {
      configurable: true,
      enumerable: false,
      value(index) {
        return Array.from(values.keys())[Number(index)] || null;
      },
    },
    removeItem: {
      configurable: true,
      enumerable: false,
      value(key) {
        key = String(key);
        values.delete(key);
        delete storage[key];
      },
    },
    setItem: {
      configurable: true,
      enumerable: false,
      value(key, value) {
        key = String(key);
        values.set(key, String(value));
        syncProperty(key);
      },
    },
  });
  return new Proxy(storage, {
    get(target, prop, receiver) {
      if (typeof prop === 'string' && values.has(prop) && !(prop in target)) {
        syncProperty(prop);
      }
      return Reflect.get(target, prop, receiver);
    },
    set(target, prop, value, receiver) {
      if (typeof prop === 'string' && !(prop in target)) {
        values.set(prop, String(value));
        syncProperty(prop);
        return true;
      }
      return Reflect.set(target, prop, value, receiver);
    },
    deleteProperty(target, prop) {
      if (typeof prop === 'string') {
        values.delete(prop);
      }
      return Reflect.deleteProperty(target, prop);
    },
    ownKeys(target) {
      const keys = new Set(Reflect.ownKeys(target));
      values.forEach((_value, key) => keys.add(key));
      return Array.from(keys);
    },
    getOwnPropertyDescriptor(target, prop) {
      if (typeof prop === 'string' && values.has(prop) && !(prop in target)) {
        syncProperty(prop);
      }
      return Reflect.getOwnPropertyDescriptor(target, prop);
    },
    has(target, prop) {
      return (typeof prop === 'string' && values.has(prop)) || Reflect.has(target, prop);
    },
  });
}

const localStorage = __twebCreateStorage();
const sessionStorage = __twebCreateStorage();
window.Storage = Storage;
self.Storage = Storage;
window.localStorage = localStorage;
window.sessionStorage = sessionStorage;
self.localStorage = localStorage;
self.sessionStorage = sessionStorage;

const __twebIndexedDatabases = new Map();

function __twebCreateStringList(values) {
  const entries = Array.from(values);
  return {
    get length() {
      return entries.length;
    },
    contains(value) {
      return entries.includes(String(value));
    },
    item(index) {
      return entries[Number(index)] || null;
    },
    [Symbol.iterator]() {
      return entries[Symbol.iterator]();
    },
  };
}

class IDBRequest extends EventTarget {
  constructor() {
    super();
    this.result = undefined;
    this.error = null;
    this.source = null;
    this.transaction = null;
    this.readyState = 'pending';
    this.onsuccess = null;
    this.onerror = null;
  }
  __twebResolve(result) {
    this.result = result;
    this.readyState = 'done';
    __twebEnqueueTimer(() => {
      __twebDispatchEventOnTarget(this, new Event('success'));
    });
    this.transaction?.__twebRequestFinished();
  }
  __twebReject(error) {
    this.error = error;
    this.readyState = 'done';
    __twebEnqueueTimer(() => {
      __twebDispatchEventOnTarget(this, new Event('error'));
    });
    this.transaction?.__twebRequestFinished(error);
  }
}

class IDBOpenDBRequest extends IDBRequest {
  constructor() {
    super();
    this.onupgradeneeded = null;
  }
  __twebUpgrade(result) {
    this.result = result;
    __twebDispatchEventOnTarget(this, new Event('upgradeneeded'));
  }
}

class IDBObjectStore {
  constructor(storeMeta, transaction) {
    this._storeMeta = storeMeta;
    this.transaction = transaction;
    this.name = storeMeta.name;
    this.keyPath = storeMeta.keyPath;
    this.autoIncrement = storeMeta.autoIncrement;
  }
  put(value, key) {
    const request = new IDBRequest();
    request.source = this;
    request.transaction = this.transaction;
    this.transaction?.__twebRegisterRequest(request);
    __twebEnqueueTimer(() => {
      let resolvedKey = key;
      if (resolvedKey === undefined && this.keyPath && value && typeof value === 'object') {
        resolvedKey = value[this.keyPath];
      }
      if (resolvedKey === undefined && this.autoIncrement) {
        resolvedKey = this._storeMeta.nextKey++;
      }
      if (resolvedKey === undefined) {
        resolvedKey = String(this._storeMeta.records.size);
      }
      this._storeMeta.records.set(resolvedKey, value);
      request.__twebResolve(resolvedKey);
    });
    return request;
  }
  get(key) {
    const request = new IDBRequest();
    request.source = this;
    request.transaction = this.transaction;
    this.transaction?.__twebRegisterRequest(request);
    __twebEnqueueTimer(() => {
      request.__twebResolve(this._storeMeta.records.has(key) ? this._storeMeta.records.get(key) : undefined);
    });
    return request;
  }
  delete(key) {
    const request = new IDBRequest();
    request.source = this;
    request.transaction = this.transaction;
    this.transaction?.__twebRegisterRequest(request);
    __twebEnqueueTimer(() => {
      this._storeMeta.records.delete(key);
      request.__twebResolve(undefined);
    });
    return request;
  }
  clear() {
    const request = new IDBRequest();
    request.source = this;
    request.transaction = this.transaction;
    this.transaction?.__twebRegisterRequest(request);
    __twebEnqueueTimer(() => {
      this._storeMeta.records.clear();
      request.__twebResolve(undefined);
    });
    return request;
  }
}

class IDBTransaction extends EventTarget {
  constructor(databaseMeta, storeNames, mode = 'readonly') {
    super();
    this.db = new IDBDatabase(databaseMeta);
    this.mode = mode;
    this.error = null;
    this.objectStoreNames = __twebCreateStringList(storeNames);
    this.oncomplete = null;
    this.onerror = null;
    this.onabort = null;
    this._pendingRequests = 0;
    this._completionScheduled = false;
    this._completed = false;
    this.__twebScheduleCompletionCheck();
  }
  __twebRegisterRequest(_request) {
    if (this._completed) {
      return;
    }
    this._pendingRequests += 1;
  }
  __twebRequestFinished(error = null) {
    if (error && !this.error) {
      this.error = error;
    }
    if (this._pendingRequests > 0) {
      this._pendingRequests -= 1;
    }
    this.__twebScheduleCompletionCheck();
  }
  __twebScheduleCompletionCheck() {
    if (this._completionScheduled || this._completed) {
      return;
    }
    this._completionScheduled = true;
    __twebEnqueueTimer(() => {
      this._completionScheduled = false;
      if (this._completed || this._pendingRequests !== 0) {
        return;
      }
      this._completed = true;
      __twebDispatchEventOnTarget(this, new Event(this.error ? 'error' : 'complete'));
    });
  }
  objectStore(name) {
    const storeMeta = this.db._meta.stores.get(String(name));
    if (!storeMeta) {
      throw new DOMException('Object store not found', 'NotFoundError');
    }
    return new IDBObjectStore(storeMeta, this);
  }
  abort() {
    this._completed = true;
    __twebDispatchEventOnTarget(this, new Event('abort'));
  }
}

class IDBDatabase extends EventTarget {
  constructor(meta) {
    super();
    this._meta = meta;
    this.name = meta.name;
    this.version = meta.version;
    this.onclose = null;
  }
  get objectStoreNames() {
    return __twebCreateStringList(this._meta.stores.keys());
  }
  createObjectStore(name, options = {}) {
    const storeName = String(name);
    let storeMeta = this._meta.stores.get(storeName);
    if (!storeMeta) {
      storeMeta = {
        name: storeName,
        keyPath: options.keyPath === undefined ? null : options.keyPath,
        autoIncrement: Boolean(options.autoIncrement),
        nextKey: 1,
        records: new Map(),
      };
      this._meta.stores.set(storeName, storeMeta);
    }
    return new IDBObjectStore(storeMeta, null);
  }
  deleteObjectStore(name) {
    this._meta.stores.delete(String(name));
  }
  transaction(storeNames, mode = 'readonly') {
    const names = Array.isArray(storeNames) ? storeNames.map(String) : [String(storeNames)];
    return new IDBTransaction(this._meta, names, mode);
  }
  close() {}
}

const indexedDB = {
  open(name, version = 1) {
    const dbName = String(name);
    const request = new IDBOpenDBRequest();
    __twebEnqueueTimer(() => {
      let meta = __twebIndexedDatabases.get(dbName);
      const numericVersion = Math.max(1, Number(version) || 1);
      const needsUpgrade = !meta || numericVersion > meta.version;
      if (!meta) {
        meta = { name: dbName, version: numericVersion, stores: new Map() };
        __twebIndexedDatabases.set(dbName, meta);
      } else if (numericVersion > meta.version) {
        meta.version = numericVersion;
      }
      const database = new IDBDatabase(meta);
      request.result = database;
      if (needsUpgrade) {
        request.__twebUpgrade(database);
      }
      request.__twebResolve(database);
    });
    return request;
  },
  deleteDatabase(name) {
    const request = new IDBOpenDBRequest();
    __twebEnqueueTimer(() => {
      __twebIndexedDatabases.delete(String(name));
      request.__twebResolve(undefined);
    });
    return request;
  },
};
window.indexedDB = indexedDB;
self.indexedDB = indexedDB;
window.IDBRequest = IDBRequest;
window.IDBOpenDBRequest = IDBOpenDBRequest;
window.IDBDatabase = IDBDatabase;
window.IDBTransaction = IDBTransaction;
window.IDBObjectStore = IDBObjectStore;
self.IDBRequest = IDBRequest;
self.IDBOpenDBRequest = IDBOpenDBRequest;
self.IDBDatabase = IDBDatabase;
self.IDBTransaction = IDBTransaction;
self.IDBObjectStore = IDBObjectStore;

const history = {
  state: null,
  length: 1,
  scrollRestoration: 'auto',
  pushState(state, _title, url) {
    this.state = state;
    if (url !== undefined && url !== null) {
      __twebApplyLocation(__twebResolveLocationTarget(url));
    }
  },
  replaceState(state, _title, url) {
    this.state = state;
    if (url !== undefined && url !== null) {
      __twebApplyLocation(__twebResolveLocationTarget(url));
    }
  },
  goBackThroughModals() {
    return false;
  },
  back() {},
  forward() {},
  go() {}
};
window.history = history;
self.history = history;

function scrollTo(_x, _y) {}
function scroll(optionsOrX, maybeY) {
  if (typeof optionsOrX === 'object' && optionsOrX !== null) {
    window.scrollX = Number(optionsOrX.left || 0);
    window.scrollY = Number(optionsOrX.top || 0);
  } else {
    window.scrollX = Number(optionsOrX || 0);
    window.scrollY = Number(maybeY || 0);
  }
  window.pageXOffset = window.scrollX;
  window.pageYOffset = window.scrollY;
  self.scrollX = window.scrollX;
  self.scrollY = window.scrollY;
  self.pageXOffset = window.pageXOffset;
  self.pageYOffset = window.pageYOffset;
}
window.scrollTo = scrollTo;
self.scrollTo = scrollTo;
window.scroll = scroll;
self.scroll = scroll;

function getComputedStyle(target) {
  const style = target && target.style ? target.style : {};
  const computed = target && target.__twebNodeId
    ? JSON.parse(__twebGetComputedStyle(target.__twebNodeId))
    : {};
  const names = Array.from(new Set([
    ...Object.keys(computed || {}),
    ...Object.keys(style || {}),
  ]));
  const lookup = (name) => {
    const key = String(name);
    const camelKey = key.replace(/-([a-z])/g, (_match, part) => part.toUpperCase());
    const kebabKey = key.replace(/[A-Z]/g, (part) => `-${part.toLowerCase()}`);
    return computed[key] || computed[camelKey] || computed[kebabKey] || style[key] || style[camelKey] || style[kebabKey] || '';
  };
  const declaration = {
    get length() {
      return names.length;
    },
    item(index) {
      const nextIndex = Number(index) || 0;
      return names[nextIndex] || '';
    },
    getPropertyValue(name) {
      return lookup(name);
    },
    getPropertyPriority(_name) {
      return '';
    },
    entries() {
      return names.map((name) => [name, lookup(name)]);
    },
    keys() {
      return names.slice();
    },
    values() {
      return names.map((name) => lookup(name));
    },
    toJSON() {
      return Object.fromEntries(names.map((name) => [name, lookup(name)]));
    },
    [Symbol.iterator]() {
      return this.keys()[Symbol.iterator]();
    }
  };
  return new Proxy(declaration, {
    get(target, prop, receiver) {
      if (typeof prop === 'string' && !(prop in target)) {
        return lookup(prop);
      }
      return Reflect.get(target, prop, receiver);
    },
    has(target, prop) {
      if (typeof prop === 'string' && names.includes(prop)) {
        return true;
      }
      return Reflect.has(target, prop);
    },
    ownKeys(target) {
      return Array.from(new Set([...Reflect.ownKeys(target), ...names]));
    },
    getOwnPropertyDescriptor(target, prop) {
      if (typeof prop === 'string' && names.includes(prop)) {
        return {
          configurable: true,
          enumerable: true,
          writable: false,
          value: lookup(prop),
        };
      }
      return Reflect.getOwnPropertyDescriptor(target, prop);
    },
  });
}
window.getComputedStyle = getComputedStyle;
self.getComputedStyle = getComputedStyle;

function __twebEvaluateMediaQuery(query) {
  const source = String(query || '').trim().toLowerCase();
  if (!source) {
    return false;
  }
  const clauses = source
    .replace(/^@media\s+/, '')
    .split(/\band\b/)
    .map((part) => part.trim())
    .filter(Boolean);
  let matches = true;
  clauses.forEach((clause) => {
    const normalized = clause.replace(/^\(|\)$/g, '').trim();
    if (!normalized || normalized === 'screen' || normalized === 'all') {
      return;
    }
    const width = Number(window.innerWidth) || 0;
    const height = Number(window.innerHeight) || 0;
    let match = true;
    let result = normalized.match(/^min-width:\s*(\d+)px$/);
    if (result) {
      match = width >= Number(result[1]);
    } else {
      result = normalized.match(/^max-width:\s*(\d+)px$/);
      if (result) {
        match = width <= Number(result[1]);
      } else {
        result = normalized.match(/^min-height:\s*(\d+)px$/);
        if (result) {
          match = height >= Number(result[1]);
        } else {
          result = normalized.match(/^max-height:\s*(\d+)px$/);
          if (result) {
            match = height <= Number(result[1]);
          } else if (normalized === 'orientation: landscape') {
            match = width >= height;
          } else if (normalized === 'orientation: portrait') {
            match = height > width;
          } else {
            match = false;
          }
        }
      }
    }
    matches = matches && match;
  });
  return matches;
}

function matchMedia(query) {
  const media = String(query);
  return {
    media,
    matches: __twebEvaluateMediaQuery(media),
    onchange: null,
    addListener(_callback) {},
    removeListener(_callback) {},
    addEventListener(_type, _callback) {},
    removeEventListener(_type, _callback) {},
    dispatchEvent(_event) { return true; }
  };
}
window.matchMedia = matchMedia;
self.matchMedia = matchMedia;

class Event {
  constructor(type, options = {}) {
    this.type = String(type);
    this.bubbles = Boolean(options.bubbles);
    this.cancelable = Boolean(options.cancelable);
    this.composed = options.composed !== undefined ? Boolean(options.composed) : false;
    this.defaultPrevented = false;
    this.target = null;
    this.currentTarget = null;
    this.eventPhase = 0;
    this.cancelBubble = false;
    this.altKey = Boolean(options.altKey);
    this.ctrlKey = Boolean(options.ctrlKey);
    this.metaKey = Boolean(options.metaKey);
    this.shiftKey = Boolean(options.shiftKey);
    this.clientX = Number(options.clientX || 0);
    this.clientY = Number(options.clientY || 0);
    this.pageX = Number(options.pageX || this.clientX || 0);
    this.pageY = Number(options.pageY || this.clientY || 0);
    this._changedTouches = options.changedTouches;
    this._touches = options.touches;
    this._targetTouches = options.targetTouches;
    this.__twebImmediatePropagationStopped = false;
    this.__twebPath = null;
  }
  preventDefault() {
    if (this.cancelable) {
      this.defaultPrevented = true;
    }
  }
  stopPropagation() {
    this.cancelBubble = true;
  }
  stopImmediatePropagation() {
    this.cancelBubble = true;
    this.__twebImmediatePropagationStopped = true;
  }
  composedPath() {
    if (Array.isArray(this.__twebPath)) {
      return this.__twebPath.slice();
    }
    if (!this.target) {
      return [];
    }
    return __twebBuildEventPath(this.target);
  }
  get changedTouches() {
    return this._changedTouches;
  }
  set changedTouches(value) {
    this._changedTouches = value;
  }
  get touches() {
    if (this._touches !== undefined) {
      return this._touches;
    }
    return this._changedTouches || [];
  }
  set touches(value) {
    this._touches = value;
  }
  get targetTouches() {
    if (this._targetTouches !== undefined) {
      return this._targetTouches;
    }
    return this.touches;
  }
  set targetTouches(value) {
    this._targetTouches = value;
  }
}

class CustomEvent extends Event {
  constructor(type, options = {}) {
    super(type);
    this.detail = options.detail;
  }
}

class MouseEvent extends Event {
  constructor(type, options = {}) {
    super(type, options);
    this.button = Number(options.button || 0);
    this.buttons = Number(options.buttons || 0);
    this.relatedTarget = options.relatedTarget || null;
  }
}

class FocusEvent extends Event {
  constructor(type, options = {}) {
    super(type, options);
    this.relatedTarget = options.relatedTarget || null;
  }
}

class KeyboardEvent extends Event {
  constructor(type, options = {}) {
    super(type, options);
    this.key = options.key || '';
    this.code = options.code || '';
    this.location = Number(options.location || 0);
    this.repeat = Boolean(options.repeat);
    this.isComposing = Boolean(options.isComposing);
    this.charCode = Number(options.charCode || options.keyCode || 0);
    this.keyCode = Number(options.keyCode || 0);
    this.which = Number(options.which || this.keyCode || this.charCode || 0);
  }
}

class InputEvent extends Event {
  constructor(type, options = {}) {
    super(type, options);
    this.data = options.data || null;
    this.inputType = options.inputType || '';
    this.isComposing = Boolean(options.isComposing);
  }
}

class PointerEvent extends MouseEvent {
  constructor(type, options = {}) {
    super(type, options);
    this.pointerId = Number(options.pointerId || 0);
    this.pointerType = options.pointerType || 'mouse';
    this.width = Number(options.width || 1);
    this.height = Number(options.height || 1);
    this.pressure = Number(options.pressure || 0);
    this.tangentialPressure = Number(options.tangentialPressure || 0);
    this.tiltX = Number(options.tiltX || 0);
    this.tiltY = Number(options.tiltY || 0);
    this.twist = Number(options.twist || 0);
    this.isPrimary = options.isPrimary !== undefined ? Boolean(options.isPrimary) : true;
  }
}

class DOMException extends Error {
  constructor(message = '', name = 'Error') {
    super(String(message));
    this.name = String(name);
    this.message = String(message);
  }
}

function __twebCreateSyntheticEvent(kind) {
  return {
    type: String(kind || ''),
    bubbles: false,
    cancelable: false,
    defaultPrevented: false,
    target: null,
    currentTarget: null,
    initEvent(type, bubbles = false, cancelable = false) {
      this.type = String(type);
      this.bubbles = !!bubbles;
      this.cancelable = !!cancelable;
    },
    initCustomEvent(type, bubbles = false, cancelable = false, detail = null) {
      this.initEvent(type, bubbles, cancelable);
      this.detail = detail;
    },
    preventDefault() {
      if (this.cancelable) {
        this.defaultPrevented = true;
      }
    },
  };
}

class MessageEvent extends Event {
  constructor(type, options = {}) {
    super(type);
    this.data = options.data;
    this.origin = options.origin || '';
    this.source = options.source || null;
    this.ports = options.ports || [];
  }
}

window.Event = Event;
window.CustomEvent = CustomEvent;
window.MouseEvent = MouseEvent;
window.FocusEvent = FocusEvent;
window.KeyboardEvent = KeyboardEvent;
window.InputEvent = InputEvent;
window.MessageEvent = MessageEvent;
window.PointerEvent = PointerEvent;
window.DOMException = DOMException;
self.Event = Event;
self.CustomEvent = CustomEvent;
self.MouseEvent = MouseEvent;
self.FocusEvent = FocusEvent;
self.KeyboardEvent = KeyboardEvent;
self.InputEvent = InputEvent;
self.MessageEvent = MessageEvent;
self.PointerEvent = PointerEvent;
self.DOMException = DOMException;

class __TwebImage extends EventTarget {
  constructor(width = 0, height = 0) {
    super();
    this._src = '';
    this.width = Number(width) || 1;
    this.height = Number(height) || 1;
    this.naturalWidth = this.width;
    this.naturalHeight = this.height;
    this.style = {};
    this.complete = false;
    this.onload = null;
    this.onerror = null;
  }
  get src() {
    return this._src;
  }
  set src(value) {
    this._src = String(value);
    this.complete = true;
    __twebEnqueueTimer(() => {
      __twebDispatchEventOnTarget(this, new Event('load'));
    });
  }
  decode() {
    return Promise.resolve();
  }
}
function Image(width = 0, height = 0) {
  return new __TwebImage(width, height);
}
Image.prototype = __TwebImage.prototype;
Object.defineProperty(Image.prototype, 'constructor', {
  value: Image,
  writable: true,
  configurable: true,
});
window.Image = Image;
self.Image = Image;

class Worker extends EventTarget {
  constructor(url) {
    super();
    this.url = String(url);
    this.onmessage = null;
    this.onerror = null;
    this._terminated = false;
    this._workerScope = __twebCreateWorkerGlobalScope(this);
    const source = __twebGetWorkerScriptSource(this.url);
    if (source === null) {
      __twebEnqueueTimer(() => {
        __twebDispatchWorkerError(
          this,
          new DOMException(`Unsupported worker URL: ${this.url}`, 'NetworkError'),
        );
      });
      return;
    }
    __twebEnqueueTimer(() => {
      if (this._terminated) {
        return;
      }
      __twebEvalWorkerSource(this, this._workerScope, source, this.url);
    });
  }
  postMessage(value) {
    if (this._terminated || !this._workerScope) {
      return;
    }
    const workerScope = this._workerScope;
    __twebEnqueueTimer(() => {
      if (this._terminated) {
        return;
      }
      __twebDispatchEventOnTarget(
        workerScope,
        new MessageEvent('message', {
          data: value,
          origin: location.origin,
          source: window,
          ports: [],
        }),
      );
    });
  }
  terminate() {
    this._terminated = true;
    if (this._workerScope) {
      this._workerScope.__twebClosed = true;
      this._workerScope = null;
    }
  }
}
window.Worker = Worker;
self.Worker = Worker;

function __twebGetWorkerScriptSource(url) {
  if (String(url).startsWith('blob:')) {
    return __twebReadObjectUrlText(url);
  }
  return null;
}

function __twebDispatchWorkerError(worker, error) {
  const event = new Event('error');
  event.error = error;
  event.message = error && error.message ? String(error.message) : String(error);
  __twebDispatchEventOnTarget(worker, event);
}

function __twebCreateWorkerGlobalScope(worker) {
  const scope = new EventTarget();
  scope.self = scope;
  scope.globalThis = scope;
  scope.window = undefined;
  scope.document = undefined;
  scope.navigator = navigator;
  scope.location = location;
  scope.console = console;
  scope.performance = performance;
  scope.__twebClosed = false;
  scope.onmessage = null;
  scope.onerror = null;
  scope.postMessage = (value) => {
    if (worker._terminated || scope.__twebClosed) {
      return;
    }
    __twebEnqueueTimer(() => {
      if (worker._terminated || scope.__twebClosed) {
        return;
      }
      __twebDispatchEventOnTarget(
        worker,
        new MessageEvent('message', {
          data: value,
          origin: location.origin,
          source: scope,
          ports: [],
        }),
      );
    });
  };
  scope.close = () => {
    scope.__twebClosed = true;
    worker._terminated = true;
  };
  scope.importScripts = (...urls) => {
    urls.forEach((target) => {
      const source = __twebGetWorkerScriptSource(target);
      if (source === null) {
        throw new DOMException(`Unsupported worker script URL: ${target}`, 'NetworkError');
      }
      __twebEvalWorkerSource(worker, scope, source, target);
    });
  };
  return scope;
}

function __twebEvalWorkerSource(worker, scope, source, url) {
  try {
    const evaluate = new Function(
      'workerSelf',
      `
      const self = workerSelf;
      const globalThis = workerSelf;
      const postMessage = workerSelf.postMessage.bind(workerSelf);
      const addEventListener = workerSelf.addEventListener.bind(workerSelf);
      const removeEventListener = workerSelf.removeEventListener.bind(workerSelf);
      const dispatchEvent = workerSelf.dispatchEvent.bind(workerSelf);
      const importScripts = workerSelf.importScripts.bind(workerSelf);
      const close = workerSelf.close.bind(workerSelf);
      ${String(source)}
      //# sourceURL=${String(url).replace(/\r?\n/g, '')}
      `,
    );
    evaluate.call(scope, scope);
  } catch (error) {
    __twebDispatchWorkerError(worker, error);
  }
}

const __twebBroadcastChannels = new Map();

class BroadcastChannel extends EventTarget {
  constructor(name) {
    super();
    this.name = String(name);
    this.onmessage = null;
    const bucket = __twebBroadcastChannels.get(this.name) || [];
    bucket.push(this);
    __twebBroadcastChannels.set(this.name, bucket);
  }
  postMessage(value) {
    const peers = __twebBroadcastChannels.get(this.name) || [];
    peers.forEach((peer) => {
      if (peer === this) {
        return;
      }
      __twebEnqueueTimer(() => {
        __twebDispatchEventOnTarget(
          peer,
          new MessageEvent('message', {
            data: value,
            origin: location.origin,
            source: window,
            ports: [],
          })
        );
      });
    });
  }
  close() {
    const peers = (__twebBroadcastChannels.get(this.name) || []).filter((peer) => peer !== this);
    if (peers.length) {
      __twebBroadcastChannels.set(this.name, peers);
    } else {
      __twebBroadcastChannels.delete(this.name);
    }
  }
}

window.BroadcastChannel = BroadcastChannel;
self.BroadcastChannel = BroadcastChannel;

class WeakRef {
  constructor(value) {
    this._value = value;
  }
  deref() {
    return this._value;
  }
}

class FinalizationRegistry {
  constructor(_callback) {}
  register(_target, _heldValue, _unregisterToken) {}
  unregister(_unregisterToken) {
    return false;
  }
}

window.WeakRef = WeakRef;
self.WeakRef = WeakRef;
window.FinalizationRegistry = FinalizationRegistry;
self.FinalizationRegistry = FinalizationRegistry;

class AbortSignal extends EventTarget {
  constructor() {
    super();
    this.aborted = false;
    this.reason = undefined;
    this.onabort = null;
  }
  static timeout(milliseconds = 0) {
    const controller = new AbortController();
    __twebEnqueueTimer(() => {
      controller.abort(new DOMException('Signal timed out', 'TimeoutError'));
    }, Math.max(0, Number(milliseconds) || 0));
    return controller.signal;
  }
}

class AbortController {
  constructor() {
    this.signal = new AbortSignal();
  }
  abort(reason = undefined) {
    if (this.signal.aborted) {
      return;
    }
    this.signal.aborted = true;
    this.signal.reason = reason;
    __twebDispatchEventOnTarget(this.signal, new Event('abort'));
  }
}

window.AbortSignal = AbortSignal;
window.AbortController = AbortController;
self.AbortSignal = AbortSignal;
self.AbortController = AbortController;

function structuredClone(value) {
  if (value === null || typeof value !== 'object') {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => structuredClone(entry));
  }
  if (value instanceof Date) {
    return new Date(value.getTime());
  }
  if (value instanceof Map) {
    return new Map(Array.from(value.entries(), ([key, entry]) => [structuredClone(key), structuredClone(entry)]));
  }
  if (value instanceof Set) {
    return new Set(Array.from(value.values(), (entry) => structuredClone(entry)));
  }
  if (value instanceof ArrayBuffer) {
    return value.slice(0);
  }
  if (ArrayBuffer.isView(value)) {
    return new value.constructor(value);
  }
  const next = {};
  Object.keys(value).forEach((key) => {
    next[key] = structuredClone(value[key]);
  });
  return next;
}

window.structuredClone = structuredClone;
self.structuredClone = structuredClone;

class DOMParser {
  parseFromString(source, mimeType = 'text/html') {
    if (String(mimeType).toLowerCase().includes('html')) {
      const documentNode = document.implementation.createHTMLDocument('');
      documentNode.body.innerHTML = String(source || '');
      return documentNode;
    }
    const rootNodeId = __twebParseXmlDocument(String(source || ''));
    const rootNode = rootNodeId ? __twebWrapNode(rootNodeId) : null;
    const xmlDocument = Object.create(Document.prototype);
    Object.defineProperties(xmlDocument, {
      documentElement: { get() { return rootNode; } },
      body: { get() { return null; } },
      head: { get() { return null; } },
      nodeType: { get() { return Node.DOCUMENT_NODE; } },
      nodeName: { get() { return '#document'; } },
      ownerDocument: { get() { return null; } },
      parentNode: { get() { return null; } },
      childNodes: { get() { return __twebCreateNodeList(rootNode ? [rootNode] : []); } },
      children: { get() { return __twebCreateHTMLCollection(rootNode ? [rootNode] : []); } },
      firstChild: { get() { return rootNode; } },
      lastChild: { get() { return rootNode; } },
    });
    // XML names are case-sensitive, and selector engines inspect nodeName and
    // ownerDocument to choose XML matching rather than HTML matching.
    if (rootNode) {
      const pending = [rootNode];
      while (pending.length) {
        const node = pending.pop();
        Object.defineProperty(node, 'ownerDocument', { value: xmlDocument, configurable: true });
        if (node.nodeType === Node.ELEMENT_NODE) {
          Object.defineProperty(node, 'tagName', { value: __twebGetNodeTagName(node.__twebNodeId), configurable: true });
          Object.defineProperty(node, 'namespaceURI', { value: null, configurable: true });
        }
        pending.push(...Array.from(node.childNodes || []));
      }
    }
    // Selector engines create temporary nodes when probing a new document.
    xmlDocument.createElement = document.createElement.bind(document);
    xmlDocument.createElementNS = document.createElementNS.bind(document);
    xmlDocument.createTextNode = document.createTextNode.bind(document);
    xmlDocument.createComment = document.createComment.bind(document);
    xmlDocument.createDocumentFragment = document.createDocumentFragment.bind(document);
    xmlDocument.getElementById = function(id) {
      return this.querySelector(`#${String(id)}`);
    };
    xmlDocument.querySelector = function(selector) {
      return rootNode ? rootNode.querySelector(selector) : null;
    };
    xmlDocument.querySelectorAll = function(selector) {
      return rootNode ? rootNode.querySelectorAll(selector) : __twebCreateNodeList([]);
    };
    xmlDocument.getElementsByTagName = function(tagName) {
      if (!rootNode) {
        return __twebCreateHTMLCollection([]);
      }
      const matches = Array.from(rootNode.getElementsByTagName(tagName));
      if (String(rootNode.tagName).toLowerCase() === String(tagName).toLowerCase()) {
        matches.unshift(rootNode);
      }
      return __twebCreateHTMLCollection(matches);
    };
    return xmlDocument;
  }
}

const cookieStore = {
  get(name) {
    const params = new URLSearchParams(__twebGetCookieString().replace(/; /g, '&'));
    const value = params.get(String(name));
    return Promise.resolve(value == null ? null : { name: String(name), value });
  },
  set(name, value) {
    document.cookie = `${String(name)}=${String(value)}`;
    return Promise.resolve();
  },
  delete(name) {
    document.cookie = `${String(name)}=; Max-Age=0`;
    return Promise.resolve();
  },
};

window.DOMParser = DOMParser;
self.DOMParser = DOMParser;
window.cookieStore = cookieStore;
self.cookieStore = cookieStore;
window.CookieStore = function CookieStore() {};
self.CookieStore = window.CookieStore;

class FileReader extends EventTarget {
  constructor() {
    super();
    this.result = null;
    this.error = null;
    this.onload = null;
    this.onerror = null;
  }
  readAsDataURL(blob) {
    this.result = typeof blob === 'string' ? blob : 'data:application/octet-stream;base64,';
    __twebEnqueueTimer(() => __twebDispatchEventOnTarget(this, new Event('load')));
  }
  readAsText(blob) {
    this.result = typeof blob === 'string' ? blob : '';
    __twebEnqueueTimer(() => __twebDispatchEventOnTarget(this, new Event('load')));
  }
}

window.FileReader = FileReader;
self.FileReader = FileReader;

class MutationObserver {
  constructor(callback) {
    this.callback = callback;
    this._records = [];
    this._scheduled = false;
  }
  observe(target, options = {}) {
    this.disconnect();
    __twebMutationObservers.push({
      observer: this,
      target,
      options: {
        childList: !!options.childList,
        attributes: !!options.attributes,
        characterData: !!options.characterData,
        subtree: !!options.subtree,
      },
    });
  }
  disconnect() {
    for (let index = __twebMutationObservers.length - 1; index >= 0; index -= 1) {
      if (__twebMutationObservers[index].observer === this) {
        __twebMutationObservers.splice(index, 1);
      }
    }
    this._scheduled = false;
  }
  takeRecords() {
    const records = this._records.slice();
    this._records = [];
    return records;
  }
}

class ResizeObserver {
  constructor(callback) {
    this.callback = callback;
  }
  observe(target) {
    __twebEnqueueTimer(() => this.callback([{ target, contentRect: target.getBoundingClientRect() }], this));
  }
  unobserve(_target) {}
  disconnect() {}
}

class PerformanceObserver {
  constructor(callback) {
    this.callback = callback;
    this._entries = [];
  }
  observe(_options = {}) {}
  disconnect() {}
  takeRecords() {
    const entries = this._entries.slice();
    this._entries = [];
    return entries;
  }
}

class IntersectionObserver {
  constructor(callback) {
    this.callback = callback;
  }
  observe(target) {
    __twebEnqueueTimer(() => this.callback([{
      target,
      isIntersecting: true,
      intersectionRatio: 1,
      boundingClientRect: target.getBoundingClientRect(),
      intersectionRect: target.getBoundingClientRect(),
      rootBounds: null,
      time: Date.now()
    }], this));
  }
  unobserve(_target) {}
  disconnect() {}
  takeRecords() { return []; }
}

window.MutationObserver = MutationObserver;
window.PerformanceObserver = PerformanceObserver;
window.ResizeObserver = ResizeObserver;
window.IntersectionObserver = IntersectionObserver;
self.MutationObserver = MutationObserver;
self.PerformanceObserver = PerformanceObserver;
self.ResizeObserver = ResizeObserver;
self.IntersectionObserver = IntersectionObserver;

class MessagePort extends EventTarget {
  constructor() {
    super();
    this.onmessage = null;
    this._entangledPort = null;
    this._started = true;
  }
  postMessage(value) {
    if (!this._entangledPort) {
      return;
    }
    const target = this._entangledPort;
    __twebEnqueueTimer(() => {
      __twebDispatchEventOnTarget(
        target,
        new MessageEvent('message', {
          data: value,
          origin: location.origin,
          source: this,
          ports: [this],
        })
      );
    });
  }
  start() {
    this._started = true;
  }
  close() {
    this._entangledPort = null;
  }
}

class MessageChannel {
  constructor() {
    this.port1 = new MessagePort();
    this.port2 = new MessagePort();
    this.port1._entangledPort = this.port2;
    this.port2._entangledPort = this.port1;
  }
}

function postMessage(message, targetOrigin = '*') {
  const origin = String(targetOrigin) === '*' ? location.origin : String(targetOrigin);
  __twebEnqueueTimer(() => {
    __twebDispatchEventOnTarget(
      window,
      new MessageEvent('message', {
        data: message,
        origin,
        source: window,
        ports: [],
      })
    );
  });
}

window.MessageChannel = MessageChannel;
window.MessagePort = MessagePort;
window.postMessage = postMessage;
self.MessageChannel = MessageChannel;
self.MessagePort = MessagePort;
self.postMessage = postMessage;

function __twebNormalizeHeaders(headers) {
  if (!headers) {
    return {};
  }
  const normalizeKey = (key) => String(key).toLowerCase();
  if (Array.isArray(headers)) {
    const result = {};
    headers.forEach(([key, value]) => {
      result[normalizeKey(key)] = String(value);
    });
    return result;
  }
  if (typeof headers.forEach === 'function') {
    const result = {};
    headers.forEach((value, key) => {
      result[normalizeKey(key)] = String(value);
    });
    return result;
  }
  const result = {};
  Object.entries(headers).forEach(([key, value]) => {
    result[normalizeKey(key)] = String(value);
  });
  return result;
}

class Headers {
  constructor(init = {}) {
    this._values = __twebNormalizeHeaders(init);
  }
  append(name, value) {
    this._values[String(name).toLowerCase()] = String(value);
  }
  delete(name) {
    delete this._values[String(name).toLowerCase()];
  }
  get(name) {
    return this._values[String(name).toLowerCase()] || null;
  }
  has(name) {
    return this.get(name) !== null;
  }
  set(name, value) {
    this._values[String(name).toLowerCase()] = String(value);
  }
  forEach(callback) {
    Object.entries(this._values).forEach(([key, value]) => callback(value, key, this));
  }
  entries() {
    return Object.entries(this._values)[Symbol.iterator]();
  }
  keys() {
    return Object.keys(this._values)[Symbol.iterator]();
  }
  values() {
    return Object.values(this._values)[Symbol.iterator]();
  }
  [Symbol.iterator]() {
    return this.entries();
  }
}

class URLSearchParams {
  constructor(init = '') {
    this._pairs = [];
    if (init instanceof URLSearchParams) {
      init.forEach((value, key) => this.append(key, value));
      return;
    }
    if (typeof init === 'string') {
      const source = init.startsWith('?') ? init.slice(1) : init;
      if (source) {
        source.split('&').forEach((part) => {
          if (!part) {
            return;
          }
          const [rawKey, rawValue = ''] = part.split('=');
          this.append(
            decodeURIComponent(rawKey.replace(/\+/g, ' ')),
            decodeURIComponent(rawValue.replace(/\+/g, ' '))
          );
        });
      }
      return;
    }
    if (Array.isArray(init)) {
      init.forEach(([key, value]) => this.append(key, value));
      return;
    }
    Object.entries(init || {}).forEach(([key, value]) => this.append(key, value));
  }
  append(key, value) {
    this._pairs.push([String(key), String(value)]);
  }
  delete(key, value) {
    const matchKey = String(key);
    if (arguments.length < 2) {
      this._pairs = this._pairs.filter(([entryKey]) => entryKey !== matchKey);
      return;
    }
    const matchValue = String(value);
    this._pairs = this._pairs.filter(([entryKey, entryValue]) => entryKey !== matchKey || entryValue !== matchValue);
  }
  entries() {
    return this._pairs[Symbol.iterator]();
  }
  forEach(callback, thisArg = undefined) {
    this._pairs.forEach(([key, value]) => {
      callback.call(thisArg, value, key, this);
    });
  }
  get(key) {
    const match = this._pairs.find(([entryKey]) => entryKey === String(key));
    return match ? match[1] : null;
  }
  getAll(key) {
    const matchKey = String(key);
    return this._pairs
      .filter(([entryKey]) => entryKey === matchKey)
      .map(([, entryValue]) => entryValue);
  }
  has(key, value) {
    const matchKey = String(key);
    if (arguments.length < 2) {
      return this._pairs.some(([entryKey]) => entryKey === matchKey);
    }
    const matchValue = String(value);
    return this._pairs.some(([entryKey, entryValue]) => entryKey === matchKey && entryValue === matchValue);
  }
  set(key, value) {
    const matchKey = String(key);
    const nextValue = String(value);
    let replaced = false;
    const nextPairs = [];
    this._pairs.forEach(([entryKey, entryValue]) => {
      if (entryKey !== matchKey) {
        nextPairs.push([entryKey, entryValue]);
        return;
      }
      if (!replaced) {
        nextPairs.push([entryKey, nextValue]);
        replaced = true;
      }
    });
    if (!replaced) {
      nextPairs.push([matchKey, nextValue]);
    }
    this._pairs = nextPairs;
  }
  sort() {
    this._pairs.sort(([left], [right]) => left.localeCompare(right));
  }
  keys() {
    return this._pairs.map(([key]) => key)[Symbol.iterator]();
  }
  values() {
    return this._pairs.map(([, value]) => value)[Symbol.iterator]();
  }
  toString() {
    return this._pairs
      .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
      .join('&');
  }
  get size() {
    return this._pairs.length;
  }
  [Symbol.iterator]() {
    return this.entries();
  }
}

function __twebAttachUrlSearchParams(url) {
  if (!url || typeof url !== 'object') {
    return url;
  }
  if (Object.prototype.hasOwnProperty.call(url, 'searchParams')) {
    return url;
  }
  Object.defineProperty(url, 'searchParams', {
    configurable: true,
    enumerable: true,
    get() {
      if (!this.__twebSearchParams) {
        const params = new URLSearchParams(this.search || '');
        const sync = () => {
          const query = params.toString();
          this.search = query ? `?${query}` : '';
          this.href = `${this.origin || ''}${this.pathname || '/'}${this.search}${this.hash || ''}`;
        };
        ['append', 'delete', 'set', 'sort'].forEach((name) => {
          const original = params[name].bind(params);
          params[name] = (...args) => {
            const result = original(...args);
            sync();
            return result;
          };
        });
        this.__twebSearchParams = params;
      }
      return this.__twebSearchParams;
    },
  });
  return url;
}

class FormData {
  constructor() {
    this._pairs = [];
  }
  append(key, value) {
    this._pairs.push([String(key), String(value)]);
  }
  forEach(callback) {
    this._pairs.forEach(([key, value]) => callback(value, key, this));
  }
  entries() {
    return this._pairs[Symbol.iterator]();
  }
  keys() {
    return this._pairs.map(([key]) => key)[Symbol.iterator]();
  }
  values() {
    return this._pairs.map(([, value]) => value)[Symbol.iterator]();
  }
  [Symbol.iterator]() {
    return this.entries();
  }
}

class Blob {
  constructor(parts = [], options = {}) {
    const bytes = [];
    parts.forEach((part) => {
      const chunk = __twebToUint8Array(part);
      for (const value of chunk) {
        bytes.push(value);
      }
    });
    this._bytes = new Uint8Array(bytes);
    this.size = this._bytes.length;
    this.type = String(options.type || '').toLowerCase();
  }
  text() {
    return Promise.resolve(new TextDecoder().decode(this._bytes));
  }
  arrayBuffer() {
    return Promise.resolve(this._bytes.buffer.slice(0));
  }
  slice(start = 0, end = this.size, type = '') {
    return new Blob([this._bytes.slice(start, end)], { type });
  }
}

class File extends Blob {
  constructor(parts = [], name = '', options = {}) {
    super(parts, options);
    this.name = String(name);
    this.lastModified = Number(options.lastModified || Date.now());
  }
}

class NodeList extends Array {
  item(index) {
    return this[index] || null;
  }
}

class HTMLCollection extends Array {
  item(index) {
    return this[index] || null;
  }
  namedItem(name) {
    const target = String(name);
    return this.find((entry) => entry && (entry.id === target || entry.getAttribute && entry.getAttribute('name') === target)) || null;
  }
}

class NamedNodeMap extends Array {
  item(index) {
    return this[index] || null;
  }
  getNamedItem(name) {
    const target = String(name);
    return this.find((entry) => entry && entry.name === target) || null;
  }
  getNamedItemNS(_namespace, name) {
    return this.getNamedItem(name);
  }
  setNamedItem(attribute) {
    return attribute || null;
  }
  setNamedItemNS(attribute) {
    return this.setNamedItem(attribute);
  }
  removeNamedItem(name) {
    return this.getNamedItem(name);
  }
  removeNamedItemNS(_namespace, name) {
    return this.removeNamedItem(name);
  }
}

function __twebCreateAttrNode(element, name, value) {
  return {
    name: String(name),
    value: String(value),
    ownerElement: element,
    specified: true,
    get nodeName() {
      return this.name;
    },
    get nodeValue() {
      return this.value;
    },
    set nodeValue(nextValue) {
      this.value = String(nextValue);
      if (this.ownerElement && typeof this.ownerElement.setAttribute === 'function') {
        this.ownerElement.setAttribute(this.name, this.value);
      }
    },
    get textContent() {
      return this.value;
    },
    set textContent(nextValue) {
      this.nodeValue = nextValue;
    },
    cloneNode() {
      return __twebCreateAttrNode(null, this.name, this.value);
    },
  };
}

function __twebCreateNamedNodeMap(element, nodeId) {
  const readEntries = () => Object.entries(JSON.parse(__twebGetAttributes(nodeId))).map(
    ([name, value]) => __twebCreateAttrNode(element, name, value)
  );
  const target = new NamedNodeMap();
  return new Proxy(target, {
    get(target, prop, receiver) {
      const entries = readEntries();
      if (prop === 'length') {
        return entries.length;
      }
      if (prop === 'item') {
        return (index) => entries[Number(index) || 0] || null;
      }
      if (prop === 'getNamedItem') {
        return (name) => entries.find((entry) => entry.name === String(name)) || null;
      }
      if (prop === 'getNamedItemNS') {
        return (_namespace, name) => entries.find((entry) => entry.name === String(name)) || null;
      }
      if (prop === 'setNamedItem') {
        return (attribute) => {
          if (!attribute || typeof attribute.name !== 'string') {
            throw new TypeError('Invalid attribute node');
          }
          const previous = entries.find((entry) => entry.name === String(attribute.name)) || null;
          if (element && typeof element.setAttribute === 'function') {
            element.setAttribute(attribute.name, attribute.value || '');
          }
          attribute.ownerElement = element || null;
          return previous;
        };
      }
      if (prop === 'setNamedItemNS') {
        return (attribute) => {
          if (!attribute || typeof attribute.name !== 'string') {
            throw new TypeError('Invalid attribute node');
          }
          const previous = entries.find((entry) => entry.name === String(attribute.name)) || null;
          if (element && typeof element.setAttribute === 'function') {
            element.setAttribute(attribute.name, attribute.value || '');
          }
          attribute.ownerElement = element || null;
          return previous;
        };
      }
      if (typeof prop === 'string') {
        if (/^\d+$/.test(prop)) {
          return entries[Number(prop)] || null;
        }
        const named = entries.find((entry) => entry.name === prop);
        if (named) {
          return named;
        }
      }
      return Reflect.get(target, prop, receiver);
    },
    ownKeys(target) {
      const entries = readEntries();
      return Array.from(new Set([
        ...Reflect.ownKeys(target),
        ...entries.map((_entry, index) => String(index)),
        ...entries.map((entry) => entry.name),
      ]));
    },
    getOwnPropertyDescriptor(target, prop) {
      const entries = readEntries();
      if (prop === 'length') {
        return {
          configurable: true,
          enumerable: false,
          writable: false,
          value: entries.length,
        };
      }
      if (typeof prop === 'string') {
        if (/^\d+$/.test(prop)) {
          const entry = entries[Number(prop)] || null;
          if (entry) {
            return {
              configurable: true,
              enumerable: true,
              writable: false,
              value: entry,
            };
          }
        }
        const named = entries.find((entry) => entry.name === prop);
        if (named) {
          return {
            configurable: true,
            enumerable: true,
            writable: false,
            value: named,
          };
        }
      }
      return Reflect.getOwnPropertyDescriptor(target, prop);
    },
  });
}

function __twebCreateTokenList(getValue, setValue, supportChecker = null) {
  const readTokens = () => String(getValue() || '').split(/\s+/).filter(Boolean);
  const writeTokens = (tokens) => {
    setValue(Array.from(new Set(tokens)).join(' '));
  };
  return {
    get value() {
      return readTokens().join(' ');
    },
    set value(value) {
      writeTokens(String(value || '').split(/\s+/).filter(Boolean));
    },
    get length() {
      return readTokens().length;
    },
    item(index) {
      return readTokens()[index] || null;
    },
    contains(token) {
      return readTokens().includes(String(token));
    },
    add(...tokens) {
      writeTokens(readTokens().concat(tokens.map((token) => String(token))));
    },
    remove(...tokens) {
      const blocked = new Set(tokens.map((token) => String(token)));
      writeTokens(readTokens().filter((token) => !blocked.has(token)));
    },
    toggle(token, force) {
      const text = String(token);
      const present = readTokens().includes(text);
      if (force === true || (!present && force !== false)) {
        this.add(text);
        return true;
      }
      if (present) {
        this.remove(text);
      }
      return false;
    },
    replace(oldToken, newToken) {
      const current = readTokens();
      const oldText = String(oldToken);
      const newText = String(newToken);
      const index = current.indexOf(oldText);
      if (index < 0) {
        return false;
      }
      current[index] = newText;
      writeTokens(current);
      return true;
    },
    supports(token) {
      if (typeof supportChecker !== 'function') {
        return false;
      }
      return !!supportChecker(String(token));
    },
    forEach(callback, thisArg = undefined) {
      readTokens().forEach((token, index) => callback.call(thisArg, token, index, this));
    },
    [Symbol.iterator]() {
      return readTokens()[Symbol.iterator]();
    },
  };
}

function __twebCreateRelList(node) {
  const supported = new Set([
    'alternate',
    'apple-touch-icon',
    'dns-prefetch',
    'icon',
    'modulepreload',
    'noopener',
    'noreferrer',
    'prefetch',
    'preconnect',
    'preload',
    'stylesheet',
  ]);
  return __twebCreateTokenList(
    () => node.rel || '',
    (value) => { node.rel = value; },
    (token) => supported.has(String(token).toLowerCase()),
  );
}

function __twebDefaultNamespaceURI(node, tagName) {
  if (tagName === '#text' || tagName === '#comment' || tagName === '#doctype' || tagName === 'fragment') {
    return null;
  }
  if (node.__twebNamespaceURI) {
    return node.__twebNamespaceURI;
  }
  const parent = node.parentNode;
  if (parent && parent !== document && parent.namespaceURI) {
    if (parent.namespaceURI === 'http://www.w3.org/2000/svg' && tagName !== 'foreignObject') {
      return parent.namespaceURI;
    }
    if (parent.namespaceURI === 'http://www.w3.org/1998/Math/MathML') {
      return parent.namespaceURI;
    }
  }
  if (tagName === 'svg') {
    return 'http://www.w3.org/2000/svg';
  }
  if (tagName === 'math') {
    return 'http://www.w3.org/1998/Math/MathML';
  }
  return 'http://www.w3.org/1999/xhtml';
}

class ReadableStream {
  constructor(source = {}) {
    this._chunks = [];
    this._closed = false;
    this._error = null;
    this._pendingReads = [];
    this._pendingClosedResolves = [];
    this._pendingClosedRejects = [];
    this.locked = false;
    this._pullAlgorithm = null;
    this._cancelAlgorithm = null;
    this._pulling = false;
    this._pullAgain = false;
    this.__twebEnqueue = (chunk) => {
      if (this._closed || this._error) {
        return;
      }
      if (this._pendingReads.length) {
        const { resolve } = this._pendingReads.shift();
        resolve({ value: chunk, done: false });
        return;
      }
      this._chunks.push(chunk);
    };
    this.__twebClose = () => {
      if (this._closed) {
        return;
      }
      this._closed = true;
      while (this._pendingReads.length) {
        const { resolve } = this._pendingReads.shift();
        resolve({ value: undefined, done: true });
      }
      while (this._pendingClosedResolves.length) {
        this._pendingClosedResolves.shift()();
      }
      this._pendingClosedRejects = [];
    };
    this.__twebError = (error) => {
      this._error = error;
      while (this._pendingReads.length) {
        const { reject } = this._pendingReads.shift();
        reject(error);
      }
      while (this._pendingClosedRejects.length) {
        this._pendingClosedRejects.shift()(error);
      }
      this._pendingClosedResolves = [];
    };
    if (Array.isArray(source)) {
      this._chunks = source.slice();
      this._closed = true;
      return;
    }
    const controller = {
      enqueue: (chunk) => this.__twebEnqueue(chunk),
      close: () => this.__twebClose(),
      error: (error) => this.__twebError(error),
      get desiredSize() {
        return 1;
      },
    };
    if (source && typeof source.pull === 'function') {
      this._pullAlgorithm = () => Promise.resolve(source.pull(controller));
    }
    if (source && typeof source.cancel === 'function') {
      this._cancelAlgorithm = (reason) => Promise.resolve(source.cancel(reason));
    }
    this._maybePull = () => {
      if (
        this._closed ||
        this._error ||
        !this._pullAlgorithm ||
        this._chunks.length > 0 ||
        !this._pendingReads.length
      ) {
        return;
      }
      if (this._pulling) {
        this._pullAgain = true;
        return;
      }
      this._pulling = true;
      this._pullAlgorithm().then(() => {
        this._pulling = false;
        if (this._pullAgain) {
          this._pullAgain = false;
          this._maybePull();
        }
      }, (error) => {
        this._pulling = false;
        this.__twebError(error);
      });
    };
    if (source && typeof source.start === 'function') {
      Promise.resolve(source.start(controller)).then(() => {
        this._maybePull();
      }, (error) => {
        this.__twebError(error);
      });
      return;
    }
    if (!this._pullAlgorithm) {
      this._closed = true;
    }
  }
  getReader() {
    this.locked = true;
    const stream = this;
    const closed = new Promise((resolve, reject) => {
      if (stream._error) {
        reject(stream._error);
        return;
      }
      if (stream._closed) {
        resolve();
        return;
      }
      stream._pendingClosedResolves.push(resolve);
      stream._pendingClosedRejects.push(reject);
    });
    return {
      closed,
      read() {
        if (stream._chunks.length) {
          return Promise.resolve({ value: stream._chunks.shift(), done: false });
        }
        if (stream._error) {
          return Promise.reject(stream._error);
        }
        if (!stream._closed) {
          return new Promise((resolve, reject) => {
            stream._pendingReads.push({
              resolve,
              reject,
            });
            stream._maybePull();
          });
        }
        return Promise.resolve({ value: undefined, done: true });
      },
      releaseLock() {
        stream.locked = false;
      },
      cancel(reason = undefined) {
        stream._chunks = [];
        stream._closed = true;
        while (stream._pendingReads.length) {
          const { resolve } = stream._pendingReads.shift();
          resolve({ value: undefined, done: true });
        }
        while (stream._pendingClosedResolves.length) {
          stream._pendingClosedResolves.shift()();
        }
        stream._pendingClosedRejects = [];
        stream.locked = false;
        if (stream._cancelAlgorithm) {
          return stream._cancelAlgorithm(reason);
        }
        return Promise.resolve();
      },
    };
  }
  cancel(reason = undefined) {
    this._chunks = [];
    this._closed = true;
    while (this._pendingReads.length) {
      const { resolve } = this._pendingReads.shift();
      resolve({ value: undefined, done: true });
    }
    while (this._pendingClosedResolves.length) {
      this._pendingClosedResolves.shift()();
    }
    this._pendingClosedRejects = [];
    if (this._cancelAlgorithm) {
      return this._cancelAlgorithm(reason);
    }
    return Promise.resolve();
  }
  tee() {
    const sourceReader = this.getReader();
    const controllers = [null, null];
    const canceled = [false, false];
    const reasons = [undefined, undefined];
    let reading = false;
    const maybeCancelSource = () => {
      if (!canceled[0] || !canceled[1]) {
        return Promise.resolve();
      }
      return sourceReader.cancel([reasons[0], reasons[1]]);
    };
    const pump = () => {
      if (reading) {
        return;
      }
      reading = true;
      sourceReader.read().then(({ value, done }) => {
        reading = false;
        if (done) {
          controllers.forEach((controller, index) => {
            if (!canceled[index] && controller) {
              controller.close();
            }
          });
          return;
        }
        controllers.forEach((controller, index) => {
          if (!canceled[index] && controller) {
            controller.enqueue(value);
          }
        });
        pump();
      }, (error) => {
        reading = false;
        controllers.forEach((controller, index) => {
          if (!canceled[index] && controller) {
            controller.error(error);
          }
        });
      });
    };
    const makeBranch = (index) => new ReadableStream({
      start(controller) {
        controllers[index] = controller;
        if (controllers[0] && controllers[1]) {
          pump();
        }
      },
      cancel(reason = undefined) {
        canceled[index] = true;
        reasons[index] = reason;
        return maybeCancelSource();
      },
    });
    return [makeBranch(0), makeBranch(1)];
  }
  pipeThrough(transform) {
    if (!transform || !transform.readable) {
      return this;
    }
    const reader = this.getReader();
    const writer = transform.writable && typeof transform.writable.getWriter === 'function'
      ? transform.writable.getWriter()
      : null;
    if (!writer) {
      return transform.readable;
    }
    const pump = () => reader.read().then(({ value, done }) => {
      if (done) {
        if (typeof writer.close === 'function') {
          return writer.close();
        }
        return null;
      }
      return Promise.resolve(writer.write(value)).then(pump);
    });
    pump();
    return transform.readable;
  }
  pipeTo(destination) {
    const writer = destination && typeof destination.getWriter === 'function'
      ? destination.getWriter()
      : null;
    if (!writer) {
      return Promise.resolve();
    }
    const reader = this.getReader();
    const pump = () => reader.read().then(({ value, done }) => {
      if (done) {
        if (typeof writer.close === 'function') {
          return writer.close();
        }
        return null;
      }
      return Promise.resolve(writer.write(value)).then(pump);
    });
    return pump();
  }
  values() {
    const reader = this.getReader();
    return {
      next() {
        return reader.read();
      },
      return() {
        reader.releaseLock();
        return Promise.resolve({ done: true });
      },
      [Symbol.asyncIterator]() {
        return this;
      },
    };
  }
  [Symbol.asyncIterator]() {
    return this.values();
  }
}

class WritableStream {
  constructor(sink = {}) {
    this._sink = sink || {};
  }
  getWriter() {
    const sink = this._sink;
    return {
      write(chunk) {
        if (typeof sink.write === 'function') {
          return Promise.resolve(sink.write(chunk));
        }
        return Promise.resolve();
      },
      close() {
        if (typeof sink.close === 'function') {
          return Promise.resolve(sink.close());
        }
        return Promise.resolve();
      },
      abort(reason) {
        if (typeof sink.abort === 'function') {
          return Promise.resolve(sink.abort(reason));
        }
        return Promise.resolve();
      },
    };
  }
}

class TransformStream {
  constructor(transformer = {}) {
    this.readable = new ReadableStream();
    this.readable._chunks = [];
    this.readable._closed = false;
    this.writable = new WritableStream({
      write: (chunk) => {
        if (typeof transformer.transform === 'function') {
          const controller = {
            enqueue: (value) => {
              this.readable.__twebEnqueue(value);
            },
          };
          transformer.transform(chunk, controller);
          return;
        }
        this.readable.__twebEnqueue(chunk);
      },
      close: () => {
        if (typeof transformer.flush === 'function') {
          const controller = {
            enqueue: (value) => {
              this.readable.__twebEnqueue(value);
            },
          };
          transformer.flush(controller);
        }
        this.readable.__twebClose();
      },
      abort: (reason) => {
        if (typeof transformer.abort === 'function') {
          transformer.abort(reason);
        }
        this.readable.__twebError(reason);
      },
    });
  }
}

class Request {
  constructor(resource, options = {}) {
    this.url = typeof resource === 'string' ? resource : resource.url;
    this.method = options.method || resource.method || 'GET';
    this.headers = new Headers(options.headers || resource.headers || {});
    this.body = options.body || resource.body || '';
    this.credentials = options.credentials || resource.credentials || 'same-origin';
    this.cache = options.cache || resource.cache || 'default';
    this.mode = options.mode || resource.mode || 'cors';
    this.redirect = options.redirect || resource.redirect || 'follow';
    this.referrer = options.referrer || resource.referrer || 'about:client';
    this.referrerPolicy = options.referrerPolicy || resource.referrerPolicy || '';
    this.signal = options.signal || resource.signal || null;
  }
  clone() {
    return new Request(this, {
      method: this.method,
      headers: this.headers,
      body: this.body,
      credentials: this.credentials,
      cache: this.cache,
      mode: this.mode,
      redirect: this.redirect,
      referrer: this.referrer,
      referrerPolicy: this.referrerPolicy,
      signal: this.signal,
    });
  }
}

function __twebWrapResponse(raw) {
  const body = raw.base64Body
    ? __twebDecodeBase64ToUint8Array(raw.base64Body)
    : raw.text;
  return new Response(body, raw);
}

function __twebToUint8Array(value) {
  if (value instanceof Uint8Array) {
    return value;
  }
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer.slice(0));
  }
  if (value instanceof ArrayBuffer) {
    return new Uint8Array(value.slice(0));
  }
  return new TextEncoder().encode(String(value));
}

function __twebDecodeBase64ToUint8Array(value = '') {
  const binary = atob(String(value || ''));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index) & 255;
  }
  return bytes;
}

function __twebSerializeBody(body, headers = null) {
  if (body === undefined || body === null) {
    return '';
  }
  if (body instanceof URLSearchParams) {
    if (headers && !headers.has('content-type')) {
      headers.set('content-type', 'application/x-www-form-urlencoded;charset=UTF-8');
    }
    return body.toString();
  }
  if (body instanceof FormData) {
    const params = new URLSearchParams();
    body.forEach((value, key) => {
      params.append(key, value);
    });
    if (headers && !headers.has('content-type')) {
      headers.set('content-type', 'application/x-www-form-urlencoded;charset=UTF-8');
    }
    return params.toString();
  }
  if (body instanceof Blob) {
    if (headers && body.type && !headers.has('content-type')) {
      headers.set('content-type', body.type);
    }
    return new TextDecoder().decode(body._bytes);
  }
  if (ArrayBuffer.isView(body) || body instanceof ArrayBuffer) {
    return new TextDecoder().decode(__twebToUint8Array(body));
  }
  return String(body);
}

class Response {
  constructor(body = '', init = {}) {
    this.ok = init.ok !== undefined ? !!init.ok : true;
    this.status = init.status || 200;
    this.statusText = init.statusText || '';
    this.url = init.url || '';
    this.redirected = Boolean(init.redirected);
    this.type = init.type || 'default';
    this.headers = new Headers(init.headers || {});
    this._bodyBytes = __twebToUint8Array(body);
    this._body = new TextDecoder().decode(this._bodyBytes);
    this.bodyUsed = false;
    this.body = new ReadableStream([this._bodyBytes]);
  }
  text() {
    this.bodyUsed = true;
    return Promise.resolve(this._body);
  }
  json() {
    this.bodyUsed = true;
    return Promise.resolve(JSON.parse(this._body));
  }
  arrayBuffer() {
    this.bodyUsed = true;
    return Promise.resolve(this._bodyBytes.buffer.slice(0));
  }
  formData() {
    this.bodyUsed = true;
    const data = new FormData();
    new URLSearchParams(this._body).forEach((value, key) => {
      data.append(key, value);
    });
    return Promise.resolve(data);
  }
  blob() {
    this.bodyUsed = true;
    return Promise.resolve(
      new Blob([this._bodyBytes], {
        type: this.headers.get('content-type') || '',
      })
    );
  }
  clone() {
    return new Response(this._bodyBytes.slice(0), {
      ok: this.ok,
      status: this.status,
      statusText: this.statusText,
      url: this.url,
      redirected: this.redirected,
      type: this.type,
      headers: Object.fromEntries(this.headers.entries()),
    });
  }
}

function fetch(resource, options = {}) {
  const request = resource instanceof Request ? resource : new Request(resource, options);
  const body = __twebSerializeBody(request.body, request.headers);
  const normalizedHeaders = __twebNormalizeHeaders(request.headers);
  if (!normalizedHeaders.cookie) {
    const cookieValue = __twebGetCookieString();
    if (cookieValue) {
      normalizedHeaders.cookie = cookieValue;
    }
  }
  const headers = JSON.stringify(normalizedHeaders);
  return new Promise((resolve, reject) => {
    __twebEnqueueTimer(() => {
      try {
        const response = JSON.parse(
          __twebHttpRequest(String(request.method), String(request.url), String(body), headers)
        );
        resolve(__twebWrapResponse(response));
      } catch (error) {
        reject(error);
      }
    });
  });
}

function __twebCreateNodeList(nodes) {
  return NodeList.from(nodes || []);
}

function __twebCreateHTMLCollection(nodes) {
  return HTMLCollection.from(nodes || []);
}

function __twebFormControlsForNode(node) {
  if (!node || typeof node.querySelectorAll !== 'function') {
    return __twebCreateHTMLCollection([]);
  }
  return __twebCreateHTMLCollection(Array.from(node.querySelectorAll('input, select, textarea, button')));
}

function __twebOptionElementsForNode(node) {
  if (!node || typeof node.querySelectorAll !== 'function') {
    return [];
  }
  return Array.from(node.querySelectorAll('option'));
}

function __twebOptionValue(option) {
  if (!option) {
    return '';
  }
  const explicit = option.getAttribute && option.getAttribute('value');
  if (explicit !== null && explicit !== undefined) {
    return String(explicit);
  }
  return String(option.textContent || '');
}

function __twebOptionText(option) {
  if (!option) {
    return '';
  }
  return String(option.textContent || '');
}

function __twebSelectAllowsMultiple(select) {
  return !!(select && select.getAttribute && select.getAttribute('multiple') !== null);
}

function __twebSelectOptionIndex(option) {
  if (!option || !option.parentElement) {
    return -1;
  }
  const select = option.closest && option.closest('select');
  if (!select) {
    return -1;
  }
  return __twebOptionElementsForNode(select).findIndex((entry) => entry === option);
}

function __twebGetSelectedIndex(select) {
  const options = __twebOptionElementsForNode(select);
  const selectedIndex = options.findIndex((option) => option.getAttribute('selected') !== null);
  if (selectedIndex >= 0) {
    return selectedIndex;
  }
  if (!options.length || __twebSelectAllowsMultiple(select)) {
    return -1;
  }
  return 0;
}

function __twebGetSelectedOptions(select) {
  const options = __twebOptionElementsForNode(select);
  const selected = options.filter((option) => option.getAttribute('selected') !== null);
  if (selected.length) {
    return selected;
  }
  if (!options.length || __twebSelectAllowsMultiple(select)) {
    return [];
  }
  return [options[0]];
}

function __twebSetSelectedIndex(select, index) {
  const options = __twebOptionElementsForNode(select);
  const normalizedIndex = Number(index);
  if (!Number.isFinite(normalizedIndex)) {
    return;
  }
  options.forEach((option, optionIndex) => {
    option.selected = optionIndex === normalizedIndex;
  });
}

function __twebSetSelectValue(select, value) {
  const target = String(value);
  const options = __twebOptionElementsForNode(select);
  let matched = false;
  options.forEach((option) => {
    const nextSelected = !matched && __twebOptionValue(option) === target;
    option.selected = nextSelected;
    if (nextSelected) {
      matched = true;
    }
  });
  if (!matched && !__twebSelectAllowsMultiple(select)) {
    options.forEach((option) => {
      option.selected = false;
    });
  }
}

function __twebClassNameSelector(classNames) {
  const names = String(classNames || '').trim().split(/\s+/).filter(Boolean);
  if (!names.length) {
    return '';
  }
  return names.map((name) => `.${name}`).join('');
}

function __twebGetElementsByClassNameImpl(classNames) {
  if (!this) {
    return __twebCreateHTMLCollection([]);
  }
  const names = String(classNames || '');
  let ids = [];
  if (this === document) {
    ids = JSON.parse(__twebGetElementsByClassName(names));
  } else if (this.__twebNodeId) {
    ids = JSON.parse(__twebNodeGetElementsByClassName(this.__twebNodeId, names));
  }
  return __twebCreateHTMLCollection(ids.map((nodeId) => __twebWrapNode(nodeId)));
}

__twebGetElementsByClassNameImpl.toString = () => 'function getElementsByClassName() { [native code] }';

function __twebGetElementsByNameImpl(name) {
  const ids = JSON.parse(__twebGetElementsByName(String(name || '')));
  return __twebCreateNodeList(ids.map((nodeId) => __twebWrapNode(nodeId)));
}

__twebGetElementsByNameImpl.toString = () => 'function getElementsByName() { [native code] }';

window.fetch = fetch;
self.fetch = fetch;
window.Headers = Headers;
window.URLSearchParams = URLSearchParams;
window.FormData = FormData;
window.Request = Request;
window.Response = Response;
window.Blob = Blob;
window.File = File;
window.NodeList = NodeList;
window.HTMLCollection = HTMLCollection;
window.ReadableStream = ReadableStream;
window.WritableStream = WritableStream;
window.TransformStream = TransformStream;
self.Headers = Headers;
self.URLSearchParams = URLSearchParams;
self.FormData = FormData;
self.Request = Request;
self.Response = Response;
self.Blob = Blob;
self.File = File;
self.NodeList = NodeList;
self.HTMLCollection = HTMLCollection;
self.ReadableStream = ReadableStream;
self.WritableStream = WritableStream;
self.TransformStream = TransformStream;

class XMLHttpRequest {
  constructor() {
    this.readyState = 0;
    this.status = 0;
    this.statusText = '';
    this.responseURL = '';
    this.responseText = '';
    this.response = null;
    this.responseType = '';
    this.onreadystatechange = null;
    this.onload = null;
    this.onloadend = null;
    this.onerror = null;
    this.onabort = null;
    this.withCredentials = false;
    this.timeout = 0;
    this.upload = new EventTarget();
    this._method = 'GET';
    this._url = '';
    this._headers = {};
    this._responseHeaders = {};
    this._overrideMimeType = '';
  }

  open(method, url) {
    this._method = String(method);
    this._url = String(url);
    this.readyState = 1;
    if (this.onreadystatechange) {
      this.onreadystatechange();
    }
  }

  setRequestHeader(name, value) {
    this._headers[String(name)] = String(value);
  }

  overrideMimeType(value) {
    this._overrideMimeType = String(value || '');
  }

  getResponseHeader(name) {
    const target = String(name).toLowerCase();
    const match = Object.entries(this._responseHeaders).find(([key]) => String(key).toLowerCase() === target);
    return match ? String(match[1]) : null;
  }

  getAllResponseHeaders() {
    return Object.entries(this._responseHeaders)
      .map(([key, value]) => `${key}: ${value}`)
      .join('\r\n');
  }

  abort() {
    this.readyState = 0;
    this.status = 0;
    this.statusText = '';
    this.responseText = '';
    this.response = null;
    if (this.onabort) {
      this.onabort(new Event('abort'));
    }
    __twebDispatchEventOnTarget(this, new Event('abort'));
    if (this.onloadend) {
      this.onloadend(new Event('loadend'));
    }
    __twebDispatchEventOnTarget(this, new Event('loadend'));
  }

  send(body = '') {
    __twebEnqueueTimer(() => {
      try {
        const headers = new Headers(this._headers);
        const serializedBody = __twebSerializeBody(body, headers);
        const normalizedHeaders = __twebNormalizeHeaders(headers);
        if (!normalizedHeaders.cookie) {
          const cookieValue = __twebGetCookieString();
          if (cookieValue) {
            normalizedHeaders.cookie = cookieValue;
          }
        }
        const raw = JSON.parse(
          __twebHttpRequest(
            this._method,
            this._url,
            String(serializedBody),
            JSON.stringify(normalizedHeaders),
            this._overrideMimeType,
          )
        );
        const responseBytes = raw.base64Body
          ? __twebDecodeBase64ToUint8Array(raw.base64Body)
          : new TextEncoder().encode(raw.text);
        const overrideCharset = __twebExtractCharset(this._overrideMimeType);
        let responseText = raw.text;
        if (
          responseBytes.length
          && (
            overrideCharset === 'utf-8'
            || overrideCharset === 'utf8'
          )
        ) {
          responseText = new TextDecoder().decode(responseBytes);
        }
        this.status = raw.status;
        this.statusText = raw.statusText || '';
        this.responseURL = raw.url || '';
        this._responseHeaders = raw.headers || {};
        this.responseText = responseText;
        this.response = this.responseText;
        if (this.responseType === 'json') {
          try {
            this.response = this.responseText ? JSON.parse(this.responseText) : null;
          } catch (_error) {
            this.response = null;
          }
        } else if (this.responseType === 'arraybuffer') {
          this.response = responseBytes.buffer.slice(0);
        } else if (this.responseType === 'blob') {
          this.response = new Blob([responseBytes], {
            type: this.getResponseHeader('content-type') || '',
          });
        } else if (this.responseType === 'document') {
          const parser = new DOMParser();
          this.response = parser.parseFromString(this.responseText, 'text/html');
        }
        this.readyState = 4;
        __twebDispatchEventOnTarget(this, new Event('readystatechange'));
        if (this.onreadystatechange) {
          this.onreadystatechange(new Event('readystatechange'));
        }
        __twebDispatchEventOnTarget(this, new Event('load'));
        if (this.onload) {
          this.onload(new Event('load'));
        }
        __twebDispatchEventOnTarget(this, new Event('loadend'));
        if (this.onloadend) {
          this.onloadend(new Event('loadend'));
        }
      } catch (error) {
        __twebDispatchEventOnTarget(this, new Event('error'));
        if (this.onerror) {
          this.onerror(error);
        } else {
          throw error;
        }
        __twebDispatchEventOnTarget(this, new Event('loadend'));
        if (this.onloadend) {
          this.onloadend(new Event('loadend'));
        }
      }
    });
  }

  get responseXML() {
    if (this.responseType === 'document' && this.response && typeof this.response === 'object') {
      return this.response;
    }
    return null;
  }
}

Object.setPrototypeOf(XMLHttpRequest.prototype, EventTarget.prototype);

window.XMLHttpRequest = XMLHttpRequest;
self.XMLHttpRequest = XMLHttpRequest;

function __twebCreateBuiltinHidingProxy(target, builtinKeys) {
  return new Proxy(target, {
    get(target, prop, receiver) {
      return Reflect.get(target, prop, receiver);
    },
    set(target, prop, value, receiver) {
      return Reflect.set(target, prop, value, receiver);
    },
    ownKeys(target) {
      return Reflect.ownKeys(target).filter((key) => {
        return typeof key !== 'string' || !builtinKeys.has(key);
      });
    },
    getOwnPropertyDescriptor(target, prop) {
      const descriptor = Reflect.getOwnPropertyDescriptor(target, prop);
      if (!descriptor) {
        return undefined;
      }
      if (typeof prop === 'string' && builtinKeys.has(prop)) {
        return {
          ...descriptor,
          enumerable: false,
        };
      }
      return descriptor;
    },
  });
}

const __twebParserInsertedPriorSources = [];

function __twebLoadParserInsertedScripts(scripts) {
  scripts.forEach((script) => {
    script.__twebParserLoadedResourceUrl = script.src;
    try {
      const source = __twebLoadExternalScriptSource(script.src);
      if (source) {
        if (!__twebParserInsertedScriptPreflightSafe(source, JSON.stringify(__twebParserInsertedPriorSources))) {
          __twebRecordParserInsertedScriptError(script.src, 'script skipped after crash preflight');
          return;
        }
        (0, eval)(`${source}\n//# sourceURL=${script.src}`);
        __twebParserInsertedPriorSources.push(source);
      }
      if (script.onload || __twebGetListenerBucket(script, 'load')) {
        script.dispatchEvent(new Event('load'));
      }
    } catch (error) {
      __twebRecordParserInsertedScriptError(
        script.src,
        error && error.stack ? `${String(error)}\n${String(error.stack)}` : String(error),
      );
      if (script.onerror || __twebGetListenerBucket(script, 'error')) {
        script.dispatchEvent(new Event('error'));
      }
    }
  });
}

const __twebDocumentTarget = {
  get nodeType() {
    return Node.DOCUMENT_NODE;
  },
  get nodeName() {
    return '#document';
  },
  get parentNode() {
    return null;
  },
  get ownerDocument() {
    return null;
  },
  getRootNode() {
    return this;
  },
  get title() {
    return __twebGetDocumentTitle();
  },
  set title(value) {
    __twebSetDocumentTitle(String(value));
  },
  get body() {
    const nodeId = __twebGetDocumentNode('body');
    return nodeId ? __twebWrapNode(nodeId) : null;
  },
  get head() {
    const nodeId = __twebGetDocumentNode('head');
    return nodeId ? __twebWrapNode(nodeId) : null;
  },
  get documentElement() {
    const nodeId = __twebGetDocumentNode('html');
    return nodeId ? __twebWrapNode(nodeId) : null;
  },
  get doctype() {
    const nodeId = __twebGetDocumentDoctype();
    return nodeId ? __twebWrapNode(nodeId) : null;
  },
  get childNodes() {
    const nodes = [];
    if (this.doctype) {
      nodes.push(this.doctype);
    }
    if (this.documentElement) {
      nodes.push(this.documentElement);
    }
    return __twebCreateNodeList(nodes);
  },
  get children() {
    const root = this.documentElement;
    return __twebCreateHTMLCollection(root ? [root] : []);
  },
  get firstChild() {
    return this.childNodes[0] || null;
  },
  get lastChild() {
    const children = this.childNodes;
    return children.length ? children[children.length - 1] : null;
  },
  get firstElementChild() {
    return this.documentElement;
  },
  get lastElementChild() {
    return this.documentElement;
  },
  get readyState() {
    return __twebDocumentReadyState;
  },
  get compatMode() {
    return 'CSS1Compat';
  },
  get visibilityState() {
    return 'visible';
  },
  get hidden() {
    return false;
  },
  get scrollingElement() {
    const stored = this.__twebScrollingElement || null;
    if (stored && stored.isConnected) {
      return stored;
    }
    return this.documentElement || this.body || null;
  },
  set scrollingElement(value) {
    this.__twebScrollingElement = value || null;
  },
  get activeElement() {
    return __twebActiveElement || this.body || this.documentElement || null;
  },
  get adoptedStyleSheets() {
    return this.__twebAdoptedStyleSheets || [];
  },
  set adoptedStyleSheets(value) {
    this.__twebAdoptedStyleSheets = Array.isArray(value) ? value : [];
  },
  hasFocus() {
    return true;
  },
  get cookie() {
    return __twebGetCookieString();
  },
  set cookie(value) {
    __twebSetCookie(value);
    __twebPersistCookie(String(value));
  },
  get referrer() {
    return '';
  },
  get URL() {
    return location.href;
  },
  get implementation() {
    return {
      hasFeature() {
        return true;
      },
      createHTMLDocument(title = '') {
        const html = document.createElement('html');
        const head = document.createElement('head');
        const body = document.createElement('body');
        html.appendChild(head);
        html.appendChild(body);
        const next = Object.create(Document.prototype);
        next.__twebDetachedHtml = html;
        next.defaultView = window;
        next.location = location;
        next.scrollingElement = body;
        Object.defineProperties(next, {
          nodeType: { get() { return Node.DOCUMENT_NODE; } },
          nodeName: { get() { return '#document'; } },
          parentNode: { get() { return null; } },
          ownerDocument: { get() { return null; } },
          documentElement: { get() { return this.__twebDetachedHtml; } },
          head: { get() { return this.__twebDetachedHtml.firstElementChild; } },
          body: { get() { return this.__twebDetachedHtml.lastElementChild; } },
          childNodes: { get() { return [this.__twebDetachedHtml]; } },
          children: { get() { return this.childNodes; } },
          firstChild: { get() { return this.__twebDetachedHtml; } },
          lastChild: { get() { return this.__twebDetachedHtml; } },
          title: {
            get() {
              const titleNode = this.head ? this.head.querySelector('title') : null;
              return titleNode ? titleNode.textContent : '';
            },
            set(value) {
              let titleNode = this.head ? this.head.querySelector('title') : null;
              if (!titleNode && this.head) {
                titleNode = document.createElement('title');
                this.head.appendChild(titleNode);
              }
              if (titleNode) {
                titleNode.textContent = String(value);
              }
            },
          },
        });
        if (title) {
          next.title = String(title);
        }
        next.getRootNode = function() { return this; };
        next.createElement = document.createElement.bind(document);
        next.createElementNS = document.createElementNS.bind(document);
        next.createTextNode = document.createTextNode.bind(document);
        next.createComment = document.createComment.bind(document);
        next.createDocumentFragment = document.createDocumentFragment.bind(document);
        next.querySelector = function(selector) { return this.documentElement.querySelector(selector); };
        next.querySelectorAll = function(selector) { return this.documentElement.querySelectorAll(selector); };
        next.getElementById = function(id) { return this.querySelector(`#${String(id)}`); };
        next.getElementsByTagName = function(tagName) {
          return __twebCreateHTMLCollection(Array.from(this.querySelectorAll(String(tagName))));
        };
        next.open = function() {
          this.head.replaceChildren();
          this.body.replaceChildren();
          return this;
        };
        next.write = function(...parts) {
          const fragment = document.createRange().createContextualFragment(
            parts.map((part) => String(part)).join('')
          );
          while (fragment.firstChild) {
            this.body.appendChild(fragment.firstChild);
          }
        };
        next.writeln = function(...parts) {
          this.write(...parts, '\n');
        };
        next.close = function() {};
        return next;
      },
    };
  },
  get currentScript() {
    const raw = JSON.parse(__twebGetCurrentScriptInfo());
    if (!raw) {
      return null;
    }
    const directMatch = raw.src ? document.querySelector(`script[src="${String(raw.src).replace(/"/g, '\\"')}"]`) : null;
    if (directMatch) {
      return directMatch;
    }
    const resolved = raw.src ? new URL(raw.src, location.href).href : '';
    const scripts = document.querySelectorAll('script[src]');
    for (const script of scripts) {
      if (new URL(script.src || '', location.href).href === resolved) {
        return script;
      }
    }
    return null;
  },
  write(...parts) {
    const html = parts.map((part) => String(part)).join('');
    if (!html) {
      return;
    }
    const fragment = document.createRange().createContextualFragment(html);
    const parserInsertedScripts = Array.from(fragment.querySelectorAll('script[src]'));
    const current = this.currentScript;
    if (current && current.parentNode) {
      const parent = current.parentNode;
      const anchor = current.nextSibling;
      while (fragment.firstChild) {
        parent.insertBefore(fragment.firstChild, anchor);
      }
      __twebLoadParserInsertedScripts(parserInsertedScripts);
      return;
    }
    const target = this.body || this.documentElement;
    if (!target) {
      return;
    }
    while (fragment.firstChild) {
      target.appendChild(fragment.firstChild);
    }
    __twebLoadParserInsertedScripts(parserInsertedScripts);
  },
  writeln(...parts) {
    this.write(...parts, "\n");
  },
  createElement(tagName) {
    return __twebWrapNode(__twebCreateElement(String(tagName)));
  },
  createElementNS(namespaceURI, tagName) {
    const node = __twebWrapNode(__twebCreateElement(String(tagName)));
    node.namespaceURI = namespaceURI == null ? null : String(namespaceURI);
    return node;
  },
  createTextNode(text) {
    return __twebWrapNode(__twebCreateTextNode(String(text)));
  },
  createAttribute(name) {
    return __twebCreateAttrNode(null, String(name), '');
  },
  createComment(text) {
    return __twebWrapNode(__twebCreateComment(String(text)));
  },
  createDocumentFragment() {
    return __twebWrapNode(__twebCreateDocumentFragment());
  },
  importNode(node, deep = false) {
    if (!node || typeof node.cloneNode !== 'function') {
      return null;
    }
    return node.cloneNode(!!deep);
  },
  createRange() {
    let startContainer = this.body || this.documentElement || this;
    let endContainer = startContainer;
    let startOffset = 0;
    let endOffset = 0;
    return {
      setStart(node, offset) {
        startContainer = node;
        startOffset = Number(offset) || 0;
      },
      setEnd(node, offset) {
        endContainer = node;
        endOffset = Number(offset) || 0;
      },
      selectNode(node) {
        startContainer = node;
        endContainer = node;
        startOffset = 0;
        endOffset = 1;
      },
      selectNodeContents(node) {
        startContainer = node;
        endContainer = node;
        startOffset = 0;
        endOffset = node && node.childNodes ? node.childNodes.length : 0;
      },
      collapse(toStart = false) {
        if (toStart) {
          endContainer = startContainer;
          endOffset = startOffset;
        } else {
          startContainer = endContainer;
          startOffset = endOffset;
        }
      },
      cloneRange() {
        const range = document.createRange();
        range.setStart(startContainer, startOffset);
        range.setEnd(endContainer, endOffset);
        return range;
      },
      deleteContents() {},
      extractContents() {
        return document.createDocumentFragment();
      },
      insertNode(node) {
        if (startContainer && startContainer.appendChild && node) {
          startContainer.appendChild(node);
        }
      },
      createContextualFragment(html) {
        const fragment = document.createDocumentFragment();
        const container = document.createElement('div');
        container.innerHTML = String(html);
        while (container.firstChild) {
          fragment.appendChild(container.firstChild);
        }
        return fragment;
      },
      get commonAncestorContainer() {
        return startContainer && startContainer.nodeType === Node.TEXT_NODE
          ? startContainer.parentNode
          : startContainer;
      },
      get startContainer() {
        return startContainer;
      },
      get endContainer() {
        return endContainer;
      },
      get startOffset() {
        return startOffset;
      },
      get endOffset() {
        return endOffset;
      },
      get collapsed() {
        return startContainer === endContainer && startOffset === endOffset;
      },
    };
  },
  createTreeWalker(root, whatToShow = NodeFilter.SHOW_ALL, filter = null) {
    const nodes = [];
    const visit = (node) => {
      if (!node) {
        return;
      }
      const isElement = node.nodeType === Node.ELEMENT_NODE;
      const visible = whatToShow === NodeFilter.SHOW_ALL || ((whatToShow & NodeFilter.SHOW_ELEMENT) && isElement);
      let verdict = NodeFilter.FILTER_ACCEPT;
      if (visible && filter) {
        if (typeof filter === 'function') {
          verdict = filter(node);
        } else if (typeof filter.acceptNode === 'function') {
          verdict = filter.acceptNode(node);
        }
      }
      if (visible && verdict === NodeFilter.FILTER_ACCEPT) {
        nodes.push(node);
      }
      if (verdict === NodeFilter.FILTER_REJECT) {
        return;
      }
      if (node.childNodes) {
        node.childNodes.forEach((child) => visit(child));
      }
    };
    visit(root);
    let index = -1;
    return {
      root,
      whatToShow,
      filter,
      currentNode: root,
      nextNode() {
        index += 1;
        this.currentNode = nodes[index] || null;
        return this.currentNode;
      },
      previousNode() {
        index = Math.max(-1, index - 1);
        this.currentNode = index >= 0 ? nodes[index] : root;
        return index >= 0 ? this.currentNode : null;
      },
    };
  },
  createNodeIterator(root, whatToShow = NodeFilter.SHOW_ALL, filter = null) {
    const walker = this.createTreeWalker(root, whatToShow, filter);
    return {
      root,
      referenceNode: root,
      pointerBeforeReferenceNode: true,
      nextNode() {
        const node = walker.nextNode();
        if (node) {
          this.referenceNode = node;
          this.pointerBeforeReferenceNode = false;
        }
        return node;
      },
      previousNode() {
        const node = walker.previousNode();
        if (node) {
          this.referenceNode = node;
          this.pointerBeforeReferenceNode = false;
        }
        return node;
      },
      detach() {},
    };
  },
  createEvent(kind) {
    return __twebCreateSyntheticEvent(kind);
  },
  querySelector(selector) {
    const nodeId = __twebQueryOne(selector);
    if (!nodeId) {
      return null;
    }
    return __twebWrapNode(nodeId);
  },
  querySelectorAll(selector) {
    const ids = JSON.parse(__twebQueryAll(selector));
    return __twebCreateNodeList(ids.map((nodeId) => __twebWrapNode(nodeId)));
  },
  getElementById(id) {
    const nodeId = __twebGetElementById(String(id));
    if (!nodeId) {
      return null;
    }
    return __twebWrapNode(nodeId);
  },
  getElementsByTagName(tagName) {
    const ids = JSON.parse(__twebGetElementsByTagName(String(tagName)));
    return __twebCreateHTMLCollection(ids.map((nodeId) => __twebWrapNode(nodeId)));
  },
  getElementsByName(name) {
    const ids = JSON.parse(__twebGetElementsByName(String(name)));
    return __twebCreateNodeList(ids.map((nodeId) => __twebWrapNode(nodeId)));
  },
  addEventListener(type, callback) {
    __twebAddEventListener(document, type, callback);
  },
  removeEventListener(type, callback) {
    __twebRemoveEventListener(document, type, callback);
  },
  dispatchEvent(event) {
    return __twebDispatchEventOnTarget(document, event);
  },
  getSelection() {
    return {
      removeAllRanges() {},
      addRange(_range) {},
      toString() {
        return '';
      },
    };
  },
  appendChild(child) {
    const childNodeId = __twebDocumentAppendChild(child.__twebNodeId);
    return __twebWrapNode(childNodeId);
  },
  insertBefore(child, referenceNode) {
    if (!referenceNode) {
      return this.appendChild(child);
    }
    const childNodeId = __twebDocumentInsertBefore(child.__twebNodeId, referenceNode.__twebNodeId);
    return __twebWrapNode(childNodeId);
  },
  removeChild(child) {
    __twebDocumentRemoveChild(child.__twebNodeId);
    return child;
  },
  replaceChild(child, referenceNode) {
    const inserted = this.insertBefore(child, referenceNode);
    this.removeChild(referenceNode);
    return inserted;
  },
  hasChildNodes() {
    return this.childNodes.length > 0;
  },
  cloneNode(deep = false) {
    return __twebWrapNode(__twebDocumentCloneNode(!!deep));
  },
  contains(candidate) {
    if (!candidate || !candidate.__twebNodeId) {
      return false;
    }
    return __twebDocumentContains(candidate.__twebNodeId);
  }
};
const __twebDocumentBuiltinKeys = new Set(Reflect.ownKeys(__twebDocumentTarget));
const document = __twebCreateBuiltinHidingProxy(__twebDocumentTarget, __twebDocumentBuiltinKeys);
window.document = document;
self.document = document;
document.defaultView = window;
document.location = location;
Object.defineProperty(document, 'forms', {
  configurable: true,
  enumerable: true,
  get() {
    return __twebCreateHTMLCollection(Array.from(document.querySelectorAll('form')));
  },
});
document.getElementsByClassName = __twebGetElementsByClassNameImpl;
document.getElementsByName = __twebGetElementsByNameImpl;
__twebDocumentBuiltinKeys.add('forms');
__twebDocumentBuiltinKeys.add('getElementsByClassName');
__twebDocumentBuiltinKeys.add('getElementsByName');
Object.setPrototypeOf(document, Document.prototype);
Object.defineProperty(Document.prototype, 'forms', {
  configurable: true,
  enumerable: true,
  get() {
    return __twebCreateHTMLCollection(Array.from(this.querySelectorAll('form')));
  },
});
Document.prototype.getElementsByClassName = __twebGetElementsByClassNameImpl;
Document.prototype.getElementsByName = __twebGetElementsByNameImpl;
Node.prototype.appendChild = function(child) {
  return __twebCallOwnMethod(this, 'appendChild', [child]);
};
Node.prototype.removeChild = function(child) {
  return __twebCallOwnMethod(this, 'removeChild', [child]);
};
Node.prototype.insertBefore = function(child, referenceNode) {
  return __twebCallOwnMethod(this, 'insertBefore', [child, referenceNode]);
};
Node.prototype.hasChildNodes = function() {
  return __twebCallOwnMethod(this, 'hasChildNodes');
};
Node.prototype.cloneNode = function(deep = false) {
  return __twebCallOwnMethod(this, 'cloneNode', [deep]);
};
Node.prototype.contains = function(candidate) {
  const descriptor = Object.getOwnPropertyDescriptor(this, 'contains');
  if (descriptor && typeof descriptor.value === 'function') {
    return descriptor.value.call(this, candidate);
  }
  if (!candidate) {
    return false;
  }
  if (this === candidate) {
    return true;
  }
  const pending = this && this.childNodes ? Array.from(this.childNodes) : [];
  while (pending.length) {
    const current = pending.pop();
    if (current === candidate) {
      return true;
    }
    if (current && current.childNodes) {
      pending.push(...Array.from(current.childNodes));
    }
  }
  return false;
};
Node.prototype.compareDocumentPosition = function(other) {
  return __twebCallOwnMethod(this, 'compareDocumentPosition', [other]);
};
Node.prototype.isEqualNode = function(other) {
  if (!other || this.nodeType !== other.nodeType || this.nodeName !== other.nodeName) {
    return false;
  }
  if (this.nodeType === Node.TEXT_NODE || this.nodeType === Node.COMMENT_NODE) {
    return this.textContent === other.textContent;
  }
  if (this.outerHTML && other.outerHTML) {
    return this.outerHTML === other.outerHTML;
  }
  return this.textContent === other.textContent;
};
Node.prototype.getRootNode = function() {
  return __twebCallOwnMethod(this, 'getRootNode');
};
function __twebMaybeLoadInsertedResource(targetNode) {
  if (!targetNode || targetNode.nodeType !== Node.ELEMENT_NODE) {
    return;
  }
  if (!targetNode.isConnected) {
    return;
  }
  if (targetNode.tagName === 'SCRIPT' && targetNode.src) {
    if (targetNode.__twebRequestedResourceUrl === targetNode.src) {
      return;
    }
    targetNode.__twebRequestedResourceUrl = targetNode.src;
    __twebEnqueueTimer(() => {
      try {
        if (targetNode.__twebParserLoadedResourceUrl === targetNode.src) {
          return;
        }
        __twebLoadExternalScript(targetNode.src);
        targetNode.dispatchEvent(new Event('load'));
      } catch (error) {
        if (targetNode.onerror || __twebGetListenerBucket(targetNode, 'error')) {
          targetNode.dispatchEvent(new Event('error'));
        } else {
          throw error;
        }
      }
    });
    return;
  }
  if (targetNode.tagName === 'LINK' && targetNode.href) {
    if (targetNode.__twebRequestedResourceUrl === targetNode.href) {
      return;
    }
    targetNode.__twebRequestedResourceUrl = targetNode.href;
    __twebEnqueueTimer(() => {
      __twebEnqueueTimer(() => {
        __twebDispatchEventOnTarget(targetNode, new Event('load'));
      });
    });
    return;
  }
  if (targetNode.tagName === 'IFRAME') {
    const requestedState = JSON.stringify({
      src: targetNode.getAttribute('src') || '',
      srcdoc: targetNode.getAttribute('srcdoc') || '',
    });
    if (targetNode.__twebRequestedResourceUrl === requestedState) {
      return;
    }
    targetNode.__twebRequestedResourceUrl = requestedState;
    __twebEnqueueTimer(() => {
      const frameWindow = __twebRefreshIframeWindow(targetNode);
      if (frameWindow && frameWindow.document) {
        __twebDispatchEventOnTarget(frameWindow.document, new Event('DOMContentLoaded'));
        __twebDispatchEventOnTarget(frameWindow.document, new Event('readystatechange'));
      }
      __twebDispatchEventOnTarget(targetNode, new Event('load'));
      if (frameWindow) {
        __twebDispatchEventOnTarget(frameWindow, new Event('load'));
      }
    });
  }
}

function __twebMaybeLoadInsertedSubtree(targetNode) {
  if (!targetNode) {
    return;
  }
  __twebMaybeLoadInsertedResource(targetNode);
  if (!targetNode.childNodes || !targetNode.childNodes.length) {
    return;
  }
  Array.from(targetNode.childNodes).forEach((child) => {
    __twebMaybeLoadInsertedSubtree(child);
  });
}
Element.prototype.getAttribute = function(name) {
  return __twebCallOwnMethod(this, 'getAttribute', [name]);
};
Element.prototype.hasAttribute = function(name) {
  return __twebCallOwnMethod(this, 'hasAttribute', [name]);
};
Element.prototype.setAttribute = function(name, value) {
  return __twebCallOwnMethod(this, 'setAttribute', [name, value]);
};
Element.prototype.removeAttribute = function(name) {
  return __twebCallOwnMethod(this, 'removeAttribute', [name]);
};
Element.prototype.querySelector = function(selector) {
  return __twebCallOwnMethod(this, 'querySelector', [selector]);
};
Element.prototype.querySelectorAll = function(selector) {
  return __twebCallOwnMethod(this, 'querySelectorAll', [selector]);
};
Element.prototype.getElementsByTagName = function(tagName) {
  return __twebCallOwnMethod(this, 'getElementsByTagName', [tagName]);
};
Element.prototype.matches = function(selector) {
  return __twebCallOwnMethod(this, 'matches', [selector]);
};
Element.prototype.getElementsByClassName = __twebGetElementsByClassNameImpl;
Element.prototype.getBoundingClientRect = function() {
  return __twebCallOwnMethod(this, 'getBoundingClientRect');
};
Element.prototype.checkVisibility = function() {
  return __twebCallOwnMethod(this, 'checkVisibility');
};
Document.prototype.createElement = function(tagName) {
  return __twebCallOwnMethod(this, 'createElement', [tagName]);
};
Document.prototype.createElementNS = function(namespaceURI, tagName) {
  return __twebCallOwnMethod(this, 'createElementNS', [namespaceURI, tagName]);
};
Document.prototype.createTextNode = function(text) {
  return __twebCallOwnMethod(this, 'createTextNode', [text]);
};
Document.prototype.createAttribute = function(name) {
  return __twebCallOwnMethod(this, 'createAttribute', [name]);
};
Document.prototype.createComment = function(text) {
  return __twebCallOwnMethod(this, 'createComment', [text]);
};
Document.prototype.createDocumentFragment = function() {
  return __twebCallOwnMethod(this, 'createDocumentFragment');
};
Document.prototype.importNode = function(node, deep = false) {
  return __twebCallOwnMethod(this, 'importNode', [node, deep]);
};
Document.prototype.createRange = function() {
  return __twebCallOwnMethod(this, 'createRange');
};
Document.prototype.createTreeWalker = function(root, whatToShow, filter) {
  return __twebCallOwnMethod(this, 'createTreeWalker', [root, whatToShow, filter]);
};
Document.prototype.createNodeIterator = function(root, whatToShow, filter) {
  return __twebCallOwnMethod(this, 'createNodeIterator', [root, whatToShow, filter]);
};
Document.prototype.createEvent = function(kind) {
  return __twebCallOwnMethod(this, 'createEvent', [kind]);
};
Document.prototype.querySelector = function(selector) {
  return __twebCallOwnMethod(this, 'querySelector', [selector]);
};
Document.prototype.querySelectorAll = function(selector) {
  return __twebCallOwnMethod(this, 'querySelectorAll', [selector]);
};
Document.prototype.getElementById = function(id) {
  return __twebCallOwnMethod(this, 'getElementById', [id]);
};
Document.prototype.getElementsByTagName = function(tagName) {
  return __twebCallOwnMethod(this, 'getElementsByTagName', [tagName]);
};
Document.prototype.getElementsByName = function(name) {
  return __twebCallOwnMethod(this, 'getElementsByName', [name]);
};
Object.defineProperty(HTMLFormElement.prototype, 'elements', {
  configurable: true,
  enumerable: true,
  get() {
    return __twebFormControlsForNode(this);
  },
});
window.addEventListener = function(type, callback) {
  __twebAddEventListener(window, type, callback);
};
window.removeEventListener = function(type, callback) {
  __twebRemoveEventListener(window, type, callback);
};
window.dispatchEvent = function(event) {
  return __twebDispatchEventOnTarget(window, event);
};
window.getSelection = function() {
  return document.getSelection();
};
self.addEventListener = window.addEventListener;
self.removeEventListener = window.removeEventListener;
self.dispatchEvent = window.dispatchEvent;
self.getSelection = window.getSelection;

const __twebNamedWindowProperties = new Set();
let __twebNamedWindowPropertiesDirty = true;

function __twebIsValidNamedWindowProperty(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(String(name || ''));
}

function __twebMarkNamedWindowPropertiesDirty(attributeName = null) {
  if (attributeName === null) {
    __twebNamedWindowPropertiesDirty = true;
    return;
  }
  const normalized = String(attributeName || '').toLowerCase();
  if (normalized === 'id' || normalized === 'name') {
    __twebNamedWindowPropertiesDirty = true;
  }
}

function __twebSyncNamedWindowProperties() {
  if (!__twebNamedWindowPropertiesDirty) {
    return false;
  }
  window.__twebLastNamedWindowPropertySyncError = null;
  try {
    const currentNames = new Set();
    const nodes = document.getElementsByTagName('*');
    Array.from(nodes).forEach((node, nodeIndex) => {
      let candidates;
      try {
        candidates = [String(node.id || ''), String(node.getAttribute('name') || '')];
      } catch (error) {
        window.__twebLastNamedWindowPropertySyncError =
          `candidate-read node=${nodeIndex} error=${String(error)}`;
        return;
      }
      candidates.forEach((name) => {
        try {
          if (!__twebIsValidNamedWindowProperty(name)) {
            return;
          }
          currentNames.add(name);
          if (name in window) {
            return;
          }
          Object.defineProperty(window, name, {
            configurable: true,
            enumerable: true,
            get() {
              const direct = document.getElementById(name);
              if (direct) {
                return direct;
              }
              const named = document.getElementsByName(name);
              return named && named.length ? named[0] : undefined;
            },
          });
          __twebNamedWindowProperties.add(name);
        } catch (error) {
          window.__twebLastNamedWindowPropertySyncError =
            `define name=${name} error=${String(error)}`;
        }
      });
    });
    Array.from(__twebNamedWindowProperties).forEach((name) => {
      try {
        if (currentNames.has(name)) {
          return;
        }
        delete window[name];
        __twebNamedWindowProperties.delete(name);
      } catch (error) {
        window.__twebLastNamedWindowPropertySyncError =
          `delete name=${name} error=${String(error)}`;
      }
    });
  } catch (error) {
    window.__twebLastNamedWindowPropertySyncError = `sync error=${String(error)}`;
  }
  __twebNamedWindowPropertiesDirty = false;
  return true;
}

function __twebInstallJQueryLegacyShims() {
  const jq = window.jQuery || window.$;
  if (!jq || !jq.fn || jq.fn.__twebLegacyShimsInstalled) {
    return;
  }
  const shorthandEvents = [
    'blur', 'focus', 'focusin', 'focusout', 'resize', 'scroll',
    'click', 'dblclick', 'mousedown', 'mouseup', 'mousemove',
    'mouseover', 'mouseout', 'mouseenter', 'mouseleave',
    'change', 'select', 'submit', 'keydown', 'keypress',
    'keyup', 'contextmenu',
  ];
  shorthandEvents.forEach((eventName) => {
    if (typeof jq.fn[eventName] === 'function') {
      return;
    }
    jq.fn[eventName] = function(handler) {
      if (handler === undefined) {
        return this.trigger(eventName);
      }
      return this.on(eventName, handler);
    };
  });
  if (typeof jq.fn.load === 'function') {
    const originalLoad = jq.fn.load;
    jq.fn.load = function(url, params, callback) {
      if (typeof url !== 'string') {
        if (url === undefined) {
          return this.trigger('load');
        }
        return this.on('load', url);
      }
      return originalLoad.call(this, url, params, callback);
    };
  }
  jq.fn.__twebLegacyShimsInstalled = true;
}

function __twebWrapNode(nodeId) {
  if (__twebNodeCache.has(nodeId)) {
    return __twebNodeCache.get(nodeId);
  }
  const tagName = __twebGetNodeTagName(nodeId);
  const elementPrototypeMap = {
    a: HTMLAnchorElement.prototype,
    audio: HTMLAudioElement.prototype,
    body: HTMLBodyElement.prototype,
    button: HTMLButtonElement.prototype,
    canvas: HTMLCanvasElement.prototype,
    form: HTMLFormElement.prototype,
    head: HTMLHeadElement.prototype,
    html: HTMLHtmlElement.prototype,
    iframe: HTMLIFrameElement.prototype,
    img: HTMLImageElement.prototype,
    input: HTMLInputElement.prototype,
    label: HTMLLabelElement.prototype,
    link: HTMLLinkElement.prototype,
    meta: HTMLMetaElement.prototype,
    option: HTMLOptionElement.prototype,
    script: HTMLScriptElement.prototype,
    select: HTMLSelectElement.prototype,
    style: HTMLStyleElement.prototype,
    template: HTMLTemplateElement.prototype,
    textarea: HTMLTextAreaElement.prototype,
    title: HTMLTitleElement.prototype,
    video: HTMLVideoElement.prototype,
    dialog: HTMLDialogElement.prototype,
  };
  let prototype = elementPrototypeMap[tagName] || HTMLElement.prototype;
  if (tagName === '#text') {
    prototype = Text.prototype;
  } else if (tagName === '#comment') {
    prototype = Comment.prototype;
  } else if (tagName === '#doctype') {
    prototype = DocumentType.prototype;
  } else if (tagName === 'fragment') {
    prototype = DocumentFragment.prototype;
  }
  const node = {
    get tagName() {
      if (tagName === '#text') {
        return '#text';
      }
      if (tagName === '#comment') {
        return '#comment';
      }
      if (tagName === '#doctype') {
        return 'html';
      }
      if (tagName === 'fragment') {
        return '#document-fragment';
      }
      return tagName.toUpperCase();
    },
    get nodeType() {
      if (tagName === '#text') {
        return Node.TEXT_NODE;
      }
      if (tagName === '#comment') {
        return Node.COMMENT_NODE;
      }
      if (tagName === '#doctype') {
        return Node.DOCUMENT_TYPE_NODE;
      }
      if (tagName === 'fragment') {
        return Node.DOCUMENT_FRAGMENT_NODE;
      }
      return Node.ELEMENT_NODE;
    },
    get nodeName() {
      if (tagName === '#doctype') {
        return 'html';
      }
      return this.tagName;
    },
    get localName() {
      if (tagName.startsWith('#')) {
        return this.nodeName;
      }
      return String(tagName).toLowerCase();
    },
    get ownerDocument() {
      return document;
    },
    get sheet() {
      return __twebEnsureStyleSheet(this);
    },
    get styleSheet() {
      const sheet = __twebEnsureStyleSheet(this);
      return sheet ? sheet.styleSheet : null;
    },
    get namespaceURI() {
      return __twebDefaultNamespaceURI(this, tagName);
    },
    set namespaceURI(value) {
      this.__twebNamespaceURI = value == null ? null : String(value);
    },
    get textContent() {
      return __twebGetTextContent(nodeId);
    },
    set textContent(value) {
      __twebSetTextContent(nodeId, String(value));
      if (this.nodeType === Node.TEXT_NODE || this.nodeType === Node.COMMENT_NODE) {
        __twebRecordCharacterDataMutation(this);
      } else {
        __twebRecordChildListMutation(this);
      }
    },
    get nodeValue() {
      return this.textContent;
    },
    set nodeValue(value) {
      this.textContent = value;
    },
    get data() {
      return this.textContent;
    },
    set data(value) {
      this.textContent = value;
    },
    get name() {
      if (tagName === '#doctype') {
        return 'html';
      }
      return __twebGetAttribute(nodeId, 'name') || '';
    },
    get content() {
      if (tagName !== 'template') {
        return undefined;
      }
      if (!this.__twebTemplateContent) {
        const fragment = document.createDocumentFragment();
        this.childNodes.forEach((child) => {
          fragment.appendChild(child.cloneNode(true));
        });
        this.__twebTemplateContent = fragment;
      }
      return this.__twebTemplateContent;
    },
    get id() {
      return __twebGetAttribute(nodeId, 'id') || '';
    },
    set id(value) {
      __twebSetAttribute(nodeId, 'id', String(value));
    },
    get className() {
      return __twebGetAttribute(nodeId, 'class') || '';
    },
    set className(value) {
      __twebSetAttribute(nodeId, 'class', String(value));
      __twebRecordAttributeMutation(this, 'class');
    },
    get contentEditable() {
      return __twebGetAttribute(nodeId, 'contenteditable') || 'inherit';
    },
    set contentEditable(value) {
      __twebSetAttribute(nodeId, 'contenteditable', String(value));
      __twebRecordAttributeMutation(this, 'contenteditable');
    },
    get innerHTML() {
      return __twebGetInnerHTML(nodeId);
    },
    set innerHTML(value) {
      __twebSetInnerHTML(nodeId, String(value));
      __twebRecordChildListMutation(this);
      Array.from(this.childNodes).forEach((child) => {
        __twebMaybeLoadInsertedSubtree(child);
      });
    },
    get outerHTML() {
      return __twebGetOuterHTML(nodeId);
    },
    set outerHTML(value) {
      if (!this.parentNode) {
        return;
      }
      this.insertAdjacentHTML('beforebegin', String(value));
      this.remove();
    },
    get innerText() {
      return __twebGetTextContent(nodeId);
    },
    set innerText(value) {
      __twebSetTextContent(nodeId, String(value));
      __twebRecordChildListMutation(this);
    },
    get parentElement() {
      const parentId = __twebGetParentNode(nodeId);
      return parentId ? __twebWrapNode(parentId) : null;
    },
    get parentNode() {
      const parent = this.parentElement;
      if (parent) {
        return parent;
      }
      if (
        (this.nodeType === Node.ELEMENT_NODE && this.nodeName === 'HTML') ||
        this.nodeType === Node.DOCUMENT_TYPE_NODE
      ) {
        return document;
      }
      return null;
    },
    get isConnected() {
      let current = this;
      while (current) {
        if (current.nodeType === Node.ELEMENT_NODE && current.nodeName === 'HTML') {
          return true;
        }
        current = current.parentNode;
      }
      return false;
    },
    get childNodes() {
      const ids = JSON.parse(__twebGetChildNodes(nodeId));
      return __twebCreateNodeList(ids.map((childNodeId) => __twebWrapNode(childNodeId)));
    },
    get children() {
      return __twebCreateHTMLCollection(this.childNodes.filter((child) => child.nodeType === Node.ELEMENT_NODE));
    },
    get firstChild() {
      return this.childNodes[0] || null;
    },
    get lastChild() {
      const children = this.childNodes;
      return children.length ? children[children.length - 1] : null;
    },
    get firstElementChild() {
      return this.children[0] || null;
    },
    get lastElementChild() {
      const children = this.children;
      return children.length ? children[children.length - 1] : null;
    },
    get childElementCount() {
      return this.children.length;
    },
    get clientWidth() {
      return __twebMeasureNode(this).width;
    },
    get clientHeight() {
      return __twebMeasureNode(this).height;
    },
    get offsetWidth() {
      return __twebMeasureNode(this).width;
    },
    get offsetHeight() {
      return __twebMeasureNode(this).height;
    },
    get scrollWidth() {
      return __twebMeasureNode(this).width;
    },
    get scrollHeight() {
      return __twebMeasureNode(this).height;
    },
    get scrollTop() {
      return this.__twebScrollTop || 0;
    },
    set scrollTop(value) {
      this.__twebScrollTop = Number(value) || 0;
    },
    get scrollLeft() {
      return this.__twebScrollLeft || 0;
    },
    set scrollLeft(value) {
      this.__twebScrollLeft = Number(value) || 0;
    },
    get nextSibling() {
      const parent = this.parentNode;
      if (!parent) {
        return null;
      }
      const siblings = parent.childNodes;
      const index = siblings.findIndex((child) => child.__twebNodeId === nodeId);
      return index >= 0 ? siblings[index + 1] || null : null;
    },
    get previousSibling() {
      const parent = this.parentNode;
      if (!parent) {
        return null;
      }
      const siblings = parent.childNodes;
      const index = siblings.findIndex((child) => child.__twebNodeId === nodeId);
      return index > 0 ? siblings[index - 1] : null;
    },
    get nextElementSibling() {
      let sibling = this.nextSibling;
      while (sibling && sibling.nodeType !== Node.ELEMENT_NODE) {
        sibling = sibling.nextSibling;
      }
      return sibling;
    },
    get previousElementSibling() {
      let sibling = this.previousSibling;
      while (sibling && sibling.nodeType !== Node.ELEMENT_NODE) {
        sibling = sibling.previousSibling;
      }
      return sibling;
    },
    get src() {
      const value = __twebGetAttribute(nodeId, 'src') || '';
      return value ? __twebResolveLocationTarget(value) : '';
    },
    set src(value) {
      __twebSetAttribute(nodeId, 'src', String(value));
      __twebRecordAttributeMutation(this, 'src');
      __twebMaybeLoadInsertedResource(this);
    },
    get href() {
      const value = __twebGetAttribute(nodeId, 'href') || '';
      return value ? __twebResolveLocationTarget(value) : '';
    },
    set href(value) {
      __twebSetAttribute(nodeId, 'href', String(value));
      __twebRecordAttributeMutation(this, 'href');
      __twebMaybeLoadInsertedResource(this);
    },
    get protocol() {
      return this.href ? new URL(this.href, location.href).protocol : '';
    },
    get host() {
      return this.href ? new URL(this.href, location.href).host : '';
    },
    get hostname() {
      return this.href ? new URL(this.href, location.href).hostname : '';
    },
    get pathname() {
      return this.href ? new URL(this.href, location.href).pathname : '';
    },
    get search() {
      return this.href ? new URL(this.href, location.href).search : '';
    },
    get hash() {
      return this.href ? new URL(this.href, location.href).hash : '';
    },
    get origin() {
      return this.href ? new URL(this.href, location.href).origin : '';
    },
    get target() {
      return __twebGetAttribute(nodeId, 'target') || '';
    },
    set target(value) {
      __twebSetAttribute(nodeId, 'target', String(value));
      __twebRecordAttributeMutation(this, 'target');
    },
    get rel() {
      return __twebGetAttribute(nodeId, 'rel') || '';
    },
    set rel(value) {
      __twebSetAttribute(nodeId, 'rel', String(value));
      __twebRecordAttributeMutation(this, 'rel');
    },
    get relList() {
      if (!this.__twebRelList) {
        this.__twebRelList = __twebCreateRelList(this);
      }
      return this.__twebRelList;
    },
    get nonce() {
      return __twebGetAttribute(nodeId, 'nonce') || '';
    },
    set nonce(value) {
      __twebSetAttribute(nodeId, 'nonce', String(value));
      __twebRecordAttributeMutation(this, 'nonce');
    },
    get crossOrigin() {
      return __twebGetAttribute(nodeId, 'crossorigin') || '';
    },
    set crossOrigin(value) {
      __twebSetAttribute(nodeId, 'crossorigin', String(value));
      __twebRecordAttributeMutation(this, 'crossorigin');
    },
    get async() {
      return __twebGetAttribute(nodeId, 'async') !== null;
    },
    set async(value) {
      if (value) {
        __twebSetAttribute(nodeId, 'async', '');
      } else {
        __twebRemoveAttribute(nodeId, 'async');
      }
      __twebRecordAttributeMutation(this, 'async');
    },
    get defer() {
      return __twebGetAttribute(nodeId, 'defer') !== null;
    },
    set defer(value) {
      if (value) {
        __twebSetAttribute(nodeId, 'defer', '');
      } else {
        __twebRemoveAttribute(nodeId, 'defer');
      }
      __twebRecordAttributeMutation(this, 'defer');
    },
    get fetchPriority() {
      return __twebGetAttribute(nodeId, 'fetchpriority') || '';
    },
    set fetchPriority(value) {
      __twebSetAttribute(nodeId, 'fetchpriority', String(value));
      __twebRecordAttributeMutation(this, 'fetchpriority');
    },
    get onload() {
      return this.__twebOnload || null;
    },
    set onload(value) {
      this.__twebOnload = typeof value === 'function' ? value : null;
    },
    get onerror() {
      return this.__twebOnerror || null;
    },
    set onerror(value) {
      this.__twebOnerror = typeof value === 'function' ? value : null;
    },
    get contentWindow() {
      if (this.tagName !== 'IFRAME') {
        return null;
      }
      if (!this.__twebContentWindow) {
        this.__twebContentWindow = __twebCreateIframeWindow(this);
      }
      return this.__twebContentWindow;
    },
    get contentDocument() {
      const frameWindow = this.contentWindow;
      return frameWindow ? frameWindow.document : null;
    },
    get name() {
      return __twebGetAttribute(nodeId, 'name') || '';
    },
    set name(value) {
      __twebSetAttribute(nodeId, 'name', String(value));
      __twebRecordAttributeMutation(this, 'name');
    },
    get type() {
      return __twebGetAttribute(nodeId, 'type') || '';
    },
    set type(value) {
      __twebSetAttribute(nodeId, 'type', String(value));
      __twebRecordAttributeMutation(this, 'type');
    },
    get value() {
      if (tagName === 'option') {
        return __twebOptionValue(this);
      }
      if (tagName === 'select') {
        const selected = __twebGetSelectedOptions(this)[0] || null;
        return selected ? __twebOptionValue(selected) : '';
      }
      return __twebGetAttribute(nodeId, 'value') || '';
    },
    set value(value) {
      if (tagName === 'option') {
        __twebSetAttribute(nodeId, 'value', String(value));
        __twebRecordAttributeMutation(this, 'value');
        return;
      }
      if (tagName === 'select') {
        __twebSetSelectValue(this, value);
        __twebRecordAttributeMutation(this, 'value');
        return;
      }
      __twebSetAttribute(nodeId, 'value', String(value));
      __twebRecordAttributeMutation(this, 'value');
    },
    get text() {
      return __twebOptionText(this);
    },
    set text(value) {
      this.textContent = String(value);
    },
    get label() {
      if (tagName !== 'option') {
        return __twebGetAttribute(nodeId, 'label') || '';
      }
      return __twebGetAttribute(nodeId, 'label') || __twebOptionText(this);
    },
    set label(value) {
      __twebSetAttribute(nodeId, 'label', String(value));
      __twebRecordAttributeMutation(this, 'label');
    },
    get placeholder() {
      return __twebGetAttribute(nodeId, 'placeholder') || '';
    },
    set placeholder(value) {
      __twebSetAttribute(nodeId, 'placeholder', String(value));
      __twebRecordAttributeMutation(this, 'placeholder');
    },
    get checked() {
      return __twebGetAttribute(nodeId, 'checked') !== null;
    },
    set checked(value) {
      if (value) {
        __twebSetAttribute(nodeId, 'checked', 'checked');
      } else {
        __twebRemoveAttribute(nodeId, 'checked');
      }
      __twebRecordAttributeMutation(this, 'checked');
    },
    get disabled() {
      return __twebGetAttribute(nodeId, 'disabled') !== null;
    },
    set disabled(value) {
      if (value) {
        __twebSetAttribute(nodeId, 'disabled', 'disabled');
      } else {
        __twebRemoveAttribute(nodeId, 'disabled');
      }
      __twebRecordAttributeMutation(this, 'disabled');
    },
    get defaultSelected() {
      return __twebGetAttribute(nodeId, 'selected') !== null;
    },
    set defaultSelected(value) {
      if (value) {
        __twebSetAttribute(nodeId, 'selected', 'selected');
      } else {
        __twebRemoveAttribute(nodeId, 'selected');
      }
      __twebRecordAttributeMutation(this, 'selected');
    },
    get selected() {
      if (tagName !== 'option') {
        return __twebGetAttribute(nodeId, 'selected') !== null;
      }
      const parentSelect = this.closest && this.closest('select');
      if (!parentSelect) {
        return __twebGetAttribute(nodeId, 'selected') !== null;
      }
      return __twebGetSelectedOptions(parentSelect).includes(this);
    },
    set selected(value) {
      if (tagName !== 'option') {
        if (value) {
          __twebSetAttribute(nodeId, 'selected', 'selected');
        } else {
          __twebRemoveAttribute(nodeId, 'selected');
        }
        __twebRecordAttributeMutation(this, 'selected');
        return;
      }
      const parentSelect = this.closest && this.closest('select');
      if (value) {
        if (parentSelect && !__twebSelectAllowsMultiple(parentSelect)) {
          __twebOptionElementsForNode(parentSelect).forEach((option) => {
            if (option === this) {
              __twebSetAttribute(option.__twebNodeId, 'selected', 'selected');
            } else {
              __twebRemoveAttribute(option.__twebNodeId, 'selected');
            }
            __twebRecordAttributeMutation(option, 'selected');
          });
          return;
        }
        __twebSetAttribute(nodeId, 'selected', 'selected');
      } else {
        __twebRemoveAttribute(nodeId, 'selected');
      }
      __twebRecordAttributeMutation(this, 'selected');
    },
    get length() {
      if (tagName === 'select') {
        return __twebOptionElementsForNode(this).length;
      }
      return this.children.length;
    },
    set length(value) {
      if (tagName !== 'select') {
        return;
      }
      const nextLength = Math.max(0, Number(value) || 0);
      const options = __twebOptionElementsForNode(this);
      if (nextLength >= options.length) {
        return;
      }
      options.slice(nextLength).forEach((option) => option.remove());
    },
    get options() {
      if (tagName !== 'select') {
        return undefined;
      }
      return __twebCreateHTMLCollection(__twebOptionElementsForNode(this));
    },
    get selectedOptions() {
      if (tagName !== 'select') {
        return __twebCreateHTMLCollection([]);
      }
      return __twebCreateHTMLCollection(__twebGetSelectedOptions(this));
    },
    get selectedIndex() {
      if (tagName !== 'select') {
        return -1;
      }
      return __twebGetSelectedIndex(this);
    },
    set selectedIndex(value) {
      if (tagName !== 'select') {
        return;
      }
      __twebSetSelectedIndex(this, value);
      __twebRecordAttributeMutation(this, 'selectedIndex');
    },
    get form() {
      return this.closest ? this.closest('form') : null;
    },
    get index() {
      if (tagName !== 'option') {
        return -1;
      }
      return __twebSelectOptionIndex(this);
    },
    get width() {
      return Number(__twebGetAttribute(nodeId, 'width') || 0);
    },
    set width(value) {
      __twebSetAttribute(nodeId, 'width', String(value));
      __twebRecordAttributeMutation(this, 'width');
    },
    get height() {
      return Number(__twebGetAttribute(nodeId, 'height') || 0);
    },
    set height(value) {
      __twebSetAttribute(nodeId, 'height', String(value));
      __twebRecordAttributeMutation(this, 'height');
    },
    get hidden() {
      return __twebGetAttribute(nodeId, 'hidden') !== null;
    },
    set hidden(value) {
      if (value) {
        __twebSetAttribute(nodeId, 'hidden', 'hidden');
      } else {
        __twebRemoveAttribute(nodeId, 'hidden');
      }
      __twebRecordAttributeMutation(this, 'hidden');
    },
    get dataset() {
      const entries = {};
      Object.entries(JSON.parse(__twebGetAttributes(nodeId))).forEach(([name, value]) => {
        if (name.startsWith('data-')) {
          entries[__twebAttributeToDataKey(name)] = value;
        }
      });
      return new Proxy(entries, {
        get: (_target, prop) => __twebGetAttribute(nodeId, __twebDataKeyToAttribute(prop)) || undefined,
        set: (_target, prop, value) => {
          const attrName = __twebDataKeyToAttribute(prop);
          __twebSetAttribute(nodeId, attrName, String(value));
          __twebRecordAttributeMutation(this, attrName);
          return true;
        }
      });
    },
    get style() {
      const save = (styleMap) => {
        const cssText = __twebSerializeStyle(styleMap);
        if (cssText) {
          __twebSetAttribute(nodeId, 'style', cssText);
        } else {
          __twebRemoveAttribute(nodeId, 'style');
        }
      };
      const declaration = {
        get cssText() {
          return __twebGetAttribute(nodeId, 'style') || '';
        },
        set cssText(value) {
          __twebSetAttribute(nodeId, 'style', String(value));
          __twebRecordAttributeMutation(node, 'style');
        },
        getPropertyValue(name) {
          return __twebParseStyle(__twebGetAttribute(nodeId, 'style') || '')[String(name)] || '';
        },
        setProperty(name, value) {
          const styleMap = __twebParseStyle(__twebGetAttribute(nodeId, 'style') || '');
          styleMap[String(name)] = String(value);
          save(styleMap);
          __twebRecordAttributeMutation(node, 'style');
        },
        removeProperty(name) {
          const styleMap = __twebParseStyle(__twebGetAttribute(nodeId, 'style') || '');
          const key = String(name);
          const value = styleMap[key] || '';
          delete styleMap[key];
          save(styleMap);
          __twebRecordAttributeMutation(node, 'style');
          return value;
        }
      };
      return new Proxy(declaration, {
        get(target, prop, receiver) {
          if (typeof prop !== 'string' || prop in target) {
            return Reflect.get(target, prop, receiver);
          }
          const name = prop === 'cssFloat'
            ? 'float'
            : prop.replace(/[A-Z]/g, (part) => `-${part.toLowerCase()}`);
          return target.getPropertyValue(name);
        },
        set(target, prop, value, receiver) {
          if (typeof prop !== 'string' || prop in target) {
            return Reflect.set(target, prop, value, receiver);
          }
          const name = prop === 'cssFloat'
            ? 'float'
            : prop.replace(/[A-Z]/g, (part) => `-${part.toLowerCase()}`);
          target.setProperty(name, value);
          return true;
        },
      });
    },
    get adoptedStyleSheets() {
      return this.__twebAdoptedStyleSheets || [];
    },
    set adoptedStyleSheets(value) {
      this.__twebAdoptedStyleSheets = Array.isArray(value) ? value : [];
    },
    get classList() {
      const getClasses = () => (this.className || '').split(/\\s+/).filter(Boolean);
      const setClasses = (classes) => {
        this.className = classes.join(' ');
      };
      return {
        contains(name) {
          return getClasses().includes(String(name));
        },
        add(...names) {
          const next = new Set(getClasses());
          names.forEach((name) => next.add(String(name)));
          setClasses(Array.from(next));
        },
        remove(...names) {
          const blocked = new Set(names.map((name) => String(name)));
          setClasses(getClasses().filter((name) => !blocked.has(name)));
        },
        toggle(name, force) {
          const text = String(name);
          const exists = getClasses().includes(text);
          if (force === true || (!exists && force !== false)) {
            this.add(text);
            return true;
          }
          if (exists) {
            this.remove(text);
          }
          return false;
        }
      };
    },
    get attributes() {
      if (!this.__twebNamedNodeMap) {
        this.__twebNamedNodeMap = __twebCreateNamedNodeMap(this, nodeId);
      }
      return this.__twebNamedNodeMap;
    },
    getAttribute(name) {
      return __twebGetAttribute(nodeId, String(name));
    },
    getAttributeNode(name) {
      const value = this.getAttribute(name);
      if (value === null) {
        return null;
      }
      return __twebCreateAttrNode(this, name, value);
    },
    getAttributeNodeNS(_namespace, name) {
      return this.getAttributeNode(name);
    },
    hasAttribute(name) {
      return __twebGetAttribute(nodeId, String(name)) !== null;
    },
    hasAttributeNS(_namespace, name) {
      return this.hasAttribute(name);
    },
    getAttributeNames() {
      return Object.keys(JSON.parse(__twebGetAttributes(nodeId)));
    },
    setAttribute(name, value) {
      const attrName = String(name);
      __twebSetAttribute(nodeId, attrName, String(value));
      __twebRecordAttributeMutation(this, attrName);
      if (attrName === 'src' || attrName === 'href') {
        __twebMaybeLoadInsertedResource(this);
      }
    },
    setAttributeNode(attribute) {
      if (!attribute || typeof attribute.name !== 'string') {
        throw new TypeError('Invalid attribute node');
      }
      const previous = this.getAttributeNode(attribute.name);
      this.setAttribute(attribute.name, attribute.value);
      attribute.ownerElement = this;
      return previous;
    },
    setAttributeNodeNS(attribute) {
      return this.setAttributeNode(attribute);
    },
    setAttributeNS(_namespace, name, value) {
      const attrName = String(name);
      __twebSetAttribute(nodeId, attrName, String(value));
      __twebRecordAttributeMutation(this, attrName);
      if (attrName === 'src' || attrName === 'href') {
        __twebMaybeLoadInsertedResource(this);
      }
    },
    removeAttribute(name) {
      __twebRemoveAttribute(nodeId, String(name));
      __twebRecordAttributeMutation(this, name);
    },
    removeAttributeNode(attribute) {
      if (!attribute || typeof attribute.name !== 'string') {
        throw new TypeError('Invalid attribute node');
      }
      const existing = this.getAttributeNode(attribute.name);
      if (!existing) {
        throw new DOMException('Attribute was not found', 'NotFoundError');
      }
      this.removeAttribute(attribute.name);
      attribute.ownerElement = null;
      return existing;
    },
    removeAttributeNS(_namespace, name) {
      __twebRemoveAttribute(nodeId, String(name));
      __twebRecordAttributeMutation(this, name);
    },
    toggleAttribute(name, force = undefined) {
      const attrName = String(name);
      const present = this.hasAttribute(attrName);
      const next = force === undefined ? !present : !!force;
      if (next) {
        this.setAttribute(attrName, '');
      } else {
        this.removeAttribute(attrName);
      }
      return next;
    },
    appendChild(child) {
      const childNode = child;
      const fragmentChildren = child.nodeType === Node.DOCUMENT_FRAGMENT_NODE
        ? Array.from(child.childNodes)
        : null;
      const childNodeId = __twebAppendChild(nodeId, child.__twebNodeId);
      const insertedNode = __twebWrapNode(childNodeId);
      __twebRecordChildListMutation(this, [insertedNode], []);
      if (this.tagName === 'STYLE' && child.tagName === '#text') {
        if (this.__twebStyleSheetInitialized && this.__twebStyleSheet) {
          const sheet = this.__twebStyleSheet;
          __twebParseCssRules(child.textContent || '').forEach((rule) => {
            sheet.cssRules.push(rule);
          });
        }
      }
      if (fragmentChildren) {
        fragmentChildren.forEach((entry) => __twebMaybeLoadInsertedSubtree(entry));
      } else {
        __twebMaybeLoadInsertedSubtree(insertedNode);
      }
      return insertedNode;
    },
    append(...children) {
      children.forEach((child) => {
        if (typeof child === 'string') {
          this.appendChild(document.createTextNode(child));
        } else {
          this.appendChild(child);
        }
      });
    },
    prepend(...children) {
      let referenceNode = this.firstChild;
      children.forEach((child) => {
        const nextChild = typeof child === 'string'
          ? document.createTextNode(child)
          : child;
        this.insertBefore(nextChild, referenceNode);
      });
    },
    replaceChildren(...children) {
      while (this.firstChild) {
        this.removeChild(this.firstChild);
      }
      this.append(...children);
    },
    hasChildNodes() {
      return this.childNodes.length > 0;
    },
    remove(index = undefined) {
      if (tagName === 'select' && index !== undefined) {
        const options = __twebOptionElementsForNode(this);
        const target = options[Math.max(0, Number(index) || 0)] || null;
        if (target) {
          target.remove();
        }
        return undefined;
      }
      const parent = this.parentNode;
      __twebRemoveNode(nodeId);
      if (parent) {
        __twebRecordChildListMutation(parent, [], [this]);
      }
      return undefined;
    },
    removeChild(child) {
      child.remove();
      return child;
    },
    getContext(kind) {
      if (this.tagName !== 'CANVAS' || String(kind) !== '2d') {
        return null;
      }
      if (!this.__twebCanvasContext) {
        this.__twebCanvasContext = __twebCreateCanvasContext(this);
      }
      return this.__twebCanvasContext;
    },
    toBlob(callback, type = 'image/png') {
      const blob = { type: String(type), size: 0 };
      __twebEnqueueTimer(() => callback(blob));
    },
    toDataURL(type = 'image/png') {
      return `data:${String(type)};base64,`;
    },
    insertBefore(child, referenceNode) {
      if (!referenceNode) {
        return this.appendChild(child);
      }
      const fragmentChildren = child.nodeType === Node.DOCUMENT_FRAGMENT_NODE
        ? Array.from(child.childNodes)
        : null;
      const childNodeId = __twebInsertBefore(nodeId, child.__twebNodeId, referenceNode.__twebNodeId);
      const insertedNode = __twebWrapNode(childNodeId);
      __twebRecordChildListMutation(this, [insertedNode], []);
      if (fragmentChildren) {
        fragmentChildren.forEach((entry) => __twebMaybeLoadInsertedSubtree(entry));
      } else {
        __twebMaybeLoadInsertedSubtree(insertedNode);
      }
      return insertedNode;
    },
    replaceChild(child, referenceNode) {
      const inserted = this.insertBefore(child, referenceNode);
      referenceNode.remove();
      return inserted;
    },
    before(...children) {
      const parent = this.parentNode;
      if (!parent) {
        return;
      }
      children.forEach((child) => {
        const nextChild = typeof child === 'string'
          ? document.createTextNode(child)
          : child;
        parent.insertBefore(nextChild, this);
      });
    },
    after(...children) {
      const parent = this.parentNode;
      if (!parent) {
        return;
      }
      let referenceNode = this.nextSibling;
      children.forEach((child) => {
        const nextChild = typeof child === 'string'
          ? document.createTextNode(child)
          : child;
        parent.insertBefore(nextChild, referenceNode);
      });
    },
    replaceWith(...children) {
      const parent = this.parentNode;
      if (!parent) {
        return;
      }
      let referenceNode = this;
      children.forEach((child) => {
        const nextChild = typeof child === 'string'
          ? document.createTextNode(child)
          : child;
        parent.insertBefore(nextChild, referenceNode);
      });
      this.remove();
    },
    cloneNode(deep = false) {
      return __twebWrapNode(__twebCloneNode(nodeId, !!deep));
    },
    contains(candidate) {
      if (!candidate) {
        return false;
      }
      if (candidate.__twebNodeId === nodeId) {
        return true;
      }
      const pending = this.childNodes.slice();
      while (pending.length) {
        const current = pending.pop();
        if (!current) {
          continue;
        }
        if (current.__twebNodeId === candidate.__twebNodeId) {
          return true;
        }
        if (current.childNodes && current.childNodes.length) {
          for (let index = current.childNodes.length - 1; index >= 0; index -= 1) {
            pending.push(current.childNodes[index]);
          }
        }
      }
      return false;
    },
    compareDocumentPosition(other) {
      if (!other || !other.__twebNodeId) {
        return Node.DOCUMENT_POSITION_DISCONNECTED;
      }
      if (other.__twebNodeId === nodeId) {
        return 0;
      }
      const getChain = (node) => {
        const chain = [];
        let current = node;
        while (current) {
          chain.push(current);
          current = current.parentNode;
        }
        return chain;
      };
      const selfChain = getChain(this);
      const otherChain = getChain(other);
      const selfRoot = selfChain[selfChain.length - 1] || null;
      const otherRoot = otherChain[otherChain.length - 1] || null;
      if (!selfRoot || !otherRoot || selfRoot !== otherRoot) {
        return Node.DOCUMENT_POSITION_DISCONNECTED;
      }
      if (this.contains(other)) {
        return Node.DOCUMENT_POSITION_CONTAINS | Node.DOCUMENT_POSITION_PRECEDING;
      }
      if (other.contains && other.contains(this)) {
        return Node.DOCUMENT_POSITION_CONTAINED_BY | Node.DOCUMENT_POSITION_FOLLOWING;
      }
      let selfIndex = selfChain.length - 1;
      let otherIndex = otherChain.length - 1;
      while (
        selfIndex >= 0 &&
        otherIndex >= 0 &&
        selfChain[selfIndex].__twebNodeId === otherChain[otherIndex].__twebNodeId
      ) {
        selfIndex -= 1;
        otherIndex -= 1;
      }
      if (selfIndex < 0 || otherIndex < 0) {
        return Node.DOCUMENT_POSITION_DISCONNECTED;
      }
      const selfAncestor = selfChain[selfIndex];
      const otherAncestor = otherChain[otherIndex];
      const parent = selfChain[selfIndex + 1];
      if (!parent || !parent.childNodes) {
        return Node.DOCUMENT_POSITION_DISCONNECTED;
      }
      const siblings = parent.childNodes;
      for (let index = 0; index < siblings.length; index += 1) {
        const sibling = siblings[index];
        if (sibling.__twebNodeId === selfAncestor.__twebNodeId) {
          return Node.DOCUMENT_POSITION_FOLLOWING;
        }
        if (sibling.__twebNodeId === otherAncestor.__twebNodeId) {
          return Node.DOCUMENT_POSITION_PRECEDING;
        }
      }
      return Node.DOCUMENT_POSITION_DISCONNECTED;
    },
    isSameNode(other) {
      return this === other;
    },
    isEqualNode(other) {
      return __twebNodesEqual(this, other);
    },
    getRootNode() {
      let current = this;
      while (current.parentNode) {
        current = current.parentNode;
      }
      if (current && current.nodeType === Node.ELEMENT_NODE && current.nodeName === 'HTML') {
        return document;
      }
      return current;
    },
    querySelector(selector) {
      const childNodeId = __twebNodeQueryOne(nodeId, String(selector));
      if (!childNodeId) {
        return null;
      }
      return __twebWrapNode(childNodeId);
    },
    querySelectorAll(selector) {
      const ids = JSON.parse(__twebNodeQueryAll(nodeId, String(selector)));
      return __twebCreateNodeList(ids.map((childNodeId) => __twebWrapNode(childNodeId)));
    },
    matches(selector) {
      const parent = this.parentNode || document;
      return parent.querySelectorAll(selector).some((candidate) => candidate.__twebNodeId === nodeId);
    },
    closest(selector) {
      let current = this;
      while (current && current.nodeType === Node.ELEMENT_NODE) {
        if (current.matches(selector)) {
          return current;
        }
        current = current.parentElement;
      }
      return null;
    },
    getElementsByTagName(tagName) {
      const ids = JSON.parse(__twebNodeGetElementsByTagName(nodeId, String(tagName)));
      return __twebCreateHTMLCollection(ids.map((childNodeId) => __twebWrapNode(childNodeId)));
    },
    addEventListener(type, callback) {
      __twebAddEventListener(this, type, callback);
    },
    removeEventListener(type, callback) {
      __twebRemoveEventListener(this, type, callback);
    },
    dispatchEvent(event) {
      return __twebDispatchEventOnTarget(this, event);
    },
    focus() {
      __twebActiveElement = this;
      const event = new Event('focus');
      event.target = this;
      __twebDispatchEventOnTarget(this, event);
    },
    blur() {
      if (__twebActiveElement === this) {
        __twebActiveElement = document.body || document.documentElement || null;
      }
      const event = new Event('blur');
      event.target = this;
      __twebDispatchEventOnTarget(this, event);
    },
    click() {
      const event = new MouseEvent('click', { bubbles: true, cancelable: true });
      event.target = this;
      return __twebDispatchEventOnTarget(this, event);
    },
    submit() {
      const event = new Event('submit', { bubbles: true, cancelable: true });
      event.target = this;
      return __twebDispatchEventOnTarget(this, event);
    },
    requestSubmit(submitter = null) {
      if (submitter && typeof submitter.click === 'function') {
        submitter.click();
      }
      return this.submit();
    },
    reset() {
      const event = new Event('reset', { bubbles: true, cancelable: true });
      event.target = this;
      return __twebDispatchEventOnTarget(this, event);
    },
    add(item, before = undefined) {
      if (tagName !== 'select') {
        return undefined;
      }
      if (!item || typeof item !== 'object') {
        throw new TypeError('Failed to execute add on HTMLSelectElement');
      }
      const options = __twebOptionElementsForNode(this);
      let referenceNode = null;
      if (typeof before === 'number') {
        referenceNode = options[Math.max(0, Number(before) || 0)] || null;
      } else if (before && typeof before === 'object') {
        referenceNode = before;
      }
      this.insertBefore(item, referenceNode);
      return undefined;
    },
    checkValidity() {
      return true;
    },
    reportValidity() {
      return true;
    },
    animate(_keyframes = [], _options = {}) {
      return {
        finished: Promise.resolve(this),
        ready: Promise.resolve(this),
        playState: 'finished',
        cancel() {},
        finish() {},
        play() {},
        pause() {},
        reverse() {},
      };
    },
    getAnimations() {
      return [];
    },
    decode() {
      return Promise.resolve();
    },
    play() {
      this.paused = false;
      return Promise.resolve();
    },
    pause() {
      this.paused = true;
    },
    canPlayType(_type = '') {
      return 'maybe';
    },
    load() {},
    show() {
      this.open = true;
    },
    showModal() {
      this.open = true;
    },
    close(_returnValue = '') {
      this.open = false;
    },
    getContext(kind = '2d') {
      if (tagName !== 'canvas') {
        return null;
      }
      if (!this.__twebCanvasContexts) {
        this.__twebCanvasContexts = {};
      }
      const key = String(kind || '2d');
      if (!this.__twebCanvasContexts[key]) {
        this.__twebCanvasContexts[key] = {
          canvas: this,
          fillStyle: '#000000',
          strokeStyle: '#000000',
          lineWidth: 1,
          globalAlpha: 1,
          font: '10px sans-serif',
          clearRect() {},
          fillRect() {},
          strokeRect() {},
          drawImage() {},
          beginPath() {},
          closePath() {},
          moveTo() {},
          lineTo() {},
          bezierCurveTo() {},
          quadraticCurveTo() {},
          arc() {},
          rect() {},
          fill() {},
          stroke() {},
          clip() {},
          save() {},
          restore() {},
          scale() {},
          rotate() {},
          translate() {},
          transform() {},
          setTransform() {},
          resetTransform() {},
          createLinearGradient() {
            return { addColorStop() {} };
          },
          createPattern() {
            return null;
          },
          createRadialGradient() {
            return { addColorStop() {} };
          },
          createImageData(width = 0, height = 0) {
            return {
              data: new Uint8ClampedArray(Math.max(0, Number(width) * Number(height) * 4)),
              width: Number(width),
              height: Number(height),
            };
          },
          getImageData(_x = 0, _y = 0, width = 0, height = 0) {
            return this.createImageData(width, height);
          },
          putImageData() {},
          measureText(text = '') {
            return { width: String(text).length * 8 };
          },
          fillText() {},
          strokeText() {},
        };
      }
      return this.__twebCanvasContexts[key];
    },
    toDataURL(type = 'image/png') {
      if (tagName !== 'canvas') {
        return '';
      }
      return `data:${String(type)};base64,`;
    },
    insertAdjacentElement(position, element) {
      const where = String(position || '').toLowerCase();
      if (!(element instanceof Node)) {
        return null;
      }
      if (where === 'beforebegin' && this.parentNode) {
        this.parentNode.insertBefore(element, this);
        return element;
      }
      if (where === 'afterbegin') {
        this.insertBefore(element, this.firstChild);
        return element;
      }
      if (where === 'beforeend') {
        this.appendChild(element);
        return element;
      }
      if (where === 'afterend' && this.parentNode) {
        this.parentNode.insertBefore(element, this.nextSibling);
        return element;
      }
      return null;
    },
    insertAdjacentText(position, text) {
      const node = document.createTextNode(String(text));
      this.insertAdjacentElement(position, node);
    },
    insertAdjacentHTML(position, html) {
      const container = document.createElement('div');
      container.innerHTML = String(html);
      const nodes = Array.from(container.childNodes);
      const fragment = document.createDocumentFragment();
      nodes.forEach((child) => fragment.appendChild(child));
      this.insertAdjacentElement(position, fragment);
    },
    showPopover() {
      this.hidden = false;
    },
    hidePopover() {
      this.hidden = true;
    },
    togglePopover(force) {
      if (force === undefined) {
        this.hidden = !this.hidden;
      } else {
        this.hidden = !force;
      }
    },
    attachShadow(_init = {}) {
      const root = document.createDocumentFragment();
      root.host = this;
      this.shadowRoot = root;
      return root;
    },
    getBoundingClientRect() {
      const box = __twebMeasureNode(this);
      return {
        x: 0,
        y: 0,
        width: box.width,
        height: box.height,
        top: 0,
        right: box.width,
        bottom: box.height,
        left: 0
      };
    },
    scroll(_x = 0, _y = 0) {},
    scrollTo(_x = 0, _y = 0) {},
    scrollBy(_x = 0, _y = 0) {},
    scrollIntoView() {},
    select() {},
    setSelectionRange(start = 0, end = start, direction = 'none') {
      this.selectionStart = Number(start) || 0;
      this.selectionEnd = Number(end) || 0;
      this.selectionDirection = String(direction || 'none');
    },
    setRangeText(replacement = '', start = 0, end = start, _selectionMode = 'preserve') {
      const currentValue = String(this.value || '');
      const from = Math.max(0, Number(start) || 0);
      const to = Math.max(from, Number(end) || 0);
      this.value = `${currentValue.slice(0, from)}${String(replacement)}${currentValue.slice(to)}`;
    },
    showPicker() {},
    checkVisibility() {
      return !this.hidden;
    },
    __twebNodeId: nodeId
  };
  Object.setPrototypeOf(node, prototype);
  const builtinKeys = new Set(Reflect.ownKeys(node));
  const wrapped = new Proxy(node, {
    get(target, prop, receiver) {
      if (Reflect.has(target, prop)) {
        return Reflect.get(target, prop, receiver);
      }
      if (typeof prop !== 'string') {
        return undefined;
      }
      if (prop.startsWith('__tweb')) {
        return target[prop];
      }
      const attrName = __twebPropertyToAttribute(prop);
      const value = __twebGetAttribute(nodeId, attrName);
      if (value !== null) {
        return value;
      }
      if (__twebReflectedProperties.has(prop)) {
        return '';
      }
      return undefined;
    },
    set(target, prop, value, receiver) {
      if (Reflect.has(target, prop)) {
        return Reflect.set(target, prop, value, receiver);
      }
      if (typeof prop !== 'string') {
        target[prop] = value;
        return true;
      }
      if (prop.startsWith('__tweb')) {
        target[prop] = value;
        return true;
      }
      const attrName = __twebPropertyToAttribute(prop);
      if (__twebReflectedProperties.has(prop) || __twebGetAttribute(nodeId, attrName) !== null) {
        __twebSetAttribute(nodeId, attrName, String(value));
        return true;
      }
      target[prop] = value;
      return true;
    },
    ownKeys(target) {
      return Reflect.ownKeys(target).filter((key) => {
        return typeof key !== 'string' || !builtinKeys.has(key);
      });
    },
    getOwnPropertyDescriptor(target, prop) {
      const descriptor = Reflect.getOwnPropertyDescriptor(target, prop);
      if (!descriptor) {
        return undefined;
      }
      if (typeof prop === 'string' && builtinKeys.has(prop)) {
        return {
          ...descriptor,
          enumerable: false,
        };
      }
      return descriptor;
    }
  });
  __twebNodeCache.set(nodeId, wrapped);
  return wrapped;
}
"""
