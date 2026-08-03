import re
import hashlib
import json
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


GOOD_PATTERNS = ("tốt", "okie")
BAD_PATTERNS = ("chưa tốt", "kém", "ảnh hưởng", "lỗi", "thiếu")
URL_PATTERN = re.compile(r"https?://[^\s)]+")
COLUMN_SPLIT_PATTERN = re.compile(r"\s{2,}")

GROUP_KEYWORDS = {
    "GSC": (
        "google search console",
        "google search consolve",
        "crawl",
        "lập chỉ mục",
        "index",
        "excluded",
        "trang có lệnh chuyển hướng",
        "thay thế có thẻ chính tắc",
        "không tìm thấy (404)",
        "đã thu thập dữ liệu",
        "đã phát hiện thấy",
        "noindex",
        "robots.txt",
        "máy chủ",
        "5xx",
        "4xx",
        "bị chặn bằng tệp",
    ),
    "Sitemap": ("sitemap", "xml sitemap"),
    "Robots": ("robots.txt", "robot.txt"),
    "Speed": ("pagespeed", "site speed", "tốc độ", "page caching"),
    "Onpage": (
        "meta",
        "title",
        "heading",
        "h1",
        "canonical",
        "onpage",
        "schema",
        "structure data",
        "semantic markup",
    ),
    "Images": ("image", "hình ảnh", "alt"),
    "Video": ("video",),
    "Mobile": ("mobile",),
    "Security": ("bảo mật", "security", "https", "certificate", "response code", "disavow", "server key"),
    "International": ("hreflang", "international", "geo parameters", "self-referential", "html lang"),
}
STATUS_HINTS = (
    "chưa tốt",
    "tốt",
    "okie",
    "kém",
    "ảnh hưởng",
    "không ảnh hưởng",
)
SECTION_HEADERS = {
    "GSC": ("google search consolve", "google search console"),
    "Sitemap": ("sitemap",),
    "Robots": ("robots.txt", "robot.txt"),
    "Speed": ("site speed", "pagespeed"),
    "Security": ("response code", "dịch chuyển https", "certificate (xác thực)", "website"),
    "Onpage": ("onpage", "meta tags", "semantic markup"),
    "Images": ("images",),
    "Video": ("video",),
    "Mobile": ("mobile",),
    "International": ("international",),
    "General": ("các lỗi khác",),
}
STATUS_SCORES = {
    "needs_fix": 70,
    "unknown": 30,
    "good": 0,
}
GROUP_SCORES = {
    "GSC": 20,
    "Onpage": 18,
    "Sitemap": 16,
    "Robots": 14,
    "Speed": 14,
    "Security": 12,
    "Mobile": 10,
    "Images": 8,
    "Video": 8,
    "International": 10,
    "General": 5,
}
GROUP_OWNERS = {
    "GSC": "SEO Lead",
    "Onpage": "Content SEO",
    "Sitemap": "Tech SEO",
    "Robots": "Tech SEO",
    "Speed": "Web Dev",
    "Security": "DevOps",
    "Mobile": "Web Dev",
    "Images": "Content Team",
    "Video": "Content Team",
    "International": "SEO Lead",
    "General": "SEO Team",
}
GROUP_ETA_DAYS = {
    "GSC": 3,
    "Onpage": 5,
    "Sitemap": 2,
    "Robots": 2,
    "Speed": 10,
    "Security": 7,
    "Mobile": 7,
    "Images": 5,
    "Video": 5,
    "International": 5,
    "General": 7,
}
GROUP_SOLUTIONS = {
    "GSC": "Fix index coverage, remove redirect chains, and prioritize crawlable canonical URLs.",
    "Onpage": "Update title/meta/H1 structure and improve heading consistency per template.",
    "Sitemap": "Keep only valid XML sitemaps, remove redundant sitemaps, and resubmit clean index.",
    "Robots": "Update robots.txt to block low-value paths and keep sitemap declaration clean.",
    "Speed": "Optimize Core Web Vitals, compress assets, and remove render-blocking resources.",
    "Security": "Ensure HTTPS, valid certificates, and stable server response codes.",
    "Mobile": "Fix mobile UX and performance issues impacting indexing and engagement.",
    "Images": "Compress heavy images and add relevant ALT text for missing cases.",
    "Video": "Fix video embed/indexing setup and add supporting textual context.",
    "International": "Add correct hreflang/html lang and self-referential canonicals.",
    "General": "Review issue manually and assign to the proper SEO/Dev owner.",
}
GROUP_REFERENCES = {
    "GSC": "https://support.google.com/webmasters/answer/7440203",
    "Onpage": "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
    "Sitemap": "https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap",
    "Robots": "https://developers.google.com/search/docs/crawling-indexing/robots/intro",
    "Speed": "https://web.dev/vitals/",
    "Security": "https://developers.google.com/search/docs/crawling-indexing/https",
    "Mobile": "https://developers.google.com/search/mobile-sites/",
    "Images": "https://developers.google.com/search/docs/appearance/google-images",
    "Video": "https://developers.google.com/search/docs/appearance/video",
    "International": "https://developers.google.com/search/docs/specialty/international",
    "General": "https://developers.google.com/search/docs",
}

# Giải pháp gợi ý (tiếng Việt) — cột GIẢI PHÁP
GROUP_SOLUTIONS_VI = {
    "GSC": "Rà soát coverage/index trong GSC, rút gọn chuỗi redirect, chuẩn hóa canonical để Google crawl ổn định. "
    "Ví dụ: GSC → Cài đặt → chọn đúng property (https://www.tenmien.com/ hoặc sc-domain:tenmien.com) → Lập chỉ mục → xuất CSV theo từng «Lý do».",
    "Onpage": "Chỉnh title, meta description, cấu trúc H1–H2 đồng nhất theo template.",
    "Sitemap": "Giữ sitemap XML hợp lệ, bỏ sitemap thừa/lỗi, gửi lại index sạch trong GSC.",
    "Robots": "Cập nhật robots.txt: chặn path kém giá trị, khai báo dòng Sitemap đúng.",
    "Speed": "Cải thiện Core Web Vitals, nén ảnh/CSS/JS, giảm render-blocking.",
    "Security": "Đảm bảo HTTPS, chứng chỉ hợp lệ, mã phản hồi máy chủ ổn định. "
    "Ví dụ: curl -I https://tenmien.com phải thấy HTTP/2 200; curl -I http://tenmien.com phải 301 Location: https://… (không để 200 trên HTTP).",
    "Mobile": "Tối ưu UX và tốc độ mobile, tránh layout/ads cản trở người dùng.",
    "Images": "Nén ảnh nặng, bổ sung alt mô tả liên quan nội dung.",
    "Video": "Chuẩn hóa embed/video schema, thêm ngữ cảnh text hỗ trợ index.",
    "International": "Bổ sung hreflang/lang đúng, self-referential canonical.",
    "General": "Phân công SEO/Dev xử lý theo từng hạng mục Technical-SEO.txt.",
}

# Khớp chuỗi dài trước — GIẢI PHÁP cụ thể theo từng dòng GSC / checklist (tiếng Việt)
_CHECKLIST_SOLUTION_OVERRIDES_RAW: list[tuple[str, str]] = [
    (
        "Đã thu thập dữ liệu – hiện chưa được lập chỉ mục",
        "Trong GSC → Lập chỉ mục → chọn hạng mục «Đã thu thập dữ liệu – hiện chưa được lập chỉ mục» → xuất CSV mẫu 15–20 URL. "
        "Mở URL Inspection từng URL: kiểm tra canonical đích, soft-404, nội dung trùng SERP hoặc thin content. "
        "Sửa: gộp trùng lặp (301 hoặc noindex đúng bản chính), bổ sung nội dung độc quyền/H1–FAQ, nội bộ hóa từ trang có thứ hạng; "
        "sau đó «Yêu cầu lập chỉ mục» cho URL đã chỉnh và theo dõi 2–4 tuần.",
    ),
    (
        "Đã phát hiện thấy – hiện chưa được lập chỉ mục",
        "Google đã biết URL nhưng chưa crawl đủ ưu tiên. Trong báo cáo GSC, xuất danh sách URL thuộc hạng mục này; "
        "đặt liên kết nội bộ trực tiếp từ trang chủ / menu / bài pillar (anchor tự nhiên), bỏ orphan. "
        "Kiểm tra robots meta/X-Robots-Tag, chuỗi redirect dài, và tốc độ máy chủ (5xx/timeout). "
        "Đảm bảo URL nằm trong sitemap chỉ một lần (200), không chặn robots.txt; cải thiện chất lượng trang (duplicate/thin) rồi dùng «Yêu cầu lập chỉ mục» cho mẫu quan trọng.",
    ),
    (
        "Bị loại trừ bởi thẻ 'noindex'",
        "Xuất danh sách URL từ GSC cho hạng mục noindex. Với từng URL: View Source hoặc tab «Coverage» trong URL Inspection, tìm `<meta name=\"robots\" content=\"noindex\"` hoặc header `X-Robots-Tag: noindex`. "
        "Nếu trang cần được index: gỡ noindex trong theme/template (WordPress: Settings → Reading bỏ chặn), plugin SEO, hoặc rule nginx/Cloudflare; deploy và «Kiểm tra URL trực tiếp» rồi «Yêu cầu lập chỉ mục». "
        "Giữ noindex chỉ cho thank-you, cart, bản nháp, trang lọc trùng.",
    ),
    (
        "Trang thay thế có thẻ chính tắc thích hợp",
        "Đây thường là URL trùng/bản phụ mà Google gộp theo canonical. Mở từng URL trong báo cáo: xác nhận thẻ `<link rel=\"canonical\"` trỏ đúng bản chính (self hoặc bản gốc), không đổi canonical theo session/UTM. "
        "Chuẩn hóa internal link + sitemap chỉ chứa bản được index; tránh hai canonical khác nhau giữa AMP/mobile.",
    ),
    (
        "Trang có lệnh chuyển hướng",
        "Trong GSC → Lập chỉ mục → «Trang có lệnh chuyển hướng» → xuất danh sách URL. Với mỗi URL dùng `curl -I` hoặc công cụ redirect chain: ghi lại mã (301/302/meta refresh). "
        "Chuẩn hóa còn tối đa một bước 301 tới URL canonical cuối; sửa internal link và sitemap trỏ thẳng URL đích; bỏ chuỗi A→B→C và redirect vòng. "
        "Ưu tiên URL đích trả 200, có canonical self.",
    ),
    (
        "bị chặn bằng tệp robots.txt",
        "Mở báo cáo chi tiết trong GSC → xuất URL. Với từng URL: kiểm tra `robots.txt` tại gốc host — rule `Disallow` có chặn đường dẫn đó không (kể cả wildcard). "
        "Nếu trang cần index: nới Disallow (không chặn nhầm /category/, /product/), hoặc thêm rule Allow cụ thể; CDN/WAF đôi khi phục robots động — đối chiếu «Kiểm tra URL trực tiếp » trong GSC. "
        "Tránh chặn CSS/JS quan trọng cho render.",
    ),
    (
        "Không tìm thấy (404)",
        "Xuất danh sách URL 404 từ GSC. Với mỗi URL: nếu đã chuyển nội dung → 301 sang URL mới; nếu không còn → giữ 410/404 và gỡ mọi internal link trỏ tới (Search & replace trong CMS). "
        "Đảm bảo sitemap không còn chứa URL chết; dùng báo cáo «Liên kết» trong GSC để tìm nguồn trỏ tới.",
    ),
    (
        "Bị chặn do một vấn đề 4xx khác",
        "Xuất URL từ GSC; kiểm tra mã thực (401/403/407…) bằng `curl -I` và User-Agent Googlebot. "
        "Điều chỉnh auth/Basic Auth/WAF, CDN «Hotlink», hoặc rule nginx không áp nhầm cho bot; đảm bảo URL công khai trả 200 cho Googlebot khi cần index.",
    ),
    (
        "Lỗi máy chủ (5xx)",
        "Theo dõi URL trong báo cáo; kiểm tra log server, PHP-FPM, DB timeout, plugin WordPress, cron spike. "
        "Giảm lỗi tạm thời (502/503): scale hosting, cache, tách DB; sau khi ổn định dùng URL Inspection «Kiểm tra lại».",
    ),
    (
        "Bị chặn do quyền truy cập bị cấm (403)",
        "Lấy URL từ GSC; mở trình duyệt ẩn danh và curl: xác nhận 403 cho Googlebot-Desktop/Mobile. "
        "Kiểm tra WAF, rule IP, Basic Auth, plugin bảo mật, và file `.htaccess`/nginx `deny` — mở quyền đọc cho bot hoặc trả 401 có chủ đích khi thật sự private. "
        "Đảm bảo trang công khai trả 200 và không nằm trong robots.txt Disallow nhầm.",
    ),
    (
        "Số lượng lỗi nhiều trong phần Lập chỉ mục",
        "Vào GSC → Lập chỉ mục: lần lượt xử lý từng «Lý do» có số lượng lớn (redirect, noindex, 404, robots…), xuất URL mẫu cho từng lý do. "
        "Lập bảng theo dõi: loại lỗi → nguyên nhân kỹ thuật → owner → ngày sửa → xác thực lại trong GSC. Ưu tiên lỗi do site (Website) trước lỗi «Hệ thống Google».",
    ),
    (
        "Số lượng lớn về Excluded",
        "Mở báo cáo «Trang không được lập chỉ mục» trong GSC, sắp xếp theo số URL. "
        "Nhóm theo lý do (redirect, noindex, robots, 404…), xuất CSV từng nhóm, gán sprint Technical SEO — không chỉnh số tay trong file checklist; cập nhật `data/gsc_indexing_counts.json` sau mỗi lần đồng bộ số liệu GSC.",
    ),
    (
        "Tất cả các trang đã redirect 301 từ HTTP về HTTPS đúng chuẩn hay chưa?",
        "Kiểm tra từng biến thể host: `curl -I http://domain` và `http://www.domain` — bắt buộc trả 301 (hoặc 308) với header `Location: https://...` tương ứng; tránh 302 tạm thời cho chuyển đổi vĩnh viễn. "
        "Trong nginx: `return 301 https://$host$request_uri;` — Apache: `Redirect 301 / https://...`. WordPress: cấu hình «Site Address» là https + plugin ép SSL hoặc rule hosting. "
        "Sau khi sửa: dùng GSC URL Inspection với URL http — phải thấy redirect sang https; kiểm tra không tạo chuỗi redirect dài (http→www→https). "
        "Tài liệu: https://developers.google.com/search/docs/crawling-indexing/https",
    ),
    (
        "Kiểm tra loại giao thức chính mà trang web đang sử dụng (HTTP hay HTTPS)?",
        "Cách làm cụ thể: (1) Mở trang chủ bằng Chrome/Edge — nếu thanh địa chỉ có ổ khóa và URL bắt đầu bằng https:// thì người dùng đang truy cập qua TLS. Bấm ổ khóa → «Kết nối an toàn» để xem chứng chỉ (CA, ngày hết hạn). "
        "(2) F12 → tab Network → tải lại trang — chọn request document: cột Scheme/Protocol phải là https; nếu có tài nguyên (css/js/font) còn http:// thì ghi lại URL đó (mixed content). "
        "(3) Trên máy bạn: `curl -I https://tenmien.com` — dòng đầu nên là HTTP/2 200 hoặc HTTP/1.1 200; thử thêm `curl -I http://tenmien.com` — phải 301/302 sang https (nếu vẫn 200 trên HTTP thì site chưa ép HTTPS). "
        "(4) Nếu chưa có HTTPS: cài chứng chỉ (Let's Encrypt / CA hosting), bật TLS trên nginx/Apache/IIS hoặc Cloudflare «Full (strict)», rồi redirect 301 toàn site http→https. "
        "Chụp màn hình thanh địa chỉ + Network (hoặc kết quả curl) đưa vào báo cáo. Tài liệu Google: https://developers.google.com/search/docs/crawling-indexing/https",
    ),
]

CHECKLIST_SOLUTION_OVERRIDES_VI: list[tuple[str, str]] = sorted(
    _CHECKLIST_SOLUTION_OVERRIDES_RAW,
    key=lambda pair: len(pair[0]),
    reverse=True,
)

# Cột HIỆN TRẠNG (từ status checklist)
STATUS_LABEL_VI = {
    "needs_fix": "Cần xử lý",
    "good": "Đạt / tốt",
    "unknown": "Chưa rõ",
}

# Quét tự động — độ nghiêm trọng → hiển thị
SEVERITY_LABEL_VI = {
    "high": "Cao",
    "medium": "Trung bình",
    "low": "Thấp",
}

# Thứ tự hiển thị theo checklist Technical SEO mong muốn
GROUP_DISPLAY_ORDER = [
    "GSC",
    "Security",      # WEBSITE / HTTPS / bảo mật / response
    "Sitemap",
    "Robots",
    "Images",
    "Video",
    "Speed",         # Desktop / Site speed
    "Onpage",
    "Mobile",
    "International",
    "General",
]

GROUP_DISPLAY_LABEL_VI = {
    "GSC": "GOOGLE SEARCH CONSOLE",
    "Security": "WEBSITE / HTTPS",
    "Sitemap": "SITEMAP",
    "Robots": "ROBOTS.TXT",
    "Images": "IMAGES",
    "Video": "VIDEO",
    "Speed": "SITE SPEED (DESKTOP/MOBILE)",
    "Onpage": "ONPAGE",
    "Mobile": "MOBILE",
    "International": "INTERNATIONAL",
    "General": "KHÁC",
}

_ALLOWED_EVIDENCE_SRC_PREFIX = "/static/reports/"


def _load_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def gsc_indexing_counts_file_path(project_root: Path | None = None) -> Path:
    root = project_root or _PROJECT_ROOT
    return root / "data" / "gsc_indexing_counts.json"


def read_gsc_indexing_counts_raw(project_root: Path | None = None) -> dict[str, Any]:
    """Đọc nguyên file JSON (giữ _meta + các lý do)."""
    path = gsc_indexing_counts_file_path(project_root)
    data = _load_json_file(path)
    if not data:
        return {
            "_meta": {
                "synced_at": "",
                "source": "Google Search Console → Lập chỉ mục → Lý do trang không được lập chỉ mục",
                "property_url": "",
                "note_vi": "",
            }
        }
    return dict(data)


MAX_GSC_URLS_PER_REASON = 500


def parse_gsc_reason_value(v: Any) -> tuple[int, list[str]]:
    """
    Một lý do GSC có thể là:
    - số nguyên ≥ 0 (chỉ có tổng «Trang»)
    - object {"count": int, "urls": [...]} — URLs xuất/dán từ báo cáo chi tiết GSC (Google không cấp API đủ danh sách này).
    """
    if isinstance(v, bool):
        raise ValueError("Không dùng boolean cho số trang.")
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not v.is_integer():
            raise ValueError("Số trang phải là số nguyên.")
        n = int(v)
        if n < 0:
            raise ValueError("Số trang phải ≥ 0.")
        return n, []
    if isinstance(v, dict):
        c = v.get("count")
        if isinstance(c, float) and c.is_integer():
            c = int(c)
        if not isinstance(c, int):
            raise ValueError('Object lý do phải có "count" là số nguyên.')
        if c < 0:
            raise ValueError("count phải ≥ 0.")
        urls_raw = v.get("urls")
        urls: list[str] = []
        if urls_raw is not None:
            if not isinstance(urls_raw, list):
                raise ValueError('"urls" phải là mảng chuỗi URL.')
            for u in urls_raw:
                if not isinstance(u, str):
                    continue
                u2 = u.strip()
                if u2.startswith(("http://", "https://")):
                    urls.append(u2[:2048])
        return c, urls[:MAX_GSC_URLS_PER_REASON]
    raise ValueError("Giá trị phải là số nguyên hoặc object có «count» (và tùy chọn «urls»).")


def validate_and_normalize_gsc_indexing_counts(data: Any) -> dict[str, Any]:
    """Kiểm tra cấu trúc trước khi ghi file."""
    if not isinstance(data, dict):
        raise ValueError("Dữ liệu phải là một object JSON.")

    out: dict[str, Any] = {}
    meta_in = data.get("_meta")
    if meta_in is not None:
        if not isinstance(meta_in, dict):
            raise ValueError("_meta phải là object.")
        meta_out: dict[str, Any] = {}
        for mk, mv in meta_in.items():
            if not isinstance(mk, str):
                continue
            if isinstance(mv, bool):
                meta_out[mk] = "true" if mv else "false"
            elif mv is None:
                meta_out[mk] = ""
            elif isinstance(mv, (int, float)):
                meta_out[mk] = str(int(mv)) if isinstance(mv, float) and mv == int(mv) else str(mv)
            elif isinstance(mv, str):
                meta_out[mk] = mv
            else:
                meta_out[mk] = str(mv)
        out["_meta"] = meta_out

    for k, v in data.items():
        if k == "_meta":
            continue
        if not isinstance(k, str) or not k.strip():
            raise ValueError("Tên lý do GSC phải là chuỗi không rỗng.")
        if k.startswith("_"):
            raise ValueError("Khóa không được bắt đầu bằng _ (ngoại trừ _meta).")
        try:
            cnt, urls = parse_gsc_reason_value(v)
        except ValueError as exc:
            raise ValueError(f"«{k}»: {exc}") from exc
        key = k.strip()
        if urls:
            out[key] = {"count": cnt, "urls": urls}
        else:
            out[key] = cnt

    return out


def save_gsc_indexing_counts_raw(data: dict[str, Any], project_root: Path | None = None) -> None:
    normalized = validate_and_normalize_gsc_indexing_counts(data)
    path = gsc_indexing_counts_file_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_gsc_indexing_counts_config(
    project_root: Path | None = None,
    *,
    user_id: int | None = None,
) -> tuple[dict[str, int], dict[str, Any]]:
    """
    Đọc số liệu GSC theo user (data/users/{id}/gsc_indexing_counts.json).
    Không dùng file global khi user_id=None — tránh lộ số liệu chéo user trên /api/report.
    """
    meta: dict[str, Any] = {}
    counts: dict[str, int] = {}
    if user_id is None:
        return counts, meta
    from app.services.user_data_paths import user_gsc_indexing_counts_file

    raw = _load_json_file(user_gsc_indexing_counts_file(int(user_id)))
    if not raw:
        return counts, meta
    if isinstance(raw.get("_meta"), dict):
        meta = dict(raw["_meta"])
    for prefix, raw_val in raw.items():
        if not isinstance(prefix, str) or prefix.startswith("_"):
            continue
        if not prefix.strip():
            continue
        try:
            cnt, _urls = parse_gsc_reason_value(raw_val)
        except ValueError:
            continue
        counts[prefix.strip()] = cnt
    return counts, meta


def apply_gsc_indexing_count_overrides(
    raw_text: str,
    project_root: Path | None = None,
    *,
    user_id: int | None = None,
) -> str:
    """Đồng bộ số trong ngoặc (...) sau mỗi lý do với file GSC per-user."""
    counts, _meta = load_gsc_indexing_counts_config(project_root, user_id=user_id)
    if not counts:
        return raw_text
    out = raw_text
    for prefix, n in sorted(counts.items(), key=lambda kv: len(str(kv[0])), reverse=True):
        esc = re.escape(prefix)
        pat = re.compile(rf"({esc})\s*-\s*\(\d+\)")
        out = pat.sub(rf"\1 - ({n})", out)
    return out


def _longest_gsc_indexing_reason_key(checklist: str, counts: dict[str, int]) -> str | None:
    best: str | None = None
    best_len = -1
    for key in counts:
        if key in checklist and len(key) > best_len:
            best = key
            best_len = len(key)
    return best


def _append_gsc_index_source_block(text: str, checklist: str, project_root: Path) -> str:
    """Ghi rõ nguồn số trang: báo cáo GSC (đồng bộ file), không phải crawler nội bộ."""
    counts, meta = load_gsc_indexing_counts_config(project_root)
    reason_key = _longest_gsc_indexing_reason_key(checklist, counts)
    if not reason_key:
        return text
    n = counts.get(reason_key)
    lines = [
        "",
        "── Nguồn & phạm vi (Search Console) ──",
        f"• Lý do trong GSC khớp checklist: «{reason_key}». Số trong ngoặc (Trang): {n if n is not None else '—'}.",
        "• API Search Console công khai không trả về đầy đủ bảng tổng hợp «Lý do trang không được lập chỉ mục» như trên giao diện; "
        "số hiển thị lấy từ báo cáo GSC (Export/chụp màn hình) và lưu trong data/gsc_indexing_counts.json.",
    ]
    if meta.get("synced_at"):
        lines.append(f"• Ghi nhận đồng bộ: {meta['synced_at']}.")
    if meta.get("property_url"):
        lines.append(f"• Property GSC: {meta['property_url']}.")
    if meta.get("note_vi"):
        lines.append(f"• Ghi chú: {meta['note_vi']}")

    raw_full = read_gsc_indexing_counts_raw(project_root)
    val = raw_full.get(reason_key)
    try:
        _c, url_list = parse_gsc_reason_value(val) if val is not None else (0, [])
    except ValueError:
        url_list = []
    if url_list:
        lines.append("• Danh sách URL (xuất từ GSC hoặc dán vào JSON trong /tool, trường urls):")
        shown = url_list[:50]
        for u in shown:
            lines.append(f"  – {u}")
        if len(url_list) > 50:
            lines.append(f"  … và {len(url_list) - 50} URL khác (xem file JSON).")

    return (text or "").rstrip() + "\n" + "\n".join(lines)


def _safe_evidence_image_src(url: str) -> str | None:
    u = (url or "").strip()
    if not u.startswith(_ALLOWED_EVIDENCE_SRC_PREFIX):
        return None
    if ".." in u or " " in u or "\n" in u or "<" in u:
        return None
    tail = u[len(_ALLOWED_EVIDENCE_SRC_PREFIX) :]
    if not tail or any(part == ".." for part in tail.split("/")):
        return None
    return u


def _longest_substring_value(checklist: str, mapping: dict) -> str | None:
    best: str | None = None
    best_len = -1
    for key, val in mapping.items():
        if not isinstance(key, str) or not isinstance(val, str):
            continue
        if key in checklist and len(key) > best_len:
            best = val
            best_len = len(key)
    return best


def _gsc_evidence_image_for_checklist(checklist: str, project_root: Path | None = None) -> str | None:
    root = project_root or _PROJECT_ROOT
    data = _load_json_file(root / "data" / "gsc_evidence_images.json")
    raw = _longest_substring_value(checklist, data)
    return _safe_evidence_image_src(raw) if raw else None


def _longest_checklist_detail_entry(checklist: str, project_root: Path) -> dict:
    """Mục chi tiết trong data/checklist_evidence_detail.json (dẫn chứng + ảnh + link tham khảo tùy dòng)."""
    data = _load_json_file(project_root / "data" / "checklist_evidence_detail.json")
    if not data:
        return {}
    best: dict = {}
    best_len = -1
    for key, val in data.items():
        if not isinstance(key, str) or not isinstance(val, dict):
            continue
        if key in checklist and len(key) > best_len:
            best = val
            best_len = len(key)
    return best


def _apply_evidence_enrichment(checklist: str, base_plain: str, project_root: Path) -> tuple[str, str | None]:
    """Ghép dẫn chứng chi tiết (JSON) với dữ liệu từ Technical-SEO.txt; trả về (plain, ảnh tùy chọn)."""
    detail = _longest_checklist_detail_entry(checklist, project_root)
    block = (detail.get("evidence_text") or "").strip()
    img = _safe_evidence_image_src(str(detail.get("image") or ""))
    base = (base_plain or "").strip()
    parts: list[str] = []
    if block:
        parts.append(block)
    if base:
        parts.append("Dữ liệu kèm theo từ checklist / URL trong file:\n" + base)
    merged = "\n\n".join(parts).strip()
    if not merged:
        merged = base
    merged = _append_gsc_index_source_block(merged, checklist, project_root)
    return (merged, img)


def _reference_for_checklist(checklist: str, group: str, project_root: Path) -> str:
    detail = _longest_checklist_detail_entry(checklist, project_root)
    u = str(detail.get("reference_url") or "").strip()
    if u.startswith("https://") and " " not in u and "<" not in u:
        return u
    return GROUP_REFERENCES.get(group, GROUP_REFERENCES["General"])


def _solution_for_checklist(checklist: str, group: str) -> str:
    for needle, text in CHECKLIST_SOLUTION_OVERRIDES_VI:
        if needle in checklist:
            return text
    return GROUP_SOLUTIONS_VI.get(group, GROUP_SOLUTIONS_VI["General"])


def _nl2br(text: str) -> Markup:
    return Markup("<br>\n").join(escape(text).split("\n"))


def _build_evidence_cell(plain: str, img_src: str | None) -> tuple[str, Markup]:
    """plain: CSV/PDF; Markup: hiển thị web (có ảnh minh chứng khi cấu hình)."""
    plain = (plain or "").strip()
    note_plain = plain
    if img_src:
        note_plain = f"{plain}\n[Hình minh chứng GSC: {img_src}]".strip() if plain else f"[Hình minh chứng GSC: {img_src}]"
    parts: list[Markup] = []
    if plain:
        parts.append(Markup('<div class="evidence-text">') + _nl2br(plain) + Markup("</div>"))
    if img_src:
        parts.append(
            Markup(
                f'<div class="gsc-evidence-shot"><img src="{escape(img_src)}" '
                'alt="Minh chứng Google Search Console" loading="lazy" '
                'style="max-width:min(520px,100%);height:auto;border:1px solid #e2e8f0;border-radius:8px;margin-top:8px" />'
                "</div>"
            )
        )
    if not parts:
        return ("", Markup("—"))
    return (note_plain, Markup("").join(parts))


def _evaluation_tab_label(status: str) -> str:
    return "Tốt" if status == "good" else "Chưa tốt"


def _group_rank(group: str) -> int:
    try:
        return GROUP_DISPLAY_ORDER.index(group)
    except ValueError:
        return len(GROUP_DISPLAY_ORDER) + 1


def _classify_status(text: str) -> str:
    lowered = text.lower()
    if any(pattern in lowered for pattern in BAD_PATTERNS):
        return "needs_fix"
    if any(pattern in lowered for pattern in GOOD_PATTERNS):
        return "good"
    return "unknown"


def _extract_urls(text: str) -> list[str]:
    found = URL_PATTERN.findall(text)
    unique_urls: list[str] = []
    seen: set[str] = set()
    for raw_url in found:
        clean = raw_url.rstrip(".,)")
        if clean not in seen:
            seen.add(clean)
            unique_urls.append(clean)
    return unique_urls


def _detect_group(checklist: str, assessment: str, evidence: str, current_group: str) -> str:
    combined = f"{checklist} {assessment} {evidence}".lower()
    for group, keywords in GROUP_KEYWORDS.items():
        if any(keyword in combined for keyword in keywords):
            return group
    return current_group or "General"


def _parse_row(line: str) -> tuple[str, str, str]:
    stripped = line.strip()
    if "\t" in stripped:
        columns = [part.strip() for part in stripped.split("\t") if part.strip()]
    else:
        columns = [part.strip() for part in COLUMN_SPLIT_PATTERN.split(stripped) if part.strip()]
    if not columns:
        return ("", "", "")
    if len(columns) == 1:
        return (columns[0], "", "")
    if len(columns) == 2:
        return (columns[0], columns[1], "")
    checklist = columns[0]
    assessment = columns[1]
    evidence = " | ".join(columns[2:])
    return (checklist, assessment, evidence)


def _looks_like_record_start(line: str) -> bool:
    checklist, assessment, _ = _parse_row(line)
    if checklist and assessment:
        return True

    lowered = line.lower()
    if any(hint in lowered for hint in STATUS_HINTS):
        return True
    # OCR fragments should not start a new record on their own.
    return False


def _append_field(base: str, chunk: str) -> str:
    chunk = chunk.strip()
    if not chunk:
        return base
    if not base:
        return chunk
    return f"{base} {chunk}"


def _record_from_buffer(buffer: dict, current_group: str) -> tuple[dict | None, str]:
    checklist = buffer.get("checklist", "").strip()
    assessment = buffer.get("assessment", "").strip()
    evidence = buffer.get("evidence", "").strip()
    merged = f"{checklist} {assessment} {evidence}".strip()
    if len(merged) < 8:
        return None, current_group

    status = _classify_status(merged)
    if assessment.lower() == "chưa rõ":
        status = "unknown"
    group = _detect_group(checklist, assessment, evidence, current_group)
    item = {
        "group": group,
        "checklist": checklist,
        "assessment": assessment,
        "evidence": evidence,
        "status": status,
        "evidence_urls": _extract_urls(merged),
    }
    return item, group


def _reconstruct_records(lines: list[str]) -> list[dict]:
    records: list[dict] = []
    current_group = "General"
    buffer = {"checklist": "", "assessment": "", "evidence": ""}

    def flush_buffer() -> None:
        nonlocal current_group, buffer
        item, updated_group = _record_from_buffer(buffer, current_group)
        if item:
            records.append(item)
            current_group = updated_group
        buffer = {"checklist": "", "assessment": "", "evidence": ""}

    for line in lines:
        lowered = line.lower()
        if "checklist" in lowered and "đánh giá" in lowered:
            continue

        checklist, assessment, evidence = _parse_row(line)
        if _looks_like_record_start(line) and any(buffer.values()):
            flush_buffer()

        # Strong 3-column row.
        if checklist and assessment and evidence:
            if any(buffer.values()):
                flush_buffer()
            buffer = {
                "checklist": checklist,
                "assessment": assessment,
                "evidence": evidence,
            }
            flush_buffer()
            continue

        # 2-column row: new checklist + assessment, evidence may follow in next lines.
        if checklist and assessment:
            if any(buffer.values()):
                flush_buffer()
            buffer["checklist"] = checklist
            buffer["assessment"] = assessment
            continue

        # 1-column row continuation.
        text = checklist
        if not text:
            continue
        has_url = bool(_extract_urls(text))
        has_status_hint = any(hint in text.lower() for hint in STATUS_HINTS)

        if not buffer["checklist"]:
            buffer["checklist"] = text
            continue
        if has_url:
            buffer["evidence"] = _append_field(buffer["evidence"], text)
            continue
        if has_status_hint and not buffer["assessment"]:
            buffer["assessment"] = _append_field(buffer["assessment"], text)
            continue
        if buffer["assessment"] and not buffer["evidence"]:
            buffer["evidence"] = _append_field(buffer["evidence"], text)
            continue
        buffer["checklist"] = _append_field(buffer["checklist"], text)

    if any(buffer.values()):
        flush_buffer()

    return records


def _detect_section_header(line: str) -> str | None:
    lowered = line.lower().strip()
    for group, headers in SECTION_HEADERS.items():
        if any(header in lowered for header in headers):
            return group
    return None


def _guess_status_from_neighbors(items: list[dict], idx: int) -> str:
    current = items[idx]
    merged = f"{current['checklist']} {current['assessment']} {current['evidence']}".lower()
    if any(hint in merged for hint in BAD_PATTERNS):
        return "needs_fix"
    if any(hint in merged for hint in GOOD_PATTERNS):
        return "good"

    same_group_neighbors: list[str] = []
    for n in range(max(0, idx - 2), min(len(items), idx + 3)):
        if n == idx:
            continue
        if items[n].get("group") == current.get("group"):
            same_group_neighbors.append(items[n].get("status", "unknown"))

    if same_group_neighbors:
        if same_group_neighbors.count("needs_fix") >= 2:
            return "needs_fix"
        if same_group_neighbors.count("good") >= 2:
            return "good"
    return "unknown"


def _post_process_records(items: list[dict], raw_lines: list[str]) -> list[dict]:
    processed = [dict(item) for item in items]

    # Pass 1: apply section context to groups in sequence.
    current_section = "General"
    line_index = 0
    for line in raw_lines:
        lowered = line.lower()
        if "checklist" in lowered and "đánh giá" in lowered:
            continue
        header = _detect_section_header(line)
        if header:
            current_section = header
        if line_index < len(processed):
            if processed[line_index]["group"] == "General":
                processed[line_index]["group"] = current_section
            line_index += 1

    # Pass 2: refine unknown statuses with local context (bỏ qua hàng mẫu «Chưa rõ»).
    for idx, item in enumerate(processed):
        if item.get("status") != "unknown":
            continue
        if str(item.get("assessment", "")).strip().lower() == "chưa rõ":
            continue
        guessed = _guess_status_from_neighbors(processed, idx)
        item["status"] = guessed

    return processed


def _compute_priority_score(item: dict) -> int:
    status = item.get("status", "unknown")
    group = item.get("group", "General")
    assessment = str(item.get("assessment", "")).lower()
    evidence_urls = item.get("evidence_urls", [])

    score = STATUS_SCORES.get(status, 10) + GROUP_SCORES.get(group, 5)
    if "chưa tốt" in assessment or "kém" in assessment:
        score += 8
    if evidence_urls:
        score += min(10, len(evidence_urls) * 3)
    if len(str(item.get("checklist", ""))) > 70:
        score += 2
    return score


def _score_bucket(score: int) -> str:
    if score >= 85:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


_OKE_SECTION_LINE = re.compile(r"^\d+\.\s+.+$")


def convert_oke_prose_to_tsv(content: str) -> str:
    """Chuyển `technical-checklist-oke.txt` (đoạn văn + gạch đầu dòng) → TSV 3 cột cho parser checklist."""
    out_lines: list[str] = ["CHECKLIST\tĐÁNH GIÁ\tDẪN CHỨNG"]
    section = ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _OKE_SECTION_LINE.match(line):
            section = line
            ck = line.replace("\t", " ")
            out_lines.append(f"{ck}\tChưa rõ\t{section}")
            continue
        if line.startswith("-"):
            inner = line[1:].strip()
            if not inner:
                continue
            ck = inner.replace("\t", " ")
            ev = section or "—"
            out_lines.append(f"{ck}\tChưa rõ\t{ev}")
            continue
        ck = line.replace("\t", " ")
        ev = section or "—"
        out_lines.append(f"{ck}\tChưa rõ\t{ev}")
    return "\n".join(out_lines) + "\n"


def build_seo_report_from_text(
    raw_text: str,
    group_filter: str | None = None,
    status_filter: str | None = None,
) -> dict:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    all_items = _post_process_records(_reconstruct_records(lines), lines)
    items: list[dict] = []
    total_good = 0
    total_needs_fix = 0
    total_unknown = 0
    group_counts: dict[str, int] = {}

    for item in all_items:
        if group_filter and item["group"].lower() != group_filter.lower():
            continue
        if status_filter and item["status"].lower() != status_filter.lower():
            continue

        group = item["group"]
        status = item["status"]
        group_counts[group] = group_counts.get(group, 0) + 1
        if status == "good":
            total_good += 1
        elif status == "needs_fix":
            total_needs_fix += 1
        else:
            total_unknown += 1
        item_copy = dict(item)
        item_copy["priority_score"] = _compute_priority_score(item_copy)
        items.append(item_copy)

    prioritized = sorted(
        [item for item in items if item["status"] == "needs_fix"],
        key=lambda entry: (
            _group_rank(str(entry.get("group", "General"))),
            -int(entry.get("priority_score", 0) or 0),
            -len(entry.get("evidence_urls", [])),
        ),
    )

    return {
        "summary": {
            "total_items": len(items),
            "good": total_good,
            "needs_fix": total_needs_fix,
            "unknown": total_unknown,
        },
        "groups": sorted(group_counts.keys(), key=_group_rank),
        "group_counts": group_counts,
        "priorities": prioritized[:20],
        "items": items,
    }


def build_seo_report_from_file(
    file_path: str,
    group_filter: str | None = None,
    status_filter: str | None = None,
    *,
    user_id: int | None = None,
) -> dict:
    path = Path(file_path)
    raw_text = path.read_text(encoding="utf-8", errors="ignore")
    if path.name.lower() == "technical-checklist-oke.txt":
        raw_text = convert_oke_prose_to_tsv(raw_text)
    project_root = _PROJECT_ROOT
    raw_text = apply_gsc_indexing_count_overrides(raw_text, project_root=project_root, user_id=user_id)
    return build_seo_report_from_text(raw_text, group_filter=group_filter, status_filter=status_filter)


ACTION_PLAN_CSV_COLUMNS = [
    "Ưu tiên",
    "Nhóm",
    "CHECKLIST",
    "ĐÁNH GIÁ",
    "DẪN CHỨNG CHI TIẾT",
    "GIẢI PHÁP",
    "LINK THAM KHẢO",
    "HIỆN TRẠNG",
    "LINK TRIỂN KHAI",
    "NOTE",
]


def _format_dan_chi_tiet(item: dict) -> str:
    chunks: list[str] = []
    ev = (item.get("evidence") or "").strip()
    if ev:
        chunks.append(ev)
    urls = item.get("evidence_urls") or []
    if urls:
        chunks.append("\n".join(urls))
    return "\n\n".join(chunks).strip() if chunks else ""


def _task_key(group: str, task: str) -> str:
    raw = f"{group}|{task}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:12]


def build_audit_action_plan_rows(
    grouped_issues: list[dict],
    notes_map: dict[str, str] | None = None,
    deploy_map: dict[str, str] | None = None,
    *,
    checklist_titles: dict[str, str] | None = None,
    group_filter: str | None = None,
    project_root: Path | None = None,
) -> list[dict]:
    """Action-plan rows từ kết quả quét Technical của user (không dùng file Technical-SEO.txt tĩnh)."""
    notes_map = notes_map or {}
    deploy_map = deploy_map or {}
    titles = checklist_titles or {}
    root = project_root or _PROJECT_ROOT
    rows: list[dict] = []
    rank = {"critical": 5, "high": 4, "medium": 3, "low": 2, "passed": 1}

    for issue in grouped_issues:
        if not isinstance(issue, dict):
            continue
        group = str(issue.get("checklist_group") or "General")
        if group_filter and group != group_filter:
            continue
        issue_type = str(issue.get("type") or "").strip()
        if not issue_type:
            continue
        checklist_text = titles.get(issue_type) or issue_type
        sev = str(issue.get("severity") or "low").lower()
        sev_lbl = SEVERITY_LABEL_VI.get(sev, sev.upper() if sev else "—")
        urls = issue.get("urls") or []
        if not urls and issue.get("url"):
            urls = [str(issue.get("url"))]
        evidence_parts = [str(issue.get("message") or "").strip()]
        evidence_parts.extend(str(u) for u in urls[:8] if u)
        evidence_plain = "\n".join(p for p in evidence_parts if p).strip() or "—"
        fix_primary = str(issue.get("remediation") or issue.get("suggested_fix") or "").strip()
        gsol = GROUP_SOLUTIONS_VI.get(group, GROUP_SOLUTIONS_VI["General"])
        gref = GROUP_REFERENCES.get(group, GROUP_REFERENCES["General"])
        task_key = _task_key(group, issue_type)
        evidence_markup = evidence_plain.replace("\n", "<br>")
        rows.append(
            {
                "Ưu tiên": 0,
                "Nhóm": GROUP_DISPLAY_LABEL_VI.get(group, group),
                "Nhóm_raw": group,
                "CHECKLIST": checklist_text,
                "ĐÁNH GIÁ": sev_lbl,
                "DẪN CHỨNG CHI TIẾT": evidence_plain,
                "DẪN CHỨNG HTML": evidence_markup,
                "GIẢI PHÁP": fix_primary or gsol,
                "LINK THAM KHẢO": gref,
                "HIỆN TRẠNG": f"Quét tự động — {sev_lbl}",
                "LINK TRIỂN KHAI": deploy_map.get(task_key, ""),
                "NOTE": notes_map.get(task_key, ""),
                "priority_score": rank.get(sev, 40) * 10,
                "status_raw": "needs_fix",
            }
        )

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            _group_rank(str(row.get("Nhóm_raw", "General"))),
            -int(row.get("priority_score", 0) or 0),
            str(row.get("CHECKLIST", "")),
        ),
    )
    for idx, row in enumerate(sorted_rows, start=1):
        row["Ưu tiên"] = idx
    return sorted_rows


def audit_issues_summary(grouped_issues: list[dict]) -> dict[str, int]:
    """Tổng hợp số lỗi theo mức độ từ audit user."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for issue in grouped_issues:
        if not isinstance(issue, dict):
            continue
        sev = str(issue.get("severity") or "low").lower()
        if sev in counts:
            counts[sev] += 1
        else:
            counts["low"] += 1
    total = len(grouped_issues)
    return {
        "total_items": total,
        "needs_fix": total,
        "good": 0,
        "unknown": 0,
        "critical": counts["critical"],
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
    }


def build_action_plan_rows(
    report: dict,
    notes_map: dict[str, str] | None = None,
    deploy_map: dict[str, str] | None = None,
    *,
    scope: str = "all",
    project_root: Path | None = None,
) -> list[dict]:
    """scope=all: toàn bộ dòng checklist (Technical-SEO.txt). scope=priorities: chỉ needs_fix (20 mục ưu tiên)."""
    notes_map = notes_map or {}
    deploy_map = deploy_map or {}
    root = project_root or _PROJECT_ROOT
    if scope == "priorities":
        source_items = list(report.get("priorities", []))
    else:
        source_items = list(report.get("items", []))
    rows: list[dict] = []
    for index, item in enumerate(source_items, start=1):
        group = item.get("group", "General")
        checklist_text = item.get("checklist", "")
        task_key = _task_key(group, checklist_text)
        status = item.get("status", "") or ""
        evidence_plain = _format_dan_chi_tiet(item)
        evidence_plain, detail_img = _apply_evidence_enrichment(checklist_text, evidence_plain, root)
        img = detail_img or _gsc_evidence_image_for_checklist(checklist_text, project_root=root)
        plain_cell, evidence_markup = _build_evidence_cell(evidence_plain, img)
        rows.append(
            {
                "Ưu tiên": index,
                "Nhóm": GROUP_DISPLAY_LABEL_VI.get(group, group),
                "Nhóm_raw": group,
                "CHECKLIST": checklist_text,
                "ĐÁNH GIÁ": _evaluation_tab_label(status),
                "DẪN CHỨNG CHI TIẾT": plain_cell or "—",
                "DẪN CHỨNG HTML": evidence_markup,
                "GIẢI PHÁP": _solution_for_checklist(checklist_text, group),
                "LINK THAM KHẢO": _reference_for_checklist(checklist_text, group, root),
                "HIỆN TRẠNG": STATUS_LABEL_VI.get(status, status or "—"),
                "LINK TRIỂN KHAI": deploy_map.get(task_key, ""),
                "NOTE": notes_map.get(task_key, ""),
                "priority_score": item.get("priority_score", 0),
                "status_raw": status,
            }
        )
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            _group_rank(str(row.get("Nhóm_raw", "General"))),
            -int(row.get("priority_score", 0) or 0),
            int(row.get("Ưu tiên", 0) or 0),
        ),
    )
    for idx, row in enumerate(sorted_rows, start=1):
        row["Ưu tiên"] = idx
    return sorted_rows


def load_notes_map(notes_file: str) -> dict[str, str]:
    path = Path(notes_file)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            clean[key] = value
    return clean


def save_notes_map(notes_file: str, notes_map: dict[str, str]) -> None:
    path = Path(notes_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(notes_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_deploy_links_map(deploy_file: str) -> dict[str, str]:
    path = Path(deploy_file)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def save_deploy_links_map(deploy_file: str, deploy_map: dict[str, str]) -> None:
    path = Path(deploy_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(deploy_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_notes_by_priority(raw: str) -> dict[int, str]:
    # Format: "1:done;2:waiting-dev;5:client-confirm"
    parsed: dict[int, str] = {}
    if not raw.strip():
        return parsed
    for chunk in raw.split(";"):
        part = chunk.strip()
        if not part or ":" not in part:
            continue
        left, right = part.split(":", 1)
        try:
            priority = int(left.strip())
        except ValueError:
            continue
        note = right.strip()
        if priority > 0 and note:
            parsed[priority] = note
    return parsed


def parse_deploy_links_by_priority(raw: str) -> dict[int, str]:
    parsed: dict[int, str] = {}
    if not raw.strip():
        return parsed
    for chunk in raw.split(";"):
        part = chunk.strip()
        if not part or ":" not in part:
            continue
        left, right = part.split(":", 1)
        try:
            priority = int(left.strip())
        except ValueError:
            continue
        link = right.strip()
        if priority > 0 and link:
            parsed[priority] = link
    return parsed


def build_lean_action_plan(
    report: dict,
    notes_map: dict[str, str] | None = None,
    deploy_map: dict[str, str] | None = None,
    global_note: str | None = None,
) -> list[dict]:
    lean_rows: list[dict] = []
    notes_map = notes_map or {}
    deploy_map = deploy_map or {}
    global_note = (global_note or "").strip()
    for index, item in enumerate(report.get("priorities", []), start=1):
        group = item.get("group", "General")
        score = int(item.get("priority_score", 0) or 0)
        task = item.get("checklist", "")
        task_key = _task_key(group, task)
        persisted_note = notes_map.get(task_key, "")
        combined_note = persisted_note
        if global_note:
            combined_note = f"{persisted_note} | {global_note}".strip(" |") if persisted_note else global_note
        st = item.get("status", "") or ""
        evidence_plain = _format_dan_chi_tiet(item)
        evidence_plain, detail_img = _apply_evidence_enrichment(task, evidence_plain, _PROJECT_ROOT)
        img = detail_img or _gsc_evidence_image_for_checklist(task, project_root=_PROJECT_ROOT)
        plain_cell, evidence_markup = _build_evidence_cell(evidence_plain, img)
        lean_rows.append(
            {
                "priority": index,
                "owner": GROUP_OWNERS.get(group, "SEO Team"),
                "eta": f"{GROUP_ETA_DAYS.get(group, 7)}d",
                "score_bucket": _score_bucket(score),
                "score": score,
                "group": group,
                "task": task,
                "task_key": task_key,
                "CHECKLIST": task,
                "ĐÁNH GIÁ": _evaluation_tab_label(st),
                "DẪN CHỨNG CHI TIẾT": plain_cell or "—",
                "DẪN CHỨNG HTML": evidence_markup,
                "GIẢI PHÁP": _solution_for_checklist(task, group),
                "LINK THAM KHẢO": _reference_for_checklist(task, group, _PROJECT_ROOT),
                "HIỆN TRẠNG": STATUS_LABEL_VI.get(st, st or "—"),
                "LINK TRIỂN KHAI": deploy_map.get(task_key, ""),
                "NOTE": combined_note,
            }
        )
    return lean_rows


# —— Technical audit export (normalized_issues ↔ legacy issues) ——

NORM_CATEGORY_TO_CHECKLIST_GROUP: dict[str, str] = {
    "gsc_indexing": "GSC",
    "onpage": "Onpage",
    "sitemap": "Sitemap",
    "robots": "Robots",
    "schema": "Onpage",
    "images": "Images",
    "video": "Video",
    "mobile": "Mobile",
    "international": "International",
    "site_speed": "Speed",
    "https": "Security",
    "response_code": "Security",
    "website": "General",
    "other": "General",
}


def _normalized_issue_export_type(issue: dict[str, Any]) -> str:
    explicit = issue.get("_issue_type") or issue.get("type")
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    iid = str(issue.get("id") or "").strip()
    if re.match(r"^.+_[a-f0-9]{12}$", iid):
        return iid.rsplit("_", 1)[0]
    if "|" in iid:
        return iid.split("|", 1)[0]
    return iid or "issue"


def _issue_url_list(issue: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    u = str(issue.get("url") or "").strip()
    if u and u not in seen:
        seen.add(u)
        out.append(u)
    for key in ("urls", "affected_urls", "sample_urls"):
        raw = issue.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            s = str(item or "").strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def normalized_issue_to_legacy_export_row(issue: dict[str, Any]) -> dict[str, Any]:
    """Chuyển normalized issue sang dòng legacy để group/export CSV/PDF/GSheet."""
    cat = str(issue.get("category") or "other").lower()
    group = NORM_CATEGORY_TO_CHECKLIST_GROUP.get(cat, "General")
    urls = _issue_url_list(issue)
    how_to = str(issue.get("how_to_fix") or "").strip()
    expl = str(issue.get("why_it_matters") or issue.get("explanation") or "").strip()
    conf = issue.get("confidence")
    try:
        conf_val = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_val = None
    return {
        "type": _normalized_issue_export_type(issue),
        "severity": str(issue.get("severity") or "low").lower(),
        "checklist_group": group,
        "group": group,
        "category": cat,
        "message": str(issue.get("description") or issue.get("title") or "").strip(),
        "url": urls[0] if urls else "",
        "urls": urls,
        "remediation": how_to,
        "suggested_fix": how_to,
        "explanation": expl,
        "page_type": str(issue.get("page_type") or "").strip(),
        "confidence": conf_val,
        "source": issue.get("source"),
        "priority_score": issue.get("priority_score"),
        "gsc_clicks": issue.get("gsc_clicks"),
        "gsc_impressions": issue.get("gsc_impressions"),
        "gsc_ctr": issue.get("gsc_ctr"),
        "gsc_position": issue.get("gsc_position"),
        "gsc_index_verdict": issue.get("gsc_index_verdict"),
        "gsc_badge": issue.get("gsc_badge"),
    }


def resolve_audit_issues_for_export(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Ưu tiên normalized_issues; fallback issues legacy.
    Bỏ qua severity=passed và issue bị suppressed.
    """
    if not run or not isinstance(run, dict):
        return []
    norm = run.get("normalized_issues")
    if isinstance(norm, list) and norm:
        rows: list[dict[str, Any]] = []
        for item in norm:
            if not isinstance(item, dict):
                continue
            if str(item.get("severity") or "").lower() == "passed":
                continue
            rows.append(normalized_issue_to_legacy_export_row(item))
        if rows:
            return rows
    legacy = run.get("issues") or []
    return [
        i
        for i in legacy
        if isinstance(i, dict) and not i.get("suppressed")
    ]
