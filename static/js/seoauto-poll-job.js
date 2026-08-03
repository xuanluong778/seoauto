/**
 * Shared poll helper for async LLM / keyword jobs (Prompt 2.5).
 * Usage: const final = await window.SeoautoPollJob(pollUrl, { headers, signal, maxTries, intervalMs });
 */
(function (global) {
  async function SeoautoPollJob(pollUrl, options) {
    var opts = options || {};
    var headers = opts.headers || {};
    var signal = opts.signal;
    var maxTries = opts.maxTries != null ? opts.maxTries : 600;
    var intervalMs = opts.intervalMs != null ? opts.intervalMs : 1500;
    var url = String(pollUrl || "");
    if (!url) throw new Error("Thiếu poll_url.");
    for (var i = 0; i < maxTries; i++) {
      if (signal && signal.aborted) throw new Error("Đã hủy.");
      await new Promise(function (r) { setTimeout(r, intervalMs); });
      var pr = await fetch(url, { headers: headers, signal: signal, credentials: "same-origin" });
      var st = await pr.json().catch(function () { return {}; });
      if (pr.status === 403 || pr.status === 404) {
        var d = st.detail;
        throw new Error(typeof d === "string" ? d : (st.error || st.message || "Không tìm thấy job."));
      }
      if (!pr.ok) continue;
      var state = String(st.state || "");
      if (state === "QUEUED" || state === "PENDING" || state === "RUNNING") continue;
      if (state === "COMPLETED" || state === "SUCCESS") return st;
      if (state === "FAILED" || state === "ERROR") {
        throw new Error(st.error || st.message || "Job thất bại.");
      }
    }
    throw new Error("Hết thời gian chờ job.");
  }

  /** If response has job_id + poll_url, poll until done; else return data as-is. */
  async function SeoautoAwaitQueued(data, options) {
    if (data && data.job_id && data.poll_url) {
      return SeoautoPollJob(data.poll_url, options);
    }
    return data;
  }

  global.SeoautoPollJob = SeoautoPollJob;
  global.SeoautoAwaitQueued = SeoautoAwaitQueued;
})(typeof window !== "undefined" ? window : globalThis);
