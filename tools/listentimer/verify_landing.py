#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ListenTimer 랜딩 정합 검사기 — 랜딩 저장소 루트에서 실행, 실패 0이면 rc 0.

이 페이지의 위험은 "사람 눈에는 멀쩡한데 기계가 읽는 층(JSON-LD·hreflang·robots)만 어긋나는"
쪽이다. LLM 인용·검색 노출이 목적이라 그 층이 정본이므로, 아래 11개 검사를 게이트로 둔다.

사용:
    python3 tools/listentimer/verify_landing.py [--assets-optional]

`--assets-optional`은 이미지(⑥)만 경고로 낮춘다 — 캡처가 아직 배치되기 전(구현 창)에 쓰고,
자산 배치 뒤에는 플래그 없이 돌려야 통과로 친다.
"""
import argparse
import html as htmlmod
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def load_contract():
    """자산 계약(§1.2)의 단일 소스는 `derive_assets.py`다 — 경로로 직접 로드해 표를 공유한다.

    (검사기가 표를 복사해 가지면 파생기와 조용히 갈라져 "생성은 됐는데 검사는 통과"가 생긴다.)
    """
    path = Path(__file__).resolve().parent / "derive_assets.py"
    spec = importlib.util.spec_from_file_location("listentimer_derive_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT = load_contract()

REPO = Path.cwd()
PAGES = {
    "listentimer/index.html": "https://pocketlabs.kr/listentimer/en/",   # 루트 = en 본문 복사본
    "listentimer/en/index.html": "https://pocketlabs.kr/listentimer/en/",
    "listentimer/ko/index.html": "https://pocketlabs.kr/listentimer/ko/",
    "listentimer/ja/index.html": "https://pocketlabs.kr/listentimer/ja/",
}
ASSETS_ROOT = Path("listentimer/assets")

STORE_URL = "https://apps.apple.com/app/id6769309369"
STORE_URL_COUNT = 3  # 헤더 · 히어로 · 다운로드

# 구 세대 문안의 화석 — 하나라도 살아 있으면 1.3.2 현행화가 덜 끝난 것이다
BANNED_TOKENS = ["$2.99", "PT Coach", "3종", "Three character", "three voices"]
# 가격 숫자 금지 — 앱 내 링크가 3.1.1(외부 결제 유도)로 읽힐 여지를 원천 차단한다
PRICE_PATTERNS = [r"\$\d", r"₩\d", r"¥\d", r"USD \d"]

HREFLANG_EXPECTED = {
    "en": "https://pocketlabs.kr/listentimer/en/",
    "ko": "https://pocketlabs.kr/listentimer/ko/",
    "ja": "https://pocketlabs.kr/listentimer/ja/",
    "x-default": "https://pocketlabs.kr/listentimer/",
}
SECTION_IDS = ["top", "hero", "every-second", "facts", "features", "voices", "pro",
               "made-for", "faq", "download", "footer"]
FEATURE_IDS = ["f%d" % n for n in range(1, 13)]

ROBOTS_AGENTS = ["*", "OAI-SearchBot", "GPTBot", "ChatGPT-User",
                 "ClaudeBot", "Claude-User", "Claude-SearchBot", "PerplexityBot"]

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
XHTML_NS = "{http://www.w3.org/1999/xhtml}"

TAGS = re.compile(r"<[^>]+>")
BADGE = re.compile(r'<span class="lt-badge[^"]*">[^<]*</span>')

failures = []
warnings = []


def fail(check, message):
    failures.append("[%s] %s" % (check, message))


def warn(check, message):
    warnings.append("[%s] %s" % (check, message))


def plain(fragment):
    """HTML 조각 → 표시 텍스트 (PRO 뱃지 제거 → 태그 제거 → 엔티티 복원 → 공백 정리).

    JSON-LD를 만든 쪽과 **같은 규칙**이어야 FAQ 글자 동일 검사가 의미를 갖는다.
    """
    text = BADGE.sub("", fragment)
    text = TAGS.sub("", text)
    text = htmlmod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def section(text, sid):
    match = re.search(r'<section id="%s".*?</section>' % re.escape(sid), text, re.S)
    return match.group(0) if match else None


# ── ①②⑦⑧⑩⑪ 텍스트 층 검사 ────────────────────────────────────────────────
def check_text_layer(rel, text):
    for token in BANNED_TOKENS:
        if token in text:
            fail("1 구세대 문안", "%s: 금지 토큰 %r 발견" % (rel, token))

    scripts = re.findall(r"<script\b[^>]*>", text)
    non_ld = [s for s in scripts if 'type="application/ld+json"' not in s]
    if non_ld:
        fail("2 스크립트", "%s: ld+json 이외의 <script> %d개" % (rel, len(non_ld)))

    if "data-implementation-note" in text:
        fail("7 인계 속성", "%s: data-implementation-note가 남아 있음" % rel)

    for pattern in PRICE_PATTERNS:
        hits = re.findall(pattern, text)
        if hits:
            fail("8 가격 숫자", "%s: 패턴 %s %d건" % (rel, pattern, len(hits)))

    wide = re.findall(r"width:\s*\d{4,}px", text)
    if wide:
        fail("10 고정 폭", "%s: 4자리 이상 고정 폭 %d건" % (rel, len(wide)))
    for tag in re.findall(r"<img\b[^>]*>", text):
        if re.search(r"\s(?:width|height)=", tag):
            fail("10 img 속성", "%s: <img>에 width/height 속성 — %s" % (rel, tag[:90]))

    # 스토어프런트 세그먼트(/us/·/kr/·/jp/)가 남으면 다른 나라 방문자가 오배송된다 —
    # 페이지 안의 모든 형태가 규격 URL이어야 한다(JSON-LD installUrl 포함).
    urls = re.findall(r"https://apps\.apple\.com/\S*?id6769309369", text)
    bad = [u for u in urls if u != STORE_URL]
    if bad:
        fail("11 스토어 URL", "%s: 규격 밖 URL %s" % (rel, sorted(set(bad))))
    # 방문자가 누를 수 있는 링크는 정확히 3곳(헤더 · 히어로 · 다운로드)이다.
    # 전체 등장 횟수는 4회 — 나머지 1회는 JSON-LD의 installUrl(링크가 아님)이라 따로 센다.
    hrefs = re.findall(r'href="(https://apps\.apple\.com/\S*?id6769309369)"', text)
    if len(hrefs) != STORE_URL_COUNT:
        fail("11 스토어 URL", "%s: 스토어 링크 %d회 (기대 %d회)" % (rel, len(hrefs), STORE_URL_COUNT))


# ── ④ hreflang · canonical ─────────────────────────────────────────────────
def check_hreflang(rel, text, canonical_expected):
    found = dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', text))
    if found != HREFLANG_EXPECTED:
        fail("4 hreflang", "%s: %s (기대 %s)" % (rel, found, HREFLANG_EXPECTED))
    match = re.search(r'<link rel="canonical" href="([^"]+)">', text)
    if not match:
        fail("4 canonical", "%s: canonical 없음" % rel)
    elif match.group(1) != canonical_expected:
        fail("4 canonical", "%s: %s (기대 %s)" % (rel, match.group(1), canonical_expected))


# ── ⑤ 섹션 · 기능 앵커 ─────────────────────────────────────────────────────
def check_anchors(rel, text):
    ids = re.findall(r'\sid="([^"]+)"', text)
    for sid in SECTION_IDS:
        if sid not in ids:
            fail("5 섹션 id", "%s: id=%s 없음" % (rel, sid))
    for fid in FEATURE_IDS:
        if fid not in ids:
            fail("5 기능 앵커", "%s: id=%s 없음" % (rel, fid))


# ── ③ JSON-LD ──────────────────────────────────────────────────────────────
def check_jsonld(rel, text):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    if not match:
        fail("3 JSON-LD", "%s: ld+json 블록 없음" % rel)
        return
    raw = match.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail("3 JSON-LD", "%s: 파싱 실패 — %s" % (rel, exc))
        return

    graph = data.get("@graph", [])
    types = [node.get("@type") for node in graph]
    if types != ["Organization", "MobileApplication", "FAQPage"]:
        fail("3 JSON-LD", "%s: @graph 타입 %s" % (rel, types))
        return

    for banned in ("aggregateRating", "review"):
        if re.search(r'"%s"' % banned, raw):
            fail("3 JSON-LD", "%s: 금지 속성 %s 포함" % (rel, banned))

    app = graph[1]
    if len(app.get("featureList", [])) != 12:
        fail("3 JSON-LD", "%s: featureList %d개 (기대 12)"
             % (rel, len(app.get("featureList", []))))
    if app.get("softwareVersion") != "1.3.2":
        fail("3 JSON-LD", "%s: softwareVersion %s" % (rel, app.get("softwareVersion")))
    if app.get("installUrl") != STORE_URL:
        fail("3 JSON-LD", "%s: installUrl %s" % (rel, app.get("installUrl")))

    # 본문 F1~F12 h3 ↔ featureList 대조 (같은 추출 규칙)
    feats = section(text, "features")
    if feats:
        body_features = []
        for fid in FEATURE_IDS:
            art = re.search(r'<article id="%s".*?</article>' % fid, feats, re.S)
            if not art:
                continue
            heading = re.search(r"<h3[^>]*>(.*?)</h3>", art.group(0), re.S)
            if heading:
                body_features.append(plain(heading.group(1)))
        if body_features != app.get("featureList"):
            fail("3 JSON-LD", "%s: featureList가 본문 h3와 다름" % rel)

    # FAQ 11문항 — 본문 h3/p와 글자 동일
    faq_section = section(text, "faq")
    if faq_section is None:
        fail("3 JSON-LD", "%s: #faq 섹션 없음" % rel)
        return
    body_pairs = [(plain(q), plain(a)) for q, a in
                  re.findall(r"<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>", faq_section, re.S)]
    ld_pairs = [(item.get("name"), item.get("acceptedAnswer", {}).get("text"))
                for item in graph[2].get("mainEntity", [])]
    if len(body_pairs) != 11:
        fail("3 JSON-LD", "%s: 본문 FAQ %d문항 (기대 11)" % (rel, len(body_pairs)))
    if len(ld_pairs) != 11:
        fail("3 JSON-LD", "%s: FAQPage %d문항 (기대 11)" % (rel, len(ld_pairs)))
    for idx, pair in enumerate(zip(body_pairs, ld_pairs), start=1):
        body, structured = pair
        if body != structured:
            fail("3 JSON-LD", "%s: FAQ %d번이 본문과 불일치\n    본문 Q: %s\n    LD   Q: %s"
                 % (rel, idx, body[0], structured[0]))


# ── ⑥ 이미지 자산 ──────────────────────────────────────────────────────────
def check_assets(assets_optional):
    report = warn if assets_optional else fail
    contract = CONTRACT.expected_assets()
    for rel in sorted(contract):
        width, height, has_webp = contract[rel]
        png = ASSETS_ROOT / ("%s.png" % rel)
        if not png.is_file():
            report("6 자산", "없음: %s" % png)
            continue
        actual_w, actual_h, color_type = CONTRACT.png_header(png)
        if (actual_w, actual_h) != (width, height):
            report("6 자산", "%s 치수 %dx%d (기대 %dx%d)"
                   % (png, actual_w, actual_h, width, height))
        if color_type in CONTRACT.ALPHA_COLOR_TYPES:
            report("6 자산", "%s 알파 채널 포함" % png)
        if has_webp and not (ASSETS_ROOT / ("%s.webp" % rel)).is_file():
            report("6 자산", "webp 쌍 없음: %s.webp" % rel)

    # 페이지가 참조하는 경로가 계약표 밖이면(오탈자 등) 배포 뒤 404가 된다 — 자산 유무와 무관한 결함
    for rel in PAGES:
        path = REPO / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for src in re.findall(r'(?:src|srcset)="\.{1,2}/assets/([^"]+)"', text):
            stem = re.sub(r"\.(png|webp)$", "", src)
            if stem not in contract:
                fail("6 자산", "%s: 계약표에 없는 경로 참조 — assets/%s" % (rel, src))


# ── ⑨ robots.txt · sitemap.xml ─────────────────────────────────────────────
def check_site_files():
    robots = REPO / "robots.txt"
    if not robots.is_file():
        fail("9 robots", "robots.txt 없음")
    else:
        text = robots.read_text(encoding="utf-8")
        agents = re.findall(r"^User-agent:\s*(\S+)\s*$", text, re.M)
        for agent in ROBOTS_AGENTS:
            if agent not in agents:
                fail("9 robots", "User-agent %s 누락" % agent)
        if not re.search(r"^Sitemap:\s*https://pocketlabs\.kr/sitemap\.xml\s*$", text, re.M):
            fail("9 robots", "Sitemap: 줄 없음/불일치")

    sitemap = REPO / "sitemap.xml"
    if not sitemap.is_file():
        fail("9 sitemap", "sitemap.xml 없음")
        return
    try:
        root = ET.parse(sitemap).getroot()
    except ET.ParseError as exc:
        fail("9 sitemap", "XML 파싱 실패 — %s" % exc)
        return
    urls = root.findall("%surl" % SITEMAP_NS)
    if len(urls) != 4:
        fail("9 sitemap", "<url> %d개 (기대 4)" % len(urls))
    links = root.findall(".//%slink" % XHTML_NS)
    if len(links) != 16:
        fail("9 sitemap", "xhtml:link %d개 (기대 16 = url 4 × hreflang 4)" % len(links))
    locs = [u.findtext("%sloc" % SITEMAP_NS) for u in urls]
    expected_locs = ["https://pocketlabs.kr/listentimer/",
                     "https://pocketlabs.kr/listentimer/en/",
                     "https://pocketlabs.kr/listentimer/ko/",
                     "https://pocketlabs.kr/listentimer/ja/"]
    if sorted(locs) != sorted(expected_locs):
        fail("9 sitemap", "loc 목록 %s" % locs)
    for url in urls:
        pairs = {link.get("hreflang"): link.get("href")
                 for link in url.findall("%slink" % XHTML_NS)}
        if pairs != HREFLANG_EXPECTED:
            fail("9 sitemap", "%s의 hreflang %s" % (url.findtext("%sloc" % SITEMAP_NS), pairs))


def main(argv=None):
    parser = argparse.ArgumentParser(description="ListenTimer 랜딩 정합 검사기")
    parser.add_argument("--assets-optional", action="store_true",
                        help="이미지 자산 검사를 경고로 낮춘다(캡처 배치 전용)")
    args = parser.parse_args(argv)

    for rel in PAGES:
        path = REPO / rel
        if not path.is_file():
            fail("0 페이지", "없음: %s" % rel)
            continue
        text = path.read_text(encoding="utf-8")
        check_text_layer(rel, text)
        check_hreflang(rel, text, PAGES[rel])
        check_anchors(rel, text)
        check_jsonld(rel, text)

    check_assets(args.assets_optional)
    check_site_files()

    for line in warnings:
        print("WARN  %s" % line)
    for line in failures:
        print("FAIL  %s" % line)
    print("\n검사 결과 — 실패 %d건 · 경고 %d건" % (len(failures), len(warnings)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
