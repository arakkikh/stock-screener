// サインの種類（データ側のキー）と、画面に出す名前の対応表。

export const REVERSAL = {
  engulfing: "抱き線",
  harami: "はらみ線",
  doji: "十字線",
  double_bottom: "ダブルボトム上抜け",
  triple_bottom: "トリプルボトム上抜け",
  island_bottom: "アイランドボトム",
  gap_up: "ギャップアップ",
};

export const WARNING = {
  hanging_man: "首吊り線",
  harami_top: "高値圏のはらみ線",
  double_top: "ダブルトップ割れ",
  triple_top: "トリプルトップ割れ",
  island_top: "アイランドリバーサル",
  two_black: "下放れ二本黒",
};

export const OTHER = {
  entry: "エントリー候補",
  bounce: "100日線で反発",
  divergence: "−2σダイバージェンス",
  two_white: "上放れ並び赤",
};

export const LABEL = { ...REVERSAL, ...WARNING, ...OTHER };

// チャートに付ける印の短い名前
export const SHORT = {
  engulfing: "抱", harami: "はらみ", doji: "十字", double_bottom: "W底", triple_bottom: "三底",
  island_bottom: "島", gap_up: "窓↑", hanging_man: "首吊", harami_top: "はらみ", double_top: "W天",
  triple_top: "三天", island_top: "島", two_black: "二本黒", bounce: "100日", divergence: "ダイバ",
  two_white: "並び赤",
};

export const MA_NAME = { short: "ma_s", mid: "ma_m", long: "ma_l" };
