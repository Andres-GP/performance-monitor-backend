// TestStrategy.cs
using System;
using System.ComponentModel.DataAnnotations;
using System.Windows.Media;
using NinjaTrader.NinjaScript.Indicators;
using NinjaTrader.NinjaScript.Strategies;

namespace NinjaTrader.NinjaScript.Strategies
{
    public class TestStrategy : HealthMonitor
    {
        private SMA smaFast;
        private SMA smaSlow;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "TestStrategy";
                Description = "MA Crossover with full health & performance monitoring.";
                Fast = 10;
                Slow = 25;
                Quantity = 1;
                StopTicks = 10;
                TargetTicks = 20;
                Calculate = Calculate.OnBarClose;
                IsInstantiatedOnEachOptimizationIteration = false;
                MaxBarsWithoutTrade = 50;
                EnableInactivityAlert = true;
                RolloverAlertDays = 100;  
            }
            else if (State == State.DataLoaded)
            {
                smaFast = SMA(Fast);
                smaSlow = SMA(Slow);
                smaFast.Plots[0].Brush = Brushes.Goldenrod;
                smaSlow.Plots[0].Brush = Brushes.SeaGreen;
                AddChartIndicator(smaFast);
                AddChartIndicator(smaSlow);
            }
            base.OnStateChange();
        }

        protected override void OnBarUpdate()
        {
            base.OnBarUpdate();

            if (CurrentBar < BarsRequiredToTrade) return;

            SetStopLoss(CalculationMode.Ticks, StopTicks);
            SetProfitTarget(CalculationMode.Ticks, TargetTicks);

            if (CrossAbove(smaFast, smaSlow, 1))
                EnterLong(Quantity, "LongEntry");
            else if (CrossBelow(smaFast, smaSlow, 1))
                EnterShort(Quantity, "ShortEntry");
        }

        [Range(1, int.MaxValue)]
        [NinjaScriptProperty]
        [Display(Name = "Fast", Order = 1, GroupName = "Indicators")]
        public int Fast { get; set; }

        [Range(1, int.MaxValue)]
        [NinjaScriptProperty]
        [Display(Name = "Slow", Order = 2, GroupName = "Indicators")]
        public int Slow { get; set; }

        [Range(1, int.MaxValue)]
        [NinjaScriptProperty]
        [Display(Name = "Quantity", Order = 3, GroupName = "Order Management")]
        public int Quantity { get; set; }

        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Stop Loss (ticks)", Order = 4, GroupName = "Order Management")]
        public int StopTicks { get; set; }

        [Range(1, 100)]
        [NinjaScriptProperty]
        [Display(Name = "Take Profit (ticks)", Order = 5, GroupName = "Order Management")]
        public int TargetTicks { get; set; }
    }
}