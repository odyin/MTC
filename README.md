# MTC - MultiCharts Trading Code System

自動化 MultiCharts 策略交易系統，支援台指期（TAIEX Futures）策略的生成、回測、優化與版本追蹤。

## 功能

- **策略生成** - 從 YAML 配置自動產生 MultiCharts PowerLanguage (.pla) 程式碼
- **Python 回測** - 模擬 MultiCharts 執行邏輯的回測引擎（next-bar-at-market）
- **參數優化** - 網格搜尋 / 遺傳演算法 / Walk-Forward 分析
- **版本追蹤** - SQLite 記錄所有策略版本與回測結果
- **技術指標** - MA、RSI、MACD、布林通道、KD 隨機指標、ATR

## 安裝

```bash
pip install pyyaml jinja2 numpy pandas pytest
```

## 使用方式

### 1. 產生 PowerLanguage 程式碼
```bash
python -m src.cli generate strategies/examples/ma_cross.yaml
```

### 2. 回測策略
```bash
python -m src.cli backtest strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --trades
```

### 3. 網格搜尋優化
```bash
python -m src.cli optimize strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --method grid --metric sharpe_ratio
```

### 4. 遺傳演算法優化
```bash
python -m src.cli optimize strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --method genetic --generations 100
```

### 5. Walk-Forward 分析
```bash
python -m src.cli optimize strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --method walk_forward
```

### 6. 查看回測報告
```bash
python -m src.cli report --strategy MA_Cross_TAIEX --top 10
```

### 7. 迭代策略（更新參數產生新版本）
```bash
python -m src.cli iterate strategies/examples/ma_cross.yaml --params "fast_ma.period=15,slow_ma.period=40"
```

## 策略配置格式 (YAML)

```yaml
name: "MA_Cross_TAIEX"
version: "1.0"
instrument: "TX"
timeframe: "5m"

indicators:
  - type: ma
    name: fast_ma
    params:
      period: {default: 10, min: 5, max: 50, step: 5}
      method: "SMA"
      source: "close"

entry:
  long:
    condition: "fast_ma crosses_above slow_ma"
  short:
    condition: "fast_ma crosses_below slow_ma"

exit:
  stop_loss: {type: "points", value: 100}
  take_profit: {type: "points", value: 200}
  time_exit: {enabled: true, time: "13:30"}

risk:
  max_daily_loss: 300
  session_filter: "day"
```

## 內建範例策略

| 策略 | 說明 | 檔案 |
|------|------|------|
| MA 交叉 | 雙均線交叉 | `strategies/examples/ma_cross.yaml` |
| RSI 反轉 | RSI 超買超賣 + 趨勢過濾 | `strategies/examples/rsi_reversal.yaml` |
| KD + MACD | KD 交叉配合 MACD 確認 | `strategies/examples/kd_macd_combo.yaml` |
| 布林突破 | 布林通道突破 + ATR 動態停損 | `strategies/examples/bollinger_breakout.yaml` |

## 條件語法 DSL

| DSL 語法 | PowerLanguage 對應 | 說明 |
|----------|-------------------|------|
| `crosses_above` | `crosses above` | 上穿 |
| `crosses_below` | `crosses below` | 下穿 |
| `above` | `>` | 大於 |
| `below` | `<` | 小於 |
| `and` | `and` | 且 |
| `or` | `or` | 或 |

## 資料格式

CSV 檔案需包含以下欄位：
```
datetime,open,high,low,close,volume
2024-01-02 08:45:00,17500,17520,17480,17510,1234
```

## 測試

```bash
python -m pytest tests/ -v
```

## 專案結構

```
MTC/
├── config/settings.yaml          # 全域設定
├── strategies/examples/          # 策略 YAML 範例
├── templates/                    # Jinja2 PowerLanguage 模板
├── src/
│   ├── cli.py                    # CLI 入口
│   ├── codegen/generator.py      # PowerLanguage 程式碼生成
│   ├── backtest/engine.py        # 回測引擎
│   ├── backtest/indicators.py    # 技術指標計算
│   ├── optimizer/grid.py         # 網格搜尋
│   ├── optimizer/genetic.py      # 遺傳演算法
│   ├── optimizer/walk_forward.py # Walk-Forward 分析
│   └── tracker/db.py             # SQLite 追蹤器
├── output/powerlanguage/         # 生成的 .pla 檔案
└── tests/                        # 測試
```
