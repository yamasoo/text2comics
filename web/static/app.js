// 文字轉漫畫 的前端進入點。頁面怎麼寫見 fekit 的 docs/03_頁面寫法.md。
(async function () {
  "use strict";
  const { h, PAGES } = FE;

  // 介面文字維持中文，語言檔（static/locales/<語言>.json）把中文對到其他語言。要在 mount 之前 await。
  await FE.i18n.init({ base: "static/locales", langs: [["zh-TW", "繁體中文"], ["en", "English"]] });

  let panel = null;                                    // 右欄的任務面板，下面 mount 時建立

  /* 頁面：FE.PAGES 的 key 就是網址片段（#/tasks）；"items/:id" 可以帶參數。
     一律用 ctx.view／ctx.crumbs（不是全域的 FE.view），非同步頁面等資料時使用者可能已經換頁。 */

  PAGES.home = (ctx) => {
    ctx.crumbs([{ label: "首頁" }]);
    const output = h("p", { class: "muted" }, "按下按鈕呼叫後端。");
    ctx.view(h("div", { class: "page-narrow stack" },
      h("h1", {}, "文字轉漫畫"),
      h("p", {}, "把小說改編成日式黑白頁漫：改編 → 漫畫劇本 → 分鏡 → MOSS-Image 逐格出圖 → 嵌字 → 組版。"),
      h("p", { class: "muted" }, "目前是骨架階段：先到「任務」頁編譯範例分鏡，確認每格的提示詞；到「嵌字」頁拖曳調整範例頁的對話框。進度見 docs/00_階段計畫.md。"),
      h("div", { class: "row" },
        h("button", {
          class: "btn btn-primary",
          type: "button",
          onclick: async () => {
            const data = await FE.api("/api/hello", { query: { name: "fekit" }, signal: ctx.signal });
            output.textContent = data.message;
            FE.toast(data.message, "ok");
          },
        }, "呼叫後端")),
      output));
  };

  PAGES.tasks = (ctx) => {
    ctx.crumbs([{ label: "首頁", href: "#/" }, { label: "任務" }]);
    ctx.view(h("div", { class: "page-narrow stack" },
      h("h1", {}, "任務"),
      h("p", {}, "長時間的工作交給背景任務，進度與輸出會顯示在右邊的面板，可以停止。"),
      h("div", { class: "row" },
        h("button", { class: "btn btn-primary", type: "button", onclick: () => panel.run("/api/sample/compile") }, "編譯範例分鏡"),
        h("button", { class: "btn", type: "button", onclick: () => panel.run("/api/demo-task") }, "開始示範任務"))));
  };

  /* 外殼：頂列、左側導覽、主區、右側任務面板 */

  FE.shell.mount({
    brand: { label: "文字轉漫畫", mark: "文" },
    nav: [
      { label: "首頁", href: "#/", page: "home" },
      { label: "任務", href: "#/tasks", page: "tasks" },
      { label: "嵌字", href: "#/letter", page: "letter" },
    ],
    panel: (el, shell) => {
      panel = FE.jobs.panel({
        root: el,
        onreveal: () => shell.toggle("panel", true),
        onchange: (job) => {
          if (!job) shell.badge("panel", null);
          else if (job.status === "running" || job.status === "queued") shell.badge("panel", "busy");
          else shell.badge("panel", job.status === "done" ? "ok" : job.status === "error" ? "err" : "warn");
        },
      });
    },
    panel_label: "任務",
    slots: { top: FE.i18n.select() },
  });

  panel.resume().catch(FE.fail);                       // 重新整理頁面後，接回還在跑的任務
})().catch((error) => { console.error(error); });
