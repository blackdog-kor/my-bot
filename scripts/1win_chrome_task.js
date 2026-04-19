/**
 * Chrome용 Claude 예약 작업 스크립트
 * 매일 09:00 KST (00:00 UTC) 실행
 *
 * 설정 방법:
 *   1. Chrome에서 claude.ai 열기
 *   2. 오른쪽 상단 → 작업 → 새 예약 작업
 *   3. 이 스크립트 붙여넣기
 *   4. 실행 주기: 매일 09:00 (KST)
 *   5. RAILWAY_WEBHOOK_URL 값을 실제 Railway 도메인으로 교체
 */

const RAILWAY_WEBHOOK_URL = "https://web-production-608e6.up.railway.app/api/affiliate/stats";
const AFFILIATE_WEBHOOK_SECRET = "uZNqnyH1O388R52qTHqprVZM6TzytjtjG7A7y_mbC6Y";

const API_BASE = "https://1win-partners.com";

async function getToday() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

async function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

async function fetchStats(dateFrom, dateTo, accessToken) {
  const url = `${API_BASE}/api/v5/stats/common?dateFrom=${dateFrom}&dateTo=${dateTo}&currency=USD`;
  const res = await fetch(url, {
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    credentials: "include",
  });
  if (!res.ok) throw new Error(`stats API ${res.status}: ${await res.text()}`);
  return res.json();
}

async function fetchLinks(accessToken) {
  const res = await fetch(`${API_BASE}/api/v2/links/info`, {
    headers: {
      "Authorization": `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    credentials: "include",
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data?.data?.links || data?.links || [];
}

async function getAccessToken() {
  // Try from localStorage first
  const token = localStorage.getItem("accessToken")
    || localStorage.getItem("token")
    || sessionStorage.getItem("accessToken");
  if (token) return token;

  // Fallback: extract from cookie
  const match = document.cookie.match(/(?:^|;\s*)accessToken=([^;]+)/);
  if (match) return decodeURIComponent(match[1]);

  throw new Error("accessToken not found. Please log in to 1win-partners.com first.");
}

async function refreshIfNeeded(accessToken) {
  // Validate JWT expiry
  try {
    const payload = JSON.parse(atob(accessToken.split(".")[1]));
    if (payload.exp * 1000 > Date.now() + 60000) return accessToken;
  } catch (_) {}

  // Attempt refresh
  const refreshToken = localStorage.getItem("refreshToken")
    || "4ed86fff-796d-4a21-a8c1-a73f6652d8af";
  const res = await fetch(`${API_BASE}/api/v2/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refreshToken }),
    credentials: "include",
  });
  if (!res.ok) throw new Error(`Token refresh failed: ${res.status}`);
  const data = await res.json();
  const newToken = data?.accessToken || data?.data?.accessToken;
  if (newToken) localStorage.setItem("accessToken", newToken);
  return newToken || accessToken;
}

async function postToRailway(payload) {
  const res = await fetch(RAILWAY_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Railway POST ${res.status}: ${await res.text()}`);
  return res.json();
}

async function main() {
  console.log("[1win] Starting daily stats collection...");

  const dateFrom = await getYesterday();
  const dateTo   = await getYesterday();

  let token = await getAccessToken();
  token = await refreshIfNeeded(token);

  let statsData = {};
  try {
    const raw = await fetchStats(dateFrom, dateTo, token);
    statsData = raw?.data || raw?.stats || raw || {};
    console.log("[1win] Stats fetched:", JSON.stringify(statsData).slice(0, 200));
  } catch (err) {
    console.warn("[1win] Stats fetch failed (will send zeros):", err.message);
  }

  let links = [];
  try {
    const rawLinks = await fetchLinks(token);
    links = rawLinks.map(l => ({
      code: l.code || l.link || "",
      source_id: l.source_id || l.sourceId || null,
      clicks: l.clicks || l.clickCount || 0,
      registrations: l.registrations || l.regCount || 0,
    }));
  } catch (err) {
    console.warn("[1win] Links fetch failed:", err.message);
  }

  const payload = {
    secret: AFFILIATE_WEBHOOK_SECRET,
    date_from: dateFrom,
    date_to: dateTo,
    clicks:        Number(statsData.clicks        || statsData.clickCount    || 0),
    registrations: Number(statsData.registrations || statsData.regCount      || 0),
    ftd_count:     Number(statsData.ftd           || statsData.ftdCount      || 0),
    deposits:      Number(statsData.deposits      || statsData.depositAmount || 0),
    revenue:       Number(statsData.revenue       || statsData.profit        || 0),
    commission:    Number(statsData.commission    || statsData.earnings      || 0),
    source: "chrome",
    links,
    extra: { raw_stats: statsData },
  };

  const result = await postToRailway(payload);
  console.log("[1win] Sent to Railway:", JSON.stringify(result));
  return `✅ 1win stats for ${dateFrom}: clicks=${payload.clicks}, reg=${payload.registrations}, commission=$${payload.commission}`;
}

main().catch(err => {
  console.error("[1win] Task failed:", err);
  return `❌ 1win stats collection failed: ${err.message}`;
});
