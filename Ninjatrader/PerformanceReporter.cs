using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.Strategies;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;

namespace NinjaTrader.NinjaScript.Strategies
{
    public abstract class PerformanceReporter : Strategy
    {
        [NinjaScriptProperty]
        [Display(Name = "Backend URL", Description = "Base URL of the backend (e.g., https://xxx.ngrok-free.dev)", Order = 0)]
        public string BackendUrl { get; set; } = "https://laxative-buckskin-gyration.ngrok-free.dev";

        [NinjaScriptProperty]
        [Display(Name = "Auth Token", Description = "Authentication token for backend", Order = 1)]
        public string AuthToken { get; set; } = "miclave123";

        [NinjaScriptProperty]
        [Display(Name = "Rollover Alert (days)", Description = "Days before expiry to send alert (0 = disabled)", Order = 2)]
        public int RolloverAlertDays { get; set; } = 5;

        private static readonly HttpClient _httpClient = new HttpClient();
        private bool _startReported = false;
        private Dictionary<string, bool> _rolloverAlertSent = new Dictionary<string, bool>();

        // --- Manual trade tracking (bypass AllTrades) ---
        private double _lastEntryPrice = 0;
        private DateTime _lastEntryTime = DateTime.MinValue;
        private int _lastEntryQuantity = 0;
        private MarketPosition _lastEntryPosition = MarketPosition.Flat;
        private bool _hasEntryData = false;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults) return;

            if (State == State.Realtime && !_startReported)
            {
                _startReported = true;
                ReportStrategyStarted();
            }
            else if (State == State.Terminated)
            {
                ReportStrategyStopped();
            }
        }

        protected override void OnBarUpdate()
        {
            if (State == State.Realtime && Bars != null && Instrument != null)
            {
                CheckRollover();
            }
        }

        private void CheckRollover()
        {
            if (RolloverAlertDays <= 0) return;

            try
            {
                DateTime expiry = Instrument.Expiry;
                if (expiry == DateTime.MinValue) return;

                int daysUntilExpiry = (int)(expiry - DateTime.Now).TotalDays;

                if (daysUntilExpiry >= 0 && daysUntilExpiry <= RolloverAlertDays)
                {
                    string key = $"Rollover_{Instrument.FullName}";
                    if (!_rolloverAlertSent.ContainsKey(key) || !_rolloverAlertSent[key])
                    {
                        _rolloverAlertSent[key] = true;
                        string details = $"Instrument {Instrument.FullName} expires in {daysUntilExpiry} days. Please rollover to the next contract.";
                        Print($"🚨 {details}");
                        SendHealthAlert("Contract Rollover Approaching", details, "medium");
                    }
                }
                else if (daysUntilExpiry > RolloverAlertDays)
                {
                    string key = $"Rollover_{Instrument.FullName}";
                    if (_rolloverAlertSent.ContainsKey(key))
                        _rolloverAlertSent[key] = false;
                }
            }
            catch (Exception ex)
            {
                Print($"❌ Rollover error: {ex.Message}");
            }
        }

        private async void SendHealthAlert(string problemType, string details, string severity = "high")
        {
            var data = new
            {
                strategy_id = this.Id.ToString(),
                timestamp = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                problem_type = problemType,
                details = details,
                severity = severity
            };
            await SendToApi("/alerts", data);
        }

        private async void ReportStrategyStarted()
        {
            string instrumentType = "Unknown";
            string timeframe = "Unknown";
            string dataType = "Real";
            string platform = "NT8";
            int sizing = 1;

            try
            {
                if (Instrument != null && Instrument.MasterInstrument != null)
                    instrumentType = Instrument.MasterInstrument.InstrumentType.ToString();
            }
            catch { }

            try
            {
                if (BarsPeriod != null)
                {
                    string periodType = BarsPeriod.BarsPeriodType.ToString();
                    int periodValue = BarsPeriod.Value;
                    timeframe = $"{periodValue} {periodType}";
                }
            }
            catch { }

            try
            {
                if (Account != null && Account.Name != null && Account.Name.Contains("Sim"))
                    dataType = "Simulation";
            }
            catch { }

            try
            {
                var quantityProp = this.GetType().GetProperty("Quantity");
                if (quantityProp != null)
                {
                    object value = quantityProp.GetValue(this);
                    if (value != null)
                        sizing = (int)value;
                }
            }
            catch { }

            var data = new
            {
                strategy_id = this.Id.ToString(),
                name = this.Name,
                instrument = this.Instrument.FullName,
                instrument_type = instrumentType,
                timeframe = timeframe,
                data_type = dataType,
                platform = platform,
                sizing = sizing,
                start_date = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                state = "Running"
            };
            await SendToApi("/strategies/start", data);
        }

        private async void ReportStrategyStopped()
        {
            var data = new
            {
                strategy_id = this.Id.ToString(),
                state = "Stopped",
                stopped_at = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
            };
            await SendToApi("/strategies/stop", data);
        }

        // 🔥 OnPositionUpdate: store entry data and report trade on close ONLY if exit price > 0
        protected override void OnPositionUpdate(Position position, double averagePrice, int quantity, MarketPosition marketPosition)
        {
            Print($"📌 OnPositionUpdate: quantity={quantity}, marketPosition={marketPosition}");

            // Position opened: store entry data
            if (quantity > 0 && !_hasEntryData)
            {
                _lastEntryPrice = averagePrice;
                _lastEntryTime = Time[0];
                _lastEntryQuantity = quantity;
                _lastEntryPosition = marketPosition;
                _hasEntryData = true;
                Print($"📌 Stored entry: price={_lastEntryPrice}, time={_lastEntryTime}, qty={_lastEntryQuantity}, pos={_lastEntryPosition}");
            }

            // Position closed: report trade ONLY if exit price is valid (> 0)
            if (quantity == 0 && _hasEntryData && averagePrice > 0)
            {
                double exitPrice = averagePrice;
                DateTime exitTime = Time[0];
                string direction = (_lastEntryPosition == MarketPosition.Long) ? "Long" : "Short";
                double pnl = (direction == "Long") ? (exitPrice - _lastEntryPrice) * _lastEntryQuantity
                                                   : (_lastEntryPrice - exitPrice) * _lastEntryQuantity;

                Print($"📌 Trade closed: entry={_lastEntryPrice}, exit={exitPrice}, qty={_lastEntryQuantity}, direction={direction}, PnL={pnl}");

                ReportTradeClosedManual(
                    _lastEntryPrice,
                    _lastEntryTime,
                    exitPrice,
                    exitTime,
                    _lastEntryQuantity,
                    pnl,
                    direction,
                    0.0
                );

                // Clear entry data to avoid duplicate reporting
                _hasEntryData = false;
                _lastEntryPrice = 0;
                _lastEntryTime = DateTime.MinValue;
                _lastEntryQuantity = 0;
                _lastEntryPosition = MarketPosition.Flat;
            }

            base.OnPositionUpdate(position, averagePrice, quantity, marketPosition);
        }

        // Fallback: OnExecutionUpdate can also trigger reporting (if OnPositionUpdate missed it or exit price was 0)
        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            // If we have entry data and we detect a filled exit order, report again if not already reported.
            if (execution.Order != null && execution.Order.OrderState == OrderState.Filled && _hasEntryData)
            {
                string orderName = execution.Order.Name ?? "";
                bool isExitOrder = orderName.Contains("Exit") || orderName.Contains("Stop") || orderName.Contains("Target") ||
                                   orderName.Contains("Stop loss") || orderName.Contains("Profit target");

                if (isExitOrder && price > 0)  // Ensure exit price is valid
                {
                    // This could be a duplicate, but we check _hasEntryData to prevent double report.
                    // If OnPositionUpdate already reported, we cleared _hasEntryData, so this won't run.
                    double exitPrice = price;
                    DateTime exitTime = time;
                    string direction = (_lastEntryPosition == MarketPosition.Long) ? "Long" : "Short";
                    double pnl = (direction == "Long") ? (exitPrice - _lastEntryPrice) * _lastEntryQuantity
                                                       : (_lastEntryPrice - exitPrice) * _lastEntryQuantity;

                    Print($"📌 Fallback trade closed via Execution: entry={_lastEntryPrice}, exit={exitPrice}, qty={_lastEntryQuantity}, direction={direction}, PnL={pnl}");

                    ReportTradeClosedManual(
                        _lastEntryPrice,
                        _lastEntryTime,
                        exitPrice,
                        exitTime,
                        _lastEntryQuantity,
                        pnl,
                        direction,
                        0.0
                    );

                    // Clear entry data
                    _hasEntryData = false;
                    _lastEntryPrice = 0;
                    _lastEntryTime = DateTime.MinValue;
                    _lastEntryQuantity = 0;
                    _lastEntryPosition = MarketPosition.Flat;
                }
            }

            base.OnExecutionUpdate(execution, executionId, price, quantity, marketPosition, orderId, time);
        }

        // Manual trade reporting method (does not rely on AllTrades)
        private async void ReportTradeClosedManual(double entryPrice, DateTime entryTime, double exitPrice, DateTime exitTime, int quantity, double pnl, string direction, double commission)
        {
            var data = new
            {
                strategy_id = this.Id.ToString(),
                instrument = this.Instrument.FullName,
                entry_time = entryTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                exit_time = exitTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                quantity = quantity,
                entry_price = entryPrice,
                exit_price = exitPrice,
                pnl = pnl,
                direction = direction,
                cost = commission
            };
            await SendToApi("/trades", data);
        }

        // Original method kept for compatibility (not used)
        private async void ReportTradeClosed(Trade trade)
        {
            // Not used, but kept to avoid breaking any references.
        }

        private async Task SendToApi(string endpoint, object data)
        {
            try
            {
                string json = JsonConvert.SerializeObject(data);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                _httpClient.DefaultRequestHeaders.Clear();
                _httpClient.DefaultRequestHeaders.Add("Authorization", $"Bearer {AuthToken}");

                string fullUrl = BackendUrl.TrimEnd('/') + endpoint;
                var response = await _httpClient.PostAsync(fullUrl, content);
                Print($"📤 Report sent: {endpoint} - Status: {response.StatusCode}");
            }
            catch (Exception ex)
            {
                Print($"❌ Error reporting to {endpoint}: {ex.Message}");
            }
        }
    }
}