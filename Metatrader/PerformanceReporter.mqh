//+------------------------------------------------------------------+
//|                                              PerformanceReporter.mqh |
//|                   Base class for reporting to backend from MT5    |
//+------------------------------------------------------------------+
#property copyright "AlphaCapital"
#property version   "1.00"
#property strict

//+------------------------------------------------------------------+
//| Class that handles communication with the backend                |
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
   int               m_sizing;
   string            m_dataType;
   bool              m_startReported;
   int               m_barsWithoutTrade;
   bool              m_inactivityAlertSent;
   int               m_maxBarsWithoutTrade;
   bool              m_enableInactivityAlert;

   string            SendPostRequest(string endpoint, string jsonPayload);
   string            FormatISODate(datetime dt);

public:
                     PerformanceReporter(string backendUrl, string authToken, string strategyName, string instrument, string timeframe, int sizing, string dataType);
                    ~PerformanceReporter();

   void              ReportStrategyStarted();
   void              ReportTradeClosed(ulong ticket, string symbol, double entryPrice, double exitPrice, double volume, double profit, datetime entryTime, datetime exitTime, double commission);
   void              ReportHealthAlert(string problemType, string details, string severity = "high");
   void              ReportCapital(double capital, string currency = "USD");
   void              SendHeartbeat();

   void              OnBarUpdate(int barsTotal);
   void              OnOrderRejected(string orderName, int errorCode, string comment);
   void              OnOrderFrozen(string orderName, datetime orderTime);
   void              OnPartialFill(string orderName, int requested, int filled);
   void              OnConnectionLost();

   void              SetMaxBarsWithoutTrade(int bars) { m_maxBarsWithoutTrade = bars; }
   void              EnableInactivityAlert(bool enable) { m_enableInactivityAlert = enable; }
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
     m_enableInactivityAlert(true)
{
   m_platform = "MT5";
   m_strategyId = IntegerToString(TimeCurrent()) + "_" + strategyName;
}

//+------------------------------------------------------------------+
//| Destructor                                                        |
//+------------------------------------------------------------------+
PerformanceReporter::~PerformanceReporter()
{
}

//+------------------------------------------------------------------+
//| Formats a datetime to ISO 8601 string (YYYY-MM-DDTHH:MM:SSZ)     |
//+------------------------------------------------------------------+
string PerformanceReporter::FormatISODate(datetime dt)
{
   MqlDateTime mdt;
   TimeToStruct(dt, mdt);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                       mdt.year, mdt.mon, mdt.day, mdt.hour, mdt.min, mdt.sec);
}

//+------------------------------------------------------------------+
//| Sends a POST request to the backend                              |
//+------------------------------------------------------------------+
string PerformanceReporter::SendPostRequest(string endpoint, string jsonPayload)
{
   string url = m_backendUrl + endpoint;
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + m_authToken + "\r\n";
   char postData[];
   char resultData[];
   string resultHeaders;
   int res;

   // ✅ CORREGIDO: usar StringLen para evitar el terminador nulo
   int dataSize = StringLen(jsonPayload);
   StringToCharArray(jsonPayload, postData, 0, dataSize);

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
//| Reports the strategy start to the backend                        |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportStrategyStarted()
{
   if(m_startReported) return;
   m_startReported = true;

   string endpoint = "/strategies/start";
   string dateStr = FormatISODate(TimeCurrent());
   
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
      dateStr
   );
   Print("[INFO] Reporting strategy start: ", m_strategyName);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Reports a closed trade to the backend                            |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportTradeClosed(ulong ticket, string symbol, double entryPrice, double exitPrice, double volume, double profit, datetime entryTime, datetime exitTime, double commission)
{
   string endpoint = "/trades";
   string direction = (profit >= 0) ? "Long" : "Short";

   string entryStr = FormatISODate(entryTime);
   string exitStr = FormatISODate(exitTime);

   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\","
      "\"instrument\":\"%s\","
      "\"entry_time\":\"%s\","
      "\"exit_time\":\"%s\","
      "\"quantity\":%d,"
      "\"entry_price\":%.5f,"
      "\"exit_price\":%.5f,"
      "\"pnl\":%.2f,"
      "\"direction\":\"%s\","
      "\"cost\":%.2f"
      "}",
      m_strategyId,
      symbol,
      entryStr,
      exitStr,
      (int)volume,
      entryPrice,
      exitPrice,
      profit,
      direction,
      commission
   );
   Print("[INFO] Reporting closed trade: ", ticket);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Reports a health alert to the backend                            |
//+------------------------------------------------------------------+
void PerformanceReporter::ReportHealthAlert(string problemType, string details, string severity = "high")
{
   string endpoint = "/alerts";
   string timestamp = FormatISODate(TimeCurrent());
   
   string payload = StringFormat(
      "{"
      "\"strategy_id\":\"%s\","
      "\"timestamp\":\"%s\","
      "\"problem_type\":\"%s\","
      "\"details\":\"%s\","
      "\"severity\":\"%s\""
      "}",
      m_strategyId,
      timestamp,
      problemType,
      details,
      severity
   );
   Print("[WARNING] Sending health alert: ", problemType);
   SendPostRequest(endpoint, payload);
}

//+------------------------------------------------------------------+
//| Reports the account capital to the backend                       |
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
//| Sends a heartbeat to the backend                                 |
//+------------------------------------------------------------------+
void PerformanceReporter::SendHeartbeat()
{
   if(!m_startReported) return;

   string endpoint = "/heartbeat";
   string payload = StringFormat("{\"strategy_id\":\"%s\"}", m_strategyId);
   Print("[INFO] Sending heartbeat: ", m_strategyId);
   SendPostRequest(endpoint, payload);
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
//| Monitoring: order rejected                                       |
//+------------------------------------------------------------------+
void PerformanceReporter::OnOrderRejected(string orderName, int errorCode, string comment)
{
   ReportHealthAlert("Order rejected", 
      StringFormat("Order %s rejected. Error: %d, Comment: %s", orderName, errorCode, comment));
}

//+------------------------------------------------------------------+
//| Monitoring: frozen order                                         |
//+------------------------------------------------------------------+
void PerformanceReporter::OnOrderFrozen(string orderName, datetime orderTime)
{
   int seconds = (int)(TimeCurrent() - orderTime);
   ReportHealthAlert("Frozen order", 
      StringFormat("Order %s has been active for %d seconds. Cancelling.", orderName, seconds));
}

//+------------------------------------------------------------------+
//| Monitoring: partial fill                                         |
//+------------------------------------------------------------------+
void PerformanceReporter::OnPartialFill(string orderName, int requested, int filled)
{
   ReportHealthAlert("Partial fill", 
      StringFormat("Order %s: requested %d, filled %d. Remaining part not managed.", orderName, requested, filled));
}

//+------------------------------------------------------------------+
//| Monitoring: connection lost                                      |
//+------------------------------------------------------------------+
void PerformanceReporter::OnConnectionLost()
{
   ReportHealthAlert("Connection lost", "Connection to broker/data lost. Strategy will not send orders.");
}
//+------------------------------------------------------------------+