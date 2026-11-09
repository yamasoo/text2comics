// 文字轉漫畫 的前端進入點：外殼（導覽、任務面板）。各頁在 project.js、chapter.js、storyboard.js、panels.js、bible.js、letter.js。
(async function () {
  "use strict";

  // 介面文字維持中文，語言檔（static/locales/<語言>.json）把中文對到其他語言。要在 mount 之前 await。
  await FE.i18n.init({ base: "static/locales", langs: [["zh-TW", "繁體中文"], ["en", "English"]] });

  const lastChapter = () => FE.store.get("chapter", 1) || 1;

  function nav(route) {
    const has = !!T2C.project();
    const here = route && route.page === "chapter/:n" ? parseInt(route.params.n, 10) : 0;
    const n = here > 0 ? here : lastChapter();
    return [
      { label: "專案", href: "#/", page: "home" },
      { group: has ? "目前的專案" : "（尚未開啟專案）" },
      { label: `第 ${n} 章`, href: FE.hash("chapter", n), page: "chapter/:n" },
      { label: "視覺聖經", href: "#/bible", page: "bible" },
      { label: "嵌字", href: "#/letter", page: "letter" },
      { label: "設定", href: "#/settings", page: "settings" },
    ];
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
    slots: { top: FE.i18n.select() },
  });

  // 專案換了：導覽跟著變（章節頁會自己記住最後看的章，導覽在每次換頁時重算）。
  window.addEventListener("t2c-project", () => shell.refresh_nav());

  T2C.panel.resume().catch(FE.fail);                   // 重新整理頁面後，接回還在跑的任務
})().catch((error) => { console.error(error); });
