// 文字轉漫畫：各頁共用的小工具（window.T2C）。設計見 docs/05_介面設計.md。
// 目前開啟的漫畫專案記在瀏覽器（FE.store 的 project），每個 API 都帶它。
(function () {
  "use strict";
  const { h } = FE;
  const RECENT_MAX = 8;

  const T2C = (window.T2C = {
    panel: null,                                         // 右欄的任務面板（app.js 建立）

    project: () => FE.store.get("project", ""),
    setProject(path) {
      FE.store.set("project", path);
      const list = T2C.recent().filter((p) => p !== path);
      list.unshift(path);
      FE.store.set("recent", list.slice(0, RECENT_MAX));
      window.dispatchEvent(new CustomEvent("t2c-project", { detail: { path } }));
    },
    recent: () => (Array.isArray(FE.store.get("recent", [])) ? FE.store.get("recent", []) : []),
    forget(path) {
      FE.store.set("recent", T2C.recent().filter((p) => p !== path));
      if (T2C.project() === path) FE.store.remove("project");
    },

    /** GET／POST 自動帶上目前的專案。 */
    get: (path, query, ctx) => FE.api(path, { query: Object.assign({ project: T2C.project() }, query || {}), signal: ctx && ctx.signal }),
    post: (path, body, ctx) => FE.api(path, { body: Object.assign({ project: T2C.project() }, body || {}), signal: ctx && ctx.signal }),

    /** 開始背景任務（進度在右邊的任務面板）。 */
    run(path, body) {
      if (!T2C.panel) return Promise.resolve(null);
      return T2C.panel.run(path, Object.assign({ project: T2C.project() }, body || {}));
    },

    /** 任務結束時：是同一個專案（與章）才呼叫 fn(job, result)。離開頁面自動取消。 */
    onJobEnd(ctx, fn, chapter) {
      const off = FE.jobs.onend((job) => {
        if (!ctx.active()) return off();
        const r = job.result || {};
        if (r.project && r.project !== T2C.project()) return;
        if (chapter && r.chapter && r.chapter !== chapter) return;
        fn(job, r);
      });
      ctx.signal.addEventListener("abort", off, { once: true });
    },

    /** 專案裡的圖（renders/、pages/、build/）；w 給了就是縮圖。v 用來避開瀏覽器快取。 */
    img(path, w, v) {
      const q = { project: T2C.project(), path };
      if (w) q.w = w;
      if (v) q.v = v;
      return `/api/image?${new URLSearchParams(q)}`;
    },

    /** 檢查結果清單；空的回傳 null。 */
    issues(list, opts = {}) {
      if (!list || !list.length) return opts.ok ? h("p", { class: "t2c-ok" }, opts.ok) : null;
      const errs = list.filter((i) => i.level === "error").length;
      const head = errs ? `${errs} 個錯誤、${list.length - errs} 則提醒` : `${list.length} 則提醒`;
      return h("details", { class: "t2c-issues", open: opts.open !== false },
        h("summary", { class: errs ? "t2c-err" : "t2c-warn" }, opts.title ? `${opts.title}：${head}` : head),
        h("ul", {}, list.map((i) => h("li", { class: i.level === "error" ? "t2c-err" : "t2c-warn" },
          i.where ? h("b", {}, `${i.where}　`) : null, i.message))));
    },

    /** 沒開專案時顯示提示並回傳 false。 */
    need(ctx, label) {
      if (T2C.project()) return true;
      ctx.crumbs([{ label: "專案", href: "#/" }, { label }]);
      ctx.view(h("div", { class: "empty" }, "還沒有開啟漫畫專案。", " ", h("a", { href: "#/" }, "到專案頁開啟或新建")));
      return false;
    },

    chip(text, kind) {
      return h("span", { class: ["chip", kind && `chip-${kind}`] }, text);
    },

    /** 文字輸入框（多行）：自動把 Tab 變成兩個空白，Ctrl+S 呼叫 onsave。 */
    editor(value, opts = {}) {
      const el = h("textarea", {
        class: ["t2c-editor", opts.mono && "t2c-mono"], spellcheck: "false", rows: opts.rows || 24,
        oninput: () => { FE.dirty.set(true); if (opts.oninput) opts.oninput(el.value); },
        onkeydown: (e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
            e.preventDefault();
            if (opts.onsave) opts.onsave();
          } else if (e.key === "Tab" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            el.setRangeText("  ", el.selectionStart, el.selectionEnd, "end");
          }
        },
      });
      el.value = value || "";
      return el;
    },

    /** 數字欄位的小工具 */
    num(value, opts = {}) {
      return h("input", Object.assign({ type: "number", class: "t2c-num", value: value === undefined || value === null ? "" : value }, opts));
    },

    label: { plan: "規劃", script: "劇本", storyboard: "分鏡", render: "出圖", pages: "頁面" },
    shot: { extreme_wide: "大遠景", wide: "遠景", full: "全身", medium: "中景", close: "近景", extreme_close: "特寫" },
    angle: { eye: "平視", high: "俯視", low: "仰視", bird: "鳥瞰", dutch: "斜角", over_shoulder: "過肩" },
    kind: { speech: "對話", thought: "心聲", shout: "喊叫", whisper: "悄悄話", narration: "旁白" },
  });

  /** 整章批次的對話框。 */
  T2C.batchDialog = function (chapter, env) {
    const stages = ["plan", "script", "storyboard", "render", "pages"];
    const boxes = {};
    const presets = (env && env.presets) || [];
    const preset = h("select", {}, presets.map((p) => h("option", { value: p, selected: p === (env && env.default_preset) }, p)));
    const force = h("input", { type: "checkbox" });
    const pages = T2C.num("", { min: 1, max: 60, placeholder: "自動" });
    const close = FE.modal({
      title: `第 ${chapter} 章：整章批次`,
      body: h("div", { class: "stack" },
        h("p", { class: "muted" }, "依序執行勾選的階段；已經有的檔案會跳過。用本機 LLM 時，文字端跑完會先請你關掉 llama-server 釋放 VRAM，再開始出圖。"),
        h("div", { class: "stack t2c-tight" }, stages.map((s) => h("label", { class: "check" },
          (boxes[s] = h("input", { type: "checkbox", checked: true })), T2C.label[s] === "頁面" ? "輸出頁面（組版＋嵌字）" : T2C.label[s]))),
        h("label", { class: "check" }, force, "重做已有的規劃、劇本、分鏡（會覆蓋；出圖永遠只補沒畫過的）"),
        h("div", { class: "row" }, h("label", { class: "row t2c-inline" }, "規劃頁數", pages),
          presets.length ? h("label", { class: "row t2c-inline" }, "出圖預設", preset) : null)),
      foot: (done) => [
        h("button", { class: "btn", type: "button", onclick: () => done(null) }, "取消"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => done(true) }, "開始"),
      ],
    });
    return close.closed.then((ok) => {
      if (!ok) return null;
      const chosen = stages.filter((s) => boxes[s].checked);
      if (!chosen.length) { FE.toast("至少要選一個階段", "warn"); return null; }
      if (force.checked && !window.confirm) return null;
      return T2C.run("/api/task/batch", { chapter, stages: chosen, force: force.checked, preset: preset.value || null, pages: pages.value ? Number(pages.value) : null });
    });
  };
})();
