// StrategyTemplate.cs
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;
using System.Windows.Media;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class StrategyTemplate : HealthMonitor
    {
        // ================================ INDICATORS ================================
        // private SMA mySMA;

        // ================================ INITIALIZATION ================================
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                // --- Basic strategy information ---
                Name = "StrategyTemplate";
                Description = "Template with full health monitoring and rollover alerts.";

                // --- Trading parameters (adjust as needed) ---
                Quantity = 1;
                StopTicks = 10;
                TargetTicks = 20;

                // --- Health monitoring settings (optional) ---
                MaxBarsWithoutTrade = 50;      // 0 = disable inactivity alert
                EnableInactivityAlert = true;

                // --- Rollover alert (days before expiry) ---
                RolloverAlertDays = 5;         // 5 days before expiry (adjust as needed)

                // --- Technical settings ---
                Calculate = Calculate.OnBarClose;
                IsInstantiatedOnEachOptimizationIteration = false;
            }
            else if (State == State.DataLoaded)
            {
                // --- Initialize indicators (example: SMA) ---
                // mySMA = SMA(20);
                // mySMA.Plots[0].Brush = Brushes.Goldenrod;
                // AddChartIndicator(mySMA);

                // --- Initialize any other indicators here ---
            }
            // ✅ IMPORTANT: Always call base.OnStateChange() for health monitoring & rollover
            base.OnStateChange();
        }

        // ================================ MAIN TRADING LOGIC ================================
        protected override void OnBarUpdate()
        {
            // ✅ IMPORTANT: Call base.OnBarUpdate() for rollover detection to work
            base.OnBarUpdate();

            // --- Wait for enough bars ---
            if (CurrentBar < BarsRequiredToTrade) return;

            // --- Optional: Set stop loss and take profit (if you don't use SetStopLoss/SetProfitTarget inside conditions) ---
            // SetStopLoss(CalculationMode.Ticks, StopTicks);
            // SetProfitTarget(CalculationMode.Ticks, TargetTicks);

            // ==================== YOUR TRADING CODE GOES HERE ====================
            /*
            // Example conditions (replace with your own):
            if (BuyCondition)
                EnterLong(Quantity, "LongEntry");

            if (SellCondition)
                EnterShort(Quantity, "ShortEntry");

            if (ExitLongCondition)
                ExitLong("ExitLong", "LongEntry");

            if (ExitShortCondition)
                ExitShort("ExitShort", "ShortEntry");
            */
            // ======================================================================
        }

        // ================================ UI-EDITABLE PARAMETERS ================================
        // --- Trading parameters ---
        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Quantity", Description = "Number of contracts per order", Order = 1, GroupName = "Order Management")]
        public int Quantity { get; set; }

        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Stop Loss (ticks)", Description = "Stop loss distance in ticks", Order = 2, GroupName = "Order Management")]
        public int StopTicks { get; set; }

        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Take Profit (ticks)", Description = "Take profit distance in ticks", Order = 3, GroupName = "Order Management")]
        public int TargetTicks { get; set; }

        // --- Add your own parameters here ---
        // [Range(1, 50)]
        // [NinjaScriptProperty]
        // [Display(Name = "My Period", Description = "Description of your custom parameter", Order = 4, GroupName = "Indicators")]
        // public int MyPeriod { get; set; }
    }
}