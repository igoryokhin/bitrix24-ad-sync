export async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });

  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }

  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await res.json() : await res.text();

  if (!res.ok) {
    const err = new Error((data && data.error) || res.statusText);
    err.data = data;
    err.status = res.status;
    throw err;
  }
  return data;
}

export function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  el.classList.toggle("error", isError);
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 4000);
}
