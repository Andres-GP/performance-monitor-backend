// PerformanceReporter.cs
using System;
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

        private static readonly HttpClient _httpClient = new HttpClient();
        private bool _startReported = false;

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

        private async void ReportStrategyStarted()
        {
            // --- Strategy information ---
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

            // --- Report strategy start ---
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

        protected override void OnPositionUpdate(Position position, double averagePrice, int quantity, MarketPosition marketPosition)
        {
            if (quantity == 0 && SystemPerformance.AllTrades.Count > 0)
            {
                Trade lastTrade = SystemPerformance.AllTrades[SystemPerformance.AllTrades.Count - 1];
                ReportTradeClosed(lastTrade);
            }
        }

        private async void ReportTradeClosed(Trade trade)
        {
            var data = new
            {
                strategy_id = this.Id.ToString(),
                instrument = this.Instrument.FullName,
                entry_time = trade.Entry.Time.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                exit_time = trade.Exit?.Time.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                quantity = trade.Quantity,
                entry_price = trade.Entry.Price,
                exit_price = trade.Exit?.Price ?? 0,
                pnl = trade.ProfitCurrency,
                direction = trade.Entry.Position.ToString()
            };
            await SendToApi("/trades", data);
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