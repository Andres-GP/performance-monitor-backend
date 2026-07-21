//+------------------------------------------------------------------+
//|                                              PerformanceReporter.mqh |
//|                   Base class for reporting to backend from MT5     |
//|                   FIXES: Quantity, Date format, Heartbeat         |
//+------------------------------------------------------------------+
#property copyright "AlphaCapital"
#property version   "1.10"

#include <Trade/Trade.mqh>

//+------------------------------------------------------------------+
//| Class that handles communication with the backend                 |
//+------------------------------------------------------------------+
class PerformanceReporter
{
private:
   string            m_backendUrl;
   string            m_authToken;
   string            m_strategyId;
   string            m_strategyName;
   string            m_instrument;
   string            m_timeframe;
   string            m_platform;
   int               m_sizing;           // Contract size (lot * 100)
   string            m_dataType;
   bool              m_startReported;    // Flag to ensure strategy is registered before heartbeat
   int               m_barsWithoutTrade;
   bool              m_inactivityAlertSent;
   int               m_maxBarsWithoutTrade;
   bool              m_enableInactivityAlert;
   int               m_rolloverAlertDays;

   //--- Internal method to send POST requests
   string            SendPostRequest(string endpoint, string jsonPayload);
   
   //--- Helper to format datetime in ISO 8601
   string            FormatISODate(datetime dt);

public:
                     PerformanceReporter(string backendUrl, string authToken, string strategyName, string instrument, string timeframe, int sizing, string dataType);
                    ~PerformanceReporter();

   //--- Main methods
   void              ReportStrategyStarted();
   void              ReportTradeClosed(ulong ticket, string symbol, double entryPrice, double exitPrice, double volume, double profit, datetime entryTime, datetime exitTime, double commission, ENUM_POSITION_TYPE positionType);
   void              ReportHealthAlert(string problemType, string details, string severity = "high");
   void              ReportCapital(double capital, string currency = "USD");
   void              SendHeartbeat();
   void              CheckRollover();

   //--- Monitoring methods
   void              OnBarUpdate(int barsTotal);
   void              OnOrderRejected(string orderName, int errorCode, string comment);
   void              OnOrderFrozen(string orderName, datetime orderTime);
   void              OnPartialFill(string orderName, int requested, int filled);
   void              OnConnectionLost();

   //--- Configuration
   void              SetMaxBarsWithoutTrade(int bars) { m_maxBarsWithoutTrade = bars; }
   void              EnableInactivityAlert(bool enable) { m_enableInactivityAlert = enable; }
   void              SetRolloverAlertDays(int days) { m_rolloverAlertDays = days; }
};

//+------------------------------------------------------------------+
//| Constructor                                                       |
//+------------------------------------------------------------------+
PerformanceReporter::PerformanceReporter(string backendUrl, string authToken, string strategyName, string instrument, string timeframe, int sizing, string dataType)
   : m_backendUrl(backendUrl),
     m_authToken(authToken),
     m_strategyName(strategyName),
     m_instrument(instrument),
     m_timeframe(timeframe),
     m_sizing(sizing),
     m_dataType(dataType),
     m_startReported(false),
     m_barsWithoutTrade(0),
     m_inactivityAlertSent(false),
     m_maxBarsWithoutTrade(50),
     m_enableInactivityAlert(true),
     m_rolloverAlertDays(60)
{
   m_platform = "MT5";
   // Generate a unique ID combining timestamp + strategy name
   m_strategyId = IntegerToString(TimeCurrent()) + "_" + strategyName;
}

//+------------------------------------------------------------------+
//| Destructor                                                        |
//+------------------------------------------------------------------+
PerformanceReporter::~PerformanceReporter()
{
}

//+------------------------------------------------------------------+
//| Helper: Format datetime to ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)      |
//+------------------------------------------------------------------+
string PerformanceReporter::FormatISODate(datetime dt)
{
   MqlDateTime dtStruct;
   TimeToStruct(dt, dtStruct);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                       dtStruct.year,
                       dtStruct.mon,
                       dtStruct.day,
                       dtStruct.hour,
                       dtStruct.min,
                       dtStruct.sec);
}

//+------------------------------------------------------------------+
//| Send POST request to backend                                      |
//+------------------------------------------------------------------+
string PerformanceReporter::SendPostRequest(string endpoint, string jsonPayload)
{
   string url = m_backendUrl + endpoint;
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + m_authToken + "\r\n";
   char postData[];
   char resultData[];
   string resultHeaders;
   int res;

   int dataSize = StringToCharArray(jsonPayload, postData) - 1;
   if(dataSize < 0)
   {
      Print("[ERROR] Invalid JSON payload");
      return "";
   }

   ResetLastError();
   res = WebRequest("POST", url, headers, 5000, postData, resultData, resultHeaders);

   if(res == -1)
   {
      Print("[ERROR] WebRequest error: ", GetLastError());
      return "";
   }

   return CharArrayToString(resultData);
}

//+------------------------------------------------------------------+
//| Report strategy started                                           |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportStrategyStarted()
{
   if(m_startReported) return;
   m_startReported = true;

   string endpoint = "/strategies/start";
   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\","
      "\"name\":\"%s\","
      "\"instrument\":\"%s\","
      "\"instrument_type\":\"Future\","
      "\"timeframe\":\"%s\","
      "\"data_type\":\"%s\","
      "\"platform\":\"%s\","
      "\"sizing\":%d,"
      "\"start_date\":\"%s\","
      "\"state\":\"Running\""
      "}",
      m_strategyId,
      m_strategyName,
      m_instrument,
      m_timeframe,
      m_dataType,
      m_platform,
      m_sizing,
      FormatISODate(TimeCurrent())   // ✅ FIX 2: ISO 8601 date format
   );
   Print("[INFO] Reporting strategy started: ", m_strategyName);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Report a closed trade (CORRECTED: quantity as double, ISO date) |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportTradeClosed(
   ulong ticket,
   string symbol,
   double entryPrice,
   double exitPrice,
   double volume,                     // Actual position volume (e.g., 0.1 lots)
   double profit,
   datetime entryTime,
   datetime exitTime,
   double commission,
   ENUM_POSITION_TYPE positionType
)
{
   string endpoint = "/trades";

   // ✅ FIX 1: Use actual volume (not 0). Send as double to preserve decimals.
   // If you prefer to send in contracts, multiply by 100 (since 0.1 lot = 10 contracts)
   // Here we send as lot size (e.g., 0.1). Adjust if your backend expects contracts.
   double quantity = volume;   // Send as decimal (e.g., 0.1). To send as contracts: volume * 100

   // ✅ FIX 2: Use ISO 8601 date format
   string entryTimeStr = FormatISODate(entryTime);
   string exitTimeStr = FormatISODate(exitTime);

   // Direction based on actual position type
   string direction = (positionType == POSITION_TYPE_BUY) ? "Long" : "Short";

   // If profit is 0, calculate it from prices (backup)
   double calculatedPnl = (direction == "Long") ? (exitPrice - entryPrice) * quantity : (entryPrice - exitPrice) * quantity;
   if(profit == 0.0)
      profit = calculatedPnl;

   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\","
      "\"instrument\":\"%s\","
      "\"entry_time\":\"%s\","
      "\"exit_time\":\"%s\","
      "\"quantity\":%.2f,"          // ✅ FIX 1: Send as double with 2 decimals
      "\"entry_price\":%.5f,"
      "\"exit_price\":%.5f,"
      "\"pnl\":%.8f,"
      "\"direction\":\"%s\","
      "\"cost\":%.2f"
      "}",
      m_strategyId,
      symbol,
      entryTimeStr,                  // ✅ FIX 2: ISO 8601
      exitTimeStr,                   // ✅ FIX 2: ISO 8601
      quantity,                      // ✅ FIX 1: Actual volume (not 0)
      entryPrice,
      exitPrice,
      profit,
      direction,
      commission
   );
   Print("[INFO] Reporting closed trade: ", ticket, " Direction: ", direction, " Quantity: ", quantity, " PnL: ", profit);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Report a health alert                                             |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportHealthAlert(string problemType, string details, string severity = "high")
{
   string endpoint = "/alerts";
   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\","
      "\"timestamp\":\"%s\","
      "\"problem_type\":\"%s\","
      "\"details\":\"%s\","
      "\"severity\":\"%s\""
      "}",
      m_strategyId,
      FormatISODate(TimeCurrent()),   // ✅ FIX 2: ISO 8601
      problemType,
      details,
      severity
   );
   Print("[WARNING] Sending health alert: ", problemType);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Report account capital                                            |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportCapital(double capital, string currency = "USD")
{
   string endpoint = "/capital/report";
   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\","
      "\"account_type\":\"%s\","
      "\"capital\":%.2f,"
      "\"currency\":\"%s\""
      "}",
      m_strategyId,
      (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO) ? "demo" : "real",
      capital,
      currency
   );
   Print("[INFO] Reporting capital: ", capital, " ", currency);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Send heartbeat to backend (FIX 3: only if strategy started)      |
//+------------------------------------------------------------------+
void PerformanceReporter::SendHeartbeat()
{
   // ✅ FIX 3: Only send heartbeat if strategy has been reported as started
   if(!m_startReported)
   {
      Print("[DEBUG] Heartbeat skipped: strategy not yet reported as started.");
      return;
   }
   
   string endpoint = "/heartbeat";
   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\""
      "}",
      m_strategyId
   );
   Print("[DEBUG] Sending heartbeat");
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Check contract rollover                                           |
//+------------------------------------------------------------------+
void PerformanceReporter::CheckRollover()
{
   if(m_rolloverAlertDays <= 0) return;

   datetime expiration = SymbolInfoInteger(_Symbol, SYMBOL_EXPIRATION_TIME);
   if(expiration > 0)
   {
      int daysLeft = (int)((expiration - TimeCurrent()) / 86400);
      if(daysLeft <= m_rolloverAlertDays && daysLeft > 0)
      {
         ReportHealthAlert("Contract Rollover",
            StringFormat("Contract %s expires in %d days. Please rollover.", _Symbol, daysLeft));
         Print("[INFO] Rollover alert: ", daysLeft, " days left for ", _Symbol);
      }
   }
}

//+------------------------------------------------------------------+
//| Monitoring: called on each new bar                               |
//+------------------------------------------------------------------+
void PerformanceReporter::OnBarUpdate(int barsTotal)
{
   if(!m_enableInactivityAlert || m_maxBarsWithoutTrade <= 0) return;

   if(PositionsTotal() > 0)
   {
      m_barsWithoutTrade = 0;
      m_inactivityAlertSent = false;
      return;
   }

   m_barsWithoutTrade++;
   if(m_barsWithoutTrade >= m_maxBarsWithoutTrade && !m_inactivityAlertSent)
   {
      ReportHealthAlert("Inactive strategy",
         StringFormat("No trade generated in the last %d bars.", m_maxBarsWithoutTrade));
      m_inactivityAlertSent = true;
   }
}

//+------------------------------------------------------------------+
//| Monitoring: order rejected                                        |
//+------------------------------------------------------------------+
void PerformanceReporter::OnOrderRejected(string orderName, int errorCode, string comment)
{
   ReportHealthAlert("Order rejected",
      StringFormat("Order %s rejected. Error: %d, Comment: %s", orderName, errorCode, comment));
}

//+------------------------------------------------------------------+
//| Monitoring: order frozen                                          |
//+------------------------------------------------------------------+
void PerformanceReporter::OnOrderFrozen(string orderName, datetime orderTime)
{
   int seconds = (int)(TimeCurrent() - orderTime);
   ReportHealthAlert("Frozen order",
      StringFormat("Order %s has been active for %d seconds. Cancelling.", orderName, seconds));
}

//+------------------------------------------------------------------+
//| Monitoring: partial fill                                          |
//+------------------------------------------------------------------+
void PerformanceReporter::OnPartialFill(string orderName, int requested, int filled)
{
   ReportHealthAlert("Partial fill",
      StringFormat("Order %s: requested %d, filled %d. Remaining part not managed.", orderName, requested, filled));
}

//+------------------------------------------------------------------+
//| Monitoring: connection lost                                       |
//+------------------------------------------------------------------+
void PerformanceReporter::OnConnectionLost()
{
   ReportHealthAlert("Connection lost", "Connection to broker/data lost. Strategy will not send orders.");
}

//+------------------------------------------------------------------+