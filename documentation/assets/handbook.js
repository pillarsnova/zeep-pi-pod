(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("handbook-data").textContent);
  const documents = new Map(data.documents.map((doc) => [doc.id, doc]));
  const groups = new Map(data.groups.map((group) => [group.id, group]));
  const main = document.getElementById("main");
  const search = document.getElementById("search");
  const nav = document.getElementById("chapter-nav");
  const breadcrumb = document.getElementById("breadcrumb");
  const menuButton = document.getElementById("menu-button");
  const backdrop = document.getElementById("sidebar-backdrop");
  let toastTimer;
  const escape = (value) =>
    String(value).replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  const iconPaths = {
    book: "M4 4h6l2 2 2-2h6v16h-6l-2 1-2-1H4ZM12 6v15",
    layers: "m12 3 10 5-10 5L2 8ZM2 12l10 5 10-5M2 16l10 5 10-5",
    wave: "M2 12h4l3-7 5 14 3-7h5",
    moon: "M20 14A9 9 0 0 1 10 3a9 9 0 1 0 10 11ZM17 3v4M15 5h4",
    spark: "m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3ZM20 2v4M18 4h4",
    code: "m8 6-6 6 6 6M16 6l6 6-6 6M14 3l-4 18",
    window: "M3 4h18v16H3ZM3 9h18M8 9v11M6 6.5h1M10 6.5h1",
    tool: "M14 4a6 6 0 0 0-7 7l-5 6 5 5 6-6a6 6 0 0 0 7-7l-4 4-5-5Z",
    research: "M9 3h6M10 3v6L4 19q-1 2 2 2h12q3 0 2-2L14 9V3M7 15h10",
    check: "M9 4H4v17h16V4h-5M9 2h6v4H9ZM8 13l3 3 6-7",
  };
  const icon = (name) =>
    `<span class="icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${iconPaths[name] || iconPaths.book}"/></svg></span>`;
  const tag = (doc) =>
    `<span class="tag ${doc.kind}">${escape(doc.kindLabel)}</span>`;
  const groupDocs = (id) => data.documents.filter((doc) => doc.group === id);
  const link = (id, anchor = "") =>
    `#/read/${id}${anchor ? "/" + encodeURIComponent(anchor) : ""}`;

  function buildNavigation() {
    nav.innerHTML = data.groups
      .map(
        (group) =>
          `<details class="nav-group" data-group="${group.id}" ${group.id === "start" ? "open" : ""}><summary><span class="nav-number">${group.number}</span>${escape(group.title)}</summary><ul>${groupDocs(
            group.id,
          )
            .map(
              (doc) =>
                `<li><a href="${link(doc.id)}" data-document="${doc.id}">${escape(doc.title)}</a></li>`,
            )
            .join("")}</ul></details>`,
      )
      .join("");
    document.getElementById("bundle-meta").textContent =
      `${data.reviewedOn} · CONTENT ${data.digest.slice(0, 10)}`;
  }

  function home() {
    main.replaceChildren(
      document.getElementById("home-template").content.cloneNode(true),
    );
    document.getElementById("document-count").textContent =
      data.documents.length;
    document.getElementById("category-grid").innerHTML = data.groups
      .map(
        (group) =>
          `<a class="category-card" href="#/group/${group.id}"><div class="card-top">${icon(group.icon)}<span class="card-number">${group.number}</span></div><h3>${escape(group.title)}</h3><p>${escape(group.description)}</p><div class="card-footer"><span>${groupDocs(group.id).length} เอกสาร</span><span aria-hidden="true">↗</span></div></a>`,
      )
      .join("");
    breadcrumb.innerHTML = "คู่มือระบบ <span>/</span> <strong>ภาพรวม</strong>";
    document.title = "คู่มือระบบ ZEEP POD · Knowledge Hub";
  }

  function documentRow(doc, index, excerpt = "") {
    return `<a class="document-row" href="${link(doc.id)}"><span class="row-number">${String(index + 1).padStart(2, "0")}</span><div class="row-body">${tag(doc)}<h2>${escape(doc.title)}</h2><p>${excerpt || escape(doc.summary)}</p></div><span aria-hidden="true">↗</span></a>`;
  }

  function collection(group) {
    main.innerHTML = `<header class="collection-heading"><span class="eyebrow">CHAPTER ${group.number}</span><h1>${escape(group.title)}</h1><p>${escape(group.description)}</p></header><section class="document-list" aria-label="รายการเอกสาร">${groupDocs(
      group.id,
    )
      .map((doc, index) => documentRow(doc, index))
      .join("")}</section>`;
    breadcrumb.innerHTML = `<a href="#/">คู่มือระบบ</a><span>/</span><strong>${escape(group.title)}</strong>`;
    document.title = `${group.title} · ZEEP POD`;
  }

  function wrapTables() {
    main.querySelectorAll(".article-body table").forEach((table) => {
      const wrapper = document.createElement("div");
      wrapper.className = "table-scroll";
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute(
        "aria-label",
        "ตารางข้อมูล เลื่อนแนวนอนเพื่ออ่านเพิ่มเติม",
      );
      table.before(wrapper);
      wrapper.append(table);
    });
  }

  function reader(doc) {
    const group = groups.get(doc.group);
    const neighbors = groupDocs(doc.group);
    const index = neighbors.findIndex((item) => item.id === doc.id);
    const warnings = {
      audit:
        "ผลตรวจนี้ใช้กับวันที่และรุ่นที่ระบุในเอกสาร ไม่ใช่การรับรองรุ่นปัจจุบันโดยอัตโนมัติ",
      plan: "แผนพัฒนา: บางรายการยังไม่ได้ติดตั้งหรือเปิดใช้งาน ตรวจสถานะรายหัวข้อก่อนนำไปอ้างอิง",
      shadow:
        "ผลสำหรับทีมพัฒนา / Admin: ยังไม่ใช้เป็นข้อสรุปสุขภาพหรือคำสั่งควบคุมอัตโนมัติ",
    };
    const outline = doc.outline.filter(
      (item) => item.level === 2 || item.level === 3,
    );
    main.innerHTML = `<div class="reader-toolbar">${tag(doc)}<div><button class="quiet-button" data-action="copy">คัดลอกลิงก์</button><button class="quiet-button" data-action="print">พิมพ์ / PDF</button></div></div><div class="reader-layout"><article class="reader-card"><p class="reader-summary">${escape(doc.summary)}</p>${warnings[doc.kind] ? `<aside class="reader-warning">${warnings[doc.kind]}</aside>` : ""}<div class="article-body">${doc.html}</div><footer class="source-meta"><strong>เอกสารต้นทาง</strong><br><a href="${doc.source}" target="_blank" rel="noopener noreferrer">${escape(doc.path)} ↗</a><br>ฉบับอ่านนี้สร้างจากไฟล์ต้นทางโดยตรง · SHA-256 <code>${doc.checksum.slice(0, 16)}</code><br>ลิงก์ต้นฉบับเปิด branch develop ซึ่งอาจมีการปรับปรุงหลังสร้างชุดนี้</footer><nav class="reader-pagination" aria-label="บทก่อนหน้าและถัดไป">${index > 0 ? `<a href="${link(neighbors[index - 1].id)}"><small>← บทก่อนหน้า</small>${escape(neighbors[index - 1].title)}</a>` : ""}${index < neighbors.length - 1 ? `<a href="${link(neighbors[index + 1].id)}"><small>บทถัดไป →</small>${escape(neighbors[index + 1].title)}</a>` : ""}</nav></article><nav class="outline" aria-label="หัวข้อในหน้านี้"><div class="outline-title">ในเอกสารนี้</div>${outline.map((item) => `<a class="level-${item.level}" href="${link(doc.id, item.id)}">${escape(item.title)}</a>`).join("")}<a class="back-top" href="${link(doc.id)}">↑ กลับด้านบน</a></nav></div>`;
    wrapTables();
    if (outline.length) {
      const mobileContents = document.createElement("details");
      mobileContents.className = "mobile-outline";
      const summary = document.createElement("summary");
      summary.textContent = "หัวข้อในเอกสารนี้";
      const contents = main.querySelector(".outline").cloneNode(true);
      contents.className = "mobile-outline-nav";
      contents.querySelector(".outline-title").remove();
      mobileContents.append(summary, contents);
      main.querySelector(".reader-summary").after(mobileContents);
    }
    breadcrumb.innerHTML = `<a href="#/">คู่มือระบบ</a><span>/</span><a href="#/group/${group.id}">${escape(group.title)}</a><span>/</span><strong>${escape(doc.title)}</strong>`;
    document.title = `${doc.title} · ZEEP POD`;
  }

  function searchExcerpt(doc, query) {
    const text = doc.text.replace(/\s+/g, " ");
    const offset = text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
    if (offset < 0) return escape(doc.summary);
    const start = Math.max(0, offset - 50);
    return `${start ? "…" : ""}${escape(text.slice(start, offset))}<mark>${escape(text.slice(offset, offset + query.length))}</mark>${escape(text.slice(offset + query.length, offset + query.length + 125))}…`;
  }

  function searchDocuments() {
    const query = search.value.trim();
    if (!query) return route();
    const needle = query.toLocaleLowerCase();
    const found = data.documents.filter((doc) =>
      `${doc.title} ${doc.summary} ${doc.text}`
        .toLocaleLowerCase()
        .includes(needle),
    );
    found.sort(
      (a, b) =>
        Number(b.title.toLocaleLowerCase().includes(needle)) -
        Number(a.title.toLocaleLowerCase().includes(needle)),
    );
    main.innerHTML = `<header class="collection-heading"><span class="eyebrow">SEARCH THE HANDBOOK</span><h1>ผลการค้นหา</h1><p id="search-result-status" role="status" aria-live="polite">“${escape(query)}” · พบ ${found.length} เอกสาร</p></header>${found.length ? `<section class="document-list" aria-label="ผลการค้นหา">${found.map((doc, index) => documentRow(doc, index, searchExcerpt(doc, query))).join("")}</section>` : '<div class="empty-state"><strong>ไม่พบคำนี้ในคู่มือ</strong>ลองใช้คำสั้นลง เช่น Baseline, API, เสียง หรือคะแนน</div>'}`;
    breadcrumb.innerHTML =
      '<a href="#/">คู่มือระบบ</a><span>/</span><strong>ค้นหา</strong>';
    document.title = "ค้นหาในคู่มือ · ZEEP POD";
  }

  function route() {
    search.value = "";
    let parts;
    try {
      parts = location.hash.slice(2).split("/").map(decodeURIComponent);
    } catch {
      parts = [];
    }
    const [view, id, anchor] = parts;
    const doc = view === "read" ? documents.get(id) : null;
    if (doc) reader(doc);
    else if (view === "group" && groups.has(id)) collection(groups.get(id));
    else if (view && view !== "") {
      main.innerHTML =
        '<div class="collection-heading"><h1>ไม่พบเอกสารที่เลือก</h1><p>ลิงก์อาจถูกเปลี่ยน กรุณาค้นหาหรือกลับไปที่สารบัญ</p><a class="primary-button" href="#/">กลับหน้าคู่มือ</a></div>';
    } else home();
    nav.querySelectorAll("a[data-document]").forEach((item) => {
      if (item.dataset.document === doc?.id) {
        item.setAttribute("aria-current", "page");
        item.closest("details").open = true;
      } else item.removeAttribute("aria-current");
    });
    setMenu(false);
    window.scrollTo({ top: 0, behavior: "instant" });
    if (doc && anchor)
      requestAnimationFrame(() => {
        const heading = document.getElementById(anchor);
        if (heading && main.contains(heading)) heading.scrollIntoView();
      });
  }

  function setMenu(open) {
    document.body.classList.toggle("menu-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "ปิดสารบัญ" : "เปิดสารบัญ");
    backdrop.hidden = !open;
    const mobile = window.matchMedia("(max-width: 940px)").matches;
    document.querySelector(".workspace").inert = mobile && open;
    document.getElementById("sidebar").inert = mobile && !open;
  }

  function toast(message) {
    const box = document.getElementById("toast");
    clearTimeout(toastTimer);
    box.textContent = message;
    box.hidden = false;
    toastTimer = setTimeout(() => {
      box.hidden = true;
    }, 3500);
  }

  document.addEventListener("click", async (event) => {
    if (event.target.closest(".skip-link")) {
      event.preventDefault();
      main.focus();
      main.scrollIntoView();
      return;
    }
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "print") window.print();
    if (action === "copy") {
      try {
        await navigator.clipboard.writeText(location.href);
        toast("คัดลอกลิงก์แล้ว");
      } catch {
        toast("กรุณาคัดลอกลิงก์จากแถบที่อยู่ของเบราว์เซอร์");
      }
    }
    // Reopening the same article after a search must also restore its content.
    const target = event.target.closest('a[href^="#/"]');
    if (target && target.getAttribute("href") === location.hash) route();
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      setMenu(false);
      search.focus();
    }
    if (event.key === "Escape") {
      if (document.body.classList.contains("menu-open")) {
        setMenu(false);
        menuButton.focus();
      } else if (search.value) {
        search.value = "";
        route();
        search.focus();
      }
    }
  });
  search.addEventListener("input", searchDocuments);
  menuButton.addEventListener("click", () =>
    setMenu(!document.body.classList.contains("menu-open")),
  );
  backdrop.addEventListener("click", () => setMenu(false));
  window.addEventListener("hashchange", route);
  window
    .matchMedia("(max-width: 940px)")
    .addEventListener("change", () => setMenu(false));
  buildNavigation();
  route();
})();
