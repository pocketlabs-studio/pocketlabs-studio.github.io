#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO = Path.cwd()
PAGE = Path("index.html")
APPS_SECTION_ID = "apps"

HOUSECAST_NAME = "HouseCast"
HOUSECAST_STORES = [
    ("iOS", "https://apps.apple.com/kr/app/id6806436067", "iOS — HouseCast on the App Store"),
    ("Android", "https://play.google.com/store/apps/details?id=com.pocketlabs.housecast&hl=ko&gl=KR",
     "Android — HouseCast on Google Play"),
]
LISTENTIMER_NAME = "ListenTimer"
LISTENTIMER_HREF = "/listentimer/"
LISTENTIMER_LABEL = "iOS"

TABLE_MIN_WIDTH = 1160
STORES_BESIDE_NAME_MIN_WIDTH = 375

ARROW_GLYPH = "↗"
NEW_TAB = "_blank"
REQUIRED_REL = "noopener"
MIN_STORES_PER_MULTI_ROW = 2

VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input",
                       "link", "meta", "source", "track", "wbr"})
MAX_WIDTH = re.compile(r"\(\s*max-width:\s*([\d.]+)px\s*\)")
AREA_ROW = re.compile(r'"([^"]*)"')
ROW_STATE = re.compile(r"\.app-row:(hover|focus-visible)\b")
LINK_ROW_STATE = re.compile(r"(?<![\w.#\]-])a\.app-row:(hover|focus-visible)\b")

failures = []


def fail(check, message):
    failures.append("[%s] %s" % (check, message))


class Element:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children = []

    @property
    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def elements(self):
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.elements()

    def find(self, cls, tag=None):
        return [el for el in self.elements() if cls in el.classes and (tag is None or el.tag == tag)]

    def text(self):
        raw = "".join(child if isinstance(child, str) else child.text() for child in self.children)
        return " ".join(raw.split())

    def lineage(self):
        node = self
        while node is not None:
            yield node
            node = node.parent

    def aria_hidden(self):
        return any(node.attrs.get("aria-hidden") == "true" for node in self.lineage())


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, None)
        self.current = self.root
        self.mismatches = []

    def _element(self, tag, attrs):
        fields = {}
        for name, value in attrs:
            fields.setdefault(name, value if value is not None else "")
        element = Element(tag, fields, self.current)
        self.current.children.append(element)
        return element

    def handle_starttag(self, tag, attrs):
        element = self._element(tag, attrs)
        if tag not in VOID_TAGS:
            self.current = element

    def handle_startendtag(self, tag, attrs):
        self._element(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self.current.tag == tag:
            self.current = self.current.parent
            return
        self.mismatches.append("</%s> (열린 요소 <%s>)" % (tag, self.current.tag))
        opener = next((node for node in self.current.lineage() if node.tag == tag), None)
        if opener is not None:
            self.current = opener.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse_document(text):
    builder = TreeBuilder()
    builder.feed(text)
    builder.close()
    for mismatch in builder.mismatches:
        fail("0 마크업", "닫는 태그 불일치 %s" % mismatch)
    if builder.current is not builder.root:
        fail("0 마크업", "닫히지 않은 <%s>" % builder.current.tag)
    return builder.root


def brace_blocks(css):
    blocks = []
    depth = 0
    prelude_start = 0
    body_start = 0
    prelude = ""
    for index, char in enumerate(css):
        if char == "{":
            if depth == 0:
                prelude = css[prelude_start:index].strip()
                body_start = index + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                fail("0 CSS", "여는 괄호 없는 }")
                return blocks
            if depth == 0:
                blocks.append((prelude, css[body_start:index]))
                prelude_start = index + 1
    if depth != 0:
        fail("0 CSS", "닫히지 않은 { %d개" % depth)
    return blocks


def declarations(body):
    pairs = {}
    for item in body.split(";"):
        name, colon, value = item.partition(":")
        if colon:
            pairs[name.strip()] = " ".join(value.split())
    return pairs


class Rule:
    def __init__(self, media, selector, body):
        self.media = media
        self.selectors = [" ".join(part.split()) for part in selector.split(",")]
        self.decls = declarations(body)


def css_rules(css):
    rules = []
    for prelude, body in brace_blocks(css):
        if prelude.startswith("@media"):
            rules.extend(Rule(prelude, selector, inner) for selector, inner in brace_blocks(body))
        else:
            rules.append(Rule(None, prelude, body))
    return rules


def media_max_width(media):
    match = MAX_WIDTH.search(media or "")
    return float(match.group(1)) if match else None


def boundary_is(width, boundary):
    return width is not None and boundary - 1 < width < boundary


def row_name(row):
    names = row.find("app-name")
    return names[0].text() if names else "?"


def single(container, cls, where, check):
    found = container.find(cls)
    if len(found) != 1:
        fail(check, "%s: .%s %d개 (기대 1개)" % (where, cls, len(found)))
        return None
    return found[0]


def check_store_link(name, link):
    where = "%s 스토어 링크 %s" % (name, link.attrs.get("href"))
    check = "2 스토어 링크"
    if not (link.attrs.get("href") or "").startswith("https://"):
        fail(check, "%s: href가 https 주소가 아님" % where)
    if link.attrs.get("target") != NEW_TAB:
        fail(check, "%s: target=%r (기대 %r)" % (where, link.attrs.get("target"), NEW_TAB))
    if REQUIRED_REL not in (link.attrs.get("rel") or "").split():
        fail(check, "%s: rel=%r에 %s 없음" % (where, link.attrs.get("rel"), REQUIRED_REL))
    if link.aria_hidden():
        fail(check, "%s: 링크 또는 조상에 aria-hidden=true — 보조기술에서 사라진다" % where)
    if "tabindex" in link.attrs:
        fail(check, "%s: tabindex=%r — Tab 순서는 문서 순서를 따라야 한다" % (where, link.attrs["tabindex"]))

    label = single(link, "app-store-label", where, check)
    label_text = label.text() if label else ""
    if label is not None and not label_text:
        fail(check, "%s: 플랫폼 라벨이 비어 있음" % where)
    accessible_name = link.attrs.get("aria-label") or ""
    if not accessible_name:
        fail(check, "%s: aria-label 없음" % where)
    elif label_text and not accessible_name.casefold().startswith(label_text.casefold()):
        fail(check, "%s: aria-label %r가 보이는 라벨 %r로 시작하지 않음(WCAG 2.5.3)"
             % (where, accessible_name, label_text))
    if accessible_name and name.casefold() not in accessible_name.casefold():
        fail(check, "%s: aria-label %r에 앱 이름 %r 없음" % (where, accessible_name, name))

    arrow = single(link, "app-arrow", where, check)
    if arrow is not None:
        if arrow.attrs.get("aria-hidden") != "true":
            fail(check, "%s: 화살표 글리프에 aria-hidden=true 없음" % where)
        if arrow.text() != ARROW_GLYPH:
            fail(check, "%s: 화살표 글리프 %r (기대 %r)" % (where, arrow.text(), ARROW_GLYPH))
    return label_text


def check_multi_row(name, row):
    check = "1 행 구조"
    where = "%s 행(div)" % name
    if "app-row--multi" not in row.classes:
        fail(check, "%s: 링크 아닌 행에 app-row--multi 없음" % where)
    stores = single(row, "app-stores", where, check)
    if stores is None:
        return []
    if stores.aria_hidden():
        fail(check, "%s: .app-stores가 aria-hidden — 스토어 링크가 보조기술에서 사라진다" % where)
    entries = stores.find("app-store")
    not_links = [entry.tag for entry in entries if entry.tag != "a"]
    if not_links:
        fail(check, "%s: 링크 아닌 .app-store %s" % (where, not_links))
    links = [entry for entry in entries if entry.tag == "a"]
    if len(links) < MIN_STORES_PER_MULTI_ROW:
        fail(check, "%s: 스토어 링크 %d개 — 하나뿐이면 행 전체 링크(a.app-row)여야 한다" % (where, len(links)))
    return [(check_store_link(name, link), link.attrs.get("href"), link.attrs.get("aria-label"))
            for link in links]


def check_link_row(name, row):
    check = "1 행 구조"
    where = "%s 행(a)" % name
    if "app-row--multi" in row.classes:
        fail(check, "%s: 행 전체 링크에 app-row--multi" % where)
    if not row.attrs.get("href"):
        fail(check, "%s: href 없음" % where)
    nested = [el.attrs.get("href") for el in row.elements() if el.tag == "a"]
    if nested:
        fail(check, "%s: 링크 행 안에 링크 %s — 중첩 상호작용" % (where, nested))
    stores = single(row, "app-stores", where, check)
    if stores is None:
        return ""
    if stores.attrs.get("aria-hidden") != "true":
        fail(check, "%s: 장식 .app-stores에 aria-hidden=true 없음" % where)
    store = single(stores, "app-store", where, check)
    if store is None:
        return ""
    single(store, "app-arrow", where, check)
    label = single(store, "app-store-label", where, check)
    return label.text() if label else ""


def check_rows(apps):
    rows = apps.find("app-row")
    if not rows:
        fail("1 행 구조", "#%s에 .app-row 없음" % APPS_SECTION_ID)
    summary = {}
    for row in rows:
        name = row_name(row)
        if row.tag == "a":
            summary[name] = (row, check_link_row(name, row))
        elif row.tag == "div":
            summary[name] = (row, check_multi_row(name, row))
        else:
            fail("1 행 구조", "%s 행: <%s> (기대 <a> 또는 <div>)" % (name, row.tag))
    return summary


def check_housecast(summary):
    check = "3 HouseCast"
    if HOUSECAST_NAME not in summary:
        fail(check, "HouseCast 행 없음")
        return
    row, stores = summary[HOUSECAST_NAME]
    if row.tag != "div":
        fail(check, "HouseCast 행이 <%s> — 스토어가 둘인 행은 링크가 아니어야 한다" % row.tag)
        return
    if stores != HOUSECAST_STORES:
        fail(check, "스토어 링크 (라벨, href, aria-label) %s\n    기대 %s" % (stores, HOUSECAST_STORES))


def check_listentimer(summary):
    check = "4 ListenTimer"
    if LISTENTIMER_NAME not in summary:
        fail(check, "ListenTimer 행 없음")
        return
    row, label = summary[LISTENTIMER_NAME]
    if row.tag != "a":
        fail(check, "ListenTimer 행이 <%s> — 행 전체 링크여야 한다" % row.tag)
        return
    if row.attrs.get("href") != LISTENTIMER_HREF:
        fail(check, "href %r (기대 %r)" % (row.attrs.get("href"), LISTENTIMER_HREF))
    if label != LISTENTIMER_LABEL:
        fail(check, "화살표 아래 라벨 %r (기대 %r)" % (label, LISTENTIMER_LABEL))


def check_focus_order(apps):
    tabbed = ["<%s class=%r tabindex=%r>" % (el.tag, el.attrs.get("class"), el.attrs["tabindex"])
              for el in apps.elements() if "tabindex" in el.attrs]
    if tabbed:
        fail("5 포커스 순서", "#%s 안에 tabindex %s — Tab 순서는 문서 순서를 따라야 한다" % (APPS_SECTION_ID, tabbed))


def internal_target(url):
    path = url.split("#", 1)[0].split("?", 1)[0].lstrip("/")
    if not path or path.endswith("/"):
        path += "index.html"
    return REPO / path


def check_internal_targets(apps):
    for el in apps.elements():
        for attr in ("href", "src"):
            url = el.attrs.get(attr) or ""
            if url.startswith("/") and not url.startswith("//") and not internal_target(url).is_file():
                fail("6 내부 경로", "<%s %s=%r> → %s 없음" % (el.tag, attr, url, internal_target(url)))


def check_row_hover(rules):
    check = "7 hover"
    states = [selector for rule in rules for selector in rule.selectors if ROW_STATE.search(selector)]
    if not states:
        fail(check, "행 hover 규칙 없음 — 링크 행(a.app-row)은 hover 배경을 유지해야 한다")
    for selector in states:
        if len(ROW_STATE.findall(selector)) != len(LINK_ROW_STATE.findall(selector)):
            fail(check, "셀렉터 %r — 행 hover·포커스 배경은 링크 행(a.app-row)에만" % selector)

    inverted = set()
    for rule in rules:
        if rule.decls.get("background") == "var(--ink)" and rule.decls.get("color") == "var(--bg)":
            inverted.update(rule.selectors)
    for state in ("hover", "focus-visible"):
        selector = "a.app-store:%s .app-arrow" % state
        if selector not in inverted:
            fail(check, "%r 반전(background var(--ink) · color var(--bg)) 규칙 없음" % selector)


def media_groups(rules):
    groups = {}
    for rule in rules:
        if rule.media is not None:
            groups.setdefault(rule.media, []).append(rule)
    return groups


def arrow_below_meta(rule):
    rows = AREA_ROW.findall(rule.decls.get("grid-template-areas", ""))
    tokens = [row.split() for row in rows]
    arrow = next((i for i, row in enumerate(tokens) if "arrow" in row), None)
    meta = next((i for i, row in enumerate(tokens) if "meta" in row), None)
    return arrow is not None and meta is not None and arrow > meta and "app" not in tokens[arrow]


def check_breakpoints(rules):
    check = "8 분기점"
    groups = media_groups(rules)

    table_switch = [media for media, inner in groups.items()
                    if any(".index-head" in rule.selectors and rule.decls.get("display") == "none" for rule in inner)]
    if len(table_switch) != 1:
        fail(check, "표 머리(.index-head)를 숨기는 미디어 블록 %d개 (기대 1개)" % len(table_switch))
    for media in table_switch:
        if not boundary_is(media_max_width(media), TABLE_MIN_WIDTH):
            fail(check, "%s — 표는 %dpx 이상, 쌓기는 %dpx 미만이어야 한다"
                 % (media, TABLE_MIN_WIDTH, TABLE_MIN_WIDTH))

    stacked = [media for media, inner in groups.items() if any(arrow_below_meta(rule) for rule in inner)]
    if len(stacked) != 1:
        fail(check, "화살표 묶음을 상태 줄 아래로 내리는 미디어 블록 %d개 (기대 1개)" % len(stacked))
    for media in stacked:
        if not boundary_is(media_max_width(media), STORES_BESIDE_NAME_MIN_WIDTH):
            fail(check, "%s — 화살표 묶음은 %dpx 미만에서만 상태 줄 아래로 내려가야 한다"
                 % (media, STORES_BESIDE_NAME_MIN_WIDTH))
        for rule in groups[media]:
            outside = [selector for selector in rule.selectors if ".app-row--multi" not in selector]
            if outside:
                fail(check, "%s 안의 %s — 화살표가 두 개인 행(.app-row--multi)만 바꿔야 한다" % (media, outside))
        aligned = [rule for rule in groups[media]
                   if any(".app-stores" in selector for selector in rule.selectors)
                   and rule.decls.get("justify-content") == "flex-start"]
        if not aligned:
            fail(check, "%s — 내려간 화살표 묶음의 왼쪽 정렬(justify-content: flex-start) 없음" % media)


def main(argv=None):
    parser = argparse.ArgumentParser(description="pocketlabs.kr 홈 앱 목록 정합 검사기 — 저장소 루트에서 실행")
    parser.parse_args(argv)

    path = REPO / PAGE
    if not path.is_file():
        fail("0 페이지", "없음: %s" % PAGE)
    else:
        root = parse_document(path.read_text(encoding="utf-8"))
        apps = next((el for el in root.elements() if el.attrs.get("id") == APPS_SECTION_ID), None)
        if apps is None:
            fail("0 페이지", "#%s 없음" % APPS_SECTION_ID)
        else:
            summary = check_rows(apps)
            check_housecast(summary)
            check_listentimer(summary)
            check_focus_order(apps)
            check_internal_targets(apps)
        rules = css_rules("".join(el.text() for el in root.elements() if el.tag == "style"))
        check_row_hover(rules)
        check_breakpoints(rules)

    for line in failures:
        print("FAIL  %s" % line)
    print("\n검사 결과 — 실패 %d건" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
