// 專案的三個入口頁（LAYOUT A）：`#/new` 新建專案、`#/projects` 開啟專案、`#/project` 總覽。
// 中間一次只放一件事；章節在 chapter.js，聖經、嵌字、設定各自有自己的檔。
(function () {
  "use strict";
  const { h, PAGES } = FE;

  /* ──────────────── 畫風預設集（GET /api/styles） ──────────────── */

  // 新建與總覽的換畫風共用一份；頁面層級的變數，重新載入頁面才會重抓。
  let stylesCache = null;
  function loadStyles(ctx) {
    if (!stylesCache) {
      stylesCache = T2C.get("/api/styles", {}, ctx)
        .then((data) => ({ presets: ((data && data.presets) || []).filter((p) => p && p.name),
                           fallback: (data && data.default) || "" }))
        .catch((error) => { stylesCache = null; throw error; });
    }
    return stylesCache;
  }

  const styleOptions = (presets) => presets.map((p) => h("option", { value: p.name }, `${p.label}（${p.name}）`));

  function styleLabel(presets, name) {
    const found = presets.find((p) => p.name === name);
    return found ? found.label : String(name || "－");
  }

  function stageCell(value, unit) {
    return value === null || value === undefined ? h("span", { class: "muted" }, "－") : `${value}${unit || ""}`;
  }

  function progress(done, total) {
    if (!total) return h("span", { class: "muted" }, "－");
    return h("span", { class: done >= total ? "t2c-ok" : "" }, `${done}／${total}`);
  }

  /* ──────────────── #/projects 開啟專案 ──────────────── */

  function openForm(ctx) {
    const input = h("input", { type: "text", class: "grow", placeholder: "E:\\comics\\作品名（有 project.yaml 的資料夾）", value: T2C.project() });
    const open = async (path) => {
      path = (path || input.value).trim();
      if (!path) return FE.toast("請輸入專案資料夾", "warn");
      try {
        await FE.api("/api/project", { query: { project: path }, signal: ctx.signal });
        T2C.setProject(path);
        FE.go("#/project");                                             // 開完就進總覽，不在同一頁堆三個表單
      } catch (error) { FE.fail(error); }
    };
    const browse = async () => {
      const path = await FE.filepicker.open({ mode: "dir", title: "選擇漫畫專案資料夾", start: input.value || undefined });
      if (path) { input.value = path; open(path); }
    };
    const recent = T2C.recent();
    return h("div", { class: "stack" },
      h("section", { class: "card stack" },
        h("h2", { class: "card-title" }, "開啟一個已經存在的專案"),
        h("div", { class: "row" }, input,
          h("button", { class: "btn", type: "button", onclick: browse }, "瀏覽…"),
          h("button", { class: "btn btn-primary", type: "button", onclick: () => open() }, "開啟")),
        h("p", { class: "muted t2c-small" }, "貼上專案資料夾的路徑（裡面要有 project.yaml）。沒開過專案的話，先", h("a", { href: "#/new" }, "新建一個"), "。")),
      recent.length ? h("section", { class: "card stack" },
        h("h2", { class: "card-title" }, "最近開過"),
        h("div", { class: "stack t2c-tight" }, recent.map((p) => h("div", { class: "row t2c-recent" },
          h("button", { class: ["btn btn-sm", p === T2C.project() ? "btn-primary" : "btn-ghost"], type: "button", title: p, onclick: () => open(p) },
            p.split(/[\\/]/).filter(Boolean).slice(-2).join(" / ")),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "從清單移除", "aria-label": "從清單移除",
            onclick: () => { T2C.forget(p); FE.route(); } }, "×")))))
        : null);
  }

  /* ──────────────── #/new 新建專案 ──────────────── */

  function createForm(ctx) {
    const path = h("input", { type: "text", class: "grow", placeholder: "新資料夾的完整路徑，例如 E:\\comics\\屋頂的便當" });
    const title = h("input", { type: "text", placeholder: "作品名" });
    const preset = h("select", { "aria-label": "畫風" }, h("option", { value: "" }, "畫風清單載入中…"));
    const style = h("textarea", { rows: 2, placeholder: "英文的自由畫風描述；填了會蓋掉預設集的那一欄，留空就用預設集" });
    const mode = { blank: h("input", { type: "radio", name: "t2c-new", checked: true }), sample: h("input", { type: "radio", name: "t2c-new" }) };
    const renders = h("input", { type: "checkbox" });
    const rendersNote = h("span", { class: "muted t2c-small" });
    loadStyles(ctx).then((loaded) => {
      if (!loaded.presets.length) { preset.replaceChildren(h("option", { value: "" }, "沒有可用的畫風預設集，會用預設值")); return; }
      preset.replaceChildren(...styleOptions(loaded.presets));
      preset.value = loaded.presets.some((p) => p.name === loaded.fallback) ? loaded.fallback : loaded.presets[0].name;
    }).catch((error) => {
      if (error.name === "AbortError") return;
      preset.replaceChildren(h("option", { value: "" }, "讀不到畫風清單，會用預設值"));
    });
    FE.api("/api/info", { signal: ctx.signal }).then((info) => {           // 範例的出圖不進版控，新下載的工具沒有
      if (info && info.sample_renders === false) {
        renders.checked = false;
        renders.disabled = true;
        rendersNote.textContent = "（這份範例沒有出圖，不能勾）";
      }
    }).catch(() => {});
    const browse = async () => {
      const dir = await FE.filepicker.open({ mode: "dir", title: "選擇要放新專案的上層資料夾" });
      if (dir) path.value = dir.replace(/[\\/]+$/, "") + (dir.includes("/") && !dir.includes("\\") ? "/" : "\\") + (title.value.trim() || "新作品");
    };
    const create = async () => {
      const body = {
        path: path.value.trim(), title: title.value.trim(), style_preset: preset.value || "",
        from_sample: mode.sample.checked, sample_renders: renders.checked,
      };
      const custom = style.value.trim();
      if (custom) body.style = custom;                                     // 有填才送；留空就把 style 那一欄交給預設集
      try {
        const data = await FE.api("/api/project/create", { body, signal: ctx.signal });
        T2C.setProject(data.root);
        FE.toast(`已建立：${data.root}`, "ok");
        FE.go("#/project");
      } catch (error) { FE.fail(error); }
    };
    return h("section", { class: "card stack" },
      h("h2", { class: "card-title" }, "建立一個新的專案資料夾"),
      h("div", { class: "row" }, path, h("button", { class: "btn", type: "button", onclick: browse }, "選上層資料夾…")),
      h("div", { class: "row" }, h("label", { class: "check" }, mode.blank, "空白專案"),
        h("label", { class: "check" }, mode.sample, "複製範例「屋頂的便當」（一章、兩個角色，用來試流程）"),
        h("label", { class: "check" }, renders, "連同範例的出圖（沒有 GPU 也能走完一章）", rendersNote)),
      h("label", { class: "field" }, "作品名", title),
      h("label", { class: "field" }, "畫風", preset),
      h("details", { class: "t2c-tight" },
        h("summary", { class: "muted t2c-small" }, "自訂畫風（進階）"),
        h("label", { class: "field" }, "自訂畫風字串（英文）", style)),
      h("div", { class: "row" }, h("button", { class: "btn btn-primary", type: "button", onclick: create }, "建立")));
  }

  /* ──────────────── 總覽的畫風（POST /api/project/style） ──────────────── */

  function styleCard(ctx, data) {
    const cfg = data.config || {};
    const preset = h("select", { "aria-label": "換這部作品的畫風預設集" }, h("option", { value: "" }, "載入中…"));
    const current = h("b", {}, "－");
    const note = h("div", { class: "alert alert-warn", hidden: true });
    const custom = cfg.style
      ? h("span", { class: "muted t2c-small" }, "（project.yaml 另有明寫的 style，會蓋掉預設集的那一欄；換一次畫風就清掉）")
      : null;
    let presets = [];
    let fallback = "mono";
    let value = cfg.style_preset || "";

    const show = (name) => {
      const key = name || fallback;
      current.textContent = `${styleLabel(presets, key)}（${key}）`;
    };

    loadStyles(ctx).then((loaded) => {
      presets = loaded.presets;
      fallback = loaded.fallback || fallback;
      preset.replaceChildren(...(presets.length ? styleOptions(presets) : [h("option", { value: "" }, "沒有可用的畫風預設集")]));
      preset.value = presets.some((p) => p.name === value) ? value : (presets.length ? fallback : "");
      show(value);
    }).catch((error) => {
      if (error.name === "AbortError") return;
      preset.replaceChildren(h("option", { value: "" }, "讀不到畫風清單"));
      show(value);
    });

    const apply = async () => {
      const chosen = preset.value;
      if (!chosen || chosen === value) return;
      preset.disabled = true;
      try {
        const reply = await T2C.post("/api/project/style", { preset: chosen }, ctx);
        value = reply.preset || chosen;
        if (!presets.some((p) => p.name === value)) {                      // 快取比後端舊：補上這一組，顯示才不會只剩名稱
          presets = presets.concat([{ name: value, label: (reply.resolved && reply.resolved.name) || value }]);
          preset.replaceChildren(...styleOptions(presets));
        }
        preset.value = value;
        show(value);
        FE.toast(`畫風已改成 ${styleLabel(presets, value)}（${value}）`, "ok");
        const dropped = Array.isArray(reply.dropped) ? reply.dropped : [];
        if (dropped.length) {
          note.textContent = `已拿掉 project.yaml 裡明寫的 ${dropped.join("／")}，不然會蓋掉預設集。`;
          note.hidden = false;
        } else {
          note.hidden = true;
        }
      } catch (error) {
        FE.fail(error);
        preset.value = value;
      } finally { preset.disabled = false; }
    };
    preset.addEventListener("change", apply);

    return h("section", { class: "card stack" },
      h("div", { class: "row" }, h("h2", { class: "card-title grow" }, "畫風"), preset),
      h("p", {}, "畫風：", current, custom),
      note,
      h("p", { class: "muted t2c-small" }, "畫風改了要在分鏡／編劇本之前改；已畫好的圖不會重畫。"));
  }

  /* ──────────────── 匯入整本切章（/api/import/plan → /api/import/commit） ──────────────── */

  function importDialog(ctx) {
    const file = h("input", { type: "text", class: "grow", spellcheck: "false", placeholder: "小說檔的完整路徑（.txt／.md／.docx）" });
    const mode = h("select", { "aria-label": "切章方式" },
      h("option", { value: "auto" }, "自動判斷"),
      h("option", { value: "chapter" }, "第 N 章標題"),
      h("option", { value: "markdown" }, "Markdown 的 ＃ 標題"));
    const numbering = h("select", { "aria-label": "章號編號" },
      h("option", { value: "auto" }, "自動（標題有章號就用標題的）"),
      h("option", { value: "titles" }, "照標題的章號"),
      h("option", { value: "sequential" }, "從第 1 章連續編號"));
    const conflict = h("select", { "aria-label": "重複匯入" },
      h("option", { value: "skip" }, "跳過（專案裡已經有的章不動）"),
      h("option", { value: "overwrite" }, "覆蓋（先備份舊檔）"));
    const convert = h("input", { type: "checkbox" });
    const preface = h("input", { type: "checkbox" });
    const out = h("div", { class: "stack" }, h("p", { class: "muted" }, "按「預覽」只切章、不寫檔；表格確認過再按「匯入」。"));

    let planned = null;      // 預覽成功的結果；換了任何選項就作廢
    let imported = false;    // 匯入成功：關掉對話框後要刷新頁面

    const previewBtn = h("button", { class: "btn", type: "button" }, "預覽");
    const commitBtn = h("button", { class: "btn btn-primary", type: "button", disabled: true }, "匯入");
    let cancelBtn = null;

    const options = () => ({
      path: file.value.trim(), mode: mode.value, numbering: numbering.value,
      convert: convert.checked, preface_as_chapter: preface.checked,
    });
    const invalidate = () => {
      planned = null;
      commitBtn.disabled = true;
      out.replaceChildren(h("p", { class: "muted" }, "選項改了，請重新按「預覽」。"));
    };
    const browse = async () => {
      const picked = await FE.filepicker.open({ mode: "file", exts: [".txt", ".md", ".docx"], title: "選擇小說檔" });
      if (!picked) return;
      file.value = picked;
      invalidate();
    };
    [file, mode, numbering, convert, preface].forEach((el) => {
      el.addEventListener(el.tagName === "SELECT" ? "change" : "input", invalidate);
    });

    const warningsOf = (list) => (Array.isArray(list) ? list : []).map((w) => ({ level: "warn", message: String(w) }));

    function previewTable(reply) {
      const chapters = Array.isArray(reply.chapters) ? reply.chapters : [];
      const total = chapters.reduce((sum, c) => sum + (Number(c.chars) || 0), 0);
      const heads = Array.isArray(reply.preface) ? reply.preface : [];
      return h("div", { class: "stack" },
        h("p", {}, `共 ${chapters.length} 章、合計 ${total} 字${reply.numbered_by_title ? "（章號照標題上的號碼）" : ""}。`),
        chapters.length
          ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
              h("thead", {}, h("tr", {}, ["章號", "章名", "字數", "旗標"].map((t) => h("th", {}, t)))),
              h("tbody", {}, chapters.map((c) => h("tr", {},
                h("td", { class: "num" }, c.no),
                h("td", {}, c.title || h("span", { class: "muted" }, "（沒有章名）"),
                  c.head ? h("div", { class: "muted t2c-small" }, c.head) : null),
                h("td", { class: "num" }, Number(c.chars) || 0),
                h("td", {}, (Array.isArray(c.flags) && c.flags.length)
                  ? c.flags.map((f) => T2C.chip(f, "warn"))
                  : h("span", { class: "muted" }, "－")))))))
          : h("div", { class: "alert alert-warn" }, "這個檔案切不出章節。換一個「切章方式」再預覽，或確認檔案是 UTF-8 的全文。"),
        heads.length
          ? h("p", { class: "muted t2c-small" },
              `開頭有 ${heads.length} 段文字（合計 ${heads.reduce((n, p) => n + (Number(p.chars) || 0), 0)} 字：${heads.map((p) => p.name).join("、")}），預設不會匯入；要的話勾「把開頭的文字當成一章」。`)
          : null,
        T2C.issues(warningsOf(reply.warnings), { title: "提醒" }));
    }

    function summary(reply) {
      const written = Array.isArray(reply.written) ? reply.written : [];
      const skipped = Array.isArray(reply.skipped) ? reply.skipped : [];
      const replaced = Array.isArray(reply.replaced) ? reply.replaced : [];
      return h("div", { class: "stack" },
        h("div", { class: "alert alert-ok" },
          `寫入 ${written.length} 章（${reply.chars || 0} 字）、跳過 ${skipped.length} 章、覆蓋 ${replaced.length} 章。`),
        skipped.length ? h("p", { class: "muted t2c-small" }, `跳過的章號：${skipped.join("、")}（專案裡已經有了；要換掉請把「重複匯入」改成覆蓋）`) : null,
        replaced.length ? h("p", { class: "muted t2c-small" }, `覆蓋並備份的章號：${replaced.join("、")}`) : null,
        T2C.issues(warningsOf(reply.warnings), { title: "提醒" }));
    }

    async function preview() {
      if (!file.value.trim()) { FE.toast("請先選或貼上小說檔的路徑", "warn"); return; }
      planned = null;
      commitBtn.disabled = true;
      previewBtn.disabled = true;
      out.replaceChildren(h("p", { class: "muted" }, "切章中…"));
      try {
        const reply = await T2C.post("/api/import/plan", options(), ctx);
        planned = reply;
        out.replaceChildren(previewTable(reply));
        commitBtn.disabled = !(Array.isArray(reply.chapters) && reply.chapters.length);
      } catch (error) {
        if (error.name === "AbortError") return;
        out.replaceChildren(h("div", { class: "alert alert-err" }, error.message || String(error)));
      }
      previewBtn.disabled = false;
    }

    async function commit() {
      if (!planned) return;
      commitBtn.disabled = true;
      previewBtn.disabled = true;
      out.replaceChildren(h("p", { class: "muted" }, "寫入 source/…"));
      try {
        const reply = await T2C.post("/api/import/commit", Object.assign(options(), { conflict: conflict.value }), ctx);
        imported = true;
        out.replaceChildren(summary(reply));
        if (cancelBtn) cancelBtn.textContent = "完成";
        FE.toast(`已匯入 ${(Array.isArray(reply.written) ? reply.written : []).length} 章`, "ok");
      } catch (error) {
        if (error.name === "AbortError") return;
        out.replaceChildren(h("div", { class: "alert alert-err" }, error.message || String(error)));
        commitBtn.disabled = false;
        previewBtn.disabled = false;
      }
    }

    previewBtn.addEventListener("click", preview);
    commitBtn.addEventListener("click", commit);

    const close = FE.modal({
      title: "匯入整本切章",
      wide: true,
      body: h("div", { class: "stack" },
        h("p", { class: "muted" }, "把整本小說切成章、寫進這個專案的 source/chNNN.txt。先預覽再匯入；覆蓋時舊檔會先備份。"),
        h("div", { class: "row" }, file, h("button", { class: "btn", type: "button", onclick: browse }, "瀏覽…")),
        h("div", { class: "row" },
          h("label", { class: "row t2c-inline" }, "切章方式", mode),
          h("label", { class: "row t2c-inline" }, "章號編號", numbering),
          h("label", { class: "row t2c-inline" }, "重複匯入", conflict)),
        h("div", { class: "stack t2c-tight" },
          h("label", { class: "check" }, convert, "簡轉繁（轉成台灣繁體）",
            h("span", { class: "muted t2c-small" }, "（沒裝 opencc 時會跳過，並寫在提醒裡）")),
          h("label", { class: "check" }, preface, "把開頭的文字當成一章（書名、簡介、楔子）")),
        out),
      foot: (done) => {
        cancelBtn = h("button", { class: "btn", type: "button", onclick: () => done(false) }, "取消");
        return [cancelBtn, previewBtn, commitBtn];
      },
    });
    close.closed.then(() => { if (imported) FE.route(); });
    return close;
  }

  /* ──────────────── 總覽 ──────────────── */

  function addChapter(chapters) {
    const next = chapters.length ? Math.max(...chapters.map((c) => c.chapter)) + 1 : 1;
    FE.go(FE.hash("chapter", next, { tab: "source" }));
  }

  async function projectOverview(ctx) {
    let data;
    try {
      data = await FE.api("/api/project", { query: { project: T2C.project() }, signal: ctx.signal });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      return h("div", { class: "stack" },
        h("div", { class: "alert alert-err" }, `打不開目前的專案：${error.message}`),
        h("div", { class: "row" }, h("a", { class: "btn", href: "#/projects" }, "換一個專案"), h("a", { class: "btn", href: "#/new" }, "新建專案")));
    }
    const rows = data.chapters.map((c) => h("tr", {},
      h("td", { class: "num" }, h("a", { href: FE.hash("chapter", c.chapter) }, `第 ${c.chapter} 章`)),
      h("td", {}, c.title || h("span", { class: "muted" }, "－"), c.problems.length ? h("div", { class: "t2c-err t2c-small" }, c.problems.join("；")) : null),
      h("td", { class: "num" }, stageCell(c.source_chars, " 字")),
      h("td", { class: "num" }, stageCell(c.plan_pages, " 頁")),
      h("td", { class: "num" }, stageCell(c.script_pages, " 頁")),
      h("td", { class: "num" }, stageCell(c.storyboard_pages, c.storyboard_pages === null ? "" : ` 頁 ${c.panels} 格`)),
      h("td", { class: "num" }, progress(c.rendered, c.panels)),
      h("td", { class: "num" }, progress(c.picked, c.panels)),
      h("td", { class: "num" }, c.pages_out ? `${c.pages_out} 頁` : h("span", { class: "muted" }, "－"))));
    const b = data.bible;
    const drafts = b.drafts.character.length + b.drafts.location.length;
    return h("div", { class: "stack" },
      h("div", { class: "row" },
        h("h1", { class: "t2c-title grow" }, `《${data.title}》`),
        h("button", { class: "btn", type: "button", onclick: () => importDialog(ctx) }, "匯入整本切章…"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => addChapter(data.chapters) }, "新增一章")),
      h("p", { class: "muted t2c-small" }, data.root),
      h("section", { class: "card stack" },
        h("h2", { class: "card-title" }, "章節與進度"),
        data.chapters.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", {}, h("tr", {}, ["章", "標題", "原著", "規劃", "劇本", "分鏡", "已出圖", "已選圖", "頁面"].map((t) => h("th", {}, t)))),
          h("tbody", {}, rows)))
          : h("div", { class: "empty" }, "還沒有章節。按「新增一章」貼上第一章的原著，或按「匯入整本切章…」一次切完整本。")),
      styleCard(ctx, data),
      h("section", { class: "card stack" },
        h("div", { class: "row" }, h("h2", { class: "card-title grow" }, "視覺聖經"), h("a", { class: "btn btn-sm", href: "#/bible" }, "開啟")),
        h("p", {}, `角色 ${b.characters.length}：${b.characters.map((c) => c.name).join("、") || "無"}`),
        h("p", {}, `地點 ${b.locations.length}：${b.locations.map((c) => c.name).join("、") || "無"}`),
        drafts ? h("div", { class: "alert alert-warn" }, `有 ${drafts} 張草稿還沒確認入庫（分鏡只會用確認過的卡片）。`) : null));
  }

  /* ──────────────── 四個路由 ──────────────── */

  // 舊的 `#/` 還留著（書籤、文件裡的連結）：直接帶到該去的地方。
  PAGES.home = () => {
    FE.go(T2C.project() ? "#/project" : "#/projects");
  };

  PAGES.projects = (ctx) => {
    ctx.crumbs([{ label: "開啟專案" }]);
    ctx.view(h("div", { class: "stack t2c-page" },
      h("h1", { class: "t2c-title" }, "開啟專案"),
      h("p", { class: "muted" }, "選一個已經存在的漫畫專案資料夾。第一次用可以先", h("a", { href: "#/new" }, "新建專案"), "並複製範例。"),
      openForm(ctx)));
  };

  PAGES.new = (ctx) => {
    ctx.crumbs([{ label: "新建專案" }]);
    ctx.view(h("div", { class: "stack t2c-page" },
      h("h1", { class: "t2c-title" }, "新建專案"),
      h("p", { class: "muted" }, "小說一章 → 改編規劃 → 漫畫劇本 → 分鏡 → MOSS-Image 逐格出圖 → 挑圖 → 嵌字 → 頁面。"),
      createForm(ctx)));
  };

  PAGES.project = async (ctx) => {
    if (!T2C.need(ctx, "總覽")) return;
    ctx.crumbs([{ label: "總覽" }]);
    const view = await projectOverview(ctx);
    if (!ctx.active()) return;
    ctx.view(h("div", { class: "stack t2c-page" }, view));
    T2C.onJobEnd(ctx, (job, r) => { if (r.refresh && r.refresh.length && !FE.dirty.is()) FE.route(); });
  };
})();
