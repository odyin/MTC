# MTC - MultiCharts Trading Code System

## 專案位置
- 伺服器路徑：`/home/user/MTC`
- GitHub：`odyin/MTC`
- 開發分支：`claude/automated-trading-strategy-system-uDotz`

## 專案目的
自動化 MultiCharts 策略交易系統，支援台指期（TAIEX Futures）策略的生成、回測、優化與版本追蹤。

## 資料
| 檔案 | 說明 | 筆數 |
|------|------|------|
| `data/processed/TX_1d.csv` | 台指期日線 OHLCV | 2600 筆（2015-01-05 起） |
| `data/processed/TX_5m_sample.csv` | 台指期 5 分鐘樣本資料 | 少量 |

CSV 格式：`datetime,open,high,low,close,volume`，datetime 格式為 `YYYY-MM-DD HH:MM:SS`

## 策略檔案
| 檔案 | 名稱 | 時間框架 | 說明 |
|------|------|---------|------|
| `strategies/examples/ma_cross.yaml` | MA_Cross_TAIEX | 5m | 雙均線交叉（5分鐘版） |
| `strategies/examples/ma_cross_daily.yaml` | MA_Cross_TAIEX_Daily | 1d | 雙均線交叉（日線版） |
| `strategies/examples/rsi_reversal.yaml` | - | 5m | RSI 反轉 |
| `strategies/examples/kd_macd_combo.yaml` | - | 5m | KD + MACD |
| `strategies/examples/bollinger_breakout.yaml` | - | 5m | 布林突破 |

## 回測歷史（output/mtc.db）
| ID | 策略 | Sharpe | 淨損益 | 勝率 | 交易數 | 最大回撤 |
|----|------|--------|--------|------|--------|---------|
| 1 | MA_Cross_TAIEX | 0.00 | 0 | 0% | 0 | 0 |
| 2 | MA_Cross_TAIEX_Daily | -2.16 | -640,000 | 27.3% | 88 | 880,000 |

## 常用指令
```bash
# 回測
python -m src.cli backtest strategies/examples/ma_cross_daily.yaml --data data/processed/TX_1d.csv --trades

# 參數優化（網格搜尋）
python -m src.cli optimize strategies/examples/ma_cross_daily.yaml --data data/processed/TX_1d.csv --method grid --metric sharpe_ratio

# 遺傳演算法優化
python -m src.cli optimize strategies/examples/ma_cross_daily.yaml --data data/processed/TX_1d.csv --method genetic --generations 100

# 查看回測報告
python -m src.cli report --top 10

# 產生 PowerLanguage 程式碼
python -m src.cli generate strategies/examples/ma_cross_daily.yaml
```

## 目前進度
- [x] 專案架構建立完成
- [x] 台指期日線資料匯入（TX_1d.csv，2600筆）
- [x] MA Cross 日線回測完成（結果不佳，需優化）
- [ ] 參數優化（MA 週期、停損停利）
- [ ] 測試其他策略（RSI、KD+MACD、布林）
- [ ] Walk-Forward 分析

## MA Cross 日線策略問題
- 勝率 27.3%，損益比 2:1（停損 200 點、停利 400 點），損益平衡點需 33% 勝率
- 在震盪盤被頻繁止損
- 下一步：跑網格搜尋優化均線週期與停損停利參數

## 環境
```bash
pip install numpy pandas pyyaml jinja2 pytest
```
