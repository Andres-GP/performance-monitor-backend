// NinjaBridge.cs - Futures add-on with active contract resolution and order execution
#region Using declarations
using System;
using System.ComponentModel;
using System.Threading.Tasks;
using System.Net.WebSockets;
using System.Threading;
using System.Text;
using System.IO;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.Gui;
using Newtonsoft.Json;
using System.Linq;
using System.Windows;
using System.Timers;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    public class NinjaBridge : AddOnBase
    {
        private ClientWebSocket webSocket;
        private CancellationTokenSource cts;
        private bool isReconnecting = false;
        private string serverAddress = "wss://laxative-buckskin-gyration.ngrok-free.dev/ws/client1";
        private string authToken = "";
        private System.Timers.Timer heartbeatTimer;
        private const int HEARTBEAT_INTERVAL = 30000;

        protected override void OnWindowCreated(Window window)
        {
            if (window is ControlCenter)
            {
                Print("NinjaBridge: Control Center detected. Connecting...");
                ConnectWebSocket();
            }
        }

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "NinjaBridge";
                Description = "WebSocket bridge to receive orders from Signal Engine";
            }
        }

        private async void ConnectWebSocket()
        {
            if (isReconnecting) return;
            isReconnecting = true;

            webSocket = new ClientWebSocket();
            cts = new CancellationTokenSource();

            try
            {
                var serverUri = new Uri(serverAddress);
                Print($"NinjaBridge: Connecting to {serverUri}...");
                await webSocket.ConnectAsync(serverUri, cts.Token);
                Print("NinjaBridge: Connected to server.");

                if (!string.IsNullOrEmpty(authToken))
                {
                    var authMsg = new { type = "auth", token = authToken, platform = "NT8" };
                    string authJson = JsonConvert.SerializeObject(authMsg);
                    byte[] authBytes = Encoding.UTF8.GetBytes(authJson);
                    await webSocket.SendAsync(new ArraySegment<byte>(authBytes), WebSocketMessageType.Text, true, cts.Token);
                }

                StartHeartbeat();
                await ReceiveMessages();
            }
            catch (Exception ex)
            {
                Print($"NinjaBridge: Connection error - {ex.Message}");
                await Task.Delay(5000);
                _ = Reconnect();
            }
            finally { isReconnecting = false; }
        }

        private void StartHeartbeat()
        {
            if (heartbeatTimer != null)
            {
                heartbeatTimer.Stop();
                heartbeatTimer.Dispose();
            }
            heartbeatTimer = new System.Timers.Timer(HEARTBEAT_INTERVAL);
            heartbeatTimer.Elapsed += OnHeartbeat;
            heartbeatTimer.AutoReset = true;
            heartbeatTimer.Start();
        }

        private async void OnHeartbeat(object sender, ElapsedEventArgs e)
        {
            try
            {
                if (webSocket != null && webSocket.State == WebSocketState.Open)
                {
                    var pingMsg = new { type = "ping", timestamp = DateTime.UtcNow };
                    string json = JsonConvert.SerializeObject(pingMsg);
                    byte[] bytes = Encoding.UTF8.GetBytes(json);
                    await webSocket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, cts.Token);
                }
            }
            catch (Exception ex)
            {
                Print($"NinjaBridge: Heartbeat error - {ex.Message}");
            }
        }

        private async Task ReceiveMessages()
        {
            byte[] buffer = new byte[4096];
            while (webSocket.State == WebSocketState.Open)
            {
                try
                {
                    using (var ms = new MemoryStream())
                    {
                        WebSocketReceiveResult result;
                        do
                        {
                            result = await webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), cts.Token);
                            ms.Write(buffer, 0, result.Count);
                        } while (!result.EndOfMessage);
                        ms.Seek(0, SeekOrigin.Begin);
                        using (var reader = new StreamReader(ms, Encoding.UTF8))
                        {
                            string message = reader.ReadToEnd();
                            if (message.TrimStart().StartsWith("{"))
                            {
                                if (!message.Contains("\"type\":\"pong\""))
                                    Print($"NinjaBridge: Ignored JSON: {message}");
                                continue;
                            }
                            Print($"NinjaBridge: Order received -> {message}");
                            ProcessOrder(message);
                        }
                    }
                }
                catch (WebSocketException ex)
                {
                    Print($"NinjaBridge: Error WebSocket - {ex.Message}");
                    break;
                }
                catch (OperationCanceledException)
                {
                    break;
                }
            }
            await Reconnect();
        }

        private void ProcessOrder(string message)
        {
            try
            {
                string[] parts = message.Split(' ');
                if (parts.Length < 3)
                {
                    Print("NinjaBridge: Invalid format. Use 'buy MNQ 1' or 'buy MNQ 09-24 1'");
                    return;
                }

                string action = parts[0].ToLower();
                int lastIndex = parts.Length - 1;
                string instrumentName = string.Join(" ", parts, 1, lastIndex - 1);
                double quantity = double.Parse(parts[lastIndex], System.Globalization.CultureInfo.InvariantCulture);

                ExecuteOrder(action, instrumentName, quantity);
            }
            catch (Exception ex)
            {
                Print($"NinjaBridge: Failed to parse order - {ex.Message}");
            }
        }

        private void ExecuteOrder(string action, string instrumentName, double quantity)
        {
            Print($"=== Executing order: {action} {instrumentName} {quantity}");

            if (action != "buy" && action != "sell")
            {
                Print($"NinjaBridge: Invalid action '{action}'");
                return;
            }

            Instrument instrument = FindFrontMonthContract(instrumentName);
            if (instrument == null)
            {
                instrument = Instrument.GetInstrument(instrumentName);
                if (instrument == null)
                {
                    Print($"NinjaBridge: Instrument '{instrumentName}' not found");
                    return;
                }
            }

            Print($"Instrument: {instrument.FullName}");

            Account account = Account.All.FirstOrDefault(a => a.Name == "Sim101");
            if (account == null)
            {
                account = Account.All.FirstOrDefault();
                if (account == null)
                {
                    Print("NinjaBridge: No account available");
                    return;
                }
                Print($"Using account: {account.Name}");
            }
            else
            {
                Print($"Using Sim101 account: {account.Name}");
            }

            OrderAction orderAction = (action == "buy") ? OrderAction.Buy : OrderAction.Sell;
            int quantityInt = (int)quantity;
            Print($"Quantity (integer): {quantityInt}");

            System.Windows.Threading.Dispatcher.CurrentDispatcher.BeginInvoke(new Action(() =>
            {
                try
                {
                    var order = account.CreateOrder(instrument, orderAction, OrderType.Market, TimeInForce.Gtc, quantityInt, 0, 0, "", "SignalEngineOrder", null);
                    account.Submit(new[] { order });
                    Print($"NinjaBridge: Order submitted to market: {action} {quantity} {instrumentName}");
                }
                catch (Exception ex)
                {
                    Print($"NinjaBridge: Failed to create/submit order: {ex.Message}");
                }
            }));
        }

        private Instrument FindFrontMonthContract(string symbol)
        {
            try
            {
                if (symbol.Contains(" "))
                {
                    Instrument direct = Instrument.GetInstrument(symbol);
                    if (direct != null)
                        return direct;
                }

                string[] monthAbbr = { "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC" };
                for (int i = 1; i <= 6; i++)
                {
                    DateTime future = DateTime.Now.AddMonths(i);
                    string mm = future.ToString("MM");
                    string yy = future.ToString("yy");
                    string format1 = $"{symbol} {mm}-{yy}";
                    string format2 = $"{symbol} {monthAbbr[future.Month - 1]}{yy}";

                    Instrument contract = Instrument.GetInstrument(format1);
                    if (contract != null)
                    {
                        Print($"NinjaBridge: Resolved '{symbol}' -> '{format1}'");
                        return contract;
                    }
                    contract = Instrument.GetInstrument(format2);
                    if (contract != null)
                    {
                        Print($"NinjaBridge: Resolved '{symbol}' -> '{format2}'");
                        return contract;
                    }
                }
            }
            catch (Exception ex)
            {
                Print($"NinjaBridge: Failed to resolve contract for '{symbol}': {ex.Message}");
            }
            Print($"NinjaBridge: No active contract found for '{symbol}'");
            return null;
        }

        private async Task Reconnect()
        {
            Print("NinjaBridge: Reconnecting in 5 seconds...");
            await Task.Delay(5000);
            ConnectWebSocket();
        }

        private void DisconnectWebSocket()
        {
            heartbeatTimer?.Stop();
            heartbeatTimer?.Dispose();
            cts?.Cancel();
            webSocket?.Dispose();
        }
    }
}