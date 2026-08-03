/**
 * CAU Sửa SEO — block editor (parse/serialize + UI).
 * Mirrors app/services/cau_block_model.py for round-trip fidelity.
 */
(function (global) {
    "use strict";

    function newBlockId() {
        return "blk_" + Math.random().toString(16).slice(2) + Date.now().toString(16).slice(-4);
    }

    var GUTENBERG_OPEN = /<!--\s*wp:([a-z0-9\-\/]+)(\s+(\{[\s\S]*?\}))?\s*(\/)?-->/gi;
    var TOP_TAG = /(<!--[\s\S]*?-->)|(<(?<tag>h[1-6]|p|ul|ol|table|figure|blockquote|pre|hr|div|section|aside|nav|header|footer|article|form|iframe|video|audio|img|address)(?:\s[^>]*)?(?:\/>|>[\s\S]*?<\/\k<tag>\s*>))/gi;

    function detectType(html) {
        var raw = String(html || "").trim();
        if (!raw) return { type: "html", meta: {} };
        var low = raw.toLowerCase();
        if (low.indexOf("<!-- wp:") === 0 || low.indexOf("<!--wp:") === 0) {
            GUTENBERG_OPEN.lastIndex = 0;
            var gm = GUTENBERG_OPEN.exec(raw);
            var name = (gm && gm[1] ? gm[1] : "block").toLowerCase();
            var meta = { gutenberg: name };
            if (name.indexOf("heading") >= 0) {
                var hm = raw.match(/<h([1-6])\b/i);
                meta.level = hm ? parseInt(hm[1], 10) : 2;
                return { type: "heading", meta: meta };
            }
            if (name.indexOf("paragraph") >= 0) return { type: "paragraph", meta: meta };
            if (name.indexOf("list") >= 0) return { type: "list", meta: meta };
            if (name.indexOf("table") >= 0) return { type: "table", meta: meta };
            if (name.indexOf("image") >= 0) return { type: "image", meta: meta };
            if (name.indexOf("embed") >= 0 || name.indexOf("video") >= 0) return { type: "embed", meta: meta };
            if (name.indexOf("shortcode") >= 0) return { type: "shortcode", meta: meta };
            return { type: "gutenberg", meta: meta };
        }
        if (/^\[\/?[a-zA-Z]/.test(raw)) return { type: "shortcode", meta: {} };
        var h = raw.match(/^<h([1-6])\b/i);
        if (h) return { type: "heading", meta: { level: parseInt(h[1], 10) } };
        if (/^<(ul|ol)\b/i.test(raw)) return { type: "list", meta: {} };
        if (/^<table\b/i.test(raw)) return { type: "table", meta: {} };
        if (/^<(figure|img)\b/i.test(raw)) return { type: "image", meta: {} };
        if (/^<(iframe|embed|video|audio)\b/i.test(raw)) return { type: "embed", meta: {} };
        if (/^<p\b/i.test(raw)) return { type: "paragraph", meta: {} };
        return { type: "html", meta: {} };
    }

    function makeBlock(html, extra) {
        var det = detectType(html);
        var meta = Object.assign({}, det.meta, (extra && extra.meta) || {});
        return {
            block_id: (extra && extra.block_id) || newBlockId(),
            block_type: (extra && extra.block_type) || det.type,
            original_content: String(html || ""),
            current_content: String(html || ""),
            locked: !!(extra && extra.locked),
            changed: !!(extra && extra.changed),
            meta: meta,
        };
    }

    function parseGutenberg(text) {
        var low = text.toLowerCase();
        if (low.indexOf("<!-- wp:") < 0 && low.indexOf("<!--wp:") < 0) return null;
        var blocks = [];
        var i = 0;
        var n = text.length;
        while (i < n) {
            GUTENBERG_OPEN.lastIndex = i;
            var m = GUTENBERG_OPEN.exec(text);
            if (!m) {
                var tail = text.slice(i);
                if (tail) blocks.push(makeBlock(tail));
                break;
            }
            if (m.index > i) {
                var gap = text.slice(i, m.index);
                if (gap) blocks.push(makeBlock(gap));
            }
            var selfClose = !!m[4];
            var name = m[1];
            if (selfClose) {
                blocks.push(makeBlock(text.slice(m.index, m.index + m[0].length)));
                i = m.index + m[0].length;
                continue;
            }
            var rest = text.slice(m.index + m[0].length);
            var closeRe = new RegExp("<!--\\s*/wp:" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*-->", "i");
            var close = closeRe.exec(rest);
            if (!close) {
                blocks.push(makeBlock(text.slice(m.index)));
                break;
            }
            var end = m.index + m[0].length + close.index + close[0].length;
            blocks.push(makeBlock(text.slice(m.index, end)));
            i = end;
        }
        return blocks;
    }

    function parseClassic(text) {
        var blocks = [];
        var src = String(text || "");
        if (!src.trim()) return [];

        if (typeof DOMParser !== "undefined") {
            try {
                var doc = new DOMParser().parseFromString(
                    "<!DOCTYPE html><html><body>" + src + "</body></html>",
                    "text/html"
                );
                var body = doc && doc.body;
                if (body) {
                    var nodes = body.childNodes;
                    for (var i = 0; i < nodes.length; i++) {
                        var node = nodes[i];
                        if (node.nodeType === 1) {
                            blocks.push(makeBlock(node.outerHTML));
                        } else if (node.nodeType === 3) {
                            var tx = node.textContent || "";
                            if (tx.trim()) blocks.push(makeBlock(tx));
                        } else if (node.nodeType === 8) {
                            blocks.push(makeBlock("<!--" + node.textContent + "-->"));
                        }
                    }
                    if (blocks.length) return blocks;
                }
            } catch (_) {}
        }

        var pos = 0;
        var n = src.length;
        var guard = 0;
        var maxIter = Math.max(8000, Math.ceil(n / 8));
        TOP_TAG.lastIndex = 0;
        while (pos < n && guard < maxIter) {
            guard++;
            TOP_TAG.lastIndex = pos;
            var m = TOP_TAG.exec(src);
            if (!m) {
                var tail = src.slice(pos);
                if (tail) blocks.push(makeBlock(tail));
                break;
            }
            if (m.index > pos) {
                var gap = src.slice(pos, m.index);
                if (gap) blocks.push(makeBlock(gap));
            }
            var chunk = m[0];
            if (!chunk) {
                pos++;
                continue;
            }
            blocks.push(makeBlock(chunk));
            pos = m.index + chunk.length;
        }
        if (!blocks.length && src.trim()) blocks.push(makeBlock(src));
        return blocks;
    }

    function parseBlocks(html) {
        var text = String(html || "");
        if (!text.trim()) return [];
        var g = parseGutenberg(text);
        return g || parseClassic(text);
    }

    function serializeBlocks(blocks) {
        return (blocks || []).map(function (b) {
            return b.changed ? b.current_content : b.original_content;
        }).join("");
    }

    function headingLevel(b) {
        if (!b) return null;
        if (b.meta && b.meta.level) return parseInt(b.meta.level, 10);
        var m = String(b.current_content || "").match(/<h([1-6])\b/i);
        if (m) return parseInt(m[1], 10);
        if (b.block_type === "heading") return 2;
        return null;
    }

    function sectionRange(blocks, index) {
        var level = headingLevel(blocks[index]);
        if (level == null) return { start: index, end: index + 1 };
        var end = index + 1;
        while (end < blocks.length) {
            var hl = headingLevel(blocks[end]);
            if (hl != null && hl <= level) break;
            end++;
        }
        return { start: index, end: end };
    }

    function moveSection(blocks, index, direction) {
        var out = blocks.slice();
        var level = headingLevel(out[index]);
        if (level == null) return out;
        var range = sectionRange(out, index);
        var chunk = out.slice(range.start, range.end);
        if (direction === "up") {
            var prev = range.start - 1;
            while (prev >= 0) {
                var hl = headingLevel(out[prev]);
                if (hl != null && hl === level) {
                    var pStart = sectionRange(out, prev).start;
                    out.splice(range.start, range.end - range.start);
                    out.splice.apply(out, [pStart, 0].concat(chunk));
                    return out;
                }
                if (hl != null && hl < level) break;
                prev--;
            }
            return out;
        }
        if (direction === "down") {
            var nxt = range.end;
            while (nxt < out.length) {
                var hl2 = headingLevel(out[nxt]);
                if (hl2 != null && hl2 === level) {
                    var nEnd = sectionRange(out, nxt).end;
                    out.splice(range.start, range.end - range.start);
                    var insertAt = nEnd - (range.end - range.start);
                    out.splice.apply(out, [insertAt, 0].concat(chunk));
                    return out;
                }
                if (hl2 != null && hl2 < level) break;
                nxt++;
            }
        }
        return out;
    }

    /** Di chuyển section tới trước block index ``toIndex`` (dùng khi kéo thả trong cây cấu trúc). */
    function moveSectionToIndex(blocks, fromIndex, toIndex) {
        if (!blocks.length) return blocks.slice();
        fromIndex = Math.max(0, Math.min(fromIndex, blocks.length - 1));
        toIndex = Math.max(0, Math.min(toIndex, blocks.length));
        var fromRange = sectionRange(blocks, fromIndex);
        var chunk = blocks.slice(fromRange.start, fromRange.end);
        var next = blocks.slice();
        next.splice(fromRange.start, fromRange.end - fromRange.start);
        var insertAt = toIndex;
        if (toIndex > fromRange.start) insertAt -= chunk.length;
        if (insertAt < 0) insertAt = 0;
        if (insertAt > next.length) insertAt = next.length;
        next.splice.apply(next, [insertAt, 0].concat(chunk));
        return next;
    }

    function changeHeadingLevel(block, newLevel) {
        var lvl = Math.max(1, Math.min(6, parseInt(newLevel, 10) || 2));
        var html = String(block.current_content || "");
        html = html.replace(/<h([1-6])(\b)/i, "<h" + lvl + "$2");
        html = html.replace(/<\/h([1-6])\s*>/i, "</h" + lvl + ">");
        html = html.replace(/("level"\s*:\s*)\d+/, "$1" + lvl);
        var b = Object.assign({}, block, {
            current_content: html,
            changed: html !== block.original_content,
            meta: Object.assign({}, block.meta || {}, { level: lvl }),
        });
        return b;
    }

    function insertHeadingHtml(opts) {
        var lvl = Math.max(2, Math.min(4, parseInt(opts.level, 10) || 2));
        var title = String(opts.title || "")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        var parts = ["<h" + lvl + ">" + title + "</h" + lvl + ">"];
        var body = String(opts.bodyHtml || "").trim();
        if (body) parts.push(body.indexOf("<") === 0 ? body : "<p>" + body + "</p>");
        return parts.join("");
    }

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function plainText(html) {
        return String(html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    }

    var HEADING_OPEN_RE = /<h([1-6])\b[^>]*>/gi;

    function countHeadings(html) {
        var n = 0;
        var re = new RegExp(HEADING_OPEN_RE.source, "gi");
        var m;
        while ((m = re.exec(String(html || ""))) !== null) n++;
        return n;
    }

    /** Tách tại MỖI thẻ heading → mỗi phần chỉ còn tối đa 1 heading (tránh lặp vô hạn). */
    function splitHtmlIntoHeadingSections(html) {
        var text = String(html || "");
        if (!text.trim()) return [];
        var starts = [];
        var m;
        HEADING_OPEN_RE.lastIndex = 0;
        while ((m = HEADING_OPEN_RE.exec(text)) !== null) {
            starts.push(m.index);
        }
        if (!starts.length) return [text];
        if (starts.length === 1) return [text];
        var sections = [];
        if (starts[0] > 0) {
            var prefix = text.slice(0, starts[0]);
            if (prefix.trim()) sections.push(prefix);
        }
        for (var i = 0; i < starts.length; i++) {
            var end = (i + 1 < starts.length) ? starts[i + 1] : text.length;
            sections.push(text.slice(starts[i], end));
        }
        return sections.filter(function (s) { return String(s || "").trim(); });
    }

    /** Block chứa 2+ heading → tách thành block riêng (lặp đến khi ổn định). */
    function explodeBlocksByHeadingSections(blocks) {
        var out = blocks.slice();
        var guard = 0;
        while (guard < 32) {
            guard++;
            var next = [];
            var changed = false;
            out.forEach(function (b) {
                var sections = splitHtmlIntoHeadingSections(b.current_content);
                if (sections.length <= 1) {
                    next.push(b);
                    return;
                }
                changed = true;
                sections.forEach(function (html, i) {
                    var nb = makeBlock(html, {
                        block_id: i === 0 ? b.block_id : newBlockId(),
                        locked: b.locked,
                        changed: true,
                    });
                    if (i === 0 && !b.changed) {
                        nb.original_content = b.original_content;
                        nb.changed = html !== b.original_content;
                    } else {
                        nb.original_content = html;
                        nb.changed = true;
                    }
                    next.push(nb);
                });
            });
            out = next;
            if (!changed || !blocksNeedHeadingExplode(out)) break;
        }
        return out;
    }

    function blocksNeedHeadingExplode(blocks) {
        for (var i = 0; i < (blocks || []).length; i++) {
            if (countHeadings(blocks[i].current_content) > 1) return true;
        }
        return false;
    }

    function headingLabelText(block) {
        var content = String((block && block.current_content) || "");
        var m = content.match(/<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/i);
        if (m) return plainText(m[2]);
        return plainText(content);
    }

    function typeLabel(t) {
        var map = {
            heading: "Heading", paragraph: "Đoạn văn", list: "Danh sách", table: "Bảng",
            image: "Ảnh", shortcode: "Shortcode", embed: "Embed", gutenberg: "Gutenberg", html: "HTML",
        };
        return map[t] || t;
    }

    function History(limit) {
        this.limit = limit || 50;
        this._undo = [];
        this._redo = [];
    }
    History.prototype.push = function (blocks) {
        this._undo.push(JSON.parse(JSON.stringify(blocks)));
        if (this._undo.length > this.limit) this._undo.shift();
        this._redo = [];
    };
    History.prototype.undo = function (current) {
        if (!this._undo.length) return null;
        this._redo.push(JSON.parse(JSON.stringify(current)));
        return this._undo.pop();
    };
    History.prototype.redo = function (current) {
        if (!this._redo.length) return null;
        this._undo.push(JSON.parse(JSON.stringify(current)));
        return this._redo.pop();
    };

    function Editor(opts) {
        this.mount = opts.mount;
        this.structureMount = opts.structureMount || null;
        this.onChange = opts.onChange || function () {};
        this.blocks = [];
        this.history = new History();
        this.insertIndex = 0;
        this.selectedId = null;
        this.onSelect = opts.onSelect || null;
        this._dragId = null;
        this._structureActive = false;
        this._structBusy = false;
        this._loadGen = 0;
    }

    Editor.prototype.setStructureActive = function (active) {
        this._structureActive = !!active;
        if (this._structureActive) this.renderStructure();
    };

    Editor.prototype._maybeRenderStructure = function () {
        if (this._structureActive && this.structureMount) this.renderStructure();
    };

    Editor.prototype._applyParsedBlocks = function (blocks) {
        this.blocks = blocks || [];
        this.history = new History();
        this.render();
        this._maybeRenderStructure();
        this.onChange(this.getHtml());
    };

    Editor.prototype.loadHtml = function (html) {
        var self = this;
        var text = String(html || "");
        var gen = ++this._loadGen;
        if (!text.trim()) {
            this._applyParsedBlocks([]);
            return;
        }
        var run = function () {
            if (gen !== self._loadGen) return;
            self._applyParsedBlocks(parseBlocks(text));
        };
        if (text.length > 40000 && typeof requestAnimationFrame === "function") {
            this.blocks = [];
            this.render();
            requestAnimationFrame(run);
            return;
        }
        run();
    };

    Editor.prototype.loadBlocks = function (blocks) {
        var mapped = (blocks || []).map(function (b) {
            return {
                block_id: b.block_id,
                block_type: b.block_type || "html",
                original_content: b.original_content != null ? b.original_content : (b.current_content || ""),
                current_content: b.current_content || "",
                locked: !!b.locked,
                changed: !!b.changed,
                meta: b.meta || {},
            };
        });
        this._applyParsedBlocks(mapped);
    };

    Editor.prototype.getBlocksPayload = function () {
        return this.blocks.map(function (b) {
            return {
                block_id: b.block_id,
                block_type: b.block_type,
                original_content: b.original_content,
                current_content: b.current_content,
                locked: !!b.locked,
                changed: !!b.changed,
                meta: b.meta || {},
            };
        });
    };

    Editor.prototype.getSelectedBlock = function () {
        var idx = this._blockIndex(this.selectedId);
        return idx >= 0 ? this.blocks[idx] : null;
    };

    Editor.prototype.getHtml = function () {
        return serializeBlocks(this.blocks);
    };

    Editor.prototype._commit = function (next, opts) {
        if (!(opts && opts.skipHistory)) this.history.push(this.blocks);
        this.blocks = next;
        this.render();
        this._maybeRenderStructure();
        this.onChange(this.getHtml());
    };

    Editor.prototype.undo = function () {
        var prev = this.history.undo(this.blocks);
        if (!prev) return;
        this.blocks = prev;
        this.render();
        this._maybeRenderStructure();
        this.onChange(this.getHtml());
    };

    Editor.prototype.redo = function () {
        var next = this.history.redo(this.blocks);
        if (!next) return;
        this.blocks = next;
        this.render();
        this._maybeRenderStructure();
        this.onChange(this.getHtml());
    };

    Editor.prototype._blockIndex = function (id) {
        for (var i = 0; i < this.blocks.length; i++) {
            if (this.blocks[i].block_id === id) return i;
        }
        return -1;
    };

    Editor.prototype.render = function () {
        var root = this.mount;
        if (!root) return;
        var self = this;
        var html = [];
        html.push('<div class="cau-be-toolbar">');
        html.push('<button type="button" class="mini-btn" data-cau-be="undo" title="Undo">Undo</button>');
        html.push('<button type="button" class="mini-btn" data-cau-be="redo" title="Redo">Redo</button>');
        html.push('<span class="cau-be-toolbar__hint">Block editor · giữ HTML / Gutenberg / shortcode</span>');
        html.push("</div>");
        html.push('<div class="cau-be-list">');
        html.push(this._inserterHtml(0));
        this.blocks.forEach(function (b, idx) {
            if (!String(b.current_content || "").trim() && b.block_type === "html") {
                // still show whitespace-only as thin spacer without heavy chrome
                html.push('<div class="cau-be-gap" data-block-id="' + esc(b.block_id) + '"></div>');
                html.push(self._inserterHtml(idx + 1));
                return;
            }
            var lvl = headingLevel(b);
            var cls = "cau-be-block" +
                (b.changed ? " is-changed" : "") +
                (b.locked ? " is-locked" : "") +
                (self.selectedId === b.block_id ? " is-selected" : "");
            html.push('<article class="' + cls + '" data-block-id="' + esc(b.block_id) + '" draggable="false">');
            html.push('<header class="cau-be-block__head">');
            html.push('<span class="cau-be-block__type">' + esc(typeLabel(b.block_type)) +
                (lvl ? (" H" + lvl) : "") + "</span>");
            if (b.changed) html.push('<span class="cau-be-pill">Đã sửa</span>');
            if (b.locked) html.push('<span class="cau-be-pill cau-be-pill--lock">Khóa AI</span>');
            html.push('<div class="cau-be-block__menu">');
            html.push('<button type="button" class="mini-btn" data-cau-be-act="up" title="Chuyển lên trên">↑</button>');
            html.push('<button type="button" class="mini-btn" data-cau-be-act="down" title="Chuyển xuống dưới">↓</button>');
            html.push('<span class="cau-be-more">');
            html.push('<button type="button" class="mini-btn cau-be-more__btn" data-cau-be-more title="Thao tác khác" aria-haspopup="true" aria-expanded="false">⋯</button>');
            html.push('<span class="cau-be-more__menu" hidden>');
            html.push('<button type="button" data-cau-be-act="lock">' +
                (b.locked ? "Mở khóa AI" : "Khóa AI (không cho AI sửa)") + "</button>");
            html.push('<button type="button" data-cau-be-act="dup">Nhân bản</button>');
            html.push('<button type="button" data-cau-be-act="del" class="cau-be-more__danger">Xóa</button>');
            html.push("</span></span>");
            html.push("</div></header>");
            if (b.locked) {
                html.push('<div class="cau-be-block__body cau-be-block__body--locked">' + b.current_content + "</div>");
            } else {
                html.push('<div class="cau-be-block__body" contenteditable="true" data-cau-be-edit="1">' +
                    b.current_content + "</div>");
            }
            html.push("</article>");
            html.push(self._inserterHtml(idx + 1));
        });
        html.push("</div>");
        root.innerHTML = html.join("");
        this._bind();
    };

    Editor.prototype._inserterHtml = function (index) {
        return (
            '<div class="cau-be-inserter" data-insert-at="' + index + '">' +
            '<button type="button" class="cau-be-inserter__btn" data-cau-be="insert" title="Thêm nội dung tại vị trí này">' +
            '<span class="cau-be-inserter__plus" aria-hidden="true">+</span>' +
            '<span class="cau-be-inserter__label">Thêm nội dung</span>' +
            "</button>" +
            "</div>"
        );
    };

    Editor.prototype._bind = function () {
        var self = this;
        var root = this.mount;
        if (!root) return;
        root.querySelectorAll("[data-cau-be='undo']").forEach(function (btn) {
            btn.addEventListener("click", function () { self.undo(); });
        });
        root.querySelectorAll("[data-cau-be='redo']").forEach(function (btn) {
            btn.addEventListener("click", function () { self.redo(); });
        });
        root.querySelectorAll("[data-cau-be='insert']").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var wrap = btn.closest("[data-insert-at]");
                self.insertIndex = wrap ? parseInt(wrap.getAttribute("data-insert-at"), 10) || 0 : 0;
                if (typeof self.onRequestInsert === "function") self.onRequestInsert(self.insertIndex);
            });
        });
        // Click anywhere in the editor closes any open «⋯» menu
        root.addEventListener("click", function () {
            root.querySelectorAll(".cau-be-more__menu").forEach(function (m) { m.hidden = true; });
        });
        root.querySelectorAll(".cau-be-block").forEach(function (el) {
            var id = el.getAttribute("data-block-id");
            el.addEventListener("click", function () {
                self.selectedId = id;
                root.querySelectorAll(".cau-be-block.is-selected").forEach(function (x) {
                    x.classList.remove("is-selected");
                });
                el.classList.add("is-selected");
                if (typeof self.onSelect === "function") {
                    var idx = self._blockIndex(id);
                    self.onSelect(idx >= 0 ? self.blocks[idx] : null);
                }
            });
            el.querySelectorAll("[data-cau-be-act]").forEach(function (btn) {
                btn.addEventListener("click", function (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    var menu = btn.closest(".cau-be-more__menu");
                    if (menu) menu.hidden = true;
                    self._menuAction(id, btn.getAttribute("data-cau-be-act"));
                });
            });
            var moreBtn = el.querySelector("[data-cau-be-more]");
            if (moreBtn) {
                moreBtn.addEventListener("click", function (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    var menu = moreBtn.parentElement.querySelector(".cau-be-more__menu");
                    if (!menu) return;
                    var willOpen = menu.hidden;
                    root.querySelectorAll(".cau-be-more__menu").forEach(function (m) { m.hidden = true; });
                    menu.hidden = !willOpen;
                    moreBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
                });
            }
            var body = el.querySelector("[data-cau-be-edit]");
            if (body) {
                var timer = null;
                body.addEventListener("input", function () {
                    clearTimeout(timer);
                    timer = setTimeout(function () {
                        var idx = self._blockIndex(id);
                        if (idx < 0) return;
                        var next = self.blocks.slice();
                        var b = Object.assign({}, next[idx]);
                        b.current_content = body.innerHTML;
                        b.changed = b.current_content !== b.original_content;
                        next[idx] = b;
                        // debounce history: push once per burst via skip then manual
                        self.blocks = next;
                        self._maybeRenderStructure();
                        self.onChange(self.getHtml());
                    }, 350);
                });
                body.addEventListener("blur", function () {
                    var idx = self._blockIndex(id);
                    if (idx < 0) return;
                    var cur = self.blocks[idx];
                    if (body.innerHTML === cur.current_content && !cur.changed) return;
                    var next = self.blocks.slice();
                    var b = Object.assign({}, next[idx]);
                    self.history.push(self.blocks);
                    b.current_content = body.innerHTML;
                    b.changed = b.current_content !== b.original_content;
                    next[idx] = b;
                    self.blocks = next;
                    self._maybeRenderStructure();
                    self.onChange(self.getHtml());
                });
            }
        });
    };

    Editor.prototype._menuAction = function (id, act) {
        var idx = this._blockIndex(id);
        if (idx < 0) return;
        var next = this.blocks.slice();
        var b = next[idx];
        if (act === "lock") {
            this.history.push(this.blocks);
            next[idx] = Object.assign({}, b, { locked: !b.locked });
            this._commit(next, { skipHistory: true });
            return;
        }
        if (act === "dup") {
            var copy = makeBlock(b.current_content, { changed: true });
            next.splice(idx + 1, 0, copy);
            this._commit(next);
            return;
        }
        if (act === "del") {
            if (!window.confirm("Xóa block này?")) return;
            next.splice(idx, 1);
            this._commit(next);
            return;
        }
        if (act === "up" || act === "down") {
            if (headingLevel(b) != null) {
                next = moveSection(this.blocks, idx, act);
            } else {
                var swap = act === "up" ? idx - 1 : idx + 1;
                if (swap < 0 || swap >= next.length) return;
                this.history.push(this.blocks);
                var tmp = next[idx];
                next[idx] = next[swap];
                next[swap] = tmp;
                this._commit(next, { skipHistory: true });
                return;
            }
            this._commit(next);
        }
    };

    Editor.prototype.insertAt = function (index, html, markChanged) {
        var parts = parseBlocks(html);
        if (markChanged) {
            parts.forEach(function (p) {
                p.changed = true;
                p.original_content = p.current_content;
            });
        }
        var next = this.blocks.slice();
        var i = Math.max(0, Math.min(index, next.length));
        for (var k = 0; k < parts.length; k++) next.splice(i + k, 0, parts[k]);
        this._commit(next);
    };

    Editor.prototype._ensureHeadingSections = function () {
        if (!blocksNeedHeadingExplode(this.blocks)) return false;
        var next = explodeBlocksByHeadingSections(this.blocks);
        var same = next.length === this.blocks.length;
        if (same) {
            for (var i = 0; i < next.length; i++) {
                if (next[i].block_id !== this.blocks[i].block_id ||
                    next[i].current_content !== this.blocks[i].current_content) {
                    same = false;
                    break;
                }
            }
        }
        if (same) return false;
        this.history.push(this.blocks);
        this.blocks = next;
        this.render();
        this.onChange(this.getHtml());
        return true;
    };

    Editor.prototype.renderStructure = function () {
        var root = this.structureMount;
        if (!root) return;
        if (this._structBusy) return;
        if (blocksNeedHeadingExplode(this.blocks)) {
            this._structBusy = true;
            try {
                this._ensureHeadingSections();
            } finally {
                this._structBusy = false;
            }
            if (blocksNeedHeadingExplode(this.blocks)) return;
        }
        var self = this;
        var truncate = function (t, max) {
            t = String(t || "").trim();
            return t.length > max ? t.slice(0, max).replace(/\s+\S*$/, "") + "…" : t;
        };
        var items = [];
        this.blocks.forEach(function (b, idx) {
            var lvl = headingLevel(b);
            if (lvl == null) return;
            items.push({
                idx: idx, id: b.block_id, level: lvl,
                text: truncate(headingLabelText(b), 90), locked: b.locked,
            });
        });
        var html = [];
        html.push('<div class="cau-struct-toolbar">');
        html.push('<button type="button" class="mini-btn" data-cau-struct="refresh">Làm mới cây</button>');
        html.push('<span class="cau-struct-hint">Bấm heading để nhảy tới vị trí trong bài · rê chuột để hiện thao tác</span>');
        html.push("</div>");
        html.push('<ul class="cau-struct-tree" role="tree">');
        if (!items.length) {
            html.push('<li class="cau-struct-empty">Chưa có heading H1–H4 trong bài.</li>');
        }
        items.forEach(function (it) {
            html.push(
                '<li class="cau-struct-item cau-struct-item--h' + it.level + '" draggable="true" data-struct-id="' +
                esc(it.id) + '" data-struct-idx="' + it.idx + '" style="--cau-indent:' + Math.max(0, it.level - 2) + '">' +
                '<div class="cau-struct-row">' +
                '<span class="cau-struct-badge cau-struct-badge--h' + it.level + '">H' + it.level + "</span>" +
                '<button type="button" class="cau-struct-label" data-cau-struct="goto" title="Bấm để nhảy tới heading này trong bài">' +
                esc(it.text || "(trống)") + "</button>" +
                '<span class="cau-struct-actions">' +
                '<button type="button" class="mini-btn" data-cau-struct="up" title="Chuyển mục lên 1 vị trí">↑</button>' +
                '<button type="button" class="mini-btn" data-cau-struct="down" title="Chuyển mục xuống 1 vị trí">↓</button>' +
                '<button type="button" class="mini-btn" data-cau-struct="level-up" title="Tăng cấp (H3 → H2)">H-</button>' +
                '<button type="button" class="mini-btn" data-cau-struct="level-down" title="Giảm cấp (H2 → H3)">H+</button>' +
                '<button type="button" class="mini-btn" data-cau-struct="add-after" title="Thêm heading phía sau">+</button>' +
                '<button type="button" class="mini-btn" data-cau-struct="lock" title="' + (it.locked ? "Cho phép AI sửa lại" : "Không cho AI sửa mục này") + '">' + (it.locked ? "Mở" : "Khóa") + "</button>" +
                '<button type="button" class="mini-btn" data-cau-struct="del" title="Xóa mục này">Xóa</button>' +
                "</span></div></li>"
            );
        });
        html.push("</ul>");
        root.innerHTML = html.join("");

        root.querySelectorAll("[data-cau-struct='refresh']").forEach(function (btn) {
            btn.addEventListener("click", function () { self.renderStructure(); });
        });
        root.querySelectorAll(".cau-struct-item").forEach(function (li) {
            var id = li.getAttribute("data-struct-id");
            var idx = parseInt(li.getAttribute("data-struct-idx"), 10);
            li.querySelectorAll("[data-cau-struct]").forEach(function (btn) {
                var act = btn.getAttribute("data-cau-struct");
                if (act === "refresh") return;
                btn.addEventListener("click", function (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    self._structureAction(id, idx, act);
                });
            });
            li.addEventListener("dragstart", function (ev) {
                self._dragId = id;
                ev.dataTransfer.setData("text/plain", id);
                ev.dataTransfer.effectAllowed = "move";
            });
            li.addEventListener("dragover", function (ev) {
                ev.preventDefault();
                li.classList.add("is-drop");
            });
            li.addEventListener("dragleave", function () { li.classList.remove("is-drop"); });
            li.addEventListener("drop", function (ev) {
                ev.preventDefault();
                li.classList.remove("is-drop");
                var fromId = self._dragId || ev.dataTransfer.getData("text/plain");
                var toIdx = parseInt(li.getAttribute("data-struct-idx"), 10);
                if (!fromId || isNaN(toIdx)) return;
                var fromIdx = self._blockIndex(fromId);
                if (fromIdx < 0 || fromIdx === toIdx) return;
                self._commit(moveSectionToIndex(self.blocks, fromIdx, toIdx));
            });
        });
    };

    Editor.prototype._structureAction = function (id, idx, act) {
        var self = this;
        if (blocksNeedHeadingExplode(this.blocks)) {
            this._ensureHeadingSections();
            return;
        }
        var index = this._blockIndex(id);
        if (index < 0) index = idx;
        if (act === "goto") {
            var el = this.mount && this.mount.querySelector('[data-block-id="' + id + '"]');
            if (el) {
                el.scrollIntoView({ behavior: "smooth", block: "center" });
                this.selectedId = id;
                this.render();
            }
            return;
        }
        if (act === "up" || act === "down") {
            this._commit(moveSection(this.blocks, index, act));
            return;
        }
        if (act === "level-up" || act === "level-down") {
            var b = this.blocks[index];
            var lvl = headingLevel(b) || 2;
            var nextLvl = act === "level-up" ? Math.max(1, lvl - 1) : Math.min(6, lvl + 1);
            var next = this.blocks.slice();
            next[index] = changeHeadingLevel(b, nextLvl);
            this._commit(next);
            return;
        }
        if (act === "lock") {
            var nextL = this.blocks.slice();
            nextL[index] = Object.assign({}, nextL[index], { locked: !nextL[index].locked });
            this.history.push(this.blocks);
            this._commit(nextL, { skipHistory: true });
            return;
        }
        if (act === "del") {
            if (!window.confirm("Xóa toàn bộ section (heading + nội dung con)?")) return;
            var range = sectionRange(this.blocks, index);
            var nextD = this.blocks.slice();
            nextD.splice(range.start, range.end - range.start);
            this._commit(nextD);
            return;
        }
        if (act === "add-before" || act === "add-after" || act === "add-child") {
            var baseLvl = headingLevel(this.blocks[index]) || 2;
            var newLvl = act === "add-child" ? Math.min(4, baseLvl + 1) : baseLvl;
            var insertAt = act === "add-before" ? index : sectionRange(this.blocks, index).end;
            if (act === "add-after") insertAt = index + 1;
            this.insertIndex = insertAt;
            if (typeof this.onRequestInsert === "function") {
                this.onRequestInsert(insertAt, { presetLevel: newLvl, forceHeading: true });
            } else {
                var html = insertHeadingHtml({ title: "Heading mới", level: newLvl });
                this.insertAt(insertAt, html, true);
            }
        }
    };

    global.CauBlockEditor = {
        parseBlocks: parseBlocks,
        serializeBlocks: serializeBlocks,
        insertHeadingHtml: insertHeadingHtml,
        headingLevel: headingLevel,
        moveSection: moveSection,
        moveSectionToIndex: moveSectionToIndex,
        explodeBlocksByHeadingSections: explodeBlocksByHeadingSections,
        splitHtmlIntoHeadingSections: splitHtmlIntoHeadingSections,
        changeHeadingLevel: changeHeadingLevel,
        makeBlock: makeBlock,
        History: History,
        Editor: Editor,
        roundtripUnchanged: function (html) {
            return serializeBlocks(parseBlocks(html)) === String(html || "");
        },
    };
})(typeof window !== "undefined" ? window : globalThis);
