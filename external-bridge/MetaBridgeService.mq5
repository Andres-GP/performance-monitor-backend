//+------------------------------------------------------------------+
//|                                          MT5_Bridge_Service.mq5  |
//|                                    Signal Engine Bridge Service  |
//|                                            HTTP Polling (no DLL) |
//+------------------------------------------------------------------+
#property copyright "Signal Engine"
#property version   "1.00"
#property strict

input string   ApiUrl            = "https://laxative-buckskin-gyration.ngrok-free.dev/get_next_order";
input int      PollingIntervalMs = 1000;
input bool     debug_mode        = true;

//+------------------------------------------------------------------+
void OnStart()
{
   Print("MT5 Bridge Service: started.");
   Print("URL: ", ApiUrl);
   Print("Polling interval: ", PollingIntervalMs, " ms");

   while(!IsStopped())
   {
      string headers = "";
      char postData[];
      char resultData[];
      string resultHeaders;

      int res = WebRequest("GET", ApiUrl, headers, 5000, postData, resultData, resultHeaders);

      if(res == 200)
      {
         string json = CharArrayToString(resultData);
         if(debug_mode) Print("Response received: ", json);

         string symbol = "";
         string action = "";
         double volume = 0.0;

         int posSym = StringFind(json, "\"symbol\":\"") + 10;
         if(posSym > 9)
         {
            int endSym = StringFind(json, "\"", posSym);
            symbol = StringSubstr(json, posSym, endSym - posSym);
         }

         int posAct = StringFind(json, "\"action\":\"") + 10;
         if(posAct > 9)
         {
            int endAct = StringFind(json, "\"", posAct);
            action = StringSubstr(json, posAct, endAct - posAct);
         }

         int posVol = StringFind(json, "\"volume\":") + 9;
         if(posVol > 8)
         {
            int endVol = StringFind(json, ",", posVol);
            if(endVol == -1) endVol = StringFind(json, "}", posVol);
            string volStr = StringSubstr(json, posVol, endVol - posVol);
            volume = StringToDouble(volStr);
         }

         if(symbol != "" && action != "" && volume > 0)
         {
            Print("Order received: ", action, " ", symbol, " ", volume);
            SendOrder(symbol, action, volume);
         }
      }
      else if(res != 204)
      {
         static int errCount = 0;
         if(errCount++ % 10 == 0)
            Print("WebRequest error (code ", res, "). Check URL and permissions.");
      }

      Sleep(PollingIntervalMs);
   }

   Print("MT5 Bridge Service: stopped.");
}

//+------------------------------------------------------------------+
void SendOrder(string symbol, string action, double volume)
{
   ENUM_ORDER_TYPE order_type = (action == "buy") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   MqlTradeRequest request = {};
   MqlTradeResult  result = {};
   request.action   = TRADE_ACTION_DEAL;
   request.symbol   = symbol;
   request.volume   = volume;
   request.type     = order_type;
   request.deviation = 10;
   request.type_filling = ORDER_FILLING_IOC;

   if(OrderSend(request, result))
      Print("Order executed. Ticket: ", result.order);
   else
      Print("Failed to send order. Code: ", GetLastError());
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("MT5 Bridge Service: finished. Reason: ", reason);
}
//+------------------------------------------------------------------+
