// 文字轉漫畫 的前端進入點：外殼（導覽、任務面板、左側底部的環境狀態）。
// 各頁在 project.js（新建、開啟、總覽）、chapter.js、storyboard.js、panels.js、bible.js、letter.js、settings.js。
// 導覽照 docs/06_決策記錄.md D5：專案（新建、開啟）／目前的專案（總覽、章、聖經、嵌字）／系統（設定）。
(async function () {
  "use strict";

  const { h } = FE;

  // 介面文字維持中文，語言檔（static/locales/<語言>.json）把中文對到其他語言。要在 mount 之前 await。
  await FE.i18n.init({ base: "static/locales", langs: [["zh-TW", "繁體中文"], ["en", "English"]] });

  const lastChapter = () => FE.store.get("chapter", 1) || 1;
  const folderName = (path) => String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";

  // 沒有專案時工作入口不出現（D5）；分組標題是 fekit 支援的最細層級，子項縮排在 app.css。
  function nav(route) {
    const has = !!T2C.project();
    const here = route && route.page === "chapter/:n" ? parseInt(route.params.n, 10) : 0;
    const n = here > 0 ? here : lastChapter();
    const items = [
      { label: "新建專案", href: "#/new", page: "new" },
      { label: "開啟專案", href: "#/projects", page: "projects" },
    ];
    if (has) {
      items.push({ group: `目前的專案：${folderName(T2C.project())}` },
        { label: "總覽", href: "#/project", page: "project" },
        { label: `第 ${n} 章`, href: FE.hash("chapter", n), page: "chapter/:n" },
        { label: "視覺聖經", href: "#/bible", page: "bible" },
        { label: "嵌字", href: "#/letter", page: "letter" });
    } else {
      items.push({ group: "（尚未開啟專案）" });
    }
    items.push({ group: "系統" }, { label: "設定", href: "#/settings", page: "settings" });
    return items;
  }

  /* ── 左側底部：ComfyUI 與金鑰的一行狀態（D5：入口不掛徽章，狀態寫在底部）── */
  const foot = h("div", { class: "shell-env" }, h("span", { class: "muted" }, "環境檢查中…"));
  let envBusy = false;

  async function checkEnv() {
    if (envBusy) return;
    envBusy = true;
    try {
      const env = await T2C.get("/api/env", {});
      const comfy = env.comfy || {};
      const missing = (env.providers || []).filter((p) => !p.local && !p.has_key).map((p) => p.name);
      foot.replaceChildren(
        h("div", { class: "row t2c-tight" },
          T2C.chip(comfy.ok ? "ComfyUI 連得上" : "ComfyUI 沒回應", comfy.ok ? "ok" : "warn", comfy.url || ""),
          h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "重新檢查環境", "aria-label": "重新檢查環境", onclick: checkEnv }, "↻")),
        h("span", { class: missing.length ? "t2c-warn" : "muted t2c-small" },
          missing.length ? `沒有金鑰：${missing.join("、")}` : "金鑰都設好了"));
    } catch (error) {
      foot.replaceChildren(h("span", { class: "t2c-warn" }, "讀不到環境：" + error.message));
    } finally {
      envBusy = false;
    }
  }

  const shell = FE.shell.mount({
    brand: { label: "文字轉漫畫", mark: "文" },
    nav: (route) => nav(route),
    panel: (el, sh) => {
      T2C.panel = FE.jobs.panel({
        root: el,
        onreveal: () => sh.toggle("panel", true),
        onchange: (job) => {
          if (!job) sh.badge("panel", null);
          else if (job.status === "running" || job.status === "queued") sh.badge("panel", "busy");
          else sh.badge("panel", job.status === "done" ? "ok" : job.status === "error" ? "err" : "warn");
        },
      });
    },
    panel_label: "任務",
    slots: { top: FE.i18n.select(), nav_foot: foot },
  });

  // 專案換了：導覽跟著變（章節頁會自己記住最後看的章，導覽在每次換頁時重算），底部狀態也要重抓。
  window.addEventListener("t2c-project", () => { shell.refresh_nav(); checkEnv(); });

  checkEnv().catch(FE.fail);
  T2C.panel.resume().catch(FE.fail);                   // 重新整理頁面後，接回還在跑的任務
})().catch((error) => { console.error(error); });
