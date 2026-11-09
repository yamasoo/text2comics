// 專案頁（#/）：開啟、新建、從範例複製；目前專案的章節表、視覺聖經摘要、環境檢查。
(function () {
  "use strict";
  const { h, PAGES } = FE;

  function stageCell(value, unit) {
    return value === null || value === undefined ? h("span", { class: "muted" }, "－") : `${value}${unit || ""}`;
  }

  function progress(done, total) {
    if (!total) return h("span", { class: "muted" }, "－");
    return h("span", { class: done >= total ? "t2c-ok" : "" }, `${done}／${total}`);
  }

  function openForm(ctx, refresh) {
    const input = h("input", { type: "text", class: "grow", placeholder: "E:\\comics\\作品名（有 project.yaml 的資料夾）", value: T2C.project() });
    const open = async (path) => {
      path = (path || input.value).trim();
      if (!path) return FE.toast("請輸入專案資料夾", "warn");
      try {
        await FE.api("/api/project", { query: { project: path }, signal: ctx.signal });
        T2C.setProject(path);
        refresh();
      } catch (error) { FE.fail(error); }
    };
    const browse = async () => {
      const path = await FE.filepicker.open({ mode: "dir", title: "選擇漫畫專案資料夾", start: input.value || undefined });
      if (path) { input.value = path; open(path); }
    };
    const recent = T2C.recent();
    return h("section", { class: "card stack" },
      h("h2", { class: "card-title" }, "開啟專案"),
      h("div", { class: "row" }, input,
        h("button", { class: "btn", type: "button", onclick: browse }, "瀏覽…"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => open() }, "開啟")),
      recent.length ? h("div", { class: "stack t2c-tight" },
        h("div", { class: "muted" }, "最近開過："),
        recent.map((p) => h("div", { class: "row t2c-recent" },
          h("button", { class: ["btn btn-sm", p === T2C.project() ? "btn-primary" : "btn-ghost"], type: "button", title: p, onclick: () => open(p) },
            p.split(/[\\/]/).filter(Boolean).slice(-2).join(" / ")),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "從清單移除", "aria-label": "從清單移除",
            onclick: () => { T2C.forget(p); refresh(); } }, "×")))) : null);
  }

  function createForm(ctx, refresh) {
    const path = h("input", { type: "text", class: "grow", placeholder: "新資料夾的完整路徑，例如 E:\\comics\\屋頂的便當" });
    const title = h("input", { type: "text", placeholder: "作品名" });
    const style = h("textarea", { rows: 2, placeholder: "畫風（英文，可留空用預設：黑白日式漫畫、網點、高對比）" });
    const mode = { blank: h("input", { type: "radio", name: "t2c-new", checked: true }), sample: h("input", { type: "radio", name: "t2c-new" }) };
    const renders = h("input", { type: "checkbox" });
    const rendersNote = h("span", { class: "muted t2c-small" });
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
      try {
        const data = await FE.api("/api/project/create", {
          body: { path: path.value.trim(), title: title.value.trim(), style: style.value.trim(), from_sample: mode.sample.checked, sample_renders: renders.checked },
          signal: ctx.signal,
        });
        T2C.setProject(data.root);
        FE.toast(`已建立：${data.root}`, "ok");
        refresh();
      } catch (error) { FE.fail(error); }
    };
    return h("details", { class: "card" },
      h("summary", { class: "card-title" }, "新建專案"),
      h("div", { class: "stack" },
        h("div", { class: "row" }, path, h("button", { class: "btn", type: "button", onclick: browse }, "選上層資料夾…")),
        h("div", { class: "row" }, h("label", { class: "check" }, mode.blank, "空白專案"),
          h("label", { class: "check" }, mode.sample, "複製範例「屋頂的便當」（一章、兩個角色，用來試流程）"),
          h("label", { class: "check" }, renders, "連同範例的出圖（沒有 GPU 也能走完一章）", rendersNote)),
        h("label", { class: "field" }, "作品名", title),
        h("label", { class: "field" }, "畫風", style),
        h("div", { class: "row" }, h("button", { class: "btn btn-primary", type: "button", onclick: create }, "建立"))));
  }

  function envCard(ctx) {
    const box = h("div", { class: "stack" }, h("p", { class: "muted" }, "檢查中…"));
    const load = async () => {
      try {
        const env = await FE.api("/api/env", { signal: ctx.signal });
        box.replaceChildren(
          h("div", { class: "row" }, T2C.chip(env.comfy.ok ? "ComfyUI 已連線" : "ComfyUI 沒有回應", env.comfy.ok ? "ok" : "warn"),
            h("span", { class: "muted" }, env.comfy.url), env.comfy.vram ? h("span", {}, env.comfy.vram) : null),
          h("table", { class: "table" },
            h("thead", {}, h("tr", {}, ["模型", "型號", "狀態", "用在"].map((t) => h("th", {}, t)))),
            h("tbody", {}, env.providers.map((p) => {
              const used = Object.entries(env.stages).filter(([, id]) => id === p.id).map(([s]) => ({ adapt: "規劃", script: "劇本", storyboard: "分鏡", bible: "聖經" })[s]);
              const state = p.local
                ? T2C.chip(p.running ? "執行中（佔 VRAM）" : "沒有執行", p.running ? "info" : "")
                : T2C.chip(p.has_key ? "有金鑰" : `沒有金鑰（設環境變數 ${p.key_env}）`, p.has_key ? "ok" : "err");
              return h("tr", {}, h("td", {}, p.name), h("td", {}, p.model || h("span", { class: "muted" }, "預設")), h("td", {}, state), h("td", {}, used.join("、") || "－"));
            }))),
          h("p", { class: "muted t2c-small" }, `設定檔：${env.config_path}；出圖預設：${env.presets.join("、") || "（workflow 預設）"}（預設 ${env.default_preset || "－"}）`));
      } catch (error) {
        if (error.name !== "AbortError") box.replaceChildren(h("div", { class: "alert alert-err" }, error.message));
      }
    };
    load();
    return h("section", { class: "card stack" },
      h("div", { class: "row" }, h("h2", { class: "card-title grow" }, "環境"), h("button", { class: "btn btn-sm", type: "button", onclick: load }, "重新檢查")),
      box);
  }

  function addChapter(chapters) {
    const next = chapters.length ? Math.max(...chapters.map((c) => c.chapter)) + 1 : 1;
    FE.go(FE.hash("chapter", next, { tab: "source" }));
  }

  async function projectView(ctx) {
    let data;
    try {
      data = await FE.api("/api/project", { query: { project: T2C.project() }, signal: ctx.signal });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      return h("div", { class: "alert alert-err" }, `打不開目前的專案：${error.message}`);
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
      h("section", { class: "card stack" },
        h("div", { class: "row" }, h("h2", { class: "card-title grow" }, `《${data.title}》`),
          h("button", { class: "btn btn-primary", type: "button", onclick: () => addChapter(data.chapters) }, "新增一章")),
        h("p", { class: "muted t2c-small" }, data.root),
        data.chapters.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", {}, h("tr", {}, ["章", "標題", "原著", "規劃", "劇本", "分鏡", "已出圖", "已選圖", "頁面"].map((t) => h("th", {}, t)))),
          h("tbody", {}, rows)))
          : h("div", { class: "empty" }, "還沒有章節。按「新增一章」貼上第一章的原著。")),
      h("section", { class: "card stack" },
        h("div", { class: "row" }, h("h2", { class: "card-title grow" }, "視覺聖經"), h("a", { class: "btn btn-sm", href: "#/bible" }, "開啟")),
        h("p", {}, `角色 ${b.characters.length}：${b.characters.map((c) => c.name).join("、") || "無"}`),
        h("p", {}, `地點 ${b.locations.length}：${b.locations.map((c) => c.name).join("、") || "無"}`),
        drafts ? h("div", { class: "alert alert-warn" }, `有 ${drafts} 張草稿還沒確認入庫（分鏡只會用確認過的卡片）。`) : null));
  }

  PAGES.home = async (ctx) => {
    ctx.crumbs([{ label: "專案" }]);
    const refresh = () => FE.route();
    const main = T2C.project() ? await projectView(ctx) : h("div", { class: "empty" }, "開啟一個漫畫專案資料夾，或新建一個。第一次用可以選「複製範例」。");
    ctx.view(h("div", { class: "stack t2c-page" },
      h("h1", { class: "t2c-title" }, "文字轉漫畫"),
      h("p", { class: "muted" }, "小說一章 → 改編規劃 → 漫畫劇本 → 分鏡 → MOSS-Image 逐格出圖 → 挑圖 → 嵌字 → 頁面。"),
      main,
      h("div", { class: "t2c-two" }, openForm(ctx, refresh), createForm(ctx, refresh)),
      envCard(ctx)));
    T2C.onJobEnd(ctx, (job, r) => { if (r.refresh && r.refresh.length && !FE.dirty.is()) FE.route(); });
  };
})();
