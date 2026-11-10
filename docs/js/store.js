// ブラウザ内（localStorage）への保存。データはこの端末のこのブラウザにだけ残る。
const PREFIX = "screener:";

export const store = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  },
  remove(key) {
    localStorage.removeItem(PREFIX + key);
  },
};

// エクスポート用: このアプリが保存したデータをすべて取り出す
export function exportAll() {
  const data = {};
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key.startsWith(PREFIX)) data[key.slice(PREFIX.length)] = JSON.parse(localStorage.getItem(key));
  }
  return { app: "stock-screener", version: 1, exportedAt: new Date().toISOString(), data };
}

// インポート用: 今のデータを消して、読み込んだデータに置き換える
export function importAll(payload) {
  if (!payload || payload.app !== "stock-screener" || typeof payload.data !== "object" || payload.data === null) {
    throw new Error("このアプリのエクスポートファイルではありません。");
  }
  if (payload.data.positions !== undefined && !Array.isArray(payload.data.positions)) {
    throw new Error("ファイルの中身が壊れています。");
  }
  const old = [];
  for (let i = 0; i < localStorage.length; i++) {
    if (localStorage.key(i).startsWith(PREFIX)) old.push(localStorage.key(i));
  }
  old.forEach((key) => localStorage.removeItem(key));
  for (const [key, value] of Object.entries(payload.data)) store.set(key, value);
}
