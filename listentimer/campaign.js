(() => {
  const STORE_HOST = "apps.apple.com";
  const STORE_TOKEN_PARAM = "ct";
  const STORE_TOKEN = "web_gpt";
  const UTM_SOURCE_PARAM = "utm_source";
  const CHATGPT_UTM_SOURCE = "chatgpt.com";
  const CHATGPT_REFERRER_HOSTS = ["chatgpt.com", "chat.openai.com"];
  const LANDING_PATH_PREFIX = "/listentimer/";

  const parseUrl = (value) => {
    try {
      return new URL(value);
    } catch {
      return null;
    }
  };

  const arrivedFromChatGpt = () => {
    const tagged = new URLSearchParams(location.search)
      .getAll(UTM_SOURCE_PARAM)
      .some((value) => value.toLowerCase() === CHATGPT_UTM_SOURCE);
    const referrer = parseUrl(document.referrer);
    return tagged || (referrer !== null && CHATGPT_REFERRER_HOSTS.includes(referrer.hostname));
  };

  const taggedHref = (url) => {
    if (url.hostname === STORE_HOST && url.searchParams.has(STORE_TOKEN_PARAM)) {
      url.searchParams.set(STORE_TOKEN_PARAM, STORE_TOKEN);
      return url.href;
    }
    const otherLandingPage =
      url.origin === location.origin &&
      url.pathname.startsWith(LANDING_PATH_PREFIX) &&
      url.pathname !== location.pathname;
    if (otherLandingPage) {
      url.searchParams.set(UTM_SOURCE_PARAM, CHATGPT_UTM_SOURCE);
      return url.href;
    }
    return null;
  };

  if (!arrivedFromChatGpt()) return;

  const updates = [];
  for (const anchor of document.querySelectorAll("a[href]")) {
    const href = anchor.href;
    const url = parseUrl(href);
    const next = url === null ? null : taggedHref(url);
    if (next !== null) updates.push([anchor, next]);
  }
  for (const [anchor, next] of updates) {
    anchor.href = next;
  }
})();
