namespace TSScoringPlugin.Handshake
{
    /// <summary>
    /// Phase D1 - application-level constants of the Caller. Only the two Tick-age thresholds of the DrivingActive state live here
    /// (Caller\src\DrivingActivityState.cs). No process, path, event or object definition belongs in this file yet.
    ///
    /// Measured basis (Phase D1-OBS, BVE5 and BVE6): the Caller's Tick runs at about 59-60 Hz and keeps running during Pause; the Tick age at the
    /// moment DrivingActive became ON was 1-14 ms. While a scenario was being driven, BVE stopped the Tick for 1062-1118 ms three times
    /// (a UI operation before the scenario was closed); a 1000 ms limit turned DrivingActive OFF and ON again, 2000 ms does not.
    /// </summary>
    internal static class AppProtocol
    {
        /// <summary>OFF -> ON needs the last Tick to be at most this old (inclusive).</summary>
        public const int TickFreshOnMs = 250;

        /// <summary>ON -> OFF (soft) happens only when the last Tick is MORE than this old; exactly this age keeps ON.</summary>
        public const int TickStaleOffMs = 2000;
    }
}
