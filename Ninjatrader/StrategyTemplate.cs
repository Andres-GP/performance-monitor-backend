// StrategyTemplate.cs
using System;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;

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
                Name = "StrategyTemplate";
                Description = "Your strategy description.";

                // --- Trading parameters ---
                Quantity = 1;
                StopTicks = 10;
                TargetTicks = 20;

                // --- Health monitoring settings (optional) ---
                MaxBarsWithoutTrade = 50;      // 0 = disable inactivity alert
                EnableInactivityAlert = true;

                // --- Technical settings ---
                Calculate = Calculate.OnBarClose;
                IsInstantiatedOnEachOptimizationIteration = false;
            }
            else if (State == State.DataLoaded)
            {
                // Initialize indicators
                // mySMA = SMA(20);
                // AddChartIndicator(mySMA);
            }
            base.OnStateChange();
        }

        // ================================ MAIN TRADING LOGIC ================================
        protected override void OnBarUpdate()
        {
            if (CurrentBar < BarsRequiredToTrade) return;

            // Optional: Set stop loss and take profit
            // SetStopLoss(CalculationMode.Ticks, StopTicks);
            // SetProfitTarget(CalculationMode.Ticks, TargetTicks);

            // ==================== YOUR CODE HERE ====================
            /*
            if (BuyCondition)
                EnterLong(Quantity, "LongEntry");

            if (SellCondition)
                EnterShort(Quantity, "ShortEntry");

            if (ExitLongCondition)
                ExitLong("ExitLong", "LongEntry");

            if (ExitShortCondition)
                ExitShort("ExitShort", "ShortEntry");
            */
            // ========================================================
        }

        // ================================ UI-EDITABLE PARAMETERS ================================
        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Quantity", Order = 1, GroupName = "Order Management")]
        public int Quantity { get; set; }

        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Stop Loss (ticks)", Order = 2, GroupName = "Order Management")]
        public int StopTicks { get; set; }

        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Take Profit (ticks)", Order = 3, GroupName = "Order Management")]
        public int TargetTicks { get; set; }

        // Add your own parameters here
        // [Range(1, 50)]
        // [NinjaScriptProperty]
        // [Display(Name = "My Period", Order = 4, GroupName = "Custom")]
        // public int MyPeriod { get; set; }
    }
}