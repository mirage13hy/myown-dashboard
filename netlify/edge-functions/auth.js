// Netlify Edge Function: 개인 대시보드 비밀번호 잠금 (방안 B)
// Netlify 환경변수 DASHBOARD_PASSWORD가 설정되어 있을 때만 잠금이 활성화됩니다.

const COOKIE_NAME = "dash_auth";

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function parseCookies(cookieHeader) {
  const cookies = {};
  if (!cookieHeader) return cookies;
  for (const part of cookieHeader.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k) cookies[k] = decodeURIComponent(v.join("="));
  }
  return cookies;
}

function renderLoginHtml(hasError = false) {
  return `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>대시보드 로그인</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #0f172a;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 16px;
      box-sizing: border-box;
    }
    .card {
      width: 100%;
      max-width: 360px;
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 16px;
      padding: 28px 24px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.35);
    }
    h1 { font-size: 1.25rem; margin: 0 0 8px; }
    p { font-size: 0.9rem; color: #94a3b8; margin: 0 0 20px; }
    input {
      width: 100%;
      box-sizing: border-box;
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid #475569;
      background: #0f172a;
      color: #f8fafc;
      font-size: 1rem;
      margin-bottom: 12px;
    }
    button {
      width: 100%;
      padding: 12px;
      border: none;
      border-radius: 10px;
      background: #3b82f6;
      color: white;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
    }
    .err { color: #f87171; font-size: 0.85rem; margin-bottom: 12px; }
  </style>
</head>
<body>
  <form class="card" method="POST" action="/__auth">
    <h1>나만의 대시보드</h1>
    <p>개인 전용 공간입니다. 비밀번호를 입력하세요.</p>
    ${hasError ? '<div class="err">비밀번호가 올바르지 않습니다.</div>' : ""}
    <input type="password" name="password" placeholder="비밀번호" autofocus required />
    <button type="submit">입장하기</button>
  </form>
</body>
</html>`;
}

export default async function handler(request, context) {
  const password = Netlify.env.get("DASHBOARD_PASSWORD");
  if (!password) {
    return context.next();
  }

  const url = new URL(request.url);
  const ingestToken = Netlify.env.get("INGEST_TOKEN") || password;
  if (
    url.pathname === "/.netlify/functions/data" &&
    request.method === "POST" &&
    request.headers.get("x-ingest-token") === ingestToken
  ) {
    return context.next();
  }

  const expectedToken = await sha256Hex(`myown:${password}`);

  if (url.pathname === "/__auth" && request.method === "POST") {
    const form = await request.formData();
    const input = String(form.get("password") || "");
    if (input === password) {
      return new Response(null, {
        status: 302,
        headers: {
          Location: "/",
          "Set-Cookie": `${COOKIE_NAME}=${expectedToken}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`,
        },
      });
    }
    return new Response(renderLoginHtml(true), {
      status: 401,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }

  if (url.pathname === "/__logout") {
    return new Response(null, {
      status: 302,
      headers: {
        Location: "/",
        "Set-Cookie": `${COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`,
      },
    });
  }

  const cookies = parseCookies(request.headers.get("cookie"));
  if (cookies[COOKIE_NAME] === expectedToken) {
    return context.next();
  }

  return new Response(renderLoginHtml(false), {
    status: 401,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}
