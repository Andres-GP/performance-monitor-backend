//+------------------------------------------------------------------+
//|                                              StrategyTemplateMT5.mq5 |
//|                   Full template with performance monitoring       |
//|                   FIXES: direction, quantity, ISO dates, heartbeat|
//|                   IMPROVED: fixed strategy_id input              |
//+------------------------------------------------------------------+
#property copyright "AlphaCapital"
#property link      "https://www.alphacapital.com"
#property version   "1.10"

//+------------------------------------------------------------------+
//| INCLUDES                                                         |
//+------------------------------------------------------------------+
#include <Trade/Trade.mqh>              // For CTrade
#include <PerformanceReporter.mqh>     // For backend reporting

//+------------------------------------------------------------------+
//| INPUT PARAMETERS (Editable from UI)                              |
//+------------------------------------------------------------------+
//--- Backend configuration
input string   Inp_BackendUrl   = "https://laxative-buckskin-gyration.ngrok-free.dev";   // Backend URL
input string   Inp_AuthToken    = ""; // Auth Token
input string   Inp_StrategyId   = ""; // Custom strategy ID (if empty, auto-generated)

//--- Monitoring settings
input bool     Inp_EnableInactivity = true;      // Enable inactivity alert
input int      Inp_MaxBarsWithoutTrade = 50;     // Bars without trade before alert
input int      Inp_RolloverAlertDays = 60;       // Days before expiry to send alert (0 = disabled)

//--- Trading parameters
input double   Inp_LotSize      = 0.1;           // Lot size
input int      Inp_MagicNumber  = 1000;          // Magic number
input bool     Inp_UseTimer     = false;         // Use timer for trading (true) or ticks (false)

//--- Strategy parameters (example: MA Crossover)
input int      Inp_FastMA       = 10;            // Fast MA period
input int      Inp_SlowMA       = 25;            // Slow MA period
input int      Inp_StopLoss     = 50;            // Stop Loss in points
input int      Inp_TakeProfit   = 100;           // Take Profit in points

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                 |
//+------------------------------------------------------------------+
PerformanceReporter *g_reporter = NULL;   // Reporter for backend
CTrade            g_trade;               // CTrade object for trading

//--- Indicators (example: moving averages)
int               g_handleFastMA = INVALID_HANDLE;
int               g_handleSlowMA = INVALID_HANDLE;

//--- Tracking variables
ulong             g_lastTicket = 0;
double            g_lastEntryPrice = 0;
datetime          g_lastEntryTime = 0;
double            g_lastVolume = 0;
int               g_barsCount = 0;
bool              g_hasPosition = false;
bool              g_waitingForClose = false;   // Prevent multiple close attempts

//+------------------------------------------------------------------+
//| INITIALIZATION                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   //--- Configure CTrade
   g_trade.SetExpertMagicNumber(Inp_MagicNumber);
   g_trade.SetDeviationInPoints(10);
   
   //--- 1. INITIALIZE REPORTER
   string accountType = (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO) ? "Simulation" : "Real";
   
   // Build strategy ID: use custom if provided, else auto-generate
   string strategyId;
   if(StringLen(Inp_StrategyId) > 0)
      strategyId = Inp_StrategyId;
   else
      strategyId = IntegerToString(TimeCurrent()) + "_StrategyTemplate";   // Auto-generate
   
   g_reporter = new PerformanceReporter(
      Inp_BackendUrl,
      Inp_AuthToken,
      strategyId,                     // ✅ FIXED ID (or auto-generated)
      Symbol(),
      EnumToString(Period()),
      (int)(Inp_LotSize * 100),
      accountType
   );
   
   if(CheckPointer(g_reporter) == POINTER_INVALID)
   {
      Print("[ERROR] Failed to create reporter.");
      return INIT_FAILED;
   }
   
   //--- Configure monitoring
   g_reporter.SetMaxBarsWithoutTrade(Inp_MaxBarsWithoutTrade);
   g_reporter.EnableInactivityAlert(Inp_EnableInactivity);
   g_reporter.SetRolloverAlertDays(Inp_RolloverAlertDays);
   
   //--- Report strategy start and capital
   g_reporter.ReportStrategyStarted();
   double capital = AccountInfoDouble(ACCOUNT_BALANCE);
   g_reporter.ReportCapital(capital, AccountInfoString(ACCOUNT_CURRENCY));
   Print("[INFO] EA started successfully. Strategy ID: ", strategyId);
   
   //--- 2. INITIALIZE INDICATORS (example: moving averages)
   g_handleFastMA = iMA(_Symbol, _Period, Inp_FastMA, 0, MODE_SMA, PRICE_CLOSE);
   g_handleSlowMA = iMA(_Symbol, _Period, Inp_SlowMA, 0, MODE_SMA, PRICE_CLOSE);
   
   if(g_handleFastMA == INVALID_HANDLE || g_handleSlowMA == INVALID_HANDLE)
   {
      Print("[ERROR] Error creating indicators.");
      return INIT_FAILED;
   }
   Print("[INFO] Indicators initialized.");
   
   //--- 3. START TIMER (if used)
   if(Inp_UseTimer)
      EventSetTimer(30);
   
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| DEINITIALIZATION                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_handleFastMA != INVALID_HANDLE) IndicatorRelease(g_handleFastMA);
   if(g_handleSlowMA != INVALID_HANDLE) IndicatorRelease(g_handleSlowMA);
   
   if(CheckPointer(g_reporter) != POINTER_INVALID)
   {
      delete g_reporter;
      g_reporter = NULL;
   }
   Print("[INFO] EA terminated. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| TICK EVENT                                                       |
//+------------------------------------------------------------------+
void OnTick()
{
   if(CheckPointer(g_reporter) == POINTER_INVALID) return;
   
   // Check rollover on every tick
   g_reporter.CheckRollover();
   
   // Inactivity monitoring
   int currentBars = Bars(_Symbol, _Period);
   if(currentBars != g_barsCount && currentBars > 0)
   {
      g_barsCount = currentBars;
      g_reporter.OnBarUpdate(g_barsCount);
   }
   
   // Detect position close (to report to backend)
   static int prevPosTotal = 0;
   int currentPosTotal = PositionsTotal();
   
   // If there was a position and now there is none, it was closed
   if(prevPosTotal > 0 && currentPosTotal == 0)
   {
      if(g_lastTicket > 0)
      {
         // Get data from history
         HistorySelect(0, TimeCurrent());
         int total = HistoryDealsTotal();
         if(total > 0)
         {
            ulong ticket = HistoryDealGetTicket(total - 1);
            if(ticket > 0)
            {
               string symbol = HistoryDealGetString(ticket, DEAL_SYMBOL);
               double entryPrice = HistoryDealGetDouble(ticket, DEAL_PRICE);
               double volume = HistoryDealGetDouble(ticket, DEAL_VOLUME);
               double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
               datetime entryTime = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
               double commission = HistoryDealGetDouble(ticket, DEAL_COMMISSION);
               
               // Get position type from history
               ENUM_DEAL_TYPE dealType = (ENUM_DEAL_TYPE)HistoryDealGetInteger(ticket, DEAL_TYPE);
               ENUM_POSITION_TYPE posType;
               if(dealType == DEAL_TYPE_BUY)
                  posType = POSITION_TYPE_BUY;
               else if(dealType == DEAL_TYPE_SELL)
                  posType = POSITION_TYPE_SELL;
               else
                  posType = POSITION_TYPE_BUY; // fallback
               
               // Report trade with 10 parameters (including posType)
               g_reporter.ReportTradeClosed(
                  ticket,
                  symbol,
                  g_lastEntryPrice,   // saved entry price
                  entryPrice,         // exit price
                  volume,             // actual volume (double)
                  profit,
                  g_lastEntryTime,    // saved entry time
                  TimeCurrent(),
                  commission,
                  posType
               );
               Print("[INFO] Trade closed reported: ", ticket, " profit: ", profit);
            }
         }
         g_lastTicket = 0;
         g_hasPosition = false;
         g_waitingForClose = false;
      }
   }
   prevPosTotal = currentPosTotal;
   
   // Update position status
   if(PositionsTotal() > 0)
   {
      for(int i = 0; i < PositionsTotal(); i++)
      {
         ulong ticket = PositionGetTicket(i);
         if(PositionSelectByTicket(ticket))
         {
            if(PositionGetInteger(POSITION_MAGIC) == Inp_MagicNumber)
            {
               g_hasPosition = true;
               if(ticket != g_lastTicket)
               {
                  g_lastTicket = ticket;
                  g_lastEntryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
                  g_lastEntryTime = (datetime)PositionGetInteger(POSITION_TIME);
                  g_lastVolume = PositionGetDouble(POSITION_VOLUME);
                  Print("[INFO] New position opened: ", ticket);
               }
               break;
            }
         }
      }
   }
   else
   {
      g_hasPosition = false;
   }
   
   //--- Trading logic (if NOT using timer)
   if(!Inp_UseTimer)
      ExecuteTradingLogic();
}

//+------------------------------------------------------------------+
//| TRADE EVENT                                                      |
//+------------------------------------------------------------------+
void OnTrade()
{
   if(CheckPointer(g_reporter) == POINTER_INVALID) return;
   // New position opening is already handled in OnTick
   // Keep for additional logic if needed
}

//+------------------------------------------------------------------+
//| TIMER EVENT                                                      |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(CheckPointer(g_reporter) == POINTER_INVALID) return;
   
   // Check rollover in timer as well
   g_reporter.CheckRollover();
   
   if(Inp_UseTimer)
      ExecuteTradingLogic();
}

//+------------------------------------------------------------------+
//| MAIN TRADING LOGIC (PUT YOUR STRATEGY HERE)                      |
//+------------------------------------------------------------------+
void ExecuteTradingLogic()
{
   //--- Check for enough bars
   if(Bars(_Symbol, _Period) < Inp_SlowMA) return;
   
   //--- Get indicator values (example: moving averages)
   double fastMA[], slowMA[];
   ArraySetAsSeries(fastMA, true);
   ArraySetAsSeries(slowMA, true);
   
   if(CopyBuffer(g_handleFastMA, 0, 0, 3, fastMA) < 3) return;
   if(CopyBuffer(g_handleSlowMA, 0, 0, 3, slowMA) < 3) return;
   
   bool buyCondition  = (fastMA[1] > slowMA[1] && fastMA[2] <= slowMA[2]);
   bool sellCondition = (fastMA[1] < slowMA[1] && fastMA[2] >= slowMA[2]);
   
   //--- ============================================================
   //--- PUT YOUR TRADING LOGIC HERE (replace the example)
   //--- ============================================================
   
   // If position exists, close it if condition changes
   if(g_hasPosition && !g_waitingForClose)
   {
      bool shouldClose = false;
      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      
      if(posType == POSITION_TYPE_BUY && sellCondition)
         shouldClose = true;
      else if(posType == POSITION_TYPE_SELL && buyCondition)
         shouldClose = true;
      
      if(shouldClose && g_lastTicket > 0)
      {
         if(g_trade.PositionClose(g_lastTicket))
         {
            Print("[INFO] Position closed by signal. Ticket: ", g_lastTicket);
            g_waitingForClose = true;
            g_hasPosition = false;
         }
         else
         {
            Print("[ERROR] Failed to close position: ", g_trade.ResultRetcode());
            if(g_trade.ResultRetcode() == 10008)
               g_reporter.OnOrderRejected("ClosePosition", g_trade.ResultRetcode(), "Rejected by broker");
         }
      }
   }
   
   // Open new position if no position
   if(!g_hasPosition && !g_waitingForClose)
   {
      if(buyCondition)
      {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double sl = ask - Inp_StopLoss * _Point;
         double tp = ask + Inp_TakeProfit * _Point;
         
         if(g_trade.Buy(Inp_LotSize, _Symbol, ask, sl, tp))
         {
            Print("[INFO] BUY order sent: ", g_trade.ResultOrder());
            g_lastTicket = g_trade.ResultOrder();
            g_lastEntryPrice = ask;
            g_lastEntryTime = TimeCurrent();
            g_hasPosition = true;
         }
         else
         {
            Print("[ERROR] Buy failed: ", g_trade.ResultRetcode());
            if(g_trade.ResultRetcode() == 10008)
               g_reporter.OnOrderRejected("BuyOrder", g_trade.ResultRetcode(), "Rejected by broker");
         }
      }
      else if(sellCondition)
      {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double sl = bid + Inp_StopLoss * _Point;
         double tp = bid - Inp_TakeProfit * _Point;
         
         if(g_trade.Sell(Inp_LotSize, _Symbol, bid, sl, tp))
         {
            Print("[INFO] SELL order sent: ", g_trade.ResultOrder());
            g_lastTicket = g_trade.ResultOrder();
            g_lastEntryPrice = bid;
            g_lastEntryTime = TimeCurrent();
            g_hasPosition = true;
         }
         else
         {
            Print("[ERROR] Sell failed: ", g_trade.ResultRetcode());
            if(g_trade.ResultRetcode() == 10008)
               g_reporter.OnOrderRejected("SellOrder", g_trade.ResultRetcode(), "Rejected by broker");
         }
      }
   }
}

//+------------------------------------------------------------------+
//| HELPER: Report a manual health alert                             |
//+------------------------------------------------------------------+
void ReportHealthAlert(string problemType, string details, string severity = "high")
{
   if(CheckPointer(g_reporter) != POINTER_INVALID)
      g_reporter.ReportHealthAlert(problemType, details, severity);
}
//+------------------------------------------------------------------+