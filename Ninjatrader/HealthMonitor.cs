// HealthMonitor.cs
using System;
using System.Collections.Generic;
using System.Linq;
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
    public abstract class HealthMonitor : PerformanceReporter
    {
        // ---------------------------- Thresholds ----------------------------
        private const double MAX_SLIPPAGE_TICKS = 3;
        private const double DRIFT_TOLERANCE = 0.01;
        private const int FREEZE_TIMEOUT_SECONDS = 5;

        // ---------------------------- Internal tracking ----------------------------
        private Dictionary<string, DateTime> _orderSentTime = new Dictionary<string, DateTime>();
        private int _barsSinceLastTrade = 0;
        private bool _isConnected = true;
        private HashSet<string> _partialFilledOrders = new HashSet<string>();
        private bool _isFirstRealtimeBar = true;
        private Dictionary<string, double> _limitOrderPrices = new Dictionary<string, double>();
        private bool _inactivityAlertSent = false;
        private DateTime _startTime = DateTime.MinValue;   // Para evitar alertas de conexión al inicio

        // --- UI-editable properties ---
        [NinjaScriptProperty]
        [Display(Name = "Max bars without trade", Description = "Number of bars without activity before sending inactivity alert (0 = disable)", Order = 10, GroupName = "Health Monitoring")]
        public int MaxBarsWithoutTrade { get; set; } = 50;

        [NinjaScriptProperty]
        [Display(Name = "Enable inactivity alert", Description = "If true, alerts when no trades are generated", Order = 11, GroupName = "Health Monitoring")]
        public bool EnableInactivityAlert { get; set; } = true;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults) return;

            if (State == State.Realtime)
            {
                _startTime = DateTime.Now;   // Guardar tiempo de inicio
                _barsSinceLastTrade = 0;
                _isFirstRealtimeBar = true;
                _inactivityAlertSent = false;

                Account acc = Account.All.FirstOrDefault(a => a.Name == "Sim101") ?? Account.All.FirstOrDefault();
                if (acc != null)
                {
                    foreach (Order order in acc.Orders)
                    {
                        if (order.OrderState != OrderState.Filled && order.OrderState != OrderState.Cancelled)
                            CancelOrder(order);
                    }
                }
            }
            else if (State == State.Terminated)
            {
                Account acc = Account.All.FirstOrDefault(a => a.Name == "Sim101") ?? Account.All.FirstOrDefault();
                if (acc != null)
                {
                    foreach (Order order in acc.Orders)
                    {
                        if (order.OrderState != OrderState.Filled && order.OrderState != OrderState.Cancelled)
                            CancelOrder(order);
                    }
                }
            }
            base.OnStateChange();
        }

        protected override void OnBarUpdate()
        {
            // 12. Inactive strategy (only if enabled, threshold > 0, and there is at least one trade in history)
            if (EnableInactivityAlert && MaxBarsWithoutTrade > 0 && 
                Position.MarketPosition == MarketPosition.Flat &&
                SystemPerformance.AllTrades.Count > 0)   // 🔥 No enviar si nunca ha habido un trade
            {
                _barsSinceLastTrade++;
                if (_barsSinceLastTrade >= MaxBarsWithoutTrade && !_inactivityAlertSent)
                {
                    ReportHealthProblem("Inactive strategy", 
                        $"No trade generated in the last {MaxBarsWithoutTrade} bars.");
                    _inactivityAlertSent = true;
                }
            }
            else if (Position.MarketPosition != MarketPosition.Flat)
            {
                _barsSinceLastTrade = 0;
                _inactivityAlertSent = false;
            }

            // 6. Position drift
            Account currentAccount = Account.All.FirstOrDefault(a => a.Name == "Sim101") ?? Account.All.FirstOrDefault();
            if (currentAccount != null)
            {
                long instrumentId = Instrument.MasterInstrument.Id;
                Position accountPos = currentAccount.GetPosition(instrumentId);
                if (accountPos != null && Math.Abs(accountPos.Quantity - Position.Quantity) > DRIFT_TOLERANCE)
                {
                    ReportHealthProblem("Position drift", 
                        $"Strategy position: {Position.Quantity}, Account position: {accountPos.Quantity}. Difference of {accountPos.Quantity - Position.Quantity} units.");
                }
            }

            // 5. Ghost orders
            if (_isFirstRealtimeBar)
            {
                _isFirstRealtimeBar = false;
                Account tmpAccount = Account.All.FirstOrDefault(a => a.Name == "Sim101") ?? Account.All.FirstOrDefault();
                if (tmpAccount != null)
                {
                    foreach (Order order in tmpAccount.Orders)
                    {
                        if (order.OrderState != OrderState.Filled && order.OrderState != OrderState.Cancelled)
                        {
                            ReportHealthProblem("Ghost order detected", 
                                $"Order {order.Name} is still {order.OrderState} from historical state. Cancelling.");
                            CancelOrder(order);
                        }
                    }
                }
            }

            base.OnBarUpdate();
        }

        protected override void OnOrderUpdate(Order order, double limitPrice, double stopPrice, int quantity, int filled, double averageFillPrice, OrderState orderState, DateTime time, ErrorCode error, string comment)
        {
            // 1. Order rejected
            if (orderState == OrderState.Rejected)
            {
                ReportHealthProblem("Order rejected", 
                    $"Order {order.Name} rejected. Error: {error}. Comment: {comment}");
                CancelOrder(order);
            }

            // 2. Partial fill - track but don't alert immediately
            if (orderState == OrderState.PartFilled)
            {
                if (!_partialFilledOrders.Contains(order.Name))
                    _partialFilledOrders.Add(order.Name);
            }

            // If order fills completely, remove from partial tracking
            if (orderState == OrderState.Filled && filled == quantity)
            {
                if (_partialFilledOrders.Contains(order.Name))
                    _partialFilledOrders.Remove(order.Name);
                _orderSentTime.Remove(order.Name);
            }

            // If order is cancelled or rejected and had partial fill, alert
            if ((orderState == OrderState.Cancelled || orderState == OrderState.Rejected) && _partialFilledOrders.Contains(order.Name))
            {
                ReportHealthProblem("Partial fill (incomplete)", 
                    $"Order {order.Name}: requested {quantity}, only filled {filled}. Remaining part not filled.");
                _partialFilledOrders.Remove(order.Name);
            }

            // 4. Frozen order - ignore stop/target/profit orders
            bool isProtectionOrder = order.Name.Contains("Stop") || order.Name.Contains("Target") || order.Name.Contains("Profit");
            if (!isProtectionOrder && _orderSentTime.ContainsKey(order.Name))
            {
                TimeSpan elapsed = DateTime.UtcNow - _orderSentTime[order.Name];
                if (elapsed.TotalSeconds > FREEZE_TIMEOUT_SECONDS && 
                    (orderState == OrderState.Working || orderState == OrderState.Submitted))
                {
                    ReportHealthProblem("Frozen order", 
                        $"Order {order.Name} has been {orderState} for {elapsed.TotalSeconds} seconds. Cancelling.");
                    CancelOrder(order);
                    _orderSentTime.Remove(order.Name);
                }
            }

            // Track order sent time (only for entry orders)
            if (!isProtectionOrder && (orderState == OrderState.Accepted || orderState == OrderState.Working) && !_orderSentTime.ContainsKey(order.Name))
                _orderSentTime[order.Name] = DateTime.UtcNow;

            base.OnOrderUpdate(order, limitPrice, stopPrice, quantity, filled, averageFillPrice, orderState, time, error, comment);
        }

        protected override void OnExecutionUpdate(Execution execution, string executionId, double price, int quantity, MarketPosition marketPosition, string orderId, DateTime time)
        {
            Order order = GetOrderById(orderId);

            // 9. Excessive slippage
            if (order != null && order.OrderState == OrderState.Filled)
            {
                double expectedPrice = GetExpectedPrice(order);
                double slippageTicks = Math.Abs(price - expectedPrice) / TickSize;
                if (slippageTicks > MAX_SLIPPAGE_TICKS)
                {
                    ReportHealthProblem("Excessive slippage", 
                        $"Order {order.Name}: expected {expectedPrice}, executed {price}, slippage {slippageTicks} ticks.");
                }
            }

            // 10. Limit order not executed despite price touched
            if (order != null && order.OrderType == OrderType.Limit)
            {
                if (_limitOrderPrices.ContainsKey(order.Name))
                {
                    double limitPrice = _limitOrderPrices[order.Name];
                    if ((marketPosition == MarketPosition.Long && Close[0] > limitPrice + (2 * TickSize)) ||
                        (marketPosition == MarketPosition.Short && Close[0] < limitPrice - (2 * TickSize)))
                    {
                        if (order.OrderState == OrderState.Working || order.OrderState == OrderState.Accepted)
                        {
                            ReportHealthProblem("Limit order not filled", 
                                $"Limit order {order.Name} at {limitPrice} not filled even though price touched. Cancelling.");
                            CancelOrder(order);
                        }
                    }
                }
                else
                {
                    _limitOrderPrices[order.Name] = order.LimitPrice;
                }
            }

            base.OnExecutionUpdate(execution, executionId, price, quantity, marketPosition, orderId, time);
        }

        protected override void OnConnectionStatusUpdate(ConnectionStatusEventArgs e)
        {
            // 🔥 No enviar alerta de conexión en los primeros 10 segundos
            if ((DateTime.Now - _startTime).TotalSeconds < 10)
                return;

            if (e.Status == ConnectionStatus.Connecting || e.Status == ConnectionStatus.Disconnected)
            {
                _isConnected = false;
                ReportHealthProblem("Connection lost", 
                    $"Connection status: {e.Status}. Strategy will not send orders.");
            }
            else if (e.Status == ConnectionStatus.Connected)
            {
                _isConnected = true;
                Print("Reconnected. Monitoring resumed.");
            }
            base.OnConnectionStatusUpdate(e);
        }

        private Order GetOrderById(string orderId)
        {
            Account account = Account.All.FirstOrDefault(a => a.Name == "Sim101") ?? Account.All.FirstOrDefault();
            if (account == null) return null;
            foreach (Order o in account.Orders)
            {
                if (o.Id.ToString() == orderId)
                    return o;
            }
            return null;
        }

        protected virtual double GetExpectedPrice(Order order)
        {
            return order.LimitPrice > 0 ? order.LimitPrice : Close[0];
        }

        private async void ReportHealthProblem(string problemType, string details)
        {
            var data = new
            {
                strategy_id = this.Id.ToString(),
                timestamp = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ"),
                problem_type = problemType,
                details = details,
                severity = "high"
            };
            await SendHealthAlert(data);
        }

        private async Task SendHealthAlert(object data)
        {
            try
            {
                string json = JsonConvert.SerializeObject(data);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                using (var client = new HttpClient())
                {
                    client.DefaultRequestHeaders.Clear();
                    client.DefaultRequestHeaders.Add("Authorization", $"Bearer {AuthToken}");
                    string fullUrl = BackendUrl.TrimEnd('/') + "/alerts";
                    var response = await client.PostAsync(fullUrl, content);
                    Print($"📤 Health alert sent: {response.StatusCode}");
                }
            }
            catch (Exception ex)
            {
                Print($"❌ Error sending health alert: {ex.Message}");
            }
        }
    }
}