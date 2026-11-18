const DEAL_CATEGORIES = ["AI·구독", "디지털·가전", "상품권·이용권", "항공·여행"];
const LOCAL_SCRAP_KEY = "myown_dash_scraps_v1";
const PIN_AUTH_KEY = "myown_dash_pin_exp_v1";
const PIN_HASH = "d2c3f2c1"; // lightweight gate for static Pages hosting

function simplePinCheck(val) {
  let h = 2166136261;
  for (let i = 0; i < val.length; i++) {
    h ^= val.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16) === PIN_HASH;
}

function initPinGate() {
  const gate = document.getElementById("pinGate");
  const form = document.getElementById("pinForm");
  const input = document.getElementById("pinInput");
  const err = document.getElementById("pinError");
  if (!gate || !form) return true;

  const isLocal = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  const exp = Number(localStorage.getItem(PIN_AUTH_KEY) || "0");
  if (isLocal || exp > Date.now()) {
    gate.classList.add("hidden");
    return true;
  }

  gate.classList.remove("hidden");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (simplePinCheck(input.value.trim())) {
      localStorage.setItem(PIN_AUTH_KEY, String(Date.now() + 30 * 24 * 60 * 60 * 1000));
      gate.classList.add("hidden");
      if (initPinGate()) {
  loadAllData();
}
    } else {
      err.classList.remove("hidden");
      input.value = "";
      input.focus();
    }
  });
  return false;
}

const state = {
  tab: "hot",
  filter: "all",
  dealToggles: new Set(),
  hotData: { updated_at: "", cross_topics: [], posts: [], source_status: {} },
  aiData: { updated_at: "", posts: [], source_status: {} },
  dealsData: { updated_at: "", posts: [], source_status: {} },
  gamesData: { updated_at: "", posts: [], source_status: {} },
  redditData: { updated_at: "", posts: [], source_status: {} },
  economyData: { updated_at: "", markets: [], market_brief: "", videos: [] },
  scraps: [],
  scrollY: 0,
  currentPostId: null,
};

const els = {
  updatedAt: document.getElementById("updatedAt"),
  mainTabs: document.getElementById("mainTabs"),
  listView: document.getElementById("listView"),
  detailView: document.getElementById("detailView"),
  filterBar: document.getElementById("filterBar"),
  crossTopicSection: document.getElementById("crossTopicSection"),
  marketSection: document.getElementById("marketSection"),
  postList: document.getElementById("postList"),
  backBtn: document.getElementById("backBtn"),
  detailStarBtn: document.getElementById("detailStarBtn"),
  originalLink: document.getElementById("originalLink"),
  detailContent: document.getElementById("detailContent"),
};

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function fetchJson(path, fallback) {
  try {
    const res = await fetch(`${path}?t=${Date.now()}`);
    if (!res.ok) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

async function loadScraps() {
  try {
    const res = await fetch("/.netlify/functions/scraps");
    if (res.ok) {
      const data = await res.json();
      state.scraps = data.items || [];
      localStorage.setItem(LOCAL_SCRAP_KEY, JSON.stringify(state.scraps));
      return;
    }
  } catch {}
  try {
    state.scraps = JSON.parse(localStorage.getItem(LOCAL_SCRAP_KEY) || "[]");
  } catch {
    state.scraps = [];
  }
}

function isScrapped(post) {
  return state.scraps.some((s) => s.id === post.id || s.url === post.url);
}

async function toggleScrap(post) {
  const payload = {
    id: post.id,
    title: post.title,
    url: post.url,
    source: post.source || "슈카월드",
    category: post.category || "",
    time: post.time || "",
  };

  try {
    const res = await fetch("/.netlify/functions/scraps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const data = await res.json();
      state.scraps = data.items || [];
      localStorage.setItem(LOCAL_SCRAP_KEY, JSON.stringify(state.scraps));
      render();
      return;
    }
  } catch {}

  const exists = isScrapped(post);
  state.scraps = exists
    ? state.scraps.filter((s) => s.id !== post.id && s.url !== post.url)
    : [{ ...payload, saved_at: new Date().toISOString() }, ...state.scraps];
  localStorage.setItem(LOCAL_SCRAP_KEY, JSON.stringify(state.scraps));
  render();
}

async function fetchDataset(name, fallback) {
  try {
    const res = await fetch(`/.netlify/functions/data?name=${encodeURIComponent(name)}&t=${Date.now()}`);
    if (res.ok) return await res.json();
  } catch {}
  return fetchJson(`data/${name}.json`, fallback);
}

async function loadAllData() {
  const [hot, ai, deals, games, reddit, econ] = await Promise.all([
    fetchDataset("community_hot", state.hotData),
    fetchDataset("community_ai", state.aiData),
    fetchDataset("deals", state.dealsData),
    fetchDataset("games", state.gamesData),
    fetchDataset("reddit", state.redditData),
    fetchDataset("economy_briefing", state.economyData),
    loadScraps(),
  ]);
  state.hotData = hot;
  state.aiData = ai;
  state.dealsData = deals;
  state.gamesData = games;
  state.redditData = reddit;
  state.economyData = econ;
  render();
}

function getAllPostsForCurrentTab() {
  if (state.tab === "hot") return state.hotData.posts || [];
  if (state.tab === "ai") return state.aiData.posts || [];
  if (state.tab === "deals") return state.dealsData.posts || [];
  if (state.tab === "games") return state.gamesData.posts || [];
  if (state.tab === "reddit") return state.redditData.posts || [];
  if (state.tab === "scraps") return state.scraps || [];
  return state.economyData.videos || [];
}

function findPostById(id) {
  const all = [
    ...(state.hotData.posts || []),
    ...(state.aiData.posts || []),
    ...(state.dealsData.posts || []),
    ...(state.gamesData.posts || []),
    ...(state.redditData.posts || []),
    ...(state.economyData.videos || []),
  ];
  return all.find((p) => p.id === id) || null;
}

function renderFilters() {
  if (state.tab === "scraps") {
    els.filterBar.classList.add("hidden");
    els.filterBar.innerHTML = "";
    return;
  }

  els.filterBar.classList.remove("hidden");

  if (state.tab === "deals") {
    const resetActive = state.dealToggles.size === 0 ? "active" : "";
    const chips = [
      `<button class="chip ${resetActive}" data-deal-reset="1">전체 보기</button>`,
      ...DEAL_CATEGORIES.map((cat) => {
        const on = state.dealToggles.has(cat) ? "active" : "";
        return `<button class="chip chip-toggle ${on}" data-deal-toggle="${esc(cat)}"><span class="dot"></span>${esc(cat)}</button>`;
      }),
    ];
    els.filterBar.innerHTML = chips.join("");
    return;
  }

  const posts = getAllPostsForCurrentTab();
  const sources = ["all", ...new Set(posts.map((p) => p.source))];

  const chips = sources.map((src) => {
    const label = src === "all" ? "전체" : src;
    const active = state.filter === src ? "active" : "";
    return `<button class="chip ${active}" data-filter="${esc(src)}">${esc(label)}</button>`;
  });

  if (state.tab === "hot" && (state.hotData.cross_topics || []).length > 0) {
    const active = state.filter === "__cross__" ? "active" : "";
    chips.splice(
      1,
      0,
      `<button class="chip ${active}" data-filter="__cross__">공동 화제</button>`
    );
  }

  els.filterBar.innerHTML = chips.join("");
}

function renderCrossTopics() {
  const topics = state.hotData.cross_topics || [];
  if (state.tab !== "hot" || topics.length === 0) {
    els.crossTopicSection.classList.add("hidden");
    els.crossTopicSection.innerHTML = "";
    return;
  }

  els.crossTopicSection.classList.remove("hidden");
  const itemsHtml = topics
    .slice(0, 5)
    .map((t) => {
      const pills = (t.posts || [])
        .map(
          (p) =>
            `<button class="cross-pill" data-post-id="${esc(p.id)}">[${esc(
              p.source
            )}] ${esc(p.title)}</button>`
        )
        .join("");
      return `
        <div class="cross-item">
          <div class="cross-keyword">🔥 ${esc(t.topic)} (${(t.sources || []).join(" · ")})</div>
          <div class="cross-links">${pills}</div>
        </div>
      `;
    })
    .join("");

  els.crossTopicSection.innerHTML = `
    <div class="section-title">여러 커뮤니티 동시 화제</div>
    ${itemsHtml}
  `;
}

function renderMarkets() {
  if (state.tab !== "economy") {
    els.marketSection.classList.add("hidden");
    els.marketSection.innerHTML = "";
    return;
  }

  els.marketSection.classList.remove("hidden");
  const markets = state.economyData.markets || [];
  const cards = markets
    .map((m) => {
      const cls = m.change_pct > 0 ? "up" : m.change_pct < 0 ? "down" : "flat";
      const sign = m.change_pct > 0 ? "+" : "";
      const dateBadge = m.date ? ` (${esc(m.date)})` : "";
      return `
        <div class="market-card">
          <div class="market-name">${esc(m.name)}${dateBadge}</div>
          <div class="market-price">${esc(m.price)}</div>
          <div class="market-chg ${cls}">${sign}${esc(m.change_pct)}%</div>
        </div>
      `;
    })
    .join("");

  const brief = state.economyData.market_brief
    ? `<div class="brief-box">${esc(state.economyData.market_brief)}</div>`
    : "";

  els.marketSection.innerHTML = `
    <div class="market-grid">${cards}</div>
    ${brief}
  `;
}

function renderPostList() {
  let posts = getAllPostsForCurrentTab();

  if (state.tab === "deals") {
    if (state.dealToggles.size > 0) {
      posts = posts.filter((p) => state.dealToggles.has(p.category));
    }
  } else if (state.tab !== "scraps") {
    if (state.filter === "__cross__") {
      posts = posts.filter((p) => p.is_cross_hot);
    } else if (state.filter !== "all") {
      posts = posts.filter((p) => p.source === state.filter);
    }
  }

  if (posts.length === 0) {
    const emptyMsg =
      state.tab === "scraps"
        ? "스크랩한 글이 없습니다. 목록이나 글 화면에서 ☆ 버튼을 눌러 보관하세요."
        : "표시할 게시글이 없습니다.";
    els.postList.innerHTML = `<div class="empty-state">${emptyMsg}</div>`;
    return;
  }

  els.postList.innerHTML = posts
    .map((p) => {
      const hotBadge = p.is_cross_hot
        ? `<span class="badge badge-hot">공동화제</span>`
        : "";
      const tagBadge = p.category
        ? `<span class="badge badge-tag">${esc(p.category)}</span>`
        : "";
      const saved = isScrapped(p);
      const starCls = saved ? "star-btn saved" : "star-btn";
      const starTxt = saved ? "★" : "☆";
      const metaStats = [
        p.author ? esc(p.author) : "",
        p.time ? esc(p.time) : "",
        p.likes !== undefined && p.likes !== null ? `추천 ${esc(p.likes)}` : "",
        p.comments !== undefined && p.comments !== null ? `댓글 ${esc(p.comments)}` : "",
      ]
        .filter(Boolean)
        .join(" · ");

      return `
        <div class="post-row" data-post-id="${esc(p.id)}" data-post-url="${esc(p.url || "")}" role="button" tabindex="0">
          <div class="post-meta-top">
            <div class="post-badges">
              <span class="badge">${esc(p.source || "슈카월드")}</span>
              ${hotBadge}
              ${tagBadge}
            </div>
            <button type="button" class="${starCls}" data-star-id="${esc(p.id)}" aria-label="스크랩">${starTxt}</button>
          </div>
          <div class="post-title">${esc(p.title)}</div>
          ${metaStats ? `<div class="post-meta-bottom">${metaStats}</div>` : ""}
        </div>
      `;
    })
    .join("");
}

function updateDetailStarButton(post) {
  const saved = isScrapped(post);
  els.detailStarBtn.classList.toggle("saved", saved);
  els.detailStarBtn.textContent = saved ? "★ 스크랩됨" : "☆ 스크랩";
}

function renderDetail(postId) {
  const post = findPostById(postId);
  if (!post) {
    showList();
    return;
  }

  state.currentPostId = post.id;
  els.listView.classList.add("hidden");
  els.detailView.classList.remove("hidden");

  els.originalLink.href = post.url || "#";
  updateDetailStarButton(post);

  const metaParts = [
    post.source || "슈카월드",
    post.author,
    post.time,
    post.likes !== undefined && post.likes !== null ? `추천 ${post.likes}` : "",
    post.comments !== undefined && post.comments !== null ? `댓글 ${post.comments}` : "",
  ].filter(Boolean);

  const imagesHtml = (post.images || [])
    .map(
      (src) =>
        `<img src="${esc(src)}" alt="첨부 이미지" loading="lazy" referrerpolicy="no-referrer" />`
    )
    .join("");

  const bodyText =
    post.content && post.content.trim()
      ? post.content
      : "본문 내용을 불러오지 못했습니다. 상단의 '원본 글 열기'를 이용해 주세요.";

  els.detailContent.innerHTML = `
    <h1 class="detail-title">${esc(post.title)}</h1>
    <div class="detail-meta">${metaParts.map((m) => `<span>${esc(m)}</span>`).join("")}</div>
    <div class="detail-body">${esc(bodyText)}</div>
    ${imagesHtml ? `<div class="detail-images">${imagesHtml}</div>` : ""}
  `;

  window.scrollTo({ top: 0, behavior: "instant" });
}

function showList() {
  state.currentPostId = null;
  els.detailView.classList.add("hidden");
  els.listView.classList.remove("hidden");
  window.scrollTo({ top: state.scrollY, behavior: "instant" });
}

function updateTimestamp() {
  const map = {
    hot: state.hotData.updated_at,
    ai: state.aiData.updated_at,
    deals: state.dealsData.updated_at,
    games: state.gamesData.updated_at,
    reddit: state.redditData.updated_at,
    economy: state.economyData.updated_at,
    scraps: state.scraps.length ? `보관 ${state.scraps.length}건` : "비어 있음",
  };
  if (state.tab === "scraps") {
    els.updatedAt.textContent = map.scraps;
  } else {
    els.updatedAt.textContent = map[state.tab]
      ? `업데이트: ${map[state.tab]}`
      : "수집 대기 중";
  }
}

function render() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    const active = btn.dataset.tab === state.tab;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });

  updateTimestamp();
  renderFilters();
  renderCrossTopics();
  renderMarkets();
  renderPostList();

  const hash = window.location.hash;
  if (hash.startsWith("#post=")) {
    const id = decodeURIComponent(hash.slice(6));
    renderDetail(id);
  } else {
    showList();
  }
}

function openPost(postId, fallbackUrl) {
  if (!findPostById(postId) && fallbackUrl) {
    window.open(fallbackUrl, "_blank", "noopener,noreferrer");
    return;
  }
  state.scrollY = window.scrollY;
  window.location.hash = `post=${encodeURIComponent(postId)}`;
}

// 이벤트 바인딩
els.mainTabs.addEventListener("click", (e) => {
  const btn = e.target.closest(".tab-btn");
  if (!btn) return;
  state.tab = btn.dataset.tab;
  state.filter = "all";
  state.scrollY = 0;
  if (window.location.hash.startsWith("#post=")) {
    window.history.replaceState(null, "", "#");
  }
  render();
});

els.filterBar.addEventListener("click", (e) => {
  const toggleBtn = e.target.closest("[data-deal-toggle]");
  if (toggleBtn) {
    const cat = toggleBtn.dataset.dealToggle;
    if (state.dealToggles.has(cat)) state.dealToggles.delete(cat);
    else state.dealToggles.add(cat);
    renderFilters();
    renderPostList();
    return;
  }

  if (e.target.closest("[data-deal-reset]")) {
    state.dealToggles.clear();
    renderFilters();
    renderPostList();
    return;
  }

  const chip = e.target.closest(".chip");
  if (!chip) return;
  state.filter = chip.dataset.filter;
  renderFilters();
  renderPostList();
});

document.addEventListener("click", (e) => {
  const starBtn = e.target.closest("[data-star-id]");
  if (starBtn) {
    e.stopPropagation();
    const id = starBtn.dataset.starId;
    const post = findPostById(id) || state.scraps.find((s) => s.id === id);
    if (post) toggleScrap(post);
    return;
  }

  const row = e.target.closest("[data-post-id]");
  if (!row) return;
  openPost(row.dataset.postId, row.dataset.postUrl);
});

els.detailStarBtn.addEventListener("click", () => {
  if (!state.currentPostId) return;
  const post = findPostById(state.currentPostId);
  if (post) toggleScrap(post);
});

els.backBtn.addEventListener("click", () => {
  if (window.location.hash.startsWith("#post=")) {
    window.history.back();
  } else {
    showList();
  }
});

window.addEventListener("hashchange", () => {
  if (window.location.hash.startsWith("#post=")) {
    const id = decodeURIComponent(window.location.hash.slice(6));
    renderDetail(id);
  } else {
    showList();
  }
});

if (initPinGate()) {
  loadAllData();
}
