import { readFileSync } from "node:fs";
import vm from "node:vm";

const ANCHOR_SELECTOR = "a[href]";
const RUN_TIMEOUT_MS = 1000;
const RUNNER_FAILURE_EXIT_CODE = 2;

const parseHref = (href, base) => {
  try {
    const url = new URL(href, base);
    return { href: url.href, hostname: url.hostname };
  } catch {
    return null;
  }
};

const guard = (label, target, readable, writable, violations) => {
  const record = (action, key) => {
    violations.push(`${label}.${String(key)} ${action}`);
  };
  return new Proxy(target, {
    get(object, key) {
      if (readable.has(key)) return Reflect.get(object, key);
      record("읽기", key);
      return undefined;
    },
    set(object, key, value) {
      if (writable.has(key)) return Reflect.set(object, key, value);
      record("쓰기", key);
      return true;
    },
    has(_, key) {
      if (readable.has(key)) return true;
      record("읽기", key);
      return false;
    },
    getOwnPropertyDescriptor(_, key) {
      record("읽기", key);
      return undefined;
    },
    ownKeys() {
      record("읽기", "ownKeys");
      return [];
    },
    getPrototypeOf() {
      record("읽기", "prototype");
      return null;
    },
    defineProperty(_, key) {
      record("쓰기", key);
      return true;
    },
    deleteProperty(_, key) {
      record("쓰기", key);
      return true;
    },
    setPrototypeOf() {
      record("쓰기", "prototype");
      return true;
    },
    preventExtensions() {
      record("쓰기", "preventExtensions");
      return false;
    },
  });
};

const makeAnchor = (state, index, failingIndex, pageUrl, violations) =>
  guard(
    `a[${index}]`,
    {
      get href() {
        if (index === failingIndex) throw new Error(`a[${index}].href 읽기 고장 주입`);
        return parseHref(state.attribute, pageUrl)?.href ?? state.attribute;
      },
      set href(value) {
        state.attribute = String(value);
      },
    },
    new Set(["href"]),
    new Set(["href"]),
    violations,
  );

const makeDocument = (referrer, anchors, violations) =>
  guard(
    "document",
    {
      referrer,
      querySelectorAll(selector) {
        if (selector === ANCHOR_SELECTOR) return [...anchors];
        violations.push(`document.querySelectorAll(${JSON.stringify(String(selector))})`);
        return [];
      },
    },
    new Set(["referrer", "querySelectorAll"]),
    new Set(),
    violations,
  );

const makeLocation = (pageUrl, violations) => {
  const { search, origin, pathname } = new URL(pageUrl);
  return guard("location", { search, origin, pathname }, new Set(["search", "origin", "pathname"]), new Set(), violations);
};

const describeThrown = (thrown) => {
  try {
    return typeof thrown?.message === "string" ? thrown.message : String(thrown);
  } catch {
    return "throw";
  }
};

const runCase = (source, scriptPath, { url, referrer, hrefs, throwOnHrefRead }) => {
  const violations = [];
  const states = hrefs.map((attribute) => ({ attribute }));
  const anchors = states.map((state, index) => makeAnchor(state, index, throwOnHrefRead, url, violations));
  const context = vm.createContext({
    document: makeDocument(referrer, anchors, violations),
    location: makeLocation(url, violations),
    URL,
    URLSearchParams,
  });
  let error = null;
  try {
    new vm.Script(source, { filename: scriptPath }).runInContext(context, { timeout: RUN_TIMEOUT_MS });
  } catch (thrown) {
    error = describeThrown(thrown);
  }
  return { hrefs: states.map((state) => state.attribute), error, violations };
};

const main = () => {
  const request = JSON.parse(readFileSync(0, "utf8"));
  const parse = request.parse.map(({ base, hrefs }) => hrefs.map((href) => parseHref(href, base)));
  const { script, cases } = request.run;
  const source = cases.length > 0 ? readFileSync(script, "utf8") : "";
  const run = cases.map((testCase) => runCase(source, script, testCase));
  process.stdout.write(JSON.stringify({ parse, run }));
};

try {
  main();
} catch (error) {
  process.stderr.write(`campaign_runner: ${describeThrown(error)}\n`);
  process.exitCode = RUNNER_FAILURE_EXIT_CODE;
}
