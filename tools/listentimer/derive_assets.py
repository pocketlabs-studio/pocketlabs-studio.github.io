#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ListenTimer 랜딩 이미지 파생기 — 캡처 raw → `listentimer/assets/` (png + webp 쌍).

랜딩 페이지가 쓰는 자산은 **전부 이 스크립트의 산출물**이다. 손으로 만든 파일이 섞이면
치수·알파·마스터링이 조용히 어긋나므로, 자산 계약(아래 표)을 이 파일 하나가 소유한다.

사용:
    python3 tools/listentimer/derive_assets.py \\
        --iphone-raw   <…/screenshots/iphone69> \\
        --watch-raw    <…/screenshots/watch> \\
        --store-output <…/composite/output> \\
        --icon         <…/AppIcon-1024.png> \\
        --out          listentimer/assets

설계 원칙
- **조용한 폴백 금지**: 원본이 없거나 치수가 어긋나면 그 자리에서 실패한다(부분 산출 금지).
- **멱등**: `-strip`으로 메타데이터(생성 시각 등)를 털어 재실행 시 바이트가 같다.
- **알파 금지**: PNG24로 강제하고, 생성 뒤 IHDR을 직접 읽어 컬러타입을 재확인한다
  (앱 스토어 캡처 계열에서 RGBA가 섞여 들어온 전례가 있다).
"""
import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

LANGS = ("en", "ko", "ja")

# ── 자산 계약 (§1.2) ────────────────────────────────────────────────────────
# iPhone 캡처(1320×2868) → 50% 축소. (출력 이름, 원본 파일명)
IPHONE_SLOTS = [
    ("S1_main_idle", "09_timer_idle.png"),
    ("S2_timer_running", "02_timer_running_single.png"),
    ("S3_character_sheet", "03_character_sheet.png"),
    ("S4_routine_edit", "04_routine_edit.png"),
    ("S5_records", "06_records_premium.png"),
    ("S6_lockscreen", "08_lockscreen_la.png"),
    ("S6_home_widget", "07_home_widget.png"),
    ("S7_interval_settings", "05_settings_interval.png"),
]
IPHONE_SRC_SIZE = (1320, 2868)
IPHONE_OUT_SIZE = (660, 1434)

# Watch 캡처 — 원본 그대로(축소 없음)
WATCH_SLOT = ("S8_watch", "02_routine_work.png")
WATCH_SIZE = (396, 484)

# 라이프스타일 실사(ASC 라이브와 동일 원본, 1290×2796) → 800×1734 강제 리샘플
LIFESTYLE_SLOTS = [
    ("yoga", "01_yoga_core.png"),
    ("pullup", "02_pullup_hold.png"),
]
LIFESTYLE_SRC_SIZE = (1290, 2796)
LIFESTYLE_OUT_SIZE = (800, 1734)

ICON_SIZE = (512, 512)          # app_icon.png — png만(webp 쌍 없음)
OG_SIZE = (1200, 630)           # og_1200x630.png — 검정 바탕 + 아이콘 중앙, 글자 없음
OG_BACKGROUND = "#000000"

WEBP_QUALITY = "84"
WEBP_METHOD = "6"


def expected_assets():
    """랜딩이 참조하는 전 자산의 계약표 — {확장자 없는 상대경로: (너비, 높이, webp 쌍 여부)}.

    `verify_landing.py`가 이 표를 그대로 import해서 검사하므로 자산 계약의 단일 소스다.
    """
    out = {}
    for lang in LANGS:
        for name, _src in IPHONE_SLOTS:
            out["%s/%s" % (lang, name)] = (IPHONE_OUT_SIZE[0], IPHONE_OUT_SIZE[1], True)
        out["%s/%s" % (lang, WATCH_SLOT[0])] = (WATCH_SIZE[0], WATCH_SIZE[1], True)
        for name, _src in LIFESTYLE_SLOTS:
            out["lifestyle/%s/%s" % (lang, name)] = (LIFESTYLE_OUT_SIZE[0], LIFESTYLE_OUT_SIZE[1], True)
    out["app_icon"] = (ICON_SIZE[0], ICON_SIZE[1], False)
    out["og_1200x630"] = (OG_SIZE[0], OG_SIZE[1], False)
    return out


# ── PNG IHDR 직접 판독 ──────────────────────────────────────────────────────
# 외부 도구(identify)의 출력 파싱에 의존하지 않는다 — 헤더는 고정 오프셋이라 직접 읽는 쪽이
# 빠르고, "도구가 없어서 검사를 건너뛰는" 조용한 통과가 생기지 않는다.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ALPHA_COLOR_TYPES = {4, 6}  # 4=Gray+Alpha, 6=RGBA


def png_header(path):
    """PNG의 (너비, 높이, 컬러타입)을 IHDR에서 읽는다."""
    with open(path, "rb") as f:
        head = f.read(26)
    if len(head) < 26 or head[:8] != PNG_MAGIC:
        raise SystemExit("[derive] PNG이 아닙니다: %s" % path)
    width, height, _depth, color_type = struct.unpack(">IIBB", head[16:26])
    return width, height, color_type


def assert_png(path, size, label):
    """산출물 검증 — 치수 일치 + 알파 채널 없음."""
    width, height, color_type = png_header(path)
    if (width, height) != tuple(size):
        raise SystemExit("[derive] %s 치수 불일치: %dx%d (기대 %dx%d) — %s"
                         % (label, width, height, size[0], size[1], path))
    if color_type in ALPHA_COLOR_TYPES:
        raise SystemExit("[derive] %s 알파 채널 포함(color_type=%d): %s" % (label, color_type, path))


def require(path, label):
    """원본 부재는 즉시 실패 — 부분 산출로 넘어가지 않는다."""
    if not Path(path).is_file():
        raise SystemExit("[derive] 원본 없음(%s): %s" % (label, path))
    return Path(path)


def run(cmd):
    """외부 도구 실행 — 실패 시 stderr를 그대로 올리고 중단한다."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("[derive] 명령 실패(rc=%d): %s\n%s"
                         % (proc.returncode, " ".join(cmd), proc.stderr.strip()))


def make_webp(png_path):
    """png과 짝이 되는 webp 생성 — `<picture>`의 첫 후보다."""
    webp_path = png_path.with_suffix(".webp")
    run(["cwebp", "-quiet", "-q", WEBP_QUALITY, "-m", WEBP_METHOD,
         str(png_path), "-o", str(webp_path)])
    if not webp_path.is_file():
        raise SystemExit("[derive] webp 생성 실패: %s" % webp_path)
    return webp_path


def derive(args):
    out_root = Path(args.out)
    iphone_raw = Path(args.iphone_raw)
    watch_raw = Path(args.watch_raw)
    store_output = Path(args.store_output)
    icon_src = require(args.icon, "아이콘")

    made = []

    # 1) 아이콘 512 — OG 카드의 합성 소스이기도 해서 가장 먼저 만든다
    icon_out = out_root / "app_icon.png"
    icon_out.parent.mkdir(parents=True, exist_ok=True)
    run(["magick", str(icon_src), "-resize", "%dx%d" % ICON_SIZE, "-strip", "PNG24:%s" % icon_out])
    assert_png(icon_out, ICON_SIZE, "app_icon")
    made.append(icon_out)

    # 2) OG 카드 — 검정 바탕 + 아이콘 중앙(글자 없음 · 3언어 공용)
    og_out = out_root / "og_1200x630.png"
    run(["magick", "-size", "%dx%d" % OG_SIZE, "xc:%s" % OG_BACKGROUND, str(icon_out),
         "-gravity", "center", "-composite", "-strip", "PNG24:%s" % og_out])
    assert_png(og_out, OG_SIZE, "og_1200x630")
    made.append(og_out)

    for lang in LANGS:
        lang_dir = out_root / lang
        lang_dir.mkdir(parents=True, exist_ok=True)

        # 3) iPhone 스크린샷 8종 — 1320×2868 → 660×1434 (정확히 50%)
        for name, src_name in IPHONE_SLOTS:
            src = require(iphone_raw / lang / src_name, "iPhone raw %s/%s" % (lang, src_name))
            width, height, _ct = png_header(src)
            if (width, height) != IPHONE_SRC_SIZE:
                raise SystemExit("[derive] iPhone raw 치수 불일치 %dx%d (기대 %dx%d): %s"
                                 % (width, height, IPHONE_SRC_SIZE[0], IPHONE_SRC_SIZE[1], src))
            dst = lang_dir / ("%s.png" % name)
            run(["magick", str(src), "-resize", "50%", "-strip", "PNG24:%s" % dst])
            assert_png(dst, IPHONE_OUT_SIZE, "%s/%s" % (lang, name))
            made.append(dst)
            make_webp(dst)

        # 4) Watch 스크린샷 — 396×484 원본 그대로 복사(축소 없음) + 무알파 확인
        src = require(watch_raw / lang / WATCH_SLOT[1], "Watch raw %s" % lang)
        dst = lang_dir / ("%s.png" % WATCH_SLOT[0])
        shutil.copyfile(src, dst)
        assert_png(dst, WATCH_SIZE, "%s/%s" % (lang, WATCH_SLOT[0]))
        made.append(dst)
        make_webp(dst)

        # 5) 라이프스타일 실사 2종 — 1290×2796 → 800×1734 강제(비율 미세 차이는 리샘플로 흡수)
        life_dir = out_root / "lifestyle" / lang
        life_dir.mkdir(parents=True, exist_ok=True)
        for name, src_name in LIFESTYLE_SLOTS:
            src = require(store_output / lang / src_name, "라이프스타일 %s/%s" % (lang, src_name))
            width, height, _ct = png_header(src)
            if (width, height) != LIFESTYLE_SRC_SIZE:
                raise SystemExit("[derive] 라이프스타일 원본 치수 불일치 %dx%d (기대 %dx%d): %s"
                                 % (width, height, LIFESTYLE_SRC_SIZE[0], LIFESTYLE_SRC_SIZE[1], src))
            dst = life_dir / ("%s.png" % name)
            run(["magick", str(src), "-resize", "%dx%d!" % LIFESTYLE_OUT_SIZE,
                 "-strip", "PNG24:%s" % dst])
            assert_png(dst, LIFESTYLE_OUT_SIZE, "lifestyle/%s/%s" % (lang, name))
            made.append(dst)
            make_webp(dst)

    # 6) 계약표 대조 — 표에 있는데 안 만들어진 파일이 있으면 실패
    missing = []
    for rel, spec in expected_assets().items():
        png = out_root / ("%s.png" % rel)
        if not png.is_file():
            missing.append(str(png))
            continue
        assert_png(png, (spec[0], spec[1]), rel)
        if spec[2] and not (out_root / ("%s.webp" % rel)).is_file():
            missing.append(str(out_root / ("%s.webp" % rel)))
    if missing:
        raise SystemExit("[derive] 계약표 대비 누락:\n  " + "\n  ".join(missing))

    print("[derive] png %d개 · webp %d개 생성 완료 → %s"
          % (len(made), sum(1 for s in expected_assets().values() if s[2]), out_root))


def main(argv=None):
    parser = argparse.ArgumentParser(description="ListenTimer 랜딩 이미지 파생기")
    parser.add_argument("--iphone-raw", required=True, help="iPhone 캡처 루트 (하위에 en/ko/ja)")
    parser.add_argument("--watch-raw", required=True, help="Watch 캡처 루트 (하위에 en/ko/ja)")
    parser.add_argument("--store-output", required=True,
                        help="라이프스타일 합성 출력 루트 (하위에 en/ko/ja)")
    parser.add_argument("--icon", required=True, help="AppIcon-1024.png 경로")
    parser.add_argument("--out", required=True, help="출력 루트 (listentimer/assets)")
    derive(parser.parse_args(argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
