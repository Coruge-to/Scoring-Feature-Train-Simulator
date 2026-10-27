using System;
using System.Collections.Generic;
using System.Globalization;
using TSScoringPlugin.Telemetry;

// ============================================================================
// PHASE SI-R2.2-S2b test fixture (NOT a product file: it is compiled only by Test-OfficialTargetWireS2B.ps1, next to TelemetryTestFixture.cs).
//   FakeOfficialApi       the read surface of the official next-station target (ILegacyOfficialTargetApi) with values the test sets between two Ticks
//   OfficialHarness       a LegacyTelemetrySession over the FakeApi of the L3 fixture, with (or without) the official-target surface wired
//   OfficialWireProbe     the shared wire helper and the reader core with primitive arguments, for the PowerShell test
// C# 5 compatible on purpose (the Windows PowerShell 5.1 compiler). The classes are public with explicit interface members, like FakeApi: the internal product types never leak.
// ============================================================================
namespace TsScoringLegacyTelemetryTests
{
    public class FakeOfficialApi : ILegacyOfficialTargetApi
    {
        public bool Null = false;               // ReadOfficialTarget returns null
        public bool HostNull = false;
        public bool CursorOk = true;
        public int Cursor = -1;
        public bool CountOk = true;
        public int Count = 0;
        public bool NextOk = true;
        public double Location = 0.0;
        public double MarginMin = 0.0;
        public double MarginMax = 0.0;
        public bool Throw = false;              // ReadOfficialTarget throws
        public int Calls = 0;

        OfficialTargetReading ILegacyOfficialTargetApi.ReadOfficialTarget()
        {
            Calls++;
            if (Throw) { throw new InvalidOperationException("scripted failure of the official target read"); }
            if (Null) { return null; }
            OfficialTargetReading r = new OfficialTargetReading();
            r.HostNull = HostNull;
            r.CursorOk = CursorOk;
            r.Cursor = Cursor;
            r.CountOk = CountOk;
            r.Count = Count;
            r.NextOk = NextOk;
            r.NextLocation = Location;
            r.MarginMin = MarginMin;
            r.MarginMax = MarginMax;
            return r;
        }
    }

    /// <summary>Drives a LegacyTelemetrySession the way Harness does (time is a number the test moves), with the official-target surface wired or not.</summary>
    public class OfficialHarness
    {
        public FakeApi Api = new FakeApi();
        public CollectSink Sink = new CollectSink();
        public FakeOfficialApi Official;
        public long Now = 1000;
        public long Seed = 5000000000L;
        private LegacyTelemetrySession session;

        public OfficialHarness(bool wireOfficial)
        {
            if (wireOfficial) { Official = new FakeOfficialApi(); }
            session = new LegacyTelemetrySession(Api, Sink, delegate { return Now; }, delegate { return Seed; }, null, null, null, null, null, Official);
        }

        /// <summary>The nine-argument constructor of the earlier phases: the official surface is not wired at all.</summary>
        public static OfficialHarness WithTheNineArgumentConstructor()
        {
            OfficialHarness h = new OfficialHarness(false);
            h.session = new LegacyTelemetrySession(h.Api, h.Sink, delegate { return h.Now; }, delegate { return h.Seed; }, null, null, null, null, null);
            return h;
        }

        public void Run(int ticks, int stepMs)
        {
            for (int i = 0; i < ticks; i++)
            {
                Now += stepMs;
                Api.TimeMs += stepMs;
                session.OnTick(TimeSpan.FromMilliseconds((double)stepMs));
            }
        }

        public void Dispose() { session.OnDispose(); }
    }

    public static class OfficialWireProbe
    {
        public static string Part(bool isNull, bool hostNull, bool cursorOk, int cursor, bool countOk, int count, bool nextOk, double loc, double marginMin, double marginMax, string listId)
        {
            if (isNull) { return OfficialTargetWire.Part(null, listId); }
            OfficialTargetReading r = new OfficialTargetReading();
            r.HostNull = hostNull;
            r.CursorOk = cursorOk;
            r.Cursor = cursor;
            r.CountOk = countOk;
            r.Count = count;
            r.NextOk = nextOk;
            r.NextLocation = loc;
            r.MarginMin = marginMin;
            r.MarginMax = marginMax;
            return OfficialTargetWire.Part(r, listId);
        }

        public static string Placeholder(string state) { return OfficialTargetWire.Key + ":" + OfficialTargetWire.Placeholder(state); }

        /// <summary>The canonical text of v, or null when it has none.</summary>
        public static string Real(double v)
        {
            string text;
            return OfficialTargetWire.TryReal(v, out text) ? text : null;
        }

        public static string Key { get { return OfficialTargetWire.Key; } }

        public static int Version { get { return OfficialTargetWire.Version; } }

        /// <summary>
        /// The reader core over a scripted host. mode: ok, null-stations, throw-stations, throw-cursor, throw-count, throw-station. Returns
        /// "part|stationReads|lastIndex|error" where stationReads counts the calls of the station reader and lastIndex is the index it was asked for (-1 = never).
        /// </summary>
        public static string Read(string mode, int cursor, int count, double loc, double marginMin, double marginMax, string listId)
        {
            int stationReads = 0;
            int lastIndex = -1;
            OfficialTargetHost host = new OfficialTargetHost();
            host.GetStations = delegate
            {
                if (mode == "throw-stations") { throw new InvalidOperationException("stations"); }
                if (mode == "null-stations") { return null; }
                return new object();
            };
            host.GetCursor = delegate (object list)
            {
                if (mode == "throw-cursor") { throw new ArgumentException("cursor"); }
                return cursor;
            };
            host.GetCount = delegate (object list)
            {
                if (mode == "throw-count") { throw new NotSupportedException("count"); }
                return count;
            };
            host.ReadStation = delegate (object list, int index)
            {
                stationReads++;
                lastIndex = index;
                if (mode == "throw-station") { throw new IndexOutOfRangeException("station"); }
                OfficialTargetStation s = new OfficialTargetStation();
                s.Location = loc;
                s.MarginMin = marginMin;
                s.MarginMax = marginMax;
                return s;
            };
            OfficialTargetReading r = OfficialTargetReader.Read(host);
            return OfficialTargetWire.Part(r, listId) + "|" + stationReads.ToString(CultureInfo.InvariantCulture) + "|" + lastIndex.ToString(CultureInfo.InvariantCulture) + "|" + r.Error;
        }
    }
}
