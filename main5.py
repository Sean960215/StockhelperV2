import sys
import datetime
import json
import os
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtUiTools import QUiLoader # PySide6 載入 UI 的工具
from PySide6.QtWidgets import QVBoxLayout, QMessageBox, QCompleter, QGridLayout, QLineEdit, QPushButton
from PySide6.QtCore import QThread, Signal
import yfinance as yf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

# 設定 Matplotlib 字型 (避免中文亂碼)
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei']
plt.rcParams['axes.unicode_minus'] = False


# ========== 簡單計算機類 ==========
class SimpleCalculator(QtWidgets.QWidget):
    """簡單的浮動計算機"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("計算機")
        self.setGeometry(100, 100, 350, 500)
        self.initUI()
        
    def initUI(self):
        """初始化 UI"""
        layout = QVBoxLayout()
        
        # 顯示螢幕
        self.display = QLineEdit()
        self.display.setReadOnly(True)
        self.display.setAlignment(QtCore.Qt.AlignRight)
        self.display.setStyleSheet("""
            QLineEdit {
                font-size: 24px;
                padding: 10px;
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 3px;
                color: #000000;
            }
        """)
        self.display.setText("0")
        layout.addWidget(self.display)
        
        # 按鍵佈局
        grid = QGridLayout()
        
        buttons = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2), ('÷', 0, 3),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2), ('×', 1, 3),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2), ('-', 2, 3),
            ('0', 3, 0), ('.', 3, 1), ('=', 3, 2), ('+', 3, 3),
            ('C', 4, 0), ('←', 4, 1), ('√', 4, 2), ('%', 4, 3),
        ]
        
        for (text, row, col) in buttons:
            btn = QPushButton(text)
            btn.setMinimumHeight(50)
            btn.setFont(QtGui.QFont('Arial', 12, QtGui.QFont.Bold))
            
            # 設定按鈕顏色
            if text in ['÷', '×', '-', '+', '=']:
                btn.setStyleSheet("QPushButton { background-color: #FF9500; color: #000000; font-weight: bold; border-radius: 3px; }")
                btn.clicked.connect(lambda checked, t=text: self.on_operator(t))
            elif text in ['C', '←']:
                btn.setStyleSheet("QPushButton { background-color: #FF6B6B; color: #000000; font-weight: bold; border-radius: 3px; }")
                btn.clicked.connect(lambda checked, t=text: self.on_clear(t))
            elif text in ['√', '%']:
                btn.setStyleSheet("QPushButton { background-color: #4ECDC4; color: #000000; font-weight: bold; border-radius: 3px; }")
                btn.clicked.connect(lambda checked, t=text: self.on_operator(t))
            else:
                btn.setStyleSheet("QPushButton { background-color: #e0e0e0; color: #000000; font-weight: bold; border-radius: 3px; }")
                btn.clicked.connect(lambda checked, t=text: self.on_number(t))
            
            grid.addWidget(btn, row, col)
        
        layout.addLayout(grid)
        self.setLayout(layout)
        
        self.expression = ""
    
    def on_number(self, num):
        """按下數字鍵"""
        if self.display.text() == "0":
            self.display.setText(num)
        else:
            self.display.setText(self.display.text() + num)
        self.expression += str(num)
    
    def on_operator(self, op):
        """按下操作符"""
        current = self.display.text()
        
        if op == '=':
            try:
                # 將中文符號轉換為英文
                calc_expr = self.expression.replace('÷', '/').replace('×', '*').replace('√', 'sqrt')
                
                # 如果包含 sqrt，需要匯入 math
                if 'sqrt' in calc_expr:
                    from math import sqrt
                    result = eval(calc_expr)
                else:
                    result = eval(calc_expr)
                
                self.display.setText(str(result))
                self.expression = str(result)
            except:
                self.display.setText("錯誤")
                self.expression = ""
        
        elif op == '√':
            try:
                from math import sqrt
                value = float(current)
                result = sqrt(value)
                self.display.setText(str(result))
                self.expression = str(result)
            except:
                self.display.setText("錯誤")
                self.expression = ""
        
        elif op == '%':
            try:
                value = float(current)
                result = value / 100
                self.display.setText(str(result))
                self.expression = str(result)
            except:
                self.display.setText("錯誤")
                self.expression = ""
        
        else:  # +, -, ×, ÷
            self.expression += op
            self.display.setText(current + op)
    
    def on_clear(self, action):
        """清除或退格"""
        if action == 'C':
            self.display.setText("0")
            self.expression = ""
        elif action == '←':
            text = self.display.text()
            if len(text) > 1:
                self.display.setText(text[:-1])
                self.expression = self.expression[:-1]
            else:
                self.display.setText("0")
                self.expression = ""



class StockFetchWorker(QThread):
    """在後台執行緒中抓取股票數據，避免 UI 卡頓"""
    
    # 定義信號：用來傳送結果回主線程
    data_ready = Signal(dict)  # 成功時發送數據字典
    error_occurred = Signal(str)  # 失敗時發送錯誤訊息
    
    def __init__(self, code, period="1mo"):
        super().__init__()
        self.code = code
        self.period = period  # 儲存原始 period（"1h", "1d", "3d", "1mo"）
    
    def run(self):
        """執行緒的主函數"""
        import time
        start_time = time.time()
        
        try:
            raw_code = self.code.strip().upper()
            
            if not raw_code:
                self.error_occurred.emit("請輸入股票代號")
                return
            
            final_code = raw_code
            if raw_code.isdigit():
                final_code = f"{raw_code}.TW"
            
            # 根據時間區間設定正確的 period 和 interval
            period_config = {
                "1d": ("5d", "1h"),      # 過去 5 天，1 小時粒度（顯示最近 1 天的走勢）
                "1w": ("1mo", "1d"),     # 過去 1 月，1 天粒度（包含約 1 週的交易日）
                "1mo": ("3mo", "1d"),    # 過去 3 月，1 天粒度
                "3mo": ("6mo", "1d"),    # 過去 6 月，1 天粒度
                "1y": ("1y", "1d")       # 過去 1 年，1 天粒度
            }
            
            period, interval = period_config.get(self.period, ("1mo", None))
            
            stock = yf.Ticker(final_code)
            if interval:
                hist = stock.history(period=period, interval=interval)
            else:
                hist = stock.history(period=period)
            
            # 如果 .TW 找不到且輸入的是數字，嘗試切換成上櫃 .TWO
            if hist.empty and raw_code.isdigit():
                final_code = f"{raw_code}.TWO"
                stock = yf.Ticker(final_code)
                if interval:
                    hist = stock.history(period=period, interval=interval)
                else:
                    hist = stock.history(period=period)
            
            if hist.empty:
                self.error_occurred.emit(f"找不到 {raw_code} 的資料")
                return
            
            # 取得股票名稱
            try:
                info = stock.info
                stock_name = info.get('longName') or info.get('shortName') or final_code
            except Exception:
                stock_name = final_code
            
            # 計算數據
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
            
            day_high = hist['High'].iloc[-1]
            day_low = hist['Low'].iloc[-1]
            day_open = hist['Open'].iloc[-1]  # 新增：當日開盤價
            
            # 構建結果字典
            result = {
                'final_code': final_code,
                'stock_name': stock_name,
                'current_price': current_price,
                'prev_close': prev_close,
                'change': change,
                'change_pct': change_pct,
                'day_high': day_high,
                'day_low': day_low,
                'day_open': day_open,  # 新增
                'hist': hist,
                'period': self.period,
                'start_time': start_time,
                'success': True
            }
            
            self.data_ready.emit(result)
        
        except Exception as e:
            self.error_occurred.emit(f"讀取異常：{str(e)}")


class StockApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 1. 載入 UI
        loader = QUiLoader()
        ui_file = QtCore.QFile("stock_ui.ui")
        if not ui_file.open(QtCore.QFile.ReadOnly):
            print("錯誤：找不到 stock_ui.ui 檔案")
            sys.exit()
        
        self.ui = loader.load(ui_file, self)
        ui_file.close()

        self.setCentralWidget(self.ui)
        self.setWindowTitle("Stock Dashboard")
        self.resize(1200, 700)
        self.setMinimumSize(800, 600)  # 設定最小視窗大小

        # 2. 初始化 Matplotlib 圖表（雙軸：價格和成交量）
        self.figure, (self.ax, self.ax_volume) = plt.subplots(
            2, 1, 
            figsize=(12, 6), 
            dpi=100,
            gridspec_kw={'height_ratios': [3, 1]}  # 價格圖佔 3/4，成交量圖佔 1/4
        )
        self.figure.patch.set_facecolor('#FAFAFA')  # 淺灰背景
        self.canvas = FigureCanvas(self.figure)
        
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        
        # 將圖表放入 UI 定義的 chart_container
        self.ui.chart_container.setLayout(layout)

        # 3. 按鈕功能綁定
        self.ui.btn_search.clicked.connect(self.search_stock)
        self.ui.input_code.returnPressed.connect(self.search_stock)

        # 4. 設定自動更新計時器
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.auto_refresh_logic)
        self.ui.chk_auto.stateChanged.connect(self.toggle_timer)

        # 5. 設定時鐘計時器
        self.clock_timer = QtCore.QTimer()
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

        # 6. 初始化後台執行緒變數
        self.fetch_worker = None
        
        # 7. 設定當前時間區間（預設 1 個月）
        self.current_period = "1mo"

        # 8. 初始化我的最愛功能
        self.favorites_file = "favorites.json"
        self.favorites = self.load_favorites()
        self.current_stock = None  # 當前查詢的股票代號
        
        # 9. 初始化價格警報
        self.alerts_file = "price_alerts.json"
        self.price_alerts = self.load_alerts()  # {stock_code: {"target": price, "type": "above/below"}}
        self.last_update_time = None  # 最後更新時間
        
        # 初始化深色模式
        self.dark_mode = False
        self.setup_theme()
        
        # 設定搜尋建議
        self.setup_search_suggestions()
        
        # 10. 綁定我的最愛按鈕和選單
        self.ui.btn_favorite.clicked.connect(self.toggle_favorite)
        self.ui.combo_favorites.currentTextChanged.connect(self.on_favorite_selected)
        self.update_favorites_combo()
        
        # 綁定價格警報按鈕
        self.ui.btn_alert.clicked.connect(self.set_price_alert)
        
        # 綁定深色模式切換按鈕
        self.ui.btn_theme.clicked.connect(self.toggle_theme)

        # 綁定計算機按鈕
        self.ui.btn_calculator.clicked.connect(self.open_calculator)
        
        # 11. 綁定時間區間按鈕
        self.ui.btn_1d.clicked.connect(lambda: self.change_period("1d"))
        self.ui.btn_1w.clicked.connect(lambda: self.change_period("1w"))
        self.ui.btn_1mo.clicked.connect(lambda: self.change_period("1mo"))
        self.ui.btn_3m.clicked.connect(lambda: self.change_period("3mo"))
        self.ui.btn_1y.clicked.connect(lambda: self.change_period("1y"))

        # 預設執行一次查詢
        self.ui.input_code.setText("2330")
        self.search_stock()
        
        # 初始化計算機視窗參考
        self.calculator_window = None

    def update_clock(self):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ui.label_time.setText(f"Time: {now}")

    def toggle_timer(self):
        if self.ui.chk_auto.isChecked():
            self.timer.start(10000) # 每 10 秒更新一次
        else:
            self.timer.stop()

    def auto_refresh_logic(self):
        self.search_stock(is_auto=True)

    def search_stock(self, is_auto=False):
        """搜尋股票，在後台執行緒中運行"""
        code = self.ui.input_code.text().strip().upper()
        
        if not code: 
            return

        # 如果已有執行緒在運行，等待其完成或停止
        if self.fetch_worker is not None and self.fetch_worker.isRunning():
            return
        
        # 創建新的執行緒（傳入當前時間區間）
        self.fetch_worker = StockFetchWorker(code, self.current_period)
        
        # 連接信號到槽函數
        self.fetch_worker.data_ready.connect(lambda data: self.on_stock_data_ready(data, is_auto))
        self.fetch_worker.error_occurred.connect(lambda msg: self.on_stock_error(msg, is_auto))
        
        # 啟動執行緒
        self.fetch_worker.start()

    def on_stock_data_ready(self, data, is_auto):
        """當後台執行緒完成數據請求，更新 UI"""
        import time
        end_time = time.time()
        start_time = data.get('start_time', end_time)
        elapsed_time = end_time - start_time
        
        final_code = data['final_code']
        stock_name = data['stock_name']
        current_price = data['current_price']
        prev_close = data['prev_close']
        change = data['change']
        change_pct = data['change_pct']
        day_high = data['day_high']
        day_low = data['day_low']
        day_open = data.get('day_open', 0)  # 新增：開盤價
        hist = data['hist']
        period = data.get('period', '1mo')
        
        # 更新最後更新時間
        self.last_update_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 更新當前股票代號
        self.current_stock = final_code
        self.update_favorite_button()
        
        # 檢查價格警報
        self.check_price_alert(final_code, current_price)
        
        # 將名稱設定到 Label
        if hasattr(self.ui, 'stockname'):
            self.ui.stockname.setText(stock_name)

        # 更新文字介面
        self.ui.label_header.setText(f"Stock: {final_code}")
        self.ui.label_price.setText(f"$ {current_price:.2f}")
        
        # 現代化配色：漲紅跌綠
        color = "#FF4444" if change > 0 else "#00AA00"
        if change == 0: color = "#666666"
        self.ui.label_price.setStyleSheet(f"color: {color}; font-weight: bold;")

        stats_text = (
            f"Open:       {day_open:>8.2f}\n"
            f"High:       {day_high:>8.2f}\n"
            f"Low:        {day_low:>8.2f}\n"
            f"Prev Close: {prev_close:>8.2f}\n"
            f"Change:     {change:>8.2f} ({change_pct:+.2f}%)\n"
            f"\n最後更新: {self.last_update_time}"
        )
        self.ui.label_stats.setText(stats_text)

        # 更新 Matplotlib 圖表
        self.ax.clear()
        
        # 根據主題選擇顏色
        if self.dark_mode:
            line_color = '#42A5F5'
            fill_color = '#42A5F5'
            title_color = '#E0E0E0'
            label_color = '#B0B0B0'
            grid_color = '#404040'
            tick_color = '#B0B0B0'
        else:
            line_color = '#1E88E5'
            fill_color = '#1E88E5'
            title_color = '#333333'
            label_color = '#555555'
            grid_color = '#CCCCCC'
            tick_color = '#555555'
        
        self.ax.plot(hist.index, hist['Close'], color=line_color, linewidth=2.5, label='Close Price')
        self.ax.fill_between(hist.index, hist['Close'], alpha=0.15, color=fill_color)
        
        # 根據時間區間設定適當的標題和日期格式
        period_labels = {
            "1d": "1-Day Trend",
            "1w": "1-Week Trend",
            "1mo": "1-Month Trend",
            "3mo": "3-Month Trend",
            "1y": "1-Year Trend"
        }
        title = f"{final_code} {period_labels.get(period, '30-Day Trend')} (載入: {elapsed_time:.2f}s)"
        self.ax.set_title(title, fontsize=14, fontweight='bold', color=title_color)
        self.ax.grid(True, linestyle='--', alpha=0.3, color=grid_color)
        self.ax.set_ylabel('Price (TWD)', fontsize=11, color=label_color)
        self.ax.tick_params(colors=tick_color)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        # 繪製成交量圖表（現代化配色）
        self.ax_volume.clear()
        colors = ['#FF5252' if hist['Close'].iloc[i] >= hist['Close'].iloc[i-1] else '#4CAF50' 
                  for i in range(1, len(hist))]
        colors.insert(0, '#9E9E9E')  # 第一天用灰色
        self.ax_volume.bar(hist.index, hist['Volume'], color=colors, alpha=0.6, width=0.8)
        self.ax_volume.set_ylabel('Volume', fontsize=11, color=label_color)
        self.ax_volume.grid(True, linestyle='--', alpha=0.3, axis='y', color=grid_color)
        self.ax_volume.tick_params(colors=tick_color)
        self.ax_volume.spines['top'].set_visible(False)
        self.ax_volume.spines['right'].set_visible(False)
        
        # 根據時間區間設定不同的日期格式
        import matplotlib.dates as mdates
        if period == "1d":
            # 1天模式：顯示月-日 時:分
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            self.ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))  # 每 4 小時一個標籤
            self.ax_volume.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            self.ax_volume.xaxis.set_major_locator(mdates.HourLocator(interval=4))
        elif period == "1w":
            # 1週模式：顯示月-日
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            self.ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))  # 每天一個標籤
            self.ax_volume.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            self.ax_volume.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        elif period == "1mo":
            # 1月模式：顯示月-日
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            self.ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))  # 每 3 天一個標籤
            self.ax_volume.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            self.ax_volume.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        elif period == "3mo":
            # 3月模式：顯示月-日
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            self.ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))  # 每 7 天一個標籤
            self.ax_volume.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            self.ax_volume.xaxis.set_major_locator(mdates.DayLocator(interval=7))
        else:  # 1y
            # 1年模式：顯示月份
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            self.ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))  # 每月一個標籤
            self.ax_volume.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            self.ax_volume.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        
        self.figure.autofmt_xdate(rotation=45)
        self.figure.tight_layout()
        self.canvas.draw()

    def on_stock_error(self, error_msg, is_auto):
        """當後台執行緒發生錯誤"""
        if not is_auto:
            QtWidgets.QMessageBox.critical(self, "錯誤", error_msg)

    def change_period(self, period):
        """改變時間區間並重新抓取數據"""
        self.current_period = period
        self.search_stock()

    def load_favorites(self):
        """從檔案讀取我的最愛清單"""
        if os.path.exists(self.favorites_file):
            try:
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_favorites(self):
        """儲存我的最愛清單到檔案"""
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(self.favorites, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"儲存我的最愛失敗: {e}")

    def update_favorites_combo(self):
        """更新我的最愛下拉選單"""
        self.ui.combo_favorites.blockSignals(True)  # 暫時阻止信號
        self.ui.combo_favorites.clear()
        self.ui.combo_favorites.addItem("我的最愛")
        for stock in self.favorites:
            self.ui.combo_favorites.addItem(stock)
        self.ui.combo_favorites.blockSignals(False)

    def update_favorite_button(self):
        """更新星號按鈕狀態"""
        if self.current_stock and self.current_stock in self.favorites:
            self.ui.btn_favorite.setText("★")  # 實心星號
        else:
            self.ui.btn_favorite.setText("☆")  # 空心星號

    def toggle_favorite(self):
        """切換當前股票的我的最愛狀態"""
        if not self.current_stock:
            QtWidgets.QMessageBox.information(self, "提示", "請先搜尋股票")
            return
        
        if self.current_stock in self.favorites:
            self.favorites.remove(self.current_stock)
            QtWidgets.QMessageBox.information(self, "成功", f"已從我的最愛移除 {self.current_stock}")
        else:
            self.favorites.append(self.current_stock)
            QtWidgets.QMessageBox.information(self, "成功", f"已加入我的最愛 {self.current_stock}")
        
        self.save_favorites()
        self.update_favorites_combo()
        self.update_favorite_button()

    def on_favorite_selected(self, text):
        """當從我的最愛選單中選擇股票"""
        if text and text != "我的最愛":
            # 去除 .TW 或 .TWO 後綴以便搜尋
            code = text.replace(".TW", "").replace(".TWO", "")
            self.ui.input_code.setText(code)
            self.search_stock()
            # 重設選單到預設項
            self.ui.combo_favorites.setCurrentIndex(0)

    def load_alerts(self):
        """從檔案讀取價格警報"""
        if os.path.exists(self.alerts_file):
            try:
                with open(self.alerts_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_alerts(self):
        """儲存價格警報到檔案"""
        try:
            with open(self.alerts_file, 'w', encoding='utf-8') as f:
                json.dump(self.price_alerts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"儲存價格警報失敗: {e}")

    def check_price_alert(self, stock_code, current_price):
        """檢查是否觸發價格警報"""
        if stock_code not in self.price_alerts:
            return
        
        alert = self.price_alerts[stock_code]
        target_price = alert.get('target', 0)
        alert_type = alert.get('type', 'above')
        
        triggered = False
        if alert_type == 'above' and current_price >= target_price:
            triggered = True
            msg = f"{stock_code} 已達目標價 ${target_price:.2f}\\n當前價格: ${current_price:.2f}"
        elif alert_type == 'below' and current_price <= target_price:
            triggered = True
            msg = f"{stock_code} 已跌破目標價 ${target_price:.2f}\\n當前價格: ${current_price:.2f}"
        
        if triggered:
            QtWidgets.QMessageBox.information(self, "價格警報", msg)
            # 觸發後移除警報
            del self.price_alerts[stock_code]
            self.save_alerts()

    def set_price_alert(self):
        """設定價格警報對話框"""
        if not self.current_stock:
            QtWidgets.QMessageBox.information(self, "提示", "請先搜尋股票")
            return
        
        # 創建簡單的輸入對話框
        target_price, ok1 = QtWidgets.QInputDialog.getDouble(
            self, "設定價格警報", 
            f"請輸入 {self.current_stock} 的目標價格:", 
            0, 0, 999999, 2
        )
        
        if not ok1:
            return
        
        items = ["高於此價格時提醒", "低於此價格時提醒"]
        alert_type, ok2 = QtWidgets.QInputDialog.getItem(
            self, "警報類型", "選擇警報類型:", items, 0, False
        )
        
        if ok2:
            self.price_alerts[self.current_stock] = {
                'target': target_price,
                'type': 'above' if '高於' in alert_type else 'below'
            }
            self.save_alerts()
            QtWidgets.QMessageBox.information(
                self, "成功", 
                f"已設定 {self.current_stock} 的價格警報\\n目標價: ${target_price:.2f}"
            )

    def setup_search_suggestions(self):
        """設定搜尋建議（台股常用代號）"""
        # 台股常用股票代號
        popular_stocks = [
            "2330 台積電", "2317 鴻海", "2454 聯發科", "2382 廣達", "2308 台達電",
            "2303 聯電", "2881 富邦金", "2882 國泰金", "2886 兆豐金", "2891 中信金",
            "2412 中華電", "2002 中鋼", "1301 台塑", "1303 南亞", "6505 台塑化",
            "2207 和泰車", "2357 華碩", "2379 瑞昱", "3711 日月光投控", "2327 國巨",
            "2345 智邦", "3034 聯詠", "2301 光寶科", "3008 大立光", "2474 可成",
            "2409 友達", "2344 華邦電", "3037 欣興", "2395 研華", "4938 和碩",
            "2408 南亞科", "5880 合庫金", "2884 玉山金", "2892 第一金", "2883 開發金",
            "0050 元大台灣50", "0056 元大高股息", "00878 國泰永續高股息"
        ]
        
        completer = QCompleter(popular_stocks)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchContains)
        self.ui.input_code.setCompleter(completer)

    def setup_theme(self):
        """設定主題"""
        if self.dark_mode:
            self.apply_dark_theme()
        else:
            self.apply_light_theme()

    def apply_light_theme(self):
        """套用淺色主題"""
        self.setStyleSheet("")
        self.figure.patch.set_facecolor('#FAFAFA')
        self.ui.btn_theme.setText("🌙 深色模式")
        
    def apply_dark_theme(self):
        """套用深色主題"""
        dark_stylesheet = """
            QMainWindow, QWidget {
                background-color: #1E1E1E;
                color: #E0E0E0;
            }
            QLabel {
                color: #E0E0E0;
            }
            QLineEdit, QComboBox {
                background-color: #2D2D2D;
                color: #E0E0E0;
                border: 1px solid #404040;
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #2D2D2D;
                color: #E0E0E0;
                border: 1px solid #404040;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border: 1px solid #505050;
            }
            QPushButton:pressed {
                background-color: #252525;
            }
            QCheckBox {
                color: #E0E0E0;
            }
        """
        self.setStyleSheet(dark_stylesheet)
        self.figure.patch.set_facecolor('#1E1E1E')
        self.ui.btn_theme.setText("☀️ 淺色模式")

    def toggle_theme(self):
        """切換深色/淺色主題"""
        self.dark_mode = not self.dark_mode
        self.setup_theme()
        # 重新繪製圖表以套用新主題
        if self.current_stock:
            self.canvas.draw()
    
    def open_calculator(self):
        """打開計算機"""
        if self.calculator_window is None:
            self.calculator_window = SimpleCalculator()
        self.calculator_window.show()
        self.calculator_window.raise_()
        self.calculator_window.activateWindow()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = StockApp()
    window.show()
    sys.exit(app.exec())