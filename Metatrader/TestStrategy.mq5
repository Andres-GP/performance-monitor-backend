//+------------------------------------------------------------------+
//|                                                TestStrategy.mq5  |
//|                   Test strategy with heartbeat + rollover        |
//|                   UPDATED: Uses corrected PerformanceReporter    |
//+------------------------------------------------------------------+
#property copyright "AlphaCapital"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include <PerformanceReporter.mqh>   // ✅ Use the corrected version above

//--- Input parameters
input string   Inp_BackendUrl      = "https://laxative-buckskin-gyration.ngrok-free.dev";
input string   Inp_AuthToken       = "6d84e658780b073a7a66643135247494094bb63d0474b558c55fe002ce296920";
input double   Inp_LotSize         = 0.1;            // Position size in lots (0.1 = 1 mini lot)
input int      Inp_TimerSeconds    = 30;
input int      Inp_MagicNumber     = 1000;
input bool     Inp_EnableInactivity = true;
input int      Inp_RolloverAlertDays = 60;   // Days before expiry

//--- Global variables
PerformanceReporter *g_reporter = NULL;
CTrade            g_trade;
ulong             g_lastTicket = 0;
double            g_entryPrice = 0;
datetime          g_entryTime = 0;
int               g_barsCount = 0;
bool              g_hasPosition = false;

//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   string accountType = (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO) ? "Simulation" : "Real";
   
   g_trade.SetExpertMagicNumber(Inp_MagicNumber);
   g_trade.SetDeviationInPoints(10);
   
   g_reporter = new PerformanceReporter(
      Inp_BackendUrl,
      Inp_AuthToken,
      "TestStrategyMT5",
      Symbol(),
      EnumToString(Period()),
      (int)(Inp_LotSize * 100),   // Sizing in contracts (e.g., 10 contracts for 0.1 lot)
      accountType
   );
   
   if(CheckPointer(g_reporter) != POINTER_INVALID)
   {
      g_reporter.SetMaxBarsWithoutTrade(50);
      g_reporter.EnableInactivityAlert(Inp_EnableInactivity);
      g_reporter.SetRolloverAlertDays(Inp_RolloverAlertDays);
      g_reporter.ReportStrategyStarted();
      
      // Force rollover check immediately
      g_reporter.CheckRollover();
      
      double capital = AccountInfoDouble(ACCOUNT_BALANCE);
      g_reporter.ReportCapital(capital, AccountInfoString(ACCOUNT_CURRENCY));
      Print("[INFO] EA initialized.");
      EventSetTimer(Inp_TimerSeconds);
      return(INIT_SUCCEEDED);
   }
   else
   {
      Print("[ERROR] Failed to create reporter.");
      return(INIT_FAILED);
   }
}

//+------------------------------------------------------------------+
//| Deinitialization                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(CheckPointer(g_reporter) != POINTER_INVALID)
   {
      delete g_reporter;
      g_reporter = NULL;
   }
}

//+------------------------------------------------------------------+
//| Tick                                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   if(CheckPointer(g_reporter) == POINTER_INVALID) return;
   
   g_reporter.CheckRollover();
   
   int currentBars = Bars(_Symbol, _Period);
   if(currentBars != g_barsCount && currentBars > 0)
   {
      g_barsCount = currentBars;
      g_reporter.OnBarUpdate(g_barsCount);
   }
}

//+------------------------------------------------------------------+
//| Trade                                                            |
//+------------------------------------------------------------------+
void OnTrade()
{
   if(CheckPointer(g_reporter) == POINTER_INVALID) return;
   
   bool found = false;
   if(PositionsTotal() > 0)
   {
      for(int i = 0; i < PositionsTotal(); i++)
      {
         ulong ticket = PositionGetTicket(i);
         if(PositionSelectByTicket(ticket))
         {
            if(PositionGetInteger(POSITION_MAGIC) == Inp_MagicNumber)
            {
               found = true;
               if(ticket != g_lastTicket)
               {
                  g_lastTicket = ticket;
                  g_entryPrice = PositionGetDouble(POSITION_PRICE_OPEN);
                  g_entryTime = (datetime)PositionGetInteger(POSITION_TIME);
                  Print("[INFO] New position opened: ", ticket);
                  g_hasPosition = true;
               }
               break;
            }
         }
      }
   }
   if(!found)
   {
      g_hasPosition = false;
      g_lastTicket = 0;
   }
}

//+------------------------------------------------------------------+
//| Timer                                                            |
//+------------------------------------------------------------------+
void OnTimer()
{
   if(CheckPointer(g_reporter) == POINTER_INVALID) return;
   
   // Heartbeat every 30 seconds (now only sent if strategy started)
   g_reporter.SendHeartbeat();
   
   g_reporter.CheckRollover();
   
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ask <= 0 || bid <= 0) return;
   
   // Close existing position
   if(g_hasPosition && g_lastTicket > 0)
   {
      if(PositionSelectByTicket(g_lastTicket))
      {
         if(g_trade.PositionClose(g_lastTicket))
         {
            Print("[INFO] Trade CLOSED. Ticket: ", g_lastTicket);
            
            double closePrice = g_trade.ResultPrice();
            if(closePrice == 0)
               closePrice = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? bid : ask;
            
            ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
            
            g_reporter.ReportTradeClosed(
               g_lastTicket,
               PositionGetString(POSITION_SYMBOL),
               g_entryPrice,
               closePrice,
               PositionGetDouble(POSITION_VOLUME),   // ✅ Actual volume (e.g., 0.1)
               0.0,
               g_entryTime,
               TimeCurrent(),
               0.0,
               posType
            );
            g_hasPosition = false;
            g_lastTicket = 0;
         }
         else
         {
            if(!PositionSelectByTicket(g_lastTicket))
            {
               Print("[INFO] Position already closed.");
               g_hasPosition = false;
               g_lastTicket = 0;
            }
            else
            {
               Print("[ERROR] Close failed: ", g_trade.ResultRetcode());
            }
         }
      }
      else
      {
         g_hasPosition = false;
         g_lastTicket = 0;
      }
      return;
   }
   
   // Open new position (random Long/Short)
   if(!g_hasPosition)
   {
      bool buy = (MathRand() % 2 == 0);
      if(buy)
      {
         if(g_trade.Buy(Inp_LotSize, _Symbol, ask, 0, 0))
         {
            Print("[INFO] BUY Order opened. Ticket: ", g_trade.ResultOrder());
            g_lastTicket = g_trade.ResultOrder();
            g_entryPrice = ask;
            g_entryTime = TimeCurrent();
            g_hasPosition = true;
         }
         else
         {
            Print("[ERROR] Buy failed: ", g_trade.ResultRetcode());
         }
      }
      else
      {
         if(g_trade.Sell(Inp_LotSize, _Symbol, bid, 0, 0))
         {
            Print("[INFO] SELL Order opened. Ticket: ", g_trade.ResultOrder());
            g_lastTicket = g_trade.ResultOrder();
            g_entryPrice = bid;
            g_entryTime = TimeCurrent();
            g_hasPosition = true;
         }
         else
         {
            Print("[ERROR] Sell failed: ", g_trade.ResultRetcode());
         }
      }
   }
}
//+------------------------------------------------------------------+