Real data fixtures of the effective station state tests (Stage P1). Both files are copies of the live S-02 run (2026-11-05, Current, TB-G route, scenario iida_sanmpe_tbg_pt4_v1):
  s02_stop_profile_ticks.csv   121 REAL BVE ticks (bve_ms, location_m, speed_kmh, tick_dt_ms) around the stop in the range of the first pair A (TSScoring_VibrationProbe.csv, kind=sample): 16-18 ms apart,
                               speed 0.0030 km/h one tick before the first exact 0.0 (index 72, bve_ms 28903264, 219.5764 m).
  tbg12_station_probe.csv      the 12 stations of the route as the HOST reports them (TSScoring_TurnbackStationProbe.csv): arrival / departure / default / stoppage; the sender's completed values are DERIVED
                               by tests/ts_eff_fixtures.complete_like_sender (a port of Class1.cs:936-968).
