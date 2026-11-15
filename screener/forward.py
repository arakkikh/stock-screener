"""フォワードテスト（シグナルの自動追跡）。市場に依存しない。

毎日の更新で、その日に出たシグナルを履歴に追記し、以後の更新でその後の成績を埋める。
数え方はバックテスト（screener/backtest.py）と同じ:
  ・サインの翌営業日の始値で買い、h 営業日後の終値で売った騰落率
  ・出口ルールどおりの売買は backtest.simulate で再現する
  ・指数も同じ日に同じ方法で買った騰落率を並べる
保存するのは公開してよい市場データだけ（銘柄・日付・種類・終値・設定の番号・その後の騰落率）。

保存の形（肥大化させないため）:
  docs/data/forward/{市場}_{年}.json  … シグナルの年ごとの履歴。1行に1件の配列で、項目名は fields に1回だけ書く
  docs/data/forward/{市場}_versions.json … しきい値設定の番号と、その中身・使い始めた日
  docs/data/forward/{市場}_summary.json  … 画面用の集計（小さい。画面はこれだけ読む）
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import backtest as bt
from . import indicators as ind
from . import momentum as mo

HORIZONS = (5, 10, 20)  # 何営業日後の騰落率を見るか（変えると過去の履歴と項目が合わなくなるので固定）
FIELDS = (
    ["d", "c", "k", "p", "v"]
    + [f"r{h}" for h in HORIZONS]     # 騰落率(%)
    + [f"i{h}" for h in HORIZONS]     # 同じ期間の指数の騰落率(%)
    + ["xr", "xd", "xe", "s"]         # 出口ルールどおりの売買: 騰落率・保有日数・決済理由 / 状態
)
COL = {name: i for i, name in enumerate(FIELDS)}
PENDING, DONE, LOST = 0, 1, 2  # 状態: 追跡中 / 完了 / 追跡できなくなった

# 逆張りの判定に使うしきい値（これが変わったら、別の設定として集計を分ける）
CONTRARIAN_SECTIONS = (
    "ma", "buy", "ma100_bounce", "swing", "bb_divergence", "zone", "candle", "gap_up", "island", "double", "entry", "trend",
)


# ---------------------------------------------------------------- シグナルの種類と設定の番号

def group_of(kind: str) -> str:
    """シグナルの種類を、集計のまとまりにする（entry / breakout / warn）。"""
    return "warn" if kind.startswith("warn:") else kind


def mode_of(kind: str) -> str:
    """そのシグナルを出すのが逆張り（contrarian）か順張り（momentum）か。"""
    return "momentum" if kind == "breakout" else "contrarian"


def config_part(cfg: dict, mode: str) -> dict:
    """設定の番号のもとになる、判定と出口に関係するしきい値だけを取り出す。"""
    if mode == "momentum":
        return {"momentum": cfg["momentum"], "forward": cfg["forward"]}
    return {**{k: cfg[k] for k in CONTRARIAN_SECTIONS if k in cfg}, "forward": cfg["forward"]}


def config_version(cfg: dict, mode: str) -> str:
    """しきい値の中身から作る短い番号。中身が同じなら同じ番号になる。"""
    text = json.dumps(config_part(cfg, mode), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------- その日のシグナル

def contrarian_signals(stocks: Iterable[dict], as_of: str) -> List[Tuple[str, str, float]]:
    """逆張りの判定結果から、その日に出たシグナル（エントリー候補・警戒サイン）を集める。

    最新日のデータが取れなかった銘柄（stale）は数えない。戻り値は (銘柄, 種類, 終値) の並び。
    """
    found = []
    for s in stocks:
        if s.get("stale") or s.get("date") != as_of:
            continue
        if s.get("entry"):
            found.append((s["code"], "entry", s["close"]))
        for key in s.get("warnings") or []:
            found.append((s["code"], f"warn:{key}", s["close"]))
    return found


def momentum_signals(stocks: Iterable[dict], as_of: str) -> List[Tuple[str, str, float]]:
    """順張りの判定結果から、その日に出来高を伴ってピボットを上抜けた銘柄を集める。"""
    found = []
    for s in stocks:
        vcp = s.get("vcp") or {}
        if s.get("stale") or s.get("date") != as_of:
            continue
        if vcp.get("status") == "breakout" and vcp.get("breakout_date") == as_of:
            found.append((s["code"], "breakout", s["close"]))
    return found


def add_signals(rows: List[list], signals, as_of: str, versions: Dict[str, str]) -> int:
    """シグナルを履歴に追記する。同じ日・銘柄・種類がすでにあれば足さない（やり直しても重複しない）。

    versions = {"contrarian": 番号, "momentum": 番号}。戻り値は追記した件数。
    """
    seen = {(r[COL["d"]], r[COL["c"]], r[COL["k"]]) for r in rows}
    added = 0
    for code, kind, close in signals:
        if (as_of, code, kind) in seen:
            continue
        row = [None] * len(FIELDS)
        row[COL["d"]], row[COL["c"]], row[COL["k"]] = as_of, code, kind
        row[COL["p"]], row[COL["v"]], row[COL["s"]] = close, versions[mode_of(kind)], PENDING
        rows.append(row)
        seen.add((as_of, code, kind))
        added += 1
    return added


# ---------------------------------------------------------------- その後の成績を埋める

def _round(value, digits: int = 2):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _forward_return(df: pd.DataFrame, i: int, h: int) -> Optional[float]:
    """i 日目のサインで、翌営業日の始値で買い h 営業日後の終値で売った騰落率(%)。先のデータがなければ None。"""
    if i + h >= len(df) or i + 1 >= len(df):
        return None
    return _round((df["close"].iloc[i + h] / df["open"].iloc[i + 1] - 1) * 100)


def exit_trade(df: pd.DataFrame, i: int, kind: str, cfg: dict) -> Optional[dict]:
    """出口ルールどおりに売買した結果。まだ決済していなければ None。警戒サインは売買しないので None。

    エントリー候補: 25日線まで戻したら利確、最大 forward.entry_max_hold 日（損切りは forward.entry_stop_pct）
    ブレイクアウト: 買値から損切り%・50日線を出来高を伴って割ったら手仕舞い、最大 forward.breakout_max_hold 日
    出口は追跡する時点の設定で計算する（設定を変えたら、番号が変わるので別に集計される）。
    """
    f = cfg["forward"]
    entries = pd.Series(False, index=df.index)
    entries.iloc[i] = True
    if kind == "entry":
        trades = bt.simulate(df, entries, take_dynamic=ind.sma(df["close"], cfg["ma"]["mid"]),
                             stop_pct=f["entry_stop_pct"], max_hold=f["entry_max_hold"])
    elif kind == "breakout":
        trades = bt.simulate(df, entries, stop_pct=cfg["momentum"]["exit"]["stop_loss_pct"],
                             stop_flag=mo.ma_break_with_volume(df, cfg), max_hold=f["breakout_max_hold"])
    else:
        return None
    if not trades or trades[0]["entry_i"] != i + 1:
        return None
    t = trades[0]
    return {"ret": _round(t["ret"]), "days": int(t["days"]), "reason": t["reason"]}


def _position(index: pd.Index, date: str, exact: bool) -> Optional[int]:
    """日付の行番号。exact=False なら、その日以前でいちばん近い営業日。"""
    ts = pd.Timestamp(date)
    if exact:
        return int(index.get_loc(ts)) if ts in index else None
    i = int(index.searchsorted(ts, side="right")) - 1
    return i if i >= 0 else None


def fill_outcomes(rows: List[list], frames: Dict[str, pd.DataFrame], index_df: Optional[pd.DataFrame],
                  cfg: dict, mode: str, as_of: dt.date) -> int:
    """追跡中のシグナルのうち、mode（逆張り／順張り）のものについて、その後の成績を埋める。

    frames = {銘柄コード: 日足}。lost_after_days（暦日）を過ぎても埋まらなければ「追跡できなくなった」にする。
    戻り値は、新たに完了または追跡不能になった件数。
    """
    finished = 0
    limit = cfg["forward"]["lost_after_days"]
    for row in rows:
        if row[COL["s"]] != PENDING or mode_of(row[COL["k"]]) != mode:
            continue
        kind, date = row[COL["k"]], row[COL["d"]]
        df = frames.get(row[COL["c"]])
        i = _position(df.index, date, exact=True) if df is not None else None
        if i is not None:
            j = _position(index_df.index, date, exact=False) if index_df is not None else None
            for h in HORIZONS:
                if row[COL[f"r{h}"]] is None:
                    row[COL[f"r{h}"]] = _forward_return(df, i, h)
                if row[COL[f"i{h}"]] is None and j is not None:
                    row[COL[f"i{h}"]] = _forward_return(index_df, j, h)
            if kind in ("entry", "breakout") and row[COL["xr"]] is None:
                trade = exit_trade(df, i, kind, cfg)
                if trade:
                    row[COL["xr"]], row[COL["xd"]], row[COL["xe"]] = trade["ret"], trade["days"], trade["reason"]
        needs_exit = kind in ("entry", "breakout")
        complete = all(row[COL[f"r{h}"]] is not None for h in HORIZONS) and (not needs_exit or row[COL["xr"]] is not None)
        if complete:
            row[COL["s"]] = DONE
            finished += 1
        elif (as_of - dt.date.fromisoformat(date)).days > limit:
            row[COL["s"]] = LOST
            finished += 1
    return finished


# ---------------------------------------------------------------- 集計（画面用）

def _stats(values) -> Optional[dict]:
    s = bt.summarize(values)
    return None if s is None else {k: s[k] for k in ("n", "win", "mean", "median")}


def summarize_rows(rows: List[list]) -> dict:
    """シグナルのまとまり（種類 × 設定の番号）ごとに、その後の成績を集計する。

    h       … 営業日後の騰落率・同じ期間の指数・その差（指数との差は、両方そろったものだけ）
    exit    … 出口ルールどおりの売買の成績
    warn は「その後に下がれば当たり」なので、勝率の代わりに下がった割合（hit）も出す。
    """
    groups: Dict[Tuple[str, str], List[list]] = {}
    for row in rows:
        groups.setdefault((group_of(row[COL["k"]]), row[COL["v"]]), []).append(row)
    out = []
    for (group, version), part in sorted(groups.items()):
        live = [r for r in part if r[COL["s"]] != LOST]
        entry = {
            "group": group,
            "version": version,
            "signals": len(part),
            "lost": len(part) - len(live),
            "first": min(r[COL["d"]] for r in part),
            "last": max(r[COL["d"]] for r in part),
            "h": {},
        }
        for h in HORIZONS:
            ret = [r[COL[f"r{h}"]] for r in live if r[COL[f"r{h}"]] is not None]
            both = [(r[COL[f"r{h}"]], r[COL[f"i{h}"]]) for r in live if r[COL[f"r{h}"]] is not None and r[COL[f"i{h}"]] is not None]
            stats = _stats(ret)
            if stats is not None:
                stats["index"] = round(float(np.mean([b for _, b in both])), 2) if both else None
                stats["excess"] = round(float(np.mean([a - b for a, b in both])), 2) if both else None
                stats["hit"] = round(float(np.mean([v < 0 for v in ret]) * 100), 1)
            entry["h"][str(h)] = stats
        trades = [r for r in live if r[COL["xr"]] is not None]
        if trades:
            stats = _stats([r[COL["xr"]] for r in trades])
            stats["days"] = round(float(np.mean([r[COL["xd"]] for r in trades])), 1)
            for reason in ("take", "stop", "time"):
                stats[reason] = round(sum(1 for r in trades if r[COL["xe"]] == reason) / len(trades) * 100, 1)
            entry["exit"] = stats
        else:
            entry["exit"] = None
        out.append(entry)
    # 警戒サインの種類ごと（10営業日後）
    warn_types: Dict[str, dict] = {}
    for kind in sorted({r[COL["k"]] for r in rows if group_of(r[COL["k"]]) == "warn"}):
        ret = [r[COL["r10"]] for r in rows if r[COL["k"]] == kind and r[COL["s"]] != LOST and r[COL["r10"]] is not None]
        stats = _stats(ret)
        if stats is not None:
            stats["hit"] = round(float(np.mean([v < 0 for v in ret]) * 100), 1)
        warn_types[kind[5:]] = {"signals": sum(1 for r in rows if r[COL["k"]] == kind), "h10": stats}
    return {"groups": out, "warn_types": warn_types}


# ---------------------------------------------------------------- 保存と読み込み

def _year_path(folder: Path, market: str, year: int) -> Path:
    return folder / f"{market}_{year}.json"


def load_rows(folder: Path, market: str, years: Iterable[int]) -> Dict[int, List[list]]:
    result = {}
    for year in years:
        path = _year_path(folder, market, year)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("fields") != FIELDS:
                raise ValueError(f"{path.name} の項目が想定と違います: {data.get('fields')}")
            result[year] = data["rows"]
        else:
            result[year] = []
    return result


def all_years(folder: Path, market: str) -> List[int]:
    return sorted(int(p.stem.split("_")[1]) for p in folder.glob(f"{market}_[0-9][0-9][0-9][0-9].json"))


def save_rows(folder: Path, market: str, year: int, rows: List[list]) -> None:
    """1行に1件で書く（毎日の差分が追記と書き換えの行だけになり、Git の履歴が膨らみにくい）。"""
    folder.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r[COL["d"]], r[COL["k"]], r[COL["c"]]))
    dumps = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    head = dumps({"market": market, "year": year, "fields": FIELDS})[:-1]
    body = ",\n".join(dumps(r) for r in rows)
    _year_path(folder, market, year).write_text(f'{head},"rows":[\n{body}\n]}}\n', encoding="utf-8")


def update(folder: Path, market: str, cfg: dict, as_of: dt.date, mode: str, signals,
           frames: Dict[str, pd.DataFrame], index_df: Optional[pd.DataFrame], now: dt.datetime) -> dict:
    """1回分の更新: その日のシグナルを追記し、追跡中のものの成績を埋め、画面用の集計を作り直す。

    mode = "contrarian"（逆張りの更新から呼ぶ）/ "momentum"（順張りの更新から呼ぶ）。
    追跡中のシグナルは、追跡できなくなるまでの日数より新しいので、今年と去年のファイルだけを読み書きする。
    """
    today = as_of.isoformat()
    versions_path = folder / f"{market}_versions.json"
    registry = json.loads(versions_path.read_text(encoding="utf-8")) if versions_path.exists() else {}
    current = {m: config_version(cfg, m) for m in ("contrarian", "momentum")}
    for m, version in current.items():
        if version not in registry:
            registry[version] = {"mode": m, "first": today, "config": config_part(cfg, m)}

    years = [as_of.year - 1, as_of.year]
    loaded = load_rows(folder, market, years)
    added = add_signals(loaded[as_of.year], signals, today, current)
    finished = 0
    for year in years:
        finished += fill_outcomes(loaded[year], frames, index_df, cfg, mode, as_of)
    for year in years:
        if loaded[year] or _year_path(folder, market, year).exists():
            save_rows(folder, market, year, loaded[year])

    # 集計は全期間から作り直す（年ごとのファイルを順に読む）
    rows = [r for y in all_years(folder, market) for r in load_rows(folder, market, [y])[y]]
    summary = summarize_rows(rows)
    folder.mkdir(parents=True, exist_ok=True)
    versions_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    payload = {
        "market": market,
        "as_of": today,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started": min(e["first"] for e in registry.values()),  # 追跡を始めた日（シグナルが0件の日も含む）
        "horizons": list(HORIZONS),
        "current": current,
        "versions": {v: {"mode": e["mode"], "first": e["first"]} for v, e in registry.items()},
        "pending": sum(1 for r in rows if r[COL["s"]] == PENDING),
        **summary,
    }
    (folder / f"{market}_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return {"added": added, "finished": finished, "total": len(rows)}
