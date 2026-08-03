/**
 * Google Map SEO — Check Map Score engine
 * Chỉ đánh giá từ dữ liệu GBP có sẵn; không bịa khi thiếu trường.
 */
(function (global) {
    "use strict";

    var LS_HISTORY = "gms_check_history_v1";
    var MAX_HISTORY = 30;

    var GROUP_META = [
        { id: "business_info", label: "Thông tin doanh nghiệp", maxPoints: 15 },
        { id: "category", label: "Ngành nghề", maxPoints: 10 },
        { id: "description", label: "Mô tả doanh nghiệp", maxPoints: 12 },
        { id: "media", label: "Ảnh & Media", maxPoints: 13 },
        { id: "reviews", label: "Review", maxPoints: 15 },
        { id: "posts", label: "Bài đăng", maxPoints: 10 },
        { id: "services", label: "Dịch vụ/Sản phẩm", maxPoints: 10 },
        { id: "website", label: "Website & Local SEO", maxPoints: 15 },
    ];

    function hasObj(o) {
        return o && typeof o === "object";
    }

    function pushIssue(list, item) {
        list.push({
            id: item.id || "iss_" + list.length,
            severity: item.severity,
            groupId: item.groupId,
            title: item.title,
            cause: item.cause,
            fix: item.fix,
            aiFixable: item.aiFixable !== false,
        });
    }

    function scoreBusinessInfo(data, issues) {
        if (!hasObj(data)) return { sufficient: false, score: 0, maxPoints: 15, issues: issues };
        var pts = 0;
        var max = 15;
        if (data.hasName) pts += 3; else pushIssue(issues, { severity: "critical", groupId: "business_info", title: "Thiếu tên doanh nghiệp", cause: "Google chưa có tên hiển thị chuẩn trên hồ sơ.", fix: "Cập nhật tên thương hiệu chính thức, trùng với bảng hiệu/NAP.", aiFixable: true });
        if (data.hasAddress) pts += 3; else pushIssue(issues, { severity: "critical", groupId: "business_info", title: "Thiếu địa chỉ", cause: "Địa chỉ không đầy đủ hoặc chưa ghim bản đồ.", fix: "Xác nhận địa chỉ và vị trí pin trên Google Maps.", aiFixable: false });
        if (data.hasPhone) pts += 3; else pushIssue(issues, { severity: "warning", groupId: "business_info", title: "Thiếu số điện thoại", cause: "Khách không gọi trực tiếp từ Map.", fix: "Thêm số hotline/local có người trực.", aiFixable: false });
        if (data.hasHours) {
            pts += 3;
            if ((data.hoursDaysCovered || 0) < 7) {
                pushIssue(issues, { severity: "warning", groupId: "business_info", title: "Giờ mở cửa chưa đủ 7 ngày", cause: "Chỉ có " + (data.hoursDaysCovered || 0) + "/7 ngày.", fix: "Bổ sung giờ Chủ nhật hoặc ngày còn thiếu.", aiFixable: true });
            }
        } else {
            pushIssue(issues, { severity: "warning", groupId: "business_info", title: "Chưa cập nhật giờ mở cửa", cause: "Giờ hoạt động trống hoặc không đầy đủ.", fix: "Điền giờ mở cửa 7 ngày/tuần và ngày lễ.", aiFixable: true });
        }
        if (data.verified) pts += 3; else pushIssue(issues, { severity: "critical", groupId: "business_info", title: "Chưa xác minh doanh nghiệp", cause: "Hồ sơ chưa được Google xác minh quyền sở hữu.", fix: "Hoàn tất xác minh qua thư, điện thoại hoặc video.", aiFixable: false });
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scoreCategory(data, issues) {
        if (!hasObj(data) || !data.primary) return { sufficient: false, score: 0, maxPoints: 10, issues: issues };
        var pts = 6;
        var max = 10;
        if ((data.secondaryCount || 0) >= 2) pts += 4;
        else if ((data.secondaryCount || 0) === 1) {
            pts += 2;
            pushIssue(issues, { severity: "opportunity", groupId: "category", title: "Nên thêm danh mục phụ", cause: "Chỉ có 1 danh mục phụ.", fix: "Thêm 1–2 danh mục liên quan để mở rộng từ khóa Map.", aiFixable: true });
        } else {
            pushIssue(issues, { severity: "warning", groupId: "category", title: "Thiếu danh mục phụ", cause: "Chỉ có danh mục chính «" + data.primary + "».", fix: "Bổ sung danh mục phụ sát ngành nghề.", aiFixable: true });
        }
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scoreDescription(data, issues) {
        if (!hasObj(data) || data.textLength == null) return { sufficient: false, score: 0, maxPoints: 12, issues: issues };
        var len = Number(data.textLength) || 0;
        var pts = 0;
        var max = 12;
        if (len >= 250 && len <= 750) pts = 12;
        else if (len >= 150) {
            pts = 8;
            pushIssue(issues, { severity: "warning", groupId: "description", title: "Mô tả còn ngắn", cause: "Độ dài hiện tại: " + len + " ký tự (khuyến nghị 250–750).", fix: "Mở rộng mô tả với USP và từ khóa địa phương.", aiFixable: true });
        } else if (len > 0) {
            pts = 4;
            pushIssue(issues, { severity: "critical", groupId: "description", title: "Mô tả quá ngắn", cause: "Chỉ " + len + " ký tự — Google ưu tiên mô tả đầy đủ.", fix: "Viết lại mô tả 250+ ký tự, có CTA và khu vực phục vụ.", aiFixable: true });
        } else {
            pushIssue(issues, { severity: "critical", groupId: "description", title: "Chưa có mô tả", cause: "Trường mô tả trống trên GBP.", fix: "Thêm mô tả doanh nghiệp chuẩn SEO Local.", aiFixable: true });
        }
        if (pts >= 8 && !data.hasLocalKeywords) {
            pushIssue(issues, { severity: "opportunity", groupId: "description", title: "Thiếu từ khóa địa phương", cause: "Mô tả chưa nhắc quận/thành phố hoặc dịch vụ tại chỗ.", fix: "Chèn từ khóa «dịch vụ + khu vực» tự nhiên.", aiFixable: true });
            if (pts === 12) pts -= 2;
        }
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scoreMedia(data, issues) {
        if (!hasObj(data) || data.photoCount == null) return { sufficient: false, score: 0, maxPoints: 13, issues: issues };
        var photos = Number(data.photoCount) || 0;
        var videos = Number(data.videoCount) || 0;
        var pts = 0;
        var max = 13;
        if (data.hasLogo) pts += 2; else pushIssue(issues, { severity: "warning", groupId: "media", title: "Thiếu logo", cause: "Chưa upload logo thương hiệu.", fix: "Thêm logo vuông, nền trong suốt hoặc trắng.", aiFixable: false });
        if (data.hasCover) pts += 2; else pushIssue(issues, { severity: "warning", groupId: "media", title: "Thiếu ảnh bìa", cause: "Ảnh cover giúp nổi bật trên Map.", fix: "Upload ảnh bìa 1080×608 chất lượng cao.", aiFixable: false });
        if (hasObj(data.typesPresent)) {
            var tp = data.typesPresent;
            if (!tp.storefront) pushIssue(issues, { severity: "warning", groupId: "media", title: "Thiếu ảnh mặt tiền", cause: "Chưa có ảnh cửa hàng/văn phòng.", fix: "Upload ảnh mặt tiền thực tế.", aiFixable: false });
            if (!tp.interior) pushIssue(issues, { severity: "warning", groupId: "media", title: "Thiếu ảnh nội thất", cause: "Khách chưa thấy không gian làm việc.", fix: "Bổ sung ảnh nội thất.", aiFixable: false });
            if (!tp.product_service) pushIssue(issues, { severity: "warning", groupId: "media", title: "Thiếu ảnh sản phẩm/dịch vụ", cause: "Chưa minh họa dịch vụ trên thư viện ảnh.", fix: "Upload ảnh sản phẩm hoặc quy trình dịch vụ.", aiFixable: false });
            if (!tp.team) pushIssue(issues, { severity: "opportunity", groupId: "media", title: "Nên thêm ảnh đội ngũ", cause: "Ảnh nhân sự tăng độ tin cậy.", fix: "Upload ảnh đội ngũ tư vấn.", aiFixable: false });
            if (!tp.customer_case) pushIssue(issues, { severity: "opportunity", groupId: "media", title: "Nên thêm ảnh case thực tế", cause: "Chưa có ảnh kết quả/khách hàng.", fix: "Bổ sung case study bằng hình ảnh.", aiFixable: false });
        }
        if (photos >= 15) pts += 6;
        else if (photos >= 8) {
            pts += 4;
            pushIssue(issues, { severity: "opportunity", groupId: "media", title: "Nên thêm ảnh", cause: "Hiện có " + photos + " ảnh (khuyến nghị ≥15).", fix: "Upload ảnh thực tế: cửa hàng, đội ngũ, sản phẩm.", aiFixable: false });
        } else if (photos >= 3) {
            pts += 2;
            pushIssue(issues, { severity: "warning", groupId: "media", title: "Ít ảnh trên hồ sơ", cause: "Chỉ " + photos + " ảnh — đối thủ thường có 10+.", fix: "Bổ sung ít nhất 5–10 ảnh mới.", aiFixable: false });
        } else {
            pushIssue(issues, { severity: "critical", groupId: "media", title: "Rất ít ảnh", cause: "Chỉ " + photos + " ảnh trên GBP.", fix: "Ảnh là tín hiệu trust mạnh trên Local Pack.", aiFixable: false });
        }
        if (videos >= 1) pts += 3; else pushIssue(issues, { severity: "opportunity", groupId: "media", title: "Chưa có video", cause: "Video ngắn tăng tương tác hồ sơ.", fix: "Quay video 15–30s giới thiệu địa điểm.", aiFixable: false });
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scoreReviews(data, issues) {
        if (!hasObj(data) || data.count == null) return { sufficient: false, score: 0, maxPoints: 15, issues: issues };
        var count = Number(data.count) || 0;
        var avg = Number(data.avgRating) || 0;
        var unreplied = Number(data.unrepliedCount) || 0;
        var pts = 0;
        var max = 15;
        if (count >= 50) pts += 5;
        else if (count >= 20) {
            pts += 3;
            pushIssue(issues, { severity: "opportunity", groupId: "reviews", title: "Cần thêm review", cause: "Hiện " + count + " review (mục tiêu 50+).", fix: "Nhắc khách hài lòng để lại đánh giá Google.", aiFixable: true });
        } else if (count > 0) {
            pts += 1;
            pushIssue(issues, { severity: "warning", groupId: "reviews", title: "Số review còn thấp", cause: "Chỉ " + count + " review.", fix: "Triển khai chiến dịch xin review sau dịch vụ.", aiFixable: true });
        } else {
            pushIssue(issues, { severity: "critical", groupId: "reviews", title: "Chưa có review", cause: "Chưa thu thập đánh giá Google.", fix: "Bắt đầu xin review từ khách thân thiết.", aiFixable: true });
        }
        if (avg >= 4.5) pts += 5;
        else if (avg >= 4.0) {
            pts += 3;
            pushIssue(issues, { severity: "warning", groupId: "reviews", title: "Điểm sao trung bình trung bình", cause: "Rating " + avg + " — cần cải thiện chất lượng phản hồi.", fix: "Phản hồi review thấp và xử lý khiếu nại.", aiFixable: true });
        } else if (avg > 0) {
            pts += 1;
            pushIssue(issues, { severity: "critical", groupId: "reviews", title: "Điểm sao thấp", cause: "Rating " + avg + " ảnh hưởng thứ hạng Map.", fix: "Ưu tiên cải thiện dịch vụ và trả lời review.", aiFixable: true });
        }
        if (unreplied === 0 && count > 0) pts += 5;
        else if (unreplied > 0 && unreplied <= 5) {
            pts += 3;
            pushIssue(issues, { severity: "warning", groupId: "reviews", title: "Review chưa phản hồi", cause: unreplied + " review chưa trả lời.", fix: "Phản hồi trong 24–48h để tăng trust.", aiFixable: true });
        } else if (unreplied > 5) {
            pts += 1;
            pushIssue(issues, { severity: "critical", groupId: "reviews", title: "Nhiều review chưa phản hồi", cause: unreplied + " review đang chờ.", fix: "Dùng mẫu phản hồi AI hoặc trả lời thủ công hàng loạt.", aiFixable: true });
        }
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scorePosts(data, issues) {
        if (!hasObj(data) || data.publishedCount == null) return { sufficient: false, score: 0, maxPoints: 10, issues: issues };
        var count = Number(data.publishedCount) || 0;
        var days = data.daysSinceLastPost;
        var pts = 0;
        var max = 10;
        if (count >= 3) pts += 5;
        else if (count >= 1) {
            pts += 3;
            pushIssue(issues, { severity: "opportunity", groupId: "posts", title: "Ít bài đăng GBP", cause: "Chỉ " + count + " bài đã đăng.", fix: "Đăng 2–4 bài/tháng: ưu đãi, tin tức, sự kiện.", aiFixable: true });
        } else {
            pushIssue(issues, { severity: "warning", groupId: "posts", title: "Chưa có bài đăng", cause: "Không có bài đăng trên Google Business Profile.", fix: "Tạo bài đăng đầu tiên với CTA rõ ràng.", aiFixable: true });
        }
        if (days != null && days <= 30) pts += 5;
        else if (days != null && days <= 60) {
            pts += 3;
            pushIssue(issues, { severity: "warning", groupId: "posts", title: "Lâu chưa đăng bài", cause: "Bài gần nhất cách đây " + days + " ngày.", fix: "Lên lịch đăng ít nhất 1 bài/tháng.", aiFixable: true });
        } else if (days != null) {
            pushIssue(issues, { severity: "critical", groupId: "posts", title: "Quá lâu không đăng bài", cause: "Bài gần nhất cách đây " + days + " ngày.", fix: "Đăng bài mới ngay để tăng tín hiệu hoạt động.", aiFixable: true });
        } else if (count === 0) {
            /* already flagged */
        } else {
            pushIssue(issues, { severity: "warning", groupId: "posts", title: "Không xác định ngày bài gần nhất", cause: "API chưa trả ngày đăng bài cuối.", fix: "Đăng bài mới để làm mới hồ sơ.", aiFixable: true });
        }
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scoreServices(data, issues) {
        if (!hasObj(data) || data.itemCount == null) return { sufficient: false, score: 0, maxPoints: 10, issues: issues };
        var count = Number(data.itemCount) || 0;
        var pts = 0;
        var max = 10;
        if (count >= 5) pts += 6;
        else if (count >= 1) {
            pts += 3;
            pushIssue(issues, { severity: "opportunity", groupId: "services", title: "Ít mục dịch vụ/sản phẩm", cause: "Chỉ " + count + " mục trên GBP.", fix: "Thêm đủ dịch vụ chính kèm giá/mô tả ngắn.", aiFixable: true });
        } else {
            pushIssue(issues, { severity: "warning", groupId: "services", title: "Chưa khai báo dịch vụ", cause: "Danh sách dịch vụ/sản phẩm trống.", fix: "Thêm menu dịch vụ để match intent tìm kiếm.", aiFixable: true });
        }
        if (data.hasDescriptions && count > 0) pts += 4;
        else if (count > 0) {
            pushIssue(issues, { severity: "opportunity", groupId: "services", title: "Dịch vụ thiếu mô tả", cause: "Các mục chưa có mô tả chi tiết.", fix: "Viết mô tả ngắn có từ khóa cho từng dịch vụ.", aiFixable: true });
        }
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    function scoreWebsite(data, issues) {
        if (!hasObj(data)) return { sufficient: false, score: 0, maxPoints: 15, issues: issues };
        if (!data.url) return { sufficient: false, score: 0, maxPoints: 15, issues: issues };
        var pts = 0;
        var max = 15;
        pts += 5;
        if (data.napConsistent === true) pts += 5;
        else if (data.napConsistent === false) pushIssue(issues, { severity: "critical", groupId: "website", title: "NAP không nhất quán", cause: "Tên/địa chỉ/SĐT website khác GBP.", fix: "Đồng bộ NAP trên website và Google Map.", aiFixable: true });
        else pushIssue(issues, { severity: "warning", groupId: "website", title: "Chưa kiểm tra NAP", cause: "Chưa so khớp NAP website với GBP.", fix: "Chạy audit NAP hoặc cập nhật thủ công.", aiFixable: false });
        if (data.hasTracking) pts += 3; else pushIssue(issues, { severity: "opportunity", groupId: "website", title: "Thiếu UTM theo dõi", cause: "Link website chưa gắn UTM từ GBP.", fix: "Thêm UTM để đo traffic từ Map.", aiFixable: true });
        if (data.hasLocalLanding) pts += 2; else pushIssue(issues, { severity: "opportunity", groupId: "website", title: "Chưa có landing địa phương", cause: "Website chưa có trang landing theo khu vực.", fix: "Tạo trang «Dịch vụ + Quận/Huyện».", aiFixable: true });
        return { sufficient: true, score: Math.min(pts, max), maxPoints: max, issues: issues };
    }

    var EVALUATORS = {
        business_info: function (gbp) { return scoreBusinessInfo(gbp.businessInfo, []); },
        category: function (gbp) { return scoreCategory(gbp.category, []); },
        description: function (gbp) { return scoreDescription(gbp.description, []); },
        media: function (gbp) { return scoreMedia(gbp.media, []); },
        reviews: function (gbp) { return scoreReviews(gbp.reviews, []); },
        posts: function (gbp) { return scorePosts(gbp.posts, []); },
        services: function (gbp) { return scoreServices(gbp.services, []); },
        website: function (gbp) { return scoreWebsite(gbp.website, []); },
    };

    function evaluateLocation(loc) {
        var gbp = loc && loc.gbp;
        if (!gbp || gbp.synced !== true) {
            return {
                ok: false,
                reason: "no_sync",
                message: "Chưa đủ dữ liệu đồng bộ từ Google Business Profile để chấm điểm.",
                totalScore: null,
                groups: [],
                issues: [],
            };
        }

        var groups = [];
        var allIssues = [];
        var earned = 0;
        var maxEarnable = 0;

        GROUP_META.forEach(function (meta) {
            var ev = EVALUATORS[meta.id];
            var raw = ev ? ev(gbp) : { sufficient: false, score: 0, maxPoints: meta.maxPoints, issues: [] };
            var row = {
                id: meta.id,
                label: meta.label,
                maxPoints: meta.maxPoints,
                sufficient: raw.sufficient,
                score: raw.sufficient ? raw.score : null,
                insufficientMessage: raw.sufficient ? null : "Chưa đủ dữ liệu để đánh giá",
            };
            groups.push(row);
            if (raw.sufficient) {
                earned += raw.score;
                maxEarnable += raw.maxPoints;
                (raw.issues || []).forEach(function (i) { allIssues.push(i); });
            }
        });

        var totalScore = maxEarnable > 0 ? Math.round((earned / maxEarnable) * 100) : null;
        var summary = { critical: 0, warning: 0, opportunity: 0 };
        allIssues.forEach(function (i) {
            if (i.severity === "critical") summary.critical += 1;
            else if (i.severity === "warning") summary.warning += 1;
            else summary.opportunity += 1;
        });

        return {
            ok: true,
            reason: maxEarnable === 0 ? "no_data" : "scored",
            message: maxEarnable === 0 ? "Chưa đủ dữ liệu để đánh giá bất kỳ nhóm nào." : null,
            locationId: loc.id,
            locationName: loc.name,
            totalScore: totalScore,
            earned: earned,
            maxEarnable: maxEarnable,
            groups: groups,
            issues: allIssues,
            summary: summary,
            checkedAt: new Date().toISOString(),
        };
    }

    function readHistoryStore() {
        try {
            var raw = localStorage.getItem(LS_HISTORY);
            return raw ? JSON.parse(raw) : {};
        } catch (_e) {
            return {};
        }
    }

    function writeHistoryStore(store) {
        try {
            localStorage.setItem(LS_HISTORY, JSON.stringify(store));
        } catch (_e) {}
    }

    function saveCheckResult(result) {
        if (!result || !result.locationId || result.totalScore == null) return null;
        var store = readHistoryStore();
        var list = store[result.locationId] || [];
        var entry = {
            id: "chk_" + Date.now(),
            locationId: result.locationId,
            at: result.checkedAt || new Date().toISOString(),
            totalScore: result.totalScore,
            earned: result.earned,
            maxEarnable: result.maxEarnable,
            groups: result.groups,
            issues: result.issues,
            summary: result.summary,
        };
        list.unshift(entry);
        if (list.length > MAX_HISTORY) list = list.slice(0, MAX_HISTORY);
        store[result.locationId] = list;
        writeHistoryStore(store);
        return entry;
    }

    function getHistory(locationId) {
        var store = readHistoryStore();
        return (store[locationId] || []).slice();
    }

    function getLastCheck(locationId) {
        var list = getHistory(locationId);
        return list.length ? list[0] : null;
    }

    function severityLabel(sev) {
        if (sev === "critical") return "Critical";
        if (sev === "warning") return "Warning";
        return "Opportunity";
    }

    function groupLabel(groupId) {
        var g = GROUP_META.find(function (m) { return m.id === groupId; });
        return g ? g.label : groupId;
    }

    global.GmsMapCheck = {
        GROUP_META: GROUP_META,
        evaluateLocation: evaluateLocation,
        saveCheckResult: saveCheckResult,
        getHistory: getHistory,
        getLastCheck: getLastCheck,
        severityLabel: severityLabel,
        groupLabel: groupLabel,
    };
})(typeof window !== "undefined" ? window : global);
